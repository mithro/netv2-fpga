#!/usr/bin/env python3
"""Convert a raw YUYV (YUV 4:2:2) frame to PNG. Host-side helper (needs numpy + Pillow).

Usage: uv run --with numpy --with pillow scripts/yuyv2png.py in.yuyv out.png [width height]
"""
import sys

import numpy as np
from PIL import Image


def yuyv_to_rgb(raw, w, h):
    a = np.frombuffer(raw, dtype=np.uint8).reshape(h, w // 2, 4).astype(np.float32)
    y0, u, y1, v = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    y = np.stack([y0, y1], axis=-1).reshape(h, w)
    u = np.repeat(u, 2, axis=1)
    v = np.repeat(v, 2, axis=1)
    # BT.601 limited range -> full range RGB
    c = (y - 16.0) * (255.0 / 219.0)
    d = u - 128.0
    e = v - 128.0
    r = c + 1.596 * e
    g = c - 0.392 * d - 0.813 * e
    b = c + 2.017 * d
    return np.clip(np.stack([r, g, b], axis=-1), 0, 255).astype(np.uint8)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 1080
    with open(src, "rb") as f:
        raw = f.read()
    assert len(raw) == w * h * 2, "expected %d bytes, got %d" % (w * h * 2, len(raw))
    Image.fromarray(yuyv_to_rgb(raw, w, h)).save(dst)
    print("wrote", dst)


if __name__ == "__main__":
    main()
