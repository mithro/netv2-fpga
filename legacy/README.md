# legacy/

The unmodified AlphamaxMedia `netv2-fpga` tree (master 4f4dd0d, 2023-07-13) as
shipped: `netv2mvp.py` (LiteX 2019-03 plus forks pinned as submodules under
`deps/`), the RISC-V firmware, the HDCP/phase-alignment Verilog under `overlay/`,
and the production and testing bitstreams. No original file is modified; the
only additions are two 2026 tooling files (`Dockerfile.rebuild2019`,
`rebuild2019_verilog.py`) that will be added by the phase 1 rebuild experiment.
The modern tree lives one level up. See `docs/original/` for the description.

**Warning:** `legacy/testing-images/testing-fpga.sh` and the netv2mvp-scripts
update flow burn the SPI NOR of whatever NeTV2 is attached, with no host check,
and their hard-coded paths match the reference unit `rpi3-netv2`. Never run them
there; see `tests/hardware/hosts.py`.
