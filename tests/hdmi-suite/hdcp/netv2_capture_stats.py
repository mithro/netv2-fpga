#!/usr/bin/env python3
"""Capture a frame from the NeTV2 output (MS2109 /dev/video0) and report luma
statistics that discriminate a clean image (structured, low entropy) from
HDCP-encrypted noise (pseudo-random, ~8-bit entropy). Saves the raw frame.

Run on rpi3-netv2 from ~ (netv2test on path). Arg: output tag.
"""
import math
import sys
import time
sys.path.insert(0, "/home/pi")
from netv2test.v4l2cap import Capture

tag = sys.argv[1] if len(sys.argv) > 1 else "frame"


def luma_stats(data):
    y = data[0::2]  # YUYV luma bytes
    n = len(y)
    hist = [0] * 256
    for b in y:
        hist[b] += 1
    mean = sum(i * c for i, c in enumerate(hist)) / n
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / n
    ent = 0.0
    for c in hist:
        if c:
            p = c / n
            ent -= p * math.log2(p)
    distinct = sum(1 for c in hist if c)
    return n, mean, var, ent, distinct


cap = Capture("/dev/video0")
cap.set_format(720, 480, "YUYV", 60)
cap.start()
# let HPD/lock settle, then take best-of-N by luma variance (beat capture flakiness)
time.sleep(1.5)
best = None
best_var = -1.0
seen = 0
for _ in range(80):
    f = cap.latest(timeout=2.0)
    if not f or f.bytesused < 100000:
        time.sleep(0.03); continue
    seen += 1
    d = bytes(f.data[:f.bytesused])
    _, _, v, _, _ = luma_stats(d)
    if v > best_var:
        best_var = v; best = f
    time.sleep(0.02)
cap.stop()
frame = best
print("frames_with_data=%d best_var=%.1f" % (seen, best_var))

if not frame:
    print("NO FRAME (capture starved)")
    sys.exit(3)

data = bytes(frame.data[:frame.bytesused])
n, mean, var, ent, distinct = luma_stats(data)
path = "/home/pi/cap/hdcp_%s.yuyv" % tag
open(path, "wb").write(data)
verdict = "NOISE/ENCRYPTED?" if (ent > 7.3 and distinct > 200) else "STRUCTURED/CLEAN?"
print("[%s] bytes=%d luma: mean=%.1f var=%.1f entropy=%.3f bits distinct=%d -> %s  saved=%s"
      % (tag, frame.bytesused, mean, var, ent, distinct, verdict, path))
