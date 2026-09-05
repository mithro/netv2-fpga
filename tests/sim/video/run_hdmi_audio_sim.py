#!/usr/bin/env python3
"""Run the phase-7b HDMI audio de-embed / extract simulation (migen, no Vivado).

Thin wrapper around :mod:`test_hdmi_audio_extract` so the audio sim can be run
as one command and prints a human-readable summary of what it verified:

    uv run python tests/sim/video/run_hdmi_audio_sim.py

It runs the same four checks pytest runs:
  * ASP PCM recovery (bit-exact vs the Python packer),
  * ACR N/CTS latch + derived 48 kHz sample rate,
  * Audio InfoFrame field decode,
  * BCH-error packet drop.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import test_hdmi_audio_extract as t


def main():
    print("=== phase-7b HDMI audio extract simulation (migen) ===")
    t.test_asp_recovers_pcm()
    print("[ok] Audio Sample Packet: recovered PCM is bit-exact (stereo 24-bit)")
    t.test_acr_latches_n_cts_and_rate()
    print(f"[ok] ACR: N={t.N_48K} CTS={t.CTS_48K} latch; derived fs ~ 48 kHz")
    t.test_audio_infoframe_decodes()
    print("[ok] Audio InfoFrame: CC/CT/SF/SS/CA decode")
    t.test_bch_error_drops_packet()
    print("[ok] BCH error: corrupted subpacket dropped (ecc_ok=0), no samples")
    print("=== all audio-extract sim checks passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
