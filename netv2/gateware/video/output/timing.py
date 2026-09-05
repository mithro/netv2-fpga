"""Free-running CEA video timing generator + test pattern (phase 7c).

Because the NeTV2 output is self-timed (no input to genlock to), the timing
generator is a pair of free-running counters in the ``pix`` domain producing
``de`` / ``hsync`` / ``vsync`` plus the pixel coordinates, from which a simple
colour-bar test pattern is derived. Two CEA modes are provided (720p and
1080p); only the counts differ.

The generator also exposes ``hblank`` and a per-line ``island_slot`` strobe
that marks where in the horizontal blanking a data island may be inserted
(after HSYNC, clear of the video guard bands), which the audio embedder uses to
schedule its packets.
"""

from migen import *

# name -> (hactive, hfront, hsync, hback, vactive, vfront, vsync, vback, hpol, vpol)
CEA_TIMINGS = {
    # 1280x720p60
    "720p":  (1280, 110, 40, 220,  720, 5, 5, 20,  1, 1),
    # 1920x1080p60
    "1080p": (1920, 88, 44, 148, 1080, 4, 5, 36,  1, 1),
}


class VideoTimingGenerator(Module):
    """Free-running ``pix``-domain CEA timing + colour-bar pattern."""

    def __init__(self, resolution="720p"):
        (hact, hfp, hsw, hbp, vact, vfp, vsw, vbp, hpol, vpol) = \
            CEA_TIMINGS[resolution]
        htotal = hact + hfp + hsw + hbp
        vtotal = vact + vfp + vsw + vbp

        self.htotal = htotal
        self.vtotal = vtotal

        # outputs
        self.hcount = Signal(max=htotal)
        self.vcount = Signal(max=vtotal)
        self.de = Signal()
        self.hsync = Signal()
        self.vsync = Signal()
        self.hblank = Signal()
        self.vblank = Signal()
        self.r = Signal(8)
        self.g = Signal(8)
        self.b = Signal(8)
        # A window in the horizontal blank, after HSYNC and clear of the active
        # region, where an audio data island can be inserted. One strobe/line.
        self.island_slot = Signal()

        # # #

        hcount = self.hcount
        vcount = self.vcount
        self.sync.pix += [
            If(hcount == (htotal - 1),
               hcount.eq(0),
               If(vcount == (vtotal - 1),
                  vcount.eq(0),
               ).Else(
                  vcount.eq(vcount + 1),
               )
            ).Else(
               hcount.eq(hcount + 1),
            )
        ]

        # DE / sync regions. Blanking layout (per CEA): active | front porch |
        # sync | back porch. HSYNC/VSYNC are the *_pol-polarity pulses.
        hs_start = hact + hfp
        hs_end = hact + hfp + hsw
        vs_start = vact + vfp
        vs_end = vact + vfp + vsw
        hactive = Signal()
        vactive = Signal()
        self.comb += [
            hactive.eq(hcount < hact),
            vactive.eq(vcount < vact),
            self.de.eq(hactive & vactive),
            self.hblank.eq(~hactive),
            self.vblank.eq(~vactive),
            self.hsync.eq(((hcount >= hs_start) & (hcount < hs_end)) ^ (~hpol & 1)),
            self.vsync.eq(((vcount >= vs_start) & (vcount < vs_end)) ^ (~vpol & 1)),
        ]

        # Island insertion slot: a single-cycle strobe partway through the
        # horizontal back porch (after HSYNC, before active) so the whole island
        # (about 55 chars) fits inside blanking with margin.
        slot_pos = hs_end + 4
        self.sync.pix += self.island_slot.eq(
            (hcount == slot_pos) & (vcount >= vact))   # islands in vblank lines

        # 8-bar colour pattern across the active line (classic SMPTE-ish bars).
        bar = Signal(3)
        self.comb += bar.eq(hcount[7:10])   # 8 bars of 128 px (approx for 1280)
        colors = [
            (0xff, 0xff, 0xff),  # white
            (0xff, 0xff, 0x00),  # yellow
            (0x00, 0xff, 0xff),  # cyan
            (0x00, 0xff, 0x00),  # green
            (0xff, 0x00, 0xff),  # magenta
            (0xff, 0x00, 0x00),  # red
            (0x00, 0x00, 0xff),  # blue
            (0x00, 0x00, 0x00),  # black
        ]
        cases = {}
        for i, (rr, gg, bb) in enumerate(colors):
            cases[i] = [self.r.eq(rr), self.g.eq(gg), self.b.eq(bb)]
        self.comb += Case(bar, cases)
