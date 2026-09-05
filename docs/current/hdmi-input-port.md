# Phase 7a: litevideo HDMI-input port (foundation for HDMI audio)

Branch `phase2-modern-soc`. This is the gateware foundation the HDMI-audio
extract core (next task) is built on. It ports bunnie's litevideo **input**
pipeline -- the raw-mode HDMI receiver with a TERC4 data-island decoder -- onto
the modern LiteX 2026.04 / migen 0.9.2 stack, wires **one** input (input0, the
2019 "source" input) into a SoC that extends the phase-2 `NeTV2BaseSoC`, and
proves it elaborates and closes (or not) timing on the a7-100.

No audio yet. No overlay, no output path, no framebuffer DMA. Just: recover the
HDMI-input clock, lock the 3 TMDS channels, decode, and expose the TERC4
data-island evidence over CSRs.

## Why a port and not the modern LiteX video cores

The goal's "HDMI audio (de-embed/embed)" needs the HDMI **data-island**
(TERC4) packets that carry audio samples. The modern LiteX `VideoS7HDMIPHY`
cores are DVI-style -- pixels only -- and drop data islands entirely
(established in the HDCP review). bunnie's litevideo fork keeps a raw HDMI-input
path with a `DecodeTERC4` state machine that recognises the data-island
preamble/guardbands and captures the island's BCH-protected bytes. So HDMI
audio has to be built on a port of that pipeline; this task is that port plus a
lock-and-decode SoC to prove the hard part (the 148.5 MHz / 742.5 MHz recovered
serdes clocking) builds.

## Source

bunnie's litevideo at `/home/tim/github/AlphamaxMedia/litevideo`, master
`3bc5a24` ("add delay alignment feature") -- the commit the 2019 design pinned.
The port copies the whole `input/` package and the three Xilinx phase-alignment
Verilog blackboxes from `legacy/overlay/`.

## What was ported, and where

Port lives under `netv2/gateware/video/input/` (module boundaries and signal
names kept identical to `docs/original` so it stays comparable):

| File | Contents | Port status |
|---|---|---|
| `common.py` | control tokens, `channel_layout`, `list_signals` | clean (added local `list_signals`, previously imported from `litevideo.output.common`) |
| `clocking.py` | `S7Clocking` (input MMCM: pix / pix1p25x / pix1p25x_r / pix5x / pix_raw), `S6Clocking` | clean -- no API changes needed |
| `datacapture.py` | `S7DataCapture` (IDELAYE2 + ISERDESE2 + IBUFDS_DIFF_OUT + `delay_controller`/`phsaligner` blackboxes), `S7PhaseDetector`, `S6DataCapture` | clean |
| `charsync.py` | `CharSync` (TMDS control-token alignment) | clean |
| `chansync.py` | `ChanSync` + `_SyncBuffer` (3-channel de-skew via `Memory`/`_inc`) | clean |
| `wer.py` | `WER` (word-error-rate) | clean |
| `decoding.py` | `Decoding`, `DecodeTERC4Channel`, `DecodeTERC4` (the TERC4 island FSM + BCH capture + `t4d` counters + events) | clean |
| `analysis.py` | `SyncPolarity`, `ResolutionDetection`, `FrameExtraction` | fixed: made the ycbcr422 csc imports lazy (see below) |
| `edid.py` | `EDID` I2C slave + default EDID | clean |
| `dma.py` | `DMA`, `_SlotArray`, `_Slot` | fixed: `alignment_bits=` / `.dw` / `.aw` removed (see below). **Not on the input0 path** -- ported for the audio-DMA task, needs revalidation when actually wired. |
| `__init__.py` | `HDMIIn`, `TimingDelayChannel` | fixed: import path for `list_signals` |

Blackboxes copied verbatim to `netv2/gateware/video/blackboxes/` (originals in
`legacy/overlay/` untouched): `chnlbond.v`, `phsaligner.v`,
`delay_controller.v`, and **`DRAM16XN.v`** -- `chnlbond` instantiates `DRAM16XN`
(a `RAM16X1D` distributed-RAM delay FIFO), so it must be compiled in too; the
2019 build added all four.

## API fixes made (migen 0.9.2 / LiteX 2026.04 vs the 2019 fork)

The migration surface predicted by the HDCP spec turned out to be small for the
input path -- most of the removed APIs (`write_from_dev`, `atomic_write`) are
actually still present in 2026.04. The concrete fixes:

1. **`list_signals`** was imported from `litevideo.output.common`; the output
   package is not ported. Added a two-line local `list_signals(layout)` to
   `input/common.py` and repointed the import (`__init__.py`).

2. **Intra-package imports** `from litevideo.input.X` -> `from
   netv2.gateware.video.input.X` across every file.

3. **`analysis.py` csc imports** (`litevideo.csc.rgb2ycbcr`,
   `.ycbcr444to422`) were top-level but are only used by `FrameExtraction` in
   `mode="ycbcr422"`. input0 has `dram_port=None` so no `FrameExtraction` is
   built; moved the imports inside the ycbcr422 branch so `analysis.py` loads
   without the csc package.

4. **`dma.py` -- removed CSR features** (not on the input0 path, fixed for the
   audio-DMA task):
   - `CSRStorage(..., alignment_bits=n)` was removed in modern LiteX. The
     firmware still programs *byte* addresses, so the CSRs stay full byte width
     and the low `alignment_bits` are dropped in fabric instead:
     `self.address.eq(self._address.storage[alignment_bits:])` and the
     `write_from_dev` `dat_w` is `address_reached << alignment_bits`.
   - `dram_port.aw` / `.dw` -> `.address_width` / `.data_width`.
   - `write_from_dev=` / `atomic_write=` are unchanged in 2026.04 (kept as-is).

No changes were needed to the S7 clocking, the datacapture serdes/IDELAY
instantiation, the `Memory`/`get_port(async_read=True)` idiom in `chansync`, the
`migen.genlib.fifo._inc` import, the `stream`/`Record` layout API, the
`EventManager`/`EventSourcePulse` events, or the `Gearbox`/`BusSynchronizer`
CDC primitives -- all present and unchanged in the pinned migen/LiteX.

## The SoC: `netv2/targets/hdmi_in.py`

`NeTV2HDMIInSoC` extends the phase-2 `NeTV2BaseSoC` (VexRiscv + UART + DDR3) and
adds one `HDMIIn` on the platform's `hdmi_in` 0 resource, configured exactly as
the 2019 source input:

```
HDMIIn(pads, dram_port=None, device="xc7", hdmi=True,
       split_mmcm=False, alt_delay=True,
       clkin_freq=148.5e6, iodelay_clk_freq=200e6)
```

- `hdmi=True` -- TERC4 preamble-based DE + the `DecodeTERC4` island decoder.
- `alt_delay=True` -- use the Verilog `phsaligner`/`chnlbond`/`delay_controller`
  aligners (as in 2019), not litevideo's own aligner.
- `split_mmcm=False` -- no derived `pix_o`/`pix5x_o` output domain (input only).
- `dram_port=None` -- no framebuffer capture; input0 exists only as decoded
  characters, timing, and TERC4 status (matches the 2019 role of input0).
- `iodelay_clk_freq=200e6` -- **reuses the base CRG's single global
  `S7IDELAYCTRL` on the 200 MHz `cd_idelay`**, so the input `IDELAYE2` taps
  reference the same 200 MHz clock. No second `IDELAYCTRL` is instantiated (a
  simplification over the 2019 design's 300 MHz `delayrefclk`).

A `FreqMeter` measures the input pixel clock; it is clocked from `cd_pix_raw`
(the raw IBUFDS output, valid even before the MMCM locks) exactly like the 2019
`hdmi_in0_freq`, so a reading is available during bring-up.

### Recovered clock tree (litevideo `S7Clocking`, input MMCME2_ADV)

| Domain | Freq | Buffer | Role |
|---|---|---|---|
| `pix_raw` | 148.5 MHz | (IBUFDS out) | frequency meter; MMCM input |
| `pix` | 148.5 MHz | BUFG | pixel clock; charsync/chansync/decode/TERC4 |
| `pix1p25x` | 185.625 MHz | BUFG | 8->10 gearbox output-side |
| `pix1p25x_r` | 185.625 MHz | BUFR /4 | serdes CLKDIV; delay/monitor logic |
| `pix5x` | 742.5 MHz | BUFIO | ISERDESE2 bit clock |

### Timing constraints

Only the recovered **input** clock (`cd_pix_raw`, the IBUFDS output feeding the
MMCM) gets an explicit `create_clock` (148.5 MHz). Vivado then auto-derives the
MMCM/BUFR output clocks (`pix`/`pix5x`/`pix1p25x`/`pix1p25x_r`) as one
synchronous generated-clock family, so the intra-family crossings -- the 8->10
gearbox `pix1p25x`->`pix` and the ISERDESE2 `CLK`/`CLKDIV` (`pix5x`/`pix1p25x_r`)
-- are analysed with their true phase relationship, not as unrelated clocks.

`sys` (100 MHz) is declared asynchronous to the `pix` family via
`add_false_path_constraints(crg.cd_sys.clk, clocking.cd_pix.clk)`. Every real
`sys`<->`pix` crossing already goes through a LiteX CDC primitive (MultiReg /
PulseSynchronizer / BusSynchronizer / AsyncResetSynchronizer), which LiteX
false-paths automatically via the `mr_ff` / `ars_ff` attributes.

## CSRs exposed

The full `hdmi_in0` register block (70 CSRs) is in
`build/netv2-hdmi-in/csr.csv`. The ones this phase and the audio phase care
about:

**Lock / clock:**
- `hdmi_in0_clocking_locked` -- input MMCM locked.
- `hdmi_in0_freq_value` -- measured input pixel clock (FreqMeter, from `pix_raw`).
- `hdmi_in0_dataN_charsync_char_synced`, `..._ctl_pos` (N=0,1,2) -- per-channel
  character sync + control position.
- `hdmi_in0_chansync_channels_synced` -- three channels de-skewed.
- `hdmi_in0_dataN_wer_value` -- per-channel word-error-rate.
- `hdmi_in0_dataN_cap_*` -- per-channel IDELAY/serdes phase-detector controls
  (`lateness`, `phase`, `eye`, `monitor`, `cntvalueout_m/s`, `dly_ctl`,
  `auto_ctl`, `algorithm`, `eye_bit_time`).

**Resolution:**
- `hdmi_in0_resdetection_hres`, `hdmi_in0_resdetection_vres`.

**TERC4 data island (the audio-extract evidence):**
- `hdmi_in0_decode_terc4_t4d_char` -- characters seen in the current island (wraps at 31).
- `hdmi_in0_decode_terc4_t4d_count` -- completed 32-char packets in the current island.
- `hdmi_in0_decode_terc4_t4d_bch0..4` -- captured BCH bytes (bch0..3 are 64-bit,
  bch4 is 32-bit): channel-1/channel-2 nibble streams (`t4d_bchK` <- `{ch2.dK, ch1.dK}`)
  plus `bch4` <- `ch0.d[2]`. This is the raw data-island byte capture the audio
  extract decodes into audio-sample subpackets.
- `hdmi_in0_decode_terc4_ev_status/pending/enable` -- `t4packet` (a 32-char
  packet completed) and `t4island` (an island ended) pulse events.
- `hdmi_in0_decode_terc4_dvimode` -- select DVI-style DE instead of the TERC4 DE.

**EDID:** `hdmi_in0_edid_hpd_en`, `..._hpd_notif` (I2C EDID slave with the
Alphamax default EDID; the I2C bytes are served from a `Memory`).

The `DecodeTERC4` `EventManager` is exposed as CSRs but **not** wired to a CPU
interrupt line in this phase (firmware can poll `ev_pending`); the audio phase
can promote it to an interrupt if needed.

## Verification

**TERC4 / charsync / decoding simulation** -- `tests/sim/video/test_terc4_decoder.py`
(migen `run_simulation`, `pix`->`sys` renamed, no toolchain). Four passing tests:
- `CharSync` locks on an aligned control-token stream and passes the token through.
- `Decoding` maps each control token to `de=0` + its 2-bit `c`, and a data word to `de=1`.
- `DecodeTERC4` driven through a full data island (control preamble -> data
  guardband -> 32+ TERC4 chars -> closing guardband) advances `t4d_char`,
  completes a packet (`t4d_count>=1`), and latches the `t4island` event.
- `DecodeTERC4` driven through a video period asserts `de_hdmi`/`de_o`.

Run: `uv run pytest tests/sim/video/test_terc4_decoder.py` (all 4 pass).

**Elaboration** -- `uv run python -m netv2.targets.hdmi_in --variant a7-100`
(no `--build`) finalizes the SoC and emits gateware Verilog + software with no
error. The generated `build/netv2-hdmi-in/gateware/kosagi_netv2.v` contains the
`chnlbond`/`phsaligner`/`delay_controller` instances and all five recovered
clock domains; the XDC has the `create_clock` on `pix_raw` (6.734 ns) and the
`sys`<->`pix` async clock group.

## Build result (Vivado 2025.2, a7-100 `xc7a100t-fgg484-2`, `--toolchain vivado`)

The SoC synthesises, places, routes, and **writes a bitstream**
(`build/netv2-hdmi-in/gateware/kosagi_netv2.bit`, ~3.8 MB).

### Timing (post-route, slow corner)

| Check | Slack | Failing endpoints | Verdict |
|---|---|---|---|
| **Setup (WNS)** | **+0.718 ns** | 0 / 21592 | **MET** |
| **Hold (WHS)** | **+0.063 ns** | 0 / 21592 | **MET** |
| Pulse width (WPWS) | **-0.124 ns** | 14 / 9334 | not met |

**The 148.5 MHz pixel / 742.5 MHz serdes recovered clocking closes for setup
and hold.** Per-clock post-route intra-domain setup slack is all positive:
`pix` +0.718, `pix1p25x` +1.370, `pix1p25x_r` +0.891 ns. All inter-clock
crossings (gearbox `pix1p25x`<->`pix`, serdes `pix1p25x_r`<->`pix`) are positive
after the multicycle exceptions.

### The one remaining exception: ISERDESE2 min period at 1080p60

The only violation is a **minimum-clock-period (pulse-width) check on the six
ISERDESE2 cells** (CLK/CLKB), reported against `main_mmcm_clk2` = the 742.5 MHz
`pix5x`:

```
Min Period  ISERDESE2/CLK   Required 1.471 ns   Actual 1.347 ns   Slack -0.124 ns
```

This is a **datasheet limit of the -2 speed grade**, not a
placement/constraint problem: the ISERDESE2 on `xc7a100t...-2` wants a clock
period >= 1.471 ns (~680 MHz), but 1080p60 HDMI drives the 5x serdes clock at
742.5 MHz (1.347 ns). It cannot be closed by constraints or a faster route --
only by a faster speed grade, or by running the input at 720p (74.25 MHz pixel,
371.25 MHz serdes, period 2.69 ns, which clears the 1.471 ns limit with wide
margin). Notably the 2019 design ran the *same* 742.5 MHz serdes on the same -2
part and shipped 720p as its preferred mode (its EDID advertises the lower-rate
mode "for lower power/bw"); this pulse-width exception was present there too and
did not prevent a working bitstream (Vivado still produces the `.bit`).

**Bottom line: the HDMI-input clocking closes setup + hold at 1080p60; the sole
timing exception is the ISERDESE2 rated-frequency limit at the 1080p60 serdes
rate, which is inherent to the -2 part and is a non-issue at 720p.**

### Timing constraints applied

- `create_clock` (148.5 MHz) on the input **port** `hdmi_in0_clk_p`; Vivado
  auto-derives the MMCM/BUFR generated clocks (`pix`/`pix1p25x`/`pix1p25x_r`/
  `pix5x`) as one synchronous family.
- Emitted as **pre-placement** Tcl (post-synth, when the generated clocks/nets
  exist -- LiteX reads the .xdc before synth, so net/generated-clock references
  there are dropped):
  - `set_clock_groups -asynchronous` between all sys-tree generated clocks and
    all HDMI-port generated clocks (covers every sys<->pix* CDC).
  - `set_multicycle_path 2 -setup / 1 -hold` on the gearbox/serdes handoffs
    both directions: `pix1p25x`<->`pix` and `pix1p25x_r`<->`pix` (relaxes the
    related-clock crossings whose tightest edge alignment is only 1.347 ns; the
    12 endpoints in `pix`->`pix1p25x` are the gearbox reset-removal paths).

### Utilisation (a7-100 -- very comfortable, no risk of filling the part)

| Resource | Used | Avail | % |
|---|---|---|---|
| Slice LUTs | 7601 | 63400 | 12.0 |
| Slice Registers | 8465 | 126800 | 6.7 |
| Block RAM tile | 31.5 | 135 | 23.3 |
| DSP | 4 | 240 | 1.7 |
| MMCME2_ADV | 1 | 6 | 16.7 |
| PLLE2_ADV | 1 | 6 | 16.7 |
| BUFGCTRL | 9 | 32 | 28.1 |
| BUFIO / BUFR | 1 / 1 | 24 / 24 | 4.2 |
| Bonded IOB | 89 | 285 | 31.2 |

Unlike the 2019 overlay design on the 35T (BRAM ~95%, timing missed by ~7.5 ns),
this input-only SoC on the 100T uses ~12% logic and ~23% BRAM, leaving ample
room for the audio-extract core, DMA, and (later) the output/overlay path.

### Iteration notes (for anyone re-running the build)

Three constraint pitfalls were hit and fixed; they are worth knowing for the
audio phase:
1. `create_clock` on an internal net (`get_nets pix_raw_clk`) is dropped --
   synthesis renames it. Anchor on the input **port** instead.
2. Net/generated-clock constraints in the `.xdc` are evaluated before synth and
   dropped ("no valid object"). They must go in `toolchain.pre_placement_commands`.
3. Post-synth the `pix`/`pix1p25x` clock **nets** are absorbed into the
   auto-generated clock names `main_mmcm_clk0`/`clk1`; reference those clock
   names (glob `*mmcm_clk0`), not the nets. The BUFR net `pix1p25x_r_clk`
   survives.

## What the next task (audio extract) can rely on

- A ported, elaborating, module-for-module-comparable litevideo input pipeline
  under `netv2/gateware/video/input/`, with the TERC4 island decoder and its
  BCH/counter/event CSRs already surfaced.
- `NeTV2HDMIInSoC` as the integration point: one `HDMIIn` on `hdmi_in` 0,
  reusing the base CRG's 200 MHz IDELAYCTRL, with the recovered-clock timing
  constraints in place.
- The data-island bytes arrive at `hdmi_in0_decode_terc4_t4d_bch0..4`, gated by
  the `t4packet`/`t4island` events -- the audio extract sits on exactly these
  signals (the `DecodeTERC4` internal `decval.d` nibble streams per channel) to
  reassemble audio-sample subpackets.
- `dma.py` is ported (byte-address CSR + `.address_width`/`.data_width`) for
  when audio needs to land samples in DDR, but is unexercised here -- revalidate
  the word/byte address scaling when it is first wired to a real `dram_port`.
