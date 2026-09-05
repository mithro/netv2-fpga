# Work log

All times are Australia/Adelaide local unless noted. Newest entries at the bottom.

## 2026-09-05

### 15:30 — Task start / discovery

Goal: RPi Zero W (`rpiz-3`, switch `gsm7252ps-s1` port 26) HDMI -> NeTV2 HDMI in;
verify NeTV2 locks to 1080p60; verify USB capture card on `rpi3-netv2` sees
NeTV2 HDMI out.

Discovery (from `welland-ansible-rpi` inventory + `.cache/network.csv`):

- "Top switch in the xmas tree rack" = `sw-netgear-gsm7252ps-s1` (GSM7252PS).
- Port 1/0/26 = `rpiz-3` eth0 (`00:e0:4c:36:02:7a`, 10.1.90.234), a PoE+USB
  ethernet dongle. `host_vars/rpiz-3.yml` notes "S1 port 26 is not delivering
  PoE; power source not recorded" (2026-08-23).
- `rpi3b-netv2` in the task = inventory host `rpi3-netv2` (10.1.90.212 eth0,
  switch port 1/0/38). Legacy Raspbian 9 stretch, login user `pi` (not `tim`).

State found on `rpiz-3` (ssh `tim@rpiz-3.welland.mithis.com`):

```
Linux rpiz-3 6.18.39+rpt-rpi-v6 #1 Raspbian 1:6.18.39-1+rpt1 (2026-07-29) armv6l
Raspbian GNU/Linux 13 (trixie); Raspberry Pi Zero W Rev 1.1; up 6 days
```

State found on `rpi3-netv2` (ssh `pi@rpi3-netv2.welland.mithis.com`, passwordless sudo):

```
Linux rpi3-netv2 4.14.71-v7+ #1145 SMP Fri Sep 21 15:38:35 BST 2018 armv7l
Raspbian GNU/Linux 9 (stretch); up 44 days; TZ is US/Michigan (!)
lsusb: 345f:2109 (USB video capture card, /dev/video0 present)
/boot/config.txt: hdmi_group=1 hdmi_mode=16 (1080p60), enable_uart=1
~/code/{netv2-fpga,netv2mvp-scripts,openocd-mlabs-netv2mvp,flterm,MagicMirror}
MagicMirror (electron) is running on the Pi's own HDMI output via pm2.
~/alphamax-rpi.cfg: openocd bcm2835gpio JTAG, TCK=GPIO4 TMS=GPIO17 TDI=GPIO27 TDO=GPIO22 SRST=GPIO24
Recent (2026-03) experiment bitstreams in ~: ddr_netv2.bit, uart_netv2*.bit, pmod_netv2.bit, kosagi_netv2.bit
```

Open questions to resolve next:
1. Which bitstream is currently loaded on the FPGA (production NeTV2 gateware
   vs a 2026-03 test bitstream)?
2. How does the NeTV2 firmware report HDMI input lock (serial console on
   `/dev/serial0` via the LiteX BIOS/firmware CLI)?

### 15:50 — First contact with the NeTV2 firmware console

`scripts/netv2_serial.py` copied to `pi@rpi3-netv2:~/netv2_serial.py`. The
console is `/dev/ttyS0` (mini-UART, `/dev/serial0`), 115200 8N1. `/dev/ttyAMA0`
is held by `hciattach` (bluetooth). The FPGA is running the **production NeTV2
"RUNTIME>" firmware** (has `status`, `video_matrix`, `video_mode`, `hdp_toggle`,
`debug edid`, `json on`), not one of the 2026-03 test bitstreams.

`status` output (verbatim):

```
input0:  0x0 (@   0. 0 MHz)
input1:  1920x0 (@   0. 0 MHz)
xadc: 71487 mC
ddr: read:    0Mbps  write:    0Mbps  all:    0Mbps
```

JSON status (`json on` is being enabled by something every few seconds):

```
{"hdmi_Rx_hres" : 0, "hdmi_Rx_vres" : 0, "hdmi_Rx_pixel_clock" : 0, ... "overlay_hres" : 1920, "overlay_vres" : 0, "overlay_symbol_sync" : 111, ... "fpga_die_temp" : "71C" }
```

Findings:
- **input0 (HDMI Rx from rpiz-3) = 0x0**: no signal detected yet. Expected —
  rpiz-3 HDMI output state not yet checked/configured.
- input1 (overlay, from rpi3-netv2's own HDMI) reports 1920x0 with symbol sync
  on all 3 channels. Odd vres=0; to investigate.
- FPGA die temp 71 C.
- Output is interleaved/corrupted: a second process is reading `/dev/ttyS0`
  and repeatedly writing `json on` (looks like the MagicMirror `netv2-status`
  module). Must be stopped for reliable console use.

### New goal from Tim (received 15:50)

> Demonstrate the netv2 board connected to the rpi3-netv2 device's HDMI in and
> out functionality. Then create a test suite which is able to verify that all
> the hdmi functionality is working correctly, including accurately measuring
> frame latency, overlay functionality, etc. Only complete when an adversarial
> sub-agent is unable to find any functionality that has not had an automated
> test verify correct function. The complete test suite must run end-to-end on
> the device without intervention.

### 15:55 — Stopped the crash-looping pm2 `netv2-status` reader on rpi3-netv2

`pm2-pi.service` runs two apps: `mm` (MagicMirror) and `netv2-status` (node
serial reader on /dev/ttyS0 feeding http://127.0.0.1:6502 for the MMM-json-feed
module). `netv2-status` had **1,912,747 restarts** (crash loop, ~1/s). Stopped it
with `~/n/bin/pm2 stop netv2-status` so the console is usable. To restore:
`~/n/bin/pm2 start netv2-status`. `mm` left running.

### 16:00 — rpiz-3 login confirmed; HDMI connector is *disconnected*

`ssh tim@rpiz-3.welland.mithis.com` works, passwordless sudo OK. Host is
headless (`multi-user.target`, agetty on tty1, no X/wayland). Boot config
uses `dtoverlay=vc4-kms-v3d`, `disable_fw_kms_setup=1`, no forced HDMI mode;
`kms++-utils` (`kmstest`, `kmsprint`) is installed — useful for test patterns.

```
/sys/class/drm/card0-HDMI-A-1: status=disconnected enabled=disabled
```

So the Pi Zero is currently outputting **nothing** on HDMI: with the KMS
driver, no hotplug (HPD) => no mode set => no signal. Consistent with the
NeTV2 reporting input0 = 0x0. Next: check whether the NeTV2 presents
HPD/EDID on its HDMI input, and force a 1080p60 mode on the Pi Zero if needed.

### 16:10 — HPD/EDID architecture: NeTV2 passes HPD through from the *sink*

From `netv2mvp.py` + firmware:
- `hdmi_in0` pads have `hpd_notif` only (U17, `HDMI_HPD_LL_N`); the FPGA does
  **not** generate HPD for the source. `hdmi_rx0_forceunplug` (M22) is driven
  by the `hdcp.hpd_ena` CSR to *de-assert* HPD to the source (used at boot and
  on `link_redo`). The sink's HPD and DDC/EDID on the HDMI **output** are
  passed through in hardware to the HDMI **input** (man-in-the-middle design).
- Firmware `hdmi_in0_service()` keeps the input MMCM in reset until
  `hdmi_in0_edid_hpd_notif_read()` says connected => `status` shows 0 MHz
  even if TMDS is present.
- `debug edid output0` => "no EDID capabilities": this gateware has no I2C
  master on output0 (DDC is pure passthrough), so the FPGA cannot read the
  sink EDID.
- `hdp_toggle` command exists but prints "Toggling HDP on output0" (naming
  confusion in firmware; it toggles `hdmi_in0_edid_hpd_en`, which has no pad).

Forcing the connector on rpiz-3 via debugfs (`/sys/kernel/debug/dri/0/HDMI-A-1/force`)
did not stick (`unspecified` after write) but `kmstest -c HDMI-A-1 -r 1920x1080@60 --cea -T smpte`
does set a 148.5 MHz 1080p60 mode on the CRTC even with the connector
"disconnected":

```
Crtc 3/@97: 1920x1080@60.00 148.500 1920/88/44/148/+ 1080/4/5/36/+ 60 (60.00)
```

NeTV2 still reported `input0: 0x0 (@ 0.0 MHz)` (MMCM held in reset, see above).

### 16:20 — Capture card asserts HPD only while streaming => chain comes alive

USB capture card on rpi3-netv2: `uvcvideo`, "UVC Camera (345f:2109)",
MJPG + YUYV, 1920x1080 up to 60 fps (MS2109-class). kernel 4.14 uvcvideo.

Streaming from it for 20 s
(`v4l2-ctl -d /dev/video0 --set-fmt-video=width=1920,height=1080,pixelformat=MJPG --stream-mmap --stream-count=600 --stream-to=/dev/null`)
gave ~58 fps, and **while streaming**:

- rpiz-3: `/sys/class/drm/card0-HDMI-A-1/status` = **connected**
- NeTV2 `status`:

```
input0:  0x0 (@ 148.49 MHz)
input1:  1920x1080 (@ 148.49 MHz)
xadc: 77516 mC
ddr: read:  119Mbps  write: 3986Mbps  all: 4105Mbps
```

So: the capture card only drives HPD when a V4L2 stream is active; with HPD
present the NeTV2 sees the 148.5 MHz TMDS clock from rpiz-3 (1080p60) on
input0 and locks the overlay input (input1, rpi3-netv2's own HDMI) at
1920x1080. input0 had not yet reported a resolution after ~6 s (phase/char
alignment still in progress, or lost again when the stream stopped).

Consequence for the test suite: keep a V4L2 stream open on the capture card
for the whole test run (it is both the HPD source and the measurement sink).

Tooling on rpi3-netv2 (python 3.5): numpy 1.12 present; **no** PIL, cv2,
ffmpeg. MJPG decoding for tests will need a pure-python/numpy JPEG path or
use the YUYV format instead (raw, no decode needed).

### 16:30 — **NeTV2 locks input0 at 1920x1080 @ 148.49 MHz (goal 1 achieved)**

With a 15-minute V4L2 stream running on the capture card (keeps HPD asserted)
and `kmstest -c HDMI-A-1 -r 1920x1080@60 --cea -T smpte` running on rpiz-3,
`debug input0` on the NeTV2 console shows the lock sequence:

```
hdmi_in0: PLL locked
hdmi_in0: setting algo 2 eye time to 14 IDELAY periods
hdmi_in0: ph: ... // charsync:111 [5 6 6] // ... // WER:2759895 2735115 2760246 // chansync:0 // res:0x0
... (10 lines of phase search, ~1 s) ...
hdmi_in0: ph:   0( 1/ 8)ff    0(11/18)ff    0(10/17)ff // charsync:111 [0 0 0] // eye:0000007f 00007fc0 00007fc0 // WER:  0   0   0 // chansync:1 // res:1920x1080
```

`status`:

```
input0:  1920x1080 (@ 148.49 MHz)
input1:  1920x1080 (@ 148.49 MHz)
xadc: 79361 mC
ddr: read: 4080Mbps  write: 3974Mbps  all: 8054Mbps
```

Over 25 s of debug output: 378/389 samples `res:1920x1080 chansync:1 WER 0 0 0`
(the first 10 were the initial phase search; one transient `1920x368`).
Board DNA: `0058a44663258854`. FPGA die temp rose to ~79 C with both inputs
and the output active.

### 16:40 — **End-to-end chain verified: capture card receives NeTV2 output (goals 2 & 3)**

Captured one raw YUYV 1920x1080 frame from the capture card after skipping
400 frames (`v4l2-ctl --stream-mmap --stream-count=1 --stream-skip=400 --stream-to=frame1.yuyv`,
YUYV at 1080p is only ~5 fps over USB 2.0, so this took ~80 s). Converted
with `scripts/yuyv2png.py` -> `evidence/2026-09-05-first-capture-console-plus-overlay.png`.

The frame shows:
- **input0 (rpiz-3)**: the Pi Zero's Linux text console at native 1920x1080
  ("Raspbian GNU/Linux 13 rpiz-3 tty1", "My IP address is 10.1.90.234 ...").
- **overlay (input1, rpi3-netv2's own HDMI)**: MagicMirror UI composited on
  top (clock "02:23", "NETV2 STATUS / Error fetching stats." because I stopped
  `netv2-status`, compliments text, NYT headline). Bright pixels only, as per
  the gateware rule (`rect_on & r,g,b >= rect_thresh(20)` selects overlay).

NeTV2 `status` at capture time: `input0: 1920x1080 (@ 148.49 MHz)`,
`input1: 1920x1080 (@ 148.49 MHz)`, ddr all 8054 Mbps, xadc 81 C.

Why it is the console and not the kmstest SMPTE bars: `kmstest` was started
with stdin from /dev/null, so it hit "press enter to exit" and quit at once.
The CRTC mode survived; once HPD+EDID arrived, fbcon re-applied the EDID's
preferred mode natively. I.e. **no forcing is needed on rpiz-3**: as soon as
the capture card streams, its EDID reaches the Pi Zero through the NeTV2 and
the kernel picks 1080p60 by itself.

EDID seen by rpiz-3 (`/sys/class/drm/card0-HDMI-A-1/edid`, 256 bytes, saved as
`evidence/capture-card-edid-as-seen-by-rpiz-3.bin`), decoded with pyedid:
manufacturer PNP id `HJW`, product 2337, week 15 / 2024, name **"HD TO USB"**,
EDID 1.3, resolutions incl. 1920x1080@60 (preferred), 1280x720@60.
rpiz-3 `kmsprint`: `HDMI-A-1 (connected)`, Crtc `1920x1080@60.00 148.500`.

A 1-hour MJPG stream (`--stream-count=216000`) is now running on rpi3-netv2
(`~/cap/stream.log`) to keep HPD asserted while I build the test suite.

**Summary of the original three asks (all verified with device output above):**
1. rpiz-3 outputs 1080p60 — yes (kmsprint 1920x1080@60.00 148.500 MHz).
2. NeTV2 locks to it — yes (`input0: 1920x1080 (@ 148.49 MHz)`, WER 0, chansync 1).
3. USB capture card receives NeTV2 output — yes (frame captured, content matches).
