# Step 4 — force-encrypt attempts (in progress)

Setup: rpiz-3 source shows color bars; NeTV2 passes through (Km_valid=0); capture
luma entropy discriminates clean (~4.1 bits, structured) vs encrypted (~8 bits, noise).

Baseline clean: entropy 4.10, var 8152, distinct 254.

Attempts (all still CLEAN — encryption not engaging):
1. `encrypt` (RDB force auth): load 40 keys via 0x809000, write BKSV=0xAAAAAAAAAA
   (BKSV_VALID asserts), CP_TST ext-An+force-key, ENABLE_KU, I_SET_RDB_AUTHENTICATED
   -> CP_STATUS=0x80000016 (AUTH_OK|RDB_AUTH|HDCP_READY). Capture entropy 4.05 = CLEAN.
2. `encrypt2` (AUTH_REQUEST then SET_RDB): AUTH_REQUEST generates a random An
   (readable at AN0/1) and sets AN_READY; SET_RDB -> AUTH_OK. Capture 4.10 = CLEAN.
3. `enc_sched`: as (2) + SCHEDULER_CONTROL.ENC_ONLY_WHEN_AUTH[6]=1 (0xcb02b->0xcb06b).
   Capture 4.14 = CLEAN.

Key diagnostic: **CP_INTEGRITY (Ri) stays static at 0x1414ec00** across all attempts
-> the HDCP cipher is NOT being clocked/advanced per frame, i.e. not actually running.
So the CP engine's *authenticated status* can be forced, but the cipher/encoder is not
yet encrypting pixels. Missing: the exact "initialize + start cipher / route encoder
through HDCP" trigger. Candidate regs not yet cracked: HDMI_ENCODER_CTL(0x70)=0,
SCHEDULER_CONTROL(0xc0) MODE_REQ/MODE_ACTIVE, HDMI_CPU_* processor, RDB key-load path
(CP_CONFIG.I_ENABLE_RDB_KEY_LOAD + HDCP_KEY_1/2). Needs the Broadcom bhdm_hdcp.c
sequence to resolve deterministically.
