# NeTV2 HDCP receiver gateware

Patched HDCP cipher gateware for the NeTV2 HDCP-1.x receiver (see the design of
record `docs/superpowers/specs/2026-09-06-hdcp-receiver-design.md`, sections 5.1
and 5.2, and the plan `docs/superpowers/plans/2026-09-06-hdcp-receiver-plan.md`,
task H1).

## Files

| File | What it is |
|---|---|
| `hdcp_cipher_rx.v` | A **renamed copy** of `legacy/overlay/hdcp_cipher.v`, patched to expose R0/Ri. |

### The originals in `legacy/overlay/` are untouched

`hdcp_cipher_rx.v` is a copy; the original `legacy/overlay/hdcp_cipher.v` is
**never edited**, so the receiver variant and the 2019 `netv2mvp.py` baseline can
coexist in one build and stay bit-comparable. The module is renamed
`hdcp_cipher` -> `hdcp_cipher_rx`. Its dependencies
(`hdcp_block.v`, `hdcp_lfsr.v`, `diff_network.v`, `shuffle_network.v`) are reused
from `legacy/overlay/` unmodified.

### The patch

bunnie's cipher shifts `ostream[15:0]` into `Mi` over the `BLOCK_8`/`BLOCK_9`/
`GET_M` warm-up window and **discards `ostream[23:16]`**, which is exactly where
R0/Ri live (HDCP 1.4 Table 4-11). The patch adds, changing nothing else:

* `output [15:0] Ri` — a 16-bit register that shifts in `ostream[23:16]` over the
  identical window and cadence as `Mi`, so its final two shifts land in warm-up
  clocks 55 and 56, giving `Ri[15:8]=ri[15:8]` then `Ri[7:0]=ri[7:0]`.
* `output R0_valid` — a one-cycle strobe on the `GET_M -> STREAM` transition,
  asserted in the first `STREAM` cycle (one cycle before `stream_ready`), by which
  point `Ri` is stable.

Distinguishing R0 from per-frame Ri (the `auth_mode` latch of design section 5.2)
happens later in `hdcp_mod_rx.v`; this file only exposes the raw capture.

## Verification (task H1 exit gate)

`Ri` is proven bit-exact against the reviewed Python reference model
`netv2/hdcp/cipher.py` (the oracle) in Vivado `xsim`:

```
uv run python tests/sim/hdcp/run_cipher_rx.py
```

This driver sources the Vivado 2025.2 environment itself (it does **not** need
Vivado already on `PATH`), generates golden vectors from the oracle, builds
`hdcp_cipher_rx.v` + the unchanged legacy deps + `tests/sim/hdcp/tb_cipher_rx.v`,
runs the authentication block cipher then 256 rekey frames for each (Km, An)
vector, and checks the RTL R0 and the frame-128/256 Ri equal the model. It prints
`PASS` and exits 0 only when every value matches. Build artifacts land in
`tests/sim/hdcp/work/` (git-ignored).

Test files:

* `tests/sim/hdcp/gen_cipher_vectors.py` — golden vectors from the oracle.
* `tests/sim/hdcp/tb_cipher_rx.v` — the testbench.
* `tests/sim/hdcp/run_cipher_rx.py` — the build/sim/compare driver.
