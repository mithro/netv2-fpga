"""Pure-Python model of the HDMI data-island *audio* packets and their TERC4
byte layout, used to drive and check the gateware audio-extract core in
simulation.

It builds three packet types from the public HDMI 1.4 spec -- Audio Sample
Packet (0x02), Audio Clock Regeneration (0x01) and Audio InfoFrame (0x84) --
computes the BCH ECC over the header and each subpacket, and serialises the
whole thing into the per-channel 10-bit TMDS token stream that the ported
``DecodeTERC4`` state machine consumes (one ``(raw0, raw1, raw2)`` tuple per
pixel).

Bit / byte conventions (must match ``netv2/gateware/video/audio/parser.py``):

* Header  (32 bits): carried on channel-0 bit 2, one bit per TERC4 char.
  bits[0:24] = HB0,HB1,HB2 (each byte LSB-first); bits[24:32] = BCH ECC byte.
* Subpacket k (64 bits): carried on channels 1 and 2; for TERC4 char c
  bit(2c) = ch1.d[k], bit(2c+1) = ch2.d[k].
  bits[0:56] = PB0..PB6 (each byte LSB-first); bits[56:64] = BCH ECC byte.

The BCH ECC generator is x^8 + x^7 + x^6 + x^4 + 1 (the polynomial the HDCP /
HDMI data-island ECC uses), processed LSB-first with a reflected right-shift
LFSR (mask = reflect(0xD1) = 0x8B). The gateware LFSR is the bit-for-bit
mirror of :func:`hdmi_bch_ecc`.
"""

from netv2.gateware.video.input.common import control_tokens
from netv2.gateware.video.input.decoding import (
    terc4_tokens, data_gb_tokens,
)

# --- BCH ECC (HDMI data-island) ------------------------------------------
BCH_POLY_LOW = 0xD1          # x^0..x^7 coeffs of x^8+x^7+x^6+x^4+1


def _reflect8(v):
    r = 0
    for i in range(8):
        if v & (1 << i):
            r |= 1 << (7 - i)
    return r


BCH_MASK = _reflect8(BCH_POLY_LOW)   # 0x8B


def hdmi_bch_ecc(data_bytes):
    """Compute the 8-bit HDMI/HDCP BCH ECC over ``data_bytes`` (list of ints),
    LSB-first, reflected right-shift LFSR. Mirror of the gateware LFSR."""
    ecc = 0
    for byte in data_bytes:
        for i in range(8):
            bit = (byte >> i) & 1
            fb = (ecc ^ bit) & 1
            ecc >>= 1
            if fb:
                ecc ^= BCH_MASK
    return ecc & 0xFF


# --- packet builders ------------------------------------------------------
def _header_word(hb0, hb1, hb2):
    """Pack a 32-bit header word: 3 header bytes + BCH ECC byte."""
    ecc = hdmi_bch_ecc([hb0, hb1, hb2])
    return (hb0 & 0xFF) | ((hb1 & 0xFF) << 8) | ((hb2 & 0xFF) << 16) | (ecc << 24)


def _subpacket_word(pb, corrupt=False):
    """Pack a 64-bit subpacket word from a list of 7 data bytes + BCH ECC.

    ``pb`` is a list of exactly 7 ints (PB0..PB6). If ``corrupt`` is set the
    ECC is deliberately made wrong (flip a bit) to exercise the error path."""
    assert len(pb) == 7
    ecc = hdmi_bch_ecc(pb)
    if corrupt:
        ecc ^= 0x01
    word = 0
    for i, b in enumerate(pb):
        word |= (b & 0xFF) << (8 * i)
    word |= ecc << 56
    return word


def audio_sample_packet(samples, sample_present=0x1, layout=0, b=0x0,
                        sample_flat=0x0, corrupt_sub=None):
    """Build an Audio Sample Packet (type 0x02).

    ``samples`` is a list of up to 4 subpacket entries; each entry is a
    ``(sub_a, sub_b)`` pair of 24-bit PCM samples (subframe 0 = channel A,
    subframe 1 = channel B). Only subpackets whose ``sample_present`` bit is
    set are populated.

    Header (HDMI 1.4 Table 5-12, subset):
      HB0 = 0x02
      HB1[3:0] = sample_present, HB1[4] = layout
      HB2[3:0] = sample_flat,    HB2[7:4] = B (IEC-60958 block start flags)

    Each 7-byte subpacket carries two 28-bit IEC-60958 subframes (32-bit frame
    minus the 4-bit preamble): local bits[0:24] = 24-bit sample, bit24 = V,
    bit25 = U, bit26 = C, bit27 = P; subframe 1 occupies bits[28:56]."""
    hb0 = 0x02
    hb1 = (sample_present & 0xF) | ((layout & 1) << 4)
    hb2 = (sample_flat & 0xF) | ((b & 0xF) << 4)
    header = _header_word(hb0, hb1, hb2)

    subwords = []
    for k in range(4):
        if not (sample_present & (1 << k)):
            subwords.append(0)
            continue
        sub_a, sub_b = samples[k]
        frame = 0
        # subframe 0 (channel A): 24-bit sample, V/U/C/P = 0, then subframe 1.
        frame |= (sub_a & 0xFFFFFF)          # bits 0..23
        frame |= (sub_b & 0xFFFFFF) << 28    # bits 28..51
        pb = [(frame >> (8 * i)) & 0xFF for i in range(7)]
        corrupt = (corrupt_sub == k)
        subwords.append(_subpacket_word(pb, corrupt=corrupt))
    return header, subwords


def acr_packet(n, cts):
    """Build an Audio Clock Regeneration packet (type 0x01).

    All four subpackets carry the same CTS/N (HDMI redundancy). Subpacket byte
    layout: SB0=0, SB1[3:0]=CTS[19:16], SB2=CTS[15:8], SB3=CTS[7:0],
    SB4[3:0]=N[19:16], SB5=N[15:8], SB6=N[7:0]."""
    header = _header_word(0x01, 0x00, 0x00)
    pb = [
        0x00,
        (cts >> 16) & 0x0F,
        (cts >> 8) & 0xFF,
        cts & 0xFF,
        (n >> 16) & 0x0F,
        (n >> 8) & 0xFF,
        n & 0xFF,
    ]
    word = _subpacket_word(pb)
    return header, [word, word, word, word]


def audio_infoframe(cc=0x1, ct=0x0, sf=0x2, ss=0x1, ca=0x00):
    """Build an Audio InfoFrame packet (type 0x84).

    HB0=0x84, HB1=version(0x01), HB2=length(0x0A). Data bytes (subpacket 0):
      PB0 = checksum
      PB1[2:0]=CC, PB1[7:4]=CT
      PB2[1:0]=SS, PB2[4:2]=SF
      PB3 = 0
      PB4 = CA
      PB5..PB6 = 0
    Defaults describe 2-ch LPCM (CC=1 -> 2 channels), 48 kHz (SF=2), 24-bit
    (SS=? here 1), CA=0."""
    hb0, hb1, hb2 = 0x84, 0x01, 0x0A
    db1 = (cc & 0x7) | ((ct & 0xF) << 4)
    db2 = (ss & 0x3) | ((sf & 0x7) << 2)
    db3 = 0x00
    db4 = ca & 0xFF
    data = [db1, db2, db3, db4, 0x00, 0x00]   # PB1..PB6
    checksum = (- (hb0 + hb1 + hb2 + sum(data))) & 0xFF
    pb = [checksum] + data
    header = _header_word(hb0, hb1, hb2)
    return header, [_subpacket_word(pb), 0, 0, 0]


# --- serialisation into the TERC4 token stream ---------------------------
CTL0101 = control_tokens[1]          # ctl_code 0b0101 -> PREAM_T4
DGB = data_gb_tokens[0]              # data-island guardband
DUMMY = terc4_tokens[0]              # a TERC4 data char consumed on GOING_T4->TERC4


def _char_tokens(header, subwords, char):
    """Return the (raw0, raw1, raw2) tokens for one TERC4 char (0..31)."""
    n0 = ((header >> char) & 1) << 2          # channel-0 bit 2 = header bit
    n1 = 0
    n2 = 0
    for k in range(4):
        s = subwords[k]
        n1 |= ((s >> (2 * char)) & 1) << k
        n2 |= ((s >> (2 * char + 1)) & 1) << k
    return terc4_tokens[n0], terc4_tokens[n1], terc4_tokens[n2]


def packet_chars(header, subwords):
    """32 (raw0,raw1,raw2) tuples for one packet's TERC4 payload."""
    return [_char_tokens(header, subwords, c) for c in range(32)]


def island_stream(packets, lead_ctl=6, lead_dgb=2, trail_dgb=2, trail_ctl=6):
    """Serialise a list of ``(header, subwords)`` packets into one data island
    as a list of ``(raw0, raw1, raw2)`` tuples ready to feed data_in{0,1,2}.raw.

    Framing drives ``DecodeTERC4`` INIT -> PREAM_T4 -> GOING_T4 -> TERC4 ->
    LEAVE_T4 -> INIT. A single DUMMY char sits between the guardband and the
    first packet: it is the char consumed by the GOING_T4 -> TERC4 transition,
    so packet char 0 becomes the first char the FSM actually shifts."""
    stream = []
    ctl = (CTL0101, CTL0101, CTL0101)
    dgb = (DGB, DGB, DGB)
    dummy = (DUMMY, DUMMY, DUMMY)
    stream += [ctl] * lead_ctl
    stream += [dgb] * lead_dgb
    stream += [dummy]
    for header, subwords in packets:
        stream += packet_chars(header, subwords)
    stream += [dgb] * trail_dgb
    stream += [ctl] * trail_ctl
    return stream


# --- PCM helpers ----------------------------------------------------------
def sine_samples_24bit(n_samples, freq=1000.0, fs=48000.0, amplitude=0.5):
    """Generate ``n_samples`` of a sine as signed 24-bit two's-complement ints."""
    import math
    out = []
    full = (1 << 23) - 1
    for i in range(n_samples):
        v = amplitude * math.sin(2 * math.pi * freq * i / fs)
        q = round(v * full)
        out.append(q & 0xFFFFFF)   # 24-bit two's complement
    return out


def derived_sample_rate(pix_freq, n, cts):
    """fs = f_pixel * N / (128 * CTS) -- the HDMI ACR relation."""
    return pix_freq * n / (128.0 * cts)
