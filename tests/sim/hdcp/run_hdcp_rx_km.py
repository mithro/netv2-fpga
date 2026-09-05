"""Build and run the hdcp_rx Km-accumulator testbench in Vivado xsim.

Task H3 of docs/superpowers/plans/2026-09-06-hdcp-receiver-plan.md, spec
section 4 and verification cases 10.2 items 3, 5, 6.

Flow:
  1. read the 40 x 7-byte little-endian sink keys from
     ~/netv2-hdcp-handoff/keys/sink_keys.bin and the source KSV from
     manifest.json, compute the oracle Km with netv2/hdcp/keys.km_from_keys,
     and emit them (plus Aksv) as work/km_vectors.mem for the testbench to
     $readmemh -- the key material is written only under work/ (gitignored)
     and regenerated every run, never committed;
  2. xvlog/xelab/xsim the hdcp_rx module plus its testbench, sourcing the
     Vivado 2025.2 environment itself;
  3. grep the testbench's TB_PASS / TB_FAIL marker from the xsim log.

Prints PASS and exits 0 only if the testbench prints TB_PASS; prints FAIL /
BLOCKED and exits nonzero otherwise.

Usage:  uv run python tests/sim/hdcp/run_hdcp_rx_km.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = HERE / "work"

# Make netv2/hdcp/keys.py importable without installing the package.
sys.path.insert(0, str(REPO))
from netv2.hdcp.keys import km_from_keys, load_keys_bin, load_manifest

KEYS_BIN = Path(os.path.expanduser("~/netv2-hdcp-handoff/keys/sink_keys.bin"))
MANIFEST = Path(os.path.expanduser("~/netv2-hdcp-handoff/keys/manifest.json"))

VIVADO_SETTINGS = Path("/opt/Xilinx/2025.2/Vivado/settings64.sh")
# xelab's embedded C compiler needs crt1.o etc.; make LIBRARY_PATH find them.
LIBRARY_PATH = "/usr/lib/x86_64-linux-gnu:/usr/lib/gcc/x86_64-linux-gnu/14"

# Order matters for xvlog: leaf modules first, top (tb) last.
SOURCES = [
    REPO / "netv2/gateware/hdcp/hdcp_rx.v",
    HERE / "tb_hdcp_rx_km.v",
]

VECTORS = WORK / "km_vectors.mem"
SNAPSHOT = "hdcp_rx_km_sim"
TOP = "tb_hdcp_rx_km"


class Blocked(Exception):
    """A tool/environment problem prevented a genuine PASS/FAIL determination."""


def gen_vectors() -> int:
    """Write work/km_vectors.mem from the sink keys; return the oracle Km."""
    if not KEYS_BIN.exists():
        raise Blocked(f"sink key file not found: {KEYS_BIN}")
    if not MANIFEST.exists():
        raise Blocked(f"manifest not found: {MANIFEST}")

    keys = load_keys_bin(KEYS_BIN)
    manifest = load_manifest(MANIFEST)
    aksv = manifest["ksv_source_int"]
    km = km_from_keys(keys, aksv)

    # 42 lines of 56-bit hex: 40 keys, then Aksv (low 40 bits), then Km.
    lines = [f"{k & ((1 << 56) - 1):014x}" for k in keys]
    lines.append(f"{aksv & ((1 << 40) - 1):014x}")
    lines.append(f"{km & ((1 << 56) - 1):014x}")
    WORK.mkdir(parents=True, exist_ok=True)
    VECTORS.write_text("\n".join(lines) + "\n")
    return km


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
    run_shell(f"xvlog {srcs}", "xvlog_km.out")
    run_shell(f"xelab -timescale 1ns/1ps {TOP} -s {SNAPSHOT}", "xelab_km.out")
    return run_shell(f"xsim {SNAPSHOT} -R", "xsim_km.out")


def main() -> int:
    try:
        km = gen_vectors()
        print(f"oracle Km = {km:014x} (from {KEYS_BIN})")
        sim_out = build_and_sim()
    except Blocked as e:
        print(f"BLOCKED: {e}")
        return 2

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
