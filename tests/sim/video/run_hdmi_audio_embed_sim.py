#!/usr/bin/env python3
"""Run the phase-7c HDMI audio *embed* / round-trip simulation (migen, no Vivado).

Thin wrapper around :mod:`test_hdmi_audio_embed` printing a human-readable
summary of what it verified:

    uv run python tests/sim/video/run_hdmi_audio_embed_sim.py

It runs the phase-7c checks:
  * the island encoder's TERC4 token stream is byte-exact vs the golden model
    (ASP, ACR, Audio InfoFrame) -- proves BCH ECC, TERC4 encoding and framing;
  * embed -> de-embed round trip: the gateware-produced islands, fed back into
    the *real* phase-7b DecodeTERC4 + HDMIAudioExtract, recover PCM bit-exact,
    N/CTS -> 48 kHz, and the Audio InfoFrame.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import test_hdmi_audio_embed as t


def main():
    print("=== phase-7c HDMI audio embed + round-trip simulation (migen) ===")
    t.test_island_matches_model_asp()
    print("[ok] ASP island: TERC4 token stream byte-exact vs golden model")
    t.test_island_matches_model_acr()
    print("[ok] ACR island: token stream byte-exact vs golden model")
    t.test_island_matches_model_infoframe()
    print("[ok] Audio InfoFrame island: token stream byte-exact vs golden model")
    t.test_embed_deembed_roundtrip_pcm()
    print("[ok] embed -> de-embed: recovered PCM bit-exact (stereo 24-bit), "
          "embedder BCH verified OK in the extractor")
    t.test_embed_deembed_roundtrip_acr_infoframe()
    print("[ok] embed -> de-embed: N/CTS latch (derived fs ~ 48 kHz) + "
          "Audio InfoFrame round-trip")
    print("=== all audio-embed round-trip sim checks passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
