"""Build and run the full HDCP-receiver integration testbench in Vivado xsim.

Task H6 of docs/superpowers/plans/2026-09-06-hdcp-receiver-plan.md, spec
sections 2-6 and verification section 10.2.

This is the integration correctness gate: it wires the three verified receiver
Verilog modules together the way the bridge does --

    hdcp_rx.v          (eth domain): DDC I2C slave + 40x56 sink-key store +
                       Km accumulator; produces Km_hw / Km_valid_hw / An / Aksv
    hdcp_mod_rx.v      (pix_o domain): the mod-cipher controller, which itself
                       instantiates hdcp_cipher_rx.v (the H1 cipher patch) --
                       one cipher serves keystream, R0 and Ri (spec sec 0/5.2).

-- and drives a complete HDCP source-side authentication handshake against it
with a task-based Verilog I2C *master* model on the DDC, checking every result
against the Python oracle netv2/hdcp/cipher.py + netv2/hdcp/keys.py.

Flow:
  1. read the 40 sink keys from ~/netv2-hdcp-handoff/keys/sink_keys.bin and the
     source KSV from manifest.json; compute -- all from the oracle, never
     hard-coded -- Km, R0', Ri@128, Ri@256, the initial keystream, a "wrong Km"
     key set (one flipped bit), and Km for an all-zero and a non-balanced Aksv;
     emit them as $readmemh mem files under work/ (KEY MATERIAL LIVES ONLY
     UNDER work/, which is gitignored, and is regenerated every run);
  2. xvlog/xelab/xsim the two receiver .v modules + their unchanged legacy deps
     + the cipher patch + the testbench, sourcing the Vivado 2025.2 env;
  3. parse the testbench's machine-readable results and re-check, in Python,
     against the oracle.

Prints PASS and exits 0 only when the testbench self-check passed AND the
Python re-check matches; prints FAIL / BLOCKED and exits nonzero otherwise.
All build junk stays under tests/sim/hdcp/work/.

Usage:  uv run python tests/sim/hdcp/run_hdcp_rx_top.py
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

sys.path.insert(0, str(REPO))
from netv2.hdcp.cipher import HDCPCipher
from netv2.hdcp.keys import km_from_keys, load_keys_bin, load_manifest

KEYS_BIN = Path(os.path.expanduser("~/netv2-hdcp-handoff/keys/sink_keys.bin"))
MANIFEST = Path(os.path.expanduser("~/netv2-hdcp-handoff/keys/manifest.json"))

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
    REPO / "netv2/gateware/hdcp/hdcp_rx.v",
    HERE / "tb_hdcp_rx_top.v",
]

SNAPSHOT = "hdcp_rx_top_sim"
TOP = "tb_hdcp_rx_top"

# The source-side authentication random An (a chosen 64-bit value; matches the
# constant already used by tb_hdcp_rx_i2c.v).  All expected values below are
# computed from this via the oracle, never hard-coded.
AN = 0x46B6537884E56C78

# Number of stream-cipher keystream words captured for the encrypt->decrypt
# round-trip (and compared word-for-word against the oracle stream).
NKS = 64

# The two extra Aksv cases the RPi side needs proven (blank-OTP / non-balanced
# KSVs the Pi's BCM2835 may transmit): the receiver must accept ANY Aksv as-is.
AKSV_ZERO = 0x0000000000          # all-zeros (blank OTP)
AKSV_FF = 0x00000000FF            # 8 ones, deliberately NOT 20/20 balanced

RESULTS = WORK / "top_results.txt"
SCALARS = WORK / "top_scalars.mem"
KEYS_GOOD = WORK / "top_keys_good.mem"
KEYS_BAD = WORK / "top_keys_bad.mem"
KEYSTREAM = WORK / "top_keystream.mem"
KS_CAPTURE = WORK / "top_ks_capture.mem"


class Blocked(Exception):
    """A tool/environment problem prevented a genuine PASS/FAIL determination."""


def oracle() -> dict:
    """Compute every expected value from the trusted Python oracle."""
    if not KEYS_BIN.exists():
        raise Blocked(f"sink key file not found: {KEYS_BIN}")
    if not MANIFEST.exists():
        raise Blocked(f"manifest not found: {MANIFEST}")

    keys = load_keys_bin(KEYS_BIN)
    man = load_manifest(MANIFEST)
    aksv_src = man["ksv_source_int"]
    bksv = man["ksv_sink_int"]
    km = km_from_keys(keys, aksv_src)

    # "wrong Km": flip the LSB of the key at the lowest set-bit index of the
    # source Aksv, so the flipped key is guaranteed to be summed into Km.
    flip_idx = (aksv_src & -aksv_src).bit_length() - 1
    bad_keys = list(keys)
    bad_keys[flip_idx] ^= 1
    km_bad = km_from_keys(bad_keys, aksv_src)
    if km_bad == km:
        raise Blocked("bad-key perturbation did not change Km (test would be void)")

    # R0' and per-frame Ri at the 128 / 256 boundaries.
    c = HDCPCipher(repeater=0)
    _, _, r0 = c.authenticate(km, AN)
    ri = {}
    for frame in range(1, 257):
        c.rekey_frame()
        if frame in (128, 256):
            ri[frame] = c.ri_frame

    # Initial keystream: what the receiver streams in its first HDCP_READY
    # window == authenticate then ONE vertical-blank rekey (the FSM's automatic
    # HDCP_AUTH_VSYNC run == rekey_frame #1) then hdcpStreamCipher per pixel.
    c2 = HDCPCipher(repeater=0)
    c2.authenticate(km, AN)
    c2.rekey_frame()
    keystream = c2.stream(NKS)

    return {
        "keys": keys,
        "bad_keys": bad_keys,
        "aksv_src": aksv_src,
        "bksv": bksv,
        "km": km,
        "km_bad": km_bad,
        "km_zero": km_from_keys(keys, AKSV_ZERO),
        "km_ff": km_from_keys(keys, AKSV_FF),
        "r0": r0,
        "ri128": ri[128],
        "ri256": ri[256],
        "keystream": keystream,
    }


def write_vectors(o: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    KEYS_GOOD.write_text("".join(f"{k & ((1 << 56) - 1):014x}\n" for k in o["keys"]))
    KEYS_BAD.write_text("".join(f"{k & ((1 << 56) - 1):014x}\n" for k in o["bad_keys"]))
    KEYSTREAM.write_text("".join(f"{w & 0xFFFFFF:06x}\n" for w in o["keystream"]))
    # Fixed-index scalar table (see tb_hdcp_rx_top.v).  Comments are ignored by
    # $readmemh; each value is one 64-bit-wide entry.
    scal = [
        (o["aksv_src"], "0  Aksv (source KSV)"),
        (o["km"], "1  Km (oracle, balanced source KSV)"),
        (AN, "2  An"),
        (o["r0"], "3  R0'"),
        (o["ri128"], "4  Ri@128"),
        (o["ri256"], "5  Ri@256"),
        (o["bksv"], "6  Bksv (sink KSV)"),
        (o["km_bad"], "7  Km with one flipped sink key (wrong Km)"),
        (o["km_zero"], "8  Km for all-zero Aksv (blank OTP)"),
        (o["km_ff"], "9  Km for non-balanced Aksv 0x00000000ff"),
        (NKS, "10 keystream word count"),
    ]
    SCALARS.write_text("".join(f"{v & ((1 << 64) - 1):016x}  // {c}\n" for v, c in scal))


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
        tail = "\n".join(out.strip().splitlines()[-30:])
        raise Blocked(f"{cmd.split()[0]} failed (rc={proc.returncode}). Log tail:\n{tail}")
    return out


def build_and_sim() -> str:
    WORK.mkdir(parents=True, exist_ok=True)
    stale = WORK / "xsim.dir"
    if stale.is_dir():
        shutil.rmtree(stale)
    if RESULTS.exists():
        RESULTS.unlink()

    srcs = " ".join(f'"{s}"' for s in SOURCES)
    run_shell(f"xvlog {srcs}", "xvlog_top.out")
    run_shell(f"xelab -timescale 1ns/1ps {TOP} -s {SNAPSHOT}", "xelab_top.out")
    return run_shell(
        f'xsim {SNAPSHOT} -R -testplusarg "results={RESULTS}"', "xsim_top.out")


def parse_results() -> dict:
    """Parse the testbench's KEY=VALUE result lines into a dict."""
    if not RESULTS.exists():
        raise Blocked(f"testbench produced no results file {RESULTS}")
    row: dict[str, str] = {}
    for line in RESULTS.read_text().splitlines():
        for tok in line.split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                row[k] = v
    if not row:
        raise Blocked(f"no KEY=VALUE results parsed from {RESULTS}")
    return row


def hx(v: int, w: int) -> str:
    return f"{v & ((1 << (4 * w)) - 1):0{w}x}"


def check_keystream(o: dict) -> bool:
    """Align the captured receiver keystream to the oracle stream and check it.

    The cipher's stream output has a fixed short startup latency (a couple of
    held words before it advances), so the RTL capture contains the oracle
    sequence at a small fixed offset rather than at index 0.  Find that offset
    (proving the RTL keystream IS the oracle keystream, not by hard-coding), then
    assert every remaining word matches.  A mismatch means the RTL/harness is
    wrong (the oracle is trusted).
    """
    if not KS_CAPTURE.exists():
        print("  [FAIL] keystream capture file missing")
        return False
    cap = [int(x, 16) for x in KS_CAPTURE.read_text().split()]
    oracle_ks = o["keystream"]
    # Locate the oracle's word 0 in the capture; require the whole tail to match.
    for off in range(len(cap) - 1):
        n = min(len(oracle_ks), len(cap) - off)
        if n < 8:
            break
        if cap[off:off + n] == oracle_ks[:n]:
            print(f"  [ok  ] keystream matches oracle for {n} words "
                  f"(startup latency {off} words)")
            return True
    print(f"  [FAIL] captured keystream does not match the oracle stream: "
          f"cap[0:4]={[hex(x) for x in cap[:4]]} oracle[0:4]="
          f"{[hex(x) for x in oracle_ks[:4]]}")
    return False


def compare(row: dict, o: dict) -> bool:
    """Re-check every RTL capture against the oracle in Python."""
    checks = [
        # I2C reads of the capability / identity registers (little-endian).
        ("Bksv (I2C @0x00, LE)", row.get("bksv"), hx(o["bksv"], 10)),
        ("Bcaps (I2C @0x40)", row.get("bcaps"), "80"),
        ("Bstatus (I2C @0x41, LE)", row.get("bstatus"), "1000"),
        # Km accumulator, balanced source KSV.
        ("Km_hw (balanced KSV_source)", row.get("km"), hx(o["km"], 14)),
        # Authentication R0' and the mod-128 Ri' link value.
        ("R0' (== oracle R0)", row.get("r0"), hx(o["r0"], 4)),
        ("Ri' via I2C @0x08 after auth (== R0')", row.get("ri_i2c_auth"), hx(o["r0"], 4)),
        ("Ri_link @frame 64 (== R0', pre-boundary)", row.get("ri64"), hx(o["r0"], 4)),
        ("Ri_link @frame 127 (== R0', pre-boundary)", row.get("ri127"), hx(o["r0"], 4)),
        ("Ri_link @frame 128 (frame-128 Ri)", row.get("ri128"), hx(o["ri128"], 4)),
        ("Ri_link @frame 200 (stable == Ri128)", row.get("ri200"), hx(o["ri128"], 4)),
        ("Ri_link @frame 256 (frame-256 Ri)", row.get("ri256"), hx(o["ri256"], 4)),
        ("Ri' via I2C @0x08 after 128 frames (== Ri128)", row.get("ri_i2c_128"), hx(o["ri128"], 4)),
        # The extra Aksv acceptance cases (any KSV accepted as-is).
        ("Km_hw for all-zero Aksv (blank OTP)", row.get("km_zero"), hx(o["km_zero"], 14)),
        ("Km_hw for non-balanced Aksv 0xff", row.get("km_ff"), hx(o["km_ff"], 14)),
        ("Aksv readback for non-balanced case", row.get("aksv_ff_rb"), hx(AKSV_FF, 10)),
    ]
    ok = True
    for label, got, want in checks:
        good = got is not None and got.lower() == want.lower()
        ok = ok and good
        print(f"  [{'ok  ' if good else 'FAIL'}] {label:<48} RTL={got} oracle={want}")

    # Boolean / self-check style results reported by the testbench.
    flags = [
        ("R0_valid_out pulsed once", row.get("r0valid"), "1"),
        ("frame_count reached >= 256", None, None),  # handled below
        ("encrypt->decrypt round trip recovered plaintext", row.get("roundtrip"), "1"),
        ("wrong-Km decrypt did NOT recover (negative case)", row.get("neg_fail"), "1"),
        ("keystream non-zero (all-zero Aksv still authenticates)", row.get("ks_zero_nz"), "1"),
        ("Km_valid asserted for all-zero Aksv", row.get("kmv_zero"), "1"),
        ("Km_valid asserted for non-balanced Aksv", row.get("kmv_ff"), "1"),
        ("testbench self-check errors == 0", row.get("errors"), "0"),
    ]
    for label, got, want in flags:
        if want is None:
            continue
        good = got is not None and got == want
        ok = ok and good
        print(f"  [{'ok  ' if good else 'FAIL'}] {label:<48} RTL={got} want={want}")

    frames = int(row.get("frames", "0"))
    good = frames >= 256
    ok = ok and good
    print(f"  [{'ok  ' if good else 'FAIL'}] frame_count reached {frames:<28} want>=256")

    # Encrypt->decrypt round trip: the captured keystream is the oracle stream.
    ok = check_keystream(o) and ok
    return ok


def main() -> int:
    try:
        o = oracle()
        print(f"oracle: Km={o['km']:014x} R0={o['r0']:04x} "
              f"Ri128={o['ri128']:04x} Ri256={o['ri256']:04x} "
              f"Km_bad={o['km_bad']:014x}")
        print(f"oracle: Km(Aksv=0)={o['km_zero']:014x} "
              f"Km(Aksv=0xff)={o['km_ff']:014x}")
        write_vectors(o)
        sim_out = build_and_sim()
        row = parse_results()
    except Blocked as e:
        print(f"BLOCKED: {e}")
        return 2

    tb_pass = "TB_PASS" in sim_out
    tb_fail = "TB_FAIL" in sim_out

    print("Re-checking RTL captures against the oracle:")
    py_ok = compare(row, o)

    if py_ok and tb_pass and not tb_fail:
        print("PASS")
        return 0

    if not tb_pass:
        print("testbench did not print TB_PASS (self-check failed or sim aborted)")
    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
