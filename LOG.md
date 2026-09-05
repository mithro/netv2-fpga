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
