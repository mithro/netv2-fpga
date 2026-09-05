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
