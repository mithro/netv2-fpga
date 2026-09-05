"""HDCP 1.x device keys, KSVs and the Km shared-secret computation.

Reference: "High-bandwidth Digital Content Protection System, Revision 1.4",
Digital Content Protection LLC, 8 July 2009 (referred to below as "the spec").

Section 2.2.1 ("First Part of the Authentication Protocol") defines the key
selection vector (KSV) and the shared secret Km:

    "Each HDCP Device is furnished with ... an array of 40 secret device keys
     ... and a corresponding KSV.  Each KSV contains exactly 20 ones and 20
     zeros."

    "Device A will add its own secret device keys at array indexes ... [the set
     bit positions of B's KSV] together to calculate the shared secret value,
     Km.  Device B will perform an analogous calculation using its own private
     key array and Device A's KSV to get Km'."  (spec section 2.3, restated for
     the worked example there)

All key additions are 56-bit modular additions, i.e. mod 2**56.

NO REAL (LEAKED) HDCP MASTER KEY IS USED OR EMBEDDED HERE.  The NeTV2 closed
loop is its own key authority: a random *symmetric* 40x40 matrix M of 56-bit
values is the private master secret, a device with KSV v receives device keys
keys = M . v, and because M is symmetric

    Km = sum(A_keys[j] for j in setbits(KSV_B)) == KSV_A^T M KSV_B
       == sum(B_keys[i] for i in setbits(KSV_A))

so both endpoints derive the same Km and the spec's authentication maths goes
through unchanged.  This mirrors ``hdcp/keygen.py`` in the netv2-hdcp-handoff
tree, which produces the ``*_keys.bin`` / ``manifest.json`` files loaded here.
"""

from __future__ import annotations

import json
import os
import secrets

KSV_BITS = 40
"""Width of a Key Selection Vector, in bits (spec section 2.2.1)."""

N_KEYS = 40
"""Number of secret device keys per device (spec section 2.2.1)."""

KEY_BITS = 56
"""Width of a device private key / of Km, in bits (spec section 2.2.1)."""

MASK56 = (1 << KEY_BITS) - 1
"""Mask for 56-bit modular key arithmetic."""

KEY_BYTES = 7
"""On-disk size of one device key: 56 bits little-endian."""


def is_balanced_ksv(ksv: int) -> bool:
    """True when *ksv* is a valid KSV: 40 bits wide with exactly 20 ones.

    Spec section 2.2.1: "Each KSV contains exactly 20 ones and 20 zeros."
    """
    if ksv < 0 or ksv >> KSV_BITS:
        return False
    return ksv.bit_count() == KSV_BITS // 2


def km_from_keys(keys: list[int], other_ksv: int) -> int:
    """Compute the shared secret Km from our own device keys and the peer's KSV.

    Sum our secret device keys at the array indexes given by the set bits of
    *other_ksv*, modulo 2**56 (spec section 2.2.1 / worked example in 2.3).
    Identical to ``km()`` in the handoff ``keygen.py``.
    """
    return sum(keys[j] for j in range(N_KEYS) if (other_ksv >> j) & 1) & MASK56


def symmetric_master(rng=secrets) -> list[list[int]]:
    """Generate a random symmetric 40x40 matrix of 56-bit values.

    *rng* only needs a ``randbits(k)`` method (``secrets``, ``random.Random``,
    ``random.SystemRandom`` all qualify).  Symmetry is what makes the two ends
    of the closed loop agree on Km; see the module docstring.
    """
    m = [[0] * N_KEYS for _ in range(N_KEYS)]
    for i in range(N_KEYS):
        for j in range(i, N_KEYS):
            x = rng.randbits(KEY_BITS)
            m[i][j] = x
            m[j][i] = x
    return m


def device_keys(m: list[list[int]], ksv: int) -> list[int]:
    """Derive a device's 40 secret keys from the master matrix and its own KSV.

    keys[k] = sum(M[k][i] for i in setbits(ksv)) mod 2**56, i.e. keys = M . ksv.
    Same maths as ``device_keys()`` in the handoff ``keygen.py``.
    """
    setbits = [i for i in range(N_KEYS) if (ksv >> i) & 1]
    return [sum(m[k][i] for i in setbits) & MASK56 for k in range(N_KEYS)]


def balanced_ksv(rng=secrets) -> int:
    """Draw a random 40-bit KSV with exactly 20 ones (spec section 2.2.1).

    *rng* needs ``randbelow(n)``; matches ``balanced_ksv()`` in ``keygen.py``.
    """
    bits = [1] * (KSV_BITS // 2) + [0] * (KSV_BITS // 2)
    for i in range(KSV_BITS - 1, 0, -1):
        j = rng.randbelow(i + 1)
        bits[i], bits[j] = bits[j], bits[i]
    v = 0
    for i, b in enumerate(bits):
        if b:
            v |= 1 << i
    return v


def load_keys_bin(path: str | os.PathLike) -> list[int]:
    """Load a 280-byte device key file: 40 keys of 7 bytes, little-endian.

    This is the format written by ``keygen.py``'s ``write_keys()`` (and the
    format of the Pi's ``vc4_hdcp_keys.bin``).
    """
    with open(path, "rb") as f:
        blob = f.read()
    want = N_KEYS * KEY_BYTES
    if len(blob) != want:
        raise ValueError(f"{path}: expected {want} bytes, got {len(blob)}")
    return [
        int.from_bytes(blob[i * KEY_BYTES:(i + 1) * KEY_BYTES], "little")
        for i in range(N_KEYS)
    ]


def save_keys_bin(path: str | os.PathLike, keys: list[int]) -> None:
    """Write device keys in the 40 x 7-byte little-endian ``keygen.py`` format."""
    if len(keys) != N_KEYS:
        raise ValueError(f"expected {N_KEYS} keys, got {len(keys)}")
    with open(path, "wb") as f:
        f.writelines((int(k) & MASK56).to_bytes(KEY_BYTES, "little") for k in keys)


def load_manifest(path: str | os.PathLike) -> dict:
    """Load ``manifest.json`` as written by ``keygen.py``.

    Hex string fields (``ksv_source``, ``ksv_sink``, ``km_agreed``) are also
    made available as ints under the same name with a ``_int`` suffix.
    """
    with open(path) as f:
        manifest = json.load(f)
    for field in ("ksv_source", "ksv_sink", "km_agreed"):
        value = manifest.get(field)
        if isinstance(value, str):
            manifest[field + "_int"] = int(value, 16)
    return manifest
