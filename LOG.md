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
