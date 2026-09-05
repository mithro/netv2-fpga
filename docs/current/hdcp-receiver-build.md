# HDCP receiver bridge build (task H5)

Sibling to [../original/rebuild-2019.md](../original/rebuild-2019.md). Records the
Vivado 2025.2 build of the HDCP-receiver bridge (`legacy/netv2mvp_hdcprx.py`) for
both FPGA variants, the post-route timing and utilisation, and what it means for
the hardware attempt.

**No bitstream produced by this work was loaded onto any board.** As with the
phase-1 rebuild, the flow stops at reports on disk; nothing was programmed,
flashed, or connected to hardware. Per spec §10.3 no negative-slack bitstream is
ever loaded, and neither part below closes timing.

## 1. What was built

`legacy/netv2mvp_hdcprx.py` extends the *proven* 2019 `VideoOverlaySoC` (from
`legacy/netv2mvp.py`, unmodified) and adds an HDCP-1.x receiver on the hdmi_in0
DDC bus. It is built on the 2019 migen/litex toolchain inside the `rebuild2019`
container, exactly as the phase-1 rebuild, so it reuses the whole overlay SoC.

The three receiver modules are instantiated directly with migen `Instance(...)`
and 2019-style CSRs (mirroring how `netv2mvp.py`'s `HDCP` / `I2Csnoop` wrap
`hdcp_mod` / `i2c_snoop`), **not** through the modern
`netv2/gateware/hdcp/receiver.py` (which targets migen 0.9.2 / LiteX 2026.04 for
the eventual modern port and is deliberately not imported):

* `hdcp_rx.v`        — I2C slave + 40×56 key store + Km accumulator, **eth** (50 MHz).
* `hdcp_mod_rx.v`    — receiver FSM (instantiates `hdcp_cipher_rx.v` internally),
  produces R0'/Ri', **pix_o** (74.25/148.5 MHz).

The shared block-cipher primitives (`hdcp_block`, `hdcp_lfsr`, `shuffle_network`,
`diff_network`) that `hdcp_cipher_rx` references are already added by
`VideoOverlaySoC` from `legacy/overlay/`, so only the three receiver `.v` files
are added (bind-mounted into the container at `/netv2/gateware/hdcp`).

Both variants **elaborate** and generate `top.v` in the container
(a7-100: 44 472 lines vs the plain overlay's 43 131; a7-35 likewise), Vivado
runs synthesis (0 errors) → place → **route (`Router Completed Successfully`)**
for both. As in phase-1, `write_bitstream` is not reached: Vivado aborts in
`phys_opt_design`/WebTalk telemetry (`libudev` container crash, rebuild-2019.md
§5.9). A `top.bit` is not required — the utilisation and post-route timing
reports are the deliverable.

### 2019-migen bridge details worth recording

* **DDC override handoff (SAFETY, spec §10.3).** `hdmi_sda_over_up` (G20, a 5 V
  push-pull) is left tied `0` exactly as the original; only `hdmi_sda_over_dn`
  (F20, the open-drain FET gate) is handed to the receiver's `sda_drive_low`.
  Because `over_up` is never driven high, mutual exclusion holds trivially. The
  original `VideoOverlaySoC` drives `hdmi_sda_over_dn.eq(0)` in comb; the bridge
  removes **exactly that one** combinational `_Assign` at the fragment level
  (`release_comb_driver`, re-implemented against the pinned 2019 migen — verified
  `_Assign.l` is `wrap(target)` and is identity for a plain Signal;
  `_fragment.comb` is a list; `If.t/.f`, `Case.cases` nest) and asserts exactly
  one was removed, else raises, so a mismatch fails loudly rather than
  double-driving the FET gate. The pad handle is recovered with
  `platform.lookup_request("hdmi_sda_over_dn")` (it was already `request()`-ed by
  the parent). Generated `top.v` confirms `assign hdmi_sda_over_up = 1'd0;` and
  `assign hdmi_sda_over_dn = hdcpreceiverrx_sda_drive_low;`.
* **Km path select (spec §6).** A pix_o mux drives `Km`/`Km_valid`/`An` from the
  hardware accumulator when `km_source=1` (the value to use — the legacy CPU
  km.c path uses the real DCP matrix, incompatible with our closed-loop keys) or
  the legacy CPU CSR when `km_source=0`. The pre-existing decrypt `hdcp_mod`
  Instance takes Km from a CSR and lives inside the `self.hdcp` submodule; the
  bridge re-points its `Km`/`Km_valid`/`An` input ports to the mux at the
  fragment level (`rebind_instance_inputs`, asserts exactly one matching
  Instance and one item per port) without editing `netv2mvp.py`. `top.v`
  confirms `hdcp_mod` now reads `.Km(Km_mux) .Km_valid(Kmvalid_mux) .An(An_mux)`.
* **CDC.** The sys/eth/pix_o crossings use 2019 migen `MultiReg` /
  `PulseSynchronizer` / `BusSynchronizer` (all present and API-compatible). No
  new timing constraints are needed: sys↔eth and eth↔pix_o are already
  false-pathed both directions by `add_false_path_constraints`, sys↔pix_o by the
  sys/hdmi_in0 clock-group, and every `MultiReg` destination FF (including those
  inside the synchronizers) by the toolchain's global `mr_ff` `set_false_path`.
* **No key material** is baked into the bitstream; firmware loads keys at runtime
  over the CSRs (task H7). CSR bank `hdcprx` is allocated at `0xe000e800`.

## 2. Results

Environment identical to the phase-1 rebuild (Vivado 2025.2 in the
`rebuild2019` container). Post-route numbers are the router's end-of-route
`[Route 35-57] Estimated Timing Summary`; the signed-off
`report_timing_summary` after `route_design` is lost to the same WebTalk abort,
so failing-endpoint counts are quoted from the post-synthesis
`top_timing_synth.rpt` (whose 515-endpoint WNS path survives to route). Both
routers completed successfully; a 7–8 ns miss is not a reporting artefact.

### 2.1 Post-route timing — neither part closes

| Part | WNS (ns) | TNS (ns) | WHS (ns) | THS (ns) | Router |
| --- | ---: | ---: | ---: | ---: | --- |
| **a7-35** (xc7a35t-fgg484-2)  | **-8.100** | -1604.327 | +0.051 | 0.000 | Completed |
| **a7-100** (xc7a100t-fgg484-2) | **-8.006** | -1557.803 | +0.025 | 0.000 | Completed |

Hold is clean on both (WHS positive, THS 0). Setup fails on both by ~8 ns. The
two parts miss by essentially the same margin (0.1 ns apart), and by roughly the
phase-1 plain-overlay baseline (35T WNS **-7.505** with no receiver).

Post-synthesis both parts report an **identical 515 failing setup endpoints**
(the same count phase-1's receiver-less 35T reported), worst slack **-7.367 ns**
(100T) / **-7.569 ns** (35T). The WNS path is the pre-existing
`sys_clk → hdmi_in1_pix` (hdmi_in1_mmcm_clk0) crossing — a DDR/DMA pixel-clock
path — and the other violated paths are the HDMI output serialiser
(`s7hdmioutencoderserializer`/`OSERDESE2`) paths in the pix5x_o domain. See
[../original/clocking.md](../original/clocking.md).

### 2.2 Utilisation

From `top_utilization_place.rpt` / `top_clock_utilization.rpt`:

| Site type | a7-35 | | a7-100 | | phase-1 35T (no rx) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Slice LUTs        | 17 088 | 82.15% | 17 072 | 26.93% | 15 305 (73.58%) |
| Slice Registers (FF) | 24 462 | 58.80% | 24 458 | 19.29% | 19 498 (46.87%) |
| **Block RAM tile** | **47.5** | **95.00%** | **47.5** | **35.19%** | 47.5 (95.00%) |
| DSPs              | 6 | 6.67% | 6 | 2.50% | 6 (6.67%) |
| MMCME2_ADV        | 4 | of 5 | 4 | of 6 | 4 |
| PLLE2_ADV         | 2 | of 5 | 2 | of 6 | 2 |
| BUFGCTRL          | 15 | of 32 | 15 | of 32 | 15 |

### 2.3 Does the receiver fit, and is it the blocker? — No, and no.

* **Block RAM is unchanged: 47.5 tiles, exactly the phase-1 figure.** The
  receiver's 40×56 sink-key store is distributed RAM (`ram_style="distributed"`
  in `hdcp_rx.v`), so it adds **zero** block RAM. The 35T stays at 95% BRAM
  because the *overlay* already fills it; the receiver did not make the BRAM
  bottleneck worse.
* The receiver adds ~1.8 k LUTs (15.3 k → 17.1 k) and ~5.0 k FFs (19.5 k →
  24.5 k, mostly the CDC BusSynchronizer chains and the pix_o cipher pipeline),
  and **no** MMCM/PLL. On the 100T this is trivial (27% LUT / 19% FF / 35%
  BRAM); on the 35T it fits but the part is nearly full (82% LUT / 59% FF / 95%
  BRAM).
* **The receiver is not the incremental timing blocker.** Post-synthesis
  failing-endpoint count is *identical* to the receiver-less baseline (515), no
  receiver instance (`hdcp_rx`/`hdcp_mod_rx`/`cipher_rx`/key store) appears in
  any violated path, and post-synth WNS is actually a touch *better* than
  phase-1 (-7.57 vs -7.68). The ~0.6 ns worsening at route (-7.505 → -8.100 on
  35T) is congestion/placement on the **same pre-existing critical path**, not a
  receiver path becoming critical.

## 3. Conclusion and the decision to flag

The 2019 overlay design does not meet timing under Vivado 2025.2 on **either**
part — ~-8 ns, independent of the receiver and independent of FPGA size. This is
the pre-existing rebuild-2019 timing-closure problem (rebuild-2019.md §6.4, WNS
-7.505 on 35T with no receiver), and a bigger part does **not** fix it: the
critical path is a clocking/constraint issue on the sys↔hdmi pixel-clock
crossings, not a capacity problem. The H5 plan hoped the 100T "should have far
more room" and would close — it has the room (27% LUT), but it does **not** close
timing, because the failure was never about room.

Consequently the **DoD 1+2 hardware attempt is gated on the pre-existing
35T/100T timing-closure problem, which is a phase 2/3 item**, not something this
task resolves. Per spec §10.3 no negative-slack bitstream may be loaded, so:

* Neither part currently yields a loadable (timing-closing) bitstream.
* **Unit selection for the hardware run is therefore an open decision for the
  user / RPi side, not resolved here.** The DoD 1+2 attempt should target
  whichever unit ends up with *both* a timing-closing bitstream *and* the HDMI
  test rig — but that requires the timing work first. The golden-unit rig is a
  35T; the 35T is both the harder part to close (95% BRAM, 82% LUT) and the one
  under the never-load-negative-slack rule, so closing timing on the 100T (more
  room to try placement/constraint fixes) is the more promising path if a 100T
  rig is available.

## 4. Reproducing

Container and mounts as in rebuild-2019.md §3, plus the receiver `.v` sources
mounted read-only, run detached so the long route survives host memory pressure:

```bash
# from the repo root; TMP=/home/tim/github/AlphamaxMedia/tmp holds the phase-1
# compiler_rt / patched common.mak / writable Xilinx HOME
docker run -d --name hdcprx_build --init --shm-size=2g --user "$(id -u):$(id -g)" \
  -e HOME=/xhome -v "$TMP/xhome:/xhome" \
  -v "$PWD/legacy:/work" -w /work \
  -v "$PWD/netv2:/netv2:ro" \
  -v "$TMP/crt/compiler_rt:/work/deps/litex/litex/soc/software/compiler_rt:ro" \
  -v "$TMP/patched/common.mak:/work/deps/litex/litex/soc/software/common.mak:ro" \
  -v /opt/Xilinx:/xilinx:ro -v /run/udev:/run/udev:ro \
  netv2-rebuild2019 bash -c \
    'python3 netv2mvp_hdcprx.py -p 100 --lx-ignore-deps;
     python3 netv2mvp_hdcprx.py -p 35  --lx-ignore-deps'
```

`--verilog-only` on `netv2mvp_hdcprx.py` does a fast elaborate-and-emit-`top.v`
smoke test (no BIOS, no Vivado). Build outputs land in
`legacy/build/hdcprx-{35,100}/` (git-ignored). Each full build takes ~40–60 min
under memory contention; route peaks near 16 GB, so run the parts sequentially.

One environment note: the phase-1 memory footprint plus Vivado's ~16 GB route
peak leaves little headroom on the 31 GB host — run the Vivado work in a
**detached** container (owned by dockerd) rather than a foreground/background
task the harness may reap under memory pressure.
