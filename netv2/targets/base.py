#!/usr/bin/env python3
"""
NeTV2 modern base SoC (phase 2a).

Thin wrapper around the maintained ``litex_boards.targets.kosagi_netv2``
BaseSoC (LiteX 2026.04). It builds the NeTV2 a7-100 SoC with the target's
defaults -- VexRiscv CPU, integrated LiteX BIOS, UART, and DDR3 via the
Series-7 DDR PHY (s7ddrphy) -- using Vivado, and pins the build output to a
stable directory so later phases (PCIe, audio) can extend this same entry
point.

This deliberately reuses the upstream, timing-closing target rather than
re-deriving the CRG/DDR logic; ``NeTV2BaseSoC`` subclasses it so later phases
can add peripherals in one place.

Build (from repo root):

    uv run python -m netv2.targets.base --build --toolchain vivado

The bitstream is written to:

    build/netv2-base/gateware/kosagi_netv2.bit

and the generated CSR map to:

    build/netv2-base/csr.csv
"""

import os

from litex.build.parser import LiteXArgumentParser
from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2
from litex_boards.targets.kosagi_netv2 import BaseSoC as _KosagiBaseSoC

# Repo-root/build/netv2-base -- three levels up from this file
# (netv2/targets/base.py -> netv2/targets -> netv2 -> repo root).
REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT = os.path.join(REPO_ROOT, "build", "netv2-base")


class NeTV2BaseSoC(_KosagiBaseSoC):
    """NeTV2 base SoC: upstream kosagi_netv2 BaseSoC, defaulting to the a7-100.

    Later phases extend this subclass (e.g. add PCIe DMA, I2S audio) so the
    common CPU/UART/DDR3 base lives in exactly one place.
    """
    def __init__(self, variant="a7-100", **kwargs):
        super().__init__(variant=variant, **kwargs)


def main():
    parser = LiteXArgumentParser(
        platform=kosagi_netv2.Platform,
        description="NeTV2 modern base SoC (phase 2a): UART + DDR3 on LiteX 2026.04.",
    )
    parser.add_target_argument("--variant",       default="a7-100",
        help="Board variant (a7-35 or a7-100). Phase 2a targets a7-100.")
    parser.add_target_argument("--sys-clk-freq",  default=100e6, type=float,
        help="System clock frequency.")
    parser.add_target_argument("--with-ethernet", action="store_true",
        help="Enable Ethernet (RMII). Off by default for phase 2a (UART+DDR).")
    args = parser.parse_args()

    soc = NeTV2BaseSoC(
        variant       = args.variant,
        sys_clk_freq  = args.sys_clk_freq,
        with_ethernet = args.with_ethernet,
        **parser.soc_argdict,
    )

    builder_kwargs = parser.builder_argdict
    # Pin the output dir unless the caller overrode --output-dir on the CLI.
    output_dir = builder_kwargs.get("output_dir") or DEFAULT_OUT
    builder_kwargs["output_dir"] = output_dir
    # Emit the CSV CSR map (csr.csv) alongside the build for host tooling.
    if not builder_kwargs.get("csr_csv"):
        builder_kwargs["csr_csv"] = os.path.join(output_dir, "csr.csv")

    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
