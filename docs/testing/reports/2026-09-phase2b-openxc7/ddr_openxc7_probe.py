#!/usr/bin/env python3
# ruff: noqa
"""
Boundary probe: attempt to build the NeTV2 DDR3 base SoC with openXC7.

The modern targets (netv2/targets/base.py and the upstream
litex_boards.targets.kosagi_netv2 BaseSoC) both construct their platform with
the default Vivado toolchain and do not thread --toolchain through to the
Platform constructor, so they cannot be pointed at openXC7 from the CLI. This
probe monkeypatches the Platform default to openxc7 so the *identical* DDR3
SoC (s7ddrphy + LiteDRAM, VexRiscv, sys_clk 100 MHz) is handed to the
open-source flow. The point is to record exactly where openXC7 gives out on
the DDR design, not to make it pass.

Run (from repo root, with CHIPDB / PRJXRAY_DB_DIR / NEXTPNR_XILINX_PYTHON_DIR
set and the openxc7 bin dir + /usr/bin on PATH):

    uv run python docs/testing/reports/2026-09-phase2b-openxc7/ddr_openxc7_probe.py \
        --toolchain openxc7 --variant a7-100 --sys-clk-freq 100e6 --build \
        --output-dir build/netv2-ddr-openxc7
"""

import os
import re

import litex_boards.platforms.kosagi_netv2 as _plat

# Force the platform to build for openXC7 instead of Vivado.
_orig_init = _plat.Platform.__init__
def _patched_init(self, variant="a7-35", toolchain="openxc7"):
    _orig_init(self, variant=variant, toolchain=toolchain)
_plat.Platform.__init__ = _patched_init

from litex.build.parser import LiteXArgumentParser          # noqa: E402
from litex.soc.integration.builder import Builder            # noqa: E402
from litex_boards.platforms import kosagi_netv2              # noqa: E402
from litex_boards.targets.kosagi_netv2 import BaseSoC        # noqa: E402


def _fix_and_patch(soc):
    # Strip dash in device name so the chipdb name matches.
    dev = soc.platform.device
    soc.platform.device = re.sub(r"^(xc7[aksz]\d+t)-(.*)", r"\1\2", dev)
    # Ensure a dashed chipdb symlink exists too (belt and braces).
    chipdb = os.environ.get("CHIPDB", "")
    if chipdb:
        undashed = soc.platform.device
        dashed = re.sub(r"^(xc7[aksz]\d+t)(.*)", r"\1-\2", undashed)
        a = os.path.join(chipdb, re.sub(r"-\d+$", "", undashed) + ".bin")
        b = os.path.join(chipdb, re.sub(r"-\d+$", "", dashed) + ".bin")
        if os.path.exists(a) and not os.path.exists(b):
            try:
                os.symlink(a, b)
            except FileExistsError:
                pass
    # $scopeinfo strip (Yosys >= 0.40).
    tc = soc.platform.toolchain
    if hasattr(tc, "_yosys_template"):
        from litex.build.yosys_wrapper import YosysWrapper
        t = list(YosysWrapper._default_template)
        for i, line in enumerate(t):
            if line.startswith("write_"):
                t.insert(i, "delete t:$scopeinfo")
                break
        tc._yosys_template = t


def main():
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform,
                                 description="openXC7 DDR3 boundary probe")
    parser.add_target_argument("--variant", default="a7-100")
    parser.add_target_argument("--sys-clk-freq", default=100e6, type=float)
    args = parser.parse_args()

    soc = BaseSoC(
        variant      = args.variant,
        sys_clk_freq = args.sys_clk_freq,
        **parser.soc_argdict,
    )
    _fix_and_patch(soc)

    builder = Builder(soc, **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
