# Pi-side software (2018 to 2019)

How the Raspberry Pi half of a stock NeTV2 worked: what was on the SD card, how
the unit came up showing the MagicMirror overlay, how a user updated the FPGA,
and what a developer did instead.

Sources are local clones under `/home/tim/github/AlphamaxMedia/`. This page uses
these shorthands for them:

| Shorthand | Clone |
| --- | --- |
| `scripts/` | `netv2mvp-scripts/` (`e37bd00`, then two 2026-01 commits) |
| `wiki/` | `netv2-fpga.wiki/` |
| `mmjf/` | `MMM-json-feed/` (branch `netv2`) |
| `legacy/` | this repo's `legacy/` tree (netv2-fpga master) |

Live observations are from the golden unit `pi@rpi3-netv2.iot.welland.mithis.com`,
read-only, on 2026-09-05. Its state is a stock 2018 image plus 2026 debugging
leftovers; where the two differ this page says so.

## 1. The shipped image

| Item | Value | Evidence |
| --- | --- | --- |
| OS | Raspbian GNU/Linux 9 (stretch) | `cat /etc/os-release` on the unit |
| Kernel | `4.14.71-v7+ #1145 SMP Fri Sep 21 15:38:35 BST 2018 armv7l` | `uname -a` |
| Python | 3.5.3 | `python3 --version` |
| Node | v10.2.1, installed under `~/n` (the `n` version manager), not in `/usr` | `~/n/bin/node --version`; `node` is not on the default `PATH` |
| pm2 | `/home/pi/n/lib/node_modules/pm2` | `/etc/systemd/system/pm2-pi.service` |
| OpenOCD | `0.10.0-00019-gfb5691f0-dirty (2018-10-26-14:03)`, at `/usr/local/bin/openocd` | `openocd --version`; `which openocd` |
| MagicMirror | 2.5.0, upstream `6db61b4` (2018-10-01) | `~/code/MagicMirror/package.json`; `git -C ~/code/MagicMirror log -1` |
| Board | Raspberry Pi 3B+ mounted on the NeTV2 riser | `wiki/Using-NeTV2-as-a-Dev-Board.md:8,27` |

OpenOCD is the AlphamaxMedia fork, not mainline. `scripts/README.md:20-31` says
mainline's `bcm2835gpio` driver has a speed bug whose patch was not accepted
upstream, and that the fork runs "about 20x faster"; it must be configured with
`--enable-bcm2835gpio`. The exact configure line is
`./configure --enable-bcm2835gpio --enable-sysfsgpio --disable-werror --prefix=/opt/openocd`
(`scripts/README.md:12`). On the golden unit the source clone is
`~/code/openocd-mlabs-netv2mvp` at `8228018` (2018-10-29, "commit optimizations
on JTAG delays [...] operate at speeds > 10MHz"), with remote
`git@github.com:AlphamaxMedia/openocd.git`.

**Deviation from the README:** the shipped image installed OpenOCD to
`/usr/local`, not `/opt/openocd`, and `/opt/openocd` does not exist on the unit.
The required interface symlink is present at the `/usr/local` equivalent:
`/usr/local/share/openocd/scripts/interface/alphamax-rpi.cfg ->
/home/pi/code/netv2mvp-scripts/alphamax-rpi.cfg`, dated Oct 29 2018. This
matters because the factory-test scripts hard-code `/opt/openocd/bin/openocd`
(see `docs/original/factory-test.md`) while the user-facing updater calls plain
`openocd` from `PATH` (`scripts/update-fpga.sh:35,89,102`).

### `~/code` layout

Five clones, all present on the golden unit (`ls ~/code`):

| Directory | HEAD on the unit | Role |
| --- | --- | --- |
| `netv2-fpga` | `b20a238` 2019-05-03 bunnie, branch `master` | gateware/firmware source plus `production-images/` and `bin/mknetv2img` |
| `netv2mvp-scripts` | `e37bd00` 2019-04-17 bunnie | OpenOCD configs, `update-fpga.sh`, `set_*.sh`, MagicMirror helpers |
| `MagicMirror` | `6db61b4` 2018-10-01 (upstream v2.5.0) | the overlay UI |
| `flterm` | `ee93960` 2017-12-10 (timvideos/flterm) | serial terminal with kernel upload |
| `openocd-mlabs-netv2mvp` | `8228018` 2018-10-29 | the OpenOCD fork source |

`~/code/netv2-fpga/production-images/` holds `user-35.bit`, `user-100.bit` and
`user-firmware.bin` — "Snapshots of the latest production images as loaded in the
factory" (`production-images/README.md`).

## 2. Boot to overlay

The chain is: lightdm autologins `pi` into X on the Pi's own HDMI output;
`pm2-pi.service` resurrects two pm2 apps; one of them is MagicMirror, whose
window is what the FPGA composites onto the passthrough video.

1. **X session.** `/etc/lightdm/lightdm.conf:122` sets `autologin-user=pi`;
   `lightdm.service` is running.
2. **pm2.** `/etc/systemd/system/pm2-pi.service` is `Type=forking`, `User=pi`,
   `ExecStart=/home/pi/n/lib/node_modules/pm2/bin/pm2 resurrect`, with
   `Environment=PATH=/home/pi/n/bin:...` and `PM2_HOME=/home/pi/.pm2`.
3. **The two apps** are recorded in `~/.pm2/dump.pm2`: `mm`
   (`pm_exec_path=/home/pi/n/bin/npm`, `args=["start"]`,
   `cwd=/home/pi/code/MagicMirror`) and `netv2-status`
   (`pm_exec_path=.../netv2mvp-scripts/magicmirror/netv2-status/netv2-status.js`).
4. There is **no `~/.config/autostart`** on the unit and **no crontab**
   (`crontab -l` reports "no crontab for pi"): pm2 is the whole autostart story.

`scripts/mm.sh` (also copied to `~/mm.sh`) is the documented wrapper:

```sh
cd ~/code/MagicMirror
sleep 10 # give 10 seconds to pull up a console and quit
DISPLAY=:0 npm start
```

The ten-second sleep is what the wiki means by "it will do within 10 seconds"
when it tells users to double-click "stop mm" quickly
(`wiki/Customizing-the-Overlay.md:17,27`). Note that the pm2 entry actually saved
on the unit runs `npm start` directly rather than `mm.sh`, so on this unit the
sleep is not in the path.

### Desktop icons

`~/Desktop` holds three `.desktop` files (contents read on the unit):

| Icon | `Exec` | Effect |
| --- | --- | --- |
| `Start MM` | `/home/pi/start_mm` | `PATH=...:/home/pi/n/bin; /home/pi/n/bin/pm2 start mm` |
| `Stop MM` | `/home/pi/stop_mm` | same but `pm2 stop mm` |
| `Update FPGA` | `/home/pi/update-fpga.sh`, `Terminal=true`, `X-KeepTerminal=true` | the one-click updater below |

`~/start_mm` and `~/stop_mm` exist and are two-line shell scripts that export a
`PATH` including `/home/pi/n/bin` before calling pm2 — necessary because node is
not on the default `PATH`.

### `netv2-status.js`

`scripts/magicmirror/netv2-status/netv2-status.js` is 41 lines. It opens
`/dev/ttyS0` at 115200 with node `serialport` (lines 1-2), writes `json on\n\r`
to the FPGA REPL once at startup (line 6), accumulates serial bytes and on a
line break `JSON.parse`s the buffer only if it is longer than 200 characters —
"ignore other responses from terminal program, expect large JSON record" (lines
20-34) — and serves the last parsed object on `http://127.0.0.1:6502/` (lines
38-41). There is no framing beyond the length heuristic and no reconnection
logic; a parse failure just clears the buffer. `scripts/magicmirror/README.md:3-5`
describes it as "meant to be daemonized and run via pm2".

A second module, `scripts/magicmirror/netv2-term/`, is a native MagicMirror
module that reads the serial port itself. `scripts/magicmirror/README.md:7-8`:
"It never quite worked, but it's an interesting curio to look at later on." Its
`defaults.status` object (`netv2-term.js:5-35`) is the best surviving list of the
telemetry field names: `readbw`, `writebw`, per-input `ph0..ph2`, `charsync`,
`sp0..sp2`, `wer0..wer2`, `chansync`, `x`, `y`, `pclk`, and `temp`. It is still
deployed at `~/code/MagicMirror/modules/netv2-term` but is not in `config.js`.

### `MMM-json-feed`

The renderer is `MMM-json-feed`, an upstream module by Andrew McOlash. The
deployed copy is on the **`netv2` branch** at `8d8995b` (2018-08-15, bunnie,
"changes to make it work with NeTV2"); `git -C ~/code/MagicMirror/modules/MMM-json-feed branch`
confirms `netv2` is checked out on the unit. The branch is a 2-file, 37-line
delta from `master` touching `MMM-json-feed.js` and `node_helper.js`. Upstream
`master` last moved 2018-07-11, so this forks the final upstream state.
Upstream documents `url` as deprecated in favour of `urls` (`mmjf/README.md`,
options table); the NeTV2 config still uses the singular `url`, which is one of
the reasons the `netv2` branch exists.

### `config.js` module list

`~/code/MagicMirror/config/config.js`: `address: "0.0.0.0"`, `port: 8080`,
`ipWhitelist: []`, `language: "en"`, `timeFormat: 24`, `units: "metric"`. Modules,
in file order:

| Module | Position | Notes |
| --- | --- | --- |
| `alert` | — | stock |
| `updatenotification` | `top_bar` | stock |
| `clock` | `top_left` | stock |
| `MMM-json-feed` | `top_left` | `url: 'http://127.0.0.1:6502/'`, `updateInterval: 2000`, `title: "NeTV2 Status"` |
| `compliments` | `lower_third` | fixed strings: "This UI is MagicMirror", and pointers to the MagicMirror docs, `/home/pi/code/MagicMirror`, and "Ctrl-Q to see desktop, then double-click 'Stop MM'" |
| `newsfeed` | `bottom_bar` | one feed: New York Times `http://www.nytimes.com/services/xml/rss/nyt/HomePage.xml` |

The same `MMM-json-feed` snippet is reproduced in
`scripts/magicmirror/README.md:12-22`. `~/code/MagicMirror/modules` also contains
`MMM-ImagesPhotos` and `MMM-Remote-Control`, neither enabled in `config.js`.
Relevant `/boot/config.txt` settings: `hdmi_force_hotplug=1`, `hdmi_group=1`,
`hdmi_mode=16` (1080p60), `config_hdmi_boost=9`, `disable_overscan=1`,
`enable_uart=1` (this is what gives `/dev/ttyS0`), `dtparam=i2c_arm=on`, and
`sdram_freq=450` with the comment "underclock the SDRAM, it seems to fail".

## 3. The one-click update flow

`wiki/Updating-the-Firmware.md` is the user-facing procedure: connect Ethernet,
plug in a keyboard and mouse, press `ctrl-q` to leave MagicMirror, double-click
"Update FPGA", wait about a minute of blank screen; MagicMirror resumes by
itself. Line 11 offers `~/update-fpga.sh` over ssh as the equivalent.

`scripts/update-fpga.sh` (116 lines) does this:

1. `git pull origin master` in `/home/pi/code/netv2mvp-scripts`, then in
   `/home/pi/code/netv2-fpga`; either failure aborts with a message naming the
   expected `AlphamaxMedia` remote (lines 8-29).
2. Runs `openocd -f .../idcode.cfg` and greps `tap/device found: <id>`
   (line 35). `0x0362d093` selects `user-35.bit` + `bscan_spi_xc7a35t.bit`;
   `0x13631093` selects `user-100.bit` + `bscan_spi_xc7a100t.bit`; anything else
   aborts (lines 39-66).
3. Copies `production-images/user-firmware.bin` to `/tmp/ufirmware.bin`, pads it
   with `dd ... bs=1 count=1 seek=131071`, then wraps it with `bin/mknetv2img -f`
   into `/tmp/ufirmware.upl` (lines 78-80). The padding exists so the length is
   divisible by 4 and the CRC computes deterministically (lines 73-77).
4. `sudo openocd` with `set FIRMWARE_FILE` / `set BSCAN_FILE` and
   `cl-firmware.cfg` — burns the soft-core firmware to SPI NOR (lines 89-92).
5. `sudo openocd` with `set FPGAIMAGE` / `set BSCAN_FILE` and `cl-spifpga.cfg` —
   burns the bitstream, "~1 minute" (lines 101-105).
6. Every failure path ends with `read dummy`, so the terminal window stays open
   for the operator (`094e552`, 2018-10-30).

### OpenOCD config files

All of them `source [find interface/alphamax-rpi.cfg]` and `cpld/xilinx-xc7.cfg`.

| File | What it does |
| --- | --- |
| `alphamax-rpi.cfg` | the interface definition; `bcm2835gpio`, `transport select jtag`, `peripheral_base 0x3F000000`, `speed_coeffs 100000 5`, `jtag_nums 4 17 27 22` (TCK TMS TDI TDO), `srst_num 24`, `reset_config none`, `adapter_khz 10000` |
| `idcode.cfg` | `init; scan_chain` — read the IDCODE only |
| `reboot.cfg` | `scan_chain` then `xc7_program xc7.tap` — reboot the FPGA from flash |
| `cl-fpga.cfg` | `pld load 0 $BITFILE` — volatile load over JTAG |
| `fpga-jtag.cfg` | same but hard-coded `top.bit` (`scripts/README.md:52-58`) |
| `cl-spifpga.cfg` | `jtagspi_init 0 $BSCAN_FILE; jtagspi_program $FPGAIMAGE 0; xc7_program xc7.tap` — burn bitstream at offset 0 |
| `spi-jtag.cfg` | same with hard-coded `bscan_spi_xc7a35t.bit` and `top.bin` |
| `cl-firmware.cfg` | `jtagspi_program $FIRMWARE_FILE 0x7b0000` — burn firmware |
| `firmware-jtag.cfg` | same with hard-coded `firmware.bin` |
| `spi-erase.cfg` | `flash erase_address 0x0 0x800000` — whole 8 MiB |
| `spi-erase-firmware.cfg` | `flash erase_address 0x7b0000 0x50000` — firmware block only |

`spi-erase.cfg:14` documents the layout: "0x7B0000 = 0x800000 - 0x50000 offset
from top, so we can fit in two 100T FPGA images". `alphamax-rpi.cfg:33-45` adds
that 10 MHz is the practical ceiling, that a GPIO readback is needed to avoid
8 ns glitches, and that the fork carries a 10 mA pad-drive patch at line 472 of
`bcm2835gpio.c`.

## 4. The `set_*.sh` helpers

| Script | What it does |
| --- | --- |
| `set_rgb.sh` | `stty -F /dev/ttyS0 115200`, then `echo "chromamode 0" > /dev/ttyS0` — RGB colourspace |
| `set_ycrcb.sh` | same, `chromamode 1` — YCrCb colourspace |
| `set_res.sh` | pure X11: `xrandr --newmode "netv2_1920x1080 148.500 1920 2008 2052 2200 1080 1084 1089 1125 +hsync +vsync"`, `--addmode default`, `--output default --mode`. Does not touch the FPGA. |
| `set_governor.sh` | prints, then writes `performance` to `scaling_governor` for cpu0..cpu3, then prints again. Added because "need to lock in CPU freq for reliable openocd operation" (`c03c819`, 2018-10-01; extended to all cores in `3a3b065`) |

The two chroma scripts arrived in `7927dc9` (2019-09-13, "add scripts to change
color space easily") — the last functional change to the repository before 2026.

## 5. The developer flow

From `scripts/README.md:35-47`, the REPL is reached with:

```
./flterm --port /dev/ttyS0 --speed 115200 --kernel firmware.bin
```

`--kernel` uploads the firmware built by `make` in the netv2-fpga `firmware/`
directory. Omitting it boots from SPI NOR, but the README warns strongly against
that: "it's highly recommended you copy the firmware associated with your FPGA
bitfile, because migen/litex will occasionally munge the entire address space of
the SoC without warning due to Python non-determinism".

Because `netv2-status` holds `/dev/ttyS0` open and keeps writing `json on`, the
wiki tells developers to `pm2 stop netv2-status` before running flterm and
`pm2 start netv2-status` afterwards, in two separate places
(`wiki/Adjust-the-Cropping.md:16,22`,
`wiki/Customizing-Chroma-and-Colorspace.md:34,44`).
`wiki/Customizing-Chroma-and-Colorspace.md:47` adds that `json off` inside the
REPL is also needed, since the telemetry stream otherwise floods the terminal.

Two details matter more than the rest. The production build **inverts several
overlay-input TMDS pairs** to simplify M2M jumper routing, so a plain HDMI cable
into the overlay port does not work with the stock bitstream
(`wiki/Using-NeTV2-as-a-Dev-Board.md:34-46`); the two pin blocks are in
`legacy/netv2mvp.py:225-257`, chosen by the `cable` argument (`"pcb"` inverts
data0 and `scl`, `"cable"` inverts clk, data1, data2 and `scl`), and the prebuilt
escape hatch is `git checkout chroma-set; cd testing-images; ./testing-fpga.sh cable`.
And you must **never** connect the DC adapter while the board is in a powered
PCIe slot (`wiki/Home.md:7`, `Using-NeTV2-as-a-Dev-Board.md:3`).

### Wiki pages

Clone: `/home/tim/github/AlphamaxMedia/netv2-fpga.wiki/`.

| Page | Contents |
| --- | --- |
| `Home.md` | T5 torx screws; "NeTV2 classic" mode — MagicMirror rendered on the Pi, buffered in FPGA memory, overlaid on the video feed, with the overlay itself encryptable; Vexriscv is the default CPU; links to the `netv2-mainboard`, `netv2-case` and `netv2-tests` repositories |
| `Updating-the-Firmware.md` | the five-step ctrl-Q / "Update FPGA" procedure, plus `~/update-fpga.sh` over ssh |
| `Using-NeTV2-as-a-Dev-Board.md` | SD imaging by `zcat netv2-production-image.img.gz \| sudo dd of=/dev/sdX bs=1M` or via `usb-pyromaniac` from `bunniefoo.com/netv2/production/`; mount the Pi 3B+ with the four holes aligned, NeTV2 powers it; the cable-vs-jumper inversion caveat |
| `Customizing-the-Overlay.md` | ctrl-Q then "stop mm"; wifi or Ethernet; `ssh pi@netv2mvp.local`; default password `netv2mvp`; edit `/home/pi/code/MagicMirror/config/config.js` |
| `Adjust-the-Cropping.md` | `debug setrect <left> <right> <top> <bottom>` in the REPL. Opens with "**This is now deprecated in the latest firmware release**"; the original default cropped 32 px horizontally and 10 px vertically per side to placate fussy TVs |
| `Customizing-Chroma-and-Colorspace.md` | the `multires` branch plus `set_ycrcb.sh`/`set_rgb.sh`; or the `ycbcr` branch plus REPL `chromalo 0xeb00eb`, `chromahi 0xff10ff`, `chromapol 1`. Defaults are `chromalo 0x141414`, `chromahi 0xffffff`, `chromapol 0`. Line 18: automatic colourspace detection is not implemented because the packets specifying colourspace are themselves encrypted, so reading them would be "a violation of section 1201 of the DMCA" |
| `Multiresolution-support.md` | `git checkout multires; cd testing-images; ./testing-fpga.sh` gives 720p, 1080i and 1080p auto-detection |
| `Building-an-RPi-Image.md` | contributed by `@cgmAether` in issue #24, in a PCILeech context: apt packages, the OpenOCD fork build, the `interface/alphamax-rpi.cfg` symlink, and a `bitbang.h` `extern` patch for newer gcc |
| `Customizing-the-Front-Bezel.md` | mechanical only: STEP and PDF drawings in `netv2-case`; 1 mm stock for a laser cutter, 2 mm for a CNC |

## 6. The 2026-01 Pi 4 additions

Two commits by Tisham (whatnick) Dhar on 2026-01-19, merged by bunnie as
`c823b6d` on 2026-01-30, both titled "Config working with upstream openocd and
rpi4". Together they add exactly two files and change nothing existing.

- `alphamax-rpi-4.cfg` (49 lines) is `alphamax-rpi.cfg` translated to modern
  OpenOCD command syntax: `adapter driver bcm2835gpio`; `bcm2835gpio
  peripheral_base` / `speed_coeffs` as subcommands rather than underscore-joined
  names; four `adapter gpio tck|tms|tdi|tdo` lines in place of
  `bcm2835gpio_jtag_nums 4 17 27 22`; `adapter gpio srst 24`; `adapter speed
  10000` in place of `adapter_khz 10000`. **The GPIO numbers and the peripheral
  base are unchanged** — including `peripheral_base 0x3F000000`, the Pi 2/3
  value, still commented "Raspi2 and Raspi3" (line 9). The Pi 4 peripheral base
  is `0xFE000000`, so that line is at best suspicious for real Pi 4 use.
- `cl-spifpga-rpi4.cfg` (17 lines) differs from `cl-spifpga.cfg` in two lines:
  `jtagspi_init xc7.pld $BSCAN_FILE` instead of `jtagspi_init 0 $BSCAN_FILE`, and
  `virtex2 refresh xc7.pld` instead of `xc7_program xc7.tap` — the renamed APIs
  in current OpenOCD. It still sources `interface/alphamax-rpi.cfg`, not the `-4`
  variant, so a caller must supply the new interface file some other way.

No Pi 4 variant exists for `cl-firmware.cfg`, `cl-fpga.cfg`, `idcode.cfg` or the
erase configs, and `update-fpga.sh` was not updated to select them.

## 7. Every place the Pi touches the FPGA

| Interface | Pi side | Used by |
| --- | --- | --- |
| JTAG TCK | GPIO 4 | `scripts/alphamax-rpi.cfg:20`; `xvcpi/README.md:17` uses the same map |
| JTAG TMS | GPIO 17 | same |
| JTAG TDI | GPIO 27 | same |
| JTAG TDO | GPIO 22 | same |
| JTAG SRST | GPIO 24 | `scripts/alphamax-rpi.cfg:26`; `reset_config none`, so it is declared but not used |
| UART, 115200 8N1 | `/dev/ttyS0` (`/dev/serial0` symlinks to it) | `netv2-status.js:2`, `set_rgb.sh:4`, `set_ycrcb.sh:4`, `flterm --port /dev/ttyS0`. Enabled by `enable_uart=1` in `/boot/config.txt`. **The factory tests use `/dev/ttyAMA0` instead** — see `docs/original/factory-test.md` |
| HDMI overlay in | the Pi's own HDMI output, through the M2M jumper PCB into NeTV2 `hdmi_in1` | `legacy/netv2mvp.py:225-241`; `/boot/config.txt` forces `hdmi_group=1 hdmi_mode=16` |
| I2C | `dtparam=i2c_arm=on`, `i2c_arm_baudrate=100000` in `/boot/config.txt` | not used by any script in `scripts/`; used by the factory test hat's ADC |

The FPGA's own SPI NOR is only reachable through JTAG (`jtagspi_*`), so every
flash operation is a JTAG operation.

## 8. Hard-coded paths and hostnames

| Location | Hard-coded value |
| --- | --- |
| `scripts/update-fpga.sh:8-9` | `GIT_DIR=/home/pi/code/netv2-fpga`, `OCD_SCRIPT_DIR=/home/pi/code/netv2mvp-scripts` |
| `scripts/update-fpga.sh:16,26` | remote must be `https://github.com/AlphamaxMedia/netv2mvp-scripts.git` / `netv2-fpga.git` |
| `scripts/update-fpga.sh:69-80` | `/tmp/ufirmware.bin`, `/tmp/ufirmware.upl` |
| `scripts/netv2-status.sh:3` | `/home/pi/code/netv2mvp-scripts/magicmirror/netv2-status/netv2-status.js` |
| `scripts/netv2-status.sh:3` | invokes bare `node`, which is not on the default `PATH` on the unit |
| `netv2-status.js:2,41` | `/dev/ttyS0`; listen port `6502` |
| `MagicMirror config.js` | `http://127.0.0.1:6502/` |
| `scripts/mm.sh:1` | `~/code/MagicMirror` |
| `~/start_mm`, `~/stop_mm` | `/home/pi/n/bin/pm2` |
| `~/Desktop/*.desktop` | `/home/pi/start_mm`, `/home/pi/stop_mm`, `/home/pi/update-fpga.sh` |
| `scripts/README.md:12`, `wiki/Building-an-RPi-Image.md:31` | prefix `/opt/openocd` (the shipped image actually uses `/usr/local`) |
| `wiki/Customizing-the-Overlay.md:36`, `wiki/Adjust-the-Cropping.md:14` | hostname `netv2mvp.local` (mDNS; `avahi-daemon.service` is running on the unit) |
| `wiki/Customizing-the-Overlay.md:38` | default password `netv2mvp` |
| `wiki/Using-NeTV2-as-a-Dev-Board.md:12,21` | `https://bunniefoo.com/netv2/netv2-production-image.img.gz`, `https://bunniefoo.com/netv2/production/` |
| `scripts/set_governor.sh` | `/sys/devices/system/cpu/cpu{0,1,2,3}/...` — exactly four cores |

## 9. Golden unit deltas as of 2026-09-05

Observed, so that later work does not mistake them for original behaviour:

- `pm2 list` shows `mm` **online** and `netv2-status` **stopped** with
  **1,912,748 restarts**. It was deliberately stopped on 2026-09-05 so the serial
  console could be used; see `tests/hdmi-suite/LOG.md:91-97`. Restore with
  `~/n/bin/pm2 start netv2-status`.
- `~` contains 2026-03 experiment bitstreams (`ddr_netv2.bit`, `uart_netv2*.bit`,
  `pmod_netv2.bit`, `kosagi_netv2.bit`, `xc7a35t_test.bit`), an
  `openFPGALoader-armv7` binary, a `libgpiod-build` tree and the `netv2test/`
  suite. None of these are part of the 2018 image.
- `apache2`, `xrdp`, `xrdp-sesman` and `lldpd` are running services that the
  original image did not need for the overlay product.
- `~/mm.sh`, `~/netv2-status.sh`, `~/update-fpga.sh` and `~/alphamax-rpi.cfg` are
  copies of the `netv2mvp-scripts` files at the top of `$HOME`; the desktop icons
  point at the `$HOME` copies, not the ones in `~/code`.
