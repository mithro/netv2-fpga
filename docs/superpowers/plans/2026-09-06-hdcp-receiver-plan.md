# HDCP receiver implementation plan

> Sequences the reviewed design spec `docs/superpowers/specs/2026-09-06-hdcp-receiver-design.md`
> (v as merged, 666 lines) into ordered tasks. The spec is the design of record; this file is
> task sequencing and exit criteria only, so it did not get a separate plan-review cycle — the
> spec was reviewed and approved to implement. Executed subagent-driven on branch `hdcp-receiver`.

**Goal:** an HDCP-1.x receiver on NeTV2 hdmi_in0 so the RPi transmitter authenticates against the
NeTV2 (DoD 1) and emits encrypted video that a capture shows as noise (DoD 2). DoD 3 (a passthrough
decryptor across the split pix/pix_o MMCMs) is explicitly a later, separate step.

**Non-negotiable bounds (spec §10.3):** no bitstream is loaded on `rpi3-netv2` without Tim's
explicit go-ahead; only volatile SRAM JTAG loads there, stock `user-35.bit` kept as recovery; the
35T bitstream is never loaded while it has negative slack. Hardware target is the **100T** until the
35T baseline closes timing. All keys come from `~/netv2-hdcp-handoff/keys/`; no key `.bin` is ever
committed; no real DCP key material.

**Oracle:** `netv2/hdcp/cipher.py` (the reviewed Python HDCP 1.4 model) is the reference every RTL
test checks against. Simulation with Vivado `xsim` from `/opt/Xilinx/2025.2`.

Files live under `netv2/gateware/hdcp/` (new); the original `legacy/overlay/*.v` are never edited —
patched copies are made. Branch `hdcp-receiver` off `modern`; each task commits small with the
standard trailers; a four-direction review runs before the branch merges.

## Tasks

### H1 — cipher patch exposing R0/Ri, verified against the oracle (pix_o domain)
Copy `legacy/overlay/hdcp_cipher.v` to `netv2/gateware/hdcp/hdcp_cipher_rx.v`; add a 16-bit `Ri`
output register that shifts `ostream[23:16]` in the same `BLOCK_8`/`BLOCK_9`/`GET_M` window
(`statecnt` 55, 56) that the existing code uses to shift `ostream[15:0]` into `Mi`
(hdcp_cipher.v:176-182, 414-427 in hdcp_block terms), plus an `R0_valid` strobe on the
`GET_M -> STREAM` transition. Testbench `tests/sim/hdcp/tb_cipher_rx.v` driven by stimulus generated
from `netv2/hdcp/cipher.py`: for the shared keys' Km (0xf26625c3367e6e) and several An, assert the
RTL `Ri` after authentication equals the model R0, and Ri after 128 rekeys equals the model's
frame-128 Ri. **Exit:** `R0 == model` for all vectors in xsim (the capture-window gate, spec §5.1).

### H2 — I2C slave + receiver register file (eth domain)
`netv2/gateware/hdcp/hdcp_rx.v`: an I2C slave that ACKs only 0x74/0x75 via an open-drain
`sda_drive_low` output (never 0x50; foreign address -> wait-for-stop), read data shifted on
`SCL` falling edge (spec §2.4), register map of spec §3 (Bksv 0x00, Ri' 0x08, Pj' 0x0A, Aksv 0x10,
Ainfo 0x15, An 0x18, Bcaps 0x40=0x80, Bstatus 0x41=0x1000), pointer auto-increment, `rx_enable`
gating so it is inert at power-on. Testbench `tb_hdcp_rx_i2c.v` with an I2C master model: write
Aksv+An, read back Bksv/Bcaps/Bstatus (little-endian as the Pi parses them), read Ri'. **Exit:** all
reads correct; the slave never drives SDA when not addressed or when `rx_enable=0`.

### H3 — Km accumulator + key store (eth domain, LUTRAM)
40x56 sink-key store in distributed RAM (spec §4.1; the 35T is at 95% BRAM), loaded via CSRs
(index, data lo/hi, write strobe, `keys_loaded` count). On the last Aksv byte, a 40-cycle
accumulator sums the keys at Aksv's set bits mod 2^56 -> `Km_hw`, `Km_valid_hw`. Testbench loads
`sink_keys.bin`, drives Aksv=KSV_source, asserts `Km_hw == 0xf26625c3367e6e`; a half-loaded store
produces no `Km_valid_hw`; Aksv rewritten mid-accumulate restarts cleanly (spec §10.2 cases 5,6).

### H4 — migen wrapper `HDCPReceiver(Module, AutoCSR)` + CDC
Wrap H1-H3 with CSRs (sink KSV, key load, R0'/Ri'/auth-state readback, `km_source`, `rx_enable`);
wire the eth/pix_o/sys crossings of spec §7 including the `km_valid_hw` MultiReg; the
`_release_comb_driver` helper that removes netv2mvp.py's existing `hdmi_sda_over_dn.eq(0)` and
asserts exactly one assignment removed. Unit test the CDC helper and the CSR map in migen sim.

### H5 — bridge top level + Vivado 100T build
`legacy/netv2mvp_hdcprx.py`: import the 2019 `VideoOverlaySoC`, add `HDCPReceiver`, select the
hardware Km path (`km_source=1`), keep G20 (`hdmi_sda_over_up`) tied 0. Build a7-100 in the
`rebuild2019` container. **Exit:** builds; post-route WNS recorded; the new pix_o additions do not
push WNS materially past the 100T baseline. No 35T hardware bitstream is produced for loading.

### H6 — full handshake + encrypt/decrypt model test in xsim
`tb_hdcp_rx_top.v`: an I2C master model performs the full source handshake with the shared keys
against the integrated receiver, checks R0' == oracle, exercises the required edge cases (Ri' read
straddling an update stays consistent; pix_o unlocked at Aksv; lowest pixel clock), and a
cipher-level encrypt-then-XOR-decrypt round-trip. **Exit:** all pass; then update
`~/netv2-hdcp-handoff/STATUS.md` so the RPi side preps the Pi.

### H7 — firmware `hdcp` command group + host key loader
Firmware commands (key load, bksv, rx on/off, mode, status with the exact text format) and a
Python 3.5-compatible host tool that reads `sink_keys.bin`+`manifest.json` and loads keys over the
UART. Never store keys in a flash image.

### H8 — four-direction review, then STATUS.md handoff for the hardware attempt
Correctness, hardware safety (the golden-unit and never-load-negative-slack rules), security (key
handling, the DDC slave surface), docs/reproducibility. On pass, the branch is ready; the actual
hardware run waits for Tim's go-ahead and is DoD 1+2 only.

## Out of scope
DoD 3 passthrough decryptor; repeater support; HDCP 2.x; any real DCP keys; loading anything on
rpi3-netv2 without go-ahead.
