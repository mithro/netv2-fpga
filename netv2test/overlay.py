"""Overlay control: draw on rpi3-netv2's own HDMI output (/dev/fb0, legacy
BCM2708 framebuffer, 1920x1080 XRGB32) which feeds the NeTV2 overlay input.

The desktop (lightdm/X + MagicMirror under pm2) normally owns the screen.
`Overlay.prepare()` stops them for the test run and `restore()` brings them
back.  python 3.5 compatible.

Note: this Pi's HDMI is configured as limited-range RGB (tvservice: "RGB lim"),
so a framebuffer value V reaches the NeTV2 as roughly 16 + V*219/255.  Use
`wire_level(V)` when reasoning about the NeTV2's rect_thresh comparison.
"""

import fcntl
import mmap
import os
import struct
import subprocess
import time

import numpy as np

from . import patterns as P

FBIO_WAITFORVSYNC = 0x40044620   # _IOW('F', 0x20, __u32)
PM2 = "/home/pi/n/bin/pm2"


def wire_level(v):
    return 16.0 + v * 219.0 / 255.0


def _run(cmd, check=True):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = p.communicate()
    if check and p.returncode != 0:
        raise RuntimeError("%s failed (%d): %s" % (" ".join(cmd), p.returncode, out.decode(errors="replace")))
    return out.decode(errors="replace")


class Overlay(object):
    def __init__(self, dev="/dev/fb0"):
        self.dev = dev
        self.fd = None
        self.mm = None
        self.arr = None
        self.w = 1920
        self.h = 1080
        self.stride = 7680
        self.prior = {}

    # ---- system state --------------------------------------------------------
    def read_state(self):
        state = {}
        out = _run(["sudo", "-n", "systemctl", "is-active", "lightdm"], check=False).strip()
        state["lightdm_active"] = (out == "active")
        out = _run([PM2, "jlist"], check=False)
        state["pm2_mm_online"] = '"name":"mm"' in out.replace(" ", "") and '"status":"online"' in out.replace(" ", "")
        return state

    def prepare(self):
        """Take over the display.  Records prior state for restore()."""
        self.prior = self.read_state()
        if self.prior.get("pm2_mm_online"):
            _run([PM2, "stop", "mm"], check=False)
        if self.prior.get("lightdm_active"):
            _run(["sudo", "-n", "systemctl", "stop", "lightdm"])
            time.sleep(2.0)
        # Quiet console: switch to an unused VT, hide cursor, mute printk.
        _run(["sudo", "-n", "chvt", "7"], check=False)
        _run(["sudo", "-n", "sh", "-c", "setterm -cursor off > /dev/tty7"], check=False)
        _run(["sudo", "-n", "dmesg", "-n", "1"], check=False)
        _run(["sudo", "-n", "sh", "-c", "echo 0 > /sys/class/graphics/fbcon/cursor_blink"], check=False)
        self.open()
        self.fill((0, 0, 0))

    def restore(self):
        try:
            if self.arr is not None:
                self.fill((0, 0, 0))
        finally:
            self.close()
        _run(["sudo", "-n", "dmesg", "-n", "7"], check=False)
        _run(["sudo", "-n", "chvt", "1"], check=False)
        if self.prior.get("lightdm_active"):
            _run(["sudo", "-n", "systemctl", "start", "lightdm"], check=False)
        if self.prior.get("pm2_mm_online"):
            _run([PM2, "start", "mm"], check=False)

    # ---- framebuffer ------------------------------------------------------------
    def open(self):
        with open("/sys/class/graphics/fb0/virtual_size") as f:
            w, h = [int(x) for x in f.read().strip().split(",")]
        with open("/sys/class/graphics/fb0/stride") as f:
            stride = int(f.read().strip())
        with open("/sys/class/graphics/fb0/bits_per_pixel") as f:
            bpp = int(f.read().strip())
        if bpp != 32:
            raise RuntimeError("fb0 is %d bpp, expected 32" % bpp)
        self.w, self.h, self.stride = w, h, stride
        self.fd = os.open(self.dev, os.O_RDWR)
        self.mm = mmap.mmap(self.fd, stride * h, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        full = np.frombuffer(self.mm, dtype=np.uint32).reshape(h, stride // 4)
        self.arr = full[:, :w]

    def close(self):
        self.arr = None
        if self.mm is not None:
            self.mm.close()
            self.mm = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def wait_vsync(self):
        fcntl.ioctl(self.fd, FBIO_WAITFORVSYNC, struct.pack("<I", 0))
        return time.monotonic()

    @staticmethod
    def rgb(r, g, b):
        return (int(r) << 16) | (int(g) << 8) | int(b)

    def fill(self, rgb):
        self.arr[:, :] = self.rgb(*rgb)

    def block(self, x, y, w, h, rgb):
        self.arr[y:y + h, x:x + w] = self.rgb(*rgb)

    def strip(self, counter, y=P.OVL_STRIP_Y):
        bits = P.counter_bits(counter)
        y1 = min(self.h, y + P.STRIP_H)
        for i, b in enumerate(bits):
            x0 = i * P.BLOCK
            self.arr[y:y1, x0:x0 + P.BLOCK] = 0x00FFFFFF if b else 0

    def frame_border(self, x0, x1, y0, y1, thickness=2, rgb=(255, 255, 255)):
        v = self.rgb(*rgb)
        self.arr[y0:y0 + thickness, x0:x1] = v
        self.arr[y1 - thickness:y1, x0:x1] = v
        self.arr[y0:y1, x0:x0 + thickness] = v
        self.arr[y0:y1, x1 - thickness:x1] = v
