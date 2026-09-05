"""Known-answer and behavioural tests for the HDCP 1.4 cipher reference model.

Two independent sources of golden data are used:

1. **The HDCP 1.4 specification's own published test vectors**, Appendix A
   Tables A-3 and A-4 ("Authentication test vectors" / "Cipher test vectors"),
   plus Tables A-27 and A-28 (Ri values every 128 frames).  These are the
   numbers reproduced by Rob Johnson and Mikhail Rubnich's FreeBSD-licensed
   reference implementation at https://github.com/rtjohnso/hdcp
   (``hdcp.c: print_test_vectors()``, whose comment reads "Print test vectors
   (See Tables A-3 and A-4 of HDCP Specification)"), from which the literals in
   ``SPEC_VECTORS`` and ``SPEC_STREAM`` below were transcribed.

2. **Vectors generated from the NeTV RTL that this model must agree with.**
   ``legacy/overlay/hdcp_cipher.v`` + ``hdcp_block.v`` + ``hdcp_lfsr.v``
   (+ ``diff_network.v``, ``shuffle_network.v``) were driven by a small
   testbench under ``tmp/hdcp_tb/tb_hdcp.v`` and simulated with Vivado 2025.2::

       source /opt/Xilinx/2025.2/Vivado/settings64.sh
       xvlog $OV/hdcp_cipher.v $OV/hdcp_block.v $OV/hdcp_lfsr.v \\
             $OV/diff_network.v $OV/shuffle_network.v tb_hdcp.v
       xelab tb -s tbsim && xsim tbsim -R

   The testbench pulses ``hdcpBlockCipher_init``+``authentication`` for one
   cycle, waits for ``stream_ready``, reads the internal ``Ks``/``Mi``
   registers and a mirror of the Mi shift register carrying ``pr_data[23:16]``
   (which gives R0, a value the RTL itself never exposes because NeTV only
   needs the keystream), then repeats the sequence with ``authentication`` low
   for the vertical-blank frame key, then drives ``hdcpStreamCipher`` for 32
   pixels, then pulses ``hdcpRekeyCipher`` and takes 8 more pixels.

   The RTL reproduces the specification's Table A-3/A-4 vectors exactly and
   applies exactly 48 + 56 block clocks, so **no spec/RTL discrepancy had to be
   resolved**; ``RTL_VECTORS`` simply pins the agreement for inputs the spec
   does not cover (notably Km=0x0123456789abcd, An=0xfedcba9876543210).
"""

import pytest

from netv2.hdcp.cipher import (
    HDCPCipher,
    block_round,
    lfsr_init,
    lfsr_step,
    output_function,
)

# (Km, REPEATER, An, Ks, M0, R0, K1, M1) -- HDCP 1.4 Table A-3 / A-4.
SPEC_VECTORS = [
    (0x5309C7D22FCECC, 0, 0x34271C130C070403,
     0x54294B7C040E35, 0xA02BC815E73D001C, 0x8AE0,
     0xD692B7EE1D40E8, 0x1DBF44E50F523E56),
    (0xF6AEE46089C923, 0, 0x445E62A53AD10FE5,
     0x4E60D941D0E8B1, 0xE7D28B9B2F46C49D, 0xFB65,
     0xE46F51311A959A, 0x445B5C6EEBF657FF),
    (0x4AFE34DBEC1205, 0, 0x83BEC2BB01C66E07,
     0x2C9BEF71DF792E, 0x8E1E91F6D8AE4C25, 0x3435,
     0xF3E27849D067C1, 0x23D89127A5EE6C26),
    (0xA423D78B8676A7, 0, 0x0351F7175406A74D,
     0x1963DEB799EE82, 0xD05D8C26378A126E, 0x4FD5,
     0x65F793E160EC27, 0x68BE984885AAFEF7),
    (0x5309C7D22FCECC, 1, 0x34271C130C070403,
     0xBC607B21D48E97, 0x372D3DCE38BBE78F, 0x6485,
     0x98B281E1876A9A, 0x016F9561E001F80D),
    (0xF6AEE46089C923, 1, 0x445E62A53AD10FE5,
     0xB7894F1754CAAA, 0x43D609C682C956E1, 0x3F68,
     0xFFBFEA4BC7FD2C, 0x2A067368042FA1AA),
    (0x4AFE34DBEC1205, 1, 0x83BEC2BB01C66E07,
     0xFE3717C12F3BB1, 0x536DEE1E44A58BF4, 0xDD9B,
     0xA1EC276B2DDAF0, 0xB365F8813C45DB0B),
    (0xA423D78B8676A7, 1, 0x0351F7175406A74D,
     0xAAC4147081A2D0, 0x38B57AD3CDD1B266, 0x7930,
     0x0F0B83888E3209, 0x06471E358F601CE4),
]

# Frame 1 stream cipher output, 8 pixels of line 0 then 8 pixels of line 1
# (an hdcpRekeyCipher separates the two lines).  HDCP 1.4 Table A-4.
SPEC_STREAM = {
    0: ([0x59C03E, 0x9EE5FE, 0x9AF919, 0x5B5D6C, 0x55DCDE, 0xE58763, 0xBEFCC7, 0xA1B565],
        [0x126B14, 0x064A73, 0xF8BB15, 0xCCE621, 0x879578, 0xD203F7, 0x628144, 0x80D875]),
    3: ([0xB82C9C, 0x9B34E3, 0x1CFAD7, 0x00A008, 0xCEC3F4, 0xF43627, 0xB636F7, 0x24BD8B],
        [0x739F2E, 0xF61E16, 0xE28C59, 0xD98A86, 0xC5EB96, 0xC0B3CE, 0xEB26F3, 0xF49EE1]),
    4: ([0x334E55, 0xD2374E, 0x0E22F5, 0xC1318F, 0xDCA1A7, 0x27E7C3, 0x563EC9, 0x10DC2F],
        [0x730322, 0x690136, 0x3D2753, 0xFE4150, 0xA8188D, 0x1A0291, 0x8C29CE, 0x89CDBF]),
    7: ([0xC2C884, 0x2F7C68, 0x900BE5, 0x9EDE54, 0x78CD8C, 0x38A5B8, 0x32FF1E, 0xE4D90C],
        [0x620F61, 0x337352, 0xCD96FD, 0x53EAD5, 0x33A931, 0xCC3486, 0x6EE0BB, 0xD2FC4B]),
}

# Ri as read from the receiver after N frames -- HDCP 1.4 Table A-28 (and
# Table A-27 rows R1/R2), pair A1-B1 with REPEATER = 0, i.e. SPEC_VECTORS[0].
SPEC_RI_BY_FRAME = {128: 0x6153, 256: 0xD189}

# Golden data captured from bunnie's RTL under Vivado xsim (see module
# docstring).  Ks/M0/R0/K1/M1, then 32 stream words of line 0 of frame 1,
# then 8 stream words of line 1 (after one hdcpRekeyCipher).
RTL_VECTORS = [
    {
        "km": 0x0123456789ABCD, "an": 0xFEDCBA9876543210, "repeater": 0,
        "ks": 0x2D97FB86CAFACA, "m0": 0xEE54B83A96C22D2A, "r0": 0x343F,
        "k1": 0x1C19F9AB68F2E5, "m1": 0x7914C4956C9CD405,
        "line0": [
            0xF32048, 0x0938A6, 0xBB0AD3, 0x6F2D2D, 0x8AFAF5, 0xEF1683,
            0x2AFA49, 0x19796C, 0x14220E, 0xA7A2EA, 0xB53E4E, 0xE1ACBE,
            0x4C484D, 0xFCD3F8, 0x7DE6D5, 0xA74D38, 0xD9C4DE, 0x105C5C,
            0x0228D0, 0x7C4F7E, 0xCAF552, 0x1B984E, 0xC50DF9, 0xA2CF9E,
            0xA0083A, 0xED2706, 0x75FF58, 0x645E1E, 0x7965BE, 0x1D7AB7,
            0x7D7C86, 0x7A22E3],
        "line1": [
            0x128A7E, 0xCA9E14, 0x003E42, 0x7FAC93, 0x69B54C, 0xBCF96F,
            0x337865, 0x14E7E1],
    },
    {
        "km": 0x5309C7D22FCECC, "an": 0x34271C130C070403, "repeater": 0,
        "ks": 0x54294B7C040E35, "m0": 0xA02BC815E73D001C, "r0": 0x8AE0,
        "k1": 0xD692B7EE1D40E8, "m1": 0x1DBF44E50F523E56,
        "line0": [
            0x59C03E, 0x9EE5FE, 0x9AF919, 0x5B5D6C, 0x55DCDE, 0xE58763,
            0xBEFCC7, 0xA1B565, 0xC353B3, 0xEA8E38, 0x0AA33E, 0x13C235,
            0x40E994, 0x0BF78B, 0x13376D, 0x7D190C, 0x220992, 0x8043EE,
            0x6B9A6C, 0x80FD62, 0x271354, 0x8FCDFF, 0x72993C, 0x520D15,
            0xCD90CB, 0x83D50E, 0x685F6E, 0x1073F0, 0x2655AD, 0xFE545D,
            0x838F19, 0xB28C11],
        "line1": [
            0xD3DE39, 0x398018, 0x12B265, 0x9B488E, 0xEE2C5A, 0x520C3F,
            0xF8F6E7, 0x480C84],
    },
    {
        "km": 0xA423D78B8676A7, "an": 0x0351F7175406A74D, "repeater": 0,
        "ks": 0x1963DEB799EE82, "m0": 0xD05D8C26378A126E, "r0": 0x4FD5,
        "k1": 0x65F793E160EC27, "m1": 0x68BE984885AAFEF7,
        "line0": [
            0xB82C9C, 0x9B34E3, 0x1CFAD7, 0x00A008, 0xCEC3F4, 0xF43627,
            0xB636F7, 0x24BD8B, 0x440431, 0xED9801, 0x25363A, 0x841E2B,
            0x0E5041, 0xC8F31A, 0x4E552D, 0xE6F21B, 0x5D8F45, 0xDEF473,
            0x5E42A0, 0x6CA0F0, 0x46829F, 0x6DD7EA, 0xF2074D, 0xA2542A,
            0x44AE5C, 0xD02C19, 0x849D71, 0x07AFD6, 0xECE216, 0x9EE982,
            0x1BE135, 0xA67CB1],
        "line1": [
            0x7D2CDA, 0x55E33B, 0xEC4DE9, 0x7C47D3, 0xF14A42, 0xE30D6F,
            0xBBEA1F, 0xC16682],
    },
]


@pytest.mark.parametrize("vec", SPEC_VECTORS, ids=lambda v: f"km{v[0]:014x}_rep{v[1]}")
def test_spec_authentication_and_frame_key(vec):
    """Ks, M0, R0 (Table A-3) and K1, M1 (Table A-4) match the specification."""
    km, repeater, an, ks_x, m0_x, r0_x, k1_x, m1_x = vec
    cipher = HDCPCipher(repeater=repeater)
    assert cipher.authenticate(km, an) == (ks_x, m0_x, r0_x)
    assert cipher.rekey_frame() == (k1_x, m1_x)


@pytest.mark.parametrize("idx", sorted(SPEC_STREAM))
def test_spec_stream_cipher_output(idx):
    """The 24-bit keystream for frame 1, lines 0 and 1, matches Table A-4."""
    km, repeater, an = SPEC_VECTORS[idx][0], SPEC_VECTORS[idx][1], SPEC_VECTORS[idx][2]
    line0, line1 = SPEC_STREAM[idx]
    cipher = HDCPCipher(repeater=repeater)
    cipher.authenticate(km, an)
    cipher.rekey_frame()
    assert cipher.stream(len(line0)) == line0
    cipher.rekey_line()
    assert cipher.stream(len(line1)) == line1


@pytest.mark.parametrize("vec", RTL_VECTORS, ids=lambda v: f"rtl_km{v['km']:014x}")
def test_matches_netv_rtl(vec):
    """Agreement with the NeTV RTL as simulated by Vivado xsim."""
    cipher = HDCPCipher(repeater=vec["repeater"])
    assert cipher.authenticate(vec["km"], vec["an"]) == (vec["ks"], vec["m0"], vec["r0"])
    assert cipher.rekey_frame() == (vec["k1"], vec["m1"])
    assert cipher.stream(len(vec["line0"])) == vec["line0"]
    cipher.rekey_line()
    assert cipher.stream(len(vec["line1"])) == vec["line1"]


def test_stream_length_and_determinism():
    """stream(n) yields n 24-bit words and is reproducible from the same inputs."""
    km, repeater, an = SPEC_VECTORS[0][0], SPEC_VECTORS[0][1], SPEC_VECTORS[0][2]

    def run():
        cipher = HDCPCipher(repeater=repeater)
        cipher.authenticate(km, an)
        cipher.rekey_frame()
        return cipher.stream(64)

    words = run()
    assert len(words) == 64
    assert all(0 <= w <= 0xFFFFFF for w in words)
    assert words == run()
    assert len(set(words)) > 32, "keystream should not be obviously degenerate"


def test_stream_24bits_matches_stream():
    """stream_24bits() advances exactly one pixel clock."""
    km, repeater, an = SPEC_VECTORS[0][0], SPEC_VECTORS[0][1], SPEC_VECTORS[0][2]
    a = HDCPCipher(repeater=repeater)
    a.authenticate(km, an)
    a.rekey_frame()
    b = HDCPCipher(repeater=repeater)
    b.authenticate(km, an)
    b.rekey_frame()
    assert [a.stream_24bits() for _ in range(16)] == b.stream(16)


def test_ri_updates_every_128_frames():
    """Ri holds R0 until the 128th frame, then follows Table A-28.

    Spec section 2.2.3: Ri "is updated for every 128th frame counter increment,
    starting with the 128th".  The per-frame value is still available as
    ``ri_frame``, and it does change every frame.
    """
    km, repeater, an = SPEC_VECTORS[0][0], SPEC_VECTORS[0][1], SPEC_VECTORS[0][2]
    cipher = HDCPCipher(repeater=repeater)
    _, _, r0 = cipher.authenticate(km, an)
    assert cipher.ri == r0
    assert cipher.frame_counter == 0

    per_frame = set()
    for frame in range(1, max(SPEC_RI_BY_FRAME) + 1):
        cipher.rekey_frame()
        per_frame.add(cipher.ri_frame)
        assert cipher.frame_counter == frame
        if frame in SPEC_RI_BY_FRAME:
            assert cipher.ri == SPEC_RI_BY_FRAME[frame], f"Ri wrong at frame {frame}"
        elif frame < 128:
            assert cipher.ri == r0, f"Ri changed early at frame {frame}"
        else:
            assert cipher.ri == SPEC_RI_BY_FRAME[128 * (frame // 128)]
    assert len(per_frame) > 200, "the per-frame Ri should change every frame"


def test_rekey_frame_requires_authentication():
    with pytest.raises(RuntimeError):
        HDCPCipher().rekey_frame()


def test_block_round_reproduces_ks():
    """block_round() alone, run for the 48 clocks of Table 4-8 steps 1-2, gives Ks.

    This exercises the register loading convention of spec section 4.5 (K takes
    the 56-bit Km in Kx||Ky with Kz zero; B takes REPEATER || An in Bx||By plus
    the low nine bits of Bz) and the "least significant 56 bits of B" rule.
    """
    km, repeater, an, ks_x = (SPEC_VECTORS[4][0], SPEC_VECTORS[4][1],
                           SPEC_VECTORS[4][2], SPEC_VECTORS[4][3])
    mask28 = (1 << 28) - 1
    state = (an & mask28, (an >> 28) & mask28, ((an >> 56) & 0xFF) | (repeater << 8),
             km & mask28, (km >> 28) & mask28, 0)
    for _ in range(48):
        state = block_round(*state)
    assert (state[0] | (state[1] << 28)) == ks_x


def test_block_round_rekey_forces_ky13():
    """With rekey asserted the new Ky[13] comes from the LFSR module."""
    state = (0x0123456, 0x789ABCD, 0xEF01234, 0x5678, 0x9ABCDEF, 0x1234567)
    plain = block_round(*state)
    for bit in (0, 1):
        rekeyed = block_round(*state, lfsr_bit=bit)
        assert (rekeyed[4] >> 13) & 1 == bit
        assert rekeyed[4] | (1 << 13) == plain[4] | (1 << 13)
        assert rekeyed[:4] == plain[:4] and rekeyed[5] == plain[5]


def test_lfsr_init_bit_layout():
    """LFSR seeding follows spec section 4.2: 12/13/15/16 bits plus an inverted bit."""
    iv = 0
    l0, l1, l2, l3, sn_a, sn_b = lfsr_init(iv)
    assert (l0, l1, l2, l3) == (1 << 12, 1 << 13, 1 << 15, 1 << 16)
    assert (sn_a, sn_b) == (0x0, 0xF)

    iv = (1 << 6) | (1 << 18) | (1 << 32) | (1 << 47)
    l0, l1, l2, l3, _, _ = lfsr_init(iv)
    assert l0 == 1 << 6 and l1 == 1 << 6 and l2 == 1 << 7 and l3 == 1 << 7

    all_ones = lfsr_init((1 << 56) - 1)
    assert all_ones[:4] == (0x0FFF, 0x1FFF, 0x7FFF, 0xFFFF)


def test_lfsr_step_is_pure_and_bounded():
    state = lfsr_init(0x0123456789ABCD)
    original = state
    bits = []
    for _ in range(200):
        bit, state = lfsr_step(state)
        assert bit in (0, 1)
        for reg, width in zip(state[:4], (13, 14, 16, 17)):
            assert 0 <= reg < (1 << width)
        assert 0 <= state[4] <= 0xF and 0 <= state[5] <= 0xF
        bits.append(bit)
    assert original == lfsr_init(0x0123456789ABCD), "lfsr_step must not mutate its input"
    assert 0 < sum(bits) < 200, "the LFSR output must not be constant"


def test_output_function_shape_and_use():
    """output_function() is the very function the stream cipher taps."""
    km, repeater, an = SPEC_VECTORS[0][0], SPEC_VECTORS[0][1], SPEC_VECTORS[0][2]
    cipher = HDCPCipher(repeater=repeater)
    cipher.authenticate(km, an)
    cipher.rekey_frame()
    _, by, bz = cipher._b
    _, ky, kz = cipher._k
    assert output_function(bz, by, kz, ky) == cipher.stream_24bits()
    assert 0 <= output_function(bz, by, kz, ky) <= 0xFFFFFF
    assert output_function(0, 0, 0, 0) == 0
