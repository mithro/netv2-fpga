# The 2019 NeTV2 gateware

`legacy/netv2mvp.py` builds one of two SoCs: `BaseSoC`, a plain LiteX
VexRiscv/DDR3 system, and `VideoOverlaySoC`, which is `BaseSoC` plus the whole
video path. `video_overlay` is the default target
(`legacy/netv2mvp.py:1282-1284`) and is what every shipped bitstream in
`legacy/production-images/` and `legacy/testing-images/` contains.

This page describes both, the compositing rule in detail, the HDCP path, and
the TERC4 decoder. Pin assignments are in [hardware.md](hardware.md); the CRG,
the HDMI input clocking and the 23 timing exceptions are in
[clocking.md](clocking.md); the REPL that drives all of these CSRs is in
[firmware.md](firmware.md).

Line numbers given for `legacy/deps/litevideo/` refer to litevideo commit
`3bc5a24` ("add delay alignment feature", 2019-09-13), which is the version the
2019 design was built against.

## 1. `BaseSoC` (`legacy/netv2mvp.py:537-628`)

### 1.1 CPU and memory

`BaseSoC` subclasses `SoCSDRAM`. Its constructor arguments
(`legacy/netv2mvp.py:559-568`):

| Parameter | Value | Meaning |
|---|---|---|
| `cpu_type` | `"vexriscv"` | RV32 soft core; the `"debug"` variant is present but commented out (`legacy/netv2mvp.py:566`) |
| `integrated_rom_size` | `0x6000` | 24 KB BIOS ROM |
| `integrated_sram_size` | `0x1000` | 4 KB SRAM |
| `ident` | `"NeTV2 LiteX Base SoC"` | reported by the BIOS and by `status` |
| `reserve_nmi_interrupt` | `False` | frees interrupt 0 |
| `csr_address_width` | `17` | a large CSR space — the video cores need it |

`BaseSoC` registers six CSR peripherals: `ddrphy`, `xadc`, `dna`,
`cpu_or_bridge`, `spiflash`, `crg` (`legacy/netv2mvp.py:538-546`). `dna.DNA()`
and `xadc.XADC()` are instantiated unconditionally
(`legacy/netv2mvp.py:573-574`); the firmware's `dna` command reads the device
DNA as a serial number and `status` reads the XADC die temperature and supply
rails.

### 1.2 The system clock is 75 MHz, not 100

The system frequency is not a parameter — it is derived from the IDELAY
reference frequency, which is a module-level constant
(`legacy/netv2mvp.py:304`, `iodelay_clk_freq = int(300e6)`):

```python
    def __init__(self, platform, dqs_phase="112.5", spiflash="spiflash_1x", **kwargs):
        if iodelay_clk_freq == int(400e6) or iodelay_clk_freq == int(200e6):
            clk_freq = int(100e6)
        elif iodelay_clk_freq == int(300e6):
            clk_freq = int(75e6)  # we achieve 300e6 by changing the master divider so the whole system goes slower
```
(`legacy/netv2mvp.py:553-557`)

The comment is the whole explanation: a single MMCM generates both the IDELAY
reference and the fabric clock, and 300 MHz for `IDELAYCTRL` is only reachable
by lowering the VCO multiplier, which drags `sys` down with it. With
`clkfbout_mult = 12` (`legacy/netv2mvp.py:343-347`) the VCO runs at 600 MHz;
`CLKOUT5_DIVIDE=8` then gives 75 MHz for `sys` — the comment beside that output
still says "100 MHz - routing fabric" (`legacy/netv2mvp.py:403-405`), a leftover
from the 400 MHz/200 MHz configuration. `CLKOUT4_DIVIDE=clkfbout_mult` gives
50 MHz for `eth` regardless of which IDELAY frequency is chosen
(`legacy/netv2mvp.py:407-409`).

75 MHz is the number every DDR bandwidth and CPU-throughput calculation in the
2019 design rests on. See [clocking.md](clocking.md) for the full tree.

### 1.3 DDR3

`A7DDRPHY` on the `ddram` pads, with `iodelay_clk_freq=300e6` and electrical
settings `rtt_nom='20ohm'`, `rtt_wr='disabled'`, `ron='40ohm'`; the module
model is `K4B2G1646FBCK0(self.clk_freq, "1:4", speedgrade='1600')`
(`legacy/netv2mvp.py:579-584`). The `"1:4"` ratio with a 75 MHz `sys` gives a
300 MHz DDR clock, i.e. DDR3-600 — far below the module's 1600 grade, which is
used only to pick timing parameters. The controller is built with
`with_bandwidth=True` (the bandwidth counters the firmware's `status` reports),
`cmd_buffer_depth=8`, `with_refresh=True` and `with_auto_precharge=True`
(`legacy/netv2mvp.py:585-591`).

`READ_LEVELING_BITSLIP` (3) and `READ_LEVELING_DELAY` (14) are hard-coded BIOS
constants (`legacy/netv2mvp.py:583-584`), i.e. read leveling was calibrated
once by hand rather than swept at boot. Together with the `-d/--dqsphase` build
argument (`legacy/netv2mvp.py:1285-1287`, default 112.5 degrees), the DDR3
interface is tuned by rebuilding, not at runtime.

### 1.4 SPI flash and boot

```python
self.add_memory_region(
    "spiflash", self.mem_map["spiflash"] | self.shadow_base, 8*1024*1024)

self.flash_boot_address = 0x207b0000  # hard-coded to be just above the second copy of 100T bitfile
```
(`legacy/netv2mvp.py:625-628`)

The flash window is at `0x20000000` (`legacy/netv2mvp.py:548-550`), 8 MB, and
the BIOS looks for the firmware image at `0x207b0000`, i.e. offset `0x7b0000`
into the NOR — the comment records why: two copies of a 100T bitstream fit
below it. `SPIFLASH_PAGE_SIZE` (256) and `SPIFLASH_SECTOR_SIZE` (`0x10000`) are
passed to the BIOS as constants (`legacy/netv2mvp.py:622-623`). See
[boot-and-flash.md](boot-and-flash.md).

### 1.5 LEDs and fan

`fpga_led0` gets a 0.56 Hz heartbeat from bit 26 of a free-running counter in
the `sys` domain (`legacy/netv2mvp.py:594-606`); `fpga_led1` is tied to 0;
`fan_pwm` is tied to 1, i.e. the fan runs at full speed whenever the FPGA is
configured (`legacy/netv2mvp.py:599-600`). There is no thermal control loop
despite the XADC being present.

### 1.6 Etherbone over RMII (`VideoOverlaySoC` only)

The Ethernet stack is instantiated in `VideoOverlaySoC`, not `BaseSoC`
(`legacy/netv2mvp.py:1192-1229`). A `fast_eth` flag selects between putting the
whole stack in the 100 MHz `sys` domain and putting it in the 50 MHz `eth`
domain; it is set to `False` with the comment "100 MHz domain works but timing
closure is hard" (`legacy/netv2mvp.py:1197-1199`). In the shipped configuration:

- `LiteEthPHYRMII` and `LiteEthUDPIPCore` are both wrapped by
  `ClockDomainsRenamer("eth")` (`legacy/netv2mvp.py:1208-1215`), so the MAC and
  the IP/UDP stack run at 50 MHz, with `with_icmp=True`.
- MAC address `0x1337320dbabe`, IP address `10.0.11.2`, both hard-coded
  (`legacy/netv2mvp.py:1211-1213`).
- A separate `etherbone` clock domain is created and driven from `sys`
  (`legacy/netv2mvp.py:1217-1221`), and `LiteEthEtherbone(core.udp, 1234,
  mode="master", cd="etherbone")` becomes a Wishbone master
  (`legacy/netv2mvp.py:1223-1224`). So Etherbone bridges the 50 MHz packet
  stack to the 75 MHz bus.
- `sys` to `eth` is declared a false path (`legacy/netv2mvp.py:1226-1229`).

The `hdmi_in1` LiteScope analyzer is compiled in unconditionally
(`legacy/netv2mvp.py:1238-1254`), sampling seven input1 DMA and frame signals
64 deep in the `hdmi_in1_pix` domain, with a comment noting it should be
commented out for faster builds. It costs BRAM in every shipped bitstream.

## 2. `VideoOverlaySoC` (`legacy/netv2mvp.py:795-1256`)

### 2.1 CSR peripherals and interrupts

Added on top of `BaseSoC`'s six (`legacy/netv2mvp.py:797-812`):
`hdmi_core_out0`, `hdmi_in0`, `hdmi_in0_freq`, `hdmi_in0_edid_mem`,
`hdmi_in1`, `hdmi_in1_freq`, `hdmi_in1_edid_mem`, `rectangle`, `hdcp`,
`i2c_snoop`, `analyzer`, `phy`, `core`.

| Interrupt | Number | Source | Line |
|---|---|---|---|
| `hdmi_in1` | 3 | input1's DMA slot-complete event | 815 |
| `hdcp` | 4 | `Aksv14` write strobe, i.e. "the source started an HDCP authentication" | 816 |
| `hdmi_in0` | 5 | input0's TERC4 `t4packet` / `t4island` events | 817 |

`BOOT_MEMTEST` is added as a BIOS constant (`legacy/netv2mvp.py:825`), which is
what produces the `Memtest OK` line the test suite looks for.

The four phase-alignment Verilog files are added to the build here
(`legacy/netv2mvp.py:829-832`): `delay_controller.v`, `phsaligner.v`,
`DRAM16XN.v`, `chnlbond.v`. They implement the per-channel IDELAY search and the
three-channel bonding that litevideo's `alt_delay=True` path instantiates
(`legacy/deps/litevideo/litevideo/input/__init__.py:102-137`). The HDCP Verilog
is added later, at `legacy/netv2mvp.py:1037-1043`.

### 2.2 The two HDMI inputs

```python
self.submodules.hdmi_in0 = hdmi_in0 = HDMIIn(hdmi_in0_pads, device="xc7", split_mmcm=True, hdmi=True, iodelay_clk_freq=iodelay_clk_freq, alt_delay=True)
```
(`legacy/netv2mvp.py:837`)

```python
self.submodules.hdmi_in1 = self.hdmi_in1 = HDMIIn(hdmi_in1_pads,
                                 self.sdram.crossbar.get_port(mode="write"),
                                 fifo_depth=512,
                                 device="xc7",
                                 split_mmcm=False,
                                 mode="rgb",
                                 hdmi=True,
                                 n_dma_slots=2,
                                 iodelay_clk_freq = iodelay_clk_freq,
                                 alt_delay=True,
                                  )
```
(`legacy/netv2mvp.py:901-911`)

| Parameter | input0 | input1 | Why |
|---|---|---|---|
| `dram_port` | none | write port on the DDR crossbar | input0 never touches DDR; only input1 is captured |
| `split_mmcm` | `True` | `False` | input0 needs a second MMCM to make the independent output domains `pix_o`/`pix5x_o`; input1 only needs its own recovery clock |
| `hdmi` | `True` | `True` | both use the TERC4 preamble decoder for DE rather than the naive control-token DE |
| `mode` | n/a | `"rgb"` | input1 is stored as 32-bit RGB, not YCbCr 4:2:2 |
| `alt_delay` | `True` | `True` | use the `phsaligner`/`chnlbond` Verilog instead of litevideo's own aligner |
| `n_dma_slots` | n/a | 2 | double buffering in DDR |
| `fifo_depth` | n/a | 512 | see the comment at `legacy/netv2mvp.py:897-900`: 256 works but saves no BRAM |

Because `dram_port is None` for input0, litevideo never builds a
`FrameExtraction` or a `DMA` for it
(`legacy/deps/litevideo/litevideo/input/__init__.py:231-243`).
input0 exists only as decoded characters, timing and TERC4 status. Its decoded
RGB is never used by anything in the shipped design — the passthrough path
carries raw 10-bit TMDS characters.

Each input gets a `FrequencyMeter`. input0's is clocked from `cd_pix_raw`
rather than `cd_pix` so that a frequency reading is available even when the
MMCM has not locked (`legacy/netv2mvp.py:836,838`); input1's is clocked from
`cd_pix` and has a 1 second gate (`legacy/netv2mvp.py:896,912`).

`split_mmcm=True` on input0 is the source of the `pix_o` and `pix5x_o` domains
that the entire output path runs in. That is the mechanism behind "the output
is genlocked to input0": there is no output PLL of its own.

### 2.3 The output PHY is in raw mode

```python
hdmi_out0_pads = platform.request("hdmi_out", 0)  ## TODO: pull latest litevideo and re-validate pix_o mapping
self.submodules.hdmi_out0_clk_gen = ClockDomainsRenamer({"pix":"pix_o", "pix5x":"pix5x_o"})(S7HDMIOutEncoderSerializer(hdmi_out0_pads.clk_p, hdmi_out0_pads.clk_n, bypass_encoder=True))
self.comb += self.hdmi_out0_clk_gen.data.eq(Signal(10, reset=0b0000011111))
self.submodules.hdmi_out0_phy = ClockDomainsRenamer({"pix":"pix_o", "pix5x":"pix5x_o"})(S7HDMIOutPHY(hdmi_out0_pads, mode="raw"))
```
(`legacy/netv2mvp.py:868-871`)

`mode="raw"` changes the PHY's sink from an RGB+sync layout to three 10-bit
character fields (`legacy/deps/litevideo/litevideo/output/common.py:40-44`) and
bypasses the TMDS encoders entirely:

```python
if mode == "raw":
    self.comb += [
        sink.ready.eq(1),
        self.es0.data.eq(sink.c0),
        self.es1.data.eq(sink.c1),
        self.es2.data.eq(sink.c2)
    ]
```
(`legacy/deps/litevideo/litevideo/output/hdmi/s7.py:151-157`)

This is the key architectural decision of the whole design. Because the output
PHY consumes characters rather than pixels, anything the design does not
understand — data islands, guard bands, preambles, control periods, HDCP
ciphertext — can be forwarded bit for bit. The TMDS clock is produced by
serialising the constant pattern `0b0000011111` through a fourth serialiser,
so it is exactly the recovered input0 clock.

### 2.4 The overlay read path

```python
out_dram_port = self.sdram.crossbar.get_port(mode="read", clock_domain="pix_o", data_width=32, reverse=True)
self.submodules.hdmi_core_out0 = VideoOutCore(out_dram_port, mode="rgb", fifo_depth=4096, genlock_stream=hdmi_in0_timing)
```
(`legacy/netv2mvp.py:981-984`)

| Property | Value |
|---|---|
| Direction | read from DDR |
| Clock domain | `pix_o` (input0's derived output pixel clock) |
| Data width | 32 bits, `reverse=True` |
| FIFO depth | 4096 — the comment at `legacy/netv2mvp.py:982-983` says 1024 causes tearing at 1080p60 when the CPU is busy |
| Genlock | `hdmi_in0_timing`, the input0 timing stream |

So the two DDR ports face in opposite directions and live in different clock
domains: input1 writes in `hdmi_in1_pix`, the output core reads in `pix_o`. The
crossbar arbitrates between them and the CPU.

The genlock stream is built at `legacy/netv2mvp.py:879-890`: input0's
`syncpol` DE, HSYNC, VSYNC and valid are registered into `pix_o`. Inside
`DMAReader` the genlock stream's VSYNC edge is what restarts the frame
(`legacy/deps/litevideo/litevideo/output/core.py:113-120,231-235`), which is
how the overlay framebuffer stays aligned to the incoming source frame without
any handshake with the Pi.

`early_line_end` (`legacy/netv2mvp.py:891-892`) is `hdmi_in0_timing.de &
~syncpol.de` — a one-cycle pulse on the *last* pixel of a line rather than the
first cycle after it, obtained by comparing the registered and unregistered DE.
The HDCP block needs exactly this, per the integration note at
`legacy/overlay/hdcp_mod.v:22-26`.

### 2.5 Delay matching

Three separate delay lines keep the branches of the pipeline aligned:

| Delay | Latency | Purpose | Line |
|---|---|---|---|
| `timing_rgb_delay` | 4 `pix_o` cycles | RGB overlay pixels, matched to the encoder pipeline | 995-1009 |
| `timing_csc_delay` | `4 + RGB2YCbCrDatapath.latency` | a copy of the same RGB, delayed to line up with the YCbCr output so the chroma comparison can be done against RGB while the encoder consumes YCbCr | 1026-1032 |
| raw character delay | 6 `pix_o` cycles + 1 | input0's raw TMDS characters, matched to the whole overlay pipeline | 1102-1138 |

The comment block at `legacy/netv2mvp.py:1021-1025` explains the second one:

```
# YCrCb PATH:
#    RGB overlay video => CSC   => YCrCb overlay video
#                     |=> delay => RGB overlay video (synced to YCrCb video)
#    RGB passthrough video => compare chroma against RGB overlay video synced to YCrCb video
```

The raw delay line is built by a Python loop rather than a module:

```python
for i in range(6): # either 5 or 6; 5 if the first pixel is encrypted by the idle cipher; 6 if the cipher has to be pumped before encryption
    c0_next = Signal(10)
    ...
    self.sync.pix_o += [  # extra delay to absorb cross-domain jitter & routing
        c0_next.eq(c0),
        c1_next.eq(c1),
        c2_next.eq(c2),
        stream_de_next.eq(stream_de),
    ]
```
(`legacy/netv2mvp.py:1117-1131`)

followed by one more register stage at `legacy/netv2mvp.py:1133-1138`, so the
raw path is 7 `pix_o` cycles deep in total. The loop count is empirical: the
comment says it is 5 or 6 depending on whether the HDCP cipher has to be pumped
before it produces the first keystream byte, and 6 was chosen. Note what is
delayed: `syncpol.c0/c1/c2`, the raw 10-bit characters, and `syncpol.de_int`,
the *undelayed* DE straight out of the TERC4 decoder — not `syncpol.de`
(`legacy/netv2mvp.py:1111-1116`).

### 2.6 The rectangle and the chroma key

`RectOpening` (`legacy/netv2mvp.py:720-770`) does two things. It maintains its
own pixel counters, derived from input0's DE and VSYNC rather than from
programmed timing, "because we want to sync to non-compliant data streams"
(`legacy/netv2mvp.py:738-739`, counters at `legacy/netv2mvp.py:749-767`). And
it produces `rect_on`:

```python
self.comb += self.rect_on.eq(((hcounter > self.hrect_start.storage) & (hcounter < self.hrect_end.storage) &
                              (vcounter > self.vrect_start.storage) & (vcounter < self.vrect_end.storage))  == 1)
```
(`legacy/netv2mvp.py:769-770`)

Both bounds are exclusive. Its CSRs (`legacy/netv2mvp.py:723-736`):
`hrect_start`, `hrect_end`, `vrect_start`, `vrect_end` (12 bits each),
`rect_enable`, `pipe_override`, `chroma_key_hi` (24 bits, reset `0xffffff`),
`chroma_key_lo` (24 bits, reset `0x141414`), `chroma_polarity`, `chroma_mode`.

**`pipe_override` is declared but never read.** It is a CSR at
`legacy/netv2mvp.py:728` and the firmware toggles it
(`legacy/firmware/ci.c:1132`), but nothing in `legacy/netv2mvp.py` consumes
`rectangle.pipe_override.storage`. The only file that uses it is the
alternative top level `legacy/netv2mvp_genddr.py:1152`, which is not what was
shipped. This contradicts the compositing rule stated in
`tests/hdmi-suite/docs/TEST-SUITE-DESIGN.md:22-27`, whose first branch is
`if pipe_override: out = raw input0 TMDS characters`. In the shipped design
that branch does not exist and writing `pipe_override` has no effect. The same
suite document's second branch, `min(overlay.r,g,b) >= rect_thresh`, describes
an older design too: there is no `rect_thresh` CSR in `legacy/netv2mvp.py`, and
the firmware's write of it is commented out (`legacy/firmware/ci.c:745`). What
the shipped design has instead is the two-sided chroma key below, which the
firmware initialises to `lo = 0x141414`, `hi = 0xffffff`, `polarity = 0`,
`mode = 0` (`legacy/firmware/ci.c:746-749`) — that is, "overlay wins when all
three channels are >= 20", which is numerically the same rule the suite
document describes.

The firmware also disables the rectangle at startup —
`rectangle_rect_enable_write(0); // setup the rectangle, but don't use it -- we
are now using DE gating` (`legacy/firmware/ci.c:732`) — so in the stock
configuration the overlay is gated by DE and the chroma key alone, over the
whole active area.

### 2.7 The compositing mux, verbatim

`rect_on` is recomputed at the top level, combining the rectangle with input0's
delayed DE:

```python
        # skip the final pipe to line up de against the actual video stream
        self.comb += rect_on.eq(stream_de_pix_o & (~rectangle.rect_enable.storage | rectangle.rect_on))  # let's only do overlay when DE is active on the passthrough stream
```
(`legacy/netv2mvp.py:1147-1148`)

and then the mux itself:

```python
        self.sync.pix_o += [ # overlay video selected
            chpol.eq(rectangle.chroma_polarity.storage),
            chlo.eq(rectangle.chroma_key_lo.storage),
            chhi.eq(rectangle.chroma_key_hi.storage),
            chmode.eq(rectangle.chroma_mode.storage),
            If(chmode & rect_on & (chpol ^
                         ((hdmi_out0_rgb_csc.r >= chlo[:8]) &
                          (hdmi_out0_rgb_csc.g >= chlo[8:16]) &
                          (hdmi_out0_rgb_csc.b >= chlo[16:24]) &
                          (hdmi_out0_rgb_csc.r <= chhi[:8]) &
                          (hdmi_out0_rgb_csc.g <= chhi[8:16]) &
                          (hdmi_out0_rgb_csc.b <= chhi[16:24]))),
               self.hdmi_out0_phy.sink.c0.eq(encoder_blu.out),
               self.hdmi_out0_phy.sink.c1.eq(encoder_grn.out),
               self.hdmi_out0_phy.sink.c2.eq(encoder_red.out),
            ).Elif(~chmode & rect_on & (chpol ^
```
(`legacy/netv2mvp.py:1149-1164`; the `Elif` arm at 1164-1173 is the same
comparison against `hdmi_out0_rgb_d` instead of `hdmi_out0_rgb_csc`, and
selects the same three encoder outputs)

```python
            ).Else( # background video selected
                    self.hdmi_out0_phy.sink.c0.eq(c0_pix_o),
                    self.hdmi_out0_phy.sink.c1.eq(c1_pix_o),
                    self.hdmi_out0_phy.sink.c2.eq(c2_pix_o),
            )
        ]
```
(`legacy/netv2mvp.py:1174-1179`)

In prose, per character time in the `pix_o` domain:

1. **The overlay pixel is chosen** when all three of these hold: input0's
   delayed DE is asserted (`stream_de_pix_o`), the rectangle either is disabled
   or contains the current pixel, and the chroma test passes. The chroma test
   is a two-sided per-channel window — every channel must be within
   `[chroma_key_lo, chroma_key_hi]` — XORed with `chroma_polarity`, so setting
   polarity to 1 inverts the whole key into "overlay wins outside the window".
   `chroma_mode` picks which copy of the overlay pixel is tested: the
   colour-space-converted one (`hdmi_out0_rgb_csc`) when the encoders are being
   fed YCbCr, the plain delayed RGB (`hdmi_out0_rgb_d`) otherwise. The value
   sent out is always the freshly TMDS-encoded overlay pixel from
   `encoder_blu/grn/red`.
2. **The raw input0 character passes through** in every other case: the
   `Else` arm sends `c0_pix_o`/`c1_pix_o`/`c2_pix_o`, which are input0's
   original 10-bit TMDS characters delayed by 7 `pix_o` cycles.

Two consequences follow from that structure.

**Data islands are forwarded untouched.** `stream_de_pix_o` is the delayed
`syncpol.de_int`, and with `hdmi=True` that signal is wired straight from the
TERC4 preamble decoder's `de_o`
(`legacy/deps/litevideo/litevideo/input/__init__.py:179`), which is only
asserted in the decoder's
`VIDEO` state (`legacy/deps/litevideo/litevideo/input/decoding.py:365-374`).
Data islands live in the `TERC4` state, where `de_hdmi` is 0
(`legacy/deps/litevideo/litevideo/input/decoding.py:302-315`), as do guard
bands, preambles and control periods. So during a data island `rect_on` is 0,
the `Else` arm is taken, and the original characters — audio samples,
InfoFrames, the lot — are re-serialised bit for bit. The design does not decode
them, does not regenerate them and cannot corrupt them. This is why HDMI audio
passes through a NeTV2 at all, and why the design never needed an audio path.
(It is also why the baseline suite's silent T23 audio result is surprising and
remains undiagnosed.)

**The overlay is only ever composited inside the active video area.** Because
the mux is gated on input0's DE, the overlay can never extend into the blanking
region, no matter what rectangle is programmed.

Note that this is a *character* mux, not a pixel mux: the two arms produce
10-bit TMDS characters from completely different sources, and the choice can
change every character time. There is no blending — a pixel is either fully
overlay or fully source.

One detail worth flagging for anyone reimplementing this: the byte order of
the chroma CSRs is not the obvious one. `r` is compared against bits `[0:8]` of
`chroma_key_lo` and `b` against bits `[16:24]`, so the 24-bit CSR reads as
`0xBBGGRR`, not `0xRRGGBB`. The firmware's defaults (`0x141414` and `0xffffff`)
have identical bytes and so cannot reveal the mismatch
(`legacy/firmware/ci.c:746-747`).

### 2.8 The overlay encoders

Three `Encoder()` instances in `pix_o` (`legacy/netv2mvp.py:1063-1065`) TMDS-
encode the overlay pixel. Their inputs are selected by a four-way mux
(`legacy/netv2mvp.py:1069-1100`) on `chroma_mode` (YCbCr path or RGB path) and
`hdcp.Km_valid` (HDCP initialised or not):

| `chroma_mode` | `Km_valid` | red / green / blue encoder inputs |
|---|---|---|
| 1 | 1 | `cr ^ cipher[16:24]`, `y ^ cipher[8:16]`, `cb ^ cipher[0:8]` |
| 1 | 0 | `cr`, `y`, `cb` |
| 0 | 1 | `rgb.r ^ cipher[16:24]`, `rgb.g ^ cipher[8:16]`, `rgb.b ^ cipher[0:8]` |
| 0 | 0 | `rgb.r`, `rgb.g`, `rgb.b` |

`de` is tied to 1 and `c` to 0 on all three encoders, with the comment "we
promise to use this only during video areas, so `c` is always 0"
(`legacy/netv2mvp.py:1092-1099`) — which is exactly the promise the `rect_on`
gating keeps.

## 3. HDCP

### 3.1 What is instantiated

Seven Verilog files are added to the build unconditionally
(`legacy/netv2mvp.py:1037-1043`): `i2c_snoop.v`, `diff_network.v`,
`hdcp_block.v`, `hdcp_cipher.v`, `hdcp_lfsr.v`, `shuffle_network.v`,
`hdcp_mod.v`. There is no build flag: **HDCP is a compile-time part of every
shipped bitstream**, and its LUT and BRAM cost is present whether or not a
source ever authenticates.

`I2Csnoop` (`legacy/netv2mvp.py:631-652`) wraps `i2c_snoop.v` around input0's
DDC pads. It watches, in the 50 MHz `eth` domain, for I2C transactions to
address `0x74` — the HDCP DDC slave address — and exposes:

- `edid_snoop_adr`/`edid_snoop_dat`, an 8-bit windowed read of the snooped
  register file, which the firmware uses to recover Aksv and Bksv
  (`legacy/firmware/km.c:12-15`);
- `An`, the 64-bit session key, wired straight out as a bus;
- `Aksv14_write`, a strobe asserted when byte 14 of the Aksv record is written,
  i.e. when the source has just started an authentication.

Note the polarity inversion at the instance boundary: `i_SDA=~pads.sda`,
`i_SCL=~pads.scl` (`legacy/netv2mvp.py:641-642`).

`HDCP` (`legacy/netv2mvp.py:654-717`) wraps `hdcp_mod.v` in the `pix_o` domain.
Its CSRs are `Km` (56 bits), `Km_valid`, `hpd_ena`, `Aksv_mode`,
`Aksv_manual`, `debug` (`legacy/netv2mvp.py:670-675`), and it raises the `aksv`
interrupt from an `EventSourcePulse` fed by a `MultiReg`-synchronised
`Aksv14_write_level` (`legacy/netv2mvp.py:680-687`). `Aksv_mode` selects
between the automatic strobe and a CSR-driven manual one
(`legacy/netv2mvp.py:689-697`).

The top-level wiring (`legacy/netv2mvp.py:1045-1060`):

| `hdcp_mod` input | Driven by |
|---|---|
| `de`, `hsync`, `vsync` | input0's timing stream, in `pix_o` |
| `line_end` | `early_line_end`, the last-pixel pulse from 2.4 |
| `ctl_code` | `hdmi_in0.decode_terc4.ctl_code` — the CTL bits on channels 1 and 2, needed for EESS detection |
| `hdcp_ena` | `decode_terc4.encrypting_video \| encrypting_data` |
| `hpd` | `hdmi_in0_pads.hpd_notif` |
| `An` | `i2c_snoop.An` |
| `Km`, `Km_valid` | CSRs written by the firmware |
| `Aksv14_write` | a rising-edge strobe derived from the snoop, resynchronised into `pix_o` |

The only output used is `cipher_stream`, 24 bits of keystream per pixel, XORed
into the overlay pixel before encoding (section 2.8). `stream_ready` is
declared but not consumed.

`hdcp.hpd_ena` drives `hdmi_rx0_forceunplug` (`legacy/netv2mvp.py:1060`), which
is how the firmware forces the source to re-authenticate.

### 3.2 What it does and does not do

The header of `legacy/overlay/hdcp_mod.v:1-38` states the model plainly. Km is
computed by the CPU from observed Aksv/Bksv values; An is recovered per
session from the DDC snoop; cipher initialisation is triggered when byte 14 of
Aksv is written, and must complete within 100 ms.

So the design **re-encrypts the overlay pixels with the same HDCP keystream the
source is using**, so that an overlay pixel substituted into an encrypted link
decrypts correctly at the sink. It does **not** decrypt the source. Nothing in
the passthrough path is ever decrypted or re-encrypted — the raw characters go
through untouched, ciphertext included. The design never sees the source's
plaintext video, and never needs to: it only needs to produce ciphertext that
sits in the same keystream position.

This is why the delay line in 2.5 has to be exactly right. The HDCP cipher
advances one keystream word per pixel and rekeys per line; if the overlay
encoder is fed a keystream word from a different pixel position than the one it
is substituted into, the sink decrypts garbage. Hence the comment "match pixel
processing pipeline depth (necessary to get HDCP to line up)"
(`legacy/netv2mvp.py:1102`) and the "either 5 or 6" uncertainty about pumping
the cipher.

`Km` itself is computed in firmware. `legacy/firmware/compute_ksv.c` carries a
40x40 table of 56-bit HDCP master-key values and computes Km from the observed
KSVs; it is compiled into every firmware image
(`legacy/firmware/Makefile:28`). `legacy/firmware/km.c` drives the whole
sequence: unmask the HDCP interrupt, read the snooped Aksv/Bksv over the CSR
window, compute Km, write it and set `Km_valid`. See
[firmware.md](firmware.md).

## 4. TERC4 decoding and the data-island counters

`DecodeTERC4` (`legacy/deps/litevideo/litevideo/input/decoding.py:184-375`) is
instantiated inside `HDMIIn` whenever `hdmi=True`, renamed into the `pix`
domain. It runs a seven-state FSM over the three channels' decoded control
values — `INIT`, `PREAM_T4`, `GOING_T4`, `TERC4`, `LEAVE_T4`, `PREAM_VID`,
`GOING_VID`, `VIDEO` — driven by the preamble CTL codes (`0b0101` for a data
island, `0b0001` for video), the data guard band on channels 1 and 2, and the
video guard band on all three
(`legacy/deps/litevideo/litevideo/input/decoding.py:246-374`).

Its outputs:

| Signal | Asserted in state | Consumer |
|---|---|---|
| `de_hdmi` -> `de_o` | `VIDEO` only | `syncpol.de_int`, and hence the mux gate |
| `encrypting_video` | `VIDEO` | ORed into `hdcp_ena` |
| `encrypting_data` | `TERC4` | ORed into `hdcp_ena` |
| `encoding_terc4` | `GOING_T4`, `TERC4`, `LEAVE_T4` | unused at the top level |
| `ctl_code` | always | `hdcp_mod`'s EESS detection |

A `dvimode` CSR switches `de_o` back to the naive per-channel DE for DVI
sources (`legacy/deps/litevideo/litevideo/input/decoding.py:197-210`).

Data-island capture registers, all `CSRStatus`
(`legacy/deps/litevideo/litevideo/input/decoding.py:212-228`):

| CSR | Width | Contents |
|---|---|---|
| `t4d_bch0..3` | 64 bits each | a shift register fed 2 bits per character in the `TERC4` state, from bit *n* of channels 1 and 2 — i.e. the four BCH-protected packet body bit-planes |
| `t4d_bch4` | 32 bits | bit 2 of channel 0, the packet header bit-plane |
| `t4d_char` | 8 bits | characters seen within the current packet, wrapping at 31 |
| `t4d_count` | 8 bits | packets completed within the current island |

All five capture registers and both counters are cleared on entry to `GOING_T4`
(`legacy/deps/litevideo/litevideo/input/decoding.py:294-300`), so what the
firmware reads is always from the *most recent* island, not an accumulation.

Two interrupt events: `t4packet` fires every 32 characters, i.e. once per
packet (`legacy/deps/litevideo/litevideo/input/decoding.py:321-327`), and
`t4island` fires once on `LEAVE_T4`
(`legacy/deps/litevideo/litevideo/input/decoding.py:339`).

### The `t4d` label bug

The firmware's `debug t4d` command prints six lines all labelled "hdmi0", but
the first one reads **input1's** counters:

```c
printf( "hdmi0 terc4 packet cnt: %d, char cnt: %d\n", hdmi_in1_decode_terc4_t4d_count_read(), hdmi_in1_decode_terc4_t4d_char_read());
```
(`legacy/firmware/ci.c:1155`)

The five `bch` lines below it (`legacy/firmware/ci.c:1156-1163`) do read
`hdmi_in0_*`. So a single `debug t4d` mixes two sources: packet and character
counts from the overlay input, BCH capture words from the source input, all
under one label. `debug t4i` (`legacy/firmware/ci.c:1141-1151`) unmasks
`HDMI_IN0_INTERRUPT` and enables input0's TERC4 events, which is consistent
with the intent that `t4d` should have reported input0. Anything reading
`t4d`'s packet count as evidence about the source's data islands is reading the
Pi's overlay link instead.

## 5. Data-flow diagrams

### 5.1 The passthrough path: input0 pads to output0 pads

```
  hdmi_in 0 pads (L19/L20 clk, K21..H22 data)
        |
        |  IBUFDS + MMCM (split_mmcm=True)  -> cd_pix, cd_pix5x, cd_pix_raw
        |                                   -> cd_pix_o, cd_pix5x_o  (output side)
        v
  S7DataCapture x3      IDELAY + ISERDES, phase search in phsaligner.v,
  (alt_delay=True)      3-channel bonding in chnlbond.v, p/n inversion undone
        |
        |  10-bit characters, cd_pix
        v
  CharSync -> Decoding x3 -> ChanSync
        |                        |
        |                        +--> DecodeTERC4  --> de_o, ctl_code,
        |                        |                     encrypting_video/data,
        |                        |                     t4d_* counters
        v                        v
  SyncPolarity  (c0, c1, c2 = raw characters; de_int = TERC4 de_o)
        |
        |  cross into cd_pix_o
        v
  +--------------------------------------------+
  |  7-stage register delay (netv2mvp.py:1102-1138)
  |  c0_pix_o, c1_pix_o, c2_pix_o, stream_de_pix_o
  +--------------------------------------------+
        |
        v
   +---------------------+          overlay characters
   |  compositing mux    | <------  from 5.2
   |  netv2mvp.py:1149-1179
   +---------------------+
        |  sink.c0/c1/c2
        v
  S7HDMIOutPHY(mode="raw")   3x OSERDESE2 pairs, 10:1, cd_pix5x_o
        |
        + S7HDMIOutEncoderSerializer(clk_p, clk_n) emitting 0b0000011111
        v
  hdmi_out 0 pads (W19/W20 clk, W21..U21 data)
```

Everything from the pads to the mux and back is combinational or registered
character handling: no frame buffer, no line buffer, no resampling. Latency
from input pad to output pad is the capture SERDES plus 7 pixel clocks.

### 5.2 The overlay path: input1 pads to the mux

```
  hdmi_in 1 pads (Y18/Y19 clk, AA18..AB22 data)   [pcb or cable inversions]
        |
        v
  HDMIIn(split_mmcm=False, mode="rgb", n_dma_slots=2, fifo_depth=512)
  MMCM -> cd_hdmi_in1_pix / _pix5x
        |
  capture -> charsync -> decode -> chansync -> DecodeTERC4 -> SyncPolarity
        |
        |  8:8:8 RGB + de + vsync, in hdmi_in1_pix
        v
  FrameExtraction (512-deep FIFO)
        |
        v
  DMA (2 slots)  ---- write port ---->  +-----------------+
                                        |  DDR3 crossbar  |
  hdmi_in1 interrupt 3 on slot done     |  (75 MHz sys)   |
                                        +-----------------+
                                                 |
        <-- read port, clock_domain="pix_o", dw=32, reverse=True
                                                 |
                                                 v
  VideoOutCore(fifo_depth=4096, genlock_stream=hdmi_in0_timing)
        |   Initiator (CSR frame params) + DMAReader + TimingGenerator
        |   restarts on input0's VSYNC -> frames stay aligned to the source
        v
  core_source_data_d[31:0]  (registered in pix_o, netv2mvp.py:986-992)
        |
        +--> hdmi_out0_rgb  (b = [0:8], g = [8:16], r = [16:24])
        |        |
        |        +--> TimingDelayRGB(4) --------------> hdmi_out0_rgb_d ---+
        |        |                                                          |  (chroma compare,
        |        +--> TimingDelayRGB(4 + CSC latency) -> hdmi_out0_rgb_csc -+   chroma_mode = 0/1)
        |
        +--> RGB2YCbCr --> cr / y / cb
                 |
                 v
        +--------------------------+       hdcp.cipher_stream[23:0]
        |  encoder input mux       | <---- (XOR when Km_valid)
        |  netv2mvp.py:1069-1100   |
        +--------------------------+
                 |
                 v
        Encoder x3 (red, grn, blu) in pix_o
                 |
                 v
        to the compositing mux in 5.1
```

## 6. Resource footprint

Unknown. There is no `legacy/build/` directory in this repository and no
Vivado utilisation or timing report was archived alongside the shipped
bitstreams — `legacy/production-images/` and `legacy/testing-images/` contain
only `.bit` and `.bin` files. The only quantitative hints in the source are
comments: that the input1 FIFO cannot usefully shrink below 512 because of BRAM
granularity (`legacy/netv2mvp.py:897-900`), that the output FIFO needs 4096 to
avoid tearing (`legacy/netv2mvp.py:982-983`), and that the LiteScope analyzer
should be removed for faster builds (`legacy/netv2mvp.py:1253`).

Actual LUT, FF, BRAM and CMT utilisation for the 35T and the 100T, and the
worst negative slack the 2019 design achieved, will only be known after phase
1's time-boxed rebuild. See [rebuild-2019.md](rebuild-2019.md).

What can be stated without a build: the design uses 4 MMCME2_ADV and 2 PLLE2
(see [clocking.md](clocking.md)), which on an Artix-7 with two clock-management
tiles per bank region is the main placement constraint, and it compiles in HDCP
(section 3.1) and a LiteScope analyzer (section 1.6) whether or not they are
used.

## 7. Timing exceptions

Covered in [clocking.md](clocking.md). They occupy
`legacy/netv2mvp.py:841-866`, `914-925` and `927-977`, plus
`1226-1229` and `1249-1252`.
