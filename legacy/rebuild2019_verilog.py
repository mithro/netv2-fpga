#!/usr/bin/env python3
"""2026 tooling: regenerate the 2019 VideoOverlaySoC Verilog without Vivado or a
RISC-V toolchain. Run inside the rebuild2019 container with --lx-ignore-deps."""
import lxbuildenv  # noqa: F401  must be first: re-execs with legacy deps on PYTHONPATH
import sys
from netv2mvp import Platform, VideoOverlaySoC
from litex.soc.integration.builder import Builder

part = sys.argv[1] if len(sys.argv) > 1 else "35"
platform = Platform(part=part, cable="pcb")
soc = VideoOverlaySoC(platform, part=part, dqs_phase="112.5")
builder = Builder(soc, output_dir="build/verilog-only-%s" % part,
                  compile_software=False, compile_gateware=False)
builder.build()
print("generated build/verilog-only-%s/gateware/top.v" % part)
