"""Migen simulation for the HDMI audio *embed* core (phase 7c) -- the inverse
of the phase-7b extract sim, and its round-trip partner.

Two things are proven here entirely in modern gateware, no FPGA / toolchain:

1. **Framing / byte-layout fidelity.** The :class:`AudioIslandEncoder` is driven
   with a packet (header + subpacket *data*), and the ``(c0,c1,c2)`` 10-bit
   token stream it emits is captured and asserted **bit-for-bit equal** to what
   the golden model :func:`hdmi_audio_model.island_stream` produces for the same
   packet. Since the encoder computes the BCH ECC itself, this proves the
   embedder's header/subpacket ECC matches the model (hence the phase-7b
   extractor will find ``ecc_ok``), the TERC4 encoding is correct, and the
   preamble / guard-band framing is spec-valid.

2. **embed -> de-embed round trip.** The captured token stream is fed straight
   into the *real* phase-7a :class:`DecodeTERC4` + phase-7b
   :class:`HDMIAudioExtract` de-embed path (the exact modules and helper from
   the phase-7b test), and we assert the recovered PCM is bit-exact, that N/CTS
   decode to 48 kHz, and that the Audio InfoFrame round-trips -- closing the
   goal's "HDMI audio embedding/de-embedding" pair.

Run:  uv run pytest tests/sim/video/test_hdmi_audio_embed.py
  or: uv run python tests/sim/video/test_hdmi_audio_embed.py
"""

import os
import sys

from migen import *

sys.path.insert(0, os.path.dirname(__file__))

import hdmi_audio_model as m

from netv2.gateware.video.audio.embed import AudioIslandEncoder
from netv2.gateware.video.audio.extract import HDMIAudioExtract
from netv2.gateware.video.input.decoding import DecodeTERC4

PIX_FREQ = 74.25e6
N_48K = 6144
CTS_48K = 74250


# ---------------------------------------------------------------------------
# Stage 1: run the embed encoder and capture its emitted token stream.
# ---------------------------------------------------------------------------
def _capture_island(pkt_type, hb1, hb2, subs):
    """Drive AudioIslandEncoder with one packet; return the emitted
    (c0,c1,c2) token tuples (only while stream_valid is high)."""
    dut = ClockDomainsRenamer({"pix": "sys"})(AudioIslandEncoder())
    captured = []

    def gen():
        # load packet inputs
        yield dut.pkt_type.eq(pkt_type)
        yield dut.hb1.eq(hb1)
        yield dut.hb2.eq(hb2)
        for k in range(4):
            yield dut.sub[k].eq(subs[k])
        yield dut.hsync.eq(0)
        yield dut.vsync.eq(0)
        yield
        # pulse start
        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        # capture until the island finishes (busy drops) with a safety bound
        for _ in range(200):
            sv = (yield dut.stream_valid)
            if sv:
                c0 = (yield dut.c0)
                c1 = (yield dut.c1)
                c2 = (yield dut.c2)
                captured.append((c0, c1, c2))
            elif captured:
                break
            yield

    run_simulation(dut, gen())
    return captured


def _asp_packet_data(sample_a, sample_b, sample_present=0x1, layout=0):
    """Header fields + 4 subpacket *data* words for an ASP (subpacket 0)."""
    hb1 = (sample_present & 0xF) | ((layout & 1) << 4)
    hb2 = 0x00
    frame = (sample_a & 0xFFFFFF) | ((sample_b & 0xFFFFFF) << 28)
    subs = [frame & ((1 << 56) - 1), 0, 0, 0]
    return 0x02, hb1, hb2, subs


def _acr_packet_data(n, cts):
    pb = [0x00, (cts >> 16) & 0xF, (cts >> 8) & 0xFF, cts & 0xFF,
          (n >> 16) & 0xF, (n >> 8) & 0xFF, n & 0xFF]
    word = 0
    for i, b in enumerate(pb):
        word |= (b & 0xFF) << (8 * i)
    return 0x01, 0x00, 0x00, [word, word, word, word]


def _infoframe_packet_data(cc, ct, sf, ss, ca):
    hb0, hb1, hb2 = 0x84, 0x01, 0x0A
    db1 = (cc & 0x7) | ((ct & 0xF) << 4)
    db2 = (ss & 0x3) | ((sf & 0x7) << 2)
    data = [db1, db2, 0x00, ca & 0xFF, 0x00, 0x00]
    checksum = (-(hb0 + hb1 + hb2 + sum(data))) & 0xFF
    pb = [checksum] + data
    word = 0
    for i, b in enumerate(pb):
        word |= (b & 0xFF) << (8 * i)
    return 0x84, 0x01, 0x0A, [word, 0, 0, 0]


# ---------------------------------------------------------------------------
# Test 1: framing / byte-layout equals the golden model, per packet type.
# ---------------------------------------------------------------------------
def test_island_matches_model_asp():
    sa, sb = 0x123456, 0x654321
    pkt_type, hb1, hb2, subs = _asp_packet_data(sa, sb)
    got = _capture_island(pkt_type, hb1, hb2, subs)

    hdr, subwords = m.audio_sample_packet(
        samples=[(sa, sb), (0, 0), (0, 0), (0, 0)], sample_present=0x1)
    exp = m.island_stream([(hdr, subwords)])

    assert got == exp, (
        f"ASP island mismatch: len got={len(got)} exp={len(exp)}\n"
        f"first diff at {next((i for i,(a,b) in enumerate(zip(got,exp)) if a!=b), None)}")


def test_island_matches_model_acr():
    pkt_type, hb1, hb2, subs = _acr_packet_data(N_48K, CTS_48K)
    got = _capture_island(pkt_type, hb1, hb2, subs)
    hdr, subwords = m.acr_packet(N_48K, CTS_48K)
    exp = m.island_stream([(hdr, subwords)])
    assert got == exp, "ACR island token stream does not match the golden model"


def test_island_matches_model_infoframe():
    pkt_type, hb1, hb2, subs = _infoframe_packet_data(
        cc=0x1, ct=0x0, sf=0x3, ss=0x3, ca=0x00)
    got = _capture_island(pkt_type, hb1, hb2, subs)
    hdr, subwords = m.audio_infoframe(cc=0x1, ct=0x0, sf=0x3, ss=0x3, ca=0x00)
    exp = m.island_stream([(hdr, subwords)])
    assert got == exp, "InfoFrame island token stream does not match the golden model"


# ---------------------------------------------------------------------------
# Test 2: full embed -> de-embed round trip through the real phase-7b path.
# ---------------------------------------------------------------------------
class _RxDUT(Module):
    def __init__(self):
        self.submodules.terc4 = DecodeTERC4()
        self.submodules.audio = HDMIAudioExtract(terc4=self.terc4)


def _rx_build():
    return ClockDomainsRenamer({"pix": "sys"})(_RxDUT())


def _rx_feed(dut, stream):
    yield dut.terc4.valid_i.eq(1)
    for raw0, raw1, raw2 in stream:
        yield dut.terc4.data_in0.raw.eq(raw0)
        yield dut.terc4.data_in1.raw.eq(raw1)
        yield dut.terc4.data_in2.raw.eq(raw2)
        yield


def _rx_decode_word(w):
    return {"sample": w & 0xFFFFFF, "channel": (w >> 24) & 0x7,
            "v": (w >> 27) & 1, "u": (w >> 28) & 1, "c": (w >> 29) & 1,
            "b": (w >> 30) & 1}


def _rx_drain(dut, max_reads=512):
    out = []
    for _ in range(max_reads):
        if (yield dut.audio.sample_valid.status):
            w = (yield dut.audio.sample_data.status)
            out.append(_rx_decode_word(w))
            yield dut.audio.sample_re.eq(1)
            yield
            yield dut.audio.sample_re.eq(0)
            yield
        else:
            yield
            if not (yield dut.audio.sample_valid.status):
                break
    return out


def test_embed_deembed_roundtrip_pcm():
    """Embed several ASPs of a known stereo sine, capture the gateware-produced
    islands, feed them into the real de-embed path, recover bit-exact PCM."""
    n_pairs = 8
    left = m.sine_samples_24bit(n_pairs, freq=1000.0, fs=48000.0, amplitude=0.5)
    right = [(0x010000 * (i + 1)) & 0xFFFFFF for i in range(n_pairs)]

    # Stage 1: embed -> capture islands from the gateware encoder.
    stream = []
    for i in range(n_pairs):
        pkt_type, hb1, hb2, subs = _asp_packet_data(left[i], right[i])
        stream += _capture_island(pkt_type, hb1, hb2, subs)

    # Stage 2: de-embed through the phase-7b path.
    dut = _rx_build()
    result = {}

    def gen():
        yield from _rx_feed(dut, stream)
        for _ in range(64):
            yield
        result["samples"] = (yield from _rx_drain(dut))
        result["asp_count"] = (yield dut.audio.asp_count.status)
        result["sample_count"] = (yield dut.audio.sample_count.status)
        result["ecc_err"] = (yield dut.audio.ecc_err_count.status)

    run_simulation(dut, gen())

    samples = result["samples"]
    ch0 = [s["sample"] for s in samples if s["channel"] == 0]
    ch1 = [s["sample"] for s in samples if s["channel"] == 1]

    assert result["ecc_err"] == 0, "embedder wrote a bad BCH ECC (extractor rejected it)"
    assert result["asp_count"] == n_pairs, f"asp_count={result['asp_count']}"
    assert result["sample_count"] == 2 * n_pairs, f"sample_count={result['sample_count']}"
    assert ch0 == left, f"left channel mismatch:\n got {ch0}\n exp {left}"
    assert ch1 == right, f"right channel mismatch:\n got {ch1}\n exp {right}"


def test_embed_deembed_roundtrip_acr_infoframe():
    """Embed an ACR + Audio InfoFrame, de-embed, check N/CTS and InfoFrame."""
    stream = []
    stream += _capture_island(*_acr_packet_data(N_48K, CTS_48K))
    stream += _capture_island(*_infoframe_packet_data(
        cc=0x1, ct=0x0, sf=0x3, ss=0x3, ca=0x00))

    dut = _rx_build()
    result = {}

    def gen():
        yield from _rx_feed(dut, stream)
        for _ in range(300):
            yield
        result["n"] = (yield dut.audio.n.status)
        result["cts"] = (yield dut.audio.cts.status)
        result["acr_count"] = (yield dut.audio.acr_count.status)
        result["if_valid"] = (yield dut.audio.audio_infoframe.fields.valid)
        result["cc"] = (yield dut.audio.audio_infoframe.fields.cc)
        result["sf"] = (yield dut.audio.audio_infoframe.fields.sf)
        result["ss"] = (yield dut.audio.audio_infoframe.fields.ss)
        result["if_count"] = (yield dut.audio.infoframe_count.status)

    run_simulation(dut, gen())

    assert result["n"] == N_48K, f"N={result['n']} expected {N_48K}"
    assert result["cts"] == CTS_48K, f"CTS={result['cts']} expected {CTS_48K}"
    assert result["acr_count"] == 1
    fs = m.derived_sample_rate(PIX_FREQ, result["n"], result["cts"])
    assert abs(fs - 48000.0) < 1.0, f"derived fs={fs} not ~48kHz"
    assert result["if_valid"] == 1, "InfoFrame not latched"
    assert result["cc"] == 0x1 and result["sf"] == 0x3 and result["ss"] == 0x3
    assert result["if_count"] == 1


if __name__ == "__main__":
    test_island_matches_model_asp();        print("island ASP == model: OK")
    test_island_matches_model_acr();        print("island ACR == model: OK")
    test_island_matches_model_infoframe();  print("island InfoFrame == model: OK")
    test_embed_deembed_roundtrip_pcm();     print("embed->de-embed PCM bit-exact: OK")
    test_embed_deembed_roundtrip_acr_infoframe()
    print("embed->de-embed ACR N/CTS + InfoFrame: OK")
    print("all hdmi-audio embed round-trip sim tests passed")
