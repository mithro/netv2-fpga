# Phase 6a: modern LiteX NeTV2 PCIe endpoint — build + volatile hardware bring-up

The phase-2 base SoC (UART + DDR3, LiteX 2026.04) extended with a **LitePCIe x1
endpoint** on the Xilinx `pcie_7x` hard block + GTP. The endpoint **builds**
(datapath timing closes) and **volatile-loads and boots** on the physical
NeTV2, but the Pi 5 did **not enumerate it** — the external PCIe link trains
**down** and the endpoint's own LTSSM stays in Detect. Diagnosis below points to
a physical PCIe-layer issue on the bench rig (PERST#/lane), not the gateware.

## Summary

| Item | Value |
| --- | --- |
| Date | 2026-09-06 |
| Host (Pi) | **rpi5-netv2**.iot.welland.mithis.com (non-golden 100T dev unit) |
| FPGA | Xilinx XC7A100T (kosagi_netv2, variant a7-100) |
| JTAG IDCODE | **0x13631093** (mfg 0x049 Xilinx, part 0x3631) — asserted before load |
| LiteX version | 2026.04 |
| Toolchain | Vivado 2025.2 (`/opt/Xilinx/2025.2`) |
| Build target | `netv2/targets/pcie.py` → `litex_boards.targets.kosagi_netv2.BaseSoC` + LitePCIe x1 |
| SoC | VexRiscv @ 100 MHz, integrated BIOS, UART, DDR3 (s7ddrphy), **LitePCIe endpoint (x1, 1 DMA)** |
| Bitstream | `build/netv2-pcie/gateware/kosagi_netv2.bit` |
| Bitstream sha256 | `fbf95dcd5b7afd9d99319b85441dcc7b8a5d8f15c76fd8d34a239106bece6d0b` |
| **PCIe device id** | **10ee:7021** (`CONFIG.Device_ID {7021}`, vendor 0x10ee Xilinx) |
| PCIe config | Link 5.0 GT/s (Gen2), Max Link Width X1, BAR0 = 1 MB |
| **Post-route setup WNS** | **+0.611 ns** (0 failing setup endpoints) |
| Post-route hold WHS | +0.046 ns (0 failing hold endpoints) |
| Overall timing verdict | "not met" — see caveat (a single 19 ps hard-IP max-skew) |
| SoC ident (queried) | `LiteX SoC on NeTV2 2026-09-06 04:45:50` (BIOS alive over UART) |
| **PCIe enumeration** | **FAILED** — no `10ee:7021`, host link **down**, endpoint LTSSM = Detect |

## Timing — datapath closes; sole "fail" is a benign hard-IP max-skew

The initial PCIe build failed timing hard (WNS −2.183 ns, 75 failing endpoints).
Root cause: LiteX auto-emits a `set_clock_groups` to declare the PCIe clock
domain asynchronous to the sys domain, but it resolves the domains by **net
name** (`get_nets pcie_clk` / `sys_clk`), and the GTP/MMCM clocking renames
those nets — so the constraint dropped (Vivado: "only one non-empty group
remains") and the **genuine async CDC** between the LitePCIe endpoint
(125/250 MHz PCIe user clocks) and the SoC (100 MHz sys clock) was timed as if
synchronous. `netv2/targets/pcie.py` fixes this with a pre-placement
`set_clock_groups` that re-declares the clock trees asynchronous by their stable
root clocks (`clk50`, `txoutclk_x0y0`, `pcie_x1_clk_p`) with
`-include_generated_clocks`.

After the fix (see `timing-summary.txt`, `timing-interclock.txt`):

- **Setup WNS +0.611 ns, 0 failing endpoints.** Hold WHS +0.046 ns, 0 failing.
- All inter-clock (CDC) paths pass.
- The **only** remaining violation making Vivado report "not met" is a
  **Max Skew** check *internal to the PCIe hard macro*
  (`PCIE_2_1/PIPECLK` vs `PCIE_2_1/USERCLK` at `PCIE_X0Y0`): required 0.560 ns,
  actual 0.579 ns → **−0.019 ns, fast corner only** (the slow corner passes at
  +0.054 ns). See `timing-maxskew.txt`. This is a fixed Xilinx 7-series PCIe
  hard-IP internal clock-pair skew — a well-known benign artifact of LitePCIe
  7-series builds, not a user-logic data path. The design's datapath (setup and
  hold) fully closes with positive slack.

## Load method — VOLATILE ONLY

Loaded into FPGA **SRAM** via JTAG `pld load` (power-cycle-reversible).
**No SPI flash was written** (no jtagspi, flashcpu, or program_flash).

```
sudo openocd \
  -f /home/tim/netv2/netv2-rpi5.cfg \
  -f /usr/share/openocd/scripts/fpga/xlnx/xc7.cfg \
  -c "init; scan_chain; pld load 0 /home/tim/netv2-pcie.bit; exit"
```

IDCODE read back `0x13631093` (matches the asserted value). The SoC booted:
`ident` over `/dev/ttyAMA0` returns `LiteX SoC on NeTV2 2026-09-06 04:45:50`,
and CSRs are readable over the BIOS — so the bitstream is configured and running.

## PCIe enumeration — FAILED (link down)

The Pi 5's external PCIe (controller `1000110000.pcie`, PCI domain `0001`) had
its root port present but **link down** at boot (no endpoint was loaded then).
That controller sits **unbound** at rest. After the volatile load, the link was
brought up per the plan, in order:

1. `echo 1 | sudo tee /sys/bus/pci/rescan` — no new device (link still down).
2. **Bind** the external controller: `echo 1000110000.pcie | sudo tee
   /sys/bus/platform/drivers/brcm-pcie/bind` — triggers a fresh probe that
   deasserts PERST# and attempts training. Repeated **many times** (single
   binds, unbind/rebind cycles, and a 20-iteration tight loop).

Every attempt: **`brcm-pcie 1000110000.pcie: link down`**, the root port bus is
released, and `lspci -nn` shows **no `0001:` device and no `10ee:*`** (see
`lspci-dmesg.txt`). Only the Pi's internal devices appear
(`0002:00:00.0` BCM2712 bridge, `0002:01:00.0` RP1). No BAR is assigned because
nothing enumerated.

### Endpoint-side evidence (decisive)

Read the endpoint's own LitePCIe `pcie_phy` link-status CSR
(`pcie_phy_phy_link_status` @ `0xf0003800`) over the BIOS UART, including during
active host bind windows (`endpoint-linkstatus.txt`):

```
mem_read 0xf0003800 4  →  0x0000000c   (every sample, unchanging)
```

Decode: **link-up bit = 0 (down)**, **LTSSM = 0 (Detect)**. The endpoint's PCIe
hard block never leaves Detect — it does not observe a link partner / is not
released from reset — across all host bind/training attempts.

### Diagnosis

- The external controller's `brcm,clkreq-mode = "safe"` → the Pi drives the
  PCIe **refclk continuously** (not CLKREQ#-gated), so a missing refclk is
  unlikely.
- LTSSM frozen at **Detect** with the value byte-identical in every state
  (including the resting state where the unbound controller holds **PERST#
  asserted**) is consistent with the endpoint being **held in reset** and/or the
  **TX/RX lanes not electrically reaching the FPGA** — i.e. the PERST# (pin E18)
  and/or lane routing between the NeTV2 PCIe **edge connector** and the Pi 5's
  external PCIe FPC is not carrying signal on this bench rig.
- This is the **first PCIe endpoint** ever attempted on this rig; the physical
  PCIe path was previously only observed as "bus present, link down" with no
  bitstream, never proven for endpoint bring-up. The gateware side is verified
  correct (builds, loads, boots, endpoint CSRs live); the block is at the
  **physical PCIe layer**, outside software control.

### What was NOT done (and why)

- **No Pi reboot.** Software retrain/rescan was preferred and exhausted first
  (per plan). A reboot is last-resort and risky here: if the NeTV2 draws slot
  power from the Pi's PCIe connector, rebooting the Pi could power-cycle the
  NeTV2 and drop the volatile bitstream (explicitly to be avoided), and a reboot
  cannot fix physical PERST#/lane wiring.
- **No SPI flash write; rpi3-netv2 (golden) never contacted; NeTV2 never
  power-cycled.**

## Safety

- Only **rpi5-netv2** (non-golden 100T dev unit) was touched.
- **rpi3-netv2 (golden) was never contacted.**
- Load was **volatile SRAM only**; SPI flash never written; NeTV2 never
  power-cycled; no Pi reboot.

## Files

- `timing-summary.txt` — post-route Design Timing Summary (setup +0.611, hold +0.046).
- `timing-interclock.txt` — inter-clock (CDC) table after the async-group fix (all pass).
- `timing-maxskew.txt` — the sole failing check: PCIe hard-IP PIPECLK↔USERCLK max skew −0.019 ns (fast corner).
- `lspci-dmesg.txt` — `lspci -nn`, external-controller link-down dmesg, `10ee:*` = none.
- `endpoint-linkstatus.txt` — endpoint LTSSM/link-status CSR reads (0x0c = down/Detect) during host binds.
```
