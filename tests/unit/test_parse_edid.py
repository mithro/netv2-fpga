from scripts.parse_edid import audio_descriptors, cta_blocks, has_basic_audio

# CTA-861 extension header with basic audio bit, one Audio Data Block (LPCM 2ch 32/44.1/48k, 16/20/24 bit)
CTA = bytes([0x02, 0x03, 0x21, 0xF1, 0x23, 0x09, 0x07, 0x07]) + bytes(128 - 8)


def test_basic_audio_flag():
    assert has_basic_audio(CTA) is True


def test_audio_descriptor_decoded():
    (desc,) = audio_descriptors(CTA)
    assert desc["format"] == "LPCM"
    assert desc["channels"] == 2
    assert desc["rates_khz"] == [32, 44.1, 48]


def test_no_audio_when_flag_clear():
    blk = bytearray(CTA)
    blk[3] = 0xB1  # 0xF1 with bit 6 (basic audio) cleared
    assert has_basic_audio(bytes(blk)) is False


def test_cta_blocks_selects_extension_blocks():
    edid = bytes(128) + CTA
    assert cta_blocks(edid) == [CTA]
