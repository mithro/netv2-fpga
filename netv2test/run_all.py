#!/usr/bin/env python3
"""Run the whole NeTV2 HDMI test suite end-to-end on rpi3-netv2.

    python3 -m netv2test.run_all [--list] [--only T04,T09] [--quick]

Produces reports/<timestamp>/{report.json, report.md} and evidence PPMs.
Exit code 0 only if there are zero FAILs (BLOCKED/SKIP do not fail the run,
but are reported prominently).  This is designed to run with no human present.
"""

import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from netv2test import suite            # noqa: E402
from netv2test.rig import Rig          # noqa: E402
from netv2test.suite import BLOCKED, FAIL, PASS, SKIP, run_one  # noqa: E402


def reset_capture_card():
    """USB re-enumerate the MS2109 so each run starts from a known state."""
    import glob
    import subprocess
    for idp in glob.glob("/sys/bus/usb/devices/*/idProduct"):
        base = os.path.dirname(idp)
        try:
            with open(idp) as f:
                pid = f.read().strip()
            with open(os.path.join(base, "idVendor")) as f:
                vid = f.read().strip()
        except OSError:
            continue
        if vid == "345f" and pid == "2109":
            dev = os.path.basename(base)
            def _sysfs_write(target, value):
                p = subprocess.Popen(["sudo", "-n", "tee", target],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                p.communicate(value.encode())
            try:
                _sysfs_write("/sys/bus/usb/drivers/usb/unbind", dev)
                time.sleep(2)
                _sysfs_write("/sys/bus/usb/drivers/usb/bind", dev)
                time.sleep(3)
                return dev
            except Exception:  # noqa: BLE001
                return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-reset", action="store_true", help="skip USB reset of the capture card")
    ap.add_argument("--capture", default="yuyv480", choices=["mjpg", "yuyv480", "yuyv1080"])
    args = ap.parse_args()

    tests = suite.all_tests()
    if args.only:
        want = set(x.strip() for x in args.only.split(","))
        tests = [t for t in tests if t[0] in want]
    if args.list:
        for tid, area, needs_cap, _ in tests:
            print("%-5s %-9s %s" % (tid, area, "cap" if needs_cap else ""))
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    repdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", stamp)
    evdir = os.path.join(repdir, "evidence")

    print("== NeTV2 HDMI test suite ==  reports -> %s" % repdir)
    if not args.no_reset:
        print("resetting MS2109 capture card ...")
        dev = reset_capture_card()
        print("  re-enumerated at %s" % dev)

    rig = Rig(evdir)
    # Bring the chain up on a known pattern + capture format.
    fmt = {"mjpg": ("capture_mjpg",), "yuyv480": ("capture_fast",), "yuyv1080": ("capture_hires",)}[args.capture]
    getattr(rig, fmt[0])()          # start capture (asserts HPD, re-applies source mode)
    rig.source_pattern("geometry")
    rig.wait_for_lock(timeout=60)
    duty = rig.measure_duty(6.0)
    print("capture health: duty %.0f%% @ %.0f fps (%d/%d good)" % (
        duty["duty"] * 100, duty["fps"], duty["good"], duty["n"]))

    env = {
        "started": datetime.datetime.now().isoformat(),
        "capture_format": args.capture,
        "capture_health": duty,
        "agent_info": rig.agent.info(),
        "dna": rig.console.dna(),
    }

    results = []
    try:
        for tid, area, needs_cap, fn in tests:
            sys.stdout.write("  %-5s %-9s ... " % (tid, area))
            sys.stdout.flush()
            r = run_one(rig, tid, area, needs_cap, fn)
            results.append(r)
            print("%-7s (%.1fs) %s" % (r.status, r.duration, _short(r)))
    finally:
        # restore FPGA / overlay / source state
        try:
            rig.console.rect_default()
            rig.console.rect_thresh(20)
        except Exception:  # noqa: BLE001
            pass
        try:
            if rig.overlay.arr is not None:
                rig.overlay.restore()
        except Exception:  # noqa: BLE001
            pass
        try:
            rig.source_pattern("solid", rgb=[0, 0, 0])
        except Exception:  # noqa: BLE001
            pass
        rig.close()

    counts = {PASS: 0, FAIL: 0, BLOCKED: 0, SKIP: 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    report = {"env": env, "counts": counts, "results": [r.as_dict() for r in results],
              "finished": datetime.datetime.now().isoformat()}
    with open(os.path.join(repdir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    _write_md(os.path.join(repdir, "report.md"), report)

    print("\n== summary ==")
    print("  PASS %d  FAIL %d  BLOCKED %d  SKIP %d" % (counts[PASS], counts[FAIL], counts[BLOCKED], counts[SKIP]))
    if counts[FAIL]:
        print("  FAILURES:")
        for r in results:
            if r.status == FAIL:
                print("   %s %s: %s" % (r.tid, r.area, r.detail.splitlines()[0] if r.detail else ""))
    if counts[BLOCKED]:
        print("  BLOCKED (capture card, not NeTV2):")
        for r in results:
            if r.status == BLOCKED:
                print("   %s %s: %s" % (r.tid, r.area, r.detail))
    print("  report: %s/report.md" % repdir)
    return 1 if counts[FAIL] else 0


def _short(r):
    if r.status == PASS:
        return ""
    return (r.detail or "").splitlines()[0][:80]


def _write_md(path, report):
    c = report["counts"]
    lines = []
    lines.append("# NeTV2 HDMI test suite report")
    lines.append("")
    lines.append("- Started: %s" % report["env"]["started"])
    lines.append("- Board DNA: `%s`" % report["env"].get("dna"))
    h = report["env"]["capture_health"]
    lines.append("- Capture health: duty %.0f%% @ %.0f fps (MS2109 %d/%d good frames)" % (
        h["duty"] * 100, h["fps"], h["good"], h["n"]))
    lines.append("- Result: **PASS %d / FAIL %d / BLOCKED %d / SKIP %d**" % (
        c["PASS"], c["FAIL"], c["BLOCKED"], c["SKIP"]))
    lines.append("")
    lines.append("| ID | Area | Status | Detail / key metrics |")
    lines.append("|----|------|--------|----------------------|")
    for r in report["results"]:
        m = r["metrics"]
        keys = ", ".join("%s=%s" % (k, m[k]) for k in list(m)[:4])
        det = (r["detail"] or "").splitlines()[0] if r["status"] != "PASS" else keys
        det = det.replace("|", "\\|")[:140]
        lines.append("| %s | %s | %s | %s |" % (r["id"], r["area"], r["status"], det))
    lines.append("")
    lines.append("## Full metrics")
    lines.append("```json")
    lines.append(json.dumps([{"id": r["id"], "status": r["status"], "metrics": r["metrics"],
                              "evidence": r["evidence"]} for r in report["results"]], indent=1))
    lines.append("```")
    with open(path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
