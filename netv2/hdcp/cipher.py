"""Bit-exact pure-Python model of the HDCP 1.4 cipher (HDMI / HDCP 1.x).

Reference: "High-bandwidth Digital Content Protection System, Revision 1.4",
Digital Content Protection LLC, 8 July 2009 -- chapter 4, "HDCP Cipher".

Structure (spec section 4.1, Fig. 4-1) -- three co-operating pieces:
the **LFSR module** (section 4.2), four LFSRs of 13/14/16/17 bits seeded from a
56-bit value and combined through four shuffle networks into one bit per clock;
the **block module** (section 4.3), two 84-bit round registers B and K each
split into 28-bit x/y/z sub-registers (Table 4-10) and advanced by the B and K
round functions (S-boxes of Tables 4-3/4-4, diffusion network of Tables
4-5/4-6); and the **output function** (section 4.4, Table 4-7), 24 bits per
clock which XOR the 24-bit TMDS pixel.

Operation (spec section 4.5, Tables 4-8/4-9/4-11):

  hdcpBlockCipher   1. load B and K;  2. 48 clocks of the block module (LFSR
                    idle);  3. save the least significant 56 bits of B as
                    Ks/Ki;  4. copy the 84-bit B register into K;  5. reload B;
                    6. seed the LFSR module with that 56-bit Ks/Ki;  7. assert
                    rekey;  8. 56 clocks of both modules, the output function
                    during clocks 53..56 yielding Mi (bits 15..0) and Ri (bits
                    23..16) per Table 4-11;  9. de-assert rekey.
                    At authentication K init = Km (56 bits), B init =
                    REPEATER || An, giving Ks / R0 / M0.  At each vertical
                    blank K init = Ks (56 bits), B init = REPEATER || Mi-1,
                    giving Ki / Ri / Mi.
  hdcpStreamCipher  one clock of both modules per encrypted pixel, rekey low,
                    24 bits of output function per pixel.
  hdcpRekeyCipher   56 clocks of both modules with rekey asserted, during each
                    horizontal blanking interval that follows an active line;
                    no reload and no output.

Ri (spec section 2.2.3) "is a 16-bit value used for link integrity
verification, and is updated for every 128th frame counter increment, starting
with the 128th"; hence :attr:`HDCPCipher.ri` holds R0 until 128 frames have
been keyed and then changes only on multiples of 128 (spec Tables A-27/A-28).

Cross-checks: every table and ordering decision below was verified against
bunnie's public NeTV RTL (``legacy/overlay/hdcp_{cipher,block,lfsr}.v`` plus
``diff_network.v`` / ``shuffle_network.v``), simulated under Vivado xsim, which
reproduces the spec's own Table A-3/A-4 vectors exactly.  No spec/RTL
discrepancy was found: the RTL applies exactly 48 and 56 block clocks, loads
REPEATER into Bz[8] (tied to zero there) and takes Ks/Ki from B[55:0].  Rob
Johnson and Mikhail Rubnich's FreeBSD-licensed bit-sliced C implementation
(github.com/rtjohnso/hdcp) was a second, independent cross-check.

Pure Python, standard library only.
"""

from __future__ import annotations

MASK16 = (1 << 16) - 1
MASK28 = (1 << 28) - 1
MASK56 = (1 << 56) - 1
MASK64 = (1 << 64) - 1

# Block module S-boxes, SBOX_B[g][n] / SBOX_K[g][n] for group g = 0..6 (spec
# Tables 4-3/4-4, the same 4-bit permutations as hdcp_block.v's case tables).
SBOX_B = (
    (12, 9, 3, 0, 11, 5, 13, 6, 2, 4, 14, 7, 8, 15, 1, 10),
    (3, 8, 14, 1, 5, 2, 11, 13, 10, 4, 9, 7, 6, 15, 12, 0),
    (7, 4, 1, 10, 11, 13, 14, 3, 12, 15, 6, 0, 2, 8, 9, 5),
    (6, 3, 1, 4, 10, 12, 15, 2, 5, 14, 11, 8, 9, 7, 0, 13),
    (3, 6, 15, 12, 4, 1, 9, 2, 5, 8, 10, 7, 11, 13, 0, 14),
    (11, 14, 6, 8, 5, 2, 12, 7, 1, 4, 15, 3, 10, 13, 9, 0),
    (1, 11, 7, 4, 2, 5, 12, 9, 13, 6, 8, 15, 14, 0, 3, 10),
)
SBOX_K = (
    (8, 14, 5, 9, 3, 0, 12, 6, 1, 11, 15, 2, 4, 7, 10, 13),
    (1, 6, 4, 15, 8, 3, 11, 5, 10, 0, 9, 12, 7, 13, 14, 2),
    (13, 11, 8, 6, 7, 4, 2, 15, 1, 12, 14, 0, 10, 3, 9, 5),
    (0, 14, 11, 7, 12, 3, 2, 13, 15, 4, 8, 1, 9, 10, 5, 6),
    (12, 7, 15, 8, 11, 14, 1, 4, 6, 10, 3, 5, 0, 9, 13, 2),
    (1, 12, 7, 2, 8, 3, 4, 14, 11, 5, 0, 15, 13, 6, 10, 9),
    (10, 7, 6, 1, 0, 14, 3, 13, 12, 9, 11, 2, 15, 5, 4, 8),
)

# Block module diffusion network (spec Tables 4-5 / 4-6), 8 columns x 7 rows
# of one-bit lanes.  Row i of column j takes an input bit from the z or y
# sub-register, XORs in a key bit and drives an output bit of x or y; each
# column computes (exactly ``diff_network.v``)
#     out[i] = key[i] ^ (XOR of the column's inputs except input[i])   for i<6
#     out[6] = key[6] ^ (XOR of all of the column's inputs)
# Key bits (B network only) are Ky[i] for j==0 and Ky[7*(j-4)+i] for j in 5..7,
# zero for columns 1..4; the K network adds no key at all.  In _BI, row i,
# column j, "z12" means Bz[12]/Kz[12] and "y3" means By[3]/Ky[3]; the derived
# _IN_MAP[j][i] = (from_z, index) and _OUT_MAP[j][i] = (to_x, index).
_BI = (
    ("z0", "z7", "z10", "z13", "z16", "y16", "y20", "y24"),
    ("z1", "z8", "z11", "z14", "z17", "y17", "y21", "y25"),
    ("z2", "z9", "z12", "z15", "z18", "y18", "y22", "y26"),
    ("z3", "y0", "y3", "y6", "y9", "y19", "y23", "y27"),
    ("z4", "y1", "y4", "y7", "y10", "z19", "z22", "z25"),
    ("z5", "y2", "y5", "y8", "y11", "z20", "z23", "z26"),
    ("z6", "y12", "y13", "y14", "y15", "z21", "z24", "z27"),
)
_BO_COL = (0, 0, 1, 2, 3, 1, 2, 3)

_IN_MAP = tuple(
    tuple((_BI[i][j][0] == "z", int(_BI[i][j][1:])) for i in range(7)) for j in range(8)
)
_OUT_MAP = tuple(
    tuple((j == 0 or j > 4, 4 * i + _BO_COL[j]) for i in range(7)) for j in range(8)
)
_KEY_SHIFT = (0, None, None, None, None, 7, 14, 21)

_PARITY7 = tuple(0x7F if v.bit_count() & 1 else 0 for v in range(128))


def _sbox(x: int, tables) -> int:
    """Seven 4-bit S-boxes on a 28-bit x register -> new z register (section 4.3).

    Group g takes x[g], x[g+7], x[g+14], x[g+21] as a nibble (LSB first) and
    drives z[g], z[g+7], z[g+14], z[g+21].
    """
    z = 0
    for g in range(7):
        nib = ((x >> g) & 1) | (((x >> (g + 7)) & 1) << 1) \
            | (((x >> (g + 14)) & 1) << 2) | (((x >> (g + 21)) & 1) << 3)
        out = tables[g][nib]
        z |= (out & 1) << g
        z |= ((out >> 1) & 1) << (g + 7)
        z |= ((out >> 2) & 1) << (g + 14)
        z |= ((out >> 3) & 1) << (g + 21)
    return z


def _diffuse(z: int, y: int, ky: int | None) -> tuple[int, int]:
    """Diffusion network over (z, y) -> new (x, y); *ky* is ``None`` for K."""
    out_x = out_y = 0
    for j in range(8):
        v = 0
        for i, (from_z, idx) in enumerate(_IN_MAP[j]):
            v |= (((z if from_z else y) >> idx) & 1) << i
        shift = _KEY_SHIFT[j]
        key = 0 if (ky is None or shift is None) else (ky >> shift) & 0x7F
        o = key ^ (v & 0x3F) ^ _PARITY7[v]
        for i, (to_x, idx) in enumerate(_OUT_MAP[j]):
            bit = ((o >> i) & 1) << idx
            if to_x:
                out_x |= bit
            else:
                out_y |= bit
    return out_x, out_y


def block_round(bx: int, by: int, bz: int, kx: int, ky: int, kz: int,
                lfsr_bit: int | None = None):
    """One clock of the block module (spec section 4.3).

    Returns the next ``(bx, by, bz, kx, ky, kz)``.  Both round functions read
    the *current* registers, the B round function using the *current* Ky.  A
    non-``None`` *lfsr_bit* asserts rekey: the new Ky[13] then comes from the
    LFSR module instead of the diffusion network (``hdcp_block.v``'s o_Ky[13]).
    """
    n_bz = _sbox(bx, SBOX_B)
    n_bx, n_by = _diffuse(bz, by, ky)
    n_kz = _sbox(kx, SBOX_K)
    n_kx, n_ky = _diffuse(kz, ky, None)
    if lfsr_bit is not None:
        n_ky = (n_ky & ~(1 << 13)) | ((lfsr_bit & 1) << 13)
    return n_bx, n_by, n_bz, n_kx, n_ky, n_kz


# Output function (spec section 4.4, Table 4-7): each of the 24 output bits is
# the XOR of seven Bz&Kz products with one By and one Ky bit.  Row layout is
# bz0, kz0, ..., bz6, kz6, by, ky.
_OFUNC = (
    (17, 3, 26, 6, 22, 0, 27, 9, 21, 4, 18, 22, 2, 5, 5, 10),
    (5, 20, 20, 18, 15, 7, 24, 23, 2, 15, 25, 5, 0, 3, 16, 25),
    (22, 7, 5, 19, 14, 2, 16, 10, 25, 22, 17, 4, 20, 13, 11, 21),
    (19, 6, 3, 14, 15, 9, 11, 8, 21, 17, 16, 18, 27, 12, 1, 24),
    (19, 25, 6, 6, 17, 5, 18, 2, 22, 10, 7, 15, 9, 21, 12, 8),
    (3, 27, 7, 14, 4, 2, 8, 4, 16, 24, 6, 19, 5, 1, 17, 12),
    (8, 17, 21, 26, 27, 4, 2, 16, 11, 27, 24, 7, 12, 22, 3, 11),
    (9, 9, 5, 10, 7, 19, 4, 11, 8, 7, 13, 6, 3, 8, 15, 23),
    (26, 13, 13, 12, 23, 18, 10, 24, 11, 15, 7, 23, 15, 7, 19, 16),
    (1, 0, 0, 5, 19, 20, 11, 25, 13, 1, 16, 24, 24, 9, 18, 27),
    (26, 14, 13, 23, 9, 27, 14, 25, 10, 17, 4, 19, 1, 1, 2, 22),
    (21, 6, 15, 21, 5, 17, 3, 15, 13, 26, 25, 11, 16, 16, 27, 7),
    (20, 11, 7, 22, 18, 20, 12, 0, 17, 26, 1, 23, 16, 17, 0, 2),
    (14, 8, 23, 4, 1, 3, 12, 14, 24, 20, 6, 26, 18, 23, 9, 15),
    (19, 19, 6, 0, 21, 18, 25, 2, 23, 13, 1, 8, 10, 24, 8, 14),
    (3, 16, 0, 21, 27, 24, 23, 25, 19, 12, 8, 27, 4, 15, 7, 18),
    (6, 3, 5, 5, 14, 8, 22, 25, 24, 7, 18, 27, 2, 2, 21, 26),
    (3, 11, 4, 14, 2, 23, 6, 17, 22, 22, 14, 13, 12, 19, 26, 4),
    (25, 1, 21, 16, 19, 14, 9, 11, 10, 12, 15, 6, 13, 10, 22, 19),
    (23, 21, 11, 1, 10, 10, 20, 20, 1, 18, 12, 26, 14, 9, 4, 13),
    (11, 20, 26, 21, 20, 9, 17, 25, 8, 12, 23, 3, 0, 15, 24, 0),
    (9, 18, 17, 12, 26, 21, 4, 27, 27, 1, 0, 16, 15, 24, 6, 20),
    (22, 13, 12, 0, 2, 3, 10, 16, 7, 22, 20, 11, 25, 26, 13, 9),
    (27, 2, 24, 0, 26, 13, 8, 5, 0, 4, 9, 8, 18, 10, 23, 3),
)


def output_function(bz: int, by: int, kz: int, ky: int) -> int:
    """The 24-bit output of the cipher for the current state (spec section 4.4)."""
    out = 0
    for n, row in enumerate(_OFUNC):
        bit = ((by >> row[14]) & 1) ^ ((ky >> row[15]) & 1)
        for p in range(0, 14, 2):
            bit ^= ((bz >> row[p]) & 1) & ((kz >> row[p + 1]) & 1)
        out |= bit << n
    return out


# LFSR module (spec section 4.2).  State is (lfsr0, lfsr1, lfsr2, lfsr3, sn_a,
# sn_b); sn_a/sn_b hold the four shuffle-network A/B flip-flops as 4-bit words.
_LFSR_LEN = (13, 14, 16, 17)
_LFSR_TAPS = ((3, 7, 12), (4, 8, 13), (5, 9, 15), (5, 11, 16))
_LFSR_FEEDBACK = ((4, 8, 10, 12), (3, 5, 6, 9, 10, 13),
                  (4, 6, 7, 11, 14, 15), (4, 10, 14, 16))
_LFSR_IV = ((0, 12, 6), (12, 13, 18), (25, 15, 32), (40, 16, 47))


def lfsr_init(iv: int) -> tuple:
    """Seed the LFSR module from a 56-bit value (spec section 4.2, Table 4-2).

    LFSR0 takes iv[11:0] with ~iv[6] on top, LFSR1 iv[24:12] with ~iv[18],
    LFSR2 iv[39:25] with ~iv[32], LFSR3 iv[55:40] with ~iv[47].  The shuffle
    networks reset to A=0, B=1.
    """
    regs = []
    for lo, width, inv in _LFSR_IV:
        low = (iv >> lo) & ((1 << width) - 1)
        regs.append((((iv >> inv) & 1) ^ 1) << width | low)
    return (regs[0], regs[1], regs[2], regs[3], 0x0, 0xF)


def lfsr_step(state: tuple) -> tuple[int, tuple]:
    """One clock of the LFSR module: return ``(output_bit, next_state)``.

    The output bit is combinational in the *current* state (spec section 4.2,
    Fig. 4-3): the four "tap 0" bits are XORed, threaded through the four
    shuffle networks selected by the "tap 1" bits, then XORed with the four
    "tap 2" bits.  The shuffle flip-flops and the LFSRs then shift.
    """
    l0, l1, l2, l3, sn_a, sn_b = state
    regs = (l0, l1, l2, l3)
    d = 0
    for i in range(4):
        d ^= (regs[i] >> _LFSR_TAPS[i][0]) & 1
    n_a = 0
    n_b = 0
    for i in range(4):
        sel = (regs[i] >> _LFSR_TAPS[i][1]) & 1
        a = (sn_a >> i) & 1
        b = (sn_b >> i) & 1
        if sel:
            out, na, nb = b, d, a
        else:
            out, na, nb = a, b, d
        n_a |= na << i
        n_b |= nb << i
        d = out
    for i in range(4):
        d ^= (regs[i] >> _LFSR_TAPS[i][2]) & 1
    nxt = []
    for i in range(4):
        fb = 0
        for t in _LFSR_FEEDBACK[i]:
            fb ^= (regs[i] >> t) & 1
        nxt.append(((regs[i] << 1) | fb) & ((1 << _LFSR_LEN[i]) - 1))
    return d, (nxt[0], nxt[1], nxt[2], nxt[3], n_a, n_b)


class HDCPCipher:
    """The HDCP 1.4 cipher as a stateful object (spec chapter 4).

    Typical use, mirroring the protocol of spec sections 2.2.1-2.2.3::

        c = HDCPCipher(repeater=0)
        ks, m0, r0 = c.authenticate(km, an)   # first part of authentication
        c.rekey_frame()                       # vertical blank before frame 1
        words = c.stream(width)               # 24 bits per encrypted pixel
        c.rekey_line()                        # horizontal blank after the line
    """

    def __init__(self, repeater: int = 0):
        self.repeater = repeater & 1
        self.ks: int | None = None
        self.ki: int | None = None
        self.m: int | None = None
        self.r0: int | None = None
        self.ri_current: int | None = None
        self.ri_frame: int | None = None
        self.frame_counter = 0
        self._b = (0, 0, 0)          # Bx, By, Bz
        self._k = (0, 0, 0)          # Kx, Ky, Kz
        self._lfsr = lfsr_init(0)

    # -- internals ---------------------------------------------------------
    def _load_b(self, value: int) -> None:
        """Load the 65-bit REPEATER || value into B (spec section 4.5)."""
        self._b = (value & MASK28, (value >> 28) & MASK28,
                   ((value >> 56) & 0xFF) | (self.repeater << 8))

    def _step(self, rekey: bool, want_output: bool = False) -> int:
        """Clock the block module (and the LFSR module) once."""
        out = 0
        if want_output:
            out = output_function(self._b[2], self._b[1], self._k[2], self._k[1])
        bit, self._lfsr = lfsr_step(self._lfsr)
        bx, by, bz, kx, ky, kz = block_round(*self._b, *self._k,
                                             lfsr_bit=bit if rekey else None)
        self._b = (bx, by, bz)
        self._k = (kx, ky, kz)
        return out

    def _block_cipher(self, k_init: int, b_init: int) -> tuple[int, int, int]:
        """hdcpBlockCipher (spec Table 4-8) -> (Ks/Ki, Mi, Ri)."""
        self._k = (k_init & MASK28, (k_init >> 28) & MASK28, 0)
        self._load_b(b_init)
        for _ in range(48):                                   # steps 1-2
            bx, by, bz, kx, ky, kz = block_round(*self._b, *self._k)
            self._b = (bx, by, bz)
            self._k = (kx, ky, kz)
        key = (self._b[0] | (self._b[1] << 28)) & MASK56      # step 3
        self._k = self._b                                     # step 4
        self._load_b(b_init)                                  # step 5
        self._lfsr = lfsr_init(key)                           # step 6
        mi = ri = 0
        for clk in range(1, 57):                              # steps 7-9
            out = self._step(True, want_output=clk >= 53)
            if clk >= 53:                                     # Table 4-11
                mi = ((mi << 16) | (out & MASK16)) & MASK64
                if clk >= 55:
                    ri = ((ri << 8) | ((out >> 16) & 0xFF)) & MASK16
        return key, mi, ri

    # -- public API --------------------------------------------------------
    def authenticate(self, km: int, an: int) -> tuple[int, int, int]:
        """First part of authentication: return ``(Ks, M0, R0)``.

        Spec sections 2.2.1 and 4.5 (Table 4-9, "hdcpBlockCipher at
        Authentication"): K takes the 56-bit Km, B the 65-bit REPEATER || An.
        """
        ks, m0, r0 = self._block_cipher(km & MASK56, an & MASK64)
        self.ks = ks
        self.m = m0
        self.r0 = r0
        self.ri_current = r0
        self.ri_frame = r0
        self.frame_counter = 0
        return ks, m0, r0

    def rekey_frame(self) -> tuple[int, int]:
        """Vertical-blank frame key calculation: return ``(Ki, Mi)``.

        Spec sections 2.2.3 and 4.5 (Table 4-9, "hdcpBlockCipher at Vertical
        Blank"): K takes the 56-bit Ks, B takes REPEATER || Mi-1.  Increments
        the frame counter and, on every 128th frame, publishes the new
        link-integrity value on :attr:`ri`.
        """
        if self.ks is None or self.m is None:
            raise RuntimeError("authenticate() must be called first")
        ki, mi, ri = self._block_cipher(self.ks, self.m)
        self.ki = ki
        self.m = mi
        self.ri_frame = ri
        self.frame_counter += 1
        if self.frame_counter % 128 == 0:
            self.ri_current = ri
        return ki, mi

    def rekey_line(self) -> None:
        """hdcpRekeyCipher: 56 clocks with rekey asserted, no output.

        Spec section 4.5; run during each horizontal blanking interval that
        immediately follows an active line of pixel data.
        """
        for _ in range(56):
            self._step(True)

    def stream_24bits(self) -> int:
        """hdcpStreamCipher: the 24-bit pseudo-random word for the next pixel.

        Spec section 4.5: the output function of the current state, after which
        the cipher advances one pixel clock.
        """
        return self._step(False, want_output=True)

    def stream(self, n: int) -> list[int]:
        """*n* consecutive 24-bit stream cipher words."""
        return [self._step(False, want_output=True) for _ in range(n)]

    @property
    def ri(self) -> int | None:
        """The 16-bit link-integrity value currently readable from the receiver.

        Spec section 2.2.3: Ri "is updated for every 128th frame counter
        increment, starting with the 128th", so this is R0 until 128 frames have
        been keyed and thereafter changes only on multiples of 128 (spec
        Tables A-27 / A-28).  Use :attr:`ri_frame` for the per-frame value.
        """
        return self.ri_current
