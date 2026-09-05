"""The test rig: one object that owns the console, the capture card, the
source agent and the overlay framebuffer, plus helpers shared by tests.

python 3.5 compatible.
"""

import os
import time

from . import patterns as P
from .agent_client import SourceAgent
from .console import Console
from .frames import CaptureError, ensure_dir, frame_luma, frame_to_image
from .overlay import Overlay
from .v4l2cap import Capture

AGENT_HOST = os.environ.get("NETV2_AGENT_HOST", "rpiz-3.welland.mithis.com")
CONSOLE_PORT = os.environ.get("NETV2_CONSOLE", "/dev/ttyS0")
VIDEO_DEV = os.environ.get("NETV2_VIDEO", "/dev/video0")

SRC_W, SRC_H = 1920, 1080
PIXCLK_1080P = 148.5
PIXCLK_720P = 74.25


class LockTimeout(Exception):
    pass


class Rig(object):
    def __init__(self, evidence_dir):
        self.evidence_dir = evidence_dir
        ensure_dir(evidence_dir)
        self.console = Console(CONSOLE_PORT)
        self.cap = Capture(VIDEO_DEV)
        self.agent = SourceAgent(AGENT_HOST)
        self.overlay = Overlay()
        self.metrics = {}
        self.src_w, self.src_h = SRC_W, SRC_H

    def close(self):
        for fn in (self.cap.close, self.agent.close, self.console.close):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    # ---- capture format --------------------------------------------------------
    def set_capture(self, w, h, pixfmt, fps):
        if (self.cap.width, self.cap.height, self.cap.pixfmt) == (w, h, pixfmt) and self.cap.streaming:
            return
        self.cap.set_format(w, h, pixfmt, fps)
        self.cap.start()
        # Re-negotiating the stream drops HPD briefly; the NeTV2 re-locks.
        self.wait_for_lock()

    def capture_hires(self):
        self.set_capture(1920, 1080, "YUYV", 10)

    def capture_fast(self):
        self.set_capture(720, 480, "YUYV", 60)

    def capture_mjpg(self):
        self.set_capture(1920, 1080, "MJPG", 60)

    # ---- lock handling -----------------------------------------------------
    def input0(self):
        return self.console.status()["inputs"].get(0, {})

    def locked(self, w=None, h=None, mhz=None):
        w = w or self.src_w
        h = h or self.src_h
        st = self.input0()
        if not st:
            return False
        if st["hres"] != w or st["vres"] != h:
            return False
        if mhz is not None and abs(st["mhz"] - mhz) > 0.3:
            return False
        return st["mhz"] > 1.0

    def wait_for_lock(self, timeout=45.0, w=None, h=None, mhz=None, stable=1.0):
        """Wait until the NeTV2 `status` reports the expected input0 resolution
        and pixel clock, held stable for `stable` seconds.  This is the
        authoritative 'NeTV2 has locked' signal and does not depend on the
        (intermittent) MS2109 capture card.  Returns seconds taken."""
        t0 = time.monotonic()
        deadline = t0 + timeout
        good_since = None
        last = {}
        while time.monotonic() < deadline:
            last = self.input0()
            if self.locked(w, h, mhz):
                if good_since is None:
                    good_since = time.monotonic()
                elif time.monotonic() - good_since >= stable:
                    dt = time.monotonic() - t0
                    self.metrics.setdefault("lock_times_s", []).append(round(dt, 2))
                    return dt
            else:
                good_since = None
            time.sleep(0.25)
        raise LockTimeout("input0 did not lock to %sx%s within %.0fs (last: %r)" % (
            w or self.src_w, h or self.src_h, timeout, last))

    def capture_has_signal(self):
        """The MS2109 emits a flat Y=7 frame when it has no input signal."""
        try:
            f = self.cap.latest(timeout=2.0)
        except RuntimeError:
            return False
        try:
            y = frame_luma(f)
        except CaptureError:
            return False
        return not (y.max() <= 8.0)

    SIGNAL_LUMA = 20.0

    def frame_is_signal(self, frame):
        try:
            return float(frame_luma(frame).max()) > self.SIGNAL_LUMA
        except CaptureError:
            return False

    def good_frame(self, timeout=20.0, settle=0.0):
        """Return the next capture frame that carries real signal (the MS2109
        drops to a flat no-signal frame much of the time).  Raises LockTimeout
        if none arrives within `timeout`."""
        t_min = time.monotonic() + settle
        deadline = time.monotonic() + timeout + settle
        while time.monotonic() < deadline:
            try:
                f = self.cap.latest(min_timestamp=t_min, timeout=min(2.0, max(0.1, deadline - time.monotonic())))
            except RuntimeError:
                continue
            t_min = f.timestamp
            if self.frame_is_signal(f):
                return f
        raise LockTimeout("no signal-bearing frame within %.0fs" % timeout)

    def good_image(self, timeout=20.0, settle=0.0, save_as=None):
        f = self.good_frame(timeout=timeout, settle=settle)
        img = frame_to_image(f)
        if save_as:
            img.save_ppm(os.path.join(self.evidence_dir, save_as))
        return img, f

    def measure_duty(self, seconds=6.0):
        """Fraction of captured frames that carry real signal, plus effective fps."""
        n = min(180, max(30, int(self.cap.fps or 30) * int(seconds)))
        frames = self.cap.record(n, timeout=seconds + 8)
        if not frames:
            return {"duty": 0.0, "fps": 0.0, "n": 0, "good": 0}
        good = sum(1 for f in frames if self.frame_is_signal(f))
        span = frames[-1].timestamp - frames[0].timestamp
        fps = (len(frames) - 1) / span if span > 0 else 0.0
        return {"duty": good / float(len(frames)), "fps": fps, "n": len(frames), "good": good}

    # ---- frames -----------------------------------------------------------------
    def fresh_image(self, settle=0.4, save_as=None):
        f = self.cap.fresh(settle=settle, timeout=10.0)
        img = frame_to_image(f)
        if save_as:
            img.save_ppm(os.path.join(self.evidence_dir, save_as))
        return img

    def strip_bits(self, img_or_luma, strip_y, cap_w, cap_h):
        """Decode the NBLOCKS block values of a counter strip from a luma plane."""
        luma = img_or_luma.luma if hasattr(img_or_luma, "luma") else img_or_luma
        vals = []
        for i in range(P.NBLOCKS):
            x0, y0, x1, y1 = P.strip_sample_box(strip_y, cap_w, cap_h, i)
            vals.append(float(luma[y0:y1, x0:x1].mean()))
        lo, hi = min(vals), max(vals)
        if hi - lo < 40:
            return None, vals
        thr = (lo + hi) / 2.0
        return [1 if v > thr else 0 for v in vals], vals

    def decode_counter(self, frame, strip_y):
        luma = frame_luma(frame)
        bits, vals = self.strip_bits(luma, strip_y, frame.width, frame.height)
        if bits is None:
            return None
        return P.decode_counter_bits(bits)

    # ---- source helpers -------------------------------------------------------
    def source_mode(self, w, h, refresh=60):
        self.agent.mode(w, h, refresh)
        self.src_w, self.src_h = w, h

    def source_pattern(self, name, **kw):
        return self.agent.pattern(name, **kw)
