# NeTV2 modernisation: design

Status: draft v1, 2026-09-05. Author: Claude (Fable 5.1) working for Tim Ansell (mithro).

## 1. Goal

Bring the Alphamax/Kosagi NeTV2 code base back to a working, buildable state on
current software, then extend it, and prove every step on real hardware:

(a) All existing software runs on current Raspberry Pi OS / Debian (trixie, with
    an eye on sid) on both a Raspberry Pi 3B+ and a Raspberry Pi 5.
(b) The gateware builds on the latest LiteX release with a current Python and
    the latest installed Vivado.
(c) The gateware also builds with the open-source Xilinx 7-series flow (openXC7:
    Yosys, nextpnr-xilinx, Project X-Ray).
(d) The gateware gains: a PCIe endpoint usable from the Pi 5, HDMI audio
    embedding and de-embedding, and control over the NeTV2's own Ethernet port.

Everything is done on forks under the `mithro` GitHub account in small commits,
reviewed by sub-agents from several directions, with documentation of how the
system worked originally, how it works now, and how it was tested.

## 2. Assumptions (decisions taken without the user)

The user asked to be questioned first and then left me to work independently.
The 26 questions I raised are answered here with my proposed defaults. Each is
reversible; anything marked **risky** is where a wrong guess costs the most.

| # | Topic | Decision |
|---|-------|----------|
| 1 | LiteX-family deps whose fork network `mithro` already forks | AlphamaxMedia branches pushed into the existing `mithro/*` forks as `alphamax-<branch>` branches (done 2026-09-05). Modern build uses upstream releases, not these forks. |
| 2 | Home for new work | `mithro/netv2-fpga`. `master` kept as the pristine AlphamaxMedia master; integration branch `modern`; feature branches merged into `modern` via PRs on the fork. |
| 3 | Fork scope | All 23 org repos forked or branch-archived under `mithro` (done). |
| 4 | Test suite repo | Creating a new GitHub repo was blocked by the permission classifier. The ten64 suite is merged into `mithro/netv2-fpga` under `tests/netv2test/` as a git subtree with history. The user can split it out later. |
| 5 | ten64 `~/local/netv2` notes | Folded into `docs/` (Pi 5 programming notes). |
| 6 | **risky** `rpi3-netv2` golden unit | Never re-imaged, never SPI-flashed. Volatile JTAG loads only, stock bitstream restored after every run. A netbooting fpgas.online Pi 3B+ node is the modern-OS Pi 3 target once access is sorted out. |
| 7 | Netboot nodes | Unknown access path (tweed host key changed). Treated as a later-phase dependency; infra repos are read-only. |
| 8 | Reboots and power cycling | Allowed for `rpi5-netv2` and netboot nodes. Never for `rpi3-netv2`. |
| 9 | Pi 5 PCIe cabling | Assumed connected; verified in phase 2 with a PCIe bitstream. |
| 10 | HDMI test rig | Only `rpi3-netv2` has capture (MS2109) and a source (`rpiz-3`). Pi 5 covers JTAG, UART, DDR, Ethernet, PCIe, and HDMI lock via console. |
| 11 | NeTV2 RJ45 cabling | Unknown. Phase 8 checks link state first; if uncabled, the report says so and asks the user. |
| 12 | HDMI audio scope | Staged: (1) data-island passthrough in overlay mode, (2) de-embed to DDR for the host, (3) embed host audio into the output. |
| 13 | PCIe scope | Staged: (1) LitePCIe endpoint, driver on kernel 6.18, BAR access, DMA loopback; (2) host framebuffer to HDMI out; (3) capture to host if time permits. |
| 14 | Ethernet control | Etherbone + `litex_server` + Python `netv2ctl` library + UDP JSON status from firmware. |
| 15 | HDCP blocks | Kept as a compile-time option, unchanged, not extended. |
| 16 | HDMI input pipeline | bunnie's litevideo fork ported into this repo as `netv2/gateware/video/` on current migen/LiteX. |
| 17 | Pi software | Current MagicMirror release + `MMM-json-feed`; systemd units replace pm2. |
| 18 | Factory test stack | Build-only on current Rust plus docs; no test-hat hardware. |
| 19 | Utilities | `usb-pyromaniac`, `usb-mapping`, `xvcpi`: modernised with unit tests only. `netv2-soc`: archived and documented. |
| 20 | Open-source flow gap | PCIe hard block and GTP transceivers are unsupported by nextpnr-xilinx, so the PCIe target is Vivado-only. All else must build with openXC7 (docker `regymm/openxc7`). |
| 21 | Vivado | 2025.2 (installed). Newer releases only on user confirmation. |
| 22 | LiteX | Pinned to release 2026.04 with a uv lockfile. |
| 23 | Reviews | Every milestone PR reviewed by sub-agents for correctness, hardware safety, security, and docs/reproducibility. |
| 24 | Reporting | `LOG.md` (dated entries) and `docs/` in the repo; push notification per milestone. |
| 25 | Limits | Builds only on the desktop. Never push to AlphamaxMedia or any upstream. Never open upstream issues/PRs. |
| 26 | "rpi3b" | 3B+ accepted. |

## 3. How it worked originally (summary; full write-up is a deliverable)

NeTV2 is an Artix-7 (XC7A35T or XC7A100T, FGG484) board with 512 MB DDR3, 8 MB
SPI NOR, RMII 100Base-T Ethernet, 2 HDMI in, 2 HDMI out, SD, and a PCIe x4
edge. It sits on a Raspberry Pi 3B+ riser. The Pi drives JTAG over GPIO
(TCK 4, TMS 17, TDI 27, TDO 22, SRST 24) and talks to the SoC's UART over GPIO
14/15 (`/dev/ttyS0` on the Pi 3B+, `/dev/ttyAMA0` on the Pi 5).

Gateware (`netv2mvp.py`, 2019, LiteX 2019-03 + forks): `VideoOverlaySoC` =
VexRiscv + DDR3 (litedram A7DDRPHY, 100 MHz sys) + SPI flash + Etherbone over
RMII (liteeth) + two litevideo HDMI inputs (input0 = source, input1 = Pi overlay
via the M2M jumper) + one HDMI output. Input0's TMDS characters pass straight
through to output0 with a fixed pipeline delay; the Pi's framebuffer (input1,
captured to DDR and DMA'd back out) is composited over it by chroma key inside a
programmable rectangle. An HDCP cipher path lets the overlay be re-encrypted so
it survives on encrypted links. A TERC4 decoder reads data islands (used for
colourspace detection; audio was never handled). Multi-resolution autodetect
(720p, 1080p, 1080i) landed in 2019-09.

Firmware (`firmware/`, C, RISC-V): a serial REPL (`status`, `json`, `debug`,
`video_mode`, rectangle and chroma commands, EDID, MMCM tuning), loaded from
SPI NOR by the LiteX BIOS. Pi side (`netv2mvp-scripts`): OpenOCD configs for the
Alphamax OpenOCD fork (bcm2835gpio), one-click SPI update, MagicMirror overlay
app under pm2 with a JSON status feed. Factory test: exclave (Rust) + `netv2-tests`
scenarios + `jig-20-interface-http` + the test-hat PCB. Images: `usb-pyromaniac`
and `usb-mapping`.

Reference unit: `rpi3-netv2` still runs the shipped 2018 image (Raspbian 9,
Python 3.5, OpenOCD 0.10 fork) with the 35T board, a `rpiz-3` HDMI source and an
MS2109 USB capture card. The 2026-09-05 test suite on it reports 29 PASS / 0
FAIL / 3 SKIP on the stock bitstream. That run is the behavioural baseline.

## 4. Target architecture

### 4.1 Repository layout (`mithro/netv2-fpga`, branch `modern`)

```
pyproject.toml, uv.lock        LiteX 2026.04 + deps pinned; Python >= 3.11
netv2/                         Python package
  platform.py                  NeTV2 platform (from litex-boards, plus hdmi pad
                               inversion variants "pcb"/"cable")
  targets/
    base.py                    UART+LEDs+DDR3+SPI flash+Ethernet (both toolchains)
    overlay.py                 VideoOverlaySoC (both toolchains)
    pcie.py                    overlay + LitePCIe (Vivado only)
  gateware/video/              ported litevideo: input (clocking, charsync,
                               chansync, wer, decoding, terc4, edid, dma),
                               output (core, hdmi phy/encoder), overlay, hdcp
    audio/                     data-island passthrough, audio sample packet
                               extraction, audio packet injection, ACR
  gateware/pcie/               LitePCIe integration, DMA to/from DDR
  gateware/eth/                Etherbone + UDP status
firmware/                      C firmware ported to current LiteX libbase
software/
  pi/                          netv2-scripts (OpenOCD/openFPGALoader configs for
                               Pi 3/4/5, update, systemd units, MagicMirror)
  pcie/                        litepcie kernel module + user tools for Pi 5
  netv2ctl/                    Python control library (serial, Etherbone, PCIe)
tests/
  netv2test/                   subtree of the ten64 suite (runner on the Pi)
  sim/                         migen/cocotb unit tests for cores
  hardware/                    per-host harness: build, program, run suite,
                               collect report
docs/
  original/                    how it worked (architecture, boot, data flow)
  current/                     how it works now
  testing/                     rigs, procedures, reports
  superpowers/specs, plans/    design and plan documents
legacy/                        original tree kept intact (netv2mvp.py, deps/…)
LOG.md                         dated work log
```

`master` stays byte-identical to AlphamaxMedia. `legacy/` is a move of the
original top-level files so the modern layout can coexist; the git history
preserves everything.

### 4.2 Toolchains

- Python via `uv`; LiteX 2026.04, litex-boards, litedram, liteeth, litepcie,
  litescope, litespi, pythondata packages, all pinned in `uv.lock`.
- Vivado 2025.2 at `/opt/Xilinx/2025.2` on the desktop (12 cores, 31 GB).
- openXC7 via the local `regymm/openxc7` docker image, wrapped by a `make
  openxc7-…` target. Both flows produce bitstreams into `build/<target>-<part>-<flow>/`.
- RISC-V: Debian `gcc-riscv64-unknown-elf`.
- Programming: OpenOCD `linuxgpiod` (Pi 3/4/5, stock Debian OpenOCD) and
  openFPGALoader `libgpiod`. bscan_spi proxies for SPI flash.

### 4.3 Gateware

Ported cores keep their original module boundaries so the original and current
designs are comparable line by line. Changes are confined to: the migen/LiteX
API surface (LiteXModule, CSR/interrupt API, stream layouts), clocking (S7MMCM
helpers), and toolchain neutrality (no Vivado-only primitives outside the PCIe
target; IDELAYE2/ISERDESE2/OSERDESE2, MMCM, PLL and BUFR are all supported by
prjxray).

New cores:

- `audio/island_passthrough`: in overlay mode the data islands (guard bands,
  TERC4 packets, preamble) from input0 are forwarded unchanged so audio,
  InfoFrames and ACR survive; the video mux only replaces active-video pixels.
- `audio/extract`: decodes Audio Sample Packets (type 0x02) and Audio Clock
  Regeneration (0x01) from input0, writes PCM into a DDR ring via DMA with N/CTS
  in CSRs; the host reads it over Etherbone or PCIe.
- `audio/inject`: takes PCM from a DDR ring, generates ASP + ACR + Audio
  InfoFrame packets in the output's data-island slots with correct BCH ECC and
  TERC4 encoding.
- `pcie/`: LitePCIe x1 Gen2 endpoint (Vivado `pcie_7x` IP), MMAP to CSRs,
  DMA engine to DDR; framebuffer-to-DDR path feeds the existing overlay DMA.
- `eth/`: Etherbone kept; firmware adds a UDP JSON status/command port so the
  REPL commands work over the network.

### 4.4 Software

- Firmware ported to current `libbase`/`libliteeth`; command set preserved so the
  test suite's console parser keeps working; new `audio`, `pcie`, `net` commands.
- `netv2ctl`: one Python API over three transports (serial REPL, Etherbone,
  PCIe BAR); used by the test suite and the Pi tools.
- Pi tooling: OpenOCD configs for Pi 3B+/4/5 on stock OpenOCD, `update-fpga`
  rewritten in Python with the same safety checks (IDCODE gate, padding, CRC),
  MagicMirror current release with the org's `MMM-json-feed`, systemd units.
- Pi 5 PCIe: LitePCIe kernel module built against the running 6.18 kernel via
  DKMS-style Makefile; `litepcie_util` for DMA loopback.

### 4.5 Testing

Three layers, each producing artefacts committed under `docs/testing/reports/`:

1. Simulation: migen/`litex_sim` and cocotb unit tests for every ported and new
   core (TMDS encode/decode round trip, TERC4, BCH ECC, packet framing, chroma
   key mux, overlay rectangle, DMA ring). Runs on the desktop with `uv run pytest`.
2. Bring-up on hardware: per host `tests/hardware/run.py` builds or fetches a
   bitstream, programs it (volatile), captures the BIOS/firmware console, and
   asserts memtest, ident, Ethernet link, PCIe enumeration, HDMI lock.
3. Functional: the `netv2test` suite (T01–T31) on the rpi3 rig, extended with
   audio tests (T23 becomes real: tone from `rpiz-3`, captured via MS2109 ALSA)
   and network-control variants of existing tests. Same suite, same IDs, so
   original versus modern reports are directly comparable.

Every hardware run on `rpi3-netv2` ends by reloading the stock `user-35.bit`
and confirming `status` matches the baseline.

### 4.6 Review process

Each phase ends with a PR into `modern`. Before merge, four sub-agent reviews
run from separate prompts with no shared session state: correctness (does the
code do what the spec says, tests real), hardware safety (can this damage a
board, brick SPI flash, or hang a host; are the golden-unit rules respected),
security (firmware network surfaces, kernel module, scripts run as root), and
documentation/reproducibility (can a stranger rebuild and rerun). Findings are
fixed or explicitly waived in the PR description.

## 5. Phases

| Phase | Deliverable | Hardware proof |
|-------|-------------|----------------|
| 0 Repo setup | forks, `modern`, layout, uv project, `LOG.md`, subtree of test suite, docs skeleton | none |
| 1 Baseline | `docs/original/*`; baseline suite report from `rpi3-netv2` on stock bitstream; time-boxed attempt to rebuild the 2019 design with pinned deps in a container | rpi3 report |
| 2 Modern skeleton | `targets/base.py` builds on Vivado 2025.2 and openXC7 for a7-35 and a7-100; firmware skeleton | BIOS + memtest on rpi5 (100T) and rpi3 (35T, volatile) |
| 3 HDMI port | `gateware/video/` ported; `targets/overlay.py` on Vivado; firmware ported; multires, chroma, HDCP option | rpi3 suite T01–T22 pass on the modern bitstream |
| 4 Pi software | scripts, systemd, MagicMirror, update tool on trixie | rpi5 end to end; Pi 3 trixie via netboot node when available |
| 5 openXC7 overlay | `targets/overlay.py` builds with openXC7 for both parts; timing report; gap list | rpi3 suite on openXC7 bitstream |
| 6 PCIe | `targets/pcie.py`, kernel module, DMA loopback; host framebuffer path | rpi5 lspci 10ee:7011, DMA test, image on HDMI out via PCIe |
| 7 HDMI audio | island passthrough, extract, inject cores + firmware + tests | rpi3 rig: T23 audio passes for passthrough and inject; extracted PCM matches source tone |
| 8 Ethernet control | Etherbone, UDP status, `netv2ctl`, suite over network | rpi5/rpi3 with NeTV2 RJ45 on the LAN |
| 9 Ancillary | exclave/jig-20 build on current Rust; utilities on Python 3.13 with tests; `netv2-soc` archived | none |
| 10 Docs and final proof | `docs/current`, `docs/testing`, full reports on both hosts, summary | both hosts |

Phases 6, 7, 8 are independent after 3 and can be interleaved; 5 can run in the
background as builds are slow.

## 6. Risks and mitigations

- **HDMI pipeline on openXC7 timing (148.5 MHz pixel, 742.5 MHz serdes)**:
  nextpnr-xilinx timing is weaker than Vivado's. Mitigation: 720p first, then
  1080p; keep the design split so a Vivado-only fallback is a flag, not a fork.
- **DDR3 on openXC7**: litedram A7DDRPHY needs IDELAYCTRL, IDELAYE2, ISERDES; all
  in prjxray, but calibration margins may be thin. Mitigation: your
  fpgas.online `ddr-memory` design as the starting point; measure with memtest.
- **PCIe on Pi 5**: Broadcom RC quirks (`pci=pcie_bus_safe` already set), link
  training with an FPGA that configures after the RC has scanned. Mitigation:
  load from SPI flash so the endpoint is up before Linux scans; else rescan.
- **Audio packet timing**: ACR N/CTS regeneration and ASP placement must respect
  island slot budgets per line. Mitigation: simulation with captured real
  streams (data-island capture already exists in the fork).
- **Golden unit damage**: only volatile loads; scripts refuse to run SPI flash
  commands when the IDCODE is 0x0362d093 on host `rpi3-netv2`.
- **Netboot node access**: unresolved; Pi 3 trixie proof may slip until the user
  provides access. Everything else proceeds.
- **Old LiteX rebuild (phase 1)**: may fail on Python 3.13; run in a
  `python:3.7` container; time-boxed to one day, documented either way.

## 7. Out of scope

Upstreaming anything; changes to fpgas.online infrastructure; new PCB work; USB
device gateware; HDCP feature extension; Windows or macOS build support.
