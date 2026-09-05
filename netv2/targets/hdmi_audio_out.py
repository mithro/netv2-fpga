#!/usr/bin/env python3
"""
NeTV2 modern HDMI-audio **embed** SoC (phase 7c).

The source-side counterpart to phase 7b (de-embed): this SoC acts as an HDMI
*source*, generating a self-timed raw HDMI output stream (colour-bar test
pattern) and **embedding** audio into its data-island periods -- Audio Sample
Packets, Audio Clock Regeneration (N/CTS) and an Audio InfoFrame, TERC4-encoded
into the output blanking by the :class:`AudioEmbedder` island encoder.

Because there is no input to genlock to, the pixel/serial clocks are free-running
from the 50 MHz oscillator through a fractional MMCM (M = 14.875 -> VCO 743.75
MHz, +0.17 %, in HDMI tolerance -- no integer PLL hits 74.25/148.5 from 50 MHz).

This is a lean SoC (VexRiscv + UART + integrated SRAM, **no DDR3**) so the build
isolates the output OSERDESE2 serialiser timing (the phase-7c question: does the
output serdes close at 371.875 MHz for 720p, or 743.75 MHz for 1080p) and the
island-encoder fit. The audio embed<->de-embed round trip is proven bit-exact in
simulation (tests/sim/video/test_hdmi_audio_embed.py), not on hardware here.

Elaborate (no build):

    uv run python -m netv2.targets.hdmi_audio_out --variant a7-100

Build (one Vivado at a time):

    uv run python -m netv2.targets.hdmi_audio_out --variant a7-100 --build --toolchain vivado

Outputs land under ``build/netv2-hdmi-audio-out/``.
"""

import os

from litex.build.parser import LiteXArgumentParser
from litex.gen import LiteXModule
from litex.soc.cores.clock import S7PLL
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex.soc.interconnect.csr import AutoCSR
from litex_boards.platforms import kosagi_netv2
from migen import Cat, ClockDomain, ClockDomainsRenamer, If, Module, Signal

from netv2.gateware.video.audio.embed import AudioEmbedder
from netv2.gateware.video.output.encoder import Encoder
from netv2.gateware.video.output.s7 import S7HDMIOutClocking, S7HDMIOutPHY
from netv2.gateware.video.output.timing import VideoTimingGenerator

REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT = os.path.join(REPO_ROOT, "build", "netv2-hdmi-audio-out")


class _CRG(LiteXModule):
    """System clock from the 50 MHz oscillator; exposes clk50 for the output MMCM."""
    def __init__(self, platform, sys_clk_freq):
        self.rst    = Signal()
        self.cd_sys = ClockDomain()

        self.clk50 = clk50 = platform.request("clk50")

        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


class HDMIAudioOut(Module, AutoCSR):
    """Self-timed raw HDMI output + colour-bar pattern + audio embed.

    Builds the ``pix``/``pix5x`` domains from the 50 MHz oscillator, generates
    CEA video timing and a test pattern, TMDS-encodes the pixels, and muxes in
    the audio-island TERC4 tokens during blanking -- all serialised out the
    three raw OSERDESE2 lanes.
    """
    def __init__(self, pads, clk50, resolution="720p"):
        # Self-timed output clock (creates cd_pix / cd_pix5x, drives clk lane).
        self.submodules.clocking = clocking = S7HDMIOutClocking(
            pads, clk50, clk_in_freq=50e6, resolution=resolution)
        self.pix_freq = clocking.pix_freq

        # Raw three-lane output PHY (10-bit tokens -> TMDS).
        self.submodules.phy = phy = S7HDMIOutPHY(pads)

        # Free-running CEA timing + colour-bar pattern (pix domain).
        self.submodules.timing = timing = ClockDomainsRenamer("pix")(
            VideoTimingGenerator(resolution))

        # TMDS video encoders (pix domain): ch0=blue(+sync), ch1=green, ch2=red.
        self.submodules.enc0 = enc0 = ClockDomainsRenamer("pix")(Encoder())
        self.submodules.enc1 = enc1 = ClockDomainsRenamer("pix")(Encoder())
        self.submodules.enc2 = enc2 = ClockDomainsRenamer("pix")(Encoder())
        self.comb += [
            enc0.d.eq(timing.b), enc0.de.eq(timing.de),
            enc0.c.eq(Cat(timing.hsync, timing.vsync)),
            enc1.d.eq(timing.g), enc1.de.eq(timing.de), enc1.c.eq(0),
            enc2.d.eq(timing.r), enc2.de.eq(timing.de), enc2.c.eq(0),
        ]

        # Audio embed core: islands inserted during blanking (island_slot),
        # carrying the live HSYNC/VSYNC on channel-0 nibble bits 1:0.
        self.submodules.embedder = embedder = AudioEmbedder(
            hsync=timing.hsync, vsync=timing.vsync, island_slot=timing.island_slot)

        # Raw-token mux: the island overrides the video tokens while it streams.
        self.comb += [
            If(embedder.stream_valid,
               phy.c0.eq(embedder.c0),
               phy.c1.eq(embedder.c1),
               phy.c2.eq(embedder.c2),
            ).Else(
               phy.c0.eq(enc0.out),
               phy.c1.eq(enc1.out),
               phy.c2.eq(enc2.out),
            )
        ]


class NeTV2HDMIAudioOutSoC(SoCCore):
    """Lean NeTV2 SoC (CPU + UART + SRAM, no DDR) with HDMI audio embed output."""

    def __init__(self, variant="a7-100", toolchain="vivado", sys_clk_freq=50e6,
                 resolution="720p", **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        # No DDR3: BIOS runs from integrated SRAM.
        kwargs.setdefault("integrated_main_ram_size", 0x4000)   # 16 KiB
        kwargs.setdefault("uart_baudrate", 115200)
        if not kwargs.get("ident"):
            kwargs["ident"] = "NeTV2 HDMI audio embed SoC (phase 7c)"
        kwargs.setdefault("ident_version", True)

        self.crg = _CRG(platform, sys_clk_freq)
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)

        # HDMI output + audio embed on hdmi_out 0.
        hdmi_out_pads = platform.request("hdmi_out", 0)
        self.hdmi_out = HDMIAudioOut(hdmi_out_pads, self.crg.clk50,
                                     resolution=resolution)

        # The output pixel-clock family (pix, pix5x -- auto-derived by Vivado
        # from the clk50 create_clock through the output MMCM) is asynchronous to
        # the sys/CPU clock: the AudioEmbedder crosses sys<->pix through an async
        # PCM FIFO and BusSynchronisers, so a false path is correct. Two separate
        # pairwise calls so that pix<->pix5x stay SYNCHRONOUS (the OSERDESE2
        # CLK/CLKDIV pair must be analysed together, not false-pathed).
        platform.add_false_path_constraints(
            self.crg.cd_sys.clk, self.hdmi_out.clocking.cd_pix.clk)
        platform.add_false_path_constraints(
            self.crg.cd_sys.clk, self.hdmi_out.clocking.cd_pix5x.clk)


def main():
    parser = LiteXArgumentParser(
        platform    = kosagi_netv2.Platform,
        description = "NeTV2 HDMI-audio embed SoC (phase 7c): self-timed raw "
                      "output + audio-island encoder.",
    )
    parser.add_target_argument("--variant",      default="a7-100",
        choices=["a7-35", "a7-100"],
        help="Board variant (a7-35 or a7-100). Phase 7c targets a7-100.")
    parser.add_target_argument("--sys-clk-freq", default=50e6, type=float,
        help="System clock frequency (no DDR, so 50 MHz is ample).")
    parser.add_target_argument("--resolution",   default="720p",
        choices=["720p", "1080p"],
        help="Output resolution: 720p (pix5x=371.875 MHz) or 1080p "
             "(pix5x=743.75 MHz output serdes).")
    args = parser.parse_args()

    soc = NeTV2HDMIAudioOutSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        resolution   = args.resolution,
        **parser.soc_argdict,
    )

    builder_kwargs = parser.builder_argdict
    output_dir = builder_kwargs.get("output_dir") or DEFAULT_OUT
    builder_kwargs["output_dir"] = output_dir
    if not builder_kwargs.get("csr_csv"):
        builder_kwargs["csr_csv"] = os.path.join(output_dir, "csr.csv")

    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)
    else:
        builder.build(**parser.toolchain_argdict, run=False)


if __name__ == "__main__":
    main()
