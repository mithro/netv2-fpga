"""HDMI audio *embed* output gateware (phase 7c).

A self-timed raw-mode HDMI **output** pipeline (litevideo's, ported to modern
migen) plus the audio-island encoder that inserts Audio Sample / ACR /
Audio-InfoFrame packets as TERC4 data-island characters into the output
blanking. This is the source-side counterpart to the phase-7b input-side
de-embed (:mod:`netv2.gateware.video.audio.extract`).

* :class:`~netv2.gateware.video.output.s7.S7HDMIOutPHY` -- raw 3-lane OSERDESE2
  output PHY (10-bit tokens in, TMDS out).
* :class:`~netv2.gateware.video.output.s7.S7HDMIOutClocking` -- fractional MMCM
  turning the 50 MHz oscillator into the free-running pix / pix5x clocks.
* :class:`~netv2.gateware.video.output.timing.VideoTimingGenerator` -- CEA
  timing + colour-bar test pattern.
* :class:`~netv2.gateware.video.output.encoder.Encoder` -- TMDS 8b/10b encoder.
"""

from netv2.gateware.video.output.encoder import Encoder
from netv2.gateware.video.output.s7 import (
    S7HDMIOutClocking,
    S7HDMIOutEncoderSerializer,
    S7HDMIOutPHY,
)
from netv2.gateware.video.output.timing import VideoTimingGenerator

__all__ = [
    "Encoder",
    "S7HDMIOutClocking",
    "S7HDMIOutEncoderSerializer",
    "S7HDMIOutPHY",
    "VideoTimingGenerator",
]
