# legacy/

The unmodified AlphamaxMedia `netv2-fpga` tree (master 4f4dd0d, 2023-07-13) as
shipped: `netv2mvp.py` (LiteX 2019-03 plus forks pinned as submodules under
`deps/`), the RISC-V firmware, the HDCP/phase-alignment Verilog under `overlay/`,
and the production and testing bitstreams. No original file is modified; the
only additions are two 2026 tooling files for the rebuild experiment
(`Dockerfile.rebuild2019`, `rebuild2019_verilog.py`). The modern tree lives one
level up. See `docs/original/` for the description.
