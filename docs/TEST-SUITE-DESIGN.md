# NeTV2 HDMI test suite — design

Status: draft v1, 2026-09-05. Runs end-to-end on `rpi3-netv2` without human
intervention; drives `rpiz-3` (the HDMI source) over SSH.

## Signal chain under test

```
rpiz-3 HDMI (vc4-kms, 1080p60)  --HDMI cable-->  NeTV2 RX0 ("input0")
                                                     |  passthrough (TMDS re-encode, ~0 latency)
rpi3-netv2 HDMI (legacy fb, 1080p60) --M2M jumper--> NeTV2 overlay in ("input1")
                                                     |  framebuffer in DDR -> DMA -> encoder -> keyed mux
                                                  NeTV2 TX0 ("output0")
                                                     |  HDMI cable
                                        USB capture card "HD TO USB" (345f:2109, MS2109-class)
                                                     |  USB 2.0 (uvcvideo /dev/video0, snd-usb-audio card 1)
                                                  rpi3-netv2 (test runner)
```

Compositing rule (from `netv2mvp.py`, VideoOverlaySoC):

```
if pipe_override:                       out = raw input0 TMDS characters
elif rect_on and min(overlay.r,g,b) >= rect_thresh:   out = overlay pixel
else:                                   out = input0 pixel
```
`init_rect()` defaults: rectangle = x in [32, W-32), y in [10, H-10),
`rect_thresh = 20`, `dma_delay_base = 120`.

HPD and DDC/EDID on RX0 are hardware pass-through from TX0's sink. The
capture card asserts HPD **only while a V4L2 stream is active**, so the
runner keeps a capture stream open for the whole run.

## Hosts and their roles

| Host | Role in the suite | Constraints |
|---|---|---|
| `rpi3-netv2` (Raspbian 9, py3.5, numpy 1.12, `djpeg`, `v4l2-ctl`, `arecord`) | **Runner**: FPGA console (`/dev/ttyS0`), V4L2 capture, ALSA capture, overlay drawing on its own HDMI (`/dev/fb0`), report writer | No PIL/cv2/ffmpeg. py3.5 syntax only (no f-strings). MagicMirror/X normally own the HDMI output — the runner stops `pm2 mm` + `lightdm` for the run and restores them after. |
| `rpiz-3` (Raspbian 13, py3.13, pykms, numpy) | **Source agent**: draws test patterns to KMS with page flips, reports vblank timestamps, answers time-sync pings; TCP JSON protocol on port 5910, started over SSH by the runner | ARMv6, slow: patterns are drawn with numpy into a dumb buffer; per-frame updates touch small regions only. |

## Measurement primitives

- **Capture**: pure-python V4L2 mmap streaming (`fcntl.ioctl` + `mmap`, no
  third-party deps) so every frame carries the kernel's `CLOCK_MONOTONIC`
  timestamp. Formats used:
  - `YUYV 1920x1080` (5-10 fps): exact pixels for fidelity/geometry tests.
  - `YUYV 720x480` (60 fps): raw, frame-accurate timing for latency tests.
  - `MJPG 1920x1080` (60 fps): frame-rate test; decoded via `djpeg` only when
    pixel content is needed.
- **Console**: NeTV2 serial console client; parses `status`, `json` output and
  the `debug input0` lock trace (`WER`, `chansync`, `res`).
- **Frame counter encoding**: the source draws a row of large black/white
  blocks encoding a 16-bit Gray-coded frame number (+ parity + sync marker) in
  a region that survives scaling to 720x480. The runner decodes it from every
  captured frame.
- **Clock sync** rpiz-3 <-> rpi3-netv2: NTP-style ping over the agent socket;
  offset from the minimum-RTT sample of 50 pings. Error bound = RTT/2 (~1 ms
  on the wired VLAN) — small compared with the 16.7 ms frame period.

## Latency method

Absolute latency through the capture card is unknown, so the suite measures
two paths with the same sink and reports the difference:

1. **Passthrough path** (rpiz-3 flip -> capture): `L_pt = t_cap - t_flip - offset`.
   Architecturally the NeTV2 passthrough adds only a few pixel clocks, so
   `L_pt` is dominated by the capture card + USB + software.
2. **Overlay path** (rpi3-netv2 fb0 write after `FBIO_WAITFORVSYNC` -> capture):
   `L_ov = t_cap - t_write` (same clock, no offset).
3. **NeTV2 overlay latency** = `L_ov - L_pt` (capture-card contribution
   cancels). Reported with mean, min, max, stdev over >= 30 events with
   randomised phase; quantisation of the 60 fps capture is averaged out.

The NeTV2 passthrough latency itself is bounded from above by `L_pt` and its
sub-line nature is asserted from the gateware (documented, not measured).

## Test inventory (each maps to one automated test)

| ID | Area | Test | Pass criterion |
|---|---|---|---|
| T01 | preflight | console alive, firmware build banner, `debug dna` | DNA non-zero, `help` lists expected commands |
| T02 | HPD | capture stream off -> rpiz-3 connector `disconnected`; stream on -> `connected` within 5 s and 256-byte EDID present | as stated |
| T03 | EDID | EDID seen by rpiz-3 == EDID of "HD TO USB" (name, 1080p60 preferred) | byte-equal to golden file, or name+preferred mode match |
| T04 | input0 lock | after stream on and rpiz-3 at 1080p60: `status` input0 1920x1080 @ 148.5 +-0.2 MHz within 10 s; `debug input0` trace reaches `chansync:1 WER 0 0 0` | as stated |
| T05 | input0 stability | 20 s of `debug input0`: >= 99 % samples `res:1920x1080 chansync:1`, WER sum == 0 after convergence | as stated |
| T06 | input1 (overlay) lock | `status` input1 1920x1080 @ 148.5 MHz | as stated |
| T07 | output0 format | capture MJPG 1920x1080: >= 55 fps mean over 5 s, frame interval stdev < 4 ms, no zero-size frames | as stated |
| T08 | output not blank | mean luma of captured frame with a white source pattern > 200; black source pattern < 30 | as stated |
| T09 | passthrough colour fidelity | source shows 8 solid colour bars + grey ramp; captured (YUYV 1080p) region means within +-12/255 of expected after BT.601 conversion | as stated |
| T10 | passthrough geometry | source shows corner markers + centre crosshair + 1-px grid; markers found at expected positions +-2 px; no horizontal shift/wrap | as stated |
| T11 | overlay keying | overlay draws bright block (255) and dark block (10) inside the rect over a mid-grey source; bright block visible, dark block transparent (shows source grey) | as stated |
| T12 | overlay rectangle margins | overlay draws white at x<32 / y<10 and inside rect; outside-rect region shows source, inside shows white | as stated |
| T13 | overlay threshold | `debug rectthresh 128`: overlay value 100 -> transparent, 200 -> opaque; restore 20 and re-verify | as stated |
| T14 | overlay rect override | `debug setrect` to a smaller rect: white overlay outside new rect disappears; `debug rect` restores defaults | as stated |
| T15 | overlay alignment | overlay draws a 1-px frame at rect edges; captured edge position matches passthrough geometry (+-2 px) — verifies `dma_delay_base` alignment | as stated |
| T16 | frame counter continuity | 5 s at 60 fps YUYV 720x480: decoded counter strictly increasing, gaps counted; report drop ratio; fail if > 5 % gaps (USB) or any counter going backwards | as stated |
| T17 | latency passthrough | >= 30 events; `L_pt` mean, min, max; fail if any sample < 0 or > 200 ms (sanity) | as stated |
| T18 | latency overlay | >= 30 events; `L_ov`; NeTV2 overlay latency = `L_ov - L_pt` reported; fail if < 0 or > 3 frames | as stated |
| T19 | mode change 720p | source switches to 1280x720@60: NeTV2 `status` input0 1280x720 @ 74.25 MHz; capture pattern geometry matches 720p; switch back to 1080p60 and re-verify | as stated |
| T20 | source loss / recovery | source DPMS off: NeTV2 debug reports lost PLL lock / res 0 within 5 s; DPMS on: re-lock within 10 s | as stated |
| T21 | JSON status | `json on` record parses; fields consistent with `status` (hres/vres/clock) | as stated |
| T22 | thermal | `debug xadc` < 90 C | as stated |
| T23 | audio passthrough | rpiz-3 plays 1 kHz tone on HDMI audio; `arecord` from capture card: dominant FFT bin at 1 kHz +-20 Hz, SNR > 20 dB; silence -> no tone | as stated |
| T24 | pipe_override (raw TMDS passthrough) | write `rectangle.pipe_override=1` via `mw`? — **requires CSR address, not exposed by firmware; deferred unless csr.h can be regenerated** | documented gap |

Deferred / not testable here (documented, not hidden): HDCP (no HDCP source),
`video_mode` changes on the NeTV2 itself (changes the EDID offered to the
overlay Pi and the output timing; the overlay Pi is fixed at 1080p60 by its
`/boot/config.txt`), the second HDMI output (`output1`, not present in this
gateware), Ethernet/etherbone (RMII PHY, no cable).

## Run flow (`run_all.py`)

1. Preflight: console OK, `/dev/video0` present, SSH to rpiz-3 OK, agent
   starts. Record firmware banner, DNA, versions.
2. Stop `pm2 mm` and `lightdm` on rpi3-netv2 (records prior state).
3. Start capture stream (HPD on). Wait for rpiz-3 connector + NeTV2 lock.
4. Run tests T01..T23 in order (unittest, each self-contained, each restores
   what it changed).
5. Write `reports/<timestamp>/report.json` + `report.md` + evidence PNGs
   (YUYV->PPM->PNG via `djpeg`? no — PPM written by python, converted to PNG
   on the host later; on-device evidence stays PPM to avoid deps).
6. Restore: `debug rect`, `debug rectthresh 20`, rpiz-3 back to 1080p60 console,
   stop agent, restart `lightdm` and `pm2 mm`.

Exit code 0 only if every test passed.
