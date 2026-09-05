# Pi-side software on Raspberry Pi OS trixie

How the NeTV2's Raspberry-Pi-side programming, update, and status tooling was
brought from the 2019 Raspbian-9 stack (documented in
`docs/original/pi-software.md`) onto current **Raspberry Pi OS "trixie"**
(Debian 13). The modern tooling lives under `software/pi/`.

This phase modernises the **programming / update / status** tooling and the
systemd integration. The MagicMirror overlay **application** is deliberately
deferred (it needs the overlay gateware, a separate track); its port plan is
`software/pi/magicmirror-port.md`.

## What changed

| Concern | 2019 (Raspbian 9) | trixie (Debian 13) |
| --- | --- | --- |
| OpenOCD | 0.10 AlphamaxMedia fork, `bcm2835gpio` (mmap), `--enable-bcm2835gpio`, ~10 MHz | 0.12, `linuxgpiod` (libgpiod chardev), ~1 MHz |
| JTAG interface cfg | `alphamax-rpi.cfg` / `alphamax-rpi-4.cfg` (bcm2835gpio) | `software/pi/openocd/netv2-jtag.cfg` (linuxgpiod, one file for Pi 3/4/5) |
| GPIO access | `/dev/gpiomem`, peripheral base `0x3F000000` (Pi2/3) | libgpiod character device; RP1 vs BCM gpiochip auto-detected |
| Updater | `update-fpga.sh` (bash) + `bin/mknetv2img` | `software/pi/netv2_update.py` (Python 3.9+) |
| Flash image format | `mknetv2img -f` byte-swap + CRC framing | LiteX/LiteSPI flash-ready `.bin` (no byte-swap) |
| Status feed | `netv2-status.js` (node serialport) | `software/pi/netv2_status.py` (pyserial + `http.server`) |
| Autostart | pm2 (`pm2-pi.service`, `pm2 resurrect`) | systemd (`software/pi/systemd/netv2-status.service`) |
| Language | Python 3.5, Node 10 (via `~/n`) | Python 3.13, Debian Node 20 |
| Also / alt loader | — | `openFPGALoader --cable libgpiod --pins 27:22:4:17` |

### Why the old driver cannot work on Pi 5

On Pi 1–4 the 40-pin GPIO is on the main SoC (BCM2835/2711) and OpenOCD's
`bcm2835gpio` toggles it with memory-mapped writes. On the **Pi 5** the header
hangs off the **RP1** I/O controller reached over **PCIe**: the register layout
is different, `/dev/gpiomem` is split into `gpiomem0..4`, and the peripheral base
is elsewhere. `bcm2835gpio` is simply wrong there. OpenOCD 0.12's `linuxgpiod`
driver talks to the kernel's libgpiod character device, which abstracts all of
that — the same config then works on Pi 3/4 too. (The deprecated `sysfsgpio`
driver also works and is described in `docs/current/pi5-programming.md`; on
rpi5-netv2 OpenOCD is now built **with** `linuxgpiod`, so we standardise on it.)

### One config across Pi 3/4/5

`software/pi/openocd/netv2-jtag.cfg` keeps the NeTV2 pin map
(TCK=GPIO4, TMS=GPIO17, TDI=GPIO27, TDO=GPIO22, SRST=GPIO24 — unchanged BCM line
numbers on every model) and auto-detects which `/dev/gpiochip` carries the
header: RP1 on Pi 5 (device-tree alias content matching `/rp1/`, the same rule
as OpenOCD's stock `raspberrypi5-gpiod.cfg`), else the SoC `gpio@7e200000`
controller on Pi 3/4, else chip 0 with a warning. `NETV2_JTAG_GPIOCHIP=<n>`
overrides. On Pi 5 it also warns if PCIe ASPM is not `performance` (RP1 timing).

### Flash image format: LiteSPI supersedes mknetv2img

The 2019 flow padded `user-firmware.bin` and wrapped it with `bin/mknetv2img -f`
— a byte-swap plus CRC framing step — before burning firmware and gateware to
SPI NOR. The modern LiteX build emits a **flash-ready** image directly: the
LiteX/**LiteSPI** flow produces `kosagi_netv2.bin` (gateware) and the SoC
firmware in the layout LiteSPI expects, in the correct byte order. So the trixie
updater writes the raw `.bin` at the requested offset and **does not run
mknetv2img**. This is called out in `netv2_update.py`'s docstring.

## Programming / updating on trixie (Pi 3/4/5)

Install the tools once:

```bash
sudo apt install openocd            # 0.12 with linuxgpiod
# openFPGALoader is optional (built from source on rpi5-netv2)
```

Use the Python tool (it applies the IDCODE gate and the golden-unit guard):

```bash
cd software/pi

# 1. read + identify the FPGA
python3 netv2_update.py idcode
#   -> IDCODE 0x13631093 -> XC7A100T   (or 0x0362D093 -> XC7A35T)

# 2. VOLATILE load (into config SRAM; a power cycle restores flash)
python3 netv2_update.py load /path/to/kosagi_netv2.bit

# 3. PERSISTENT SPI-flash write (DANGEROUS -- see safety rule below)
python3 netv2_update.py flash /path/to/image.bin \
        --host <hostname> --i-have-tim-go-ahead
```

`idcode`/`load` need no extra files; the tool finds `xc7.cfg` under
`/usr/share/openocd/scripts/`. Equivalent raw OpenOCD and openFPGALoader command
lines are in `software/pi/openocd/README.md`.

The IDCODE gate is preserved from the 2019 updater: `0x0362D093` = XC7A35T,
`0x13631093`/`0x03631093` = XC7A100T; anything else aborts. The silicon-revision
nibble (bits 31:28) is masked before comparison, and only that nibble — XC7A50T
(`0x0362C093`) is one nibble from the 35T and is correctly rejected (see
`tests/hardware/hosts.py`).

## Golden-unit safety rule

`rpi3-netv2` is the untouched 2018 reference unit. It may only receive
**volatile** JTAG loads and non-persistent console traffic. `netv2_update.py`
enforces this: the `flash` path calls
`tests.hardware.hosts.check_action_allowed(host, "spi_flash_write")`, which
raises `GoldenUnitError` for the golden unit, **before** the confirmation flag
is even examined and before OpenOCD is invoked. Beyond that, the flash path:

- refuses to run without the explicit `--i-have-tim-go-ahead` flag;
- **fails closed** if the guard module cannot be imported (refuses all flash).

Never run `flash` (or `openFPGALoader -f`, or any `jtagspi_program` /
`flash erase_address`) against `rpi3-netv2`. Volatile `load` is fine there.

## Status reporter and systemd

`software/pi/netv2_status.py` replaces `netv2-status.js`: it opens the console
UART (`/dev/ttyS0` on Pi 3, `/dev/ttyAMA0` on Pi 5), sends `json on`, and
republishes the latest telemetry JSON on `http://127.0.0.1:6502/` — the **same
endpoint and contract** the node app served, so an existing `MMM-json-feed`
config needs no change. It adds reconnection and environment-based config.
`software/pi/systemd/netv2-status.service` (+ `netv2-status.env`) runs it under
systemd, replacing pm2.

The telemetry field set is defined by the **overlay firmware**; until that track
lands the reporter serves `{}`. See `software/pi/magicmirror-port.md`.

## Remaining work: the MagicMirror overlay app

The MagicMirror **application** (Node app, `config.js`, the `MMM-json-feed`
`netv2` fork, lightdm/X autostart) is **not** ported in this phase. It is only
useful once the overlay gateware composites the MagicMirror window onto the HDMI
pass-through, which is a separate modernisation track. The full port plan —
MagicMirror on Debian Node, systemd instead of pm2, `MMM-json-feed` re-basing,
`config.js`, and the colourspace/console helper scripts — is in
`software/pi/magicmirror-port.md`.

## Note: Pi 3B+ on trixie needs netboot access

The Pi 3B+ target (the model the stock NeTV2 shipped with) is not directly
reachable for this phase; validating the config on real Pi 3/4 hardware needs
netboot access to that unit (`tweed` host key). The trixie config is written to
support Pi 3/4 (BCM `gpio@7e200000` gpiochip auto-detect, unchanged pin map) but
was hardware-verified only on **rpi5-netv2** (Pi 5). The Pi 3/4 path should be
confirmed once that netboot access is available.

## Hardware validation

Proven on **rpi5-netv2** (trixie, non-golden 100T): the Python tool read
IDCODE `0x13631093` and volatile-loaded the phase-2 base bitstream
(`build/netv2-base/gateware/kosagi_netv2.bit`,
sha256 `cf8b231d…`), which booted to a passing DDR3 memtest and the `litex>`
prompt. openFPGALoader's libgpiod equivalent read the same IDCODE. **No flash
write; golden unit never contacted.** Full evidence:
`docs/testing/reports/2026-09-phase4-pi/`.
