> Imported 2026-09-05 from ten64:~/local/netv2/docs (written 2026-02-22). Facts below reflect that date; the rpi5-netv2 OpenOCD now has the linuxgpiod driver compiled in (verified 2026-09-05).

# Programming the NeTV2 FPGA from a Raspberry Pi 5

## Overview

The NeTV2 is an open-source Xilinx Artix-7 FPGA board designed by bunnie (Andrew Huang). Its JTAG header connects directly to the Raspberry Pi's 40-pin GPIO header, allowing the Pi to program the FPGA without any external debug probe.

The original NeTV2 software was written for the Raspberry Pi 3B+ and used OpenOCD's `bcm2835gpio` driver for fast, direct-register GPIO bit-banging. The Pi 5's fundamentally different GPIO architecture (the RP1 I/O controller chip, connected via PCIe) breaks this approach entirely. This document covers how to make it work on Pi 5.

## Hardware

### FPGA

The NeTV2 ships in two variants:

| Variant | FPGA | Logic Cells | JTAG IDCODE |
|---------|------|-------------|-------------|
| Base | XC7A35T-FGG484-2 | 33,280 | `0x0362D093` |
| Upgraded | XC7A100T-FGG484-2 | 101,440 | `0x03631093` |

Both have 512 MB DDR3-800 RAM, 8 MB SPI NOR flash, 100Base-T Ethernet (FPGA-attached), 2x HDMI in, 2x HDMI out, USB, and PCIe x1.

### JTAG Wiring

The NeTV2's JTAG header maps to the RPi GPIO header as follows:

| JTAG Signal | BCM GPIO | Physical Pin | Direction |
|-------------|----------|--------------|-----------|
| TCK         | GPIO 4   | Pin 7        | Output    |
| TMS         | GPIO 17  | Pin 11       | Output    |
| TDI         | GPIO 27  | Pin 13       | Output    |
| TDO         | GPIO 22  | Pin 15       | Input     |
| SRST        | GPIO 24  | Pin 18       | Output    |
| GND         | —        | Pin 20       | —         |

These are the **NeTV2-specific** pin assignments. They differ from the default OpenOCD Raspberry Pi GPIO config (`raspberrypi-gpio-connector.cfg`), which uses GPIO 11/8/10/9 for TCK/TMS/TDI/TDO.

The physical 40-pin header is identical between Pi 3, Pi 4, and Pi 5 — the NeTV2 plugs in the same way on all models.

## Why Pi 5 Is Different

On the Pi 1 through Pi 4, GPIO pins connect directly to the main SoC (BCM2835/BCM2711). Software can toggle pins by writing to memory-mapped registers with single-cycle latency. OpenOCD's `bcm2835gpio` driver uses this for fast JTAG at >40 kB/s throughput.

On the Pi 5, GPIO pins connect to the **RP1** chip — a separate I/O controller connected to the BCM2712 SoC via **PCIe Gen 2**. Every GPIO register access must traverse this PCIe link, adding hundreds of nanoseconds of latency per operation. The `bcm2835gpio` driver cannot work because:

1. The GPIO register layout is completely different (RP1 vs BCM2835)
2. `/dev/gpiomem` (singular) does not exist — Pi 5 has `/dev/gpiomem0` through `/dev/gpiomem4`
3. The peripheral base addresses are different (RP1 at `0x1F00000000` vs BCM2835 at `0x3F000000`)

### What works instead

| Driver | Status on Pi 5 | Speed |
|--------|----------------|-------|
| `bcm2835gpio` | **Broken** — wrong register layout | N/A |
| `linuxgpiod` | Works in theory — but **not compiled** into the RPi-packaged OpenOCD | ~13 kB/s |
| `sysfsgpio` | **Works** — deprecated but functional | Similar to linuxgpiod |
| RP1 PIO | **Future** — hardware JTAG engine, 50-200x faster | Estimated 0.5-3 MB/s |

## Prerequisites

### Raspberry Pi 5 Setup

Confirmed working on:
- Raspberry Pi 5 Model B Rev 1.0
- Debian GNU/Linux 13 (trixie)
- Kernel 6.12.47+rpt-rpi-2712
- OpenOCD 0.12.0+rpt20250716 (Raspberry Pi packaged)

Install OpenOCD (if not already installed):

```bash
sudo apt install openocd
```

### PCIe ASPM

The RP1 chip connects via PCIe. If power saving (ASPM) is enabled, the first GPIO pulses after an idle period are unreliable. Set the policy to `performance`:

```bash
# Check current policy (brackets show active):
cat /sys/module/pcie_aspm/parameters/policy
# default [performance] powersave powersupersave  ← good
# default performance [powersave] powersupersave  ← bad

# Set to performance (non-persistent):
echo performance | sudo tee /sys/module/pcie_aspm/parameters/policy

# Make persistent across reboots — add to kernel command line:
# Edit /boot/firmware/cmdline.txt and append:
#   pcie_aspm.policy=performance
```

### Sysfs GPIO Base Offset

On Pi 5, the RP1 GPIO controller appears as `gpiochip571` in the sysfs interface (not gpiochip0). The `sysfsgpio` OpenOCD driver uses sysfs numbers, so all GPIO numbers must be offset by **571**:

| Signal | BCM GPIO | Sysfs Number |
|--------|----------|--------------|
| TCK | 4 | **575** |
| TMS | 17 | **588** |
| TDI | 27 | **598** |
| TDO | 22 | **593** |
| SRST | 24 | **595** |

To verify the RP1 base on your system:

```bash
cat /sys/class/gpio/gpiochip571/label
# Should output: pinctrl-rp1

cat /sys/class/gpio/gpiochip571/base
# Should output: 571
```

## OpenOCD Configuration

### Interface Config: `netv2-rpi5-sysfsgpio.cfg`

Create this file (e.g. at `~/netv2/netv2-rpi5-sysfsgpio.cfg`):

```tcl
# NeTV2 JTAG interface for Raspberry Pi 5 using sysfsgpio
#
# NeTV2 JTAG header pin mapping:
#   TCK = GPIO 4  (physical pin 7)  -> sysfs 575
#   TMS = GPIO 17 (physical pin 11) -> sysfs 588
#   TDI = GPIO 27 (physical pin 13) -> sysfs 598
#   TDO = GPIO 22 (physical pin 15) -> sysfs 593
#   SRST = GPIO 24 (physical pin 18) -> sysfs 595
#   GND = physical pin 20
#
# On Pi 5, the RP1 GPIO controller's sysfs base is 571 (gpiochip571).
# Sysfs GPIO number = 571 + BCM GPIO number.

adapter driver sysfsgpio

# NeTV2 JTAG pin mapping (sysfs numbers = 571 + BCM GPIO)
# Order: TCK TMS TDI TDO
sysfsgpio jtag_nums 575 588 598 593

# SRST (GPIO 24 = sysfs 595)
sysfsgpio srst_num 595
reset_config srst_only srst_push_pull

transport select jtag
adapter speed 1000
```

### Why Not `linuxgpiod`?

The RPi-packaged OpenOCD (`0.12.0+rpt20250716`) includes the `raspberrypi5-gpiod.cfg` config file but was compiled **without** the `linuxgpiod` adapter driver. The driver binary is missing despite the config being shipped. You can verify this:

```bash
openocd -c "adapter driver linuxgpiod" -c "exit"
# Error: The specified adapter driver was not found (linuxgpiod)
```

The `sysfsgpio` driver is deprecated but functional and already compiled in. If you need `linuxgpiod`, you must rebuild OpenOCD from source with `--enable-linuxgpiod` and `libgpiod-dev` installed.

## Basic Operations

### Test JTAG Connectivity (Read IDCODE)

The simplest test — reads the FPGA's JTAG identification code:

```bash
sudo openocd \
    -s ~/netv2 \
    -f netv2-rpi5-sysfsgpio.cfg \
    -f /usr/share/openocd/scripts/cpld/xilinx-xc7.cfg \
    -c "init; scan_chain; exit"
```

Expected output:

```
Info : SysfsGPIO JTAG/SWD bitbang driver
Info : Note: The adapter "sysfsgpio" doesn't support configurable speed
Info : JTAG tap: xc7.tap tap/device found: 0x13631093 (mfg: 0x049 (Xilinx), part: 0x3631, ver: 0x1)
```

If you see `0x13631093` → XC7A100T. If `0x0362D093` → XC7A35T.

### Load a Bitstream (Volatile)

Programs the FPGA's configuration SRAM via JTAG. The configuration is lost on power cycle.

```bash
sudo openocd \
    -s ~/netv2 \
    -f netv2-rpi5-sysfsgpio.cfg \
    -f /usr/share/openocd/scripts/cpld/xilinx-xc7.cfg \
    -c "init; pld load 0 /path/to/bitstream.bit; exit"
```

Pre-built bitstreams for the NeTV2 production firmware:

```bash
# Download for XC7A100T:
wget -O ~/netv2/user-100.bit \
    https://raw.githubusercontent.com/AlphamaxMedia/netv2-fpga/master/production-images/user-100.bit

# Download for XC7A35T:
wget -O ~/netv2/user-35.bit \
    https://raw.githubusercontent.com/AlphamaxMedia/netv2-fpga/master/production-images/user-35.bit
```

### Program SPI Flash (Persistent)

Writes a bitstream to the 8 MB SPI NOR flash through JTAG. The FPGA loads from flash on power-up, so this survives power cycles.

This requires a **bscan_spi proxy bitstream** — a small helper bitstream that bridges the JTAG port to the SPI flash chip inside the FPGA.

```bash
# Download bscan_spi proxy (match your FPGA variant):
wget -O ~/netv2/bscan_spi_xc7a100t.bit \
    https://raw.githubusercontent.com/quartiq/bscan_spi_bitstreams/master/bscan_spi_xc7a100t.bit

# Or for XC7A35T:
wget -O ~/netv2/bscan_spi_xc7a35t.bit \
    https://raw.githubusercontent.com/quartiq/bscan_spi_bitstreams/master/bscan_spi_xc7a35t.bit
```

Program the flash:

```bash
sudo openocd \
    -s ~/netv2 \
    -f netv2-rpi5-sysfsgpio.cfg \
    -f /usr/share/openocd/scripts/cpld/xilinx-xc7.cfg \
    -f /usr/share/openocd/scripts/cpld/jtagspi.cfg \
    -c "init; jtagspi_init 0 ~/netv2/bscan_spi_xc7a100t.bit; jtagspi_program /path/to/image.bin 0; exit"
```

Note: SPI flash requires `.bin` (raw binary) format, not `.bit` (Xilinx bitstream with header).

## Performance

The `sysfsgpio` driver does not support configurable speed. Each GPIO toggle goes through the Linux sysfs interface and crosses the PCIe bus to the RP1 chip. Programming a 3.6 MB bitstream (XC7A100T) takes several minutes.

For significantly faster programming, an RP1 PIO-based JTAG implementation is under development — see `02-rp1-pio-jtag.md`.

## Troubleshooting

### "No route to host" when SSH-ing to the Pi

The Pi may take a moment after boot to bring up networking. ARP resolves before the TCP stack is ready. Wait 30 seconds and try again, or use `arping` to verify L2 connectivity:

```bash
sudo arping -i br-int -S 10.1.10.1 10.1.10.14
```

### "adapter driver not found (linuxgpiod)"

The RPi-packaged OpenOCD lacks linuxgpiod. Use the `sysfsgpio` config instead (this document's approach).

### IDCODE all zeros or all ones

- All zeros (`0x00000000`): JTAG signals not reaching the FPGA. Check physical connection.
- All ones (`0xFFFFFFFF`): TDO stuck high. Check the NeTV2 is powered and the JTAG header is seated correctly.

### "SysfsGPIO: gpio_export: Cannot write to /sys/class/gpio/export"

Run OpenOCD with `sudo`. The sysfs GPIO interface requires root access to export pins.

### PCIe ASPM warning from OpenOCD

If using the linuxgpiod config (after rebuilding OpenOCD), you'll see:

```
Warn : Switch PCIe power saving off or the first couple of pulses gets clocked as fast as 20 MHz
```

Fix with: `echo performance | sudo tee /sys/module/pcie_aspm/parameters/policy`

## Comparison: RPi 3/4 vs RPi 5

| Aspect | RPi 3/4 | RPi 5 |
|--------|---------|-------|
| GPIO chip | BCM2835/BCM2711 (on-SoC) | RP1 (via PCIe) |
| OpenOCD driver | `bcm2835gpio` (direct mmap) | `sysfsgpio` (sysfs) or `linuxgpiod` (chardev) |
| GPIO base address | `0x3F000000` (Pi 3) / `0xFE000000` (Pi 4) | N/A (sysfs abstraction, base 571) |
| JTAG throughput | >40 kB/s | ~few kB/s (sysfsgpio) |
| `sudo` required | Yes (for /dev/gpiomem or /dev/mem) | Yes (for sysfs export) |
| Config files | `alphamax-rpi.cfg` / `alphamax-rpi-4.cfg` | `netv2-rpi5-sysfsgpio.cfg` (custom) |

## References

- [AlphamaxMedia/netv2mvp-scripts](https://github.com/AlphamaxMedia/netv2mvp-scripts) — Original RPi 3/4 OpenOCD configs
- [AlphamaxMedia/xvcpi](https://github.com/AlphamaxMedia/xvcpi) — GPIO pin mapping source
- [AlphamaxMedia/netv2-fpga](https://github.com/AlphamaxMedia/netv2-fpga) — Pre-built bitstreams
- [quartiq/bscan_spi_bitstreams](https://github.com/quartiq/bscan_spi_bitstreams) — SPI flash proxy bitstreams
- [OpenOCD raspberrypi5-gpiod.cfg](https://github.com/openocd-org/openocd/blob/master/tcl/interface/raspberrypi5-gpiod.cfg) — Pi 5 linuxgpiod reference
- [NeTV2 Crowd Supply](https://www.crowdsupply.com/alphamax/netv2) — Hardware specs
