"""Unit tests for the host-side HDCP receiver control tool.

All hardware and serial access is faked with ``MockConsole`` -- no serial port
is opened and no pyserial call happens.  Key material in these tests is a
synthetic in-test blob; the real ``~/netv2-hdcp-handoff/keys/`` are never
touched, so no real key bytes reach the test or its captured output.

The tool file is not an importable package, so it is loaded by path.
"""

import importlib.util
import io
import json
import os

import pytest

_CTL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "software", "hdcp", "netv2_hdcp_ctl.py",
)
_spec = importlib.util.spec_from_file_location("netv2_hdcp_ctl", _CTL_PATH)
ctl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ctl)

_CSR_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "legacy", "build", "hdcprx-35", "csr.csv",
)


# --------------------------------------------------------------------------
# csr.csv parsing
# --------------------------------------------------------------------------
def test_csv_parse_expected_addresses_and_sizes():
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    # (address, sub-word count) as they appear in the shipped map.
    expected = {
        "hdcprx_bksv": (0xE000E800, 5),
        "hdcprx_key_index": (0xE000E814, 1),
        "hdcprx_key_data_lo": (0xE000E818, 4),
        "hdcprx_key_data_hi": (0xE000E828, 3),
        "hdcprx_key_we": (0xE000E834, 1),
        "hdcprx_keys_clear": (0xE000E838, 1),
        "hdcprx_keys_loaded": (0xE000E83C, 1),
        "hdcprx_rx_enable": (0xE000E840, 1),
        "hdcprx_km_source": (0xE000E844, 1),
        "hdcprx_r0": (0xE000E848, 2),
        "hdcprx_ri": (0xE000E850, 2),
        "hdcprx_aksv": (0xE000E858, 5),
        "hdcprx_an": (0xE000E86C, 8),
        "hdcprx_ainfo": (0xE000E88C, 1),
        "hdcprx_km_hw": (0xE000E890, 7),
        "hdcprx_status": (0xE000E8AC, 1),
    }
    for name, (addr, nwords) in expected.items():
        assert csrmap.addr(name) == addr, name
        assert csrmap.nwords(name) == nwords, name


def test_busword_is_eight():
    # The byte-wide CSR bus is what makes bksv (40b) a 5-word register.
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    assert csrmap.busword == 8
    assert csrmap.nwords("hdcprx_bksv") * csrmap.busword == 40


# --------------------------------------------------------------------------
# multi-word read/write, MSW-first
# --------------------------------------------------------------------------
def test_bksv_40bit_roundtrip_msw_first():
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    mock = ctl.MockConsole()
    value = 0x123456789A  # 40-bit
    csrmap.write(mock, "hdcprx_bksv", value)

    base = csrmap.addr("hdcprx_bksv")
    # 5 byte-words, MSW first at consecutive +4 addresses.
    assert mock.mem[base + 0] == 0x12
    assert mock.mem[base + 4] == 0x34
    assert mock.mem[base + 8] == 0x56
    assert mock.mem[base + 12] == 0x78
    assert mock.mem[base + 16] == 0x9A
    assert csrmap.read(mock, "hdcprx_bksv") == value


def test_an_64bit_roundtrip():
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    mock = ctl.MockConsole()
    value = 0x0123456789ABCDEF  # 64-bit
    # hdcprx_an is read-only on hardware; the CSR layer split/assemble logic is
    # transport-agnostic, so a round trip through the mock validates ordering.
    csrmap.write(mock, "hdcprx_an", value)
    base = csrmap.addr("hdcprx_an")
    assert mock.mem[base + 0] == 0x01  # MSW first
    assert mock.mem[base + 28] == 0xEF  # LSW last (8 words * 4B stride)
    assert csrmap.read(mock, "hdcprx_an") == value


def test_read_masks_to_busword():
    # mr returns a full 32-bit word; only the low busword bits are the CSR.
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    base = csrmap.addr("hdcprx_aksv")
    junk = {base + 4 * i: 0xFFFFFF00 for i in range(5)}
    junk[base + 0] |= 0xAB
    junk[base + 4] |= 0xCD
    junk[base + 8] |= 0xEF
    junk[base + 12] |= 0x01
    junk[base + 16] |= 0x23
    mock = ctl.MockConsole(junk)
    assert csrmap.read(mock, "hdcprx_aksv") == 0xABCDEF0123


# --------------------------------------------------------------------------
# load-keys
# --------------------------------------------------------------------------
def _write_synthetic_keys(tmp_path):
    """A synthetic 40x7-byte key blob + manifest (NOT real key material)."""
    keys_path = os.path.join(str(tmp_path), "sink_keys.bin")
    blob = bytearray()
    for i in range(ctl.N_KEYS):
        # Distinct 7-byte little-endian pattern per index.
        blob += bytes(bytearray([(i + 1) & 0xFF, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66]))
    with open(keys_path, "wb") as f:
        f.write(bytes(blob))

    manifest_path = os.path.join(str(tmp_path), "manifest.json")
    ksv_sink = 0x55AA55AA55
    with open(manifest_path, "w") as f:
        json.dump({"ksv_sink": f"{ksv_sink:010x}"}, f)
    return keys_path, manifest_path, ksv_sink, blob


def test_load_keys_writes_words_and_pulses_we(tmp_path):
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    keys_path, manifest_path, ksv_sink, _blob = _write_synthetic_keys(tmp_path)

    loaded_addr = csrmap.addr("hdcprx_keys_loaded")
    mock = ctl.MockConsole({loaded_addr: 40})  # hardware reports 40 loaded

    out = io.StringIO()
    result = ctl.cmd_load_keys(mock, csrmap, keys_path, manifest_path, out=out)
    assert result == 40

    we_addr = csrmap.addr("hdcprx_key_we")
    idx_addr = csrmap.addr("hdcprx_key_index")
    we_pulses = [a for (a, _v) in mock.writes if a == we_addr]
    idx_writes = [(a, v) for (a, v) in mock.writes if a == idx_addr]
    assert len(we_pulses) == ctl.N_KEYS
    assert [v for (_a, v) in idx_writes] == list(range(ctl.N_KEYS))

    lo_addr = csrmap.addr("hdcprx_key_data_lo")
    # After the loop the mock retains the LAST write per address; assert the
    # last index (39) key: byte0 = 40 (0x28).
    assert mock.mem[lo_addr + 12] == 0x28  # LSW of key_data_lo for index 39
    assert csrmap.read(mock, "hdcprx_bksv") == ksv_sink


def test_load_keys_never_prints_key_bytes(tmp_path):
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    keys_path, manifest_path, _ksv, _blob = _write_synthetic_keys(tmp_path)
    loaded_addr = csrmap.addr("hdcprx_keys_loaded")
    mock = ctl.MockConsole({loaded_addr: 40})

    out = io.StringIO()
    ctl.cmd_load_keys(mock, csrmap, keys_path, manifest_path, out=out)
    text = out.getvalue()

    # No raw key byte sequence and no hex of any key value appears in output.
    keys = ctl.load_keys_bin(keys_path)
    for key in keys:
        assert f"{key:014x}" not in text.lower()
    # The distinctive shared tail bytes of every synthetic key must be absent.
    assert "66554433" not in text.lower()


def test_load_keys_raises_when_count_wrong(tmp_path):
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    keys_path, manifest_path, _ksv, _blob = _write_synthetic_keys(tmp_path)
    mock = ctl.MockConsole()  # keys_loaded reads back 0
    out = io.StringIO()
    with pytest.raises(RuntimeError):
        ctl.cmd_load_keys(mock, csrmap, keys_path, manifest_path, out=out)


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
def test_status_surfaces_received_aksv_as_a_actual():
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    aksv_addr = csrmap.addr("hdcprx_aksv")
    aksv_value = 0xDEADBEEF12
    mem = {}
    for i in range(5):
        shift = (5 - i - 1) * 8
        mem[aksv_addr + 4 * i] = (aksv_value >> shift) & 0xFF
    mock = ctl.MockConsole(mem)

    out = io.StringIO()
    ctl.cmd_status(mock, csrmap, show_km=False, out=out)
    text = out.getvalue()
    assert "A_actual" in text
    assert "received Aksv" in text
    assert "deadbeef12" in text.lower()


def test_status_gates_km_hw_behind_show_km():
    csrmap = ctl.CsrMap.from_csv(_CSR_CSV)
    km_addr = csrmap.addr("hdcprx_km_hw")
    km_value = 0xAABBCCDDEEFF00  # 56-bit secret
    mem = {}
    for i in range(7):
        shift = (7 - i - 1) * 8
        mem[km_addr + 4 * i] = (km_value >> shift) & 0xFF
    mock = ctl.MockConsole(mem)

    hidden = io.StringIO()
    ctl.cmd_status(mock, csrmap, show_km=False, out=hidden)
    assert "aabbccddeeff00" not in hidden.getvalue().lower()
    assert "hidden" in hidden.getvalue().lower()

    shown = io.StringIO()
    ctl.cmd_status(mock, csrmap, show_km=True, out=shown)
    assert "aabbccddeeff00" in shown.getvalue().lower()


def test_decode_status_bits():
    # rx_armed | keys_ok | km_valid | r0_valid | sda_driving
    bits = dict(ctl.decode_status(0b10101))
    assert bits["rx_armed"] == 1
    assert bits["keys_ok"] == 0
    assert bits["km_valid"] == 1
    assert bits["r0_valid"] == 0
    assert bits["sda_driving"] == 1
