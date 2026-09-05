#!/usr/bin/env python3
"""
NeTV2 modern PCIe-endpoint SoC (phase 6a).

Extends the phase-2 :class:`NeTV2BaseSoC` (UART + DDR3 on LiteX 2026.04) with a
LitePCIe endpoint on the Xilinx ``pcie_7x`` hard block + GTP transceivers, so
the SoC can be enumerated over the NeTV2's PCIe edge.

Why this wrapper instead of the upstream ``--with-pcie`` flag: the maintained
``litex_boards.targets.kosagi_netv2`` target hard-codes the endpoint to the
board's **x4** connector (``pcie_x4``, 128-bit datapath). The rpi5-netv2 test
rig wires the NeTV2 edge to the Pi 5's external PCIe, which is a **single lane**.
This wrapper therefore instantiates ``S7PCIEPHY`` on the **x1** pad group
(``pcie_x1``, 64-bit datapath, ``nlanes=1``) to match the Pi 5's link, then adds
the LitePCIe endpoint with one DMA channel.

LitePCIe's ``S7PCIEPHY`` sets the PCIe hard-IP ``Device_ID`` to
``0x7020 + nlanes``, so an x1 endpoint enumerates as **10ee:7021**
(vendor 0x10ee Xilinx).

Build (from repo root):

    uv run python -m netv2.targets.pcie --build --toolchain vivado

The bitstream is written to:

    build/netv2-pcie/gateware/kosagi_netv2.bit

and the generated CSR map to:

    build/netv2-pcie/csr.csv

Add ``--driver`` to also emit the LitePCIe host software/driver under
``build/netv2-pcie/driver`` (used for the optional DMA test).
"""

import os

from litex.build.parser import LiteXArgumentParser
from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2

from litepcie.phy.s7pciephy import S7PCIEPHY
from litepcie.software import generate_litepcie_software

from netv2.targets.base import NeTV2BaseSoC

REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT = os.path.join(REPO_ROOT, "build", "netv2-pcie")

# PCIe datapath width per lane count (matches upstream/LitePCIe conventions:
# x1/x2 use 64-bit, x4 uses 128-bit, x8 uses 256-bit).
_PCIE_DATA_WIDTH = {1: 64, 2: 64, 4: 128, 8: 256}


class NeTV2PCIeSoC(NeTV2BaseSoC):
    """NeTV2 SoC with a LitePCIe endpoint sized for the Pi 5's x1 link.

    Builds the phase-2 base (VexRiscv + UART + DDR3) and adds an ``S7PCIEPHY``
    endpoint on the selected PCIe connector. Defaults to a single lane
    (``pcie_lanes=1`` -> ``pcie_x1`` pads, 64-bit datapath) so it matches the
    Pi 5's external PCIe, which is x1.
    """
    def __init__(self, variant="a7-100", with_pcie=True, pcie_lanes=1,
                 pcie_bar0_size=0x20000, **kwargs):
        # Base SoC: UART + DDR3, no upstream PCIe (we add a lane-matched one).
        super().__init__(variant=variant, **kwargs)

        if with_pcie:
            assert pcie_lanes in _PCIE_DATA_WIDTH, \
                f"pcie_lanes must be one of {sorted(_PCIE_DATA_WIDTH)}"
            data_width = _PCIE_DATA_WIDTH[pcie_lanes]
            pcie_pads  = self.platform.request(f"pcie_x{pcie_lanes}")
            self.pcie_phy = S7PCIEPHY(self.platform, pcie_pads,
                data_width = data_width,
                bar0_size  = pcie_bar0_size)
            # One DMA channel, matching the upstream kosagi_netv2 --with-pcie.
            self.add_pcie(phy=self.pcie_phy, ndmas=1)

            # --- Async clock-group fix (phase 6a) -----------------------------
            # LiteX auto-emits a `set_clock_groups` to declare the PCIe clock
            # domain asynchronous to the sys domain, but it resolves the domains
            # by *net name* (`get_nets pcie_clk` / `sys_clk`). The GTP/MMCM
            # clocking renames those nets (to `main_s7pciephy_clkout*` /
            # `main_crg_clkout0`), so the lookup returns nothing (Vivado prints
            # "set_clock_groups: ... only one non-empty group remains" and drops
            # the constraint). The genuine async CDC between the LitePCIe
            # endpoint (PCIe user clock, 125/250 MHz) and the SoC (sys clock,
            # 100 MHz) then gets timed as if synchronous, producing large false
            # negative-slack inter-clock paths (~-2.2 ns) that fail post-route.
            #
            # Re-declare the clock trees asynchronous by their stable *root*
            # clocks, pulling in every generated clock beneath each:
            #   * `clk50`         -> sys PLL       -> main_crg_clkout*
            #   * `txoutclk_x0y0` -> PCIe MMCM     -> main_s7pciephy_clkout*
            #   * `pcie_x1_clk_p` -> GTP refclk
            # Emitted as a pre-placement (post-synthesis) command so the
            # generated clocks exist when `get_clocks` is evaluated. The sys
            # DDR clocks (sys4x/idelay) stay in one group with sys, so their
            # real synchronous relationship is preserved.
            self.platform.toolchain.pre_placement_commands.append(
                "set_clock_groups -asynchronous"
                " -group [get_clocks -include_generated_clocks clk50]"
                " -group [get_clocks -include_generated_clocks txoutclk_x0y0]"
                " -group [get_clocks -include_generated_clocks pcie_x1_clk_p]")


def main():
    parser = LiteXArgumentParser(
        platform=kosagi_netv2.Platform,
        description="NeTV2 modern PCIe-endpoint SoC (phase 6a): UART + DDR3 + LitePCIe (x1).",
    )
    parser.add_target_argument("--variant",      default="a7-100",
        help="Board variant (a7-35 or a7-100). Phase 6a targets a7-100.")
    parser.add_target_argument("--sys-clk-freq", default=100e6, type=float,
        help="System clock frequency.")
    parser.add_target_argument("--with-pcie",    action="store_true", default=True,
        help="Enable the PCIe endpoint (on by default for this target).")
    parser.add_target_argument("--no-pcie",      dest="with_pcie", action="store_false",
        help="Disable PCIe (falls back to the plain base SoC).")
    parser.add_target_argument("--pcie-lanes",   default=1, type=int, choices=[1, 2, 4, 8],
        help="PCIe lane count. Default 1 to match the Pi 5's external x1 link.")
    parser.add_target_argument("--driver",       action="store_true",
        help="Generate the LitePCIe host software/driver (for the DMA test).")
    args = parser.parse_args()

    soc = NeTV2PCIeSoC(
        variant      = args.variant,
        sys_clk_freq = args.sys_clk_freq,
        with_pcie    = args.with_pcie,
        pcie_lanes   = args.pcie_lanes,
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

    if args.driver:
        generate_litepcie_software(soc, os.path.join(builder.output_dir, "driver"))


if __name__ == "__main__":
    main()
