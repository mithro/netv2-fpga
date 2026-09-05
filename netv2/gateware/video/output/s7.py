"""Series-7 HDMI **output** PHY + self-timed output clock (phase 7c).

Ported from bunnie's litevideo ``output/hdmi/s7.py`` (commit 3bc5a24) and
adapted for the NeTV2 as a *source* (there is no input to genlock to, so the
pixel/serial clocks are free-running from the on-board 50 MHz oscillator).

Two pieces:

* :class:`S7HDMIOutEncoderSerializer` -- the OSERDESE2 10:1 DDR serialiser
  (master + slave pair) that shifts a 10-bit TMDS token out of one differential
  pair per pixel. In **raw** mode (``bypass_encoder=True``) it takes a raw
  10-bit token on ``.data`` (this is what the audio-island encoder needs, so it
  can emit TERC4 data-island characters that the DVI-only LiteX
  ``VideoS7HDMIPHY`` cannot); otherwise it instantiates a TMDS
  :class:`~netv2.gateware.video.output.encoder.Encoder`.

* :class:`S7HDMIOutClocking` -- a **fractional MMCM** that turns the 50 MHz
  oscillator into the pixel clock ``pix`` and the 5x serial clock ``pix5x``.
  No integer PLL hits 148.5/742.5 (or 74.25/371.25) from 50 MHz; the closest
  in-spec fractional multiplier is ``M = 14.875`` (VCO = 743.75 MHz, +0.17 %,
  well inside HDMI's +/-0.5 %). This is the "output clock mux" case from the
  HDCP receiver spec 4.3: when acting as a source there is no recovered link
  clock, so the output is self-timed.

* :class:`S7HDMIOutPHY` -- the three-channel raw output PHY: three
  serialisers + the clock lane, driven by 10-bit ``c0/c1/c2`` tokens.
"""

from litex.soc.interconnect.csr import AutoCSR
from migen import *

from netv2.gateware.video.output.encoder import Encoder

# Supported output pixel clocks. VCO is fixed at 743.75 MHz (50 MHz * 14.875);
# the pixel and 5x serial clocks are the two MMCM output dividers of that VCO.
#   720p50/60 : pix = 74.375 MHz  (VCO/10),  pix5x = 371.875 MHz (VCO/2)
#   1080p50/60: pix = 148.75 MHz  (VCO/5),   pix5x = 743.75 MHz  (VCO/1)
# (Nominals are 74.25 / 148.5; the +0.17 % offset is the fractional-MMCM error.)
OUT_CLOCK_CONFIG = {
    "720p":  {"clkout0_divide_f": 10.0, "pix5x_divide": 2, "pix": 74.375e6},
    "1080p": {"clkout0_divide_f": 5.0,  "pix5x_divide": 1, "pix": 148.75e6},
}
VCO_FREQ = 743.75e6
MMCM_MULT = 14.875


class S7HDMIOutEncoderSerializer(Module):
    """OSERDESE2 10:1 DDR serialiser for one TMDS lane (``pix`` / ``pix5x``)."""

    def __init__(self, pad_p, pad_n, bypass_encoder=False):
        if not bypass_encoder:
            self.submodules.encoder = ClockDomainsRenamer("pix")(Encoder())
            self.d, self.c, self.de = self.encoder.d, self.encoder.c, self.encoder.de
            self.data = self.encoder.out
        else:
            self.data = Signal(10)

        # # #

        data = Signal(10)
        self.comb += data.eq(self.data)

        ce = Signal()
        self.sync.pix5x += ce.eq(~ResetSignal("pix"))

        shift = Signal(2)
        pad_se = Signal()

        self.specials += [
            Instance("OSERDESE2",
                p_DATA_WIDTH=10, p_TRISTATE_WIDTH=1,
                p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="DDR",
                p_SERDES_MODE="MASTER",

                o_OQ=pad_se,
                i_OCE=ce,
                i_TCE=0,
                i_RST=ResetSignal("pix"),
                i_CLK=ClockSignal("pix5x"), i_CLKDIV=ClockSignal("pix"),
                i_D1=data[0], i_D2=data[1],
                i_D3=data[2], i_D4=data[3],
                i_D5=data[4], i_D6=data[5],
                i_D7=data[6], i_D8=data[7],

                i_SHIFTIN1=shift[0], i_SHIFTIN2=shift[1],
            ),
            Instance("OSERDESE2",
                p_DATA_WIDTH=10, p_TRISTATE_WIDTH=1,
                p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="DDR",
                p_SERDES_MODE="SLAVE",

                i_OCE=ce,
                i_TCE=0,
                i_RST=ResetSignal("pix"),
                i_CLK=ClockSignal("pix5x"), i_CLKDIV=ClockSignal("pix"),
                i_D1=0, i_D2=0,
                i_D3=data[8], i_D4=data[9],
                i_D5=0, i_D6=0,
                i_D7=0, i_D8=0,

                i_SHIFTIN1=0, i_SHIFTIN2=0,
                o_SHIFTOUT1=shift[0], o_SHIFTOUT2=shift[1]
            ),
            Instance("OBUFDS", i_I=pad_se, o_O=pad_p, o_OB=pad_n)
        ]


class S7HDMIOutClocking(Module, AutoCSR):
    """Self-timed output clock generator: 50 MHz -> pix + pix5x (fractional MMCM).

    ``clk_in`` is the 50 MHz oscillator signal (already through the SoC's clk
    input buffer); ``resolution`` selects the pixel clock (see
    :data:`OUT_CLOCK_CONFIG`). Creates the ``pix`` and ``pix5x`` clock domains
    and drives the HDMI clock lane at the pixel rate.
    """

    def __init__(self, pads, clk_in, clk_in_freq=50e6, resolution="720p"):
        assert resolution in OUT_CLOCK_CONFIG
        cfg = OUT_CLOCK_CONFIG[resolution]
        self.pix_freq = cfg["pix"]

        self.clock_domains.cd_pix = ClockDomain("pix")
        self.clock_domains.cd_pix5x = ClockDomain("pix5x", reset_less=True)

        self.locked = Signal()

        # # #

        mmcm_locked = Signal()
        mmcm_fb = Signal()
        mmcm_clk0 = Signal()   # pix
        mmcm_clk1 = Signal()   # pix5x

        self.specials += [
            Instance("MMCME2_ADV",
                p_BANDWIDTH="OPTIMIZED",
                i_RST=0, o_LOCKED=mmcm_locked,

                # VCO: 50 MHz * 14.875 / 1 = 743.75 MHz
                p_REF_JITTER1=0.01,
                p_CLKIN1_PERIOD=1e9 / clk_in_freq,
                p_CLKFBOUT_MULT_F=MMCM_MULT, p_CLKFBOUT_PHASE=0.000,
                p_DIVCLK_DIVIDE=1,
                i_CLKIN1=clk_in, i_CLKFBIN=mmcm_fb, o_CLKFBOUT=mmcm_fb,

                # CLK0 = pix (fractional divider)
                p_CLKOUT0_DIVIDE_F=cfg["clkout0_divide_f"], p_CLKOUT0_PHASE=0.000,
                o_CLKOUT0=mmcm_clk0,
                # CLK1 = pix5x
                p_CLKOUT1_DIVIDE=cfg["pix5x_divide"], p_CLKOUT1_PHASE=0.000,
                o_CLKOUT1=mmcm_clk1,
            ),
            Instance("BUFG", i_I=mmcm_clk0, o_O=self.cd_pix.clk),
            Instance("BUFG", i_I=mmcm_clk1, o_O=self.cd_pix5x.clk),
        ]
        self.comb += [
            self.cd_pix.rst.eq(~mmcm_locked),
            self.locked.eq(mmcm_locked),
        ]

        # HDMI clock lane: serialise a fixed 0b0000011111 pattern at pix5x so the
        # differential clock toggles at the pixel rate (matches litevideo).
        self.submodules.clk_gen = S7HDMIOutEncoderSerializer(
            pads.clk_p, pads.clk_n, bypass_encoder=True)
        self.comb += self.clk_gen.data.eq(Signal(10, reset=0b0000011111))


class S7HDMIOutPHY(Module):
    """Raw three-lane HDMI output PHY.

    Takes three 10-bit TMDS tokens (``c0``/``c1``/``c2``) already formed by the
    caller (TMDS-encoded pixels during active video, TERC4 characters inside a
    data island, control tokens during blanking) and serialises them out the
    three differential pairs. Raw mode is required so the audio-island encoder
    can inject TERC4 characters -- the DVI-only path cannot represent them.
    """

    def __init__(self, pads):
        self.c0 = Signal(10)
        self.c1 = Signal(10)
        self.c2 = Signal(10)

        # # #

        self.submodules.es0 = S7HDMIOutEncoderSerializer(pads.data0_p, pads.data0_n, True)
        self.submodules.es1 = S7HDMIOutEncoderSerializer(pads.data1_p, pads.data1_n, True)
        self.submodules.es2 = S7HDMIOutEncoderSerializer(pads.data2_p, pads.data2_n, True)

        self.comb += [
            self.es0.data.eq(self.c0),
            self.es1.data.eq(self.c1),
            self.es2.data.eq(self.c2),
        ]
