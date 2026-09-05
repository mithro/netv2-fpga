# netv2_hdcp_ctl.py -- host-side HDCP receiver control

A small, dependency-light tool that loads the NeTV2 HDCP receiver's 40 sink
device keys and reads back its state over the FPGA's LiteX BIOS serial console
(`mr` / `mw` memory commands). It is the host end of task H7.

## Why it exists: the Aksv read-back

The Raspberry Pi source (BCM2835) has **no writable Aksv register**. It
transmits whatever KSV its (blank-OTP) provisioning yields, which may be
all-zeros, non-balanced, and is **not guaranteed** to equal any provisional
`KSV_source`. The receiver accepts and latches whatever Aksv it sees.

`netv2_hdcp_ctl.py status` prints that latched value as
**`received Aksv (A_actual)`** (CSR `hdcprx_aksv`) so the RPi side can capture
`A_actual` on the first handshake and regenerate matching `source_keys`. This
is the step that closes the provisioning loop.

## Runtime environment

Runs on the golden-unit rig **rpi3-netv2** (Raspbian 9, CPython **3.5**) over
**`/dev/ttyS0`**. It is written to be Python 3.5-compatible on purpose: only
the standard library and `pyserial` are used -- no f-strings, no `dataclasses`,
no walrus operator. On a Pi 5 the console is usually `/dev/ttyAMA0`.

(The development repo's interpreter is CPython 3.13, so `py_compile` here only
proves the syntax is valid; the 3.5 constraint is honoured by construction.)

## The CSR map and word order

Register addresses and sub-word counts are **parsed from `csr.csv`** (default
`legacy/build/hdcprx-35/csr.csv`, override with `--csr`) rather than
hard-coded, so a SoC rebuild that shifts the map is picked up automatically.

A LiteX CSR wider than the CSR bus word is split into several sub-registers at
consecutive word addresses (stride 4 bytes), **most-significant word first**.
This build uses a **byte-wide CSR bus** (`csr_data_width = 8`): `csr.csv` lists
the 40-bit `hdcprx_bksv` with 5 sub-words (40 / 8), `hdcprx_an` (64b) with 8,
`hdcprx_km_hw` (56b) with 7. See the module docstring for the citation in
`legacy/deps/litex/litex/soc/interconnect/csr.py` and
`.../integration/cpu_interface.py`. Each `mr` word carries the byte in its low
8 bits; reads are masked to the bus word before assembly.

## Commands

```
netv2_hdcp_ctl.py [--port /dev/ttyS0] [--csr PATH] [--baud 115200] <command>
```

- `load-keys --keys sink_keys.bin --manifest manifest.json`
  Reads the 40 x 7-byte little-endian sink keys and, per index, writes
  `key_index`, `key_data_lo` (low 32b), `key_data_hi` (high 24b) and pulses
  `key_we`; sets `bksv` from the manifest's `ksv_sink`; then reads
  `keys_loaded` and fails unless it is 40. **Never prints key bytes.**
- `arm` -- set `km_source = 1` and `rx_enable = 1`.
- `status` -- print `keys_loaded`, `rx_enable`, `km_source`, `Bksv`, the
  received Aksv (labelled `A_actual`), `An`, `R0'`, `Ri'`, and the decoded
  `status` bits (`rx_armed`, `keys_ok`, `km_valid`, `r0_valid`, `sda_driving`).
  `km_hw` is the shared secret and is **masked by default**; pass `--show-km`
  to reveal it.
- `clear` -- pulse `keys_clear`.

## Example (on the rig)

```
# load keys, then arm and check that A_actual came through
python3 netv2_hdcp_ctl.py --port /dev/ttyS0 \
    load-keys --keys ~/netv2-hdcp-handoff/keys/sink_keys.bin \
              --manifest ~/netv2-hdcp-handoff/keys/manifest.json
python3 netv2_hdcp_ctl.py --port /dev/ttyS0 arm
python3 netv2_hdcp_ctl.py --port /dev/ttyS0 status
```

## Tests

Hardware-free unit tests use a dict-backed `MockConsole` (no serial, no real
key material -- a synthetic in-test blob):

```
uv run pytest tests/unit/test_hdcp_ctl.py -q
```
