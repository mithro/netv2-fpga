# Phase 8: modern LiteX NeTV2 Ethernet control — build + volatile hardware bring-up

The phase-2 base SoC (UART + DDR3, LiteX 2026.04) extended with the NeTV2's
**RMII Ethernet PHY** under LiteX, wired for **control over Ethernet**:
hardware **Etherbone** (a Wishbone master over UDP, so `litex_server`/`litex_cli`
read and write the SoC's CSRs over the NeTV2's own RJ45) plus a CPU-visible
**LiteEth MAC** sharing the UDP crossbar (`add_etherbone(..., with_ethmac=True)`,
design-spec decision 14).

**Result: full success.** The SoC builds (timing closed, eth domain closes),
volatile-loads and boots on the physical NeTV2, the FPGA↔RMII-PHY path is proven
over MDIO (PHY ID + link status read from the BIOS), the RJ45 **is** cabled and
the link is **up**, and **Etherbone works end-to-end**: a CSR was read *and*
written over the NeTV2 Ethernet from a remote host.

## Summary

| Item | Value |
| --- | --- |
| Date | 2026-09-06 |
| Host (Pi) | **rpi5-netv2**.iot.welland.mithis.com (non-golden 100T dev unit) |
| FPGA | Xilinx XC7A100T (kosagi_netv2, variant a7-100) |
| JTAG IDCODE | **0x13631093** (mfg 0x049 Xilinx, part 0x3631) — asserted before load |
| LiteX version | 2026.04 |
| Toolchain | Vivado 2025.2 (`/opt/Xilinx/2025.2`) |
| Build target | `netv2/targets/ethernet.py` → phase-2 `NeTV2BaseSoC` + `add_etherbone(with_ethmac=True)` |
| SoC | VexRiscv @ 100 MHz, integrated BIOS, UART, DDR3 (s7ddrphy), **LiteEthPHYRMII + Etherbone + CPU MAC** |
| Etherbone endpoint | MAC `0x1337320dbabe`, IP **10.0.11.2**, UDP port 1234 |
| CPU MAC endpoint | MAC `0x1337320dbabf`, IP 10.0.11.3 |
| Eth datapath | `data_width=32` (LiteX hybrid `with_sys_datapath`); RMII RX/TX in the 50 MHz `eth` domain |
| Bitstream | `build/netv2-eth/gateware/kosagi_netv2.bit` |
| Bitstream sha256 | `ade38764b8a13273f3e07f8e309d1b1a77da21a5fe8dc459add727b70af30047` |
| **Post-route setup WNS** | **+0.299 ns** (0 failing setup endpoints) |
| Post-route hold WHS | +0.043 ns (0 failing hold endpoints) |
| Overall timing verdict | **All user specified timing constraints are met** |
| **eth domain closes** | **yes** — `eth_rx_clk` WNS +1.378 ns, `eth_tx_clk` WNS +0.676 ns (0 failing) |
| SoC ident (queried) | `LiteX SoC on NeTV2 2026-09-06 07:51:07` |
| **RMII PHY (MDIO)** | Microchip/Micrel **KSZ8081**, PHY ID **0x00221561**, at MDIO addr 0 |
| **PHY link state** | **UP**, auto-negotiation **complete**, 100 Mbps full-duplex |
| **Etherbone over Ethernet** | **WORKS** — CSR read `0x12345678` and write/readback `0xdeadbeef` |

## Build — timing closes, eth domain closes

Vivado 2025.2, a7-100. Post-route (`timing-summary.txt`):

- **Setup WNS +0.299 ns, 0 failing endpoints** (24123 total). Hold WHS +0.043 ns,
  0 failing. "All user specified timing constraints are met."
- The **eth domain closes**: the RMII PHY RX/TX clocks (50 MHz, sourced from the
  sys-PLL `cd_eth` and driven onto the PHY `ref_clk` pad D17 via a DDROutput)
  report `eth_rx_clk` WNS **+1.378 ns** and `eth_tx_clk` WNS **+0.676 ns**, both
  0 failing endpoints. The 2019 design's `fast_eth=False` note ("100 MHz domain
  works but timing closure is hard", `legacy/netv2mvp.py:1197`) is moot here —
  the RMII stack runs at 50 MHz by construction and the sys-side hybrid datapath
  (100 MHz) is the tightest clock at +0.299 ns and still closes.
- Utilization (`utilization.txt`): LUTs 9072/63400 (14.31 %), FF 7893 (6.22 %),
  BRAM 46.5 tiles (34.44 %), DSP 4, IOB 90, PLLE2 1/6, MMCM 0/6, BUFG 6/32.
  Comfortably inside the 100T.

CSR map (`csr-eth.txt`): `ethphy` MDIO CSRs (`ethphy_mdio_w`/`_r`), the `ethmac`
core (SRAM slots, RX/TX regions at 0x80000000, IRQ), and the `etherbone`
Wishbone master are all present.

### On `data_width`

The delivered build uses `add_etherbone(data_width=32, with_ethmac=True)` — the
LiteX hybrid `with_sys_datapath` recipe (32-bit UDP/IP in sys, 8-bit RMII at
50 MHz bridged by the MAC CDC FIFOs). An earlier build used the default
`data_width=8`; it also built and closed timing (WNS +0.785 ns) and ICMP worked,
and its apparent Etherbone non-response was **a host-side test artifact** (source
UDP port — see the caveat below), not a gateware defect. `data_width=32` is kept
as the target default because it is the well-trodden hybrid datapath and is the
configuration proven end-to-end here.

## Load method — VOLATILE ONLY

Loaded into FPGA **SRAM** via JTAG `pld load` (power-cycle-reversible).
**No SPI flash was written** (no jtagspi, flashcpu, or program_flash). See
`openocd-load.txt`.

```
sudo openocd \
  -f /home/tim/netv2/netv2-rpi5.cfg \
  -f /usr/share/openocd/scripts/fpga/xlnx/xc7.cfg \
  -c "init; scan_chain; pld load 0 /home/tim/netv2-eth.bit; exit"
```

IDCODE read back `0x13631093`. The SoC boots (BIOS banner → DDR → `litex>`),
`ident` returns `LiteX SoC on NeTV2 2026-09-06 07:51:07`, and the BIOS `help`
lists the LiteEth command group (`mdio_read`, `mdio_write`, `mdio_dump`,
`netboot`) — i.e. the Ethernet core is enumerated (`bios-help-mdio.txt`).

## FPGA↔RMII-PHY proven over MDIO

Read from the BIOS over `/dev/ttyAMA0` (`mdio-phy-dump.txt`,
`bios-help-mdio.txt`). The PHY responds at **MDIO address 0**:

```
mdio_dump 0 8
0x00 0x3100   BMCR    : auto-neg enabled, 100 Mbps, full-duplex
0x01 0x786d   BMSR    : LINK UP (bit2), auto-neg COMPLETE (bit5), 10/100 capable
0x02 0x0022   PHYIDR1
0x03 0x1561   PHYIDR2
0x04 0x81e1   ANAR    : advertising 100/10 FD/HD + pause
0x05 0xc5e1   ANLPAR  : link partner present (auto-neg exchange succeeded)
```

- **PHY ID = 0x00221561** → OUI 0x0885, model 0x16, rev 0x1 =
  **Microchip/Micrel KSZ8081** (the NeTV2's RMII PHY). PHY addresses 1–7 read
  `0xffff` (no device), so the PHY is uniquely at address 0.
- **BMSR 0x786d**: link status bit set → **link UP**; auto-neg-complete bit set.
  This proves not just the FPGA↔PHY management (MDC/MDIO) path but a live
  negotiated link.

## Etherbone over Ethernet — WORKS (RJ45 is cabled)

The NeTV2's RJ45 is cabled to the rpi5 test rig's `eth-netv2` interface (link
up, matching the PHY BMSR). With that interface addressed on the SoC's subnet
(10.0.11.1/24), the SoC answers ICMP and Etherbone:

- **ICMP** (`ping.txt`): `ping 10.0.11.2` → 4/4 replies, ~0.39 ms — the LiteEth
  IP/ICMP stack, MAC, RMII PHY and cable all work end-to-end.
- **Etherbone probe** (`etherbone.txt`, `wire-capture.txt`): the core replies
  `pr=1` to the LiteX probe. A raw wire capture shows the SoC ARP for the host
  (from the Etherbone MAC `13:37:32:0d:ba:be`) and reply
  `UDP 10.0.11.2:1234 -> host:1234 payload=4e6f1244…` (byte[2]=0x12 → pr=1).
- **CSR read/write** (`etherbone.txt`) via `litex_server`+`litex_cli`:

```
litex_cli --read  ctrl_scratch  →  0xf0000004 : 0x12345678   (reset value)
litex_cli --write ctrl_scratch 0xdeadbeef
litex_cli --read  ctrl_scratch  →  0xf0000004 : 0xdeadbeef   (write took effect)
litex_cli --write ctrl_scratch 0x12345678                    (restored)
```

This is full **control over the Ethernet interface**: reading and writing SoC
registers over the NeTV2's own RJ45, no UART/JTAG bridge involved.

### Path used for the host test (test-rig specific)

The rpi5 rig cables the NeTV2 to the Pi's `eth-netv2` port, and the desktop
reaches the Pi over WireGuard (not the NeTV2 subnet). So the desktop's
`litex_server` was pointed at a tiny UDP relay on the Pi
(`software/udp_relay.py`, Pi:1234 → 10.0.11.2:1234) which bridges onto the
NeTV2 segment. On a host directly on the 10.0.11.0/24 segment,
`litex_server --udp --udp-ip 10.0.11.2` needs no relay.

### Caveat that cost the most debugging (recorded for reuse)

LiteEth's Etherbone core replies to the requester's **IP on the fixed UDP port
1234**, *not* the request's source port. A client must therefore **send from and
listen on port 1234** — which LiteX's `litex_server`/`CommUDP` already does. An
ephemeral-source-port probe gets no reply (the SoC's reply lands on host:1234,
where nothing listens, and the host returns ICMP port-unreachable). Any relay or
NAT in the path must **preserve port 1234 in both directions** (see the
single-socket `software/udp_relay.py`).

## Safety

- Only **rpi5-netv2** (non-golden 100T dev unit) was touched.
- **rpi3-netv2 (golden) was never contacted.**
- Load was **volatile SRAM only**; SPI flash never written; NeTV2 never
  power-cycled; no Pi reboot.
- The temporary 10.0.11.1/24 address added to the Pi's `eth-netv2` for the test
  was removed afterwards.

## Files

- `timing-summary.txt` — post-route timing (setup +0.299, hold +0.043; per-clock incl. eth_rx/eth_tx).
- `utilization.txt` — post-place utilization on the 100T.
- `csr-eth.txt` — generated CSR entries for ethphy (MDIO), ethmac and etherbone.
- `bitstream-sha256.txt` — sha256 of the delivered bitstream.
- `openocd-load.txt` — volatile `pld load` + IDCODE.
- `bios-help-mdio.txt` — BIOS `help`/`ident` and MDIO command captures over UART.
- `mdio-phy-dump.txt` — full MDIO register dump (PHY ID + link status) at addr 0.
- `ping.txt` — ICMP round-trip to 10.0.11.2 over the RMII PHY + cable.
- `etherbone.txt` — Etherbone probe reply + CSR read and write/readback.
- `wire-capture.txt` — raw AF_PACKET capture of the SoC's ARP + Etherbone reply.

## Host helpers (under `software/`)

- `phase8_eth_probe.py` — serial probe: boot capture + MDIO PHY scan/decode.
- `phase8_eth_rawcap.py` — dumb raw UART command capture (boot/help/ident/mdio).
- `eth_probe_direct.py` — dependency-free Etherbone probe (use `--bind-port 1234`).
- `udp_relay.py` — single-socket UDP relay preserving port 1234 (off-segment host).
- `eth_sniff.py` — minimal AF_PACKET wire sniffer.
