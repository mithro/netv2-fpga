# Phase 4a: Pi-side software modernised for Raspberry Pi OS trixie

The 2019 Raspbian-9 Pi-side tooling (OpenOCD 0.10 `bcm2835gpio` fork,
`update-fpga.sh`, pm2/Node status app) has been ported to current Raspberry Pi
OS (Debian 13 "trixie"): OpenOCD 0.12 `linuxgpiod`, a Python 3 update tool with
the golden-unit guard, and systemd instead of pm2. The modernised JTAG path was
proved on real hardware (rpi5-netv2) with a **volatile-only** IDCODE read and
bitstream load. **No SPI flash was written; the golden unit rpi3-netv2 was never
contacted.**

## Summary

| Item | Value |
| --- | --- |
| Date | 2026-09-06 |
| Host (Pi) | **rpi5-netv2**.iot.welland.mithis.com (non-golden 100T dev unit) |
| OS | Debian GNU/Linux 13 (trixie) |
| Kernel | 6.18.39+rpt-rpi-2712 |
| Python | 3.13.5 |
| OpenOCD | 0.12.0+dev-g43648fe-dirty (linuxgpiod compiled in) |
| openFPGALoader | v1.1.0 |
| FPGA | Xilinx XC7A100T (kosagi_netv2) |
| JTAG IDCODE (read) | **0x13631093** -> identified XC7A100T |
| Bitstream loaded | `build/netv2-base/gateware/kosagi_netv2.bit` (phase-2 base SoC) |
| Bitstream sha256 | `cf8b231daeceb4ceb04a200475d2b5cd7bf68a04daa00100a4f5a51032bde013` |
| Load method | **VOLATILE** `pld load` into config SRAM (~36 s over libgpiod) |
| Boot result | LiteX BIOS banner -> DDR3 read leveling -> **Memtest OK** -> `litex>` |

## What was exercised

1. **Unified interface config** `software/pi/openocd/netv2-jtag.cfg`
   (linuxgpiod, RP1/BCM gpiochip auto-detect, NeTV2 pin map
   TCK4/TMS17/TDI27/TDO22/SRST24) read the IDCODE:
   see `idcode-openocd.txt`.
2. **Python update tool** `software/pi/netv2_update.py`, deployed to rpi5 and
   run under the stock trixie `python3`, read the IDCODE and performed the
   volatile load: see `idcode-tool.txt`.
3. **openFPGALoader equivalent** (`--cable libgpiod --pins 27:22:4:17`)
   read the same IDCODE, confirming the documented alternative works:
   see `openfpgaloader-detect.txt`.
4. The loaded phase-2 base SoC **booted and passed its DDR3 memtest**:
   full capture in `uart-boot.log`.

## Commands run on rpi5-netv2

```
# IDCODE via the Python tool (calls: sudo openocd -f netv2-jtag.cfg -f xc7.cfg ...)
python3 netv2_update.py idcode
# -> IDCODE 0x13631093 -> XC7A100T

# volatile load (no flash)
python3 netv2_update.py load netv2-base.bit
# -> VOLATILE load OK on XC7A100T

# openFPGALoader equivalent, read-only
sudo openFPGALoader --cable libgpiod --pins 27:22:4:17 --detect
```

UART boot output captured on `/dev/ttyAMA0` @ 115200.

## Safety

- Only **rpi5-netv2** (non-golden 100T dev unit) was touched.
- **rpi3-netv2 (golden) was never contacted.**
- Load was **volatile SRAM only**; SPI flash was never written or erased; the
  `flash` subcommand of the update tool was never run against hardware (it is
  gated behind the golden-unit guard and the `--i-have-tim-go-ahead` flag, and
  covered only by mocked unit tests).
- No Pi reboot, no power cycle, no JTAG SRST assert.

## Files

- `idcode-openocd.txt` — `scan_chain` via `software/pi/openocd/netv2-jtag.cfg`.
- `idcode-tool.txt` — `netv2_update.py idcode` and `load` output.
- `openfpgaloader-detect.txt` — openFPGALoader libgpiod detect.
- `uart-boot.log` — full BIOS boot capture including `Memtest OK` and `litex>`.

## Unit tests

`tests/unit/test_netv2_update.py` (20 tests) covers IDCODE parsing/identification
(including the revision-nibble mask and the neighbouring XC7A50T rejection), the
golden-unit flash refusal (guard fires before OpenOCD is invoked), the
confirmation gate, the volatile-vs-flash command selection, and fail-closed
behaviour when the guard is unavailable. `uv run pytest tests/unit tests/hardware`
is green (93 passed).
