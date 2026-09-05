#!/usr/bin/env python3
"""NeTV2 test-source agent.  Runs on rpiz-3 (the HDMI source feeding the
NeTV2 input) as root under systemd.  Owns the KMS display and draws test
patterns on request from the test runner over a newline-delimited JSON TCP
protocol (port 5910).

Requests are JSON objects with a "cmd" key.  Every reply carries "ok": true
or "ok": false + "error".  Monotonic timestamps are CLOCK_MONOTONIC seconds.

Commands
  ping                         -> {"t": <monotonic at receipt>}
  info                         -> connector status, edid size, mode, counter state
  mode  {"w","h","refresh"}    -> set mode (from connector modes or CEA fallback)
  pattern {"name", ...params}  -> draw a static pattern and flip; returns flip time
  counter {"enable": bool}     -> run the 60 Hz frame-counter loop on/off
  flips {"since": int}         -> list of [counter, flip_time] recorded since
  dpms  {"on": bool}           -> disable/enable the CRTC (source loss test)
  audio {"hz", "seconds"}      -> play a tone over HDMI audio (aplay), async
  edid                         -> raw EDID (hex) as currently seen by the kernel
  quit                         -> exit (systemd restarts the service)

Patterns
  solid   {"rgb": [r,g,b]}
  bars    {}                    colour bars + grey ramp (patterns.BAR_COLOURS)
  geometry {}                   corner squares, centre square, marker, border
  strip   {"rgb_bg": [r,g,b], "counter": int}   background + one counter strip
"""

import json
import os
import select
import socket
import subprocess
import sys
import time
import traceback

import numpy as np
import pykms

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patterns as P  # noqa: E402

PORT = 5910
CONNECTOR_PREFIX = "HDMI"
MAX_FLIP_LOG = 8192

# CEA-861 timings used when the connector has no EDID (disconnected).
CEA_MODES = {
    (1920, 1080, 60): (148500, 1920, 88, 44, 148, 1080, 4, 5, 36),
    (1280, 720, 60): (74250, 1280, 110, 40, 220, 720, 5, 5, 20),
}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Display:
    def __init__(self):
        self.card = pykms.Card()
        conns = [c for c in self.card.connectors if c.fullname.startswith(CONNECTOR_PREFIX)]
        if not conns:
            raise RuntimeError("no HDMI connector")
        self.conn = conns[0]
        self.crtc = self.conn.get_possible_crtcs()[0]
        self.w = 0
        self.h = 0
        self.mode = None
        self.fbs = []
        self.arrays = []
        self.front = 0
        self.flip_pending = False
        self.counter_enabled = False
        self.counter = 0
        self.counter_bg = (0, 0, 0)
        self.flip_log = []      # list of (counter, flip_time)
        self.last_flip_time = None
        self.enabled = False
        self.pattern = None

    # -- mode handling ------------------------------------------------------
    def find_mode(self, w, h, refresh):
        self.conn.refresh()
        for m in self.conn.get_modes():
            if m.hdisplay == w and m.vdisplay == h and m.vrefresh == refresh:
                return m
        key = (w, h, refresh)
        if key in CEA_MODES:
            t = CEA_MODES[key]
            m = pykms.videomode_from_timings(*t)
            # CEA 1080p/720p use positive sync polarities:
            # DRM_MODE_FLAG_PHSYNC (1) | DRM_MODE_FLAG_PVSYNC (4)
            m.flags = 5
            return m
        raise RuntimeError("no mode %dx%d@%d" % (w, h, refresh))

    def set_mode(self, w, h, refresh=60):
        m = self.find_mode(w, h, refresh)
        self.fbs = [pykms.DumbFramebuffer(self.card, w, h, "XR24") for _ in range(2)]
        self.arrays = []
        for fb in self.fbs:
            a = np.frombuffer(fb.map(0), dtype=np.uint32).reshape(h, fb.stride(0) // 4)
            self.arrays.append(a[:, :w])
        for a in self.arrays:
            a[:, :] = 0
        self.w, self.h, self.mode = w, h, m
        self.front = 0
        self.crtc.set_mode(self.conn, self.fbs[0], m)
        self.enabled = True
        self.flip_pending = False
        log("mode set", m.to_string_long())
        return m

    def disable(self):
        self.crtc.disable_mode()
        self.enabled = False
        self.flip_pending = False
        log("crtc disabled")

    def enable(self):
        if self.mode is None:
            self.set_mode(1920, 1080, 60)
        else:
            self.crtc.set_mode(self.conn, self.fbs[self.front], self.mode)
            self.enabled = True
            self.flip_pending = False
        log("crtc enabled")

    # -- drawing --------------------------------------------------------------
    @staticmethod
    def rgb(r, g, b):
        return (int(r) << 16) | (int(g) << 8) | int(b)

    def back(self):
        return self.arrays[1 - self.front]

    def draw_strip(self, a, strip_y, counter):
        bits = P.counter_bits(counter)
        y0 = strip_y
        y1 = min(self.h, strip_y + P.STRIP_H)
        for i, b in enumerate(bits):
            x0 = i * P.BLOCK
            x1 = min(self.w, x0 + P.BLOCK)
            a[y0:y1, x0:x1] = 0x00FFFFFF if b else 0

    def draw_solid(self, a, rgb):
        a[:, :] = self.rgb(*rgb)

    def draw_bars(self, a):
        a[:, :] = 0
        bw = self.w // 8
        split = int(P.BARS_SPLIT_Y * self.h / P.H)
        for i, c in enumerate(P.BAR_COLOURS):
            a[:split, i * bw:(i + 1) * bw] = self.rgb(*c)
        for i, g in enumerate(P.GREY_STEPS):
            a[split:, i * bw:(i + 1) * bw] = self.rgb(g, g, g)

    def draw_geometry(self, a):
        a[:, :] = 0
        s = P.GEO_CORNER
        white = 0x00FFFFFF
        a[0:s, 0:s] = white
        a[0:s, self.w - s:self.w] = white
        a[self.h - s:self.h, 0:s] = white
        a[self.h - s:self.h, self.w - s:self.w] = white
        x, y, bw, bh = P.GEO_CENTRE
        a[y:y + bh, x:x + bw] = white
        x, y, bw, bh = P.GEO_MARK
        a[y:y + bh, x:x + bw] = white
        b = P.GEO_BORDER
        a[0:b, :] = white
        a[self.h - b:self.h, :] = white
        a[:, 0:b] = white
        a[:, self.w - b:self.w] = white

    def draw_pattern(self, name, params):
        a = self.back()
        if name == "solid":
            self.draw_solid(a, params.get("rgb", [0, 0, 0]))
        elif name == "bars":
            self.draw_bars(a)
        elif name == "geometry":
            self.draw_geometry(a)
        elif name == "strip":
            self.draw_solid(a, params.get("rgb_bg", [0, 0, 0]))
            self.draw_strip(a, P.SRC_STRIP_Y, int(params.get("counter", 0)))
        else:
            raise RuntimeError("unknown pattern " + name)
        self.pattern = name

    # -- flipping -------------------------------------------------------------
    def flip(self, data=0):
        """Queue a flip to the back buffer.  Caller must wait for the event."""
        if not self.enabled:
            raise RuntimeError("crtc disabled")
        if self.flip_pending:
            raise RuntimeError("flip already pending")
        self.crtc.page_flip(self.fbs[1 - self.front], data)
        self.flip_pending = True

    def wait_flip(self, timeout=1.0):
        deadline = time.monotonic() + timeout
        while self.flip_pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("flip timeout")
            r, _, _ = select.select([self.card.fd], [], [], remaining)
            if r:
                self.handle_events()
        return self.last_flip_time

    def handle_events(self):
        for ev in self.card.read_events():
            if ev.type == pykms.DrmEventType.FLIP_COMPLETE:
                self.front = 1 - self.front
                self.flip_pending = False
                self.last_flip_time = ev.time
                if self.counter_enabled:
                    self.flip_log.append((ev.data, ev.time))
                    if len(self.flip_log) > MAX_FLIP_LOG:
                        del self.flip_log[:len(self.flip_log) - MAX_FLIP_LOG]
                    self.queue_next_counter()

    def queue_next_counter(self):
        self.counter = (self.counter + 1) & 0xFFFF
        a = self.back()
        # Only the strip changes; the background was drawn when enabling.
        self.draw_strip(a, P.SRC_STRIP_Y, self.counter)
        self.flip(self.counter)

    def counter_start(self, bg):
        self.counter_bg = bg
        for a in self.arrays:
            self.draw_solid(a, bg)
        self.flip_log = []
        self.counter = 0
        self.counter_enabled = True
        self.draw_strip(self.back(), P.SRC_STRIP_Y, self.counter)
        self.flip(self.counter)
        self.pattern = "counter"

    def counter_stop(self):
        self.counter_enabled = False
        if self.flip_pending:
            try:
                self.wait_flip()
            except RuntimeError:
                pass

    # -- info -------------------------------------------------------------
    def edid(self):
        import glob
        for path in glob.glob("/sys/class/drm/card*-%s/edid" % self.conn.fullname):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except OSError:
                pass
        return b""

    def info(self):
        self.conn.refresh()
        d = {
            "connector": self.conn.fullname,
            "connected": bool(self.conn.connected()),
            "edid_bytes": len(self.edid()),
            "enabled": self.enabled,
            "mode": self.mode.to_string_long() if self.mode else None,
            "w": self.w,
            "h": self.h,
            "pattern": self.pattern,
            "counter_enabled": self.counter_enabled,
            "counter": self.counter,
            "flips_logged": len(self.flip_log),
            "last_flip_time": self.last_flip_time,
            "t": time.monotonic(),
        }
        return d


class Agent:
    def __init__(self):
        self.disp = Display()
        self.disp.set_mode(1920, 1080, 60)
        self.disp.draw_pattern("solid", {"rgb": [0, 0, 0]})
        self.disp.flip()
        self.disp.wait_flip()
        self.srv = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        self.srv.bind(("::", PORT))
        self.srv.listen(4)
        self.clients = {}
        self.audio_proc = None
        log("listening on port", PORT)

    def serve_forever(self):
        while True:
            fds = [self.srv, self.disp.card.fd] + list(self.clients.keys())
            r, _, _ = select.select(fds, [], [], 1.0)
            for fd in r:
                if fd is self.srv:
                    c, addr = self.srv.accept()
                    c.setblocking(True)
                    self.clients[c] = b""
                    log("client", addr)
                elif fd == self.disp.card.fd:
                    self.disp.handle_events()
                else:
                    self.read_client(fd)

    def read_client(self, c):
        try:
            data = c.recv(65536)
        except OSError:
            data = b""
        if not data:
            c.close()
            del self.clients[c]
            return
        buf = self.clients[c] + data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                req = json.loads(line.decode())
                resp = self.handle(req)
                resp["ok"] = True
            except Exception as e:  # noqa: BLE001
                log("error:", traceback.format_exc())
                resp = {"ok": False, "error": str(e)}
            try:
                c.sendall((json.dumps(resp) + "\n").encode())
            except OSError:
                pass
        self.clients[c] = buf

    def handle(self, req):
        cmd = req.get("cmd")
        d = self.disp
        if cmd == "ping":
            return {"t": time.monotonic()}
        if cmd == "info":
            return d.info()
        if cmd == "edid":
            return {"edid_hex": d.edid().hex()}
        if cmd == "mode":
            d.counter_stop()
            m = d.set_mode(int(req["w"]), int(req["h"]), int(req.get("refresh", 60)))
            d.draw_pattern("solid", {"rgb": [0, 0, 0]})
            d.flip()
            d.wait_flip()
            return {"mode": m.to_string_long()}
        if cmd == "pattern":
            d.counter_stop()
            d.draw_pattern(req["name"], req)
            d.flip()
            t = d.wait_flip()
            return {"flip_time": t}
        if cmd == "counter":
            if req.get("enable"):
                d.counter_stop()
                d.counter_start(tuple(req.get("rgb_bg", [0, 0, 0])))
                return {"started": True}
            d.counter_stop()
            return {"stopped": True, "flips_logged": len(d.flip_log)}
        if cmd == "flips":
            since = int(req.get("since", -1))
            out = [[c, t] for (c, t) in d.flip_log if c > since]
            return {"flips": out}
        if cmd == "dpms":
            d.counter_stop()
            if req.get("on"):
                d.enable()
            else:
                d.disable()
            return {"enabled": d.enabled}
        if cmd == "audio":
            return self.audio(float(req.get("hz", 1000)), float(req.get("seconds", 3)))
        if cmd == "quit":
            log("quit requested")
            os._exit(0)
        raise RuntimeError("unknown cmd %r" % cmd)

    def audio(self, hz, seconds):
        """Play a sine tone on the HDMI ALSA device using aplay (async)."""
        if self.audio_proc and self.audio_proc.poll() is None:
            self.audio_proc.kill()
        rate = 48000
        n = int(rate * seconds)
        t = np.arange(n) / rate
        pcm = (np.sin(2 * np.pi * hz * t) * 0.5 * 32767).astype("<i2")
        stereo = np.repeat(pcm[:, None], 2, axis=1).tobytes()
        path = "/run/netv2_tone.raw"
        with open(path, "wb") as f:
            f.write(stereo)
        dev = os.environ.get("NETV2_HDMI_ALSA", "hw:CARD=vc4hdmi,DEV=0")
        cmd = ["aplay", "-q", "-D", dev, "-t", "raw", "-f", "S16_LE", "-c", "2",
               "-r", str(rate), path]
        self.audio_proc = subprocess.Popen(cmd)
        return {"device": dev, "hz": hz, "seconds": seconds}


def main():
    agent = Agent()
    agent.serve_forever()


if __name__ == "__main__":
    main()
