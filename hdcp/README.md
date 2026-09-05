# HDCP output on the BCM2835 (RPi Zero) — implementation work

Goal: produce HDCP-encrypted HDMI output from `rpiz-3` (BCM2835) that the NeTV2 can decode,
delivered as local Linux kernel patches. Background/feasibility analysis is in
`../docs/HDCP-ON-BCM2835-FEASIBILITY.md`.

Register map (Broadcom generated headers, cross-checked vs GPL STB header + RE map):
- **Key-RAM loader @ VC 0x7e809000 (ARM-phys 0x20809000):** KEY_CTL[START0/DONE1/DISHDCP2],
  KEY_ADR(8b index), KEY_KY0(32b), KEY_KY1(24b) => one 56-bit device key per index.
- **Cipher/auth engine @ VC 0x7e902000 (ARM-phys 0x20902000):** BKSV0/1@10/14, AN0/1@18/1c,
  KSV_FIFO@30/34, HDCP_KEY_1/2@3c/40, HDCP_CTL@44 (AUTH_REQ0/FORCE_VCALC9/RESET_KU16),
  CP_STATUS@48 (O_AN_READY0/HDCP_READY31), CP_INTEGRITY@4c, CP_CONFIG@54
  (KEY_BASE_ADDR[9:0]/ENABLE_RDB_KEY_LOAD10/ENABLE_KU_COMPUTATION19), CP_TST@58.

## Progress

### Step 1 (DONE) — read-only /dev/mem probe: are the blocks gated?
`hdcp/mmap_probe.py`, run as root on rpiz-3. Result (`hdcp/results/probe-01.txt`): **both blocks
respond; not gated.**
- Key-loader `KEY_CTL=0x00000002` (DONE set = idle/ready); KEY_ADR/KY0/KY1 read the "hdcp" APB
  signature (write-only regs).
- HDMI core `CORE_REV=0x600`; **`CP_STATUS=0x80000000` => HDCP_READY(bit31) asserted**;
  `CP_CONFIG=0x00130080`; `CP_INTEGRITY=0x1414ec00`. `/dev/mem` reaches the vc4-claimed core.
- Precondition confirmed earlier: OTP HDCP key rows blank; HSM clock live @163MHz.
- **Conclusion:** the power/enable-gating risk is retired — remaining work is driver logic
  (key load -> auth -> cipher enable), not silicon bring-up.

## Next steps
- Step 2: key-loader write/DONE handshake (load a key index, no encryption) — mechanism check.
- Step 3: read the downstream HDCP receiver (NeTV2 / capture path) BKSV over DDC 0x74; confirm
  what sink we authenticate against.
- Step 4: minimal authentication attempt; then cipher enable; then verify NeTV2 decode.
- Step 5: port the working sequence into a vc4 kernel patch set (local only).
