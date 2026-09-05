"""Build and run the hdcp_mod_rx testbench in Vivado xsim, check vs the oracle.

hdcp_mod_rx is the HDCP-receiver mod-cipher controller patch (task H5a): a
renamed copy of ``legacy/overlay/hdcp_mod.v`` that drives the H1 cipher patch
``hdcp_cipher_rx`` and latches R0'/Ri per design of record section 5.2/5.3.

Flow:
  1. generate golden vectors from netv2.hdcp.cipher (the oracle),
  2. xvlog/xelab/xsim the patched controller + the patched cipher + their
     unchanged legacy deps + the testbench, sourcing the Vivado 2025.2
     environment itself (does NOT require Vivado already on PATH),
  3. parse the testbench's captured R0'/Ri_link/frame_count and re-compare, in
     Python, against the oracle for the rig vector.

Prints PASS and exits 0 only if the testbench self-check passed AND the Python
re-check of every captured value matches the model; prints FAIL / BLOCKED and
exits nonzero otherwise.  All build junk goes under tests/sim/hdcp/work/.

Usage:  uv run python tests/sim/hdcp/run_hdcp_mod_rx.py
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
    REPO / "netv2/gateware/hdcp/hdcp_mod_rx.v",
    HERE / "tb_hdcp_mod_rx.v",
]

VEC_HEX = HERE / "cipher_vectors.hex"
RESULTS = WORK / "mod_rx_results.txt"
SNAPSHOT = "mod_rx_sim"
TOP = "tb_hdcp_mod_rx"

# vector 0 is the rig Km (see gen_cipher_vectors.VECTORS)
RIG_KM = 0xF26625C3367E6E
RIG_AN = 0x34271C130C070403


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
    run_shell(f"xvlog {srcs}", "xvlog_mod.out")
    # diff_network.v / shuffle_network.v carry no `timescale; supply a default
    # so xelab does not error on the mix of timed and untimed modules.
    run_shell(f"xelab -timescale 1ns/1ps {TOP} -s {SNAPSHOT}", "xelab_mod.out")
    run_shell(
        f'xsim {SNAPSHOT} -R -testplusarg "vectors={VEC_HEX}" '
        f'-testplusarg "results={RESULTS}"',
        "xsim_mod.out",
    )


def parse_results() -> dict:
    if not RESULTS.exists():
        raise Blocked(f"testbench produced no results file {RESULTS}")
    pat = re.compile(
        r"RESULT\s+km=([0-9a-fA-F]+)\s+an=([0-9a-fA-F]+)\s+"
        r"r0=([0-9a-fA-FxX]+)\s+r0valid=(\d+)\s+"
        r"ri64=([0-9a-fA-FxX]+)\s+ri127=([0-9a-fA-FxX]+)\s+"
        r"ri128=([0-9a-fA-FxX]+)\s+ri200=([0-9a-fA-FxX]+)\s+"
        r"ri256=([0-9a-fA-FxX]+)\s+frames=(\d+)"
    )
    for line in RESULTS.read_text().splitlines():
        m = pat.search(line)
        if m:
            return {
                "km": int(m.group(1), 16),
                "an": int(m.group(2), 16),
                "r0": m.group(3).lower(),
                "r0valid": int(m.group(4)),
                "ri64": m.group(5).lower(),
                "ri127": m.group(6).lower(),
                "ri128": m.group(7).lower(),
                "ri200": m.group(8).lower(),
                "ri256": m.group(9).lower(),
                "frames": int(m.group(10)),
            }
    raise Blocked(f"no RESULT line parsed from {RESULTS}")


def compare(row: dict) -> bool:
    """Re-check the RTL captures against the oracle in Python."""
    exp = gen.compute(RIG_KM, RIG_AN)
    r0 = f"{exp['r0']:04x}"
    ri128 = f"{exp['ri128']:04x}"
    ri256 = f"{exp['ri256']:04x}"
    # design 5.2: Ri_link holds R0' until the 128th frame, then the 128/256 Ri,
    # and does NOT change between boundaries -> frames 64/127 read R0'; 200 the
    # frame-128 Ri.
    checks = [
        ("R0'", row["r0"], r0),
        ("Ri_link@64  (==R0')", row["ri64"], r0),
        ("Ri_link@127 (==R0')", row["ri127"], r0),
        ("Ri_link@128", row["ri128"], ri128),
        ("Ri_link@200 (==Ri128, stable)", row["ri200"], ri128),
        ("Ri_link@256", row["ri256"], ri256),
    ]
    ok = True
    for label, got, want in checks:
        good = got == want
        ok = ok and good
        print(f"  [{'ok  ' if good else 'FAIL'}] {label:<32} RTL={got} model={want}")
    if row["r0valid"] != 1:
        ok = False
        print(f"  [FAIL] R0_valid_out pulse: r0valid={row['r0valid']} (want 1)")
    else:
        print("  [ok  ] R0_valid_out pulsed once")
    if row["frames"] < 256:
        ok = False
        print(f"  [FAIL] frame_count reached only {row['frames']} (want >= 256)")
    else:
        print(f"  [ok  ] frame_count advanced to {row['frames']}")
    return ok


def main() -> int:
    try:
        gen.main()
        build_and_sim()
        row = parse_results()
    except Blocked as e:
        print(f"BLOCKED: {e}")
        return 2

    xsim_out = WORK / "xsim_mod.out"
    xsim_log = xsim_out.read_text() if xsim_out.exists() else ""
    tb_pass = "TB_PASS" in xsim_log
    tb_fail = "TB_FAIL" in xsim_log

    print("Comparing RTL captures against the oracle:")
    py_ok = compare(row)

    if py_ok and tb_pass and not tb_fail:
        print(f"Rig Km={row['km']:014x} -> RTL R0'={row['r0']} "
              f"Ri_link@128={row['ri128']} @256={row['ri256']} (match oracle)")
        print("PASS")
        return 0

    if not tb_pass:
        print("testbench did not print TB_PASS (self-check failed or sim aborted)")
    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
