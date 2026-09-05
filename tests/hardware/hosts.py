"""Test hosts and the golden-unit rules (spec decisions 6, 8, 10, 35).

Status: **advisory**. Nothing calls this module yet -- the phase 1 baseline steps
are manual ``ssh`` commands and this table is what a reviewer checks them
against. It becomes enforcing when the hardware scripts of later phases route
their destructive steps through :func:`check_action_allowed`.

Fail closed
-----------
Both the host set and the action set are allowlists, never deny-lists:

* :func:`resolve_host` accepts a host's short name, its fqdn or one of its
  registered ``aliases``; every other spelling raises :class:`KeyError`. A typo
  or an unregistered host therefore refuses to run rather than being treated as
  an unrestricted machine.
* :data:`ALLOWED_ON_GOLDEN` lists the only actions the golden unit may ever
  receive. Anything else in :data:`KNOWN_ACTIONS` is refused there, so a new
  destructive action added to ``KNOWN_ACTIONS`` in the future is forbidden on
  the golden unit by default instead of silently permitted. An action outside
  ``KNOWN_ACTIONS`` altogether is a :class:`ValueError` on every host.

The golden unit
---------------
``rpi3-netv2`` is the untouched 2018 reference unit: stock 2019 SPI flash,
stock rootfs. It may only receive volatile JTAG loads (including the reload of
the stock bitstream that ends every run), firmware serial boot, console traffic
that passes :func:`check_repl_command_allowed`, restarts of the user-session
services the suite itself pauses (``pm2 mm``, ``lightdm``), and runs of the
imported test suite. ``run_suite`` is the widest grant in the set: the suite
pauses and restores those services and writes volatile CSRs over the console.
Never SPI flash writes or erases, never a reboot, never JTAG SRST, never a
power cycle, re-imaging, USB reset, or a write to the reference rootfs.

Console commands on the golden unit
-----------------------------------
``console_command`` is the action for sending a REPL line. On the golden unit
it is allowed only together with the line itself, so
:func:`check_action_allowed` requires ``command_line`` for that action and runs
:func:`check_repl_command_allowed` on it. The 2019 firmware REPL
(``legacy/firmware/ci.c`` lines 800 to 803) exposes ``reboot`` (jumps back to
the BIOS, losing the running configuration), ``mw`` (arbitrary 32-bit write
anywhere in the address map) and ``mc`` (memory copy). None of them may ever be
sent to a golden host. The firmware dispatches on the first token of *each
line* (``readstr`` returns on every CR or LF), so a command line containing a
CR or LF is refused outright rather than inspected token by token. The check
is case-insensitive as defence in depth even though the firmware's ``strcmp``
would not execute an upper-case spelling.

IDCODE revision nibble
----------------------
Bits 31:28 of a Xilinx JTAG IDCODE are the silicon revision, not part of the
part identity: the XC7A100T on ``rpi5-netv2`` reads ``0x13631093`` (revision 1)
where the nominal value is ``0x03631093``. :attr:`Host.idcode` therefore stores
the nominal value and comparisons must go through :meth:`Host.idcode_matches`,
which masks the top nibble off both sides. Masking matters: XC7A50T is
``0x0362C093``, one nibble away from the XC7A35T's ``0x0362D093``, so the
remaining 28 bits must still be compared exactly.
"""
from dataclasses import dataclass

PART_ID_MASK = 0x0FFFFFFF


class GoldenUnitError(RuntimeError):
    """Raised when an action is forbidden on the golden reference unit."""


@dataclass(frozen=True)
class Host:
    name: str
    fqdn: str
    user: str
    fpga: str
    idcode: int                # nominal IDCODE, revision nibble (bits 31:28) zero
    golden: bool
    uart: str
    hdmi_variant: str          # "pcb" (M2M jumper) or "cable"
    has_capture: bool
    has_pcie: bool
    openocd_cfg: str
    aliases: tuple[str, ...] = ()

    @property
    def part_id(self) -> int:
        """The IDCODE with the silicon-revision nibble masked off."""
        return self.idcode & PART_ID_MASK

    def idcode_matches(self, observed: int) -> bool:
        """True if an observed IDCODE is this part, at any silicon revision."""
        return (observed & PART_ID_MASK) == self.part_id


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
        aliases=(
            "rpi3-netv2.welland.mithis.com",
            "pi@rpi3-netv2.iot.welland.mithis.com",
            "pi@rpi3-netv2.welland.mithis.com",
        ),
    ),
    "rpi5-netv2": Host(
        name="rpi5-netv2",
        fqdn="rpi5-netv2.iot.welland.mithis.com",
        user="tim",
        fpga="xc7a100t-fgg484-2",
        idcode=0x03631093,
        golden=False,
        uart="/dev/ttyAMA0",
        hdmi_variant="cable",
        has_capture=False,
        has_pcie=True,
        openocd_cfg="/home/tim/netv2/netv2-rpi5.cfg",
        aliases=(
            "rpi5-netv2.welland.mithis.com",
            "tim@rpi5-netv2.iot.welland.mithis.com",
            "tim@rpi5-netv2.welland.mithis.com",
        ),
    ),
}

# The only actions the golden unit may ever receive. "console_command" is
# allowed only with its command line, see check_action_allowed.
ALLOWED_ON_GOLDEN = frozenset({
    "jtag_volatile_load",
    "restore_stock_bitstream",
    "firmware_serial_boot",
    "console_read",
    "console_command",
    "service_restart",
    "run_suite",
})

# Every action a hardware script may ask about. Anything outside this set is a
# programming error (ValueError); anything inside it but outside
# ALLOWED_ON_GOLDEN is refused on the golden unit.
KNOWN_ACTIONS = ALLOWED_ON_GOLDEN | frozenset({
    "spi_flash_write",
    "spi_flash_erase",
    "jtag_srst",
    "reboot",
    "power_cycle",
    "reimage",
    "rootfs_write",
    "usb_reset",
    "pcie_rebind",
})

# 2019 firmware REPL commands that must never reach a golden host
# (legacy/firmware/ci.c lines 800 to 803: reboot, mr, mw, mc; mr is a read).
GOLDEN_FORBIDDEN_REPL_COMMANDS = frozenset({"reboot", "mw", "mc"})


def resolve_host(spec: str) -> Host:
    """Resolve a short name, fqdn or registered alias to a :class:`Host`.

    Fails closed: an unregistered spelling raises ``KeyError`` rather than
    being treated as an unknown (and therefore unrestricted) machine.
    """
    for host in HOSTS.values():
        if spec == host.name or spec == host.fqdn or spec in host.aliases:
            return host
    raise KeyError(f"unknown host {spec!r}")


def check_action_allowed(host_spec: str, action: str, command_line: str | None = None) -> None:
    """Raise unless ``action`` may be performed on ``host_spec``.

    For ``console_command`` the REPL line must be supplied; on a golden host it
    is then checked with :func:`check_repl_command_allowed`.
    """
    host = resolve_host(host_spec)  # KeyError for unknown hosts is intended
    if action not in KNOWN_ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if action == "console_command":
        if command_line is None:
            raise ValueError("console_command requires command_line")
        check_repl_command_allowed(host_spec, command_line)
    if host.golden and action not in ALLOWED_ON_GOLDEN:
        raise GoldenUnitError(f"{action} is forbidden on golden unit {host.name}")


def check_repl_command_allowed(host_spec: str, command_line: str) -> None:
    """Raise if a firmware REPL command line is forbidden on ``host_spec``.

    A line containing CR or LF is refused on a golden host because the firmware
    would execute every embedded line. Otherwise the first whitespace-separated
    token, case-folded, is compared with :data:`GOLDEN_FORBIDDEN_REPL_COMMANDS`.
    """
    host = resolve_host(host_spec)
    if not host.golden:
        return
    if "\r" in command_line or "\n" in command_line:
        raise GoldenUnitError(
            f"multi-line REPL input is forbidden on golden unit {host.name}: {command_line!r}"
        )
    tokens = command_line.split()
    if tokens and tokens[0].casefold() in GOLDEN_FORBIDDEN_REPL_COMMANDS:
        raise GoldenUnitError(
            f"REPL command {tokens[0]!r} is forbidden on golden unit {host.name}"
        )
