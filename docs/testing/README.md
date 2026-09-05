# Testing

- Rigs: `rpi3-netv2` (golden 35T unit, MS2109 capture, `rpiz-3` source; volatile
  JTAG loads only, never flash, never power-cycle), `rpi5-netv2` (100T, PCIe,
  UART, no capture). Details in `tests/hardware/hosts.py`.
- Suite: `tests/hdmi-suite/` (runs on the Pi attached to the board).
- Reports: `docs/testing/reports/<YYYY-MM>-<name>/` with `report.md`, `report.json`,
  evidence. The imported suite's own historical output lives at
  `tests/hdmi-suite/reports/`.

Evidence images are currently committed as raw PPM. Follow-up (tracked for the
netv2-testsuite repo): have the capture pipeline emit PNG, or move
`docs/testing/reports/*/evidence/` to Git LFS, before baseline captures
recur.
