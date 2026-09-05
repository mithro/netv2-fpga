# Phase 2a: modern LiteX NeTV2 base SoC on real hardware

First hardware-run artifact of the NeTV2 modernisation: the maintained
`litex_boards.targets.kosagi_netv2` BaseSoC (a7-100), built on the modern
LiteX **2026.04** stack, closes timing on Vivado 2025.2, and boots on the
physical NeTV2 with a passing DDR3 memtest.

## Summary

| Item | Value |
| --- | --- |
| Date | 2026-09-06 |
| Host (Pi) | **rpi5-netv2**.iot.welland.mithis.com (non-golden 100T dev unit) |
| FPGA | Xilinx XC7A100T (kosagi_netv2, variant a7-100) |
| JTAG IDCODE | **0x13631093** (mfg 0x049 Xilinx, part 0x3631) — asserted before load |
| LiteX version | **2026.04** (git sha1 776e83b) |
| Toolchain | Vivado 2025.2 (`/opt/Xilinx/2025.2`) |
| Build target | `netv2/targets/base.py` -> `litex_boards.targets.kosagi_netv2.BaseSoC` |
| SoC | VexRiscv @ 100 MHz, integrated BIOS, UART, DDR3 (s7ddrphy) |
| Bitstream | `build/netv2-base/gateware/kosagi_netv2.bit` |
| Bitstream sha256 | `cf8b231daeceb4ceb04a200475d2b5cd7bf68a04daa00100a4f5a51032bde013` |
| **Post-route WNS** | **+0.893 ns** (0 failing endpoints; "All user specified timing constraints are met") |
| SoC ident (queried) | `LiteX SoC on NeTV2 2026-09-06 04:20:20` |
| SDRAM | 512.0 MiB, 32-bit DDR3 @ 800 MT/s (CL-7 CWL-5) |
| **DDR3 memtest** | **Memtest OK** |
| Boot | LiteX BIOS banner -> read leveling -> memtest -> `litex>` prompt |

## Load method — VOLATILE ONLY

The bitstream was loaded into FPGA **SRAM** via JTAG `pld load`, which is
power-cycle-reversible. **No SPI flash was written** (no jtagspi, no flashcpu,
no program_flash). A power cycle of the NeTV2 restores its stock flash image.

Load command run on rpi5-netv2 (linuxgpiod JTAG on the RP1 GPIO):

```
sudo openocd \
  -f /home/tim/netv2/netv2-rpi5.cfg \
  -f /usr/share/openocd/scripts/fpga/xlnx/xc7.cfg \
  -c "init; scan_chain; pld load 0 /home/tim/netv2-base.bit; exit"
```

Note: the modern openocd 0.12 on this unit provides the Series-7 PLD/TAP
definition at `fpga/xlnx/xc7.cfg` (not `cpld/xilinx-xc7.cfg`, which is absent
here). It expects-id `0x03631093` (version-masked); the raw read is
`0x13631093`.

UART boot output was captured on `/dev/ttyAMA0` @ 115200.

## Safety

- Only **rpi5-netv2** (the non-golden 100T dev unit) was touched.
- **rpi3-netv2 (golden) was never contacted.**
- Load was **volatile SRAM only**; SPI flash was never written; no Pi reboot.

## Files

- `console-boot.log` — full BIOS boot capture including read leveling and `Memtest OK`.
- `console-ident.log` — `ident` command output confirming the NeTV2 identity.
- `timing-summary.txt` — post-route design timing summary (WNS +0.893 ns).
