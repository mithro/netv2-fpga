"""HDMI data-island *audio packet* parser (phase 7b).

Runs in the HDMI input pixel-clock (``pix``) domain and sits directly on the
phase-7a :class:`~netv2.gateware.video.input.decoding.DecodeTERC4` island FSM.
It taps the same per-channel decoded nibble streams the FSM shifts into its
``t4d_*`` BCH capture registers and, char-by-char, reassembles each 32-char
data-island packet into a decoded-packet stream:

    {type (8), hb1 (8), hb2 (8), sub0..sub3 (56 data bits each), ecc_ok}

while independently recomputing the header + 4 subpacket BCH ECCs with a serial
reflected LFSR and comparing them against the received ECC bytes (so ``ecc_ok``
is a genuine error check, not a copy).

Why tap the nibble streams rather than the parallel ``t4d_bchN`` CSRs: computing
the BCH over 56 bits combinationally from a latched 64-bit word would be a very
deep XOR chain; feeding the LFSR one/two bits per pixel as the island streams by
keeps the logic shallow and naturally pipelined, exactly as a hardware HDMI ECC
checker does. The reassembly bit order matches ``DecodeTERC4`` and the Python
model in ``tests/sim/video/hdmi_audio_model.py`` bit-for-bit.

The parser is deliberately protocol-only: it does not know what an Audio Sample
Packet *means*. :class:`~netv2.gateware.video.audio.extract.HDMIAudioExtract`
consumes ``self`` and turns the decoded packets into PCM / N-CTS / InfoFrame.
"""

from migen import *

# BCH ECC: generator x^8 + x^7 + x^6 + x^4 + 1 (HDMI / HDCP data-island ECC),
# processed LSB-first as a reflected right-shift LFSR. The XOR mask is the
# bit-reversal of the polynomial's low byte (0xD1 -> 0x8B).
BCH_POLY_LOW = 0xD1


def _reflect8(v):
    r = 0
    for i in range(8):
        if v & (1 << i):
            r |= 1 << (7 - i)
    return r


BCH_MASK = _reflect8(BCH_POLY_LOW)   # 0x8B


def _bch_step(cur, d):
    """One reflected-LFSR step: return the 8-bit next-state *expression* after
    feeding data bit ``d``. ``cur`` is any 8-bit migen Value."""
    fb = cur[0] ^ d
    bits = []
    for i in range(8):
        src = cur[i + 1] if i < 7 else Constant(0)   # register shifts right
        if (BCH_MASK >> i) & 1:
            bits.append(src ^ fb)
        else:
            bits.append(src)
    return Cat(*bits)


# Char-index boundaries within a 32-char data-island packet.
HDR_DATA_CHARS = 24      # header: 24 data bits (chars 0..23), 8 ECC bits (24..31)
SUB_DATA_CHARS = 28      # subpacket: 56 data bits (chars 0..27), 8 ECC (28..31)


class AudioPacketParser(Module):
    """Tap ``DecodeTERC4`` and emit a decoded-packet stream (``pix`` domain)."""

    def __init__(self):
        # --- tap inputs (wire these from a DecodeTERC4 instance) -----------
        self.t4_enc = Signal()          # encrypting_data: high during TERC4 payload
        self.t4_hbit = Signal()         # ch0.d[2]  -> header bit for this char
        self.t4_s1 = Signal(4)          # ch1.d[3:0] -> subpacket 0..3, first bit
        self.t4_s2 = Signal(4)          # ch2.d[3:0] -> subpacket 0..3, second bit

        # --- decoded-packet stream outputs (valid for one cycle on stb) ----
        self.stb = Signal()
        self.pkt_type = Signal(8)
        self.hb1 = Signal(8)
        self.hb2 = Signal(8)
        self.sub = [Signal(56) for _ in range(4)]
        self.ecc_ok = Signal()

        # # #

        enc = self.t4_enc
        cnt = Signal(6)                 # 0..31 char index within the packet
        done1 = Signal()                # pulses the cycle after char 31

        # Char counter: wraps every 32 chars while inside the island (an island
        # may carry several back-to-back packets), resets when not in TERC4.
        self.sync.pix += [
            If(enc,
               If(cnt == 31, cnt.eq(0)).Else(cnt.eq(cnt + 1))
            ).Else(
               cnt.eq(0)
            ),
            done1.eq(enc & (cnt == 31)),
        ]

        # Reassembled data + received ECC shift registers.
        hd = Signal(24)                 # header data bits (HB0,HB1,HB2)
        he = Signal(8)                  # received header ECC
        sd = [Signal(56) for _ in range(4)]   # subpacket data (PB0..PB6)
        se = [Signal(8) for _ in range(4)]    # received subpacket ECC

        self.sync.pix += If(enc,
            If(cnt < HDR_DATA_CHARS,
               hd.eq(Cat(hd[1:], self.t4_hbit))
            ).Else(
               he.eq(Cat(he[1:], self.t4_hbit))
            )
        )
        for k in range(4):
            self.sync.pix += If(enc,
                If(cnt < SUB_DATA_CHARS,
                   sd[k].eq(Cat(sd[k][2:], self.t4_s1[k], self.t4_s2[k]))
                ).Else(
                   se[k].eq(Cat(se[k][2:], self.t4_s1[k], self.t4_s2[k]))
                )
            )

        # Serial BCH ECC over the data bits, reset at char 0 of each packet.
        hl = Signal(8)                  # computed header ECC
        sl = [Signal(8) for _ in range(4)]   # computed subpacket ECC

        hbase = Signal(8)
        hfull = Signal(8)
        self.comb += [
            hbase.eq(Mux(cnt == 0, 0, hl)),
            hfull.eq(_bch_step(hbase, self.t4_hbit)),
        ]
        self.sync.pix += If(enc,
            hl.eq(Mux(cnt < HDR_DATA_CHARS, hfull, hbase))
        )

        for k in range(4):
            base = Signal(8)
            inter = Signal(8)
            full = Signal(8)
            self.comb += [
                base.eq(Mux(cnt == 0, 0, sl[k])),
                inter.eq(_bch_step(base, self.t4_s1[k])),
                full.eq(_bch_step(inter, self.t4_s2[k])),
            ]
            self.sync.pix += If(enc,
                sl[k].eq(Mux(cnt < SUB_DATA_CHARS, full, base))
            )

        # On done1 all data/ECC registers hold the just-completed packet.
        ecc_ok = Signal()
        self.comb += ecc_ok.eq(
            (hl == he)
            & (sl[0] == se[0]) & (sl[1] == se[1])
            & (sl[2] == se[2]) & (sl[3] == se[3])
        )
        self.comb += [
            self.stb.eq(done1),
            self.pkt_type.eq(hd[0:8]),
            self.hb1.eq(hd[8:16]),
            self.hb2.eq(hd[16:24]),
            self.ecc_ok.eq(ecc_ok),
        ]
        for k in range(4):
            self.comb += self.sub[k].eq(sd[k])

    def connect_to_terc4(self, terc4):
        """Comb-wire the tap inputs from a ``DecodeTERC4`` instance."""
        return [
            self.t4_enc.eq(terc4.encrypting_data),
            self.t4_hbit.eq(terc4.data0_dect4.decval.d[2]),
            self.t4_s1.eq(terc4.data1_dect4.decval.d),
            self.t4_s2.eq(terc4.data2_dect4.decval.d),
        ]
