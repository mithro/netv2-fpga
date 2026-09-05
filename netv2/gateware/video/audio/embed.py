"""HDMI audio **embed** core (phase 7c) -- the inverse of phase-7b extract.

Turns audio (PCM samples, an N/CTS pair, and an InfoFrame description) into HDMI
data-island TERC4 characters and inserts them, framed as a proper data island
(preamble + leading guard band + packets + trailing guard band), into the
blanking of a self-timed raw HDMI output stream.

Two layers:

* :class:`AudioIslandEncoder` -- the low-level island serialiser. Given one
  packet (header ``{type, hb1, hb2}`` + four 56-bit subpacket *data* words), it
  computes the header and per-subpacket BCH ECC **serially** with the exact same
  reflected LFSR (:func:`~netv2.gateware.video.audio.parser._bch_step`,
  generator x^8+x^7+x^6+x^4+1) the phase-7b parser uses to *check* it, walks the
  32 data-island characters emitting the header bit on channel-0 bit 2 and the
  subpacket bit-pairs on channels 1/2, TERC4-encodes every nibble, and wraps the
  whole thing in the CTL0101 preamble + data guard bands. Channel-0 nibble bits
  1:0 carry the live HSYNC/VSYNC. The emitted ``(c0, c1, c2)`` 10-bit token
  stream is bit-for-bit what ``hdmi_audio_model.island_stream([packet])``
  produces, so it round-trips straight back through the phase-7b
  ``DecodeTERC4`` + ``HDMIAudioExtract`` de-embed path.

* :class:`AudioEmbedder` -- the CSR-driven front end. A firmware-written PCM
  FIFO feeds Audio Sample Packets; N/CTS and the Audio-InfoFrame fields are
  CSRs; a small scheduler emits, on each island slot, a rotating ACR /
  InfoFrame / ASP so a sink sees clock-regeneration, format and samples.

Everything here runs in the ``pix`` domain (the output pixel clock); the CSR /
FIFO write side is crossed in from ``sys`` with the standard migen CDC.
"""

from litex.soc.interconnect.csr import (
    AutoCSR,
    CSRField,
    CSRStatus,
    CSRStorage,
)
from migen import *
from migen.genlib.cdc import BusSynchronizer
from migen.genlib.fifo import AsyncFIFO

from netv2.gateware.video.audio.parser import _bch_step
from netv2.gateware.video.input.common import control_tokens
from netv2.gateware.video.input.decoding import data_gb_tokens, terc4_tokens

# Packet types (mirror extract.py).
PKT_ACR = 0x01
PKT_ASP = 0x02
PKT_AUDIO_INFOFRAME = 0x84

# Island framing token constants (must match hdmi_audio_model.island_stream).
CTL_ISLAND = control_tokens[1]   # ctl_code 0b0101 -> data-island preamble
DGB = data_gb_tokens[0]          # data-island guard band
DUMMY = terc4_tokens[0]          # the char consumed on GOING_T4 -> TERC4

# Framing lengths (match the model defaults).
N_PREAMBLE = 6
N_LEAD_GB = 2
N_DUMMY = 1
N_PAYLOAD = 32
N_TRAIL_GB = 2
N_TRAIL_CTL = 6

HDR_DATA_CHARS = 24    # header: 24 data bits then 8 ECC bits
SUB_DATA_CHARS = 28    # subpacket: 56 data bits (2/char) then 8 ECC bits


class AudioIslandEncoder(Module):
    """Serialise one data-island packet into a framed TERC4 token stream."""

    def __init__(self):
        # ----- control / packet inputs ------------------------------------
        self.start = Signal()               # pulse to begin (only latched when idle)
        self.hsync = Signal()               # live sync, carried on ch0 nibble bit0
        self.vsync = Signal()               # ... bit1
        self.pkt_type = Signal(8)
        self.hb1 = Signal(8)
        self.hb2 = Signal(8)
        self.sub = [Signal(56) for _ in range(4)]   # subpacket *data* (no ECC)

        # ----- outputs -----------------------------------------------------
        self.busy = Signal()                # high from start until the island ends
        self.stream_valid = Signal()        # high while emitting island tokens
        self.c0 = Signal(10)
        self.c1 = Signal(10)
        self.c2 = Signal(10)
        self.done = Signal()                # 1-cycle pulse when the island finishes

        # # #

        # Packet shift registers (loaded on start).
        hd = Signal(24)                     # header data bits
        he = Signal(8)                      # header ECC LFSR / shift-out
        sd = [Signal(56) for _ in range(4)] # subpacket data bits
        se = [Signal(8) for _ in range(4)]  # subpacket ECC LFSR / shift-out
        hsync_l = Signal()
        vsync_l = Signal()

        cnt = Signal(6)                     # phase counter (max 31)

        # --- current-char TERC4 nibbles (combinational from the registers) ---
        pcnt = cnt                          # during PAYLOAD, cnt is the char index
        hbit = Signal()
        s1 = Signal(4)
        s2 = Signal(4)
        self.comb += hbit.eq(Mux(pcnt < HDR_DATA_CHARS, hd[0], he[0]))
        for k in range(4):
            self.comb += [
                s1[k].eq(Mux(pcnt < SUB_DATA_CHARS, sd[k][0], se[k][0])),
                s2[k].eq(Mux(pcnt < SUB_DATA_CHARS, sd[k][1], se[k][1])),
            ]
        nib0 = Signal(4)
        nib1 = Signal(4)
        nib2 = Signal(4)
        self.comb += [
            nib0.eq(Cat(hsync_l, vsync_l, hbit, C(0, 1))),
            nib1.eq(s1),
            nib2.eq(s2),
        ]
        pay_c0 = Signal(10)
        pay_c1 = Signal(10)
        pay_c2 = Signal(10)
        self.comb += [
            pay_c0.eq(Array(terc4_tokens)[nib0]),
            pay_c1.eq(Array(terc4_tokens)[nib1]),
            pay_c2.eq(Array(terc4_tokens)[nib2]),
        ]

        # --- output token selector (per FSM state) ------------------------
        # sel: 0 idle, 1 preamble, 2 guard band, 3 dummy, 4 payload, 5 trail gb,
        #      6 trail ctl. Idle emits control tokens carrying the live sync.
        sel = Signal(3)
        idle_c0 = Signal(10)
        self.comb += idle_c0.eq(Array(control_tokens)[Cat(self.hsync, self.vsync)])
        self.comb += [
            Case(sel, {
                0: [self.c0.eq(idle_c0), self.c1.eq(control_tokens[0]),
                    self.c2.eq(control_tokens[0])],
                1: [self.c0.eq(CTL_ISLAND), self.c1.eq(CTL_ISLAND),
                    self.c2.eq(CTL_ISLAND)],
                2: [self.c0.eq(DGB), self.c1.eq(DGB), self.c2.eq(DGB)],
                3: [self.c0.eq(DUMMY), self.c1.eq(DUMMY), self.c2.eq(DUMMY)],
                4: [self.c0.eq(pay_c0), self.c1.eq(pay_c1), self.c2.eq(pay_c2)],
                5: [self.c0.eq(DGB), self.c1.eq(DGB), self.c2.eq(DGB)],
                6: [self.c0.eq(CTL_ISLAND), self.c1.eq(CTL_ISLAND),
                    self.c2.eq(CTL_ISLAND)],
            }),
        ]

        # --- payload register advance (only meaningful in PAYLOAD) --------
        def payload_step():
            acts = []
            # header: 1 bit/char, ECC accumulated over chars 0..23 then shifted out
            acts.append(
                If(pcnt < HDR_DATA_CHARS,
                   NextValue(he, _bch_step(he, hd[0])),
                   NextValue(hd, Cat(hd[1:], C(0, 1))),
                ).Else(
                   NextValue(he, Cat(he[1:], C(0, 1))),
                )
            )
            for k in range(4):
                acts.append(
                    If(pcnt < SUB_DATA_CHARS,
                       NextValue(se[k], _bch_step(_bch_step(se[k], sd[k][0]), sd[k][1])),
                       NextValue(sd[k], Cat(sd[k][2:], C(0, 2))),
                    ).Else(
                       NextValue(se[k], Cat(se[k][2:], C(0, 2))),
                    )
                )
            return acts

        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            sel.eq(0),
            If(self.start,
               NextValue(hd, Cat(self.pkt_type, self.hb1, self.hb2)),
               NextValue(he, 0),
               *[NextValue(sd[k], self.sub[k]) for k in range(4)],
               *[NextValue(se[k], 0) for k in range(4)],
               NextValue(hsync_l, self.hsync),
               NextValue(vsync_l, self.vsync),
               NextValue(cnt, 0),
               NextState("PREAMBLE"),
            )
        )
        fsm.act("PREAMBLE",
            self.busy.eq(1), self.stream_valid.eq(1), sel.eq(1),
            If(cnt == (N_PREAMBLE - 1),
               NextValue(cnt, 0), NextState("LEAD_GB"),
            ).Else(NextValue(cnt, cnt + 1))
        )
        fsm.act("LEAD_GB",
            self.busy.eq(1), self.stream_valid.eq(1), sel.eq(2),
            If(cnt == (N_LEAD_GB - 1),
               NextValue(cnt, 0), NextState("DUMMY"),
            ).Else(NextValue(cnt, cnt + 1))
        )
        fsm.act("DUMMY",
            self.busy.eq(1), self.stream_valid.eq(1), sel.eq(3),
            NextValue(cnt, 0), NextState("PAYLOAD"),
        )
        fsm.act("PAYLOAD",
            self.busy.eq(1), self.stream_valid.eq(1), sel.eq(4),
            *payload_step(),
            If(cnt == (N_PAYLOAD - 1),
               NextValue(cnt, 0), NextState("TRAIL_GB"),
            ).Else(NextValue(cnt, cnt + 1))
        )
        fsm.act("TRAIL_GB",
            self.busy.eq(1), self.stream_valid.eq(1), sel.eq(5),
            If(cnt == (N_TRAIL_GB - 1),
               NextValue(cnt, 0), NextState("TRAIL_CTL"),
            ).Else(NextValue(cnt, cnt + 1))
        )
        fsm.act("TRAIL_CTL",
            self.busy.eq(1), self.stream_valid.eq(1), sel.eq(6),
            If(cnt == (N_TRAIL_CTL - 1),
               NextValue(cnt, 0), self.done.eq(1), NextState("IDLE"),
            ).Else(NextValue(cnt, cnt + 1))
        )


# --------------------------------------------------------------------------
# Packet-builder helpers (combinational subpacket / header construction).
# --------------------------------------------------------------------------
def build_asp_subpacket(sample_a, sample_b):
    """56-bit ASP subpacket data from two 24-bit PCM samples (V/U/C/P = 0)."""
    return Cat(sample_a[0:24], C(0, 4), sample_b[0:24], C(0, 4))


def build_acr_subpacket(n, cts):
    """56-bit ACR subpacket data carrying N (20) and CTS (20)."""
    return Cat(
        C(0, 8),                 # PB0
        cts[16:20], C(0, 4),     # PB1: CTS[19:16]
        cts[8:16],               # PB2: CTS[15:8]
        cts[0:8],                # PB3: CTS[7:0]
        n[16:20], C(0, 4),       # PB4: N[19:16]
        n[8:16],                 # PB5: N[15:8]
        n[0:8],                  # PB6: N[7:0]
    )


class AudioEmbedder(Module, AutoCSR):
    """CSR-driven HDMI audio embed front end (``pix`` domain output).

    Wraps :class:`AudioIslandEncoder`. Firmware pushes stereo 24-bit PCM into an
    async FIFO (sys -> pix); N/CTS and the Audio-InfoFrame fields are CSRs. On
    each asserted ``island_slot`` the scheduler emits one packet, rotating
    ACR -> Audio InfoFrame -> Audio Sample Packet so a sink receives clock
    regeneration, format, and samples.
    """

    SAMPLE_FIFO_DEPTH = 256

    def __init__(self, hsync=None, vsync=None, island_slot=None):
        # The island encoder's FSM must run in the pixel-clock domain. It only
        # uses the default (sys) domain internally, so renaming sys -> pix puts
        # the whole encoder in pix. (The round-trip sim instead instantiates
        # AudioIslandEncoder directly under a single clock, so it is unaffected.)
        self.submodules.enc = enc = ClockDomainsRenamer("pix")(AudioIslandEncoder())

        # live sync into the island encoder's ch0 nibbles
        if hsync is not None:
            self.comb += enc.hsync.eq(hsync)
        if vsync is not None:
            self.comb += enc.vsync.eq(vsync)

        # expose the token outputs
        self.c0 = enc.c0
        self.c1 = enc.c1
        self.c2 = enc.c2
        self.stream_valid = enc.stream_valid
        self.busy = enc.busy

        # ----- CSRs (sys domain) ------------------------------------------
        self.control = CSRStorage(fields=[
            CSRField("enable", 1, description="Enable audio-island insertion."),
            CSRField("send_infoframe", 1, reset=1,
                     description="Include the Audio InfoFrame in the rotation."),
            CSRField("send_acr", 1, reset=1,
                     description="Include the ACR packet in the rotation."),
        ])
        self.n = CSRStorage(20, reset=6144, description="ACR N value.")
        self.cts = CSRStorage(20, reset=74250, description="ACR CTS value.")
        self.infoframe = CSRStorage(fields=[
            CSRField("cc", 3, reset=1, description="Channel count (CC)."),
            CSRField("ct", 4, reset=0, description="Coding type (CT)."),
            CSRField("sf", 3, reset=3, description="Sample frequency (SF), 3=48k."),
            CSRField("ss", 2, reset=3, description="Sample size (SS), 3=24-bit."),
            CSRField("ca", 8, reset=0, description="Channel/speaker allocation."),
        ])
        # PCM push: write {left[23:0]} then {right[23:0]} interface. To keep it
        # simple and atomic, firmware writes a 32-bit word carrying one 24-bit
        # sample plus a 1-bit channel select; a stereo pair is two writes.
        self.pcm = CSRStorage(fields=[
            CSRField("sample", 24, description="24-bit PCM sample."),
            CSRField("channel", 1, description="0 = left/A, 1 = right/B."),
            CSRField("we", 1, description="Write strobe (push to FIFO)."),
        ])
        self.status = CSRStatus(fields=[
            CSRField("busy", 1, description="Island encoder busy."),
            CSRField("fifo_readable", 1, description="PCM FIFO has data."),
            CSRField("have_pair", 1, description="A stereo PCM pair is queued."),
        ])
        self.island_count = CSRStatus(32, description="Data islands emitted.")

        # ----- PCM FIFO (sys write -> pix read) ---------------------------
        # Firmware pushes samples in L, R, L, R, ... order (one 24-bit sample per
        # write with we=1); the read side pops them two-at-a-time into a pair.
        fifo = ClockDomainsRenamer({"write": "sys", "read": "pix"})(
            AsyncFIFO(width=24, depth=self.SAMPLE_FIFO_DEPTH))
        self.submodules.pcm_fifo = fifo
        self.comb += [
            fifo.din.eq(self.pcm.fields.sample),
            fifo.we.eq(self.pcm.fields.we & self.pcm.re),
        ]

        # ----- CDC of the config latches into pix ------------------------
        def cdc(sig, width):
            bs = BusSynchronizer(width, "sys", "pix")
            self.submodules += bs
            self.comb += bs.i.eq(sig)
            return bs.o

        n_pix = cdc(self.n.storage, 20)
        cts_pix = cdc(self.cts.storage, 20)
        if_pix = cdc(self.infoframe.storage, 20)     # cc+ct+sf+ss+ca = 3+4+3+2+8
        ctl_pix = cdc(self.control.storage, 3)
        enable = Signal()
        send_if = Signal()
        send_acr = Signal()
        self.comb += [enable.eq(ctl_pix[0]), send_if.eq(ctl_pix[1]),
                      send_acr.eq(ctl_pix[2])]
        cc = if_pix[0:3]
        ct = if_pix[3:7]
        sf = if_pix[7:10]
        ss = if_pix[10:12]
        ca = if_pix[12:20]

        # ----- InfoFrame checksum (pix, combinational) -------------------
        # checksum = -(HB0+HB1+HB2 + PB1 + PB2 + PB4) & 0xFF, with
        # HB0=0x84, HB1=0x01, HB2=0x0A, PB1=cc|ct<<4, PB2=ss|sf<<2, PB4=ca.
        db1 = Signal(8)
        db2 = Signal(8)
        checksum = Signal(8)
        self.comb += [
            db1.eq(Cat(cc, C(0, 1), ct)),
            db2.eq(Cat(ss, sf, C(0, 3))),
            checksum.eq(-(0x84 + 0x01 + 0x0A + db1 + db2 + ca)),
        ]
        if_sub0 = Signal(56)
        self.comb += if_sub0.eq(Cat(
            checksum,                 # PB0
            cc, C(0, 1), ct,          # PB1
            ss, sf, C(0, 3),          # PB2
            C(0, 8),                  # PB3
            ca,                       # PB4
            C(0, 16),                 # PB5, PB6
        ))

        # ----- read a stereo pair from the FIFO --------------------------
        smp_a = Signal(24)
        smp_b = Signal(24)
        have_pair = Signal()
        asp_consume = Signal()

        rd = FSM(reset_state="EMPTY")
        rd.act("EMPTY",
            If(fifo.readable,
               fifo.re.eq(1),
               NextValue(smp_a, fifo.dout),
               NextState("HALF"),
            )
        )
        rd.act("HALF",
            If(fifo.readable,
               fifo.re.eq(1),
               NextValue(smp_b, fifo.dout),
               NextState("READY"),
            )
        )
        rd.act("READY",
            have_pair.eq(1),
            If(asp_consume, NextState("EMPTY")),
        )
        self.submodules.rd = ClockDomainsRenamer("pix")(rd)

        # ----- scheduler: rotate ACR -> InfoFrame -> ASP -----------------
        which = Signal(2)
        island_cnt = Signal(32)
        self.comb += self.island_count.status.eq(island_cnt)

        slot = Signal()
        self.comb += slot.eq(island_slot if island_slot is not None else 0)

        asp_sub0 = Signal(56)
        acr_sub = Signal(56)
        self.comb += [
            asp_sub0.eq(build_asp_subpacket(smp_a, smp_b)),
            acr_sub.eq(build_acr_subpacket(n_pix, cts_pix)),
        ]

        # next-which helper honouring the skip flags
        next_after_acr = Signal(2)
        next_after_if = Signal(2)
        next_after_asp = Signal(2)
        self.comb += [
            next_after_acr.eq(Mux(send_if, 1, 2)),
            next_after_if.eq(2),
            next_after_asp.eq(Mux(send_acr, 0, Mux(send_if, 1, 2))),
        ]

        launch = enable & slot & ~enc.busy & ~enc.start
        self.sync.pix += [
            enc.start.eq(0),
            asp_consume.eq(0),
            If(launch,
               island_cnt.eq(island_cnt + 1),
               enc.start.eq(1),
               Case(which, {
                   0: [   # ACR
                       enc.pkt_type.eq(PKT_ACR), enc.hb1.eq(0), enc.hb2.eq(0),
                       enc.sub[0].eq(acr_sub), enc.sub[1].eq(acr_sub),
                       enc.sub[2].eq(acr_sub), enc.sub[3].eq(acr_sub),
                       which.eq(next_after_acr),
                   ],
                   1: [   # Audio InfoFrame
                       enc.pkt_type.eq(PKT_AUDIO_INFOFRAME), enc.hb1.eq(0x01),
                       enc.hb2.eq(0x0A),
                       enc.sub[0].eq(if_sub0), enc.sub[1].eq(0),
                       enc.sub[2].eq(0), enc.sub[3].eq(0),
                       which.eq(next_after_if),
                   ],
                   2: [   # Audio Sample Packet (subpacket 0 present, layout 0)
                       enc.pkt_type.eq(PKT_ASP), enc.hb1.eq(0x01), enc.hb2.eq(0x00),
                       enc.sub[0].eq(asp_sub0), enc.sub[1].eq(0),
                       enc.sub[2].eq(0), enc.sub[3].eq(0),
                       asp_consume.eq(have_pair),
                       which.eq(next_after_asp),
                   ],
               }),
            ),
        ]

        self.comb += [
            self.status.fields.busy.eq(enc.busy),
            self.status.fields.fifo_readable.eq(fifo.readable),
            self.status.fields.have_pair.eq(have_pair),
        ]
