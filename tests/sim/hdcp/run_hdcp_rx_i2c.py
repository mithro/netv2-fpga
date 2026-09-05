"""Build and run the hdcp_rx I2C-slave testbench in Vivado xsim.

Task H2 of docs/superpowers/plans/2026-09-06-hdcp-receiver-plan.md.

Flow:
  1. xvlog/xelab/xsim the hdcp_rx module plus its self-contained testbench,
     sourcing the Vivado 2025.2 environment itself (does NOT require Vivado on
     PATH already),
  2. grep the testbench's TB_PASS / TB_FAIL marker from the xsim log.

hdcp_rx.v is self-contained (it embeds copies of the i2c_snoop sampling FSMs),
so no legacy sources are needed.  All build junk goes under tests/sim/hdcp/work/.

Prints PASS and exits 0 only if the testbench prints TB_PASS; prints FAIL /
BLOCKED and exits nonzero otherwise.

Usage:  uv run python tests/sim/hdcp/run_hdcp_rx_i2c.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = HERE / "work"

VIVADO_SETTINGS = Path("/opt/Xilinx/2025.2/Vivado/settings64.sh")
# xelab's embedded C compiler needs crt1.o etc.; make LIBRARY_PATH find them.
LIBRARY_PATH = "/usr/lib/x86_64-linux-gnu:/usr/lib/gcc/x86_64-linux-gnu/14"

# Order matters for xvlog: leaf modules first, top (tb) last.
SOURCES = [
    REPO / "netv2/gateware/hdcp/hdcp_rx.v",
    HERE / "tb_hdcp_rx_i2c.v",
]

SNAPSHOT = "hdcp_rx_i2c_sim"
TOP = "tb_hdcp_rx_i2c"


class Blocked(Exception):
    """A tool/environment problem prevented a genuine PASS/FAIL determination."""


def run_shell(cmd: str, logname: str) -> str:
    """Run *cmd* in WORK with the Vivado env sourced; tee output to a log."""
    if not VIVADO_SETTINGS.exists():
        raise Blocked(f"Vivado settings not found at {VIVADO_SETTINGS}")
    env = dict(os.environ)
    env["LIBRARY_PATH"] = LIBRARY_PATH
    full = f". {VIVADO_SETTINGS}; {cmd}"
    proc = subprocess.run(
        ["bash", "-c", full],
        cwd=str(WORK),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    out = proc.stdout or ""
    (WORK / logname).write_text(out)
    if proc.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-25:])
        raise Blocked(
            f"{cmd.split()[0]} failed (rc={proc.returncode}). Log tail:\n{tail}")
    return out


def build_and_sim() -> str:
    WORK.mkdir(parents=True, exist_ok=True)
    stale = WORK / "xsim.dir"
    if stale.is_dir():
        shutil.rmtree(stale)

    srcs = " ".join(f'"{s}"' for s in SOURCES)
    run_shell(f"xvlog {srcs}", "xvlog_i2c.out")
    run_shell(f"xelab -timescale 1ns/1ps {TOP} -s {SNAPSHOT}", "xelab_i2c.out")
    return run_shell(f"xsim {SNAPSHOT} -R", "xsim_i2c.out")


def main() -> int:
    try:
        sim_out = build_and_sim()
    except Blocked as e:
        print(f"BLOCKED: {e}")
        return 2

    # Echo the testbench's per-check lines so a human sees which reads matched.
    for line in sim_out.splitlines():
        if line.startswith(("==", "  ok", "  FAIL", "TB_")):
            print(line)

    tb_pass = "TB_PASS" in sim_out
    tb_fail = "TB_FAIL" in sim_out

    if tb_pass and not tb_fail:
        print("PASS")
        return 0

    if not tb_pass:
        print("testbench did not print TB_PASS (self-check failed or sim aborted)")
    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
