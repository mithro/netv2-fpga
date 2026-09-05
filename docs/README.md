# NeTV2 modernisation: overview

This is the capstone index for the NeTV2 modernisation work. It ties together how
the board worked originally, how it works now on modern tooling, and how each part
was tested. Read the linked pages for detail.

Status: 2026-09-06. Repo: `mithro/netv2-fpga`. Integration branch: `modern`.

## Goal and where each part stands

The task: get the old NeTV2 code building and working on current software and
Raspberry Pi OS, rebase the gateware onto the latest LiteX and Vivado, enable an
open-source build, and extend the gateware with PCIe, HDMI audio and Ethernet
control, testing on real hardware.

| Goal item | State | Hardware test |
|-----------|-------|---------------|
| Build again on modern LiteX + Vivado | **Done** — `netv2/targets/base.py`, LiteX 2026.04, Vivado 2025.2, WNS +0.893 ns | **Pass** — rpi5 volatile load, LiteX BIOS + DDR3 `Memtest OK` |
| Run on latest Raspberry Pi OS (trixie) on Pi 3B+ and Pi 5 | Pi 5 (trixie) is the working host for JTAG/UART/PCIe/Ethernet; Pi 3B+ trixie via the netboot nodes is pending access | Pi 5 trixie exercised throughout |
| PCIe endpoint | **Gateware done** — `netv2/targets/pcie.py`, x1 Gen2, `10ee:7021`, datapath timing closed | Loads + boots on rpi5; **enumeration blocked at the physical PCIe wiring** (needs a person; see phase-6 report) |
| HDMI audio de-embed | **Done in sim** — `netv2/gateware/video/audio/`, bit-exact PCM recovery | Functional test needs the rpi3 golden capture rig (pending go-ahead) |
| HDMI audio embed | Not yet — needs the litevideo output-pipeline port | — |
| Ethernet control | **Done** — `netv2/targets/ethernet.py`, hardware Etherbone + CPU MAC | **Pass** — rpi5, KSZ8081 link up 100M FD, Etherbone CSR read/write over the NeTV2 RJ45 |
| Open-source toolchain (openXC7) | In progress | — |
| HDMI input pipeline (foundation for audio) | **Done** — litevideo input ported to modern LiteX, builds (setup/hold met at 1080p60; ISERDES is a -2 datasheet limit at 742.5 MHz, clean at 720p) | — |
| HDCP receiver (added mid-project by the user) | **Done in sim** (branch `hdcp-receiver`), 91 tests, full-handshake xsim pass | Blocked: the 2019 bridge design fails timing on Vivado 2025.2 (pre-existing, not the receiver) |
| Full documentation | This page + `docs/original`, `docs/current`, `docs/testing` | — |

## The key technical result

The 2019 design does **not** close timing on Vivado 2025.2 (post-route WNS -7.5 ns,
and it nearly fills the 35T) — see `original/rebuild-2019.md`. The modern
`litex-boards` NeTV2 target on LiteX 2026.04 **does** close timing cleanly and runs
on the board. So the modernisation path is the maintained modern LiteX target, not a
patch of the 2019 tree; the original tree is kept, unmodified, under `legacy/`.

## How it worked originally

`docs/original/` (cited to `legacy/`): [hardware](original/hardware.md),
[gateware](original/gateware.md), [clocking](original/clocking.md),
[firmware](original/firmware.md), [boot-and-flash](original/boot-and-flash.md),
[pi-software](original/pi-software.md), [factory-test](original/factory-test.md),
[rebuild-2019](original/rebuild-2019.md).

## How it works now

`docs/current/`: [repl-contract](current/repl-contract.md),
[pi5-programming](current/pi5-programming.md),
[pi5-rp1-pio-jtag](current/pi5-rp1-pio-jtag.md),
[hdmi-input-port](current/hdmi-input-port.md),
[hdmi-audio-extract](current/hdmi-audio-extract.md),
[hdcp-receiver-build](current/hdcp-receiver-build.md). Modern targets live in
`netv2/targets/` (base, pcie, hdmi_in, hdmi_audio_in, ethernet); ported gateware in
`netv2/gateware/`.

## How it was tested

`docs/testing/` and `docs/testing/reports/`: the golden-unit baseline
(`2026-09-baseline`, 29 pass on the stock board), and the modern hardware runs
(`2026-09-phase2-rpi5` memtest, `2026-09-phase6-pcie`, `2026-09-phase8-eth`).
Simulation: `tests/sim/` (video/audio, HDCP cipher) and `tests/unit/`. The test
suite that runs on the attached Pi is `tests/hdmi-suite/` (also `mithro/netv2-testsuite`).

## Design and plans

`docs/superpowers/specs/` (modernisation design, HDCP receiver design) and
`docs/superpowers/plans/`. Dated progress log: `LOG.md`.

## What still needs a person

- **PCIe**: verify the NeTV2 edge-to-Pi-5 FPC wiring (lane0 TX/RX, REFCLK, PERST# to
  FPGA pin E18) — the endpoint is built and loaded but the link stays in Detect.
- **HDMI audio on hardware**: go-ahead for a volatile load on the golden Pi 3, which
  has the HDMI source + capture rig.
- **Pi 3B+ trixie target**: access to the netboot nodes (the `tweed` host key changed).

Safety throughout: the golden `rpi3-netv2` is never SPI-flashed, rebooted, or
re-imaged; all hardware loads are volatile SRAM on the non-golden Pi 5.
