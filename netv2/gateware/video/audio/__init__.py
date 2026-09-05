"""HDMI audio de-embed / extract gateware (phase 7b).

Built on the phase-7a HDMI input pipeline's TERC4 data-island decoder
(:class:`netv2.gateware.video.input.decoding.DecodeTERC4`):

* :class:`~netv2.gateware.video.audio.parser.AudioPacketParser` -- frames the
  island byte stream into decoded packets and checks the BCH ECC.
* :class:`~netv2.gateware.video.audio.extract.HDMIAudioExtract` -- turns Audio
  Sample / ACR / InfoFrame packets into a CPU-readable PCM FIFO + CSRs.
"""

from netv2.gateware.video.audio.parser import AudioPacketParser
from netv2.gateware.video.audio.extract import HDMIAudioExtract

__all__ = ["AudioPacketParser", "HDMIAudioExtract"]
