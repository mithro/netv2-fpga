"""TMDS video encoder (ported from litevideo ``output/hdmi/encoder.py``).

This is the standard DVI/HDMI TMDS 8b/10b encoder: it turns an 8-bit colour
component plus the 2-bit control code (c) and a data-enable (de) into a 10-bit
TMDS token, emitting the four :data:`control_tokens` when ``de`` is low. It is
*control-token only* -- it has no notion of TERC4 data-island characters, which
is exactly why the audio-island encoder (:mod:`netv2.gateware.video.audio.embed`)
injects its TERC4 tokens by driving the raw output PHY directly rather than
going through this encoder.

Ported verbatim (modern migen, wrapped by the caller in the ``pix`` domain) from
bunnie's litevideo commit 3bc5a24.
"""

from functools import reduce
from operator import add

from migen import *

# The four TMDS control tokens (7 transitions each, for RX clock recovery).
control_tokens = [0b1101010100, 0b0010101011, 0b0101010100, 0b1010101011]


class Encoder(Module):
    """8b/10b TMDS encoder (one colour channel). ``pix`` domain when renamed."""

    def __init__(self):
        self.d = Signal(8)
        self.c = Signal(2)
        self.de = Signal()

        self.out = Signal(10)

        # # #

        # stage 1 - count number of 1s in data
        d = Signal(8)
        n1d = Signal(max=9)
        self.sync += [
            n1d.eq(reduce(add, [self.d[i] for i in range(8)])),
            d.eq(self.d)
        ]

        # stage 2 - add 9th bit
        q_m = Signal(9)
        q_m8_n = Signal()
        self.comb += q_m8_n.eq((n1d > 4) | ((n1d == 4) & ~d[0]))
        for i in range(8):
            if i:
                curval = curval ^ d[i] ^ q_m8_n
            else:
                curval = d[0]
            self.sync += q_m[i].eq(curval)
        self.sync += q_m[8].eq(~q_m8_n)

        # stage 3 - count number of 1s and 0s in q_m[:8]
        q_m_r = Signal(9)
        n0q_m = Signal(max=9)
        n1q_m = Signal(max=9)
        self.sync += [
            n0q_m.eq(reduce(add, [~q_m[i] for i in range(8)])),
            n1q_m.eq(reduce(add, [q_m[i] for i in range(8)])),
            q_m_r.eq(q_m)
        ]

        # stage 4 - final encoding
        cnt = Signal((6, True))

        s_c = self.c
        s_de = self.de
        for p in range(3):
            new_c = Signal(2)
            new_de = Signal()
            self.sync += new_c.eq(s_c), new_de.eq(s_de)
            s_c, s_de = new_c, new_de

        self.sync += \
            If(s_de,
                If((cnt == 0) | (n1q_m == n0q_m),
                    self.out[9].eq(~q_m_r[8]),
                    self.out[8].eq(q_m_r[8]),
                    If(q_m_r[8],
                        self.out[:8].eq(q_m_r[:8]),
                        cnt.eq(cnt + n1q_m - n0q_m)
                    ).Else(
                        self.out[:8].eq(~q_m_r[:8]),
                        cnt.eq(cnt + n0q_m - n1q_m)
                    )
                ).Else(
                    If((~cnt[5] & (n1q_m > n0q_m)) | (cnt[5] & (n0q_m > n1q_m)),
                        self.out[9].eq(1),
                        self.out[8].eq(q_m_r[8]),
                        self.out[:8].eq(~q_m_r[:8]),
                        cnt.eq(cnt + Cat(0, q_m_r[8]) + n0q_m - n1q_m)
                    ).Else(
                        self.out[9].eq(0),
                        self.out[8].eq(q_m_r[8]),
                        self.out[:8].eq(q_m_r[:8]),
                        cnt.eq(cnt - Cat(0, ~q_m_r[8]) + n1q_m - n0q_m)
                    )
                )
            ).Else(
                self.out.eq(Array(control_tokens)[s_c]),
                cnt.eq(0)
            )
