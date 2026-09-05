"""Unit tests for the trixie NeTV2 update tool (``software/pi/netv2_update.py``).

No hardware and no real OpenOCD: a fake runner captures the argv the tool would
run and returns canned output. These tests cover the three things that keep the
tool safe -- IDCODE parsing/identification, the golden-unit flash refusal, and
the volatile-vs-flash decision (including the confirmation gate).
"""
import subprocess

import pytest

from software.pi import netv2_update as nu
from tests.hardware.hosts import GoldenUnitError

# Real OpenOCD scan_chain output captured from rpi5-netv2 (100T, revision 1).
IDCODE_100T = (
    "adapter speed: 1000 kHz\n"
    "Info : Linux GPIOD JTAG/SWD bitbang driver\n"
    "Info : JTAG tap: xc7.tap tap/device found: 0x13631093 "
    "(mfg: 0x049 (Xilinx), part: 0x3631, ver: 0x1)\n"
)
IDCODE_35T = "Info : JTAG tap: xc7.tap tap/device found: 0x0362d093 (mfg: 0x049 (Xilinx))\n"


class FakeRunner:
    """Records every argv and returns a scripted (returncode, stdout)."""

    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), self.returncode, stdout=self.stdout)

    @property
    def last_tcl(self):
        """The TCL passed to the last invocation's trailing ``-c`` argument."""
        argv = self.calls[-1]
        return argv[argv.index("-c") + 1]


def make_prog(runner, **kw):
    return nu.Programmer("iface.cfg", xc7_cfg="xc7.cfg", jtagspi_cfg="jtagspi.cfg",
                         runner=runner, **kw)


# --- IDCODE parsing -------------------------------------------------------

def test_parse_idcode_100t():
    assert nu.parse_idcode(IDCODE_100T) == 0x13631093


def test_parse_idcode_35t_lowercase():
    assert nu.parse_idcode(IDCODE_35T) == 0x0362D093


def test_parse_idcode_missing_raises():
    with pytest.raises(nu.OpenOCDError):
        nu.parse_idcode("no tap here\nInfo : all zeros 0x00000000\n")


def test_identify_100t_masks_revision_nibble():
    # 0x13631093 (rev 1) must identify as the 100T whose nominal is 0x03631093.
    part = nu.identify_part(0x13631093)
    assert part.name == "100T"
    assert part.bscan == "bscan_spi_xc7a100t.bit"
    assert nu.identify_part(0x03631093).name == "100T"


def test_identify_35t():
    assert nu.identify_part(0x0362D093).name == "35T"


def test_identify_rejects_neighbouring_50t():
    # XC7A50T (0x0362C093) is one nibble from the 35T and must NOT be accepted.
    with pytest.raises(nu.UnknownIDCODEError):
        nu.identify_part(0x0362C093)


def test_identify_rejects_garbage():
    for bad in (0x00000000, 0xFFFFFFFF, 0x12345678):
        with pytest.raises(nu.UnknownIDCODEError):
            nu.identify_part(bad)


# --- read_idcode / identify through the runner ----------------------------

def test_read_idcode_uses_scan_chain():
    r = FakeRunner(stdout=IDCODE_100T)
    prog = make_prog(r)
    assert prog.read_idcode() == 0x13631093
    assert "scan_chain" in r.last_tcl
    # sudo openocd -f iface -f xc7 ... by default
    assert r.calls[-1][0] == "sudo"
    assert "iface.cfg" in r.calls[-1]
    assert "xc7.cfg" in r.calls[-1]


def test_no_sudo_option_drops_sudo():
    r = FakeRunner(stdout=IDCODE_100T)
    prog = make_prog(r, use_sudo=False)
    prog.read_idcode()
    assert r.calls[-1][0] != "sudo"


def test_openocd_nonzero_raises():
    r = FakeRunner(stdout="boom", returncode=1)
    with pytest.raises(nu.OpenOCDError):
        make_prog(r).read_idcode()


# --- volatile load: the safe path -----------------------------------------

def test_volatile_load_verifies_idcode_and_uses_pld_load(tmp_path):
    bit = tmp_path / "netv2-base.bit"
    bit.write_bytes(b"\x00")
    r = FakeRunner(stdout=IDCODE_100T)
    part = make_prog(r).volatile_load(str(bit))
    assert part.name == "100T"
    # last call is the load; it must use pld load and NOT touch jtagspi/flash.
    tcl = r.last_tcl
    assert "pld load 0" in tcl
    assert "jtagspi" not in tcl
    assert "flash" not in tcl


def test_volatile_load_missing_bitfile_raises():
    r = FakeRunner(stdout=IDCODE_100T)
    with pytest.raises(FileNotFoundError):
        make_prog(r).volatile_load("/no/such/file.bit")


def test_volatile_load_refuses_unknown_part(tmp_path):
    bit = tmp_path / "x.bit"
    bit.write_bytes(b"\x00")
    r = FakeRunner(stdout="tap/device found: 0x12345678\n")
    with pytest.raises(nu.UnknownIDCODEError):
        make_prog(r).volatile_load(str(bit))


# --- flash: the guarded path ----------------------------------------------

def test_flash_refused_on_golden_unit_before_anything(tmp_path):
    """The golden-unit guard must fire first -- even with the go-ahead flag and
    a valid image, rpi3-netv2 is refused and OpenOCD is never invoked."""
    img = tmp_path / "img.bin"
    img.write_bytes(b"\x00" * 8)
    r = FakeRunner(stdout=IDCODE_35T)
    with pytest.raises(GoldenUnitError):
        make_prog(r).flash_write("rpi3-netv2", str(img), confirmed=True)
    assert r.calls == []  # nothing ran


def test_flash_requires_confirmation_on_nongolden(tmp_path):
    img = tmp_path / "img.bin"
    img.write_bytes(b"\x00" * 8)
    r = FakeRunner(stdout=IDCODE_100T)
    with pytest.raises(nu.NotConfirmedError):
        make_prog(r).flash_write("rpi5-netv2", str(img), confirmed=False)
    assert r.calls == []  # refused before any OpenOCD run


def test_flash_write_confirmed_on_nongolden_runs_jtagspi(tmp_path):
    img = tmp_path / "img.bin"
    img.write_bytes(b"\x00" * 8)
    r = FakeRunner(stdout=IDCODE_100T)
    part = make_prog(r).flash_write("rpi5-netv2", str(img), offset=0, confirmed=True)
    assert part.name == "100T"
    tcl = r.last_tcl
    assert "jtagspi_init 0 bscan_spi_xc7a100t.bit" in tcl
    assert "jtagspi_program" in tcl
    # jtagspi.cfg must be sourced for the flash path.
    assert "jtagspi.cfg" in r.calls[-1]


def test_flash_unknown_host_is_refused(tmp_path):
    img = tmp_path / "img.bin"
    img.write_bytes(b"\x00" * 8)
    r = FakeRunner(stdout=IDCODE_100T)
    # resolve_host raises KeyError for an unregistered host (fail closed).
    with pytest.raises(KeyError):
        make_prog(r).flash_write("some-random-box", str(img), confirmed=True)
    assert r.calls == []


def test_guard_failure_fails_closed(tmp_path, monkeypatch):
    """If the guard cannot be imported, flash must refuse (fail closed)."""
    img = tmp_path / "img.bin"
    img.write_bytes(b"\x00" * 8)
    r = FakeRunner(stdout=IDCODE_100T)
    prog = make_prog(r)

    def broken_guard(*_a, **_k):
        raise nu.GuardUnavailableError("simulated missing guard")

    prog._guard = broken_guard
    with pytest.raises(nu.GuardUnavailableError):
        prog.flash_write("rpi5-netv2", str(img), confirmed=True)
    assert r.calls == []


# --- CLI wiring -----------------------------------------------------------

def test_cli_flash_flag_name_is_the_go_ahead():
    """The confirmation flag the task requires must exist and set `confirmed`."""
    parser = nu.build_parser()
    args = parser.parse_args(
        ["flash", "img.bin", "--host", "rpi5-netv2", nu.CONFIRM_FLAG]
    )
    assert args.confirmed is True
    assert nu.CONFIRM_FLAG == "--i-have-tim-go-ahead"


def test_cli_flash_defaults_to_unconfirmed():
    args = nu.build_parser().parse_args(["flash", "img.bin", "--host", "rpi5-netv2"])
    assert args.confirmed is False
