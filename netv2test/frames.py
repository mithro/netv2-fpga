"""Frame analysis helpers (python 3.5 + numpy 1.12; no PIL/cv2).

YUYV frames are handled natively.  MJPG frames are decoded with the
`djpeg` command from libjpeg-turbo (present on rpi3-netv2) into binary PPM.
"""

import os
import subprocess

import numpy as np


class Image(object):
    """RGB uint8 image (h, w, 3) plus a luma plane."""

    def __init__(self, rgb):
        self.rgb = rgb
        self.h, self.w = rgb.shape[0], rgb.shape[1]
        r = rgb[..., 0].astype(np.float32)
        g = rgb[..., 1].astype(np.float32)
        b = rgb[..., 2].astype(np.float32)
        self.luma = (0.299 * r + 0.587 * g + 0.114 * b)

    def box_mean(self, box):
        x0, y0, x1, y1 = box
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.w, x1)
        y1 = min(self.h, y1)
        if x1 <= x0 or y1 <= y0:
            raise ValueError("empty box %r" % (box,))
        region = self.rgb[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
        return tuple(float(v) for v in region.mean(axis=0))

    def box_luma(self, box):
        x0, y0, x1, y1 = box
        return float(self.luma[max(0, y0):y1, max(0, x0):x1].mean())

    def save_ppm(self, path):
        with open(path, "wb") as f:
            f.write(("P6\n%d %d\n255\n" % (self.w, self.h)).encode("ascii"))
            f.write(np.ascontiguousarray(self.rgb).tobytes())


def yuyv_to_rgb(data, w, h):
    a = np.frombuffer(data, dtype=np.uint8)
    if a.size != w * h * 2:
        raise ValueError("YUYV size mismatch: %d != %d" % (a.size, w * h * 2))
    a = a.reshape(h, w // 2, 4).astype(np.float32)
    y = np.empty((h, w), dtype=np.float32)
    y[:, 0::2] = a[..., 0]
    y[:, 1::2] = a[..., 2]
    u = np.repeat(a[..., 1], 2, axis=1)
    v = np.repeat(a[..., 3], 2, axis=1)
    # BT.601 limited-range YCbCr -> full-range RGB (what the MS2109 emits for
    # an RGB HDMI source; verified empirically against the colour-bar test).
    c = (y - 16.0) * (255.0 / 219.0)
    d = u - 128.0
    e = v - 128.0
    r = c + 1.596 * e
    g = c - 0.392 * d - 0.813 * e
    b = c + 2.017 * d
    rgb = np.clip(np.stack([r, g, b], axis=-1), 0, 255).astype(np.uint8)
    return rgb


def yuyv_luma(data, w, h):
    """Raw Y plane as float32 (no range conversion) — fast path for the
    counter-strip decoder."""
    a = np.frombuffer(data, dtype=np.uint8).reshape(h, w // 2, 4)
    y = np.empty((h, w), dtype=np.float32)
    y[:, 0::2] = a[..., 0]
    y[:, 1::2] = a[..., 2]
    return y


def mjpg_to_rgb(data):
    p = subprocess.Popen(["djpeg", "-pnm"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate(data)
    if p.returncode != 0:
        raise RuntimeError("djpeg failed: %s" % err.decode(errors="replace").strip())
    return parse_ppm(out)


def parse_ppm(buf):
    # P6\n<w> <h>\n255\n<data>
    parts = []
    pos = 0
    while len(parts) < 4:
        while buf[pos:pos + 1].isspace():
            pos += 1
        start = pos
        while not buf[pos:pos + 1].isspace():
            pos += 1
        parts.append(buf[start:pos])
    pos += 1
    if parts[0] != b"P6":
        raise ValueError("not a P6 ppm")
    w, h = int(parts[1]), int(parts[2])
    rgb = np.frombuffer(buf[pos:pos + w * h * 3], dtype=np.uint8).reshape(h, w, 3)
    return rgb


def frame_to_image(frame):
    if frame.pixfmt == "YUYV":
        return Image(yuyv_to_rgb(frame.data, frame.width, frame.height))
    if frame.pixfmt == "MJPG":
        return Image(mjpg_to_rgb(frame.data))
    raise ValueError("unsupported pixfmt %s" % frame.pixfmt)


def frame_luma(frame):
    """Luma plane without full conversion where possible."""
    if frame.pixfmt == "YUYV":
        return yuyv_luma(frame.data, frame.width, frame.height)
    return frame_to_image(frame).luma


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)
