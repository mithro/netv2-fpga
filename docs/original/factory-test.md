# Factory test (2018)

How NeTV2 boards were tested and imaged in the factory. Everything here is
dated October and November 2018; the test repository's last commit is
`c16e0d7`, 2018-11-15 (`git -C netv2-tests log`).

Sources are local clones under `/home/tim/github/AlphamaxMedia/`, referred to
below as `tests/` (`netv2-tests`), `exclave/`, `jig-http/`
(`jig-20-interface-http`), `testhat/` (`netv2-testhat`), `pyro/`
(`usb-pyromaniac`), `usbmap/` (`usb-mapping`), `xvcpi/` and `wiki/`
(`netv2-fpga.wiki`).

## 1. The exclave model

Exclave is a factory test framework written in Rust (`exclave/README.md:1-4`);
it is installed with `cargo install exclave` and run as `exclave -c <config-dir>`.
Everything in that directory is a **unit**, typed by file suffix
(`exclave/doc/Units.md`). A **`.jig`** describes the physical tester and can name
a `TestFile` or `TestProgram` used to decide whether we are running on it, plus a
`DefaultScenario`. A **`.test`** is the atomic unit: an `ExecStart` command whose
exit code is pass or fail, with `Requires` (hard dependency), `Suggests` (soft),
`Provides` (aliasing), `Timeout` and `Type=simple|daemon`. A **`.scenario`**
lists `Tests` in order — "you only need to specify the final test to run, as the
dependency graph will fill in the rest" — with `ExecStopSuccess`/`ExecStopFail`
hooks. A **`.trigger`** is a long-running program whose output starts a scenario;
triggers are non-repeating and events are consumed. A **`.logger`** receives
every test event. An **`.interface`** both displays tester state and can drive
it. Tests may be written in any language; they log progress to stdout and errors
to stderr, and each runs in its own session on a pseudoterminal so `printf` is
not buffered (`exclave/README.md:37-48`). Exclave also defines `.coupon` and
`.updater` units, neither of which NeTV2 uses.

Interfaces, loggers and triggers speak CFTI over stdin/stdout, one line-oriented
record per line (`exclave/doc/IPC.md`). In the `text` dialect both NeTV2
interfaces use, the server sends `HELLO`, `JIG`, `SCENARIOS`, `SCENARIO`,
`DESCRIBE`, `TESTS`, `START`, `RUNNING`, `PASS`, `FAIL`, `SKIP`,
`FINISH <http-status> <scenario>`, `LOG`, `PING` and `SHUTDOWN`; the client can
select scenarios and request lists back. `FINISH` carries an HTTP-style result
code, "with 200 indicating success" — exactly what
`tests/bin/led-interface.sh:62-68` parses.

`exclave/doc/Jig.md` documents building a jig on **Fedberry** (Fedora for the
Pi), with rustup, avahi, a `pi` user in `wheel`, and OpenOCD built to
`/opt/openocd` with `--enable-bcm2835gpio --enable-sysfsgpio`. That is the
origin of the `/opt/openocd` prefix the NeTV2 scripts hard-code.

## 2. `netv2.jig`

Six lines (`tests/netv2.jig`): `Name=NeTV2 Jig`, `Description=NeTV2 Factory Test
Jig`, `TestFile=/boot/netv2-jig`, `DefaultWorkingDirectory=bin`,
`DefaultScenario=full-sequence`. The presence of `/boot/netv2-jig` is the only
thing that marks a Pi as a tester, so the same config directory is inert on a
non-tester machine.

Exclave is launched by `tests/run_exclave.sh`, which starts pulseaudio ("root
user doesn't have pulse audio running"), calls `bin/dut-off.sh` to guarantee the
DUT is unpowered at start, then runs `/home/pi/.cargo/bin/exclave -c
/home/pi/code/netv2-tests`. `tests/exclave.service` installs that as a systemd
unit running as `User=pi` after `network.target`, so "your Rpi will boot into a
tester automatically" (`tests/README.md:59-61`).

## 3. The two scenarios

| | `full-sequence` | `quick-sequence` |
| --- | --- | --- |
| Name | Comprehensive test | Quick test |
| Timeout | 180 s | 60 s |
| Trigger | PCIe hot-plug | mechanical push-button |
| Cabling | full harness (below) | none, jig probes only |
| Purpose | test everything, then burn production images | screen gross solder faults before spending labour on the full run |

`full-sequence` requires (`tests/README.md:7-16`): TX0 to Overlay, TX1 to RX0, a
PCI express loopback header, an Rpi loopback/breakout, a ping-test network
cable, a USB loopback, a microSD card and a fan. `quick-sequence` "requires no
cables to be installed, but it does assume you have a jig which can measure all
the voltage test points on the PCB [...] and also quickly shuts down the board
if any voltages are out of spec, thus preventing further damage"
(`tests/README.md:44-52`).

Both scenarios set `ExecStopFail=.../bin/test_done.sh`.
`full-sequence.scenario:2` also sets `ExecStopSuccess`; `quick-sequence.scenario:2`
misspells it as `ExecStopSucess`, so the quick scenario has no success hook. A
commit named "fix typo on ExecStopSuccess" (`e75e172`, 2018-10-29) fixed the
full sequence only.

### `full-sequence`, in order

| # | Test | `ExecStart` | Checks | Needs |
| --- | --- | --- | --- | --- |
| 1 | `netv2-duton` | `bin/dut-on.sh` | drives GPIO 24 (`PROG_N`) high so the FPGA is not held in program, then GPIO 26 (`PWR_SWITCH`) high to power the DUT | test hat power switch |
| 2 | `netv2-check-voltage` | `testhat-drivers/tester-driver -q` | 12 V rail within 10 %, DUT current between 8 mA and 600 mA; emits JSON `{"subtest":"power", ...}` | test hat ADC |
| 3 | `netv2-check-idcode` | `bin/getidcode.sh` | OpenOCD `idcode.cfg` scan; `0x0362d093` writes `35T` to `/tmp/devicetype.txt`, `0x13631093` writes `100T`, anything else writes `INVAILD` and exits 1 | JTAG on the Pi header |
| 4 | `netv2-setup-gtptest` | `bin/setup_gtptest.sh` | pads `tester-images/gtptester-firmware.bin`, wraps it with `bin/mknetv2img -f`, burns it with `cl-firmware.cfg`, then volatile-loads `gtptester-{35,100}.bit` with `cl-fpga.cfg` | JTAG |
| 5 | `netv2-check-repl2` | `bin/check-repl.expect` | flterm on `/dev/ttyAMA0` at 115200; retries a newline up to 30 times looking for `TESTER_NX8D`. Seeing `BIOS>` instead means the firmware did not load: it prints a synthetic failure JSON record naming "Failed to load firmware, check DDR path!" and exits 1 | UART |
| 6 | `netv2-gtp-test` | `bin/run-test.expect` | sends `debug tester`, waits for `expect_pass` / `expect_fail`, 120 s expect timeout inside a 35 s unit timeout | PCIe loopback header |
| 7 | `netv2-setup-maintest` | `bin/setup_maintest.sh` | same as #4 but with `tester-firmware.bin` and `tester-{35,100}.bit` | JTAG |
| 8 | `netv2-check-repl` | `bin/check-repl.expect` | as #5, 30 s timeout | UART |
| 9 | `netv2-main-test` | `bin/run-test.expect` | `debug tester` again, this time against the full-feature bitstream: HDMI loopbacks, DDR, USB loopback, microSD, fan | full harness |
| 10 | `netv2-ping-test` | `bin/pingtest.expect` | `ping -i 0.2 -c 10 -W 1 10.0.11.2`; pass on " 0% packet loss", fail on " 100% packet loss" or timeout, emitting `{"subtest":"Ethernet", ...}` records either way | Ethernet cable, DUT at the fixed address `10.0.11.2` |
| 11 | `netv2-burn-spi` | `bin/burn-spi.sh` | burns `netv2-fpga-userimage/production-images/user-firmware.bin` (padded and `mknetv2img`-wrapped) at `0x7b0000`, then `user-{35,100}.bit` at 0 via `cl-spifpga.cfg`; sleeps 3 s "give a moment for the bios to boot, so flterm doesn't catch it by accident" | JTAG |

Two further test units exist but are not listed in either scenario:
`netv2-tests-pass.test` ("Play a test finished sound", `Requires` all five
substantive tests plus the burn) and `test-done.test` ("Notify operator, reset
test"). Both run `bin/test_done.sh`, which calls `dut-off.sh` and then
`aplay bin/test-done.wav`. The scenarios reach the same script through their
`ExecStop*` hooks instead.

### `quick-sequence`, in order

`netv2-duton` → `netv2-check-all-voltage` (`tester-driver -j`: all eleven rails
plus DUT current as JSON, and a comprehensive pass/fail) → `netv2-quick-idcode`
(same `getidcode.sh`) → `netv2-quick-setupfpga` (same `setup_maintest.sh`) →
`netv2-quick-repl` (same `check-repl.expect`) → `netv2-quicktest`
(`bin/ram-test.expect`, which sends `debug tester memory` rather than
`debug tester`).

### The voltage driver

`tests/bin/testhat-drivers/adc128d818.c` talks to two TI ADC128D818 8-channel
ADCs over I2C at addresses `0x1D` and `0x37` (`adc128d818.h:5-6`). The channel
map (`adc128d818.h:32-42`) covers `1.2VTT`, `1.2VE`, `1.8V`, `1.5V`, `3.3V`,
`3.3VE`, `5.0V`, `12.0V`, `1.0V`, `0.75VTT` and an in-line 12 V current sense.
`comprehensive_check()` applies `DEFAULT_TOLERANCE 0.045` — "4.5% tolerance on
all internal supplies -- 0.5% slop due to test jig itself for total 5%
guaranteed range" — and `ADAPTER_TOLERANCE 0.1` for the 12 V input, "this supply
is expected to be messy" (lines 310-311). Current must be above 8 mA ("14mA is
roughly the idle/leakage of just the board") and below 600 mA. `quick_check()`
tests only 12 V and current. The tolerance was narrowed to 4.5 % in `aa67863`,
2018-11-07.

## 4. Triggers and interfaces

| Unit | What runs | Notes |
| --- | --- | --- |
| `start.trigger` | `bin/gpiopoll 25` | "A start button on the jig, pin 25". Description carries the build instructions: `gcc gpiopoll.c -o gpiopoll; sudo chown root gpiopoll; sudo chmod u+s gpiopoll` — setuid root, because it writes `/sys/class/gpio/export`. Falling-edge (`gpiopoll.c:36`) |
| `hotplug.trigger` | `bin/hotplugpoll 6` | "Trigger on hot plug event", same setuid build recipe, rising-edge (`hotplugpoll.c:36`). This is what makes the full sequence start when the boards are seated |
| `webserver.interface` | `/home/pi/code/jig-20-interface-http/target/release/jig-20-interface-http -p 3000 -a 0.0.0.0` | `Format=text` |
| `leds.interface` | `bin/led-interface.sh` | `Format=text`, working directory `bin` |

There is no `.logger` unit in the repository, so test records only reach the web
interface and the LEDs.

`jig-20-interface-http` is "modified specifically for the NeTV2 test scenario"
(`jig-http/README.md:2`). It serves `html/` statically and exposes, all as GETs,
the read endpoints `/current.json`, `/log.json` (with `&start=`/`&end=`),
`/log/current.json`, `/log/previous.json`, `/stdin.txt` and the command
endpoints `/truncate`, `/start`, `/abort`, `/tests`, `/scenarios`, `/scenario`,
`/jig`, `/hello`, `/exit`. The NeTV2 unit file binds `0.0.0.0` rather than the
README's default, so the operator's browser can be another machine.

`led-interface.sh` drives three GPIOs — blue 8, yellow 7, red 1 — announces
itself as `HELLO bash-ltc-jig 1.0`, runs a startup colour sweep, then reads CFTI
lines: `start` turns yellow on, `fail` additionally lights red, `finish` parses
the third field and shows blue for 200-299 and red otherwise, `exit` quits.
`bin/test-lib.sh` is a leftover — its own comment says "most of this is cruft
below from BM17 jig, cull it once the tests are done".

## 5. The test hat

`netv2-testhat` is a PCB, not software: "This circuit board is meant to be
combined with a Raspberry Pi to create the production tester for NeTV2", with "a
'break-away' PCI express header that's meant to be plugged into the NeTV2
Raspberry Pi riser, and then both card edges are inserted simultaneously into
the tester hat board for the full sequence test" (`testhat/README.md:3-11`). The
repository holds Altium sources (`netv2mvp-testhat-v1.PrjPcb`,
`testhat1.SchDoc`, `pi2pci.SchDoc`, `netv2mvp-testhat-v1-route.PCBDOC`) and a
PDF. From what the software drives, the hat provides at minimum: DUT power
switching (GPIO 26), FPGA `PROG_N` (GPIO 24), the JTAG pins, the two ADC128D818
supply monitors with a 12 V in-line current shunt, three status LEDs (GPIO 8, 7,
1), the start button (GPIO 25) and the hot-plug detect (GPIO 6).

## 6. Why two passes

`tests/README.md:21-28`:

> The test requires two passes because a "fully-loaded" FPGA at the current
> litex rev has difficulty routing clocks to four GTP interfaces (it can route
> to one easily, and two with some finagling). [...] to make testing expedient
> we do one test where we test all the features, and then a second, quick
> GTP-only test to confirm all four GTP channels are soldered correctly.

Hence the `gtptester-*` bitstream (tests #4 to #6) and the `tester-*` bitstream
(tests #7 to #9) are separate builds; `make_tester.sh` on the `tester-master`
branch builds both, for both device sizes, via `./netv2mvp.py -p {35,100} -t
{gtptester,tester}` plus one `firmware-tester` make each.

## 7. Where the binaries came from

`tests/.gitmodules` declares four submodules, two of which are the same URL:

| Path | Repository | Pinned commit |
| --- | --- | --- |
| `bin/netv2-fpga` | `AlphamaxMedia/netv2-fpga` | `9af66d5` (2018-10-30), on **`tester-master`** — supplies `tester-images/` and `bin/mknetv2img` |
| `bin/netv2-fpga-userimage` | `AlphamaxMedia/netv2-fpga` | `7b3d0fa` (2018-11-07), on **`master`** — supplies `production-images/` |
| `bin/netv2mvp-scripts` | `AlphamaxMedia/netv2mvp-scripts` | `7da9a52` (2018-10-29) — the OpenOCD configs |
| `bin/flterm` | `timvideos/flterm` | `ee93960` (2017-12-10) |

`tests/README.md:36-42` states the intent: "The netv-fpga repository is actually
included twice, but one on the 'master' branch, and other on the
'tester-master' branch. Each of these include a copy of the production binary,
and the method for updating the tester is thus to do a git pull of the alphamax
repository and pull in the latest published binary." Checked-in binaries were
deliberate: `tester-images/README.md` on `tester-master` says "Booo I know,
people hate that. But the idea here is to check in the actual binary used in the
test program just in case there's some variance in the build process, so
conditions can always be reproduced." `tester-master` HEAD is `cb92495`
(2018-11-17) and carries `tester-images/{gtptester,tester}-{35,100}.bit` plus
`{gtptester,tester}-firmware.bin`, and a `firmware-tester/` source directory
that `master` does not have.

`tests/README.md:75-83` explains why so many paths are absolute: "the earlier
version of exclave used during development has no option to fix the run path
[...] Thus the scripts assume you have done a 'git clone' of the netv2-tests
repository in a directory called /home/pi/code [...] If you change the username,
you'll have to recode all the scripts, unfortunately." Every `.test`,
`.scenario`, `.trigger` and `.interface` uses `/home/pi/code/netv2-tests/...`,
and the shell scripts additionally hard-code `/opt/openocd/bin/openocd` and
`/tmp/{firmware,ufirmware}.{bin,upl}`.

## 8. Imaging the SD cards

Two tools, used in sequence, both outside exclave.

**`usb-mapping`** (`usbmap/README.md`) associates a memorable name with a
physical USB port: you type the name, plug a mass storage device into that port,
it captures the udev event, and on quit it pickles the dictionary to
`usb_map.pkl`. The point is failure reporting — "A dev node (/dev/sdb) doesn't
tell you which physical disk it is" (`pyro/README.md:24-27`).

**`usb-pyromaniac`** (`pyro/README.md`) is the mass burner: a curses UI over up
to seven named ports, `shift-B` to burn, `shift-Q` to quit ("Capital letters are
specified to prevent fat-fingered operators from accidentally starting or
quitting a burn"), a tone at completion, then per-port PASS/FAIL. It runs under
`sudo`, takes `-i IMAGE_DIRECTORY`, and finds `usb_map.pkl` in the invocation
directory unless `-u` says otherwise. Throughput peaked at four simultaneous
drives. Its central idea is that a 16 GB card only needs 4 GB of data, so
instead of `dd`-ing the whole card it writes a right-sized image and resizes
afterwards (lines 14-18); a side benefit is that the master can be refreshed by
re-running the rsync.

`pyro/mkimage-rpi.sh` builds one image directory from a live card, given a
device node, a rootfs size in MiB (about 1000 MiB over what `df` reports used)
and a type prefix. It refuses `/dev/sda*` (line 19), writes
`images/<prefix>-<DD-Mon-YYYY>/`, `dd`s the FAT32 boot partition to `part1.img`,
creates and formats a blank ext4 `part2.ext4`, loop-mounts it and
`rsync -aAXv --exclude={...}` the live rootfs into it (`/dev`, `/proc`, `/sys`,
`/tmp`, `/run`, `/mnt`, `/media`, `/lost+found` excluded), then `e2fsck -f -y`,
`tune2fs -U <uuid>` and `e2fsck` again so the burner need not fsck after each
duplication. It also pipes `fdisk` output through `munge-partition.py` and
appends the `blkid` UUID to produce `partition.txt`, which is the whole
partition scheme in four lines (`pyro/README.md:110-115`):

```text
part1  8192  93802    85611      fat32
part2  98304 31116287 31017984   ext4
partid 0xd81061a1
uuid   efb77116-2573-474b-931a-33b2e14cf331
```

`partid` and `uuid` matter because "The Raspberry Pi boot sequence looks for the
disk ID/partition ID so if that's not set right, the image will do nothing"
(`wiki/Using-NeTV2-as-a-Dev-Board.md:25`). The golden unit's `/boot/cmdline.txt`
still reads `root=PARTUUID=f6104fb5-02`, matching the `Disk identifier:
0xf6104fb5` in the README's worked fdisk example.

`pyro/sanitize-rootfs.sh` runs separately and only on customer images: it
verifies the file is ext4, mounts it, removes `/home/pi/.ssh/*`,
`.bash_history` and `.gitconfig`, and rewrites
`/etc/wpa_supplicant/wpa_supplicant.conf` to a three-line default, wiping stored
wifi passwords. It "doesn't clear things like chrome caches or desktop
preferences", and is separate from imaging "because there are instances where
this shouldn't be run (for example, imaging an RPi image destined to run factory
test infrastruture)" (`pyro/README.md:52-58`).

## 9. `xvcpi`: the other JTAG path

`xvcpi` is an alternative to OpenOCD for anyone who would rather drive the FPGA
from Vivado. It implements a Xilinx Virtual Cable server on the Pi, bit-banging
JTAG on the Pi's GPIOs and listening on TCP port 2542 (`xvcpi/README.md:6-8`);
the bit-bang code was lifted from OpenOCD. Its pinout is identical to
`alphamax-rpi.cfg`: `TMS=GPIO17, TDI=GPIO27, TCK=GPIO4, TDO=GPIO22` (line 17).
Vivado attaches with `hw_server -e 'set auto-open-servers
xilinx-xvc:<host>:2542'` or `open_hw_target -xvc_url <host>:2542`. XVC has no
reset channel, so `xvcpi` supports neither SRST nor TRST (line 21) — the
`PROG_N` handling `dut-on.sh` does over GPIO 24 has no XVC equivalent. No unit
file in `netv2-tests` references it.

## 10. What is reproducible today

**Build-only.** Nothing in this chapter runs end to end without the
`netv2-testhat` PCB, and no such board is available here.

| Piece | Status without the test hat |
| --- | --- |
| `tester-driver`, `gpiopoll`, `hotplugpoll` | compile from source; every code path then reaches an ADC or a GPIO that is not connected, so they return garbage or never fire |
| `dut-on.sh`, `dut-off.sh`, `led-interface.sh` | need WiringPi's `gpio` binary and drive pins that go nowhere |
| `getidcode.sh`, `setup_*.sh`, `burn-spi.sh` | the same OpenOCD flow the shipped updater uses, so the JTAG half is reproducible on a stock unit — but they write SPI flash, which the modernisation plan forbids on the golden unit (D6, D8) |
| the four `.expect` scripts | need `expect`, a `/dev/ttyAMA0` carrying the FPGA REPL, the `tester-*` bitstreams that answer `TESTER_NX8D`, and (for the ping test) a DUT at `10.0.11.2` |
| `exclave`, `jig-20-interface-http` | both build with cargo; exclave loads the config directory and reports the jig absent, since `/boot/netv2-jig` does not exist |
| `usb-mapping`, `usb-pyromaniac` | runnable in principle, irrelevant without master images to burn |

Two mismatches to carry forward if any of this is revived:

- **Serial device.** Every expect script uses `/dev/ttyAMA0`
  (`check-repl.expect:4`, `run-test.expect:4`, `ram-test.expect:4`,
  `test-lib.sh:8`), while the shipped product image uses `/dev/ttyS0`
  (`netv2mvp-scripts/set_rgb.sh:4`, `netv2-status.js:2`). On a Pi 3 these are
  different UARTs — `ttyAMA0` the PL011, `ttyS0` the mini-UART — and which one
  reaches the GPIO header depends on whether Bluetooth is enabled. The tester
  image and the product image were configured differently.
- **OpenOCD prefix.** The test scripts call `/opt/openocd/bin/openocd`
  absolutely, matching `exclave/doc/Jig.md`; the shipped product image installed
  OpenOCD under `/usr/local`, where `/opt/openocd` does not exist. See
  `docs/original/pi-software.md` section 1.
