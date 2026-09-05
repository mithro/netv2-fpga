"""Build and run the hdcp_cipher_rx testbench in Vivado xsim, check vs the oracle.

Flow:
  1. generate golden vectors from netv2.hdcp.cipher (the oracle),
  2. xvlog/xelab/xsim the patched cipher + its unchanged legacy deps + the
     testbench, sourcing the Vivado 2025.2 environment itself (does NOT require
     Vivado on PATH already),
  3. parse the testbench's captured R0/Ri and re-compare, in Python, against the
     oracle for every vector.

Prints PASS and exits 0 only if every captured value matches the model; prints
FAIL / BLOCKED and exits nonzero otherwise.  All build junk goes under
tests/sim/hdcp/work/.

Usage:  uv run python tests/sim/hdcp/run_cipher_rx.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = HERE / "work"

for p in (str(REPO), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import gen_cipher_vectors as gen

VIVADO_SETTINGS = Path("/opt/Xilinx/2025.2/Vivado/settings64.sh")
# xelab's embedded C compiler needs crt1.o etc.; make LIBRARY_PATH find them.
LIBRARY_PATH = "/usr/lib/x86_64-linux-gnu:/usr/lib/gcc/x86_64-linux-gnu/14"

# Order matters for xvlog: leaf modules first, top (tb) last.
SOURCES = [
    REPO / "legacy/overlay/shuffle_network.v",
    REPO / "legacy/overlay/diff_network.v",
    REPO / "legacy/overlay/hdcp_lfsr.v",
    REPO / "legacy/overlay/hdcp_block.v",
    REPO / "netv2/gateware/hdcp/hdcp_cipher_rx.v",
    HERE / "tb_cipher_rx.v",
]

VEC_HEX = HERE / "cipher_vectors.hex"
RESULTS = WORK / "cipher_rx_results.txt"
SNAPSHOT = "cipher_rx_sim"
TOP = "tb_cipher_rx"


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


def build_and_sim() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    stale = WORK / "xsim.dir"
    if stale.is_dir():
        shutil.rmtree(stale)
    if RESULTS.exists():
        RESULTS.unlink()

    srcs = " ".join(f'"{s}"' for s in SOURCES)
    run_shell(f"xvlog {srcs}", "xvlog.out")
    # diff_network.v / shuffle_network.v carry no `timescale; supply a default
    # so xelab does not error on the mix of timed and untimed modules.
    run_shell(f"xelab -timescale 1ns/1ps {TOP} -s {SNAPSHOT}", "xelab.out")
    run_shell(
        f'xsim {SNAPSHOT} -R -testplusarg "vectors={VEC_HEX}" '
        f'-testplusarg "results={RESULTS}"',
        "xsim.out",
    )


def parse_results() -> list[dict]:
    if not RESULTS.exists():
        raise Blocked(f"testbench produced no results file {RESULTS}")
    rows = []
    pat = re.compile(
        r"RESULT\s+(\d+)\s+km=([0-9a-fA-F]+)\s+an=([0-9a-fA-F]+)\s+"
        r"r0=([0-9a-fA-FxX]+)\s+ri128=([0-9a-fA-FxX]+)\s+ri256=([0-9a-fA-FxX]+)"
    )
    for line in RESULTS.read_text().splitlines():
        m = pat.search(line)
        if m:
            rows.append({
                "v": int(m.group(1)),
                "km": int(m.group(2), 16),
                "an": int(m.group(3), 16),
                "r0": m.group(4).lower(),
                "ri128": m.group(5).lower(),
                "ri256": m.group(6).lower(),
            })
    if not rows:
        raise Blocked(f"no RESULT lines parsed from {RESULTS}")
    return rows


def compare(rows: list[dict]) -> bool:
    ok = True
    for row in rows:
        exp = gen.compute(row["km"], row["an"])
        expected = {
            "r0": f"{exp['r0']:04x}",
            "ri128": f"{exp['ri128']:04x}",
            "ri256": f"{exp['ri256']:04x}",
        }
        for field, want in expected.items():
            got = row[field]
            mark = "ok  " if got == want else "FAIL"
            if got != want:
                ok = False
            print(f"  [{mark}] vec{row['v']} Km={row['km']:014x} "
                  f"{field:<6} RTL={got} model={want}")
    return ok


def main() -> int:
    try:
        gen.main()
        build_and_sim()
        rows = parse_results()
    except Blocked as e:
        print(f"BLOCKED: {e}")
        return 2

    xsim_out = WORK / "xsim.out"
    xsim_log = xsim_out.read_text() if xsim_out.exists() else ""
    tb_pass = "TB_PASS" in xsim_log
    tb_fail = "TB_FAIL" in xsim_log

    print("Comparing RTL captures against the oracle:")
    py_ok = compare(rows)

    if py_ok and tb_pass and not tb_fail:
        rig = next((r for r in rows if r["v"] == 0), None)
        if rig is not None:
            print(f"Rig Km={rig['km']:014x} -> RTL R0={rig['r0']} (matches oracle)")
        print("PASS")
        return 0

    if not tb_pass:
        print("testbench did not print TB_PASS (self-check failed or sim aborted)")
    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
