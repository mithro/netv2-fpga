# Building NeTV2 gateware with the open-source toolchain (openXC7)

Phase 2b, goal item (c): *enable the gateware to be built using the open-source
tooling.* This page records what builds today with the fully open-source flow
(yosys -> nextpnr-xilinx -> prjxray, collectively "openXC7"), the exact command
to reproduce it, whether it ran on real hardware, and the honest boundary: what
does **not** build with openXC7 yet and why.

**Bottom line:** a minimal NeTV2 SoC (VexRiscv + UART + LED chaser, no DDR/
video/PCIe) builds end-to-end with openXC7, produces a bitstream, and boots its
LiteX BIOS on `rpi5-netv2`. The complex blocks (DDR3, HDMI, PCIe) do not build
with openXC7 today; the blockers are documented below.

## Toolchain and versions

openXC7 is not one program; it is a set of open tools driven by LiteX's
`litex.build.xilinx.yosys_nextpnr` backend (selected with `--toolchain openxc7`):

| Tool | Version | Source |
|------|---------|--------|
| Yosys (synthesis) | 0.52 (git `fee39a3`) | system `/usr/bin/yosys` |
| nextpnr-xilinx (place & route) | 0.8.2 | openXC7 0.8.2 snap (`nextpnr-xilinx`) |
| prjxray (fasm2frames, xc7frames2bit) | openXC7 0.8.2 snap | `fasm2frames`, `xc7frames2bit`, `bbasm` |
| prjxray-db (Artix-7 bit database) | bundled with the 0.8.2 snap | `.../prjxray-db/artix7` |
| chipdb (nextpnr device db) | prebuilt `xc7a100tfgg484.bin` (158 MB) | `.../openxc7/chipdb` |

These come from the fpgas.online reference repo's installed toolchain
(`/home/tim/github/mithro/fpgas-online-test-designs/.venv/toolchains/openxc7`),
which is what `scripts/setup_toolchains.py` there installs (openXC7 snap 0.8.2 +
a modern Yosys). This is substantially newer than the local
`regymm/openxc7:latest` docker image (Yosys 0.17, snap-era nextpnr), so the
snap-based toolchain was used, not the docker image.

The RISC-V BIOS/firmware is cross-compiled with the system
`riscv64-unknown-elf-gcc` (`/usr/bin`).

### Required environment variables

The LiteX openXC7 backend reads these (see
`litex/build/xilinx/yosys_nextpnr.py`):

```sh
OXROOT=/home/tim/github/mithro/fpgas-online-test-designs/.venv/toolchains/openxc7
export CHIPDB="$OXROOT/chipdb"
export PRJXRAY_DB_DIR="$OXROOT/squashfs-root/opt/nextpnr-xilinx/external/prjxray-db"
export NEXTPNR_XILINX_PYTHON_DIR="$OXROOT/squashfs-root/opt/nextpnr-xilinx/python"
export PATH="$OXROOT/bin:/usr/bin:$PATH"
```

## The minimal SoC that builds: `netv2/targets/blink.py`

The deliverable is `netv2/targets/blink.py` -- the smallest useful NeTV2 SoC:

- **CPU:** VexRiscv (LiteX default), 32-bit wishbone.
- **UART:** LiteX UART @ 115200 (FPGA TX=E14 / RX=E13 -> RPi `/dev/ttyAMA0`).
- **LED chaser:** `LedChaser` on the six `user_led` pins.
- **Memory:** integrated LiteX ROM (128 KiB, holds the BIOS) + 8 KiB integrated
  SRAM + 8 KiB integrated *main RAM* -- **no DDR3**. The BIOS runs entirely from
  on-chip block RAM, so no memory controller is needed.
- **No DDR3, no HDMI/video, no PCIe, no Ethernet.**
- **Clock:** single `sys` domain at 50 MHz from an `S7PLL` fed by the 50 MHz
  oscillator. 50 MHz is conservative and closes timing comfortably.

### Reproduce

```sh
# from repo root, with the environment variables above exported:
uv run python -m netv2.targets.blink --toolchain openxc7 --variant a7-100 --build
```

Outputs land in `build/netv2-blink/gateware/`:

- `kosagi_netv2.bit`  -- the bitstream (~3.8 MB), produced via
  `.fasm` -> `fasm2frames` -> `.frames` -> `xc7frames2bit` -> `.bit`.
- `kosagi_netv2.fasm`, `kosagi_netv2.json` (netlist), `kosagi_netv2.rpt`
  (yosys report), `build_kosagi_netv2.sh` (the exact tool invocations).

It also builds with Vivado for comparison (`--toolchain vivado`).

### Resource usage (a7-100, XC7A100T)

Post-synthesis (yosys) cell counts and nextpnr device utilisation:

| Resource | Used | Available | % |
|----------|------|-----------|---|
| SLICE_LUT | 3447 | 126800 | 2% |
| SLICE_FF  | 1793 | 126800 | 1% |
| CARRY4    | 152  | 15850  | <1% |
| RAMB18E1  | 19   | 270    | 7% |
| RAMB36E1  | 5    | 135    | 3% |
| DSP48E1   | 4    | 240    | 1% |
| PLLE2_ADV | 1    | -      | - |
| BUFGCTRL  | 2    | 32     | 6% |

Timing (nextpnr, `--freq 50`): **PASS**. The `sys` clock
(`main_crg_clkout_buf`) reaches an estimated Fmax of ~91 MHz against the 50 MHz
target; the 50 MHz input clock reaches ~985 MHz. No timing failures.

### Platform fixups needed for openXC7

`blink.py` applies three fixups (only when `--toolchain openxc7`), mirroring the
fpgas.online reference designs:

1. **Device-name dash strip.** litex-boards names the part `xc7a100t-fgg484-2`
   (for Vivado); nextpnr-xilinx's chipdb uses `xc7a100tfgg484` (no dash between
   die and package). `blink.py` rewrites the platform device string.
2. **chipdb symlink.** If `CHIPDB` only carries one spelling of the `.bin`, a
   symlink for the other spelling is created so nextpnr finds it.
3. **`$scopeinfo` strip.** Yosys >= 0.40 emits `$scopeinfo` debug cells that
   nextpnr-xilinx cannot place; a `delete t:$scopeinfo` is inserted into the
   yosys script before the netlist write.

Not needed for this design: **INTERNAL_VREF** (no DDR3 -> no VREF banks), and no
missing I/O timing constraints (single simple clock). Note that openXC7 does
**not** support false-path / async-CDC timing exceptions (the LiteX openXC7
backend explicitly drops them -- `yosys_nextpnr.py`: "false path constraints are
currently not supported by the toolchain"); this is harmless for the
single-clock blink SoC but is a real blocker for the multi-clock designs below.

## Ran on hardware (volatile, rpi5-netv2)

The openXC7 bitstream was loaded **volatile over JTAG** (no SPI flash write) on
`rpi5-netv2` (the non-golden XC7A100T unit, IDCODE `0x13631093`) and confirmed
running:

```sh
# on rpi5-netv2, from ~/netv2:
sudo openocd -s . -f netv2-rpi5-sysfsgpio.cfg \
    -f /usr/share/openocd/scripts/cpld/xilinx-xc7.cfg \
    -c "init; pld load 0 /home/tim/netv2/blink-openxc7.bit; exit"
```

The LiteX BIOS booted on `/dev/ttyAMA0` @ 115200:

```
BIOS built on Sep  6 2026 08:21:59
BIOS CRC passed (2e4ecd75)
CPU:      VexRiscv @ 50MHz
ROM:      128.0KiB
SRAM:     8.0KiB
MAIN RAM: 8.0KiB
Memtest at 0x40000000 (8.0KiB)... Memtest OK
  Write speed: 77.2MiB/s   Read speed: 40.1MiB/s
litex> ident
Ident: NeTV2 blink SoC (openXC7 minimal) 2026-09-06 08:21:57
```

The `ident` string confirms it is the openXC7-built blink SoC; the on-chip
memtest passes; the `leds` BIOS command (the LED chaser CSR) is present. This is
an open-tooling bitstream running on real NeTV2 hardware.

**Safety:** volatile JTAG load only, no SPI flash write, no power cycle; the
golden unit `rpi3-netv2` was never touched.

## Boundary: what does NOT build with openXC7 today

The complex NeTV2 blocks do not build with openXC7 0.8.2. The DDR case was
tested empirically here; video and PCIe are characterised from their primitives
plus the known nextpnr-xilinx limitations.

### DDR3 (empirically tested -- fails in placement)

The modern DDR target (`netv2/targets/base.py`, a thin wrapper over
`litex_boards.targets.kosagi_netv2.BaseSoC`: VexRiscv + LiteDRAM `s7ddrphy` +
DDR3 @ 100 MHz) is hardwired to Vivado -- neither it nor the upstream target
threads `--toolchain` into the `Platform` constructor, so a bare
`--toolchain openxc7` on `base.py` just fails with "Unable to find Vivado". To
attempt the *same* DDR SoC on openXC7, a small probe forces the platform
toolchain to openxc7:
`docs/testing/reports/2026-09-phase2b-openxc7/ddr_openxc7_probe.py`.

Result with openXC7 (Yosys 0.52 + nextpnr-xilinx 0.8.2, a7-100):

- **Synthesis (yosys): SUCCEEDS.** 12270 cells, including the full DDR PHY
  primitive set: 32x `ISERDESE2`, 65x `OSERDESE2`, 32x `IDELAYE2`, 1x
  `IDELAYCTRL`, 1x `PLLE2_ADV`, and 256x `RAM256X1S` (LiteDRAM's data memory as
  distributed RAM).
- **Place & route (nextpnr-xilinx): FAILS in placement.** The DDR SERDES/IO
  primitives themselves placed by constraint (device util reached
  `ISERDESE2 32/300`, `OSERDESE2 65/300`, `IDELAYE2 32/300`, `IDELAYCTRL 1/6`,
  `SLICE_LUT 9076/126800`), then placement aborts:

  ```
  Info: Placed 330 cells based on constraints.
  ERROR: Unable to place cell 'data_mem_grain0.0.0.genblk1.genblk1[0].genblk1.slice',
         no Bels remaining of type 'RAM256X1S'
  ```

  i.e. nextpnr-xilinx cannot place LiteDRAM's 256 `RAM256X1S` distributed-RAM
  cells. The fpgas.online reference works around a related distributed-RAM issue
  with `-nodram` (force block RAM), but that only moves the wall.

- **Deeper blockers past placement** (documented, not reached here because
  placement fails first): nextpnr-xilinx
  [#143](https://github.com/gatecat/nextpnr-xilinx/issues/143) (ISERDESE2
  fed directly from a pad -- exactly the DQ/DQS capture path), the lack of
  false-path / async-CDC timing exceptions in the openXC7 backend (the DDR
  design crosses `sys` <-> `sys4x` <-> `idelay` domains), MMCME2_ADV/PLL lock
  quirks, and OSERDESE2 10-bit modes. LiteDRAM memtest has **never** passed with
  an openXC7 bitstream on the NeTV2 (per fpgas.online's attempts); root cause
  is still open upstream.

**Conclusion for DDR3:** not buildable with openXC7 today. First hard wall is
`RAM256X1S` placement; even past it the SERDES-from-pad routing and async-CDC
timing blockers remain unsolved.

### Video / HDMI (boundary from primitives + known issues)

The HDMI-in path (`netv2/targets/hdmi_in.py`) captures three TMDS channels with
`ISERDESE2` clocked directly from the input pads at the pixel/serial rate, plus
`MMCME2_ADV` for the recovered-clock PLL and cross-domain CDC. This is the exact
failure mode of nextpnr-xilinx #143 (ISERDESE2-from-pad routing) and #79
(MMCME2_ADV lock), and it relies on async-CDC timing exceptions the openXC7
backend drops. Not buildable with openXC7 today.

### PCIe (boundary from primitives + known issues)

The PCIe path (`netv2/targets/pcie.py`, LitePCIe) instantiates Artix-7 `GTP`
transceivers. nextpnr-xilinx's GTP support is minimal -- the fpgas.online PCIe
experiment had to patch GTP site types in the chipdb and still gated the build
behind Vivado. Not buildable with openXC7 today.

### Summary

| Design | openXC7 result | Blocker |
|--------|----------------|---------|
| blink (CPU+UART+LEDs, no DDR/video/PCIe) | **builds + runs on HW** | -- |
| DDR3 base SoC | fails (placement) | `RAM256X1S` placement; then ISERDESE2-from-pad (#143), async-CDC exceptions |
| HDMI-in / video | not buildable | ISERDESE2-from-pad (#143), MMCME2_ADV (#79), CDC exceptions |
| PCIe | not buildable | GTP transceiver support in nextpnr-xilinx |

## Files

- `netv2/targets/blink.py` -- the minimal openXC7 SoC (this deliverable).
- `docs/testing/reports/2026-09-phase2b-openxc7/` -- build logs, hardware
  evidence, and `ddr_openxc7_probe.py` (the DDR boundary probe).
