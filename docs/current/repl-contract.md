# NeTV2 console (REPL) contract

Generated 2026-09-05 by `scripts/gen_repl_contract.py` from `tests/hdmi-suite/netv2test/`.
The modern firmware must keep the text output of every command below
byte-compatible with the 2019 firmware (`legacy/firmware/ci.c`), because the
suite parses it. New commands are additive. `%d` marks an integer argument.

| Command | Used by |
|---------|---------|
| `debug ddr` | console.py |
| `debug dna` | console.py |
| `debug dumpe` | console.py |
| `debug dvimode0` | manual |
| `debug hdmimode0` | manual |
| `debug hpdforce` | console.py |
| `debug hpdrelax` | console.py |
| `debug input0` | console.py |
| `debug input1` | console.py |
| `debug override` | console.py |
| `debug rect` | console.py |
| `debug rectoff` | console.py |
| `debug rectthresh %d` | console.py |
| `debug run` | console.py |
| `debug setrect %d %d %d %d` | console.py |
| `debug stop` | console.py |
| `debug t4d` | manual |
| `debug t4i` | manual |
| `debug xadc` | console.py |
| `hdp_toggle %d` | console.py |
| `help` | console.py |
| `json` | console.py |
| `json off` | console.py |
| `json on` | console.py |
| `status` | console.py |
| `video_matrix list` | tests.py |
| `video_mode %d` | console.py |
| `video_mode list` | tests.py |
