# NeTV2 hardware as the 2019 gateware saw it

This page describes the NeTV2 board from the point of view of the shipped
gateware: which pins the design claimed, what electrical standard it used them
at, and which board features it ignored. Everything here is read out of the
`_io` list and the `Platform` class in `legacy/netv2mvp.py`, which is the only
machine-readable pinout in the tree — there is no board schematic or XDC file
in this repository. Where a fact comes from somewhere else it is cited there.
Line numbers given for `legacy/deps/litevideo/` refer to litevideo commit
`3bc5a24` ("add delay alignment feature", 2019-09-13), the version the 2019
design was built against.

Companion pages: [gateware.md](gateware.md) for what the logic did with these
pins, [clocking.md](clocking.md) for the CMT tree, and
[boot-and-flash.md](boot-and-flash.md) for the SPI NOR layout.

## 1. FPGA

| Property | Value | Source |
|---|---|---|
| Family | Xilinx Artix-7 | `legacy/netv2mvp.py:222` |
| Part string | `xc7a<part>t-fgg484-2` | `legacy/netv2mvp.py:222` |
| Package | FGG484 | `legacy/netv2mvp.py:222` |
| Speed grade | `-2` (fixed, not a build option) | `legacy/netv2mvp.py:222` |
| Selectable sizes | `35`, `50`, `100` accepted on the command line | `legacy/netv2mvp.py:1279-1281` |
| Sizes actually built | 35T and 100T (`user-35.bit`, `user-100.bit`) | `legacy/production-images/` |
| Configuration voltage | 3.3 V, `CFGBVS VCCO` | `legacy/netv2mvp.py:265-268` |
| Configuration rate | 66 MHz, SPI x2 | `legacy/netv2mvp.py:269-272` |

`-p 50` is accepted by the argument parser but no 50T image was ever shipped,
and `VideoOverlaySoC` treats any part that is not `"35"` as a 100T for the
purpose of the board-identification LED (`legacy/netv2mvp.py:1184-1190`).

The field update script identifies the board by JTAG IDCODE before choosing a
bitstream:

| IDCODE read by OpenOCD | Device | Bitstream chosen | Source |
|---|---|---|---|
| `0x0362d093` | 35T | `user35-<cable>.bit`, `bscan_spi_xc7a35t.bit` | `legacy/testing-images/testing-fpga.sh:61-64,78-79` |
| `0x13631093` | 100T | `user100-<cable>.bit`, `bscan_spi_xc7a100t.bit` | `legacy/testing-images/testing-fpga.sh:65-68,82-83` |
| anything else | abort | — | `legacy/testing-images/testing-fpga.sh:69-73` |

Note that the vendor script matches the 100T IDCODE with the revision nibble
already set to `1` (`0x13631093`) rather than the base value `0x03631093`, and
matches it exactly. A 100T of a different silicon revision would fail the check
and the script would refuse to update. The 35T entry uses the base value
`0x0362d093`. Any modern tooling should mask off the top nibble instead of
comparing the whole word.

The programmer object is configured for a `n25q128-3.3v-spi-x1_x2_x4` flash
(`legacy/netv2mvp.py:286`), a 128 Mbit (16 MB) part, while the SoC maps only
8 MB (`legacy/netv2mvp.py:625-626`) and `write_cfgmem` is told `-size 64`
(64 Mbit = 8 MB, `legacy/netv2mvp.py:279-281`). The 8 MB figure is the one the
firmware and the flash layout use; the Vivado programmer string is only used
for a JTAG-attached Vivado flash write, which is not the shipped update path.

## 2. DDR3

Two Samsung K4B2G1646F devices in a 32-bit bus, 512 MB total. The module model
is selected in the SoC, not the platform (`legacy/netv2mvp.py:582`):

```python
sdram_module = K4B2G1646FBCK0(self.clk_freq, "1:4", speedgrade='1600')
```

Pads are declared at `legacy/netv2mvp.py:77-105`:

| Signal | Pins | I/O standard |
|---|---|---|
| `a` (14) | U6 V4 W5 V5 AA1 Y2 AB1 AB3 AB2 Y3 W6 Y1 V2 AA3 | SSTL15_R |
| `ba` (3) | U5 W4 V7 | SSTL15_R |
| `ras_n` / `cas_n` / `we_n` | Y9 / Y7 / V8 | SSTL15_R |
| `dm` (4) | G1 H4 M5 L3 | SSTL15_R |
| `dq` (32) | C2 F1 B1 F3 A1 D2 B2 E2 / J5 H3 K1 H2 J1 G2 H5 G3 / N2 M6 P1 N5 P2 N4 R1 P6 / K3 M2 K4 M3 J6 L5 J4 K6 | SSTL15_R, `IN_TERM=UNTUNED_SPLIT_40` |
| `dqs_p` (4) | E1 K2 P5 M1 | DIFF_SSTL15_R, `IN_TERM=UNTUNED_SPLIT_40` |
| `dqs_n` (4) | D1 J2 P4 L1 | DIFF_SSTL15_R, `IN_TERM=UNTUNED_SPLIT_40` |
| `clk_p` / `clk_n` | R3 / R2 | DIFF_SSTL15_R |
| `cke` / `odt` / `cs_n` | Y8 / W9 / V9 | SSTL15_R |
| `reset_n` | AB5 | **LVCMOS15** |

`SLEW=FAST` is applied to the whole group (`legacy/netv2mvp.py:104`). The
`_R` suffix on the SSTL15 standards selects the Artix-7 "reduced drive"
variants. `reset_n` is deliberately LVCMOS15 rather than SSTL15_R, matching the
DDR3 RESET# input, which is a CMOS-level pin.

Electrical settings are applied to the PHY rather than the pads
(`legacy/netv2mvp.py:580`): `rtt_nom='20ohm'`, `rtt_wr='disabled'`,
`ron='40ohm'`. The four DQS pairs get a hand-written `create_clock` of 2.5 ns
each so the toolchain can time the read path (`legacy/netv2mvp.py:972-977`).

## 3. SPI NOR

8 MB, on the FPGA's dedicated configuration pins. The configuration clock is
not a normal pin — it is reached through the `STARTUPE2` primitive
(`legacy/netv2mvp.py:609-613`), which is why the platform declares no `clk`
subsignal. Two alternative pad groups are declared
(`legacy/netv2mvp.py:204-216`) and the SoC picks one by name:

| Group | Subsignal | Pins |
|---|---|---|
| `spiflash_1x` | `cs_n`, `mosi`, `miso`, `wp`, `hold` | T19, P22, R22, P21, R21 |
| `spiflash_4x` | `cs_n`, `dq[3:0]` | T19, P22 R22 P21 R21 |

Both are `LVCMOS33`. The shipped design uses `spiflash_1x`, the default of the
`BaseSoC` constructor (`legacy/netv2mvp.py:553`), with 8 dummy cycles; the
`spiflash_4x` entry carries the comment that its 12 dummy cycles are "almost
certainly wrong" (`legacy/netv2mvp.py:614-617`). A comment at
`legacy/netv2mvp.py:263-264` records why quad mode was never enabled: the QE
bit in the NOR status register has to be set once out of band, and the OpenOCD
fork used in the field cannot do it.

Bitstream loading from NOR uses SPI x2 at 66 MHz
(`legacy/netv2mvp.py:269-272`); the `.bin` for the flash is produced by
`write_cfgmem -interface spix2 -size 64` (`legacy/netv2mvp.py:279-281`).

## 4. Ethernet (RMII PHY)

An external 100Base-TX PHY on an RMII interface, `LVCMOS33` throughout
(`legacy/netv2mvp.py:187-202`):

| Signal | Pins |
|---|---|
| `rmii_eth_clocks.ref_clk` | D17 |
| `rst_n` | F16 |
| `rx_data[1:0]` | A20 B18 |
| `crs_dv` | C20 |
| `rx_er` | B20 |
| `tx_en` | A19 |
| `tx_data[1:0]` | C18 C19 |
| `mdc` / `mdio` | F14 / F13 |
| `int_n` | D21 |

`ref_clk` is an input pad to the FPGA but the design does not clock the MAC
from it: `LiteEthPHYRMII` is wrapped into the SoC's own 50 MHz `eth` domain
(`legacy/netv2mvp.py:1208-1215`), which is derived from the 50 MHz oscillator
inside the CRG (`legacy/netv2mvp.py:407-409,443`). See
[clocking.md](clocking.md).

## 5. HDMI

Four HDMI-class ports are wired to the FPGA: two inputs and two outputs.

| Port | `_io` entry | Lines | Role |
|---|---|---|---|
| RX0 | `hdmi_in` 0 | 137-149 | **input0** — the source, the video that passes through |
| OV0 | `hdmi_in` 1 | 230-242 (`pcb`) / 246-258 (`cable`) | **input1** — the overlay from the Raspberry Pi |
| TX0 | `hdmi_out` 0 | 151-160 | the composited output to the display |
| TX1 | `hdmi_out` 1 | 162-171 | internal HDMI-D port; **never requested by any target** |

### 5.1 input0 (RX0) and output0 (TX0)

```
hdmi_in 0 (netv2mvp.py:137-149)          hdmi_out 0 (netv2mvp.py:151-160)
  clk_p   L19  TMDS_33  Inverted           clk_p   W19  TMDS_33  Inverted
  clk_n   L20  TMDS_33  Inverted           clk_n   W20  TMDS_33  Inverted
  data0_p K21  TMDS_33  Inverted           data0_p W21  TMDS_33
  data0_n K22  TMDS_33  Inverted           data0_n W22  TMDS_33
  data1_p J20  TMDS_33  Inverted           data1_p U20  TMDS_33
  data1_n J21  TMDS_33  Inverted           data1_n V20  TMDS_33
  data2_p J22  TMDS_33  Inverted           data2_p T21  TMDS_33
  data2_n H22  TMDS_33  Inverted           data2_n U21  TMDS_33
  scl     T18  LVCMOS33
  sda     V18  LVCMOS33
  hpd_notif U17 LVCMOS33 Inverted   # HDMI_HPD_LL_N, active low
```

`Inverted()` in this codebase is not a toolchain property: it sets a Python
attribute on the pad object and emits nothing into the XDC
(`legacy/deps/litex/litex/build/generic_platform.py:54,187-194`). Consumers
have to honour it themselves. Two do — the input deserialiser inverts the
recovered 10-bit character
(`legacy/deps/litevideo/litevideo/input/datacapture.py:201-204`) and the output
serialiser inverts the outgoing character
(`legacy/deps/litevideo/litevideo/output/hdmi/s7.py:24-27`) — so a p/n swap on
the PCB is corrected in logic rather than by re-routing. Two consumers do
**not**: `S7Clocking` instantiates the clock IBUFDS straight from `clk_p`/
`clk_n` without checking the marker
(`legacy/deps/litevideo/litevideo/input/clocking.py:125`), and
`hdcp.hpd.eq(hdmi_in0_pads.hpd_notif)` (`legacy/netv2mvp.py:1056`) reads the
raw pad. On the clock pair a swap only inverts the phase of a recovered clock,
which the phase aligner absorbs, so the marker is effectively decorative there.

`scl`/`sda` on input0 feed two things: the litevideo `EDID` core, instantiated
automatically because the pads have an `scl` attribute
(`legacy/deps/litevideo/litevideo/input/__init__.py:50-51`), and the `I2Csnoop`
block, which watches
the same wires at address 0x74 for HDCP key traffic
(`legacy/netv2mvp.py:631-652`).

### 5.2 input1 (OV0): `pcb` versus `cable`

The overlay input's pin assignment is fixed but its per-pair inversion depends
on how the Raspberry Pi is connected. `Platform.__init__` takes
`cable="pcb"|"cable"` and appends one of two `hdmi_in` 1 blocks
(`legacy/netv2mvp.py:226-259`). `pcb` is the default
(`legacy/netv2mvp.py:221`, `legacy/netv2mvp.py:1288-1290,1293`) and is what the
board-to-board M2M jumper needs; `cable` is for a real HDMI cable into the
overlay port.

| Subsignal | Pin | I/O standard | `pcb` (lines 230-242) | `cable` (lines 246-258) |
|---|---|---|---|---|
| `clk_p` | Y18 | TMDS_33 | — | `Inverted()` |
| `clk_n` | Y19 | TMDS_33 | — | `Inverted()` |
| `data0_p` | AA18 | TMDS_33 | `Inverted()` | — |
| `data0_n` | AB18 | TMDS_33 | `Inverted()` | — |
| `data1_p` | AA19 | TMDS_33 | — | `Inverted()` |
| `data1_n` | AB20 | TMDS_33 | — | `Inverted()` |
| `data2_p` | AB21 | TMDS_33 | — | `Inverted()` |
| `data2_n` | AB22 | TMDS_33 | — | `Inverted()` |
| `scl` | W17 | LVCMOS33 | `Inverted()` | `Inverted()` |
| `sda` | R17 | LVCMOS33 | — | — |

The two variants are exact complements on all four TMDS pairs; only `scl`
(inverted in both) and `sda` (inverted in neither) are common. In other words,
the M2M jumper physically swaps p/n on the clock, data1 and data2 pairs
relative to a straight HDMI cable, and swaps data0 the other way. The comment
above the `pcb` block says "All pairs inverted to simplify/clean-up routing
between the two boards" (`legacy/netv2mvp.py:228-229`); taken literally that
describes the jumper's routing, not the `Inverted()` markers in that block,
only one of which is set.

Because the marker only affects `data*` (through the deserialiser) and not the
clock, building the wrong variant produces a locked but garbled overlay rather
than no lock at all.

**Per host**: `rpi3-netv2`, the reference unit, uses the M2M jumper and
therefore `cable="pcb"`. A Raspberry Pi 5 has only micro-HDMI connectors and
must reach the overlay port through a cable, so it needs the `cable` variant
(`docs/superpowers/specs/2026-09-05-netv2-modernisation-design.md:71`).

### 5.3 Hot-plug, DDC override and CEC

| Pad | Pin | Meaning | Declared | Used by gateware |
|---|---|---|---|---|
| `hdmi_in0.hpd_notif` | U17 | HDMI_HPD_LL_N, HPD state of the TX0 sink, active low | 147 | yes, into the HDCP block (1056) |
| `hdmi_sda_over_up` | G20 | pull DDC SDA up | 173 | yes, driven to 0 (875) |
| `hdmi_sda_over_dn` | F20 | pull DDC SDA down; must be mutually exclusive with `_up` | 174 | yes, driven to 0 (876) |
| `hdmi_rx0_forceunplug` | M22 | force an HPD event on the RX0/TX0 path | 176 | yes, driven by the `hdcp.hpd_ena` CSR (1060) |
| `hdmi_rx0_forceplug` | N22 | force plug; must be mutually exclusive with the above | 177 | **no** |
| `hdmi_tx1_hpd_n` | U18 | HPD of the internal HDMI-D port | 179 | **no** |
| `hdmi_ov0_hpd_n` | V17 | overlay input plugged-in detect | 185 | **no** |
| `hdmi_tx1_cec` | P17 | CEC on the tx1/rx1 path | 181 | **no** |
| `hdmi_tx0_cec` | P20 | CEC on the tx0/rx0 path | 182 | **no** |
| `hdmi_ov0_cec` | P19 | CEC dedicated to the overlay input | 184 | **no** |

The DDC override pair is tied low, i.e. the design never drives the source's
DDC line; EDID and HDCP DDC traffic passes through to the sink and is only
observed (`legacy/netv2mvp.py:873-877`). `hdmi_rx0_forceunplug` is the only
means the design has of re-triggering an HDCP authentication: the firmware
pulses `hdcp.hpd_ena` and the source re-reads the KSVs.

The absence of `hdmi_ov0_hpd_n` from the gateware is worth noting: the design
cannot tell whether the overlay cable is plugged in, only whether input1's
clock recovery has locked.

## 6. PCIe

Three alternative pad groups for the x4 card edge
(`legacy/netv2mvp.py:107-135`), sharing a reset and a reference clock:

| Group | rst_n | clk_p/n | rx_p | rx_n | tx_p | tx_n |
|---|---|---|---|---|---|---|
| `pcie_x1` | E18 | F10 / E10 | D11 | C11 | D5 | C5 |
| `pcie_x2` | E18 | F10 / E10 | D11 B10 | C11 A10 | D5 B6 | C5 A6 |
| `pcie_x4` | E18 | F10 / E10 | D11 B10 D9 B8 | C11 A10 C9 A8 | D5 B6 D7 B4 | C5 A6 C7 A4 |

Only `rst_n` carries an `IOStandard` (`LVCMOS33`); the differential pairs are
left to the GTP transceiver defaults. **None of these groups is requested by
any target in `legacy/netv2mvp.py`.** The `main()` argument parser accepts
`-t pcie` (`legacy/netv2mvp.py:1282-1284`) and would call
`soc.generate_software_header()` (`legacy/netv2mvp.py:1302-1303`), but there is
no `pcie` branch that builds an SoC — the `if/elif` at
`legacy/netv2mvp.py:1294-1297` only handles `base` and `video_overlay`, so
`-t pcie` crashes with an undefined `soc`. The PCIe endpoint in this tree is
vestigial.

### The "hax" pins

The second UART, `serial` 1, is on B17/A18 and the comments label them
"hax 7" and "hax 8" (`legacy/netv2mvp.py:71-75`). These are debug-header pins,
not PCIe pins. They were intended for a UART Wishbone bridge, which is present
but commented out (`legacy/netv2mvp.py:1231-1236`), so `serial` 1 is never
requested either.

## 7. Raspberry Pi connection

The board sits on a riser above a Raspberry Pi and uses the Pi's 40-pin header
for two things: JTAG configuration and the SoC console.

| Function | FPGA side | Pi side |
|---|---|---|
| JTAG TCK | dedicated config pin | GPIO 4 |
| JTAG TMS | dedicated config pin | GPIO 17 |
| JTAG TDI | dedicated config pin | GPIO 27 |
| JTAG TDO | dedicated config pin | GPIO 22 |
| JTAG SRST | PROGRAM_B | GPIO 24 |
| UART: FPGA TX -> Pi RX | E14 (`serial` 0 `tx`) | GPIO 15 (RXD) |
| UART: FPGA RX <- Pi TX | E13 (`serial` 0 `rx`) | GPIO 14 (TXD) |

The FPGA pins come from `legacy/netv2mvp.py:65-69`; the GPIO numbers are not
recorded anywhere in this repository (the OpenOCD configs live in the separate
`netv2mvp-scripts` repository, which `legacy/testing-images/testing-fpga.sh:9`
expects at `/home/pi/code/netv2mvp-scripts`) and are taken from
`docs/superpowers/specs/2026-09-05-netv2-modernisation-design.md:78-80`. The
console device is `/dev/ttyS0` on a Pi 3B+ and `/dev/ttyAMA0` on a Pi 5.

The JTAG pins are the FPGA's dedicated configuration pins and so do not appear
in `_io` at all; they are not assignable.

Mechanically the riser is a 40-pin header board, which fits any Pi with the
40-pin GPIO layout (Pi 2 B onwards, including 3B, 3B+, 4 and 5). The reference
unit is a Pi 3B+. What does *not* carry over to a Pi 5 is the overlay video
link: the M2M jumper mates a full-size HDMI connector on the Pi to the overlay
port, and a Pi 5 has only micro-HDMI, so a Pi 5 must use a cable and the
`cable` platform variant (section 5.2).

## 8. LEDs, fan and clock

| Pad | Pin | Driven by | Meaning |
|---|---|---|---|
| `fpga_led0` | M21 | `sys_led ^ pcie_led` (`legacy/netv2mvp.py:596`) | TX0 green — blinks at `sys_counter[26]`, about 0.56 Hz at 75 MHz (`legacy/netv2mvp.py:604-606`); the heartbeat |
| `fpga_led1` | N20 | constant 0 (`legacy/netv2mvp.py:597`) | TX0 red — never lit |
| `fpga_led2` | L21 | `hdmi_in0.clocking.locked` (`legacy/netv2mvp.py:1181`) | RX0 green — input0 MMCM locked |
| `fpga_led3` | AA21 | constant 0 (`legacy/netv2mvp.py:1182`) | RX0 red — never lit |
| `fpga_led4` | R19 | build-time constant (`legacy/netv2mvp.py:1185-1190`) | OV0 red — lit on a 100T build |
| `fpga_led5` | M16 | build-time constant (`legacy/netv2mvp.py:1185-1190`) | OV0 green — lit on a 35T build |
| `fan_pwm` | L14 | constant 1 (`legacy/netv2mvp.py:600`) | fan permanently on |

Pads are declared at `legacy/netv2mvp.py:57-63`, all `LVCMOS33`. The six LEDs
are three bicolour indicators labelled TX0, RX0 and OV0 in the comments. Only
one of them, RX0 green, actually reports a runtime condition; the OV0 pair is a
factory aid, described in the comment at `legacy/netv2mvp.py:1184` as a way to
read the FPGA part number off a board whose FPGA is hidden under a heatsink.
Despite the label, the OV0 LEDs say nothing about the overlay input.

`pcie_led` is declared (`legacy/netv2mvp.py:595`) and XORed into `fpga_led0`
but never driven, so it stays at 0.

The single board clock is a 50 MHz oscillator on J19, `LVCMOS33`
(`legacy/netv2mvp.py:55`), buffered through a BUFG before it reaches any
PLL or MMCM (`legacy/netv2mvp.py:339-341`) and given a hand-written
`create_clock -period 20.0` (`legacy/netv2mvp.py:929-930`).

## 9. SD card

There is an SD card slot on the board (see
`docs/superpowers/specs/2026-09-05-netv2-modernisation-design.md:77-78`), but
**no SD pads are declared anywhere in `legacy/netv2mvp.py`**. A search of the
whole `legacy/` tree for `sdcard`, `sdio` or `sd_card` finds nothing outside an
unrelated migen platform file. The 2019 gateware could not use the slot; its
pinout is not recorded in this repository and would have to be recovered from
the board schematic before an SD controller could be added.

## 10. What is on the board that the gateware never used

Every `_io` entry that no target requests, i.e. that consumes a pin assignment
in the design database but no logic:

| Entry | Lines | Note |
|---|---|---|
| `serial` 1 (B17/A18, "hax 7/8") | 71-75 | for the UART Wishbone bridge, commented out at 1231-1236 |
| `pcie_x1` / `pcie_x2` / `pcie_x4` | 107-135 | no target instantiates a PCIe endpoint; `-t pcie` does not build |
| `hdmi_out` 1 (internal HDMI-D) | 162-171 | the second output is dark |
| `hdmi_rx0_forceplug` | 177 | only `forceunplug` is driven |
| `hdmi_tx1_hpd_n` | 179 | |
| `hdmi_ov0_hpd_n` | 185 | no overlay plug detect |
| `hdmi_tx1_cec`, `hdmi_tx0_cec`, `hdmi_ov0_cec` | 181-184 | no CEC engine at all |
| `spiflash_4x` | 204-208 | declared but `spiflash_1x` is the default and the only one used |

Plus the SD slot, which is not even declared (section 9), and the second HDMI
input path's audio: the design decodes TERC4 islands only far enough to derive
DE and count packets (see [gateware.md](gateware.md)); there is no audio
extraction or injection.
