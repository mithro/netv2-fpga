import pytest

from tests.hardware import hosts
from tests.hardware.hosts import (
    ALLOWED_ON_GOLDEN,
    HOSTS,
    KNOWN_ACTIONS,
    GoldenUnitError,
    check_action_allowed,
    check_repl_command_allowed,
    resolve_host,
)


def test_rpi3_is_golden_and_35t():
    h = HOSTS["rpi3-netv2"]
    assert h.golden is True
    assert h.idcode == 0x0362D093
    assert h.part_id == 0x0362D093
    # The top nibble is the silicon revision and must not affect identification.
    assert h.idcode_matches(0x1362D093) is True
    # XC7A50T is one nibble away from the 35T; the other 28 bits must still match.
    assert h.idcode_matches(0x0362C093) is False
    assert h.user == "pi"


def test_flash_write_refused_on_golden():
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "spi_flash_write")


def test_power_cycle_refused_on_golden():
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "power_cycle")


def test_reimage_refused_on_golden():
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "reimage")


def test_every_non_allowlisted_action_refused_on_golden():
    """Anything registered but not on the golden allowlist must be refused."""
    for action in sorted(KNOWN_ACTIONS - ALLOWED_ON_GOLDEN):
        with pytest.raises(GoldenUnitError):
            check_action_allowed("rpi3-netv2", action)
    assert {"pcie_rebind", "jtag_srst", "usb_reset", "rootfs_write",
            "spi_flash_erase", "reboot"} <= KNOWN_ACTIONS - ALLOWED_ON_GOLDEN


def test_future_action_is_refused_on_golden_by_default(monkeypatch):
    monkeypatch.setattr(hosts, "KNOWN_ACTIONS", hosts.KNOWN_ACTIONS | {"laser"})
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "laser")
    check_action_allowed("rpi5-netv2", "laser")


def test_volatile_load_allowed_on_golden():
    check_action_allowed("rpi3-netv2", "jtag_volatile_load")


def test_non_destructive_actions_allowed_on_golden():
    for action in ("firmware_serial_boot", "console_read", "run_suite",
                   "restore_stock_bitstream", "service_restart"):
        check_action_allowed("rpi3-netv2", action)


def test_console_command_requires_and_checks_the_line():
    with pytest.raises(ValueError):
        check_action_allowed("rpi3-netv2", "console_command")
    check_action_allowed("rpi3-netv2", "console_command", command_line="debug t4d")
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "console_command", command_line="reboot")
    check_action_allowed("rpi5-netv2", "console_command", command_line="reboot")


def test_everything_allowed_on_rpi5():
    for a in ("spi_flash_write", "power_cycle", "jtag_volatile_load", "reboot"):
        check_action_allowed("rpi5-netv2", a)


def test_rpi5_is_not_golden_and_is_a_100t():
    h = HOSTS["rpi5-netv2"]
    assert h.golden is False
    assert h.idcode == 0x03631093
    # As observed on the wire: revision 1 silicon.
    assert h.idcode_matches(0x13631093) is True
    assert h.idcode_matches(0x0362D093) is False


def test_unknown_action_raises_value_error_on_both_hosts():
    for host in ("rpi3-netv2", "rpi5-netv2"):
        with pytest.raises(ValueError):
            check_action_allowed(host, "frobnicate")


def test_unknown_host_rejected():
    with pytest.raises(KeyError):
        check_action_allowed("nope", "reboot")


def test_resolve_host_accepts_registered_spellings():
    for spec in ("rpi3-netv2",
                 "rpi3-netv2.iot.welland.mithis.com",
                 "rpi3-netv2.welland.mithis.com",
                 "pi@rpi3-netv2.iot.welland.mithis.com",
                 "pi@rpi3-netv2.welland.mithis.com"):
        assert resolve_host(spec).name == "rpi3-netv2"
    for spec in ("rpi5-netv2",
                 "rpi5-netv2.iot.welland.mithis.com",
                 "rpi5-netv2.welland.mithis.com",
                 "tim@rpi5-netv2.iot.welland.mithis.com",
                 "tim@rpi5-netv2.welland.mithis.com"):
        assert resolve_host(spec).name == "rpi5-netv2"


def test_resolve_host_fails_closed_on_unregistered_spelling():
    with pytest.raises(KeyError):
        resolve_host("rpi3-netv2.example.com")


def test_forbidden_repl_commands_refused_on_golden():
    with pytest.raises(GoldenUnitError):
        check_repl_command_allowed("rpi3-netv2", "reboot")
    with pytest.raises(GoldenUnitError):
        check_repl_command_allowed("rpi3-netv2", "mw 0x20000000 0")
    with pytest.raises(GoldenUnitError):
        check_repl_command_allowed("rpi3-netv2", "mc 0x20000000 0x20001000 16")


def test_harmless_repl_commands_and_non_golden_hosts_pass():
    check_repl_command_allowed("rpi3-netv2", "status")
    check_repl_command_allowed("rpi3-netv2", "")
    check_repl_command_allowed("rpi3-netv2", "mr 0x20000000 4")  # a read
    check_repl_command_allowed("rpi5-netv2", "reboot")


def test_multi_line_repl_input_refused_on_golden():
    """The firmware executes every embedded line, so CR/LF is refused outright."""
    for line in ("status\nreboot", "status\r\nreboot", "json off\nreboot", "status\n"):
        with pytest.raises(GoldenUnitError):
            check_repl_command_allowed("rpi3-netv2", line)


def test_repl_check_is_case_insensitive_and_ignores_leading_space():
    for line in ("REBOOT", "Reboot", "MW 0 0", "  reboot", "\treboot"):
        with pytest.raises(GoldenUnitError):
            check_repl_command_allowed("rpi3-netv2", line)


def test_repl_check_unknown_host_raises():
    with pytest.raises(KeyError):
        check_repl_command_allowed("nope", "status")


def test_idcode_revision_nibble_sweep():
    h35, h100 = HOSTS["rpi3-netv2"], HOSTS["rpi5-netv2"]
    for rev in range(16):
        assert h35.idcode_matches((rev << 28) | 0x0362D093)
        assert h100.idcode_matches((rev << 28) | 0x03631093)
        assert not h35.idcode_matches((rev << 28) | 0x03631093)
        assert not h100.idcode_matches((rev << 28) | 0x0362D093)
        assert not h35.idcode_matches((rev << 28) | 0x0362C093)  # XC7A50T
