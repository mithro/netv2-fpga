# NeTV2 HDMI test suite report

- Started: 2026-09-05T05:21:41.716336
- Board DNA: `0058a44663258854`
- Capture health: duty 7% @ 21 fps (MS2109 12/180 good frames)
- Result: **PASS 29 / FAIL 0 / BLOCKED 0 / SKIP 3**

| ID | Area | Status | Detail / key metrics |
|----|------|--------|----------------------|
| T01 | console | PASS | dna=0058a44663258854 |
| T02 | hpd | PASS | edid_bytes=256 |
| T03 | edid | PASS | edid_name=HD TO USB |
| T04 | lock | PASS | lock_time_s=1.88 |
| T05 | lock | PASS | locked_fraction=1.0, samples=240, charsync_all_111=True |
| T06 | lock | PASS | input1={'hres': 1920, 'vres': 1080, 'mhz': 148.49} |
| T07 | output | PASS | good_frames=12, capture_duty=0.067, capture_fps=21.6 |
| T08 | output | PASS | black_mean_luma=10.9, white_mean_luma=254.1 |
| T09 | output | PASS | worst_colour_err=21.7, grey_ramp=[0.0, 31.0, 74.0, 116.0, 158.0, 199.0, 242.0, 255.0] |
| T10 | output | PASS | bg_luma=0.0 |
| T11 | overlay | PASS | transparent_bg_luma=137.0, bright_block_luma=255.0 |
| T12 | overlay | PASS | inside_luma=255.0, left_margin_luma=72.9 |
| T13 | overlay | PASS | below_thresh_luma=24.0, above_thresh_luma=221.0 |
| T14 | overlay | PASS | outside_newrect_luma=93.0, inside_newrect_luma=255.0 |
| T15 | overlay | PASS | cross_centroid=(966.70000000000005, 540.0) |
| T16 | output | PASS | counter_backwards=0, frames_captured=360, counters_decoded=152 |
| T17 | latency | PASS | frames_seen=1800, overlay_latency_ms={'std_ms': 9.61, 'n': 1453, 'min_ms': -11.25, 'max_ms': 35.18, 'median_ms': 5.83, 'mean_ms': 5.77}, pas |
| T18 | console | PASS |  |
| T19 | mode | PASS | input0_720p={'hres': 1280, 'vres': 720, 'mhz': 74.24}, 720p_lock_time_s=3.28 |
| T20 | lock | PASS | recovery_s=9.33, loss_detect_s=1.24 |
| T21 | console | PASS | json={'hdmi_Rx_pixel_clock': 148498104, 'hdmi_Rx_hres': 1920, 'hdmi_Rx_vres': 1080} |
| T22 | console | PASS | fpga_die_c=77.5 |
| T23 | audio | SKIP | NeTV2 MVP gateware has no HDMI audio path (video-only); output carries no audio, capture rms=0. Documented gateware limitation. |
| T24 | overlay | PASS | overlay_block_luma_normal=255.0, overlay_block_luma_override=137.0 |
| T25 | lock | PASS | overlay_hres=1920, overlay_symbol_sync=111, overlay_symbol_errors_sum=0 |
| T26 | overlay | PASS | block_luma_after_resume=137.0 |
| T27 | overlay | PASS | block_luma_blanked_after_rect=137.0, block_luma_redrawn_after_rect=255.0 |
| T28 | lock | PASS | hpd_force_loss_s=1.13 |
| T29 | edid | SKIP | i2c_snoop watches the HDCP DDC port (0x74); EDID DDC is at 0x50 and there is no HDCP source, so the snoop buffer is legitimately empty (0/25 |
| T30 | mode | PASS | video_mode_index=11, relock_after_video_mode_s=18.12 |
| T31 | console | PASS | ddr_mbps={'all': 8081, 'read': 4095, 'write': 3986} |
| T90 | gaps | SKIP | Genuine gaps on this rig/gateware: HDCP engine + `debug km` (no HDCP source); output1 / encoder / dma_writer / dma_reader / sdram_test (comp |

## Full metrics
```json
[
 {
  "id": "T01",
  "metrics": {
   "dna": "0058a44663258854"
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T02",
  "metrics": {
   "edid_bytes": 256
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T03",
  "metrics": {
   "edid_name": "HD TO USB"
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T04",
  "metrics": {
   "lock_time_s": 1.88
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T05",
  "metrics": {
   "locked_fraction": 1.0,
   "samples": 240,
   "charsync_all_111": true
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T06",
  "metrics": {
   "input1": {
    "hres": 1920,
    "vres": 1080,
    "mhz": 148.49
   }
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T07",
  "metrics": {
   "good_frames": 12,
   "capture_duty": 0.067,
   "capture_fps": 21.6
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T08",
  "metrics": {
   "black_mean_luma": 10.9,
   "white_mean_luma": 254.1
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T09",
  "metrics": {
   "worst_colour_err": 21.7,
   "grey_ramp": [
    0.0,
    31.0,
    74.0,
    116.0,
    158.0,
    199.0,
    242.0,
    255.0
   ]
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T10",
  "metrics": {
   "bg_luma": 0.0
  },
  "status": "PASS",
  "evidence": [
   "T10_geometry.ppm"
  ]
 },
 {
  "id": "T11",
  "metrics": {
   "transparent_bg_luma": 137.0,
   "bright_block_luma": 255.0
  },
  "status": "PASS",
  "evidence": [
   "T11_keying.ppm"
  ]
 },
 {
  "id": "T12",
  "metrics": {
   "inside_luma": 255.0,
   "left_margin_luma": 72.9
  },
  "status": "PASS",
  "evidence": [
   "T12_margins.ppm"
  ]
 },
 {
  "id": "T13",
  "metrics": {
   "below_thresh_luma": 24.0,
   "above_thresh_luma": 221.0
  },
  "status": "PASS",
  "evidence": [
   "T13_threshold.ppm"
  ]
 },
 {
  "id": "T14",
  "metrics": {
   "outside_newrect_luma": 93.0,
   "inside_newrect_luma": 255.0
  },
  "status": "PASS",
  "evidence": [
   "T14_setrect.ppm"
  ]
 },
 {
  "id": "T15",
  "metrics": {
   "cross_centroid": [
    966.7,
    540.0
   ]
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T16",
  "metrics": {
   "counter_backwards": 0,
   "frames_captured": 360,
   "counters_decoded": 152
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T17",
  "metrics": {
   "frames_seen": 1800,
   "overlay_latency_ms": {
    "std_ms": 9.61,
    "n": 1453,
    "min_ms": -11.25,
    "max_ms": 35.18,
    "median_ms": 5.83,
    "mean_ms": 5.77
   },
   "passthrough_latency_ms": {
    "std_ms": 0.0,
    "n": 1,
    "min_ms": 10.64,
    "max_ms": 10.64,
    "median_ms": 10.64,
    "mean_ms": 10.64
   },
   "clock_offset_err_ms": 1.502,
   "good_frames": 1453,
   "passthrough_samples": 1,
   "clock_offset_ms": -3229031426.979,
   "netv2_overlay_extra_ms": null,
   "rtt": {
    "max_ms": 8.471658919006586,
    "n": 50,
    "median_ms": 4.198589827865362,
    "min_ms": 3.0049453489482403
   }
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T18",
  "metrics": {},
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T19",
  "metrics": {
   "input0_720p": {
    "hres": 1280,
    "vres": 720,
    "mhz": 74.24
   },
   "720p_lock_time_s": 3.28
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T20",
  "metrics": {
   "recovery_s": 9.33,
   "loss_detect_s": 1.24
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T21",
  "metrics": {
   "json": {
    "hdmi_Rx_pixel_clock": 148498104,
    "hdmi_Rx_hres": 1920,
    "hdmi_Rx_vres": 1080
   }
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T22",
  "metrics": {
   "fpga_die_c": 77.5
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T23",
  "metrics": {
   "alsa_card": 1,
   "captured_audio_rms": 0.0
  },
  "status": "SKIP",
  "evidence": []
 },
 {
  "id": "T24",
  "metrics": {
   "overlay_block_luma_normal": 255.0,
   "overlay_block_luma_override": 137.0
  },
  "status": "PASS",
  "evidence": [
   "T24_pipe_override.ppm"
  ]
 },
 {
  "id": "T25",
  "metrics": {
   "overlay_hres": 1920,
   "overlay_symbol_sync": 111,
   "overlay_symbol_errors_sum": 0
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T26",
  "metrics": {
   "block_luma_after_resume": 137.0
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T27",
  "metrics": {
   "block_luma_blanked_after_rect": 137.0,
   "block_luma_redrawn_after_rect": 255.0
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T28",
  "metrics": {
   "hpd_force_loss_s": 1.13
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T29",
  "metrics": {
   "snoop_bytes": 256,
   "snoop_nonzero": 0
  },
  "status": "SKIP",
  "evidence": []
 },
 {
  "id": "T30",
  "metrics": {
   "video_mode_index": 11,
   "relock_after_video_mode_s": 18.12
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T31",
  "metrics": {
   "ddr_mbps": {
    "all": 8081,
    "read": 4095,
    "write": 3986
   }
  },
  "status": "PASS",
  "evidence": []
 },
 {
  "id": "T90",
  "metrics": {},
  "status": "SKIP",
  "evidence": []
 }
]
```