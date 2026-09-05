"""Test hosts and the golden-unit rules (spec decisions 6, 8, 10, 35).

Every script that touches hardware must call ``check_action_allowed`` before a
destructive step. The golden unit rpi3-netv2 only ever receives volatile JTAG
loads and console traffic.
"""
from dataclasses import dataclass


class GoldenUnitError(RuntimeError):
    """Raised when an action is forbidden on the golden reference unit."""


@dataclass(frozen=True)
class Host:
    name: str
    fqdn: str
    user: str
    fpga: str
    idcode: int
    golden: bool
    uart: str
    hdmi_variant: str          # "pcb" (M2M jumper) or "cable"
    has_capture: bool
    has_pcie: bool
    openocd_cfg: str


HOSTS = {
    "rpi3-netv2": Host(
        name="rpi3-netv2",
        fqdn="rpi3-netv2.iot.welland.mithis.com",
        user="pi",
        fpga="xc7a35t-fgg484-2",
        idcode=0x0362D093,
        golden=True,
        uart="/dev/ttyS0",
        hdmi_variant="pcb",
        has_capture=True,
        has_pcie=False,
        openocd_cfg="/home/pi/code/netv2mvp-scripts/alphamax-rpi.cfg",
    ),
    "rpi5-netv2": Host(
        name="rpi5-netv2",
        fqdn="rpi5-netv2.iot.welland.mithis.com",
        user="tim",
        fpga="xc7a100t-fgg484-2",
        idcode=0x13631093,
        golden=False,
        uart="/dev/ttyAMA0",
        hdmi_variant="cable",
        has_capture=False,
        has_pcie=True,
        openocd_cfg="/home/tim/netv2/netv2-rpi5.cfg",
    ),
}

FORBIDDEN_ON_GOLDEN = {"spi_flash_write", "power_cycle", "reboot", "reimage"}
KNOWN_ACTIONS = FORBIDDEN_ON_GOLDEN | {"jtag_volatile_load", "console", "run_suite"}


def check_action_allowed(host_name: str, action: str) -> None:
    host = HOSTS[host_name]  # KeyError for unknown hosts is intended
    if action not in KNOWN_ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if host.golden and action in FORBIDDEN_ON_GOLDEN:
        raise GoldenUnitError(f"{action} is forbidden on golden unit {host_name}")
