#!/usr/bin/env python3
"""NeTV2 FPGA update tool for Raspberry Pi OS "trixie" (Debian 13).

This replaces the 2019 ``update-fpga.sh`` one-click updater. It runs on the
modern stack (Python 3.9+, OpenOCD 0.12 with the ``linuxgpiod`` driver, Pi
3B+/4/5) instead of Raspbian 9 / OpenOCD 0.10 / ``bcm2835gpio``.

Three operations, mirroring the original safety model:

* ``idcode`` -- read the FPGA JTAG IDCODE and identify the part. The original
  gated every update on the IDCODE (``0x0362D093`` = XC7A35T, ``0x13631093`` =
  XC7A100T); we keep that gate. The silicon-revision nibble (bits 31:28) is
  masked before comparison, exactly like ``tests/hardware/hosts.py``.

* ``load`` -- **volatile** bitstream load into FPGA configuration SRAM via
  ``pld load``. Power-cycle-reversible; writes nothing to flash. This is the
  only operation used against hardware during phase 4.

* ``flash`` -- **persistent** SPI-NOR write via the ``bscan_spi`` JTAG-to-SPI
  proxy. This path is DANGEROUS and is fenced three ways:
    1. it calls the golden-unit guard
       (``tests.hardware.hosts.check_action_allowed``) and refuses
       ``spi_flash_write`` on the golden reference unit ``rpi3-netv2``;
    2. it refuses to run unless the explicit ``--i-have-tim-go-ahead`` flag is
       present;
    3. it fails closed if the guard module cannot be imported.

Image format note (LiteSPI vs mknetv2img)
------------------------------------------
The 2019 flow padded ``user-firmware.bin`` and wrapped it with
``bin/mknetv2img -f`` (a byte-swap + CRC framing step) before burning. The
modern LiteX/**LiteSPI** flow supersedes that: the LiteX build already emits a
flash-ready image (``kosagi_netv2.bin`` gateware, plus the SoC firmware in the
image layout LiteSPI expects), so **no mknetv2img byte-swap is applied here**.
``flash`` writes the raw ``.bin`` at the requested offset. See
``docs/current/pi-software-trixie.md``.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# The revision nibble (bits 31:28) is silicon revision, not part identity.
PART_ID_MASK = 0x0FFFFFFF

CONFIRM_FLAG = "--i-have-tim-go-ahead"

# Candidate locations of the Xilinx Series-7 PLD/TAP definition. OpenOCD 0.12
# on trixie ships it at fpga/xlnx/xc7.cfg; older/other layouts used
# cpld/xilinx-xc7.cfg. jtagspi.cfg adds the SPI-over-JTAG proxy commands.
XC7_CFG_CANDIDATES = (
    "/usr/share/openocd/scripts/fpga/xlnx/xc7.cfg",
    "/usr/share/openocd/scripts/cpld/xilinx-xc7.cfg",
)
JTAGSPI_CFG_CANDIDATES = (
    "/usr/share/openocd/scripts/cpld/jtagspi.cfg",
    "/usr/share/openocd/scripts/fpga/xlnx/jtagspi.cfg",
)


@dataclass(frozen=True)
class Part:
    """A recognised Artix-7 variant on the NeTV2."""

    name: str
    idcode: int  # nominal IDCODE (revision nibble zero)
    bscan: str   # matching bscan_spi proxy bitstream filename

    def matches(self, observed: int) -> bool:
        return (observed & PART_ID_MASK) == (self.idcode & PART_ID_MASK)


# The two shipping NeTV2 variants, keyed by masked (revision-independent) IDCODE.
KNOWN_PARTS = {
    0x0362D093 & PART_ID_MASK: Part("35T", 0x0362D093, "bscan_spi_xc7a35t.bit"),
    0x03631093 & PART_ID_MASK: Part("100T", 0x03631093, "bscan_spi_xc7a100t.bit"),
}


class OpenOCDError(RuntimeError):
    """OpenOCD exited non-zero or produced no usable output."""


class UnknownIDCODEError(RuntimeError):
    """The IDCODE read back is not a recognised NeTV2 part."""


class NotConfirmedError(RuntimeError):
    """A flash write was requested without the explicit go-ahead flag."""


class GuardUnavailableError(RuntimeError):
    """The golden-unit guard could not be imported; flash refuses (fail closed)."""


# ---------------------------------------------------------------------------
# IDCODE parsing / part identification (pure, unit-tested)
# ---------------------------------------------------------------------------

_IDCODE_RE = re.compile(r"tap/device found:\s*(0x[0-9a-fA-F]+)")


def parse_idcode(openocd_output: str) -> int:
    """Extract the JTAG IDCODE from OpenOCD ``scan_chain`` output.

    Raises :class:`OpenOCDError` if no ``tap/device found:`` line is present
    (e.g. the JTAG chain read back all-zeros/all-ones or OpenOCD failed).
    """
    match = _IDCODE_RE.search(openocd_output)
    if not match:
        raise OpenOCDError(
            "no 'tap/device found:' line in OpenOCD output; JTAG chain not read "
            "(check cabling, power, and the gpiochip selection)"
        )
    return int(match.group(1), 16)


def identify_part(idcode: int) -> Part:
    """Map an observed IDCODE to a :class:`Part`, masking the revision nibble.

    Raises :class:`UnknownIDCODEError` for anything that is not a NeTV2 35T or
    100T -- the same gate the 2019 ``update-fpga.sh`` applied before touching
    the board.
    """
    part = KNOWN_PARTS.get(idcode & PART_ID_MASK)
    if part is None:
        raise UnknownIDCODEError(
            f"IDCODE {idcode:#010x} is not a known NeTV2 FPGA "
            f"(expected 0x0362D093=35T or 0x13631093/0x03631093=100T)"
        )
    return part


# ---------------------------------------------------------------------------
# Golden-unit guard (fail closed)
# ---------------------------------------------------------------------------

def _load_guard() -> Callable[..., None]:
    """Return ``tests.hardware.hosts.check_action_allowed`` or fail closed.

    The guard lives in the repo. When this tool runs from a checkout it is
    importable directly; we also add the repo root to ``sys.path`` in case the
    caller's CWD differs. If it still cannot be imported, we return a stub that
    refuses every flash write, so a deployment that shipped the tool without the
    guard cannot flash anything.
    """
    last_exc: ImportError | None = None
    for attempt in range(2):
        try:
            from tests.hardware.hosts import check_action_allowed
            return check_action_allowed
        except ImportError as exc:
            last_exc = exc
            if attempt == 0:
                # Retry once with the repo root explicitly on the path.
                repo_root = Path(__file__).resolve().parents[2]
                if str(repo_root) not in sys.path:
                    sys.path.insert(0, str(repo_root))

    def _refuse(*_args, **_kwargs):  # fail closed
        raise GuardUnavailableError(
            "golden-unit guard (tests.hardware.hosts) is unavailable; "
            "refusing all flash writes"
        ) from last_exc

    return _refuse


# ---------------------------------------------------------------------------
# OpenOCD invocation
# ---------------------------------------------------------------------------

# A runner takes an argv and returns a CompletedProcess-like object. The default
# shells out; tests inject a fake so nothing touches hardware.
Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def _first_existing(candidates: Sequence[str], override: str | None, what: str) -> str:
    if override:
        return override
    for cand in candidates:
        if Path(cand).exists():
            return cand
    # Fall back to the first candidate; OpenOCD will report if it is missing.
    return candidates[0] if candidates else what


class Programmer:
    """Drive OpenOCD for IDCODE read, volatile load, and (guarded) flash write."""

    def __init__(
        self,
        interface_cfg: str,
        *,
        xc7_cfg: str | None = None,
        jtagspi_cfg: str | None = None,
        runner: Runner = default_runner,
        openocd: str = "openocd",
        use_sudo: bool = True,
        guard: Callable[..., None] | None = None,
    ) -> None:
        self.interface_cfg = interface_cfg
        self.xc7_cfg = _first_existing(XC7_CFG_CANDIDATES, xc7_cfg, "xc7.cfg")
        self.jtagspi_cfg = _first_existing(JTAGSPI_CFG_CANDIDATES, jtagspi_cfg, "jtagspi.cfg")
        self.runner = runner
        self.openocd = openocd
        self.use_sudo = use_sudo
        self._guard = guard if guard is not None else _load_guard()

    def build_argv(self, tcl_commands: str, extra_cfgs: Sequence[str] = ()) -> list[str]:
        argv: list[str] = []
        if self.use_sudo:
            argv.append("sudo")
        argv += [self.openocd, "-f", self.interface_cfg, "-f", self.xc7_cfg]
        for cfg in extra_cfgs:
            argv += ["-f", cfg]
        argv += ["-c", tcl_commands]
        return argv

    def _run(self, tcl_commands: str, extra_cfgs: Sequence[str] = ()) -> str:
        argv = self.build_argv(tcl_commands, extra_cfgs)
        result = self.runner(argv)
        out = result.stdout or ""
        if result.returncode != 0:
            raise OpenOCDError(f"openocd exited {result.returncode}:\n{out}")
        return out

    def read_idcode(self) -> int:
        return parse_idcode(self._run("init; scan_chain; exit"))

    def identify(self) -> Part:
        return identify_part(self.read_idcode())

    def volatile_load(self, bitfile: str) -> Part:
        """Read+verify IDCODE, then load ``bitfile`` into SRAM (no flash write)."""
        part = self.identify()
        bit = Path(bitfile)
        if not bit.exists():
            raise FileNotFoundError(f"bitstream not found: {bitfile}")
        self._run(f"init; scan_chain; pld load 0 {bit}; exit")
        return part

    def flash_write(
        self,
        host: str,
        image: str,
        *,
        offset: int = 0,
        bscan_path: str | None = None,
        confirmed: bool = False,
    ) -> Part:
        """Persistent SPI-NOR write. Guarded three ways; see module docstring.

        Order matters: the golden-unit guard is consulted FIRST, so a flash on
        ``rpi3-netv2`` is refused before the confirmation flag is even examined.
        """
        # 1. golden-unit guard -- raises GoldenUnitError on rpi3-netv2.
        self._guard(host, "spi_flash_write")
        # 2. explicit go-ahead.
        if not confirmed:
            raise NotConfirmedError(
                f"refusing SPI flash write without {CONFIRM_FLAG}"
            )
        # 3. identify part and pick the matching bscan proxy.
        part = self.identify()
        img = Path(image)
        if not img.exists():
            raise FileNotFoundError(f"flash image not found: {image}")
        bscan = bscan_path or part.bscan
        tcl = (
            f"init; scan_chain; "
            f"jtagspi_init 0 {bscan}; "
            f"jtagspi_program {img} {offset:#x}; "
            f"xc7_program xc7.tap; exit"
        )
        self._run(tcl, extra_cfgs=(self.jtagspi_cfg,))
        return part


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

DEFAULT_INTERFACE_CFG = str(Path(__file__).resolve().parent / "openocd" / "netv2-jtag.cfg")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="netv2_update.py",
        description="NeTV2 FPGA update tool (trixie / OpenOCD 0.12 linuxgpiod)",
    )
    p.add_argument(
        "--interface-cfg",
        default=DEFAULT_INTERFACE_CFG,
        help="OpenOCD interface config (default: bundled netv2-jtag.cfg)",
    )
    p.add_argument("--xc7-cfg", default=None, help="override the xc7 PLD/TAP config path")
    p.add_argument("--jtagspi-cfg", default=None, help="override the jtagspi config path")
    p.add_argument("--openocd", default="openocd", help="openocd executable")
    p.add_argument("--no-sudo", action="store_true", help="do not prefix openocd with sudo")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("idcode", help="read the FPGA IDCODE and identify the part")

    lp = sub.add_parser("load", help="VOLATILE bitstream load into FPGA SRAM (no flash)")
    lp.add_argument("bitfile", help="path to the .bit bitstream")

    fp = sub.add_parser("flash", help="PERSISTENT SPI-NOR write (guarded; dangerous)")
    fp.add_argument("image", help="path to the flash-ready .bin image (LiteSPI layout)")
    fp.add_argument("--host", required=True, help="target host name (golden-unit guard)")
    fp.add_argument("--offset", default="0", help="flash offset (hex or decimal, default 0)")
    fp.add_argument("--bscan", default=None, help="override the bscan_spi proxy bitstream")
    fp.add_argument(
        CONFIRM_FLAG,
        dest="confirmed",
        action="store_true",
        help="explicit go-ahead required to actually write flash",
    )
    return p


def _make_programmer(args: argparse.Namespace) -> Programmer:
    return Programmer(
        args.interface_cfg,
        xc7_cfg=args.xc7_cfg,
        jtagspi_cfg=args.jtagspi_cfg,
        openocd=args.openocd,
        use_sudo=not args.no_sudo,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prog = _make_programmer(args)

    if args.command == "idcode":
        idcode = prog.read_idcode()
        part = identify_part(idcode)
        print(f"IDCODE {idcode:#010x} -> XC7A{part.name}")
        return 0

    if args.command == "load":
        part = prog.volatile_load(args.bitfile)
        print(f"VOLATILE load OK on XC7A{part.name}: {args.bitfile}")
        print("(configuration is in SRAM; a power cycle restores flash)")
        return 0

    if args.command == "flash":
        offset = int(args.offset, 0)
        part = prog.flash_write(
            args.host,
            args.image,
            offset=offset,
            bscan_path=args.bscan,
            confirmed=args.confirmed,
        )
        print(f"FLASH write OK on XC7A{part.name}: {args.image} @ {offset:#x}")
        return 0

    return 2  # unreachable: subparsers are required


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, FileNotFoundError) as err:
        # RuntimeError covers OpenOCDError/UnknownIDCODEError/NotConfirmedError/
        # GuardUnavailableError and the guard's GoldenUnitError.
        print(f"error: {type(err).__name__}: {err}", file=sys.stderr)
        raise SystemExit(1) from err
