"""Migen simulation for the HDMI audio de-embed / extract core (phase 7b).

End-to-end: the Python model in :mod:`hdmi_audio_model` packs Audio Sample /
ACR / Audio-InfoFrame packets (with correct BCH ECC) into a per-channel TERC4
token stream; that stream is fed into the *real* phase-7a
:class:`DecodeTERC4` island FSM, whose nibble taps drive
:class:`HDMIAudioExtract`. We then assert:

* recovered PCM equals the input 24-bit sine sequence, bit-exact, per channel;
* N / CTS latch from the ACR packet, and fs = f_pix*N/(128*CTS) ~ 48 kHz;
* the Audio InfoFrame CC/CT/SF/SS/CA fields decode;
* a packet with a corrupted subpacket ECC is dropped (ecc_ok=0, no samples).

No FPGA, no toolchain. The blocks are written in ``pix``; for a single-clock
sim we rename ``pix`` -> ``sys`` (which also collapses the extract core's
pix->sys CDC to one domain -- fine for a functional check).

Run:  uv run pytest tests/sim/video/test_hdmi_audio_extract.py
  or: uv run python tests/sim/video/test_hdmi_audio_extract.py
"""

import os
import sys

from migen import *

sys.path.insert(0, os.path.dirname(__file__))

from netv2.gateware.video.input.decoding import DecodeTERC4
from netv2.gateware.video.audio.extract import HDMIAudioExtract

import hdmi_audio_model as m


PIX_FREQ = 74.25e6      # 720p pixel/TMDS clock -- the phase-7a validated mode
N_48K = 6144
CTS_48K = 74250         # f_pix*N/(128*fs) for fs=48 kHz at 74.25 MHz


class _DUT(Module):
    """DecodeTERC4 + HDMIAudioExtract wired together (pix domain)."""
    def __init__(self):
        self.submodules.terc4 = DecodeTERC4()
        self.submodules.audio = HDMIAudioExtract(terc4=self.terc4)


def _build_dut():
    return ClockDomainsRenamer({"pix": "sys"})(_DUT())


def _feed(dut, stream):
    """Drive one (raw0,raw1,raw2) tuple per cycle into the TERC4 inputs."""
    yield dut.terc4.valid_i.eq(1)
    for raw0, raw1, raw2 in stream:
        yield dut.terc4.data_in0.raw.eq(raw0)
        yield dut.terc4.data_in1.raw.eq(raw1)
        yield dut.terc4.data_in2.raw.eq(raw2)
        yield


def _decode_word(w):
    return {
        "sample": w & 0xFFFFFF,
        "channel": (w >> 24) & 0x7,
        "v": (w >> 27) & 1,
        "u": (w >> 28) & 1,
        "c": (w >> 29) & 1,
        "b": (w >> 30) & 1,
    }


def _drain(dut, max_reads=512):
    out = []
    for _ in range(max_reads):
        if (yield dut.audio.sample_valid.status):
            w = (yield dut.audio.sample_data.status)
            out.append(_decode_word(w))
            yield dut.audio.sample_re.eq(1)
            yield
            yield dut.audio.sample_re.eq(0)
            yield
        else:
            # allow a couple of idle cycles in case of FIFO CDC latency
            yield
            if not (yield dut.audio.sample_valid.status):
                break
    return out


# ---------------------------------------------------------------------------
def test_asp_recovers_pcm():
    """Several ASPs carrying a known stereo 24-bit sine -> exact PCM back."""
    dut = _build_dut()

    n_pairs = 8
    left = m.sine_samples_24bit(n_pairs, freq=1000.0, fs=48000.0, amplitude=0.5)
    # distinct right channel (descending ramp) so channel mapping is unambiguous
    right = [(0x010000 * (i + 1)) & 0xFFFFFF for i in range(n_pairs)]

    stream = []
    for i in range(n_pairs):
        hdr, subs = m.audio_sample_packet(
            samples=[(left[i], right[i]), (0, 0), (0, 0), (0, 0)],
            sample_present=0x1, layout=0)
        stream += m.island_stream([(hdr, subs)])

    result = {}

    def gen():
        yield from _feed(dut, stream)
        for _ in range(64):     # let the last pushes finish
            yield
        result["samples"] = (yield from _drain(dut))
        result["asp_count"] = (yield dut.audio.asp_count.status)
        result["sample_count"] = (yield dut.audio.sample_count.status)
        result["ecc_err"] = (yield dut.audio.ecc_err_count.status)

    run_simulation(dut, gen())

    samples = result["samples"]
    ch0 = [s["sample"] for s in samples if s["channel"] == 0]
    ch1 = [s["sample"] for s in samples if s["channel"] == 1]

    assert result["ecc_err"] == 0, "unexpected ECC errors on clean stream"
    assert result["asp_count"] == n_pairs, \
        f"asp_count={result['asp_count']} expected {n_pairs}"
    assert result["sample_count"] == 2 * n_pairs, \
        f"sample_count={result['sample_count']} expected {2*n_pairs}"
    assert ch0 == left, f"left channel mismatch:\n got {ch0}\n exp {left}"
    assert ch1 == right, f"right channel mismatch:\n got {ch1}\n exp {right}"


def test_acr_latches_n_cts_and_rate():
    dut = _build_dut()
    hdr, subs = m.acr_packet(N_48K, CTS_48K)
    stream = m.island_stream([(hdr, subs)])
    result = {}

    def gen():
        yield from _feed(dut, stream)
        for _ in range(300):    # BusSynchronizer settle
            yield
        result["n"] = (yield dut.audio.n.status)
        result["cts"] = (yield dut.audio.cts.status)
        result["acr_count"] = (yield dut.audio.acr_count.status)

    run_simulation(dut, gen())

    assert result["n"] == N_48K, f"N={result['n']} expected {N_48K}"
    assert result["cts"] == CTS_48K, f"CTS={result['cts']} expected {CTS_48K}"
    assert result["acr_count"] == 1
    fs = m.derived_sample_rate(PIX_FREQ, result["n"], result["cts"])
    assert abs(fs - 48000.0) < 1.0, f"derived fs={fs} not ~48kHz"


def test_audio_infoframe_decodes():
    dut = _build_dut()
    # 2ch LPCM, 48 kHz, 24-bit: CC=1, CT=0, SF=3(48k), SS=3(24-bit), CA=0
    hdr, subs = m.audio_infoframe(cc=0x1, ct=0x0, sf=0x3, ss=0x3, ca=0x00)
    stream = m.island_stream([(hdr, subs)])
    result = {}

    def gen():
        yield from _feed(dut, stream)
        for _ in range(300):
            yield
        result["cc"] = (yield dut.audio.audio_infoframe.fields.cc)
        result["ct"] = (yield dut.audio.audio_infoframe.fields.ct)
        result["sf"] = (yield dut.audio.audio_infoframe.fields.sf)
        result["ss"] = (yield dut.audio.audio_infoframe.fields.ss)
        result["ca"] = (yield dut.audio.audio_infoframe.fields.ca)
        result["valid"] = (yield dut.audio.audio_infoframe.fields.valid)
        result["cnt"] = (yield dut.audio.infoframe_count.status)

    run_simulation(dut, gen())

    assert result["valid"] == 1, "InfoFrame valid not set"
    assert result["cc"] == 0x1, f"CC={result['cc']}"
    assert result["ct"] == 0x0, f"CT={result['ct']}"
    assert result["sf"] == 0x3, f"SF={result['sf']}"
    assert result["ss"] == 0x3, f"SS={result['ss']}"
    assert result["ca"] == 0x00, f"CA={result['ca']}"
    assert result["cnt"] == 1


def test_bch_error_drops_packet():
    """A corrupted subpacket ECC -> ecc_ok=0, no samples, err counter ticks."""
    dut = _build_dut()

    good_l = m.sine_samples_24bit(1, freq=1000.0)[0]
    # one good ASP, then one with a corrupted subpacket-0 ECC
    hdr_g, subs_g = m.audio_sample_packet(
        samples=[(good_l, 0x555555), (0, 0), (0, 0), (0, 0)], sample_present=0x1)
    hdr_b, subs_b = m.audio_sample_packet(
        samples=[(0x123456, 0x654321), (0, 0), (0, 0), (0, 0)],
        sample_present=0x1, corrupt_sub=0)

    stream = m.island_stream([(hdr_g, subs_g)]) + m.island_stream([(hdr_b, subs_b)])
    result = {}

    def gen():
        yield from _feed(dut, stream)
        for _ in range(64):
            yield
        result["samples"] = (yield from _drain(dut))
        result["asp_count"] = (yield dut.audio.asp_count.status)
        result["sample_count"] = (yield dut.audio.sample_count.status)
        result["ecc_err"] = (yield dut.audio.ecc_err_count.status)

    run_simulation(dut, gen())

    assert result["ecc_err"] == 1, f"expected 1 ECC error, got {result['ecc_err']}"
    assert result["asp_count"] == 1, \
        f"only the good ASP should be accepted, got {result['asp_count']}"
    assert result["sample_count"] == 2, \
        f"only the good ASP's 2 samples, got {result['sample_count']}"
    ch0 = [s["sample"] for s in result["samples"] if s["channel"] == 0]
    assert ch0 == [good_l], f"recovered {ch0}, expected [{good_l:#x}]"
    # the corrupted packet's payload must NOT appear
    all_samples = [s["sample"] for s in result["samples"]]
    assert 0x123456 not in all_samples and 0x654321 not in all_samples


if __name__ == "__main__":
    test_asp_recovers_pcm();            print("asp pcm recovery: OK")
    test_acr_latches_n_cts_and_rate();  print("acr n/cts + rate: OK")
    test_audio_infoframe_decodes();     print("audio infoframe: OK")
    test_bch_error_drops_packet();      print("bch error drop: OK")
    print("all hdmi-audio extract sim tests passed")
