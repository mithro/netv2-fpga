"""NeTV2 HDMI test suite.

A lightweight, ordered test framework (python 3.5 compatible) tailored to this
hardware rig.  Each test returns a Result with an explicit status:

  PASS     - verified working
  FAIL     - a NeTV2 / chain defect (this is what must be zero)
  BLOCKED  - could not verify because the MS2109 capture card gave no usable
             frame in the time budget (a capture-card limitation, not a NeTV2
             fault).  Reported separately so capture flakiness never masquerades
             as a NeTV2 pass or fail.
  SKIP     - not applicable on this hardware (documented gaps)

Tests are registered with @test(id, area, needs_capture) and run in id order by
run_all.py.  They share one Rig.
"""

import time
import traceback

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
SKIP = "SKIP"

_REGISTRY = []


class Result(object):
    def __init__(self, tid, area, status, detail="", metrics=None, evidence=None):
        self.tid = tid
        self.area = area
        self.status = status
        self.detail = detail
        self.metrics = metrics or {}
        self.evidence = evidence or []
        self.duration = 0.0

    def as_dict(self):
        return {
            "id": self.tid, "area": self.area, "status": self.status,
            "detail": self.detail, "metrics": self.metrics,
            "evidence": self.evidence, "duration_s": round(self.duration, 2),
        }


class TestCtx(object):
    """Passed to each test; accumulates assertions, metrics and evidence."""

    def __init__(self, rig, tid, area):
        self.rig = rig
        self.tid = tid
        self.area = area
        self.metrics = {}
        self.evidence = []
        self._msgs = []

    def note(self, msg):
        self._msgs.append(msg)

    def metric(self, key, value):
        self.metrics[key] = value

    def evidence_ppm(self, image, name):
        import os
        path = os.path.join(self.rig.evidence_dir, name)
        image.save_ppm(path)
        self.evidence.append(name)

    def check(self, cond, msg):
        if not cond:
            raise AssertionError(msg)
        self._msgs.append("OK: " + msg)

    def close_to(self, actual, expected, tol, msg):
        if abs(actual - expected) > tol:
            raise AssertionError("%s: %.3f not within %.3f of %.3f" % (msg, actual, expected, tol))
        self._msgs.append("OK: %s (%.3f ~= %.3f +-%.3f)" % (msg, actual, expected, tol))

    def detail(self):
        return " | ".join(self._msgs)


class Blocked(Exception):
    """Raise to mark a test BLOCKED (capture card gave no usable frame)."""


class Skip(Exception):
    pass


def test(tid, area, needs_capture=False):
    def deco(fn):
        _REGISTRY.append((tid, area, needs_capture, fn))
        return fn
    return deco


def all_tests():
    return sorted(_REGISTRY, key=lambda t: t[0])


def run_one(rig, tid, area, needs_capture, fn):
    ctx = TestCtx(rig, tid, area)
    t0 = time.monotonic()
    try:
        fn(rig, ctx)
        status, detail = PASS, ctx.detail()
    except Skip as e:
        status, detail = SKIP, str(e)
    except Blocked as e:
        status, detail = BLOCKED, str(e)
    except AssertionError as e:
        status, detail = FAIL, str(e)
    except Exception as e:  # noqa: BLE001
        # LockTimeout from a needs_capture test => BLOCKED, else FAIL.
        name = e.__class__.__name__
        if needs_capture and name == "LockTimeout":
            status, detail = BLOCKED, "capture: " + str(e)
        else:
            status, detail = FAIL, "%s: %s\n%s" % (name, e, traceback.format_exc())
    r = Result(tid, area, status, detail, ctx.metrics, ctx.evidence)
    r.duration = time.monotonic() - t0
    return r


# Import the test definitions (registers them via @test).
from . import tests as _tests  # noqa: E402,F401
