# NeTV2 Pi-side tooling (Raspberry Pi OS trixie)

Modernised Raspberry-Pi-side programming, update, and status tooling for the
NeTV2 on current Raspberry Pi OS (Debian 13 "trixie"), replacing the 2019
Raspbian-9 stack. Background and the migration table:
`docs/current/pi-software-trixie.md`.

| Path | What it is |
| --- | --- |
| `openocd/netv2-jtag.cfg` | OpenOCD 0.12 `linuxgpiod` interface config, one file for Pi 3/4/5, NeTV2 pin map, RP1/BCM gpiochip auto-detect (replaces the 2019 `bcm2835gpio` cfgs) |
| `openocd/README.md` | OpenOCD and openFPGALoader command lines |
| `netv2_update.py` | Python 3 update tool (replaces `update-fpga.sh`): IDCODE read/gate, volatile `pld load`, and a **guarded** SPI-flash path |
| `netv2_status.py` | Python 3 status reporter (replaces `netv2-status.js`): UART telemetry -> JSON on `http://127.0.0.1:6502/` |
| `systemd/netv2-status.service`, `systemd/netv2-status.env` | systemd unit (replaces pm2) for the status reporter |
| `magicmirror-port.md` | port plan for the MagicMirror overlay app (deferred; needs the overlay gateware) |

## Quick start (on a Pi running trixie)

```bash
sudo apt install openocd
cd software/pi
python3 netv2_update.py idcode                 # read + identify the FPGA
python3 netv2_update.py load /path/to.bit      # volatile load (no flash)
```

## Safety

The `flash` subcommand writes SPI NOR persistently. It calls the golden-unit
guard (`tests/hardware/hosts.py`) and **refuses on the golden reference unit
rpi3-netv2**, requires the explicit `--i-have-tim-go-ahead` flag, and fails
closed if the guard is unavailable. Only volatile `load` is ever used against
the golden unit. See `docs/current/pi-software-trixie.md`.

## Tests

`tests/unit/test_netv2_update.py` — IDCODE parsing/identification, the
golden-unit refusal, the confirmation gate, and the volatile-vs-flash decision,
all against a mock runner (no hardware). Run: `uv run pytest tests/unit`.
