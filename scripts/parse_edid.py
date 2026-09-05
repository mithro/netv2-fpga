#!/usr/bin/env python3
"""Minimal EDID / CTA-861 parser: enough to answer "does this sink advertise
HDMI audio, and which formats?" for phase 1 and phase 7a diagnostics."""
import argparse
from pathlib import Path

RATE_BITS = [(0, 32), (1, 44.1), (2, 48), (3, 88.2), (4, 96), (5, 176.4), (6, 192)]
FORMATS = {1: "LPCM", 2: "AC-3", 3: "MPEG1", 4: "MP3", 5: "MPEG2", 6: "AAC", 7: "DTS", 8: "ATRAC"}


def cta_blocks(edid: bytes) -> list[bytes]:
    """Return the 128-byte CTA-861 extension blocks (tag 0x02) of a full EDID."""
    blocks = [edid[i:i + 128] for i in range(128, len(edid), 128)]
    return [b for b in blocks if len(b) == 128 and b[0] == 0x02]


def has_basic_audio(cta: bytes) -> bool:
    return bool(cta[3] & 0x40)


def audio_descriptors(cta: bytes) -> list[dict]:
    dtd_offset = cta[2]
    i, out = 4, []
    while i < dtd_offset:
        tag, length = cta[i] >> 5, cta[i] & 0x1F
        if tag == 1:  # Audio Data Block
            for j in range(i + 1, i + 1 + length, 3):
                b0, b1, b2 = cta[j], cta[j + 1], cta[j + 2]
                fmt = (b0 >> 3) & 0x0F
                out.append({
                    "format": FORMATS.get(fmt, f"code{fmt}"),
                    "channels": (b0 & 0x07) + 1,
                    "rates_khz": [r for bit, r in RATE_BITS if b1 & (1 << bit)],
                    "byte2": b2,
                })
        i += 1 + length
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("edid", type=Path)
    a = ap.parse_args()
    data = a.edid.read_bytes()
    print(f"{a.edid}: {len(data)} bytes, {len(data) // 128} blocks")
    ctas = cta_blocks(data)
    if not ctas:
        print("no CTA-861 extension block: sink is DVI-only for audio purposes")
        return
    for n, cta in enumerate(ctas):
        print(f"CTA block {n}: basic_audio={has_basic_audio(cta)}")
        for d in audio_descriptors(cta):
            print(f"  audio: {d}")


if __name__ == "__main__":
    main()
