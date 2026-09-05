"""HDMI audio de-embed / extract core (phase 7b).

Consumes the decoded-packet stream from
:class:`~netv2.gateware.video.audio.parser.AudioPacketParser` (in the HDMI
input ``pix`` domain) and turns it into something the CPU can read:

* **Audio Sample Packet (0x02)**  -> PCM samples pushed, one subframe per pix
  cycle, into an async sample FIFO (pix -> sys). Each 32-bit FIFO word is
  ``{mark, B, C, U, V, channel[2:0], sample[23:0]}``.
* **Audio Clock Regeneration (0x01)** -> latches N and CTS (20 bits each).
* **Audio InfoFrame (0x84)** -> latches CC / CT / SF / SS / CA / checksum.

All decode happens in ``pix``; every CSR-visible latch is carried to ``sys``
with a :class:`BusSynchronizer`, and the sample FIFO is a proper async FIFO, so
the whole core is a clean CDC island bolted onto the phase-7a input pipeline.

The derived audio sample rate is ``fs = f_pixel * N / (128 * CTS)``; the core
exposes N, CTS and (via the target's ``FreqMeter``) the pixel clock, and the
host/firmware does the division -- no divider in fabric.
"""

from migen import *
from migen.genlib.cdc import BusSynchronizer
from migen.genlib.fifo import AsyncFIFO

from litex.soc.interconnect.csr import (
    AutoCSR, CSRStatus, CSRStorage, CSRField,
)

from netv2.gateware.video.audio.parser import AudioPacketParser

# HDMI audio data-island packet types.
PKT_ACR = 0x01
PKT_ASP = 0x02
PKT_AUDIO_INFOFRAME = 0x84

SAMPLE_FIFO_DEPTH = 256


class HDMIAudioExtract(Module, AutoCSR):
    """De-embed HDMI audio from a phase-7a input's TERC4 island stream.

    Instantiate with the input's ``DecodeTERC4`` instance (``terc4``); the
    parser is wired to its nibble taps automatically. All parsing/decoding is
    in the ``pix`` domain; CSRs are read in ``sys``."""

    def __init__(self, terc4=None):
        self.submodules.parser = parser = AudioPacketParser()
        if terc4 is not None:
            self.comb += parser.connect_to_terc4(terc4)

        # ----- CSRs (sys domain) ------------------------------------------
        self.n = CSRStatus(20, description="ACR N value (audio clock regen).")
        self.cts = CSRStatus(20, description="ACR CTS value (audio clock regen).")
        self.audio_infoframe = CSRStatus(fields=[
            CSRField("cc", 3, description="Channel count (CC)."),
            CSRField("ct", 4, description="Coding type (CT)."),
            CSRField("sf", 3, description="Sample frequency (SF)."),
            CSRField("ss", 2, description="Sample size (SS)."),
            CSRField("ca", 8, description="Channel/speaker allocation (CA)."),
            CSRField("checksum", 8, description="InfoFrame checksum byte."),
            CSRField("valid", 1, description="An Audio InfoFrame has been latched."),
        ])
        self.asp_count = CSRStatus(32, description="Audio Sample Packets accepted (ECC ok).")
        self.sample_count = CSRStatus(32, description="Valid PCM samples pushed to the FIFO.")
        self.acr_count = CSRStatus(16, description="ACR packets accepted.")
        self.infoframe_count = CSRStatus(16, description="Audio InfoFrames accepted.")
        self.ecc_err_count = CSRStatus(16, description="Packets dropped on BCH ECC failure.")
        self.overflow_count = CSRStatus(16, description="Samples dropped on FIFO full.")

        self.sample_data = CSRStatus(32, description="Head of the sample FIFO "
            "{mark[31], B[30], C[29], U[28], V[27], channel[26:24], sample[23:0]}.")
        self.sample_valid = CSRStatus(1, description="Sample FIFO has data to read.")
        self.sample_pop = CSRStorage(1, description="Write to pop the sample FIFO head.")

        # Direct read-enable (sys domain), OR'd with the CSR pop. Meant for a
        # future DMA-to-DDR ring and used by the simulation to drain the FIFO.
        self.sample_re = Signal()

        # ----- pix-domain latches / counters ------------------------------
        n_pix = Signal(20)
        cts_pix = Signal(20)
        if_pix = Signal(29)                 # packed InfoFrame bus (matches CSR fields)
        asp_cnt = Signal(32)
        smp_cnt = Signal(32)
        acr_cnt = Signal(16)
        if_cnt = Signal(16)
        err_cnt = Signal(16)
        ovf_cnt = Signal(16)

        p = parser
        is_acr = p.pkt_type == PKT_ACR
        is_asp = p.pkt_type == PKT_ASP
        is_if = p.pkt_type == PKT_AUDIO_INFOFRAME
        accept = p.stb & p.ecc_ok

        # ECC-failed packets are dropped and counted.
        self.sync.pix += If(p.stb & ~p.ecc_ok, err_cnt.eq(err_cnt + 1))

        # --- ACR: latch N / CTS from subpacket 0 --------------------------
        s0 = p.sub[0]
        self.sync.pix += If(accept & is_acr,
            cts_pix.eq(Cat(s0[24:32], s0[16:24], s0[8:12])),   # PB3, PB2, PB1[3:0]
            n_pix.eq(Cat(s0[48:56], s0[40:48], s0[32:36])),    # PB6, PB5, PB4[3:0]
            acr_cnt.eq(acr_cnt + 1),
        )

        # --- Audio InfoFrame: latch CC/CT/SF/SS/CA/checksum from subpkt 0 --
        cc = s0[8:11]        # PB1[2:0]
        ct = s0[12:16]       # PB1[7:4]
        ss = s0[16:18]       # PB2[1:0]
        sf = s0[18:21]       # PB2[4:2]
        ca = s0[32:40]       # PB4
        checksum = s0[0:8]   # PB0
        self.sync.pix += If(accept & is_if,
            if_pix.eq(Cat(cc, ct, sf, ss, ca, checksum, C(1, 1))),
            if_cnt.eq(if_cnt + 1),
        )

        # --- Audio Sample Packet: enqueue subframes into the sample FIFO ---
        fifo = ClockDomainsRenamer({"write": "pix", "read": "sys"})(
            AsyncFIFO(width=32, depth=SAMPLE_FIFO_DEPTH))
        self.submodules.sample_fifo = fifo

        lat_sub = [Signal(56) for _ in range(4)]
        lat_present = Signal(4)
        lat_b = Signal(4)
        pushing = Signal()
        sidx = Signal(4)                    # 0..7 subframe index

        # index selectors for the current subframe
        k = sidx[1:3]                       # subpacket 0..3
        which = sidx[0]                     # 0 = subframe A, 1 = subframe B
        sub_sel = Signal(56)
        present_sel = Signal()
        b_sel = Signal()
        self.comb += [
            Case(k, {i: sub_sel.eq(lat_sub[i]) for i in range(4)}),
            Case(k, {i: present_sel.eq(lat_present[i]) for i in range(4)}),
            Case(k, {i: b_sel.eq(lat_b[i]) for i in range(4)}),
        ]
        sample = Signal(24)
        vbit = Signal()
        ubit = Signal()
        cbit = Signal()
        self.comb += [
            If(which,
               sample.eq(sub_sel[28:52]),   # subframe B: bits 28..51
               vbit.eq(sub_sel[52]), ubit.eq(sub_sel[53]), cbit.eq(sub_sel[54]),
            ).Else(
               sample.eq(sub_sel[0:24]),    # subframe A: bits 0..23
               vbit.eq(sub_sel[24]), ubit.eq(sub_sel[25]), cbit.eq(sub_sel[26]),
            ),
        ]
        channel = Signal(3)
        self.comb += channel.eq(Cat(which, k))   # 2*k + which
        fifo_word = Signal(32)
        self.comb += fifo_word.eq(Cat(
            sample, channel, vbit, ubit, cbit, b_sel, C(1, 1)))

        # Combinational FIFO write of the current subframe; sidx/counters are
        # registered. Keeping ``we`` and ``din`` in the same (current-sidx)
        # cycle avoids writing a word that belongs to the next index.
        self.comb += [
            fifo.din.eq(fifo_word),
            fifo.we.eq(pushing & present_sel & fifo.writable),
        ]
        self.sync.pix += [
            If(~pushing,
               If(accept & is_asp,
                  pushing.eq(1),
                  sidx.eq(0),
                  lat_present.eq(p.hb1[0:4]),
                  lat_b.eq(p.hb2[4:8]),
                  *[lat_sub[i].eq(p.sub[i]) for i in range(4)],
                  asp_cnt.eq(asp_cnt + 1),
               )
            ).Else(
               If(present_sel & fifo.writable, smp_cnt.eq(smp_cnt + 1)),
               If(present_sel & ~fifo.writable, ovf_cnt.eq(ovf_cnt + 1)),
               If(sidx == 7,
                  pushing.eq(0),
               ).Else(
                  sidx.eq(sidx + 1),
               ),
            ),
        ]

        # ----- CDC pix -> sys and CSR wiring ------------------------------
        def cdc(sig, width):
            bs = BusSynchronizer(width, "pix", "sys")
            self.submodules += bs
            self.comb += bs.i.eq(sig)
            return bs.o

        if_o = cdc(if_pix, 29)
        self.comb += [
            self.n.status.eq(cdc(n_pix, 20)),
            self.cts.status.eq(cdc(cts_pix, 20)),
            # audio_infoframe.status is composed from its fields, so drive the
            # fields (not .status) from the CDC'd packed bus.
            self.audio_infoframe.fields.cc.eq(if_o[0:3]),
            self.audio_infoframe.fields.ct.eq(if_o[3:7]),
            self.audio_infoframe.fields.sf.eq(if_o[7:10]),
            self.audio_infoframe.fields.ss.eq(if_o[10:12]),
            self.audio_infoframe.fields.ca.eq(if_o[12:20]),
            self.audio_infoframe.fields.checksum.eq(if_o[20:28]),
            self.audio_infoframe.fields.valid.eq(if_o[28]),
            self.asp_count.status.eq(cdc(asp_cnt, 32)),
            self.sample_count.status.eq(cdc(smp_cnt, 32)),
            self.acr_count.status.eq(cdc(acr_cnt, 16)),
            self.infoframe_count.status.eq(cdc(if_cnt, 16)),
            self.ecc_err_count.status.eq(cdc(err_cnt, 16)),
            self.overflow_count.status.eq(cdc(ovf_cnt, 16)),
        ]

        # Sample FIFO read port (sys domain).
        self.comb += [
            self.sample_data.status.eq(fifo.dout),
            self.sample_valid.status.eq(fifo.readable),
            fifo.re.eq(self.sample_pop.re | self.sample_re),
        ]
