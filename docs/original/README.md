# How NeTV2 worked originally (2018 to 2019)

Written from the AlphamaxMedia sources at `legacy/` (netv2-fpga master 4f4dd0d)
and the stock unit `rpi3-netv2`. Each page cites the file and line it describes.

Pages are written in phase 1; a link below is a dead link until then.

- [hardware.md](hardware.md): board, FPGA variants, Pi connections, jumpers
- [gateware.md](gateware.md): `VideoOverlaySoC`, video pipeline, compositing, HDCP
- [clocking.md](clocking.md): CRG, HDMI input clocking, DRP, timing exceptions
- [firmware.md](firmware.md): REPL, boot, EDID, multires, MMCM tables
- [boot-and-flash.md](boot-and-flash.md): BIOS, SPI NOR layout, `mknetv2img`, updater
- [pi-software.md](pi-software.md): OpenOCD flow, MagicMirror, pm2, JSON feed
- [factory-test.md](factory-test.md): exclave, netv2-tests, jig-20, test hat, imaging
- [rebuild-2019.md](rebuild-2019.md): time-boxed attempt to rebuild the 2019 design today
