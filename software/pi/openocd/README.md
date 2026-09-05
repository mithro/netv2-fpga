# NeTV2 OpenOCD / openFPGALoader configs for trixie

`netv2-jtag.cfg` is the one interface config for **Raspberry Pi OS trixie**
(Debian 13) across Pi 3B+/4/5. It uses OpenOCD 0.12's `linuxgpiod`
(libgpiod / character-device) driver and replaces the 2019 `bcm2835gpio`
configs (`alphamax-rpi.cfg`, `alphamax-rpi-4.cfg`), which cannot drive the Pi 5
(the 40-pin header hangs off the RP1 chip over PCIe, not the BCM SoC).

## Pin map (identical wiring on Pi 3/4/5)

| JTAG | BCM GPIO | Header pin |
| --- | --- | --- |
| TCK  | 4  | 7  |
| TMS  | 17 | 11 |
| TDI  | 27 | 13 |
| TDO  | 22 | 15 |
| SRST | 24 | 18 |
| GND  | —  | 20 |

The BCM line numbers are the same on every model; only the *gpiochip* that
carries the header changes. `netv2-jtag.cfg` auto-detects it: it prefers the
RP1 chip (Pi 5, device-tree alias content matches `/rp1/`), then the SoC
`gpio@7e200000` controller (Pi 3/4), then falls back to chip 0 with a warning.
Override with `NETV2_JTAG_GPIOCHIP=<n>` if detection is wrong.

## OpenOCD usage

The interface config is sourced first, then the Xilinx Series-7 PLD/TAP
definition. On trixie OpenOCD that lives at `fpga/xlnx/xc7.cfg` (older layouts
used `cpld/xilinx-xc7.cfg`).

```bash
# read IDCODE
sudo openocd -f netv2-jtag.cfg \
    -f /usr/share/openocd/scripts/fpga/xlnx/xc7.cfg \
    -c "init; scan_chain; exit"

# volatile load (SRAM; power-cycle reversible)
sudo openocd -f netv2-jtag.cfg \
    -f /usr/share/openocd/scripts/fpga/xlnx/xc7.cfg \
    -c "init; scan_chain; pld load 0 /path/to.bit; exit"
```

Prefer `../netv2_update.py`, which builds these command lines for you and adds
the IDCODE gate and the golden-unit guard.

## openFPGALoader equivalent

openFPGALoader speaks libgpiod directly; the NeTV2 pin order is
**TDI:TDO:TCK:TMS = 27:22:4:17** (SRST is not needed for load):

```bash
# detect (read-only)
sudo openFPGALoader --cable libgpiod --pins 27:22:4:17 --detect

# volatile load
sudo openFPGALoader --cable libgpiod --pins 27:22:4:17 /path/to.bit

# persistent SPI-flash write (DANGEROUS -- never on the golden unit)
sudo openFPGALoader --cable libgpiod --pins 27:22:4:17 -f /path/to.bin
```

Verified on rpi5-netv2 (trixie): `--detect` reads `idcode 0x3631093`
(artix a7 100t). See `docs/testing/reports/2026-09-phase4-pi/`.

## Speed

libgpiod bit-banging is far slower than the old 2019 `bcm2835gpio` fork (which
was patched for ~10 MHz). `netv2-jtag.cfg` sets `adapter speed 1000`; a 100T
volatile load takes roughly half a minute. The `linuxgpiod` driver reports it
"doesn't support configurable speed" — the setting is advisory. The future RP1
PIO JTAG engine (see `docs/current/pi5-rp1-pio-jtag.md`) will close the gap.
