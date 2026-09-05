import pytest

from tests.hardware.hosts import HOSTS, GoldenUnitError, check_action_allowed


def test_rpi3_is_golden_and_35t():
    h = HOSTS["rpi3-netv2"]
    assert h.golden is True
    assert h.idcode == 0x0362D093
    assert h.user == "pi"


def test_flash_write_refused_on_golden():
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "spi_flash_write")


def test_power_cycle_refused_on_golden():
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "power_cycle")


def test_volatile_load_allowed_on_golden():
    check_action_allowed("rpi3-netv2", "jtag_volatile_load")


def test_everything_allowed_on_rpi5():
    for a in ("spi_flash_write", "power_cycle", "jtag_volatile_load", "reboot"):
        check_action_allowed("rpi5-netv2", a)


def test_unknown_host_rejected():
    with pytest.raises(KeyError):
        check_action_allowed("nope", "reboot")
