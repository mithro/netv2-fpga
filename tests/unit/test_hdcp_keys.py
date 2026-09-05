"""Tests for the HDCP KSV / device-key / Km layer.

The closed-loop key system is the one implemented by ``hdcp/keygen.py`` in the
netv2-hdcp-handoff tree: a random *symmetric* 40x40 master matrix of 56-bit
values, device keys = M . KSV, and Km = sum of one side's keys over the other
side's KSV (mod 2**56).  No real HDCP master key is involved.

Spec reference: "High-bandwidth Digital Content Protection System, Revision
1.4", section 2.2.1 (40 secret device keys, KSV with exactly 20 ones) and the
worked Km example in section 2.3.
"""

import json
import random

import pytest

from netv2.hdcp.keys import (
    KEY_BYTES,
    KSV_BITS,
    MASK56,
    N_KEYS,
    balanced_ksv,
    device_keys,
    is_balanced_ksv,
    km_from_keys,
    load_keys_bin,
    load_manifest,
    save_keys_bin,
    symmetric_master,
)


class SeededRng:
    """Minimal deterministic stand-in for ``secrets`` (randbits + randbelow)."""

    def __init__(self, seed):
        self._rng = random.Random(seed)

    def randbits(self, k):
        return self._rng.getrandbits(k)

    def randbelow(self, n):
        return self._rng.randrange(n)


def _keygen_km(keys, other_ksv):
    """Literal copy of ``km()`` from the handoff ``keygen.py``, for comparison."""
    return sum(keys[j] for j in range(N_KEYS) if (other_ksv >> j) & 1) & MASK56


@pytest.fixture
def pair():
    """A throwaway (master, source, sink) key set, as keygen.py would emit."""
    rng = SeededRng(0xC0FFEE)
    master = symmetric_master(rng)
    ksv_src = balanced_ksv(rng)
    ksv_snk = balanced_ksv(rng)
    return master, ksv_src, ksv_snk


def test_master_matrix_is_symmetric_and_56_bit():
    master = symmetric_master(SeededRng(1))
    assert len(master) == N_KEYS and all(len(row) == N_KEYS for row in master)
    for i in range(N_KEYS):
        for j in range(N_KEYS):
            assert master[i][j] == master[j][i]
            assert 0 <= master[i][j] <= MASK56
    # A random 40x40 matrix should not be degenerate.
    assert len({v for row in master for v in row}) > 700


def test_km_symmetry(pair):
    """Source and sink derive the same Km -- keygen.py's central assertion."""
    master, ksv_src, ksv_snk = pair
    src = device_keys(master, ksv_src)
    snk = device_keys(master, ksv_snk)
    km_src = km_from_keys(src, ksv_snk)   # source sums its own keys over sink KSV
    km_snk = km_from_keys(snk, ksv_src)   # sink sums its own keys over source KSV
    assert km_src == km_snk
    assert 0 <= km_src <= MASK56
    assert km_src != 0


def test_km_differs_when_a_ksv_bit_flips(pair):
    """A single flipped KSV bit breaks the shared secret."""
    master, ksv_src, ksv_snk = pair
    src = device_keys(master, ksv_src)
    snk = device_keys(master, ksv_snk)
    km_good = km_from_keys(src, ksv_snk)

    differences = 0
    for bit in range(KSV_BITS):
        bad_ksv = ksv_snk ^ (1 << bit)
        # The source now sums over a corrupted sink KSV ...
        assert km_from_keys(src, bad_ksv) != km_good
        # ... and a sink built from a corrupted KSV no longer agrees either.
        bad_snk = device_keys(master, ksv_src ^ (1 << bit))
        if km_from_keys(bad_snk, ksv_src) != km_from_keys(snk, ksv_src):
            differences += 1
    assert differences == KSV_BITS


def test_km_matches_keygen_formula(pair):
    master, ksv_src, ksv_snk = pair
    keys = device_keys(master, ksv_src)
    assert km_from_keys(keys, ksv_snk) == _keygen_km(keys, ksv_snk)


def test_device_keys_shape(pair):
    master, ksv_src, _ = pair
    keys = device_keys(master, ksv_src)
    assert len(keys) == N_KEYS
    assert all(0 <= k <= MASK56 for k in keys)
    assert device_keys(master, 0) == [0] * N_KEYS


def test_is_balanced_ksv_on_keygen_output():
    """Every KSV produced in the keygen.py format has exactly 20 of 40 bits set."""
    rng = SeededRng(7)
    for _ in range(64):
        ksv = balanced_ksv(rng)
        assert ksv >> KSV_BITS == 0
        assert ksv.bit_count() == KSV_BITS // 2
        assert is_balanced_ksv(ksv)


@pytest.mark.parametrize("bad", [
    0,                          # no ones
    (1 << KSV_BITS) - 1,        # all forty ones
    (1 << 20) - 1 | (1 << 40),  # 21 ones and too wide
    -1,                         # negative
    (1 << 19) - 1,              # 19 ones
    (1 << 21) - 1,              # 21 ones
])
def test_is_balanced_ksv_rejects(bad):
    assert not is_balanced_ksv(bad)


def test_keys_bin_roundtrip(tmp_path, pair):
    """The 40 x 7-byte little-endian on-disk format survives a round trip."""
    master, ksv_src, _ = pair
    keys = device_keys(master, ksv_src)
    path = tmp_path / "source_keys.bin"
    save_keys_bin(path, keys)
    assert path.stat().st_size == N_KEYS * KEY_BYTES
    assert load_keys_bin(path) == keys

    blob = path.read_bytes()
    assert int.from_bytes(blob[:KEY_BYTES], "little") == keys[0]


def test_load_keys_bin_rejects_wrong_size(tmp_path):
    path = tmp_path / "short.bin"
    path.write_bytes(b"\x00" * (N_KEYS * KEY_BYTES - 1))
    with pytest.raises(ValueError):
        load_keys_bin(path)


def test_load_manifest(tmp_path, pair):
    """manifest.json as written by keygen.py, with hex fields also decoded."""
    master, ksv_src, ksv_snk = pair
    km = km_from_keys(device_keys(master, ksv_src), ksv_snk)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "ksv_source": f"0x{ksv_src:010x}",
        "ksv_sink": f"0x{ksv_snk:010x}",
        "km_agreed": f"0x{km:014x}",
        "note": "source_keys.bin -> Pi vc4_hdcp_keys.bin; sink_keys.bin -> NeTV2",
    }))
    manifest = load_manifest(path)
    assert manifest["ksv_source_int"] == ksv_src
    assert manifest["ksv_sink_int"] == ksv_snk
    assert manifest["km_agreed_int"] == km
    assert manifest["ksv_source"] == f"0x{ksv_src:010x}"
    assert is_balanced_ksv(manifest["ksv_sink_int"])


def test_end_to_end_km_feeds_the_cipher(pair):
    """A self-generated key pair drives the cipher identically on both ends."""
    from netv2.hdcp.cipher import HDCPCipher

    master, ksv_src, ksv_snk = pair
    km_src = km_from_keys(device_keys(master, ksv_src), ksv_snk)
    km_snk = km_from_keys(device_keys(master, ksv_snk), ksv_src)
    an = 0x0123456789ABCDEF

    tx = HDCPCipher(repeater=0)
    rx = HDCPCipher(repeater=0)
    assert tx.authenticate(km_src, an) == rx.authenticate(km_snk, an)
    assert tx.rekey_frame() == rx.rekey_frame()
    assert tx.stream(16) == rx.stream(16)
