#!/usr/bin/env python3
"""
NeTV2 minimal "blink" SoC -- the open-source-toolchain (openXC7) deliverable.

This is the smallest useful NeTV2 SoC: a VexRiscv CPU + integrated LiteX BIOS +
UART + a LED chaser on the six user LEDs. It deliberately has **no DDR3, no
video/HDMI and no PCIe** so that it builds end-to-end with the fully
open-source flow:

    yosys (synthesis) -> nextpnr-xilinx (place & route) -> prjxray (bitstream)

collectively packaged as "openXC7". The complex NeTV2 blocks (DDR3 s7ddrphy,
HDMI ISERDESE2/OSERDESE2, PCIe GTP) are not yet reliably supported by
nextpnr-xilinx, so this target is the concrete "gateware builds with the
open-source tooling" proof for phase 2b, goal item (c).

Firmware/data lives in integrated SRAM (integrated_main_ram_size) instead of
DDR3, so the BIOS runs without a memory controller.

Build with the open-source toolchain (from repo root):

    CHIPDB=<chipdb dir> \
    PRJXRAY_DB_DIR=<prjxray-db dir> \
    NEXTPNR_XILINX_PYTHON_DIR=<nextpnr-xilinx dir> \
    uv run python -m netv2.targets.blink --toolchain openxc7 --build

The bitstream is written to:

    build/netv2-blink/gateware/kosagi_netv2.bit

It can also be built with Vivado for comparison (--toolchain vivado).

See docs/current/openxc7-build.md for the exact reproduce command, toolchain
versions, resource usage and the documented DDR/video/PCIe boundary.
"""

import os
import re

from litex.build.parser import LiteXArgumentParser
from litex.gen import LiteXModule
from litex.soc.cores.clock import S7PLL
from litex.soc.cores.led import LedChaser
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import kosagi_netv2
from migen import ClockDomain, Signal

# Repo-root/build/netv2-blink -- three levels up from this file
# (netv2/targets/blink.py -> netv2/targets -> netv2 -> repo root).
REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT = os.path.join(REPO_ROOT, "build", "netv2-blink")


# openXC7 platform fixups ------------------------------------------------------
# (kept local to this file so the target is self-contained; mirrors the
#  fpgas.online reference designs' _shared/platform_fixups + yosys_workarounds).

def _fix_openxc7_device_name(platform):
    """Strip the dash between part and package (xc7a100t-fgg484-2 ->
    xc7a100tfgg484-2) so the nextpnr-xilinx chipdb name matches."""
    old = platform.device
    new = re.sub(r"^(xc7[aksz]\d+t)-(.*)", r"\1\2", old)
    if new != old:
        platform.device = new
    return old


def _ensure_chipdb_symlink(platform):
    """If CHIPDB only carries the dashed .bin, symlink the un-dashed name."""
    chipdb_dir = os.environ.get("CHIPDB", "")
    if not chipdb_dir:
        return
    device = platform.device
    old_dashed = re.sub(r"^(xc7[aksz]\d+t)(.*)", r"\1-\2", device)
    old_part = re.sub(r"-\d+$", "", old_dashed)
    new_part = re.sub(r"-\d+$", "", device)
    if old_part == new_part:
        return
    old_bin = os.path.join(chipdb_dir, old_part + ".bin")
    new_bin = os.path.join(chipdb_dir, new_part + ".bin")
    if os.path.exists(old_bin) and not os.path.exists(new_bin):
        try:
            os.symlink(old_bin, new_bin)
        except FileExistsError:
            pass


def _patch_yosys_scopeinfo(soc):
    """Yosys >= 0.40 emits $scopeinfo debug cells that nextpnr-xilinx cannot
    place; insert a `delete t:$scopeinfo` before the write step."""
    tc = soc.platform.toolchain
    if not hasattr(tc, "_yosys_template"):
        return
    from litex.build.yosys_wrapper import YosysWrapper
    template = list(YosysWrapper._default_template)
    for i, line in enumerate(template):
        if line.startswith("write_"):
            template.insert(i, "delete t:$scopeinfo")
            break
    tc._yosys_template = template


# CRG --------------------------------------------------------------------------

class _CRG(LiteXModule):
    """Minimal clock/reset generator: sys clock from the 50 MHz oscillator."""
    def __init__(self, platform, sys_clk_freq):
        self.rst    = Signal()
        self.cd_sys = ClockDomain()

        clk50 = platform.request("clk50")

        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# BlinkSoC ---------------------------------------------------------------------

class BlinkSoC(SoCCore):
    def __init__(self, variant="a7-100", toolchain="openxc7", sys_clk_freq=50e6,
                 with_led_chaser=True, **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        if toolchain == "openxc7":
            _fix_openxc7_device_name(platform)

        # No DDR3: run the BIOS entirely from integrated SRAM.
        kwargs.setdefault("integrated_main_ram_size", 0x2000)  # 8 KiB
        kwargs.setdefault("uart_baudrate", 115200)
        # ident/ident_version may already be present via parser.soc_argdict.
        if not kwargs.get("ident"):
            kwargs["ident"] = "NeTV2 blink SoC (openXC7 minimal)"
        kwargs.setdefault("ident_version", True)

        self.crg = _CRG(platform, sys_clk_freq)

        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)

        # LED chaser on the six user LEDs.
        if with_led_chaser:
            self.leds = LedChaser(
                pads         = platform.request_all("user_led"),
                sys_clk_freq = sys_clk_freq,
            )


# Build ------------------------------------------------------------------------

def main():
    parser = LiteXArgumentParser(
        platform=kosagi_netv2.Platform,
        description="NeTV2 minimal blink SoC (phase 2b): CPU + UART + LED chaser, "
                    "no DDR/video/PCIe -- the open-source (openXC7) build target.")
    parser.add_target_argument("--variant", default="a7-100",
        choices=["a7-35", "a7-100"],
        help="NeTV2 FPGA variant (a7-35 developer / a7-100 production).")
    parser.add_target_argument("--sys-clk-freq", default=50e6, type=float,
        help="System clock frequency (50 MHz is conservative for openXC7).")
    args = parser.parse_args()

    soc = BlinkSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        **parser.soc_argdict,
    )

    if args.toolchain == "openxc7":
        _ensure_chipdb_symlink(soc.platform)
        _patch_yosys_scopeinfo(soc)

    builder_kwargs = parser.builder_argdict
    output_dir = builder_kwargs.get("output_dir") or DEFAULT_OUT
    builder_kwargs["output_dir"] = output_dir
    if not builder_kwargs.get("csr_csv"):
        builder_kwargs["csr_csv"] = os.path.join(output_dir, "csr.csv")

    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
