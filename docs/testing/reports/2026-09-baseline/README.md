# 2026-09 baseline HDMI test run

- **Date:** 2026-09-05
- **Host under test:** `rpi3-netv2` (`rpi3-netv2.iot.welland.mithis.com`) — the untouched 2018 NeTV2 reference unit.
- **Gateware/firmware under test:** stock, as-shipped. The FPGA was running the shipped SPI-NOR image (not reloaded or reflashed for this run); board DNA read back as `0058a44663258854`, and the expected IDCODE for this device is `0x0362D093` per `hosts.py`.
- **Test suite commit:** `cfc7df7` (`tests/hdmi-suite` at time of run), verified byte-identical to the copy running on the unit — `md5sum` of every file in `netv2test/*.py` matched between the repo and `~/netv2test/` on `rpi3-netv2`.
- **Result:** **PASS 29 / FAIL 0 / BLOCKED 0 / SKIP 3**

## Skipped tests

- **T23 (audio):** the NeTV2 MVP gateware has no HDMI audio path (video-only); the output carries no audio, so the capture RMS is legitimately 0. This is a documented gateware limitation, not a regression.
- **T29 (i2c snoop / EDID):** `i2c_snoop` watches the HDCP DDC port (0x74); the EDID DDC bus is at 0x50, and there is no HDCP source attached, so the snoop buffer is legitimately empty.
- **T90 (gaps):** genuine, known gaps on this rig/gateware combination — the HDCP engine and `debug km` path (no HDCP source available), and output1 / encoder / dma_writer / dma_reader / sdram_test paths that are not exercised by this rig's wiring. Documented in the suite README, not a regression.

BLOCKED can legitimately be nonzero on this rig due to the MS2109 USB capture card starving under load (a known, documented capture-path limitation); on this run it was 0. FAIL was 0, which is the pass/fail bar for this baseline.

## Service state around the run

| | pm2 `mm` | `lightdm` |
|---|---|---|
| Pre-run | `online` | `active` |
| Post-run | `online` (restarted by the suite's restore step) | `active` |

The suite's own teardown paused and then restored MagicMirror (`pm2 mm`) and `lightdm` as expected; both came back up cleanly and no manual `~/start_mm` recovery was needed.

## Contents

- `report.json` — full machine-readable results (metrics per test).
- `report.md` — human-readable summary table with per-test metrics, copied verbatim from the unit.
- `evidence/` — captured `.ppm` frame grabs used as evidence for the overlay/geometry-sensitive tests (T08–T15, T24).

## Why this matters

This run is the **behavioural baseline** for the NeTV2 HDMI pipeline: PASS 29 / FAIL 0 / BLOCKED 0 / SKIP 3, captured against the stock, unmodified 2018 reference unit running its as-shipped bitstream and firmware. All later phases of this repo-setup/rebuild effort (toolchain pinning, build reproduction, any gateware or firmware changes) should be compared against this result — a regression is any test that was PASS here and is not PASS afterward, or a new class of failure/block not explained by the documented capture-card or rig limitations above.
