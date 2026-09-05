# Phase 2b (c): open-source toolchain (openXC7) build report

Date: 2026-09-06 · Branch: `phase2b-openxc7`

Goal item (c): *enable the gateware to be built using the open-source tooling.*
This report is the evidence behind `docs/current/openxc7-build.md`.

## Result

- **A minimal NeTV2 SoC builds end-to-end with openXC7 and runs on hardware.**
  `netv2/targets/blink.py` (VexRiscv + UART + LED chaser, no DDR/video/PCIe)
  synthesises with Yosys 0.52, places & routes with nextpnr-xilinx 0.8.2, and a
  bitstream is emitted via prjxray (`fasm2frames` -> `xc7frames2bit`).
- **It boots on `rpi5-netv2`** (volatile JTAG load, no flash): LiteX BIOS banner,
  on-chip memtest OK, and `ident` returns "NeTV2 blink SoC (openXC7 minimal)".
- **DDR3 does not build with openXC7:** synthesis succeeds but nextpnr-xilinx
  placement fails on LiteDRAM's `RAM256X1S` distributed RAM; deeper SERDES/CDC
  blockers lie past that. HDMI/video and PCIe are also outside the openXC7
  boundary (ISERDESE2-from-pad, MMCME2_ADV, GTP).

## Toolchain

| Tool | Version |
|------|---------|
| Yosys | 0.52 (git `fee39a3`), system `/usr/bin/yosys` |
| nextpnr-xilinx | 0.8.2 (openXC7 0.8.2 snap) |
| prjxray + prjxray-db | openXC7 0.8.2 snap bundle |
| RISC-V GCC | system `riscv64-unknown-elf-gcc` |

Toolchain root:
`/home/tim/github/mithro/fpgas-online-test-designs/.venv/toolchains/openxc7`
(installed by that repo's `scripts/setup_toolchains.py`). The local
`regymm/openxc7:latest` docker image (Yosys 0.17) was **not** used -- it is far
older than the snap toolchain.

## Reproduce (from repo root)

```sh
OXROOT=/home/tim/github/mithro/fpgas-online-test-designs/.venv/toolchains/openxc7
export CHIPDB="$OXROOT/chipdb"
export PRJXRAY_DB_DIR="$OXROOT/squashfs-root/opt/nextpnr-xilinx/external/prjxray-db"
export NEXTPNR_XILINX_PYTHON_DIR="$OXROOT/squashfs-root/opt/nextpnr-xilinx/python"
export PATH="$OXROOT/bin:/usr/bin:$PATH"

uv run python -m netv2.targets.blink --toolchain openxc7 --variant a7-100 --build
# -> build/netv2-blink/gateware/kosagi_netv2.bit  (~3.8 MB)
```

## Resource usage (blink, a7-100 / XC7A100T)

| Resource | Used | Avail | % |
|----------|------|-------|---|
| SLICE_LUT | 3447 | 126800 | 2% |
| SLICE_FF | 1793 | 126800 | 1% |
| CARRY4 | 152 | 15850 | <1% |
| RAMB18E1 | 19 | 270 | 7% |
| RAMB36E1 | 5 | 135 | 3% |
| DSP48E1 | 4 | 240 | 1% |
| PLLE2_ADV | 1 | - | - |
| BUFGCTRL | 2 | 32 | 6% |

Timing: PASS at 50 MHz (`sys` Fmax ~91 MHz). See
`blink-openxc7-build-summary.txt`.

## Hardware run (rpi5-netv2, volatile)

IDCODE read: `0x13631093` (XC7A100T rev 1, non-golden unit). Loaded with:

```sh
sudo openocd -s . -f netv2-rpi5-sysfsgpio.cfg \
    -f /usr/share/openocd/scripts/cpld/xilinx-xc7.cfg \
    -c "init; pld load 0 /home/tim/netv2/blink-openxc7.bit; exit"
```

BIOS output (full capture in `blink-rpi5-bios-banner.txt`, `blink-rpi5-help.txt`):

```
BIOS built on Sep  6 2026 08:21:59 · BIOS CRC passed (2e4ecd75)
CPU: VexRiscv @ 50MHz · ROM 128KiB · SRAM 8KiB · MAIN RAM 8KiB
Memtest at 0x40000000 (8.0KiB)... Memtest OK  (W 77.2 MiB/s, R 40.1 MiB/s)
litex> ident
Ident: NeTV2 blink SoC (openXC7 minimal) 2026-09-06 08:21:57
```

Safety: volatile JTAG load only, **no SPI flash write, no power cycle**; the
golden unit `rpi3-netv2` was **not touched**.

## DDR3 boundary probe

`ddr_openxc7_probe.py` forces the DDR base SoC's platform onto openXC7 (the
modern targets are hardwired to Vivado). Detail in
`ddr-openxc7-boundary-summary.txt`:

- yosys: **succeeds** -- 12270 cells incl. 32 ISERDESE2, 65 OSERDESE2, 32
  IDELAYE2, 1 IDELAYCTRL, 256 RAM256X1S.
- nextpnr-xilinx: **fails in placement** --
  `ERROR: Unable to place cell 'data_mem_grain0...', no Bels remaining of type 'RAM256X1S'`.

## Files in this directory

- `blink-rpi5-bios-banner.txt` -- full BIOS boot banner from hardware.
- `blink-rpi5-help.txt` -- `litex>` prompt `help` output (shows `leds` CSR).
- `blink-openxc7-build-summary.txt` -- yosys cells, nextpnr util, timing, build script.
- `ddr-openxc7-boundary-summary.txt` -- DDR probe synth stats + placement error.
- `ddr_openxc7_probe.py` -- the DDR-on-openXC7 boundary probe script.

Full build logs (`build/blink-openxc7-build.log`,
`build/ddr-openxc7-boundary.log`) are gitignored; the summaries above are the
committed excerpts.
