#!/usr/bin/env python3
"""
NeTV2 modern HDMI-audio de-embed SoC (phase 7b).

Extends the phase-7a :class:`NeTV2HDMIInSoC` (one ported litevideo HDMI input on
``hdmi_in`` 0, with the ``DecodeTERC4`` data-island decoder) with an HDMI
**audio extract** core that de-embeds the audio carried in the input's TERC4
data islands:

  * Audio Sample Packets (0x02) -> PCM samples into a CPU-readable FIFO
  * Audio Clock Regeneration (0x01) -> N / CTS latches
  * Audio InfoFrame (0x84) -> CC / CT / SF / SS / CA latches

The extract core (:class:`HDMIAudioExtract`) taps the phase-7a
``hdmi_in0.decode_terc4`` island FSM's per-channel nibble streams directly, so
no change to the input pipeline is needed -- it is bolted on by import only.

Clocking / timing note (720p vs 1080p):
    The phase-7a ``S7Clocking`` MMCM is hard-configured for a 148.5 MHz link
    clock (CLKFBOUT_MULT_F=5.0 -> 742.5 MHz VCO, the only valid build-time VCO;
    74.25 MHz would give a 371.25 MHz VCO, below the MMCM's 600 MHz floor). So
    this SoC *builds* at the 148.5 MHz config exactly like phase-7a, and 720p is
    reached on hardware via the runtime MMCM DRP retune (as the 2019 design
    did). The 742.5 MHz ISERDES pulse-width exception is the inherent -2-part
    datasheet limit documented in phase-7a; it is a non-issue at the preferred
    720p (371.25 MHz serdes) rate. The audio path itself is validated bit-exact
    at 720p / 48 kHz in simulation (tests/sim/video/test_hdmi_audio_extract.py).

Elaborate (no build):

    uv run python -m netv2.targets.hdmi_audio_in --variant a7-100

Build (one Vivado at a time):

    uv run python -m netv2.targets.hdmi_audio_in --variant a7-100 --build --toolchain vivado

Outputs land under ``build/netv2-hdmi-audio-in/``.
"""

import os

from litex.build.parser import LiteXArgumentParser
from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2

from netv2.targets.hdmi_in import NeTV2HDMIInSoC
from netv2.gateware.video.audio import HDMIAudioExtract

REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT = os.path.join(REPO_ROOT, "build", "netv2-hdmi-audio-in")


class NeTV2HDMIAudioInSoC(NeTV2HDMIInSoC):
    """Phase-7a HDMI input SoC + the HDMI audio extract (de-embed) core."""

    def __init__(self, variant="a7-100", sys_clk_freq=100e6, **kwargs):
        super().__init__(variant=variant, sys_clk_freq=sys_clk_freq, **kwargs)

        # The extract core taps the phase-7a input's TERC4 island decoder. Its
        # parser runs in the recovered ``pix`` domain; the CSR-visible latches,
        # counters and sample-FIFO read port are in ``sys`` (BusSynchronizer /
        # AsyncFIFO CDC inside the core). Both domains already exist on this SoC.
        terc4 = self.hdmi_in0.decode_terc4
        self.hdmi_audio0 = HDMIAudioExtract(terc4=terc4)


def main():
    parser = LiteXArgumentParser(
        platform    = kosagi_netv2.Platform,
        description = "NeTV2 HDMI-audio de-embed SoC (phase 7b): input + audio extract.",
    )
    parser.add_target_argument("--variant",      default="a7-100",
        help="Board variant (a7-35 or a7-100). Phase 7b targets a7-100.")
    parser.add_target_argument("--sys-clk-freq", default=100e6, type=float,
        help="System clock frequency.")
    args = parser.parse_args()

    soc = NeTV2HDMIAudioInSoC(
        variant      = args.variant,
        sys_clk_freq = args.sys_clk_freq,
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
