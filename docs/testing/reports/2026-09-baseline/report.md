# NeTV2 HDMI test suite report

- Started: 2026-09-05T07:50:30.058629
- Board DNA: `0058a44663258854`
- Capture health: duty 29% @ 27 fps (MS2109 53/180 good frames)
- Result: **PASS 29 / FAIL 0 / BLOCKED 0 / SKIP 3**

| ID | Area | Status | Detail / key metrics |
|----|------|--------|----------------------|
| T01 | console | PASS | dna=0058a44663258854 |
| T02 | hpd | PASS | edid_bytes=256 |
| T03 | edid | PASS | edid_name=HD TO USB |
| T04 | lock | PASS | lock_time_s=1.82 |
| T05 | lock | PASS | samples=242, charsync_all_111=True, locked_fraction=1.0 |
| T06 | lock | PASS | input1={'mhz': 148.49, 'hres': 1920, 'vres': 1080} |
| T07 | output | PASS | capture_duty=0.189, good_frames=34, capture_fps=24.1 |
| T08 | output | PASS | black_mean_luma=1.1, white_mean_luma=254.4 |
| T09 | output | PASS | grey_ramp=[0.0, 31.0, 74.0, 115.7, 156.8, 199.0, 242.0, 255.0], worst_colour_err=18.0 |
| T10 | output | PASS | bg_luma=0.0 |
| T11 | overlay | PASS | bright_block_luma=255.0, transparent_bg_luma=137.0 |
| T12 | overlay | PASS | left_margin_luma=72.9, inside_luma=255.0 |
| T13 | overlay | PASS | below_thresh_luma=24.0, above_thresh_luma=221.0 |
| T14 | overlay | PASS | inside_newrect_luma=255.0, outside_newrect_luma=93.0 |
| T15 | overlay | PASS | cross_centroid=(974.70000000000005, 540.0) |
| T16 | output | PASS | frames_captured=360, counter_backwards=0, counters_decoded=170 |
| T17 | latency | PASS | overlay_latency_ms={'n': 1501, 'std_ms': 9.69, 'min_ms': -5.93, 'max_ms': 36.22, 'mean_ms': 10.83, 'median_ms': 10.98}, passthrough_latency_ |
| T18 | console | PASS |  |
| T19 | mode | PASS | 720p_lock_time_s=4.97, input0_720p={'mhz': 74.24, 'hres': 1280, 'vres': 720} |
| T20 | lock | PASS | loss_detect_s=1.23, recovery_s=13.57 |
| T21 | console | PASS | json={'hdmi_Rx_pixel_clock': 148498104, 'hdmi_Rx_hres': 1920, 'hdmi_Rx_vres': 1080} |
| T22 | console | PASS | fpga_die_c=77.0 |
| T23 | audio | SKIP | NeTV2 MVP gateware has no HDMI audio path (video-only); output carries no audio, capture rms=0. Documented gateware limitation. |
| T24 | overlay | PASS | overlay_block_luma_normal=255.0, overlay_block_luma_override=137.0 |
| T25 | lock | PASS | overlay_symbol_errors_sum=0, overlay_symbol_sync=111, overlay_hres=1920 |
| T26 | overlay | PASS | block_luma_after_resume=137.0 |
| T27 | overlay | PASS | block_luma_redrawn_after_rect=255.0, block_luma_blanked_after_rect=137.0 |
| T28 | lock | PASS | hpd_force_loss_s=1.13 |
| T29 | edid | SKIP | i2c_snoop watches the HDCP DDC port (0x74); EDID DDC is at 0x50 and there is no HDCP source, so the snoop buffer is legitimately empty (0/25 |
| T30 | mode | PASS | relock_after_video_mode_s=13.07, video_mode_index=11 |
| T31 | console | PASS | ddr_mbps={'write': 3986, 'read': 4092, 'all': 8078} |
| T90 | gaps | SKIP | Genuine gaps on this rig/gateware: HDCP engine + `debug km` (no HDCP source); output1 / encoder / dma_writer / dma_reader / sdram_test (comp |

## Full metrics
```json
[
 {
  "metrics": {
   "dna": "0058a44663258854"
  },
  "evidence": [],
  "id": "T01",
  "status": "PASS"
 },
 {
  "metrics": {
   "edid_bytes": 256
  },
  "evidence": [],
  "id": "T02",
  "status": "PASS"
 },
 {
  "metrics": {
   "edid_name": "HD TO USB"
  },
  "evidence": [],
  "id": "T03",
  "status": "PASS"
 },
 {
  "metrics": {
   "lock_time_s": 1.82
  },
  "evidence": [],
  "id": "T04",
  "status": "PASS"
 },
 {
  "metrics": {
   "samples": 242,
   "charsync_all_111": true,
   "locked_fraction": 1.0
  },
  "evidence": [],
  "id": "T05",
  "status": "PASS"
 },
 {
  "metrics": {
   "input1": {
    "mhz": 148.49,
    "hres": 1920,
    "vres": 1080
   }
  },
  "evidence": [],
  "id": "T06",
  "status": "PASS"
 },
 {
  "metrics": {
   "capture_duty": 0.189,
   "good_frames": 34,
   "capture_fps": 24.1
  },
  "evidence": [],
  "id": "T07",
  "status": "PASS"
 },
 {
  "metrics": {
   "black_mean_luma": 1.1,
   "white_mean_luma": 254.4
  },
  "evidence": [],
  "id": "T08",
  "status": "PASS"
 },
 {
  "metrics": {
   "grey_ramp": [
    0.0,
    31.0,
    74.0,
    115.7,
    156.8,
    199.0,
    242.0,
    255.0
   ],
   "worst_colour_err": 18.0
  },
  "evidence": [],
  "id": "T09",
  "status": "PASS"
 },
 {
  "metrics": {
   "bg_luma": 0.0
  },
  "evidence": [
   "T10_geometry.ppm"
  ],
  "id": "T10",
  "status": "PASS"
 },
 {
  "metrics": {
   "bright_block_luma": 255.0,
   "transparent_bg_luma": 137.0
  },
  "evidence": [
   "T11_keying.ppm"
  ],
  "id": "T11",
  "status": "PASS"
 },
 {
  "metrics": {
   "left_margin_luma": 72.9,
   "inside_luma": 255.0
  },
  "evidence": [
   "T12_margins.ppm"
  ],
  "id": "T12",
  "status": "PASS"
 },
 {
  "metrics": {
   "below_thresh_luma": 24.0,
   "above_thresh_luma": 221.0
  },
  "evidence": [
   "T13_threshold.ppm"
  ],
  "id": "T13",
  "status": "PASS"
 },
 {
  "metrics": {
   "inside_newrect_luma": 255.0,
   "outside_newrect_luma": 93.0
  },
  "evidence": [
   "T14_setrect.ppm"
  ],
  "id": "T14",
  "status": "PASS"
 },
 {
  "metrics": {
   "cross_centroid": [
    974.7,
    540.0
   ]
  },
  "evidence": [],
  "id": "T15",
  "status": "PASS"
 },
 {
  "metrics": {
   "frames_captured": 360,
   "counter_backwards": 0,
   "counters_decoded": 170
  },
  "evidence": [],
  "id": "T16",
  "status": "PASS"
 },
 {
  "metrics": {
   "overlay_latency_ms": {
    "n": 1501,
    "std_ms": 9.69,
    "min_ms": -5.93,
    "max_ms": 36.22,
    "mean_ms": 10.83,
    "median_ms": 10.98
   },
   "passthrough_latency_ms": {
    "n": 0
   },
   "frames_seen": 1800,
   "clock_offset_err_ms": 1.531,
   "good_frames": 1501,
   "rtt": {
    "min_ms": 3.0629169195890427,
    "median_ms": 4.017083905637264,
    "n": 50,
    "max_ms": 9.023854043334723
   },
   "netv2_overlay_extra_ms": null,
   "clock_offset_ms": -3229031416.568,
   "passthrough_samples": 0
  },
  "evidence": [],
  "id": "T17",
  "status": "PASS"
 },
 {
  "metrics": {},
  "evidence": [],
  "id": "T18",
  "status": "PASS"
 },
 {
  "metrics": {
   "720p_lock_time_s": 4.97,
   "input0_720p": {
    "mhz": 74.24,
    "hres": 1280,
    "vres": 720
   }
  },
  "evidence": [],
  "id": "T19",
  "status": "PASS"
 },
 {
  "metrics": {
   "loss_detect_s": 1.23,
   "recovery_s": 13.57
  },
  "evidence": [],
  "id": "T20",
  "status": "PASS"
 },
 {
  "metrics": {
   "json": {
    "hdmi_Rx_pixel_clock": 148498104,
    "hdmi_Rx_hres": 1920,
    "hdmi_Rx_vres": 1080
   }
  },
  "evidence": [],
  "id": "T21",
  "status": "PASS"
 },
 {
  "metrics": {
   "fpga_die_c": 77.0
  },
  "evidence": [],
  "id": "T22",
  "status": "PASS"
 },
 {
  "metrics": {
   "captured_audio_rms": 0.0,
   "alsa_card": 1
  },
  "evidence": [],
  "id": "T23",
  "status": "SKIP"
 },
 {
  "metrics": {
   "overlay_block_luma_normal": 255.0,
   "overlay_block_luma_override": 137.0
  },
  "evidence": [
   "T24_pipe_override.ppm"
  ],
  "id": "T24",
  "status": "PASS"
 },
 {
  "metrics": {
   "overlay_symbol_errors_sum": 0,
   "overlay_symbol_sync": 111,
   "overlay_hres": 1920
  },
  "evidence": [],
  "id": "T25",
  "status": "PASS"
 },
 {
  "metrics": {
   "block_luma_after_resume": 137.0
  },
  "evidence": [],
  "id": "T26",
  "status": "PASS"
 },
 {
  "metrics": {
   "block_luma_redrawn_after_rect": 255.0,
   "block_luma_blanked_after_rect": 137.0
  },
  "evidence": [],
  "id": "T27",
  "status": "PASS"
 },
 {
  "metrics": {
   "hpd_force_loss_s": 1.13
  },
  "evidence": [],
  "id": "T28",
  "status": "PASS"
 },
 {
  "metrics": {
   "snoop_bytes": 256,
   "snoop_nonzero": 0
  },
  "evidence": [],
  "id": "T29",
  "status": "SKIP"
 },
 {
  "metrics": {
   "relock_after_video_mode_s": 13.07,
   "video_mode_index": 11
  },
  "evidence": [],
  "id": "T30",
  "status": "PASS"
 },
 {
  "metrics": {
   "ddr_mbps": {
    "write": 3986,
    "read": 4092,
    "all": 8078
   }
  },
  "evidence": [],
  "id": "T31",
  "status": "PASS"
 },
 {
  "metrics": {},
  "evidence": [],
  "id": "T90",
  "status": "SKIP"
 }
]
```