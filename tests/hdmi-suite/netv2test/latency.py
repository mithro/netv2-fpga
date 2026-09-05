"""Latency measurement via Gray-coded frame counters.

Two independent counter strips are decodable from a single captured frame:

  * SRC strip  (patterns.SRC_STRIP_Y): drawn by the *source* (rpiz-3) each KMS
    page-flip.  The source records (counter, flip_time) with CLOCK_MONOTONIC on
    rpiz-3.  With the source-to-runner clock offset this gives the
    *passthrough* latency  L_pt = t_capture - flip_time.

  * OVL strip  (patterns.OVL_STRIP_Y): drawn by the *overlay* (rpi3-netv2's own
    HDMI -> NeTV2 overlay input) each fb vsync.  Recorded (counter, write_time)
    is on the runner's own clock, so the *overlay* latency is
    L_ov = t_capture - write_time  (no cross-machine offset).

Both strips share the MS2109 + USB + decode latency, so

  NeTV2 overlay-path latency = mean(L_ov) - mean(L_pt)

cancels the capture-card contribution.

python 3.5 compatible.
"""

import threading
import time

from . import patterns as P


class OverlayCounter(object):
    """Drives the overlay fb0 counter strip at vsync in a background thread and
    records (counter -> write_time) on the runner's monotonic clock."""

    def __init__(self, overlay):
        self.ov = overlay
        self._stop = threading.Event()
        self._thread = None
        self.log = {}          # counter -> write_time
        self.counter = 0

    def start(self, bg=(0, 0, 0)):
        # Black background so the source shows through where overlay is dark.
        self.ov.fill(bg)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            self.counter = (self.counter + 1) & 0xFFFF
            self.ov.strip(self.counter, P.OVL_STRIP_Y)
            try:
                t = self.ov.wait_vsync()
            except OSError:
                t = time.monotonic()
            self.log[self.counter] = t

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)


def collect_samples(rig, src_flip_map, ovl_counter, offset, duration=8.0):
    """Capture for `duration` s, decode both strips from each good frame, and
    return per-frame latency samples.

    src_flip_map: {counter: flip_time_remote} from the source agent.
    offset: remote_monotonic - local_monotonic (from SourceAgent.sync_clock).
    Returns (pt_samples, ov_samples, nframes, ngood).
    """
    from .frames import CaptureError, frame_luma
    pt = []
    ov = []
    ngood = 0
    nframes = 0
    n = max(30, int((rig.cap.fps or 30) * duration))
    frames = rig.cap.record(n, timeout=duration + 10)
    for f in frames:
        nframes += 1
        try:
            luma = frame_luma(f)
        except CaptureError:
            continue
        if luma.max() <= rig.SIGNAL_LUMA:
            continue
        ngood += 1
        t_cap = f.timestamp
        sbits, _ = rig.strip_bits(luma, P.SRC_STRIP_Y, f.width, f.height)
        obits, _ = rig.strip_bits(luma, P.OVL_STRIP_Y, f.width, f.height)
        if sbits is not None:
            c = P.decode_counter_bits(sbits)
            if c is not None and c in src_flip_map:
                lt = src_flip_map[c] - offset      # remote->local
                pt.append(t_cap - lt)
        if obits is not None:
            c = P.decode_counter_bits(obits)
            if c is not None and c in ovl_counter.log:
                ov.append(t_cap - ovl_counter.log[c])
    return pt, ov, nframes, ngood


def stats(xs):
    if not xs:
        return {"n": 0}
    xs = sorted(xs)
    n = len(xs)
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n
    return {
        "n": n,
        "mean_ms": mean * 1e3,
        "min_ms": xs[0] * 1e3,
        "max_ms": xs[-1] * 1e3,
        "median_ms": xs[n // 2] * 1e3,
        "std_ms": (var ** 0.5) * 1e3,
    }
