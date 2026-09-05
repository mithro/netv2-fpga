# Resources

Links to documentation and resources found / needed during this work.

## NeTV2 hardware & gateware

- AlphamaxMedia netv2-fpga (LiteX gateware + firmware, production images):
  https://github.com/AlphamaxMedia/netv2-fpga
- AlphamaxMedia netv2mvp-scripts (openocd JTAG configs, update-fpga.sh, MagicMirror status module):
  https://github.com/AlphamaxMedia/netv2mvp-scripts
- Local copies on `rpi3-netv2`: `~/code/netv2-fpga`, `~/code/netv2mvp-scripts`,
  `~/code/openocd-mlabs-netv2mvp`.

## Local fleet inventory

- `~/github/mithro/welland-ansible-rpi/inventory/hosts.yml` and
  `inventory/host_vars/rpiz-3.yml` (rpiz-3 wiring / power notes).
- `~/github/mithro/welland-ansible-rpi/.cache/network.csv` (switch port -> host map).
- Netgear switch MCP inventory: `~/.config/ngsw/inventory.toml`.

## Signal-chain / capture

- MS2109 USB capture (MACROSILICON 345f:2109) — UVC + UAC. Known-flaky cheap
  HDMI->USB dongle; intermittently drops to a frozen "no signal" JPEG.
- V4L2 API (VIDIOC_*) struct layouts differ 32-bit vs 64-bit; on armhf
  `v4l2_format` is 204 bytes with the format union at offset 4 (verify with a
  tiny gcc `offsetof` probe, as done in `netv2test/tmp/sz.c`).
- Raspberry Pi KMS/DRM: `vc4-kms-v3d`, `pykms` (python3-kms++). A CEA (VIC)
  videomode is needed for vc4 to emit a populated AVI InfoFrame; the NeTV2
  resolution detector depends on it (see LOG 18:30).
- fbdev vsync: `FBIO_WAITFORVSYNC` ioctl `0x40044620`.

## Test-suite layout (this repo)

- `netv2test/patterns.py` — shared pattern geometry + Gray-coded frame counter.
- `netv2test/v4l2cap.py` — pure-python V4L2 mmap capture (kernel timestamps).
- `netv2test/frames.py` — YUYV/MJPG(`djpeg`) decode, box sampling.
- `netv2test/console.py` — NeTV2 firmware console (`/dev/ttyS0`) client/parsers.
- `netv2test/agent_client.py` — client for the rpiz-3 source agent + clock sync.
- `netv2test/overlay.py` — rpi3-netv2 fb0 overlay control (owns/releases the desktop).
- `netv2test/latency.py` — differential latency via dual frame counters.
- `netv2test/rig.py` — the rig object shared by all tests.
- `netv2test/suite.py` + `tests.py` — test registry and T01-T23 + gaps.
- `netv2test/run_all.py` — orchestrator; writes `reports/<ts>/report.{json,md}`.
- `agent/netv2_source_agent.py` — KMS pattern generator on rpiz-3 (systemd).
