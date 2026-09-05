# Rebuilding the 2019 design in 2026

A time-boxed experiment (phase 1, task 15): can the original NeTV2 gateware
still be regenerated from the pinned 2019 sources, and synthesised with the
Vivado that is installed today? The answer is the deliverable, success or
failure. This page records exactly what was run, what broke, and what was
changed to get past each break.

**No bitstream produced by this work was loaded onto any board.** Nothing here
was programmed, flashed, or connected to hardware; the experiment stops at
files on disk.

## 1. Verdict

| Stage | Result |
| --- | --- |
| Fetch the seven pinned dependency submodules | works |
| Generate `top.v` from migen (no Vivado, no RISC-V toolchain) | **works, unmodified** |
| Compile the LiteX BIOS with a 2022 RISC-V toolchain | works, needs a 2-line build-flag patch |
| Vivado 2025.2 synthesis of the 2019 RTL | **works, 0 errors** |
| Vivado 2025.2 place and route | **works, router completes** |
| Timing closure | **fails: WNS -7.505 ns, TNS -1537.7 ns after routing** |
| `write_bitstream` | blocked by a Vivado-in-container crash, not by the design |

The headline is that **the 2019 design is still buildable**. Migen emits the
same Verilog it always did, and Vivado 2025.2 synthesises, places and routes it
end to end with zero errors. Two things stand out and both matter for later
phases:

1. **The 35T is nearly full.** Block RAM sits at **95%** (47.5 of 50 tiles) and
   slices at **75%**. There is almost no room left on the xc7a35t for new
   gateware.
2. **The design does not close timing under Vivado 2025.2** (WNS -7.505 ns, 515
   failing endpoints after synthesis). The shipped 2019 bitstreams were built
   with a 2018/2019 Vivado; a modern Vivado's timing model, and its different
   placement, do not reproduce that result. Any plan that involves rebuilding
   this gateware has to budget for timing work. See
   [clocking.md](clocking.md) for the 23 timing exceptions the design relies on.

## 2. Environment

Everything ran inside a container so that a Python 3.7 / 2019-LiteX
environment could exist without touching the host. Host: 12-core Intel i7-8700,
31 GB RAM, Vivado 2025.2 at `/opt/Xilinx/2025.2` (bind-mounted read-only).

`legacy/Dockerfile.rebuild2019` builds the image:

- base `python:3.7-slim` (Debian 12 bookworm, Python 3.7.17)
- `gcc-riscv64-unknown-elf` 12.2.0, GNU ld 2.40, GNU Make 4.3
- `pyserial==3.4`, `colorama`
- Vivado runtime libraries and an `en_US.UTF-8` locale (see section 5)

### Dependency pins

The seven submodules under `legacy/deps/`, at the SHAs recorded on this branch
(restored in commit `a1af75e`; the branch previously carried wrong pins):

| Submodule | SHA | Date | Subject |
| --- | --- | --- | --- |
| `litex` | `c692e62b1cf0d30ea2a3f62ddc342423fa481f0e` | 2019-03-21 | update submodule ref to latest upstream version |
| `migen` | `b80116b8bddeb6fd53d6e8c54402f5ca5d4dc1a6` | 2018-08-07 | merge from m-labs master |
| `litedram` | `5a7af9c580209f5d437d2eb156a73dc34f897a51` | 2018-12-02 | commit changes before continuing on video dev |
| `litevideo` | `3bc5a24a08881c96d203d9b9244092704376d29e` | 2019-09-13 | add delay alignment feature |
| `liteeth` | `40b99ecc05ee490d77477cba542db6d63333c390` | 2018-09-23 | test: use new RemoteClient import |
| `litescope` | `1634fa35bb9f2717ab355ca2e494e1d02fd489ec` | 2018-09-23 | test: use new RemoteClient import |
| `pyserial` | `d7ae8f668f0d55abe2808144a1ee6c8e1254f13b` | 2018-06-15 | merge PR #354 |

One nested submodule inside `litex` is also required, because the VexRiscv core
is delivered as pre-generated Verilog rather than as migen:
`litex/soc/cores/cpu/vexriscv/verilog` at `395c5ee2868ffbe36db290a4a4ec0eabc0f5c2b5`
(m-labs/VexRiscv-verilog, 2018-07-01), which supplies `VexRiscv.v`. The
generated `top.tcl` names that file explicitly, so synthesis fails without it.

`litex`'s other nested submodules are **not** fetchable and are not needed:
`litex/soc/software/compiler_rt` points at `http://llvm.org/git/compiler-rt.git`,
which no longer exists (LLVM moved to a monorepo on GitHub in 2019), and
`litex/build/sim/core/modules/ethernet/tapcfg` is likewise unreachable. A plain
recursive clone of this repository therefore cannot succeed today. Fetching
each dependency by path, as below, works.

```bash
git submodule update --init legacy/deps/litedram
git submodule update --init legacy/deps/liteeth
git submodule update --init legacy/deps/litescope
git submodule update --init legacy/deps/litevideo
git submodule update --init legacy/deps/litex
git submodule update --init legacy/deps/migen
git submodule update --init legacy/deps/pyserial
# VexRiscv.v, from inside the litex submodule:
git -C legacy/deps/litex submodule update --init litex/soc/cores/cpu/vexriscv/verilog
```

## 3. The commands

Build the image:

```bash
docker build -t netv2-rebuild2019 -f legacy/Dockerfile.rebuild2019 legacy
```

**Verilog only** (no Vivado, no RISC-V toolchain, no BIOS). `legacy/netv2mvp.py`
cannot do this on its own: its `main()` accepts only `-p/-t/-d/-c`, and its
`Builder` always compiles the BIOS before writing Verilog. So
`legacy/rebuild2019_verilog.py` — clearly marked as 2026 tooling, the only
driver added under `legacy/` — constructs the same `Platform` and
`VideoOverlaySoC` and passes `compile_software=False, compile_gateware=False`:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/work \
  -v "$PWD/legacy:/work" \
  netv2-rebuild2019 python3 rebuild2019_verilog.py 35 --lx-ignore-deps
```

**Full original flow**, exactly the 2019 entry point, with the 2026 workarounds
supplied from outside the tree as read-only bind mounts:

```bash
docker run --rm --init --shm-size=2g --user "$(id -u):$(id -g)" \
  -e HOME=/xhome -v "$TMP/xhome:/xhome" \
  -v "$PWD/legacy:/work" -w /work \
  -v "$TMP/crt/compiler_rt:/work/deps/litex/litex/soc/software/compiler_rt:ro" \
  -v "$TMP/patched/common.mak:/work/deps/litex/litex/soc/software/common.mak:ro" \
  -v /opt/Xilinx:/xilinx:ro -v /run/udev:/run/udev:ro \
  netv2-rebuild2019 python3 netv2mvp.py -p 35 --lx-ignore-deps
```

`--lx-ignore-deps` is required because `lxbuildenv.py` otherwise exits when it
cannot find a RISC-V compiler and Vivado on `PATH` under the names it expects.
Inside the container there is no `.git`, so `lxbuildenv` prints
`Missing submodules -- updating` followed by `fatal: not a git repository` and
carries on; that pair of messages is harmless and appears in every run.

## 4. Timeline

Roughly 3.5 hours of wall clock, of which about 100 minutes were Vivado.

| Elapsed | Event |
| --- | --- |
| 0:00 | submodules fetched |
| 1:15 | container image built |
| 1:18 | **`top.v` generated on the first attempt**, unmodified sources |
| 1:19 | Vivado in the container: locale abort |
| 1:21 | BIOS: `compiler_rt` submodule missing |
| 1:24 | BIOS: `mode (TI)` unsupported on rv32 |
| 1:26 | BIOS: `csrw` needs Zicsr |
| 1:29 | BIOS: `ld` rejects `-nodefaultlibs` |
| 1:30 | **`bios.bin` built** |
| 1:31 | litex cannot find Vivado's `settings64.sh` |
| 1:35 | Vivado missing `libncurses.so.5`, then `libpixman-1.so.0` |
| 1:45 | **synthesis starts, license granted for `xc7a35t`** |
| 1:52 | **synthesis finishes: 0 errors**, 1 critical warning, 9255 warnings |
| 2:20 | Vivado hangs after synthesis (container `/dev/shm`, PID-1 reaping) |
| 2:40 | **place and route complete**, timing not met |
| 2:52 | Vivado aborts in WebTalk telemetry before `write_bitstream` |
| 3:10 | retry with WebTalk disabled from `Vivado_init.tcl`: same abort |
| 4:00 | retry with `/run/udev` mounted: same abort; time box reached |

## 5. What broke, and the fix

Nine distinct failures. **None of the fixes modified any pre-existing file in
this repository.** Every source-level change is supplied to the container as a
read-only bind mount over the submodule's file; the tree on disk is untouched,
and `git status` after the experiment shows only the three new files this task
created plus `legacy/build/` (git-ignored). The one source patch is recorded in
`legacy/rebuild2019.patch` for the record — it is documentation, not something
that is ever applied to the checkout.

### 5.1 Vivado aborts on a missing locale

```
/opt/Xilinx/2025.2/Vivado/bin/rdiArgs.sh: line 37: warning: setlocale: LC_ALL: cannot change locale (en_US.UTF-8)
terminate called after throwing an instance of 'std::runtime_error'
  what():  locale::facet::_S_create_c_locale name not valid
```

`bin/rdiArgs.sh` unconditionally does `export LC_ALL="en_US.UTF-8"`, so no
environment variable can override it; the locale has to exist.
`python:3.7-slim` ships none. Fixed in the Dockerfile by installing `locales`
and running `localedef ... en_US.UTF-8`.

### 5.2 The `compiler_rt` submodule is gone

```
make: *** No rule to make target 'umodsi3.o', needed by 'libcompiler_rt.a'.  Stop.
```

`litex/soc/software/libcompiler_rt/Makefile` compiles about 40 files out of
`$(SOC_DIRECTORY)/software/compiler_rt/lib/builtins/`, which is the dead
`llvm.org` submodule. Substituted with the `lib/builtins` tree from an LLVM
release of the right era, bind-mounted over the empty submodule directory.

### 5.3 The obvious substitution is the wrong LLVM

Using LLVM 8.0.0 first:

```
int_types.h:77:1: error: unable to emulate 'TI'
   77 | typedef int      ti_int __attribute__ ((mode (TI)));
```

LLVM 8 added `defined(__riscv)` to the `CRT_HAS_128BIT` guard, which is correct
for rv64 but breaks rv32 under GCC. **LLVM 6.0.1** predates that line and
compiles cleanly; that is what the flow uses.

### 5.4 `csrw` needs the Zicsr extension

```
crt0-vexriscv.S:59: Error: unrecognized opcode `csrw mtvec,a0', extension `zicsr' required
```

binutils 2.36 split the CSR instructions into Zicsr and `fence.i` into Zifencei.
`litex/soc/cores/cpu/vexriscv/core.py:13` emits `-march=rv32im`. A later
`-march` on the command line wins, so appending
`-march=rv32im_zicsr_zifencei` to `COMMONFLAGS` is enough. It changes no
generated code, only what the assembler will accept.

### 5.5 `ld` rejects `-nodefaultlibs`

```
riscv64-unknown-elf-ld: Error: unable to disambiguate: -nodefaultlibs (did you mean --nodefaultlibs ?)
```

LiteX passes `LDFLAGS` straight to `ld`, but `-nodefaultlibs` is a **gcc driver**
option. Older `ld` accepted it by unique-prefix abbreviation; binutils 2.40
finds several `--no*` matches. `-nostdlib` on the same line already gives `ld`
the intended behaviour, so the redundant flag is dropped.

5.4 and 5.5 are the two hunks in `legacy/rebuild2019.patch`, both in
`litex/soc/software/common.mak`. After them the BIOS builds: `bios.elf`
180,320 bytes, **`bios.bin` 20,820 bytes**, and `gateware/mem.init` 38,502
bytes of integrated-ROM initialisation.

### 5.6 litex cannot find Vivado

```
OSError: Unable to locate Vivado directory or settings.
```

`litex/build/xilinx/vivado.py:216-217` hard-codes
`toolchain_path="/opt/Xilinx/Vivado"` and then looks for
`<path>/<version>/settings64.sh`. The modern installer uses
`/opt/Xilinx/2025.2/Vivado/settings64.sh` instead, and `netv2mvp.py` exposes no
way to pass a different path. Fixed without any code change: the host tree is
mounted at `/xilinx`, and the image symlinks both `/opt/Xilinx/2025.2` and
`/opt/Xilinx/Vivado/2025.2` onto it. (A read-only bind mount of `/opt/Xilinx`
cannot be given a child mount, which is why the indirection is needed.)

### 5.7 Missing Vivado runtime libraries

```
couldn't load file "libxv_commontasks.so": libncurses.so.5: cannot open shared object file
couldn't load file "libxv_tcltasks.so": libpixman-1.so.0: cannot open shared object file
ERROR: [Common 17-217] Failed to load feature 'core'.
```

Found one at a time. The Dockerfile adds `libncurses5` and a batch-mode set:
`libpixman-1-0 libpng16-16 libedit2 libelf1 libunwind8 libusb-1.0-0 libgomp1
libfreetype6 libfontconfig1 libglib2.0-0 libbz2-1.0 zlib1g libxml2`.

### 5.8 Vivado hangs after synthesis

Synthesis completed, then Vivado sat at **0% CPU for 26 minutes** in
`report_timing_summary`, its main thread in `futex_wait_queue` with several
unreaped zombie children. This is the container environment, not the design.
Fixed with three run flags: `--init` (a real PID 1 that reaps children),
`--shm-size=2g` (the 64 MB default `/dev/shm` is too small for Vivado), and a
**writable** `HOME` — a copy of `~/.Xilinx` in scratch rather than the host's,
mounted read-only, so Vivado can write its own state without touching the
host's installation.

### 5.9 WebTalk telemetry aborts the run (unresolved)

After the router reports success:

```
Routing Is Done.
Abnormal program termination (6)
Please check '/work/build/gateware/hs_err_pid137.log' for details
```

The crash log stack is unambiguous, and has nothing to do with the NeTV2 design:

```
HAPRDesign::prepAndTransmitWebtalkData(...)
XilReg::Utils::GetRegInfoWebTalk(...)
XilReg::Utils::GetHostInfo(...)
libXil_lmgr11.so(...)
libudev.so.1(udev_enumerate_scan_devices+0x20a)
libc.so.6(realloc+0x1af)
libc.so.6(abort+0xd3)
```

Vivado's licensing library builds a host fingerprint by enumerating devices
through `libudev`, which aborts inside the container. Two remedies were tried
inside the time box and **neither worked**:

- `config_webtalk -user off` from a `Vivado_init.tcl` in
  `$HOME/.Xilinx/Vivado/`. The log confirms it is sourced
  (`Sourcing tcl script '/xhome/.Xilinx/Vivado/Vivado_init.tcl'`), but it does
  not prevent the call.
- Bind-mounting the host's `/run/udev` read-only into the container. Identical
  abort, same stack.

This crash occurs **after** `route_design` completes, so it costs only
`write_bitstream`; every implementation result below was produced before it.
It is also entirely reproducible: three separate full runs all aborted at the
same point, and the last two produced byte-identical routing checksums
(`Ending Routing Task | Checksum: e08d79a0`) and identical timing numbers, so
the flow is deterministic up to that point. The remaining lead is to run Vivado
outside the container (see section 7).

## 6. Results

### 6.1 Generated Verilog

`build/verilog-only-35/gateware/top.v`: **43,131 lines, 2,982,029 bytes**, plus
`top.xdc` (27,583 bytes), `top.tcl`, and the `edid_mem*.init` / `mem*.init`
memory images. Byte-identical in size to the `top.v` the full flow emits. This
step needed **no changes at all** — 2019 migen still runs on Python 3.7 and
produces the design.

### 6.2 Synthesis

`synth_design -top top -part xc7a35t-fgg484-2`, about 5 minutes:

```
Synthesis finished with 0 errors, 1 critical warnings and 9255 warnings.
```

The single critical warning is a block-RAM read/write collision advisory on
`top__GCB5/storage_16_reg`. The 9255 warnings are overwhelmingly the usual
migen-generated width and unused-signal noise.

### 6.3 Utilisation (xc7a35tfgg484-2, fully placed)

From `top_utilization_place.rpt`:

| Site type | Used | Available | Util% |
| --- | ---: | ---: | ---: |
| Slice LUTs | 15,305 | 20,800 | **73.58** |
| — LUT as logic | 14,252 | 20,800 | 68.52 |
| — LUT as memory | 1,053 | 9,600 | 10.97 |
| Slice registers (all FFs) | 19,498 | 41,600 | 46.87 |
| Slices occupied | 6,135 | 8,150 | **75.28** |
| F7 muxes | 488 | 16,300 | 2.99 |
| F8 muxes | 83 | 8,150 | 1.02 |
| Unique control sets | 852 | 8,150 | 10.45 |
| **Block RAM tile** | **47.5** | **50** | **95.00** |
| — RAMB36E1 | 27 | 50 | 54.00 |
| — RAMB18E1 | 41 | 100 | 41.00 |
| DSPs | 6 | 90 | 6.67 |
| Bonded IOB | 127 | 250 | 50.80 |

Clocking, which is the part most relevant to [clocking.md](clocking.md):

| Site type | Used | Available | Util% |
| --- | ---: | ---: | ---: |
| **MMCME2_ADV** | **4** | 5 | **80.00** |
| **PLLE2_ADV** | **2** | 5 | 40.00 |
| BUFGCTRL | 15 | 32 | 46.88 |
| BUFIO | 5 | 20 | 25.00 |
| BUFR | 3 | 20 | 15.00 |
| BUFMRCE / BUFHCE | 0 | 10 / 72 | 0.00 |

Also placed: 73 `OSERDESE2` and 44 `ISERDESE2`, the HDMI input and output
serialisers.

Post-synthesis LUT count was 15,915 (76.51%) before placement optimisation
brought it to 15,305.

**Six of the seven available MMCM/PLL tiles are in use, and block RAM is at
95%.** Both are effectively exhausted. Any future gateware work on the 35T part
has to free resources before it can add any.

### 6.4 Timing — not met

Post-synthesis (`top_timing_synth.rpt`):

| WNS(ns) | TNS(ns) | TNS failing | TNS total | WHS(ns) | THS(ns) | THS failing |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **-7.684** | -802.621 | 515 | 49,241 | -2.579 | -456.809 | 528 |

Post-route estimate, from the router:

```
INFO: [Route 35-57] Estimated Timing Summary | WNS=-7.505 | TNS=-1537.712| WHS=0.050  | THS=0.000  |
WARNING: [Route 35-328] Router estimated timing not met.
```

Hold is clean after routing (WHS +0.050 ns, THS 0). Setup is not: **-7.505 ns
worst negative slack** and -1537.7 ns total. The signed-off
`report_timing_summary -datasheet` run comes after `phys_opt_design` in
`top.tcl` and was lost to the WebTalk crash, so the numbers above are the
router's estimate rather than a full signoff — but a 7.5 ns miss is not a
reporting artefact.

Implementation was otherwise clean: DRC finished with 0 errors, and
`route_design` reported `[Route 35-16] Router Completed Successfully` in 730
seconds.

## 7. What a full reproduction still needs

1. **Get past the WebTalk abort** so `write_bitstream` runs. Mounting
   `/run/udev` and disabling WebTalk from `Vivado_init.tcl` were both tried and
   both failed (5.9). What remains, in order of promise: **run Vivado on the
   host** rather than in the container, driving it with the already-generated
   `build/gateware/top.tcl` — that file is self-contained and needs only
   `top.v`, `top.xdc`, the `*.init` files, `VexRiscv.v` and `legacy/overlay/*.v`
   at the paths it names, so the container is only needed for the migen and
   BIOS half of the flow; failing that, `--privileged` or a fuller `/sys`
   inside the container; or a newer/older Vivado whose licensing library does
   not take the `libudev` path.
2. **Timing closure.** The design misses setup by 7.5 ns under Vivado 2025.2.
   Establishing whether a 2018/2019 Vivado closes it — and if so, which
   constraint or placement behaviour changed — is a piece of work in its own
   right, and is the main open question this experiment raises.
3. **Compare against the shipped bitstreams.** `legacy/production-images/`
   contains the 2019 outputs; a rebuilt `top.bit` can be compared for size and
   the design compared for resource counts, which would tell us how far the
   modern toolchain has drifted.
4. **The other part variants.** Only `-p 35` was attempted. `-p 50` and
   `-p 100` have more room and would likely close timing more easily; the 100T
   in particular is the obvious target if the 35T proves too full.
5. **A permanent home for the substituted `compiler_rt`.** Vendoring LLVM
   6.0.1's `lib/builtins`, or switching the BIOS to the toolchain's own
   `libgcc`, would remove the dependency on a dead URL.

## 8. Files this task added

- `legacy/Dockerfile.rebuild2019` — the container image.
- `legacy/rebuild2019_verilog.py` — 2026 driver for Verilog-only generation.
- `legacy/rebuild2019.patch` — the record of the two `common.mak` build-flag
  changes. Applied only as a read-only bind mount inside the container; never
  to the checkout.
- `docs/original/rebuild-2019.md` — this page.

Build outputs are under `legacy/build/`, which the root `.gitignore` rule
`build` matches at any depth. The full-flow log is
`legacy/build/rebuild-full.log`.

One wrinkle worth noting: `netv2mvp.py:1298` hard-codes
`csr_csv="test/csr.csv"`, so a full run also writes `legacy/test/csr.csv` and
`legacy/test/analyzer.csv`. The root `.gitignore` entries for those paths are
anchored at the repository root and do not match them under `legacy/`, so they
show up as untracked files after a build. They are generated artefacts, not
sources.
