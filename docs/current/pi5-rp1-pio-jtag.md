> Imported 2026-09-05 from ten64:~/local/netv2/docs (written 2026-02-22). Facts below reflect that date; the rpi5-netv2 OpenOCD now has the linuxgpiod driver compiled in (verified 2026-09-05).

# RP1 PIO for High-Speed JTAG

## Background

The Raspberry Pi 5's RP1 chip contains a PIO (Programmable I/O) subsystem nearly identical to the RP2040's. This can run autonomous state machines that bit-bang JTAG at hardware speeds (up to 50 MHz), bypassing the PCIe latency that cripples software GPIO bit-banging (~13 kB/s via linuxgpiod, ~similar via sysfsgpio).

## Current State on Our RPi 5

Verified on `rpi5-netv2` (10.1.10.14):

| Component | Status |
|-----------|--------|
| `/dev/pio0` | Present (crw-rw---- root:gpio) |
| `rp1_pio` kernel module | Loaded |
| `rp1_fw` kernel module | Loaded |
| `tim` in gpio group | Yes (no sudo needed for PIO access) |
| PIOLib (userspace library) | **Not installed** — need to build from source |
| `pioasm` (PIO assembler) | **Not installed** — need to build |

## RP1 PIO Architecture

- **1 PIO block** with **4 state machines** and **32-entry instruction memory**
- **8-entry FIFOs** per state machine (doubled vs RP2040's 4)
- **200 MHz system clock** (5 ns per instruction)
- Same instruction set as RP2040 (JMP, WAIT, IN, OUT, PUSH, PULL, MOV, IRQ, SET)
- PIO config registers only accessible via RP1 firmware mailbox (not direct PCIe)
- FIFO data accessible from host via ioctl/DMA

## Performance Comparison

| Method | JTAG Throughput | Notes |
|--------|----------------|-------|
| Pi 4 bcm2835gpio | >40 kB/s | Direct register mmap, fast |
| Pi 5 linuxgpiod | ~13 kB/s | Each GPIO toggle crosses PCIe |
| Pi 5 sysfsgpio | Similar to linuxgpiod | Deprecated sysfs interface |
| **RP1 PIO (estimated)** | **0.5-3 MB/s** | **50-200x improvement** |

## Approach: PIO-Based JTAG Daemon

### Architecture

```
┌──────────┐     XVC/remote_bitbang     ┌───────────────┐
│ OpenOCD  │ ◄────── TCP ──────────────► │  PIO JTAG     │
│ or       │                             │  daemon       │
│ Vivado   │                             │  (userspace)  │
└──────────┘                             └───────┬───────┘
                                                 │ ioctl
                                         ┌───────┴───────┐
                                         │  /dev/pio0    │
                                         │  rp1_pio.ko   │
                                         └───────┬───────┘
                                                 │ mailbox
                                         ┌───────┴───────┐
                                         │  RP1 PIO HW   │
                                         │  state machine│
                                         │  @ 200 MHz    │
                                         └───────┬───────┘
                                                 │ GPIO
                                         ┌───────┴───────┐
                                         │  FPGA JTAG    │
                                         │  TCK/TMS/     │
                                         │  TDI/TDO      │
                                         └───────────────┘
```

### Protocol Options

1. **XVC (Xilinx Virtual Cable)**: TCP server on port 2542. Vivado and OpenOCD both support it (`xlnx_pcie_xvc` driver). This is ideal for Xilinx FPGAs.

2. **remote_bitbang**: OpenOCD's generic TCP-based bitbang protocol. Simpler but lower level.

3. **Custom OpenOCD adapter driver**: Highest performance but requires modifying OpenOCD source.

### Reference PIO Programs

The `pico-dirtyJtag` project has a proven JTAG PIO program that can be adapted:

```asm
; From pico-dirtyJtag/jtag.pio (simplified)
; TCK is side-set pin, TDI is OUT pin, TDO is IN pin
.program djtag_tdo
.side_set 1 opt
    pull                          ; get bit count from TX FIFO
    out x, 32        side 0      ; load bit count, TCK low
loop:
    out pins, 1      side 0      ; output TDI, TCK low
    nop              side 1      ; TCK high (rising edge)
    in pins, 1       side 1      ; sample TDO on rising edge
    jmp x-- loop     side 0      ; TCK low, loop
    push             side 0      ; flush TDO data to RX FIFO
```

This runs at `sys_clk / (4 instructions per bit)` = 50 MHz max on RP1. Practical limit ~5-25 MHz depending on FPGA's JTAG TCK spec.

### Implementation Plan

1. **Build PIOLib** from `raspberrypi/utils` repo on the Pi
2. **Port the JTAG PIO program** from pico-dirtyJtag to RP1 PIO format
3. **Write XVC server daemon** in C using PIOLib for PIO control
4. **Test with OpenOCD** using the `xlnx_pcie_xvc` adapter driver (already compiled in our OpenOCD)
5. **Benchmark** vs sysfsgpio

### Key Considerations

- **PIO resource contention**: Check no kernel driver has claimed state machines (`rp1sm` utility can inspect)
- **GPIO group access**: tim is in `gpio` group, so `/dev/pio0` is accessible without sudo
- **FIFO management**: 8-entry FIFOs give good buffering; PIO program must handle variable-length scan chains
- **Multiple state machines needed**: May need separate SMs for TDI-only shifts vs TDI+TDO shifts

## Software Dependencies to Build

```bash
# On the RPi 5:
sudo apt install cmake build-essential git

# Clone and build PIOLib + pioasm
git clone https://github.com/raspberrypi/utils.git
cd utils
cmake -B build -S . -DCMAKE_BUILD_TYPE=Release
cmake --build build --target piolib pioasm
```

## References

- [PIOLib source](https://github.com/raspberrypi/utils/tree/master/piolib)
- [PIOLib announcement](https://www.raspberrypi.com/news/piolib-a-userspace-library-for-pio-control/)
- [pico-dirtyJtag JTAG PIO program](https://github.com/phdussud/pico-dirtyJtag/blob/master/jtag.pio)
- [xvc-pico (XVC server on RP2040)](https://github.com/kholia/xvc-pico)
- [RP1 peripherals datasheet](https://datasheets.raspberrypi.com/rp1/rp1-peripherals.pdf)
- [RP1 PIO kernel support](https://github.com/raspberrypi/linux/pull/6470)
- [RP1 PIO DMA performance](https://forums.raspberrypi.com/viewtopic.php?t=390556)
