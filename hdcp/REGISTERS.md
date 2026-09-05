# BCM2835 HDCP register + field map (authoritative)

Sources: Broadcom RDB headers (rpi-open-firmware `broadcom/bcm2708_chip/{hdcp,hdmicore}.h`)
for addresses; GPL Broadcom STB `bchp_hdmi.h` (BCM7340) for bit-fields. They agree.

## Key-RAM loader @ VC 0x7e809000 (ARM-phys 0x20809000)
- `KEY_CTL   +0x00`  START[0], DONE[1], DISHDCP[2]
- `KEY_ADR   +0x04`  8-bit key index
- `KEY_KY0   +0x08`  key bits [31:0]
- `KEY_KY1   +0x0c`  key bits [55:32] (24-bit)   -> one 56-bit device key per index

## Cipher/auth engine @ VC 0x7e902000 (ARM-phys 0x20902000)
- `BKSV0 +0x10 / BKSV1 +0x14`   sink KSV (write to inject a fake sink; 20/40 ones)
- `AN0 +0x18 / AN1 +0x1c`       session An (read; or external via TST_AN)
- `TST_AN0 +0x28 / TST_AN1 +0x2c`  external An input (used when CP_TST.I_TST_EXTERNAL_AN_ENABLE)
- `AN_INFLUENCE_1/2 +0x20/24`
- `KSV_FIFO_0/1 +0x30/34`       repeater downstream KSV list
- `HDCP_KEY_1 +0x3c`  I_KEY_NUM_5_0[5:0] + I_KEY_23_0[31:8]   (alt/RDB key path)
- `HDCP_KEY_2 +0x40`  I_KEY_55_24[31:0]
- `HDCP_CTL +0x44`  (mask 0x0001030f)
    [0]  I_AUTH_REQUEST              start real authentication
    [1]  I_CLEAR_RDB_AUTHENTICATED
    [2]  I_SET_RDB_AUTHENTICATED     ** force core authenticated (no R0 exchange) **
    [3]  I_FORCE_CORE_UNAUTHENTICATED
    [8]  I_INIT_REPEATER
    [9]  I_FORCE_VCALC
    [16] I_RESET_KU
- `CP_STATUS +0x48`  (mask 0x8000031f, reset 0x00000100)
    [0] O_AN_READY  [1] O_BKSV_VALID  [2] RDB_AUTHENTICATED  [3] CORE_AUTHENTICATED
    [4] AUTHENTICATED_OK  [8] O_REPEATER_IS_BUSY  [9] O_V_MATCH  [31] HDCP_READY
- `CP_INTEGRITY +0x4c`             Ri link-integrity value
- `CP_INTEGRITY_CFG +0x50`  I_RATE[7:0], J_RATE[15:8], I_ALWAYS_REKEY_ON_VSYNC[16]
- `CP_CONFIG +0x54`  (mask 0x7fffffff)
    [9:0] I_KEY_BASE_ADDRESS  [10] I_ENABLE_RDB_KEY_LOAD  [11] I_MUX_VSYNC
    [12] I_FILTER_CTL_3_EN  [13] I_FILTER_GENERAL_CONTROL_PACKET_EN
    [18:14] I_WIN_OF_OPP_THRESHOLD  [19] I_ENABLE_KU_COMPUTATION
    [20] AN_INFLUENCE_MODE  [30:21] RANDOM_BIT_SAMPLE_PERIOD
- `CP_TST +0x58`  (mask 0x002001ff)
    [0] I_TST_FORCE_ISLAND_ALL_ZEROS  [1] I_TST_FORCE_VIDEO_ALL_ZEROS
    [2] I_TST_FORCE_ISLAND_ALL_ONES   [3] I_TST_FORCE_VIDEO_ALL_ONES
    [5:4] I_TST_AN_SEL  [6] I_TST_MODE_AN_ENABLE
    [7] I_TST_EXTERNAL_AN_ENABLE  ** use TST_AN as An **
    [8] I_TST_FORCE_KEY_VALID    ** bypass key validation **
    [21] I_TST_ENABLE_O_RANDOM_BIT

## NeTV2 decode side (LiteX CSRs, via console `mr`/`mw`; hdcp csr region)
From `netv2-fpga/netv2mvp.py` + `overlay/hdcp_mod.v`:
- `hdcp.Km` = CSRStorage(56)     shared secret Km (we compute & load)
- `hdcp.Km_valid` = CSRStorage() gates the decrypt XOR; proxy for "HDCP initialized"
- `hdcp.Aksv_mode` = CSRStorage()  0=auto (snoop DDC), 1=manual
- `hdcp.Aksv_manual` = CSRStorage() pulse to trigger cipher rekey/init (manual mode)
- `hdcp.hpd_ena` = CSRStorage()  drives hdmi_rx0_forceunplug
- An is HARDWIRED from i2c_snoop (DDC 0x74). No CSR -> defaults 0 with no snoop.
- hdcp_ena auto-detected from incoming TMDS (decode_terc4.encrypting_video/data).
- decrypt: out_rgb ^= cipher_stream, gated on Km_valid.

## Controlled encrypt->decrypt plan (no real sink, no master key)
Pi (source): load 40 arbitrary keys; write a balanced BKSV; TST_AN=chosen An (e.g. 0)
+ CP_TST.I_TST_EXTERNAL_AN_ENABLE; CP_CONFIG.I_ENABLE_KU_COMPUTATION (+ RDB key load);
CP_TST.I_TST_FORCE_KEY_VALID; HDCP_CTL.I_SET_RDB_AUTHENTICATED -> engine encrypts.
NeTV2 (sink): Aksv_mode=1; load Km = same value the Pi's cipher uses; Km_valid=1;
pulse Aksv_manual to init cipher; decrypt XOR recovers the image.
Verification: capture goes noise (encrypt on, Km wrong) -> clean (correct Km).
