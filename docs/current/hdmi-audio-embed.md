# Phase 7c: HDMI audio embed

Branch `phase7c-audio-embed`. This is the **source side** of the goal's "HDMI
audio embedding/de-embedding" pair: the NeTV2 acts as an HDMI *source*,
generates a self-timed raw HDMI output stream, and **embeds** audio into its
data-island periods (Audio Sample Packets, Audio Clock Regeneration N/CTS, and
an Audio InfoFrame), TERC4-encoded into the output blanking. Phase 7b did the
inverse (de-embed / extract); this closes the loop.

Two pieces were needed, neither of which the modern LiteX video cores provide:

1. A **raw-mode HDMI output pipeline**. LiteX's `VideoS7HDMIPHY` is DVI-only:
   its TMDS encoder emits pixels + the four control tokens and *cannot* emit
   data-island (TERC4) characters, so audio can never be inserted through it.
   bunnie's litevideo has a raw-mode output PHY (the OSERDESE2 10:1 serialiser
   takes an arbitrary 10-bit token), ported here.
2. An **audio-island encoder** that generates the packets as TERC4 characters
   and inserts them into the blanking with the correct preamble / guard-band
   framing — the hardest part, the mirror image of phase 7b's parser.

Because the NeTV2 is the source, there is no recovered link clock to genlock
to, so the pixel/serial clocks are **self-timed** from the 50 MHz oscillator
(the HDCP receiver spec's "output clock mux" case).

No hardware was touched. Verification is a migen embed→de-embed round-trip
simulation (bit-exact) plus a Vivado build for timing/fit.

## What was built

New package `netv2/gateware/video/output/` (ported from litevideo commit
3bc5a24, modern migen):

| File | Contents |
|---|---|
| `encoder.py` | `Encoder` — the TMDS 8b/10b video encoder (control-token only), ported verbatim. Used for the active-video pixels; islands bypass it via raw injection. |
| `s7.py` | `S7HDMIOutEncoderSerializer` (OSERDESE2 master/slave 10:1 DDR), `S7HDMIOutPHY` (raw 3-lane), `S7HDMIOutClocking` (self-timed fractional MMCM 50 MHz → pix/pix5x, drives the clock lane). |
| `timing.py` | `VideoTimingGenerator` — free-running CEA timing (720p / 1080p) + a colour-bar test pattern + a per-line `island_slot` strobe marking where in blanking an island may be inserted. |

New file `netv2/gateware/video/audio/embed.py`:

| Class | Contents |
|---|---|
| `AudioIslandEncoder` | The island serialiser. Given one packet (header `{type,hb1,hb2}` + four 56-bit subpacket *data* words), it computes the header + per-subpacket BCH ECC **serially** with the same reflected LFSR (`parser._bch_step`) phase 7b uses to *check*, walks the 32 island chars emitting the header bit on ch0 bit 2 and the subpacket bit-pairs on ch1/ch2, TERC4-encodes every nibble, and wraps it in the CTL0101 preamble + leading/trailing data guard bands. ch0 nibble bits 1:0 carry the live HSYNC/VSYNC. |
| `AudioEmbedder` | CSR-driven front end: a firmware-written PCM async FIFO feeds ASPs; N/CTS + InfoFrame fields are CSRs; a scheduler emits, on each `island_slot`, a rotating ACR → InfoFrame → ASP. Wraps the encoder in the `pix` domain; CSR/FIFO-write side is `sys`. |

New target `netv2/targets/hdmi_audio_out.py`: `NeTV2HDMIAudioOutSoC` — a lean SoC
(VexRiscv + UART + integrated SRAM, **no DDR3**) + `HDMIAudioOut` (the self-timed
raw output + colour-bar pattern + audio embed) on `hdmi_out` 0, a7-100.

Simulation `tests/sim/video/`:
- `test_hdmi_audio_embed.py` — the round-trip testbench (below).
- `run_hdmi_audio_embed_sim.py` — one-command runner with a readable summary.

It reuses the phase-7b `hdmi_audio_model.py` as the golden byte-layout reference
and imports the *real* phase-7a `DecodeTERC4` + phase-7b `HDMIAudioExtract` for
the de-embed half. Nothing in `legacy/`, `netv2/gateware/hdcp/`, or the phase-7a
/7b files was edited — those modules are imported, not modified.

## The raw output PHY + self-timed clock

The DVI-only limitation is why raw mode is mandatory: `S7HDMIOutPHY` takes three
already-formed 10-bit tokens `c0/c1/c2` and serialises them out the three
differential pairs with OSERDESE2 master/slave pairs (DATA_WIDTH=10, DDR, CLK =
`pix5x`, CLKDIV = `pix`). The top-level `HDMIAudioOut` muxes the token source per
pixel: the TMDS `Encoder` output during active video / blanking, overridden by
the island encoder's TERC4 tokens while it streams.

**Self-timed clock.** No integer PLL produces 74.25/148.5 MHz (and their ×5
serial clocks) from the 50 MHz oscillator. The closest in-spec **fractional**
MMCM multiplier is `M = 14.875` (VCO = 50 × 14.875 = **743.75 MHz**, inside the
MMCM 600–1440 MHz range), giving +0.17 % over nominal — well within HDMI's
±0.5 %. The two pixel modes are just different output dividers of that one VCO:

| Mode | `CLKOUT0_DIVIDE_F` (pix) | pix5x divide | pix | pix5x (output serdes) |
|---|---|---|---|---|
| 720p  | 10.0 | 2 | 74.375 MHz  | 371.875 MHz |
| 1080p | 5.0  | 1 | 148.75 MHz  | 743.75 MHz  |

The HDMI clock lane is a fixed `0b0000011111` pattern serialised at `pix5x`
(toggles at the pixel rate), exactly as litevideo does.

## The island encoder (the hard part)

A data island is: **CTL0101 preamble (6) → leading data guard band (2) → a
"dummy" TERC4 char (1) → 32 payload chars → trailing guard band (2) → trailing
control (6)**. This framing is bit-for-bit what phase 7b's `DecodeTERC4` FSM
expects (INIT → PREAM_T4 → GOING_T4 → TERC4 → LEAVE_T4) and what the golden
`hdmi_audio_model.island_stream` produces.

The payload streaming is the exact inverse of the phase-7b parser:

- **Header** — 24 data bits (type, HB1, HB2, LSB-first) then 8 ECC bits, one bit
  per char on **ch0 bit 2**. The ECC is accumulated with `_bch_step` over chars
  0–23 and shifted out over chars 24–31.
- **Subpackets 0–3** — 56 data bits (2 per char: ch1.d[k] = bit 2c, ch2.d[k] =
  bit 2c+1) then 8 ECC bits over chars 28–31. Each subpacket has its own
  `_bch_step` LFSR fed two bits/char.
- **ch0 nibble bits 1:0** carry the live HSYNC/VSYNC (0 during the round-trip
  blanking, as the model uses).

Every nibble is TERC4-encoded (`terc4_tokens[nibble]`), the guard bands use
`data_gb_tokens[0]`, and the preamble uses `control_tokens[1]` — the same tables
the phase-7a decoder decodes, so the loop is closed with one source of truth for
the token values.

**BCH ECC**: generator `x^8 + x^7 + x^6 + x^4 + 1`, reflected LSB-first LFSR
(mask `reflect(0xD1) = 0x8B`). The embedder computes it with the *same*
`parser._bch_step` the extractor uses to check it, so a clean island always
verifies `ecc_ok = 1` in the extractor (the round-trip asserts zero ECC errors).

**Packet builders** (`embed.build_asp_subpacket`, `build_acr_subpacket`, and the
InfoFrame packing in `AudioEmbedder`) place the fields at exactly the bit
positions `extract.py` decodes them from — verified by the round trip.

**N/CTS.** `fs = f_pixel · N / (128 · CTS)`. For 48 kHz at the phase-7b
reference pixel clock (74.25 MHz), N = 6144, CTS = 74250. These are CSR defaults;
the round-trip decodes them back to fs ≈ 48 kHz.

## CSR map (`hdmi_out_embedder_*`)

| CSR | Access | Contents |
|---|---|---|
| `control` | rw | `enable`, `send_infoframe`, `send_acr` |
| `n` | rw | ACR N (20-bit, default 6144) |
| `cts` | rw | ACR CTS (20-bit, default 74250) |
| `infoframe` | rw | `cc`, `ct`, `sf`, `ss`, `ca` (Audio InfoFrame fields) |
| `pcm` | rw | `sample[23:0]`, `channel`, `we` — push one 24-bit PCM sample (write L, R, L, R …) |
| `status` | ro | `busy`, `fifo_readable`, `have_pair` |
| `island_count` | ro | data islands emitted |

## Simulation results (the real verification)

`tests/sim/video/test_hdmi_audio_embed.py`, run under migen (no FPGA, no
toolchain). Two things are proven:

1. **Framing / byte-layout fidelity.** The island encoder is driven with a
   packet and the `(c0,c1,c2)` token stream it emits is asserted **byte-for-byte
   equal** to `hdmi_audio_model.island_stream([packet])` — for ASP, ACR and
   Audio InfoFrame. This proves the embedder's BCH ECC, TERC4 encoding and
   preamble/guard-band framing are all correct (spec-valid island framing).

2. **embed → de-embed round trip.** The gateware-produced islands are fed
   straight into the *real* phase-7a `DecodeTERC4` + phase-7b `HDMIAudioExtract`
   de-embed path, asserting:
   - recovered **PCM is bit-exact** — a stereo 24-bit sequence (1 kHz sine on
     the left, a distinct ramp on the right) comes back identical, per channel;
   - the embedder's **BCH ECCs verify OK** in the extractor (0 ECC errors);
   - **N/CTS** latch and decode to fs ≈ 48 kHz;
   - the **Audio InfoFrame** round-trips (CC/SF/SS decode, valid set).

All 5 embed checks pass (plus the 4 phase-7b extract checks still pass):

```
[ok] ASP island: TERC4 token stream byte-exact vs golden model
[ok] ACR island: token stream byte-exact vs golden model
[ok] Audio InfoFrame island: token stream byte-exact vs golden model
[ok] embed -> de-embed: recovered PCM bit-exact (stereo 24-bit), BCH verified OK
[ok] embed -> de-embed: N/CTS latch (derived fs ~ 48 kHz) + Audio InfoFrame round-trip
```

This closes the goal's "HDMI audio embedding/de-embedding" pair entirely within
the modern gateware.

## Build result (Vivado 2025.2, a7-100 `xc7a100t-fgg484-2`, `--toolchain vivado`)

Default build is **720p** (`--resolution 720p`), lean SoC (no DDR), sys = 50 MHz.

**Timing: post-route PASS** — "All user specified timing constraints are met."
Per-clock WNS (post-route, slow corner):

| Clock | Freq | WNS (setup) | WHS (hold) | Note |
|---|---|---|---|---|
| `clk50` (oscillator) | 50 MHz | +18.820 ns | +0.138 ns | input |
| `crg_clkout` (sys/CPU) | 50 MHz | +1.369 ns | +0.075 ns | VexRiscv + CSRs |
| `s7hdmioutclocking_mmcm_clk0` (pix) | 74.375 MHz | +7.472 ns | +0.105 ns | pixel logic, timing, encoders, island |
| `s7hdmioutclocking_mmcm_clk1` (pix5x) | **371.875 MHz** | **+0.150 ns** | +0.157 ns | **OSERDESE2 output serdes** |

The Inter-Clock table is **empty** — the sys↔pix / sys↔pix5x false paths (and
the AudioEmbedder's async FIFO + BusSynchronisers) mean no cross-domain paths are
timed, exactly as intended; pix↔pix5x stay a synchronous OSERDES CLK/CLKDIV pair.
The 720p output serdes (371.875 MHz) closes with +0.150 ns to spare.

**Utilisation (a7-100 `xc7a100t`)** — the whole SoC (CPU + UART + SRAM + output
pipeline + audio embed) is tiny:

| Resource | Used | Avail | % |
|---|---|---|---|
| Slice LUTs | 2752 | 63400 | 4.34 % |
| Slice Registers | 2662 | 126800 | 2.10 % |
| Block RAM Tile | 19.5 | 135 | 14.4 % |
| DSPs | 4 | 240 | 1.7 % |
| OSERDESE2 | 8 | 285 | (4 lanes × master/slave) |
| MMCME2_ADV | 1 | 6 | (output clock) |
| PLLE2_ADV | 1 | 6 | (sys clock) |
| BUFG | 4 | 32 | |
| Bonded IOB | 11 | 285 | |

Bitstream: `build/netv2-hdmi-audio-out/gateware/kosagi_netv2.bit` (~3.8 MB).

### Timing / clocking note — 720p vs 1080p output serdes

Both resolutions were built. **720p closes; 1080p does not.**

`--resolution 1080p` (separate build, `build/netv2-hdmi-audio-out-1080p/`)
post-route: **timing NOT met**, and the *only* failing clock is the output
serdes `pix5x` at 743.75 MHz:

| Clock (1080p) | Freq | WNS setup | WPWS (pulse width) | Endpoints failing |
|---|---|---|---|---|
| `crg_clkout` (sys) | 50 MHz | +1.352 ns | ok | 0 |
| `mmcm_clk0` (pix) | 148.75 MHz | +1.941 ns | ok | 0 |
| `mmcm_clk1` (pix5x) | **743.75 MHz** | **-0.713 ns** | **-0.248 ns** | 8 setup + 9 pulse-width |

So the pixel-domain logic (island encoder, timing, TMDS encoders) closes fine at
148.75 MHz — the audio-embed core itself is not the bottleneck — but the
**OSERDESE2 serialiser cannot run at 743.75 MHz** on this -2 part: it fails
setup by 0.713 ns and violates minimum clock pulse width. This is the exact
mirror of the phase-7a *input*-side finding (742.5 MHz needs a pulse-width
exception on the -2 ISERDESE2); at the output it is the OSERDESE2's turn.

**Conclusion: use 720p** (371.875 MHz output serdes, +0.150 ns slack), the
default. 1080p output would need either a faster speed grade or the same
datasheet pulse-width exception the 2019 design applied on the input side (and
even then the -0.713 ns setup miss is a real path failure, not just a
pulse-width waiver — so 720p is the honest answer here). Vivado still emits a
1080p `.bit` despite the failure (as in phase 7a), but it must not be used.

## What the on-hardware audio test will require

Not done here (no hardware per the task). To validate on real silicon:

- Program the a7-100 with the 720p bitstream (JTAG on a **non-golden** unit
  first; the golden `rpi3-netv2` stays untouched).
- Connect `hdmi_out` 0 to an HDMI **sink with an audio analyser**, or capture
  with the rpi3 golden rig, and confirm the sink locks video (720p bars) and
  reports 2-ch 48 kHz LPCM with the embedded tone.
- Firmware: set `n`/`cts`/`infoframe`, enable the embedder, and stream PCM into
  the `pcm` FIFO (or add an on-chip tone generator).
- Requires explicit go-ahead before any hardware step.

### Known remaining / caveats

- **Video-island interaction on hardware.** The round-trip validates the island
  path in isolation (the strongest audio check). In the full output pipeline the
  island is muxed over the TMDS stream during vertical-blank lines; full HDMI
  video-guard-band / preamble compliance for a *picky sink* is not part of the
  sim and should be checked on hardware (the audio recovery does not depend on
  it).
- **One packet per island.** The encoder emits a single packet per island
  (matching the phase-7b tests); multi-packet islands are a straightforward
  extension of the payload loop if a sink needs denser audio.
- The fractional-MMCM +0.17 % pixel-rate offset is in HDMI tolerance but is a
  real frequency error a downstream ACR consumer sees; N/CTS are set for the
  nominal rate.
