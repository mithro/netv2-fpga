# NeTV2 modernisation: design

Status: v2, 2026-09-05 (v1 reviewed for completeness and technical feasibility;
this version incorporates both reviews). Author: Claude (Fable 5.1) working for
Tim Ansell (mithro).

## 1. Goal

Bring the Alphamax/Kosagi NeTV2 code base back to a working, buildable state on
current software, then extend it, and prove every step on real hardware:

(a) All existing software runs on current Raspberry Pi OS / Debian (trixie, with
    an eye on sid) on both a Raspberry Pi 3B+ and a Raspberry Pi 5.
(b) The gateware builds on the latest LiteX release with a current Python and
    the latest installed Vivado.
(c) The gateware also builds with the open-source Xilinx 7-series flow (openXC7:
    Yosys, nextpnr-xilinx, Project X-Ray), as far as that flow can carry it,
    with every gap documented and measured.
(d) The gateware gains: a PCIe endpoint usable from the Pi 5, HDMI audio
    embedding and de-embedding, and control over the NeTV2's own Ethernet port.

Everything is done on forks under the `mithro` GitHub account in small commits,
reviewed by sub-agents from several directions, with documentation of how the
system worked originally, how it works now, and how it was tested.

## 2. Assumptions and decisions

The user asked to be questioned first and then left me to work independently.
The questions I raised are answered here with defaults; later decisions forced
by review are appended. Each is reversible; **risky** marks where a wrong guess
costs the most.

| # | Topic | Decision |
|---|-------|----------|
| 1 | LiteX-family deps whose fork network `mithro` already forks | AlphamaxMedia branches pushed into the existing `mithro/*` forks as `alphamax-<branch>` branches (done 2026-09-05). Modern build uses upstream releases, not these forks. |
| 2 | Home for new work | `mithro/netv2-fpga`. `master` kept as the pristine AlphamaxMedia master; integration branch `modern`; feature branches merged into `modern` via PRs on the fork. |
| 3 | Fork scope | All 23 org repos forked or branch-archived under `mithro` (done). |
| 4 | Test suite repo | Creating a new GitHub repo was blocked by the permission classifier. The ten64 suite (fetched as remote `ten64-testsuite/main` in this checkout) is merged into `mithro/netv2-fpga` under `tests/netv2test/` as a git subtree with history. The user can split it out later. |
| 5 | ten64 `~/local/netv2` notes | Folded into `docs/` (Pi 5 programming notes). |
| 6 | **risky** `rpi3-netv2` golden unit | Never re-imaged, never SPI-flashed, never power-cycled by me. Volatile JTAG loads only, stock bitstream reloaded after every run. A netbooting fpgas.online Pi 3B+ node is the modern-OS Pi 3 target once access is sorted out. |
| 7 | Netboot nodes | Unknown access path (tweed host key changed). Treated as a later-phase dependency; infra repos are read-only. |
| 8 | Reboots and power cycling | Allowed for `rpi5-netv2` and netboot nodes. Never for `rpi3-netv2`. |
| 9 | Pi 5 PCIe cabling | Assumed connected (x1 adapter to the x4 edge); verified in phase 6a with a PCIe bitstream. |
| 10 | HDMI test rig | Only `rpi3-netv2` has capture (MS2109) and a source (`rpiz-3`). Pi 5 covers JTAG, UART, DDR, Ethernet, PCIe, HDMI lock via console, and HDMI output content via `frame_crc` (decision 28). |
| 11 | NeTV2 RJ45 cabling | The rpi3 rig's NeTV2 Ethernet is uncabled (suite T90 gap list). The rpi5 unit is unknown. Phase 8 checks link state first; if uncabled the report asks the user to cable one unit. |
| 12 | HDMI audio scope (revised by review) | Staged: (1) **diagnose** why the baseline T23 hears silence, since the original already forwards data islands unchanged (section 3); (2) **extract**: decode Audio Sample and ACR packets from input0 into a DDR ring for the host; (3) **inject, self-timed**: generate audio islands into the output when the NeTV2 is the HDMI source (no input0, phase 6b output clock); (4) **inject into the passthrough stream**, which requires stripping the source's audio packets and repacking islands, only if time remains. Audio works only on unencrypted input (decision 31). |
| 13 | PCIe scope | Staged: (6a) LitePCIe x1 Gen2 endpoint, driver on kernel 6.18, BAR access, DMA loopback; (6b) host framebuffer to HDMI out with a free-running output clock; capture to host if time permits. |
| 14 | Ethernet control | Hardware Etherbone kept as a Wishbone master, plus a CPU-visible LiteEth MAC sharing the same RMII PHY and UDP crossbar (LiteX `add_etherbone(with_ethmac=True)`), so `litex_server` and firmware networking coexist. Stack runs in the 50 MHz `eth` domain as the original did (100 MHz was hard to close); since LiteX's stock helper builds the stack in `sys`, `gateware/eth/` carries a custom integration that renames the UDP/IP core into `eth` and bridges the Etherbone Wishbone master into `sys`, as the original `cd="etherbone"` code did. Firmware adds a UDP JSON status/command port on `libliteeth`. If the MAC does not fit the 35T alongside the video pipeline, the 35T build keeps Etherbone only and the report says so. |
| 14b | Firmware delivery | The golden-unit BIOS has **only** serial boot (no flash, netboot or SD boot compiled in), so it can never jump into the stale 2018 firmware still in NOR at 0x7b0000 and its console timing is fixed. Firmware is delivered by LiteX serial boot (SFL) over the Pi UART at 115200 baud, exactly as the original `flterm --kernel` flow did (about 12 s for a 128 KB image). A Python 3.5-compatible SFL uploader lives in `tests/hardware/`. On `rpi5-netv2` firmware may additionally be written to NOR with a flash-boot-enabled BIOS (`FLASH_BOOT_ADDRESS` constant plus LiteSPI master; the BIOS checks the length/CRC header). Firmware is not embedded in block RAM: the 35T cannot spare it next to the video FIFOs. |
| 15 | HDCP blocks | Kept as a compile-time option, unchanged, not extended. |
| 16 | HDMI input/output pipeline (revised) | bunnie's litevideo fork at `master` (3bc5a24; `multires` is the same commit, and no `terc4-data` branch exists despite `.gitmodules`) is ported into this repo as `netv2/gateware/video/`. The litevideo **raw-mode output PHY** is kept: current LiteX's `VideoS7HDMIPHY` and `TMDSEncoder` have no raw 10-bit sink, so they cannot pass through TERC4 characters or emit data islands. The port must replace removed LiteX APIs (`CSRStorage(write_from_dev=, alignment_bits=)`, `atomic_write`, `dram_port.dw/aw`, `fifo._inc`), keep the three Verilog blackboxes (`chnlbond`, `phsaligner`, `delay_controller`), and move IDELAYCTRL into the CRG. |
| 17 | Pi software | Current MagicMirror release + `MMM-json-feed`; systemd units replace pm2. |
| 18 | Factory test stack | Build-only on current Rust plus docs; no test-hat hardware. |
| 19 | Utilities | `usb-pyromaniac`, `usb-mapping`, `xvcpi`: modernised with unit tests only. `netv2-soc`: archived and documented. |
| 20 | Open-source flow (revised) | Toolchain: openXC7 **0.9.3 or newer** (the `regymm/openxc7` docker image is a 2025-04 build with Yosys 0.17 and lacks the 2026-08 BUFR/BUFIO and STA fixes). Vivado-only by construction: LitePCIe's `S7PCIEPHY` (it instantiates the Vivado `pcie_7x` IP; the openXC7 `PCIE_2_1` path via `regymm/pcie_7x` exists but is not LitePCIe-compatible and is out of scope), the XADC, and all `set_false_path`/`set_multicycle_path` exceptions (the yosys+nextpnr backend drops them). Phase 5 is a feasibility study with measurements, not a promised passing bitstream (section 6). |
| 21 | Vivado | 2025.2 (installed). Newer releases only on user confirmation. |
| 22 | LiteX and migen pinning (revised) | LiteX 2026.04 (git tag 8ae3092; PyPI stops at 2024.12) and the matching 2026.04 tags of litedram, liteeth, litepcie, litespi, litescope, litex-boards, pinned as `git+https` dependencies in `pyproject.toml`, locked with `uv.lock`. LiteX 2026.04 pins migen from `git.m-labs.hk` at a SHA (GitHub `m-labs/migen` is archived); that SHA is mirrored into `mithro/migen` as branch `netv2-pin` and the lock points at the mirror. |
| 23 | Reviews | Every milestone PR reviewed by sub-agents for correctness, hardware safety, security, and docs/reproducibility. |
| 24 | Reporting | `LOG.md` (dated entries) and `docs/` in the repo; push notification per milestone. |
| 25 | Limits | Builds only on the desktop. Never push to AlphamaxMedia or any upstream. Never open upstream issues/PRs. |
| 26 | "rpi3b" | 3B+ accepted. |
| 27 | Test runner Python | The `netv2test` runner stays on the golden unit (Raspbian 9, Python 3.5.3) because it needs `/dev/video0`, `/dev/fb0` and `/dev/ttyS0` there. Therefore `netv2ctl`'s serial-REPL and Etherbone transports are Python 3.5-compatible (no f-strings, no dataclasses, stdlib only) and the suite may depend on them. The PCIe transport is a separate optional module for Python 3.11+ on the Pi 5. |
| 28 | Output verification without capture | The overlay SoC gains `frame_crc`: CRC32 (IEEE 802.3 polynomial, init 0xFFFFFFFF, final XOR) over the 24-bit RGB value (R, G, B byte order) of every DE-active pixel of output0 in raster order, one CRC latched per frame at VSYNC together with a frame counter, in CSRs. The CRC is computed on the decoded RGB that drives the mux (input0's decoded pixels delayed to match the raw path, or the overlay pixels), never on TMDS characters. **Validation (phase 3b)**: the host writes a known pattern into the overlay framebuffer in DDR over the console or Etherbone, sets the rectangle to cover the whole frame, and compares `frame_crc` with a CRC computed on the host over the same pattern; plus stability while static and change when the pattern changes. The MS2109 capture only corroborates the picture. Phase 6b repeats exactly this with the framebuffer written over PCIe. |
| 29 | DDR PHY and system clock (new) | The original ran `sys` at **75 MHz** with a 300 MHz IDELAY clock, a bunnie-modified A7DDRPHY, BUFIO/BUFR-derived clocks from two MMCMs and a `dqs_phase` tuning knob; litex-boards' target runs the upstream PHY at 100 MHz with a 200 MHz IDELAY clock. Phase 2a builds **both** on Vivado and characterises them (memtest, litedram calibration margins, HDMI overlay tearing) before phase 3 picks one; the default is upstream 100 MHz because it lifts DDR bandwidth by a third (section 4.6), falling back to the faithful 75 MHz port if calibration is marginal. |
| 30 | PCIe target parameters (new) | `pcie_x1`, `data_width=64`, `address_width=64` (Pi 5 has RAM above 4 GB), LitePCIe default IDs so the endpoint enumerates as **10ee:7021** (7020 + lanes); the stock 2018 design's kernel module expected 10ee:7022. After JTAG programming the Pi 5 root port is retrained by unbind/rebind of `1000110000.pcie` or a reboot; with the bitstream in NOR the endpoint is up before Linux scans. |
| 31 | HDCP and audio (new) | Data-island payloads are encrypted under HDCP, so extract and inject operate only when input0 is unencrypted; the firmware refuses to enable them while the HDCP cipher is active and the docs say so. |
| 32 | Simulation strategy (new) | Core logic (TMDS/TERC4 encode and decode tables, BCH ECC, packet framing, chroma-key mux, rectangle, DMA ring, `frame_crc`) is unit-tested in migen simulation with behavioural stand-ins for Xilinx primitives (ISERDES/OSERDES/MMCM/IDELAY modelled as Python). Serdes-level checks use Vivado `xsim` with `unisims` via cocotb, run only on the desktop. |
| 33 | REPL output as a contract (new) | The text format of every command the suite's `netv2test/console.py` issues (`help`, `dna`, `status`, `json`, `xadc_c`, `debug input0 on/off`, `debug rect/rectoff/override/stop/run/hpdforce/dumpe/mmcm`, `hpd` force/relax/toggle, `pipe override`, `overlay dma run/stop`, `video_mode [n]`, `video_matrix`, the rectangle and chroma commands) plus `t4i`/`t4d` and `dvimode0`/`hdmimode0` is frozen as `docs/current/repl-contract.md`, generated in phase 0 from that file. New commands are additive. Generated CSR accessor names may change freely. |
| 34 | SPI flash layout and image format (new) | Layout preserved: bitstream copies at 0 and mid-flash, firmware at 0x7b0000 (320 KB available, stock image 69,524 B). The old `mknetv2img -f` byte-swapped 32-bit words for the old SpiFlash core; LiteSPI reads linearly, so the new updater writes plain little-endian images with the LiteX boot header (length, CRC32) and refuses to run on IDCODE 0x0362d093 when the host is `rpi3-netv2`. Bitstream properties `SPI_BUSWIDTH 2` / `CONFIGRATE 66` are Vivado-only; openXC7 bitstreams configure at the slow default (documented). |
| 35 | Platform pads (new) | `netv2/platform.py` takes `cable="pcb"|"cable"` for the input1 (overlay) pair inversions. **Per host**: `rpi3-netv2` uses `pcb` (M2M jumper to the Pi 3B+); `rpi5-netv2` uses `cable` because a Pi 5 has micro-HDMI and can only reach input1 through a cable. Whether the Pi 5's HDMI is cabled to input1 at all is unknown; phase 4's overlay-lock proof on rpi5 is conditional on it and the report asks the user if the link is absent. The platform also adds the pins litex-boards lacks: `hpd_notif` (U17), `hdmi_sda_over_up/dn`, `hdmi_rx0_forceunplug/forceplug`, `hdmi_tx1_hpd_n`, `hdmi_ov0_hpd_n`, CEC, `fan_pwm`, `fpga_led0..5`, plus the `write_cfgmem -interface spix2` and CONFIGRATE commands. |
| 36 | Feature matrix per part (new) | Every feature is tagged for 35T, 100T or both, gated by a utilisation and timing report after each gateware phase. Audio extract must fit the 35T because the audio rig is the 35T unit; PCIe and audio inject-into-passthrough are 100T-first. |

## 3. How it worked originally (summary; full write-up is a deliverable)

NeTV2 is an Artix-7 (XC7A35T or XC7A100T, FGG484) board with 512 MB DDR3
(32-bit, two K4B2G1646F), 8 MB SPI NOR, RMII 100Base-T Ethernet, 2 HDMI in,
2 HDMI out, SD, and a PCIe x4 edge. It sits on a Raspberry Pi 3B+ riser. The Pi
drives JTAG over GPIO (TCK 4, TMS 17, TDI 27, TDO 22, SRST 24) and talks to the
SoC's UART over GPIO 14/15 (`/dev/ttyS0` on the Pi 3B+, `/dev/ttyAMA0` on the Pi 5).

Gateware (`netv2mvp.py`, 2019, LiteX 2019-03 plus forks): `VideoOverlaySoC` =
VexRiscv with a 24 KB BIOS ROM + DDR3 (bunnie-modified litedram A7DDRPHY,
**75 MHz sys**, 300 MHz IDELAY, `dqs_phase` knob) + SPI flash (firmware at
0x7b0000) + XADC + Etherbone over RMII (liteeth, 50 MHz `eth` domain) + two
litevideo HDMI inputs (input0 = source, input1 = Pi overlay via the M2M jumper)
+ one raw-mode HDMI output genlocked to input0. Clocking uses 4 MMCME2_ADV and
2 PLLE2 with BUFIO/BUFR per bank; 720p is reached at runtime by the firmware
rewriting MMCM registers over DRP, not by a different build. Timing closure
relies on 23 `set_false_path`/`set_multicycle_path` exceptions.

Compositing: for every character where input0's DE (derived from the TERC4
preamble decoder, so **data islands fall outside DE and are forwarded untouched**)
is active and the chroma-key/rectangle condition selects the overlay, the
output takes the re-encoded overlay pixel; otherwise it takes input0's raw
10-bit character after a fixed pipeline delay. The stock EDID advertises basic
audio (2-channel LPCM 32/44.1/48 kHz). Audio packets are therefore *expected* to
pass through today; the baseline suite's T23 nevertheless measured silence and
skipped, which is undiagnosed (decision 12). An HDCP cipher path lets the
overlay be re-encrypted on encrypted links. Multi-resolution autodetect (720p,
1080p, 1080i) landed 2019-09.

Firmware (`firmware/`, C, RISC-V): a serial REPL (`status`, `json`, `debug`,
`video_mode`, `video_matrix`, rectangle and chroma commands, EDID, MMCM DRP
tables, `t4i` to enable the TERC4 interrupt and `t4d` to print island packet and
character counters, noting that `t4d` prints input1's counter while labelling it
"hdmi0"), loaded from SPI NOR by the LiteX BIOS. Pi side
(`netv2mvp-scripts`): OpenOCD configs for the Alphamax OpenOCD fork
(bcm2835gpio), one-click SPI update, MagicMirror overlay app under pm2 with a
JSON status feed. Factory test: exclave (Rust) + `netv2-tests` scenarios +
`jig-20-interface-http` + the test-hat PCB. Images: `usb-pyromaniac` and
`usb-mapping`.

Reference unit: `rpi3-netv2` still runs the shipped 2018 image (Raspbian 9,
Python 3.5, OpenOCD 0.10 fork) with the 35T board, a `rpiz-3` HDMI source and an
MS2109 USB capture card. The 2026-09-05 test suite on it reports 29 PASS / 0
FAIL / 3 SKIP (T23 audio, T29 i2c snoop, T90 gaps) on the stock bitstream. That
run is the behavioural baseline.

## 4. Target architecture

### 4.1 Repository layout (`mithro/netv2-fpga`, branch `modern`)

```
pyproject.toml, uv.lock        LiteX 2026.04 family by git tag; Python >= 3.11
netv2/                         Python package
  platform.py                  NeTV2 platform (decision 35)
  crg.py                       clocking, IDELAYCTRL, CMT budget (4.4)
  targets/
    base.py                    UART+LEDs+DDR3+SPI flash+Ethernet (both toolchains)
    overlay.py                 VideoOverlaySoC (Vivado; openXC7 feasibility)
    pcie.py                    overlay + LitePCIe (Vivado only)
  gateware/video/              ported litevideo: input (clocking, charsync,
                               chansync, wer, decoding incl. TERC4, edid, dma),
                               output (core, raw-mode hdmi phy/encoder), overlay,
                               hdcp, blackboxes/*.v
    audio/                     island parser + BCH, extract (ASP/ACR -> DDR ring),
                               inject (ASP/ACR/InfoFrame generator -> raw PHY)
    frame_crc.py               per-frame CRC32 + counter over output pixels
  gateware/pcie/               LitePCIe integration, DMA to/from DDR
  gateware/eth/                Etherbone + ethmac on shared UDP crossbar
firmware/                      C firmware ported to current LiteX libbase
software/
  pi/                          netv2-scripts (OpenOCD/openFPGALoader configs for
                               Pi 3/4/5, updater, systemd units, MagicMirror)
  pcie/                        litepcie kernel module + user tools for Pi 5
  netv2ctl/                    Python control library (serial, Etherbone, PCIe)
tests/
  netv2test/                   subtree of the ten64 suite (runner on the Pi)
  sim/                         migen and cocotb unit tests for cores
  hardware/                    per-host harness: build, program, serial-boot,
                               run suite, collect report; SFL uploader (py3.5)
docs/
  original/                    how it worked (architecture, boot, data flow)
  current/                     how it works now, repl-contract.md, feature matrix
  testing/                     rigs, procedures, reports
  superpowers/specs, plans/    design and plan documents
legacy/                        original tree kept intact (netv2mvp.py, deps/...)
LOG.md                         dated work log
```

`master` stays byte-identical to AlphamaxMedia. `legacy/` is a move of the
original top-level files so the modern layout can coexist; the git history
preserves everything.

### 4.2 Toolchains

- Python via `uv`; LiteX family pinned per decision 22.
- Vivado 2025.2 at `/opt/Xilinx/2025.2` on the desktop (12 cores, 31 GB).
- openXC7 0.9.3+ installed from the openXC7 release (snap or tarball) into
  `.venv/toolchains/openxc7/`, wrapped by `make openxc7-…`. Both flows produce
  bitstreams into `build/<target>-<part>-<flow>/` with utilisation and timing
  reports committed under `docs/testing/reports/`.
- RISC-V: Debian `gcc-riscv64-unknown-elf`.
- Programming: OpenOCD `linuxgpiod` (Pi 3/4/5, stock Debian OpenOCD) and
  openFPGALoader `libgpiod` (pin order documented once, resolving the two
  conflicting orders in the fpgas.online docs). bscan_spi proxies for SPI flash.

### 4.3 Gateware

Ported cores keep their original module boundaries so the original and current
designs are comparable line by line. Changes are confined to: the migen/LiteX
API surface (LiteXModule, CSR/interrupt API, stream layouts, the removed APIs in
decision 16), clocking (moved into `crg.py`), and a toolchain flag that selects
Vivado-only pieces (XADC, timing exceptions, DRP-driven MMCM tables, bitstream
properties). The raw-mode output PHY and TERC4-derived DE are preserved because
the passthrough and audio features depend on them.

New cores:

- `audio/parser`: in the `pix` domain, follows input0's preamble/guard-band
  state machine, splits islands into 32-character packets, checks header and
  subpacket BCH ECC, and exposes a decoded packet stream (type, header, four
  subpackets, ECC ok). Used by extract, by inject-into-passthrough, and by the
  `t4d` diagnostics.
- `audio/extract`: consumes Audio Sample Packets (0x02), ACR (0x01) and Audio
  InfoFrame (0x84); honours sample-present and layout flags; writes IEC 60958
  subframes (with channel status, V/U/P bits) plus sequence numbers into a DDR
  ring via DMA; latches N/CTS, InfoFrame fields and measured pixel clock in CSRs.
- `audio/inject`: builds islands (preamble, guard bands, up to 18 packets,
  trailing guard) as raw TERC4 characters into the raw PHY during blanking,
  carrying ASP, ACR, and Audio InfoFrame with correct ECC; ch0 nibbles reproduce
  live HSYNC/VSYNC. N/CTS: N fixed per sample rate, CTS counted in hardware from
  the actual pixel clock; DDR ring fill level in CSRs for host rate control. In
  self-timed mode the output also emits AVI InfoFrame and GCP so the transmitter
  is a real HDMI source rather than DVI. Inject-into-passthrough additionally
  drops the source's 0x01/0x02/0x84 packets and repacks islands, keeping AVI, GCP,
  SPD and vendor packets, with a fixed latency matching the raw delay line.
- `frame_crc`: CRC32 and frame counter over output0's active pixels (decision 28).
- `pcie/`: LitePCIe x1 Gen2 endpoint (Vivado `pcie_7x` IP), MMAP to CSRs, DMA
  engine to DDR (decision 30); a framebuffer-in-DDR path feeds the overlay DMA.
- `eth/`: Etherbone plus CPU-visible LiteEth MAC on the shared UDP crossbar
  (decision 14).
- Output clock mux (delivered in phase 3c as part of `overlay.py`, consumed by
  6b and 7c): today the output and the DRAM read port live in `pix_o` from
  input0. A free-running output clock (litevideo `S7HDMIOutClocking` from the
  system clock, implemented on a PLLE2 so the MMCM count is unchanged) and a
  glitch-free clock select with reset sequencing for the LiteDRAM read port let
  the NeTV2 output with no source connected.

### 4.4 Clock and CMT budget

Per HDMI input: `pix`, `pix1p25x`, `pix1p25x_r` (BUFR/4), `pix5x` (BUFIO),
`pix_raw`; input0 additionally `pix_o`/`pix5x_o` from a PLLE2_ADV. Original
total: 4 MMCME2_ADV + 2 PLLE2 + IDELAYCTRL (300 MHz) + BUFIO/BUFR per bank. Each
CMT holds one MMCM and one PLL; the XC7A35T has 5 CMTs (5 MMCM + 5 PLL), the
XC7A100T has 6. The self-timed output clock (phase 3c) uses a third PLLE2, so
the 35T overlay target needs 4 MMCM + 3 PLL; `pcie_7x` adds an MMCM on the 100T
only (5 MMCM + 3 PLL of 6 + 6). `crg.py` carries an explicit table of CMT sites
per target and part, and the build fails early if it is exceeded. BUFIO/BUFR are bank-local, so
pad-to-clock-region placement is fixed by the pinout and recorded in the docs.

### 4.5 Software

- Firmware ported to current `libbase`/`libliteeth`; command set and output
  format preserved (decision 33); new `audio`, `pcie`, `net` commands. Boot
  order pinned in the target (serial boot first on the golden unit, flash boot
  first on the Pi 5) so console timing stays predictable for the suite.
- `netv2ctl`: one Python API over three transports (decision 27).
- Pi tooling: OpenOCD configs for Pi 3B+/4/5 on stock OpenOCD; `update-fpga`
  rewritten in Python with the same safety checks (IDCODE gate, padding, CRC,
  golden-unit refusal) and the LiteSPI image format (decision 34); MagicMirror
  current release with the org's `MMM-json-feed`; systemd units.
- Pi 5 PCIe: LitePCIe kernel module built against the running 6.18 kernel with
  a DKMS-style Makefile; `litepcie_util` for DMA loopback; a retrain helper.

### 4.6 DDR bandwidth budget

32-bit DDR3 at 75 MHz sys (600 MT/s) is 2.4 GB/s theoretical, at 100 MHz
3.2 GB/s. 1080p60 RGBx capture of input1 (594 MB/s) plus overlay readback
(594 MB/s) is already half of the 75 MHz figure, and the original notes tearing
under CPU load. Phase 6b's PCIe framebuffer writer adds 297 to 594 MB/s; audio is
about 0.4 MB/s; Etherbone, CPU and refresh are small. At litedram's practical
60 to 80 % efficiency the 100 MHz option is needed for the combined 100T target;
the 35T target is not asked to carry PCIe. The overlay FIFO depth and DMA burst
sizes are re-tuned with measurements in phase 3b and recorded.

### 4.7 Testing

Three layers, each producing artefacts committed under `docs/testing/reports/`:

1. Simulation (decision 32): unit tests for every ported and new core (TMDS
   encode/decode round trip, TERC4 tables, BCH ECC against captured real packets
   once phase 7a produces them, packet framing, island slot allocation,
   chroma-key mux, rectangle, DMA ring, `frame_crc`). `uv run pytest` on the
   desktop; cocotb+xsim jobs marked slow.
2. Bring-up on hardware: per host `tests/hardware/run.py` builds or fetches a
   bitstream, programs it (volatile), serial-boots firmware where required,
   captures the console, and asserts memtest, ident, Ethernet link, PCIe
   enumeration, HDMI lock, utilisation/timing report presence.
3. Functional: the `netv2test` suite (T01–T31, T90) on the rpi3 rig, extended
   with audio tests (T23 becomes real, plus extract and inject tests using a tone
   from `rpiz-3` and the MS2109 ALSA capture, validated first by measuring
   `rpiz-3` to MS2109 directly) and network-control variants of existing tests.
   Same suite, same IDs, so original versus modern reports are directly comparable.

Every hardware run on `rpi3-netv2` ends by reloading the stock `user-35.bit`
and confirming `status` matches the baseline.

### 4.8 Review process

Each phase ends with a PR into `modern`. Before merge, four sub-agent reviews
run from separate prompts with no shared session state: correctness (does the
code do what the spec says, tests real), hardware safety (can this damage a
board, brick SPI flash, or hang a host; are the golden-unit rules respected),
security (firmware network surfaces, kernel module, scripts run as root), and
documentation/reproducibility (can a stranger rebuild and rerun). Findings are
fixed or explicitly waived in the PR description.

## 5. Phases

| Phase | Deliverable | Hardware proof / exit criterion |
|-------|-------------|----------------|
| 0 Repo setup | forks, `modern`, layout, uv project with pins, migen mirror, `LOG.md`, subtree of test suite, docs skeleton, REPL contract draft | none |
| 1 Baseline | `docs/original/*`; baseline suite report from `rpi3-netv2` on stock bitstream; `t4i` then `t4d` island counts (on both inputs, given the label bug) and direct `rpiz-3` to MS2109 audio measurement (feeds 7a); time-boxed (1 day) rebuild of the 2019 design in a `python:3.7` container with Vivado 2025.2 | rpi3 report |
| 2a Modern base, Vivado | `targets/base.py` for a7-35 and a7-100 in both DDR configurations (decision 29); firmware skeleton; serial boot path; utilisation baseline | BIOS + `Memtest OK` on rpi5 (100T) and rpi3 (35T, volatile), both PHY options characterised |
| 2b openXC7 base | `targets/base.py` on openXC7 0.9.3+ for both parts; per-primitive status table (ISERDES from pad, IBUFDS_DIFF_OUT, OSERDES 10:1, MMCME2_ADV lock, DRP, BUFIO/BUFR, IDELAYCTRL) from tiny probe designs | `Memtest OK` three times on each part, or a documented root cause for each failure. Runs in parallel with 3a; does not gate it |
| 3a HDMI passthrough | `gateware/video/` input0 + raw output ported; input1 clocking and decoding (lock only, no DMA); firmware `status`/`debug input0` ported; no DDR use | rpi3 suite T01–T09 pass; utilisation and timing gate for 35T |
| 3b Overlay | input1 capture, DMA, rectangle, chroma, `frame_crc`, DDR tuning | rpi3 suite T10–T18, T21, T22, T24–T29, T31 pass with baseline SKIPs (T23, T29, T90); `frame_crc` validated per decision 28 |
| 3c Multires, HDCP option, self-timed output | DRP tables, 720p/1080i, HDCP compile-time option, free-running output clock and DRAM-port clock mux (section 4.3) | rpi3 suite T19, T20, T30 pass; HDCP build fits and passes T01–T22; with input0 unplugged the output runs 1080p60 from the internal clock and the MS2109 locks to it |
| 4 Pi software | scripts, systemd, MagicMirror, updater on trixie | rpi5: systemd units up, MagicMirror serving the overlay, JSON feed live, and, if the Pi 5's HDMI is cabled to input1 (decision 35), console reports input1 locked; Pi 3 trixie via netboot node when available |
| 5 openXC7 overlay feasibility | `targets/overlay.py` build attempt on openXC7 for both parts; STA numbers; gap list per primitive and per timing exception; minimal restructuring proposal (registered gearbox, fixed-ratio MMCM per resolution) and, if it routes and locks, a hardware run | Report committed; if a bitstream locks on input0, rpi3 T01–T09 attempted and recorded either way |
| 6a PCIe endpoint | `targets/pcie.py` (100T), kernel module, DMA loopback, retrain helper | rpi5 `lspci` shows 10ee:7021 x1 Gen2, BAR CSR reads match UART, DMA loopback error-free for 1 GB |
| 6b PCIe framebuffer to HDMI | host writes framebuffer over PCIe into the overlay DDR buffer; uses the phase 3c self-timed output | `frame_crc` of the output matches the CRC the host computes over its framebuffer, with no HDMI source connected |
| 7a Audio diagnosis | `t4d` counts on both inputs, parser core, first captured real islands, root cause of T23 silence | Report: islands present/absent at input0 and output0; T23 unskipped if passthrough audio works |
| 7b Audio extract | extract core + DMA ring + firmware `audio` + `netv2ctl` | rpi3 rig: 1 kHz tone from `rpiz-3` recovered from the DDR ring, frequency within 1 %; fits the 35T |
| 7c Audio inject, self-timed | inject core on the phase 3c self-timed output; AVI/GCP/Audio InfoFrame | rpi3 rig: MS2109 ALSA capture of the injected tone, frequency within 1 %, no underruns over 10 min |
| 7d Audio inject into passthrough (optional) | source audio stripped and replaced | rpi3 rig: T23-style capture hears the injected tone while video passes through |
| 8 Ethernet control | ethmac integration, UDP JSON port, `netv2ctl` Etherbone transport, suite variants | On whichever unit has the NeTV2 RJ45 cabled (rpi5 first): `litex_server` reads CSRs; on rpi3 the console-only subset (T01, T04–T06, T18–T22, T25, T28, T31) runs with the Etherbone transport instead of the UART, capture tests unchanged |
| 9 Ancillary | exclave/jig-20 build on current Rust; utilities on Python 3.13 with tests; `netv2-soc` archived | none |
| 9b Integration per part | combined 35T and 100T targets with the feature matrix; utilisation, CMT and DDR budgets checked | full suite on rpi3 (35T) and full harness on rpi5 (100T) from the combined bitstreams |
| 10 Docs and final proof | `docs/current`, `docs/testing`, reports on both hosts, summary | both hosts |

Phases 6a, 7a, 7b and 8 are independent after 3b; 6b and 7c additionally need
3c's self-timed output. They can be interleaved; 2b and 5 run in the background
as builds are slow.

## 6. Risks and mitigations

- **openXC7 cannot yet build this design as-is.** Open nextpnr-xilinx issues
  (as of 2026-09) cover ISERDESE2 fed from a pad being unroutable (#143),
  IOSERDES differential-out unimplemented (#66), MMCME2_ADV failing to lock
  (#79), OSERDESE2 10-bit mode (#70), no hold analysis and a rudimentary STA
  (#12, #165), measured fabric Fmax of 50 to 90 MHz on Artix-7 designs, and no
  evidence of any DRP use. Every HDMI-on-openXC7 result found is 480p. Nobody
  has reported litedram passing memtest on the NeTV2 with openXC7 (fpgas.online
  tried; the 100T failure is unexplained). Mitigation: phase 2b measures each
  primitive in isolation first; phase 5 is a feasibility study with a concrete
  restructuring proposal, and its honest outcome may be "not yet". Requirement
  (c) is satisfied by `base.py` building and the overlay gap list, not by a
  passing 1080p overlay bitstream.
- **DDR3 choice (decision 29)**: the faithful 75 MHz port and the upstream
  100 MHz PHY differ in calibration and bandwidth; both are measured in 2a.
- **35T fit**: modern BIOS with litedram calibration, liteeth and litespi wants
  64 to 128 KB of ROM versus the original 24 KB, next to the 4096-deep output
  FIFO, input FIFOs, ChanSync memories, two EDID RAMs and audio. Mitigation:
  utilisation gate after 3a; BIOS trimmed (no netboot, no SD) on the 35T;
  feature matrix (decision 36).
- **Timing exceptions**: 23 false-path/multicycle constraints are load-bearing
  (185.6 to 148.5 MHz gearbox, bitslip, DQ OE). They stay on Vivado; for openXC7
  the gearbox output is registered and multicycle paths removed in the phase 5
  proposal.
- **PCIe on Pi 5**: root port needs retrain after FPGA configuration; x1 only;
  RAM above 4 GB. Mitigation: decision 30, NOR boot for persistent tests.
- **Audio inject into a passthrough stream** is the hardest new core (a blanking
  rewriter with packet stripping and repacking). Mitigation: it is phase 7d and
  optional; 7a to 7c deliver diagnosis, extract, and self-timed inject first,
  and 7b's parser plus captured islands give 7d a real testbench.
- **Golden unit damage**: only volatile loads; the updater and harness refuse
  SPI flash commands when the IDCODE is 0x0362d093 on host `rpi3-netv2`.
- **Netboot node access**: unresolved; Pi 3 trixie proof may slip until the
  user provides access. Everything else proceeds.
- **Old LiteX rebuild (phase 1)**: may fail on Python 3.13 or on Vivado 2025.2
  TCL differences; run in a `python:3.7` container, time-boxed to one day,
  documented either way.
- **Ethernet cabling**: the rpi3 rig is uncabled; if the rpi5 unit is too,
  phase 8 blocks on the user.

## 7. Out of scope

Upstreaming anything; changes to fpgas.online infrastructure; new PCB work; USB
device gateware; HDCP feature extension; audio on HDCP-encrypted input; HBR,
DSD and 3D audio packets; an openXC7 PCIe path (`regymm/pcie_7x`); Windows or
macOS build support.
