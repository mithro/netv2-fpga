# Phase 7b: HDMI audio de-embed / extract

Branch `phase2-modern-soc`. This builds the **audio de-embed** path on top of the
phase-7a HDMI input (`docs/current/hdmi-input-port.md`): it decodes the HDMI
data-island (TERC4) audio packets the input's `DecodeTERC4` already frames, and
turns them into PCM samples + clock/format metadata the CPU can read. This is
the "de-embedding audio from the video stream" the project goal names.

Scope is **de-embed only**. The embed side (phase 7c) and the on-hardware audio
functional test are separate (see the last section). No hardware was touched;
verification is migen simulation plus a Vivado build for timing/fit.

## What was built

New package `netv2/gateware/video/audio/`:

| File | Contents |
|---|---|
| `parser.py` | `AudioPacketParser` — taps `DecodeTERC4`'s per-channel nibble streams, reassembles each 32-char data-island packet, checks the header + 4 subpacket BCH ECCs with a serial reflected LFSR, and emits a decoded-packet stream `{type, hb1, hb2, sub0..3, ecc_ok}`. |
| `extract.py` | `HDMIAudioExtract` — consumes that stream; ASP→PCM FIFO, ACR→N/CTS, InfoFrame→CC/CT/SF/SS/CA; CDCs every CSR latch pix→sys with `BusSynchronizer` and crosses the sample FIFO with an `AsyncFIFO`. |
| `__init__.py` | re-exports both. |

New target `netv2/targets/hdmi_audio_in.py`: `NeTV2HDMIAudioInSoC` = the
phase-7a `NeTV2HDMIInSoC` + the extract core wired to
`hdmi_in0.decode_terc4`, a7-100.

Simulation `tests/sim/video/`:
- `hdmi_audio_model.py` — pure-Python packer (ASP/ACR/InfoFrame byte layouts +
  BCH ECC) that serialises packets into the per-channel TERC4 token stream.
- `test_hdmi_audio_extract.py` — migen testbench (feeds a crafted island stream
  through the *real* `DecodeTERC4` into the extract core).
- `run_hdmi_audio_sim.py` — one-command runner with a readable summary.

Nothing in `legacy/`, `netv2/gateware/hdcp/`, or the phase-7a input pipeline was
edited; the extract core is bolted on by import + signal tap only.

## Packet formats decoded (public HDMI 1.4)

Every data-island packet is a 1-byte type + 3-byte header (24 bits, BCH ECC =
byte 4) followed by 4 subpackets of 7 data bytes + 1 BCH ECC byte each. In the
TERC4 island the header travels on channel-0 bit 2 (one bit per char, 32 bits =
24 header + 8 ECC) and the 4 subpackets travel on channels 1 and 2 (for char c,
bit 2c = ch1.d[k], bit 2c+1 = ch2.d[k]; 64 bits = 56 data + 8 ECC each). Bytes
are LSB-first.

**BCH ECC**: generator `x^8 + x^7 + x^6 + x^4 + 1` (the polynomial HDCP/HDMI
data islands use), processed LSB-first as a reflected right-shift LFSR (XOR mask
= reflect(0xD1) = 0x8B). The gateware LFSR (`parser._bch_step`) and the Python
model (`hdmi_audio_model.hdmi_bch_ecc`) are bit-for-bit identical. There was no
existing BCH checker in the tree to reuse, so it is implemented here.

**Audio Sample Packet (0x02)** — `HB1[3:0]`=sample_present, `HB1[4]`=layout,
`HB2[3:0]`=sample_flat, `HB2[7:4]`=B (block-start). Each present subpacket
carries two IEC-60958 subframes = two audio samples: subframe A = bits[0:24]
(24-bit PCM), V=bit24 U=25 C=26 P=27; subframe B = bits[28:52], V=bit52 … The
channel is `2*k + subframe` for subpacket `k` (layout-0 stereo → subpacket 0 =
L,R).

**Audio Clock Regeneration (0x01)** — SB1[3:0]/SB2/SB3 = CTS[19:0],
SB4[3:0]/SB5/SB6 = N[19:0]. N and CTS are latched (they set the audio rate
relative to the TMDS clock).

**Audio InfoFrame (0x84)** — PB0=checksum, PB1[2:0]=CC, PB1[7:4]=CT,
PB2[1:0]=SS, PB2[4:2]=SF, PB4=CA. These are latched. The InfoFrame is decoded
solidly from subpacket 0 (all of CC/CT/SF/SS/CA/checksum fit there); the checksum
is surfaced but not verified in fabric (firmware can check it).

## Core structure

```
DecodeTERC4 (pix)                  HDMIAudioExtract
  encrypting_data ─┐
  data0.decval.d[2]─┤ header bit    ┌─ AudioPacketParser (pix) ─┐
  data1.decval.d[3:0]┤ sub ch1  ──▶ │  char counter 0..31        │
  data2.decval.d[3:0]┘ sub ch2      │  data/ecc shift regs       │
                                    │  5× serial BCH LFSR         │
                                    │  stb + {type,hb,sub,ecc_ok} │
                                    └───────────┬────────────────┘
                                                ▼ (pix)
                          ┌── ASP → subframe sequencer → AsyncFIFO ──▶ sys read
                          ├── ACR → N/CTS latch ─────────┐
                          └── InfoFrame → CC/CT/SF/SS/CA ─┤ BusSynchronizer ─▶ CSRs (sys)
                                                          counters ┘
```

Why tap the nibble streams rather than the parallel `t4d_bchN` CSRs: computing a
56-bit BCH combinationally from a latched word is a very deep XOR chain that
would not close timing; feeding a serial LFSR one/two bits per pixel as the
island streams by keeps the logic shallow, exactly as a hardware ECC checker
does. The reassembly bit-order matches `DecodeTERC4` and the Python packer.

The parser produces one decoded packet per 32-char island packet (multi-packet
islands are handled: the char counter wraps every 32 chars while
`encrypting_data` stays high). A packet with any bad ECC is dropped and counted.

## CSR map (`hdmi_audio0`)

All read-only status except `sample_pop`:

| CSR | Bits | Meaning |
|---|---|---|
| `hdmi_audio0_n` | 20 | ACR N value |
| `hdmi_audio0_cts` | 20 | ACR CTS value |
| `hdmi_audio0_audio_infoframe` | 29 | `{valid[28],checksum[27:20],ca[19:12],ss[11:10],sf[9:7],ct[6:3],cc[2:0]}` |
| `hdmi_audio0_asp_count` | 32 | Audio Sample Packets accepted (ECC ok) |
| `hdmi_audio0_sample_count` | 32 | valid PCM samples pushed to the FIFO |
| `hdmi_audio0_acr_count` | 16 | ACR packets accepted |
| `hdmi_audio0_infoframe_count` | 16 | Audio InfoFrames accepted |
| `hdmi_audio0_ecc_err_count` | 16 | packets dropped on BCH ECC failure |
| `hdmi_audio0_overflow_count` | 16 | samples dropped on FIFO full |
| `hdmi_audio0_sample_data` | 32 | FIFO head: `{mark[31],B[30],C[29],U[28],V[27],channel[26:24],sample[23:0]}` |
| `hdmi_audio0_sample_valid` | 1 | FIFO has data |
| `hdmi_audio0_sample_pop` | 1 | write to pop the FIFO head |

**Sample rate** is derived in firmware/host: `fs = f_pixel * N / (128 * CTS)`,
using the phase-7a FreqMeter (`hdmi_in0_freq_value`, the measured pixel clock)
plus `n`/`cts`. No divider is instantiated in fabric.

Firmware read loop: while `sample_valid`, read `sample_data`, then write
`sample_pop`. The extract core also exposes a plain `sample_re` fabric input
(OR'd with the CSR pop) for a future DMA-to-DDR ring — that ring is a phase-7c/
later refinement; a CPU-readable FIFO + counters is the phase-7b deliverable.

The sample FIFO is 256 entries deep (`AsyncFIFO`, pix→sys). Exact fill level is
not surfaced (async gray-counter FIFO); `sample_valid` + the `sample_count` /
`overflow_count` counters cover level monitoring.

## Simulation results

`uv run pytest tests/sim/video/` — 8/8 pass (4 phase-7a TERC4 + 4 new audio).
`uv run python tests/sim/video/run_hdmi_audio_sim.py` runs the four audio checks:

| Check | Result |
|---|---|
| **Recovered PCM** | 8 ASPs carrying a 24-bit stereo sequence (1 kHz sine @ 48 kHz on L, distinct ramp on R) decode **bit-exact**: `channel 0 == left[]`, `channel 1 == right[]`, `asp_count==8`, `sample_count==16`, `ecc_err==0`. |
| **N / CTS** | ACR with N=6144, CTS=74250 → `n==6144`, `cts==74250`, `acr_count==1`. |
| **Sample rate** | derived `fs = 74.25e6 * 6144 / (128 * 74250) = 48000.0 Hz` (asserted within 1 Hz). |
| **InfoFrame** | 2ch LPCM: `CC==1`, `CT==0`, `SF==3` (48 kHz), `SS==3` (24-bit), `CA==0`, `valid==1`, `infoframe_count==1`. |
| **BCH error** | one good ASP + one with a corrupted subpacket-0 ECC → `ecc_err==1`, `asp_count==1`, `sample_count==2`; the corrupted payload never reaches the FIFO. |

The test drives the *real* `DecodeTERC4` FSM (control preamble → data guardband →
32-char TERC4 payload → guardband), so the parser's island framing, char
alignment, and the 1-cycle decode-pipeline offset are all exercised end-to-end.

## Build result (Vivado 2025.2, a7-100 `xc7a100t-fgg484-2`)

The SoC synthesises (0 errors), places, routes, and **writes a bitstream**
(`build/netv2-hdmi-audio-in/gateware/kosagi_netv2.bit`, ~3.8 MB).

### Timing (post-route, slow corner)

| Check | Slack | Failing endpoints | Verdict |
|---|---|---|---|
| **Setup (WNS)** | **+0.774 ns** | 0 / 25125 | **MET** |
| **Hold (WHS)** | **+0.052 ns** | 0 / 25125 | **MET** |
| Pulse width (WPWS) | **-0.124 ns** | 14 / 11164 | not met (see below) |

Setup and hold **close** for the recovered 148.5 MHz pixel / 742.5 MHz serdes
clocking. This is effectively identical to phase-7a (7a: WNS +0.718, WHS +0.063,
WPWS -0.124 / 14) — **the audio core does not affect closure** (WNS is even a
touch better). The sole remaining violation is the same phase-7a exception: the
minimum-clock-period (pulse-width) check on the six ISERDESE2 cells at the
742.5 MHz `pix5x`, a **datasheet limit of the -2 speed grade** at 1080p60, not a
constraint/routing problem — cleared with margin at the preferred 720p
(371.25 MHz serdes). Vivado still writes a valid bitstream (as in 2019 / 7a).

### Utilisation (a7-100) — the audio core is small

| Resource | 7b used | 7a used | Δ (audio core) | Avail | 7b % |
|---|---|---|---|---|---|
| Slice LUTs | 8253 | 7601 | +652 | 63400 | 13.0 |
| Slice Registers | 10293 | 8465 | +1828 | 126800 | 8.1 |
| Block RAM Tile | 32 | 31.5 | +0.5 | 135 | 23.7 |
| DSP | 4 | 4 | 0 | 240 | 1.7 |
| MMCME2_ADV / PLLE2_ADV | 1 / 1 | 1 / 1 | 0 | 6 / 6 | — |
| BUFGCTRL / BUFR | 9 / 1 | 9 / 1 | 0 | 32 / 24 | — |
| Bonded IOB | 89 | 89 | 0 | 285 | 31.2 |

The extract core costs ~650 LUTs, ~1800 FFs (the 5 serial BCH LFSRs, the
BusSynchronizers, and the FIFO gray-counter CDC) and half a BRAM tile (the
256-deep sample FIFO). No new clocking resources. Plenty of room remains for the
phase-7c embed path and a DMA ring.

### Timing / clocking note — 720p vs 1080p

The build reuses the phase-7a input clocking unchanged. The phase-7a
`S7Clocking` MMCM is hard-configured for a **148.5 MHz** link clock
(`CLKFBOUT_MULT_F=5.0` → 742.5 MHz VCO — the only valid build-time VCO; a
74.25 MHz link would give a 371.25 MHz VCO, below the MMCM's 600 MHz floor).
So this SoC **builds at the 148.5 MHz (1080p60) config exactly like phase-7a**,
and 720p is reached on hardware via the runtime MMCM DRP retune (as the 2019
design did). The only phase-7a timing exception — the 742.5 MHz ISERDES
minimum-period (pulse-width) check, a **datasheet limit of the -2 speed grade**
— is inherited unchanged and is a non-issue at the preferred 720p (371.25 MHz
serdes) rate. The audio path itself is validated bit-exact at **720p / 48 kHz in
simulation**. The audio core is small (see utilisation) and does not affect the
input-serdes closure, which is the only real timing question here.

## What phase 7c (embed / re-embed) will require

- An **encoder** mirror of this core: pack PCM (from a CPU/DMA source) into
  Audio Sample Packets, generate ACR (N/CTS from the outgoing TMDS clock) and
  the Audio InfoFrame, compute the BCH ECC (reuse `parser._bch_step` /
  `hdmi_audio_model.hdmi_bch_ecc`), and TERC4-encode the bytes into data
  islands inserted into the **output** pixel stream. The HDCP spec §4.3-style
  "inject" side lives here.
- That needs the litevideo **output** pipeline (TERC4 encoder + data-island
  insertion), which is not ported yet (phase-7a ported input only).
- The Python model already produces correct island byte layouts + ECC, so it
  can double as the encoder's golden reference.

## What the on-hardware audio test will require

- A real HDMI **audio source** feeding `hdmi_in` 0 with LPCM (e.g. 720p60 /
  48 kHz), and the phase-7b bitstream loaded (needs Tim's explicit go-ahead —
  no bitstream is loaded on hardware in this phase).
- The **rpi3 golden-capture rig** to confirm the recovered PCM matches the
  source (compare `sample_data` drain against a known tone), and to validate the
  BCH algorithm/bit-order against a *real* capture (sim proves self-consistency
  vs the packer; a real stream confirms the polynomial + LSB-first byte order
  are the true HDMI convention).
- Firmware: a small `hdmi audio` command group to read N/CTS, compute fs from
  the FreqMeter, dump the InfoFrame, and drain/inspect the sample FIFO.
