# Clocking in the 2019 design

How the 2018 to 2019 NeTV2 design generated, distributed and constrained its
clocks. Every claim cites `legacy/<file>:<line>`.

**Note on litevideo line numbers.** The litevideo fork the 2019 build used is
recorded as the `deps/litevideo` submodule (`.gitmodules`, branch `terc4-data`).
All litevideo line numbers below are for **commit `3bc5a24`** ("add delay
alignment feature"), which is the commit whose API the top level actually calls:
`netv2mvp.py:837` and `netv2mvp.py:909` pass `iodelay_clk_freq=` and
`alt_delay=`, and `netv2mvp.py:838` reads `clocking.cd_pix_raw`, none of which
exist in the older `eab7078`. Read the files from the AlphamaxMedia litevideo
clone if the submodule working tree in `legacy/deps/litevideo/` is checked out
at an older commit; the citations are written as
`legacy/deps/litevideo/litevideo/<file>:<line>` throughout.

## 1. The board's only oscillator

There is one free-running clock into the FPGA: the 50 MHz `clk50` pad. It is
put on a global buffer immediately so that the PLL and MMCM instances that
consume it are not constrained to one clock region:

```python
# legacy/netv2mvp.py:339-341
self.specials += [
    Instance("BUFG", i_I=clk50, o_O=clk50_distbuf), # this allows PLLs/MMCMEs to be placed anywhere and reference the input clock
]
```

The two HDMI input clock pads are the other two clock roots. Both are declared
to the timing engine as 148.5 MHz fundamentals (`netv2mvp.py:931-934`), which is
why `S7Clocking` asserts `clkin_freq in [74.25e6, 148.5e6]`
(`legacy/deps/litevideo/litevideo/input/clocking.py:118`) — see section 6 for
what happens at 74.25 MHz.

## 2. Every CMT instance in the design

`use_ss=False` is passed at `netv2mvp.py:571`, so only the non-spread-spectrum
branch of the CRG (`netv2mvp.py:352-455`) is built. The `use_ss=True` branch
(`netv2mvp.py:456-521`) is dead code in every shipped bitstream.

| # | Primitive | Where | Input | Mult / Div | VCO | Outputs → domain | Buffer |
|---|---|---|---|---|---|---|---|
| 1 | `PLLE2_BASE` | `netv2mvp.py:365-374` | `clk50_distbuf` (50 MHz) | `CLKFBOUT_MULT=24`, `DIVCLK_DIVIDE=1` | 1200 MHz | `CLKOUT0` /4 = 300 MHz → `delayrefclk` | BUFG (`:444`) |
| 2 | `MMCME2_ADV` (DDR data/DQS, "rhs_d") | `netv2mvp.py:382-419` | `clk50_distbuf` | `CLKFBOUT_MULT_F=12`, `DIVCLK_DIVIDE=1` | 600 MHz | `CLKOUT0` /2 = 300 MHz → `sys4x`; also → `sys2x` via BUFR/2 | BUFIO (`:447`), BUFR (`:448`) |
| | | | | | | `CLKOUT1` /4 = 150 MHz → `pll_sys2x` (**unused**, see 2.1) | none |
| | | | | | | `CLKOUT2` /2, phase `dqs_phase` = 300 MHz → `sys4x_dqs` | BUFIO (`:449`) |
| | | | | | | `CLKOUT5` /8 = 75 MHz → `sys` | BUFG (`:442`) |
| | | | | | | `CLKOUT4` /12 = 50 MHz → `eth` | BUFG (`:443`) |
| 3 | `MMCME2_ADV` (DDR address/control, "rhs_ac") | `netv2mvp.py:423-434` | `clk50_distbuf` | `CLKFBOUT_MULT_F=12`, `DIVCLK_DIVIDE=1` | 600 MHz | `CLKOUT0` /2 = 300 MHz → `sys4x_ac` | BUFIO (`:451`) |
| 4 | `MMCME2_ADV` (HDMI in 0) | `clocking.py:136-160` | `hdmi_in0_clk_p` via IBUFDS (`:125`) | `CLKFBOUT_MULT_F=5.0`, `DIVCLK_DIVIDE=1` | 742.5 MHz | `CLKOUT0` /5 = 148.5 MHz → `pix` | BUFG (`:161`) |
| | | | | | | `CLKOUT1` /4 = 185.625 MHz → `pix1p25x` (gearbox only) | BUFG (`:162`) |
| | | | | | | `CLKOUT2` /1 = 742.5 MHz → `pix5x`; and /4 = 185.625 MHz → `pix1p25x_r` | BUFIO (`:164`), BUFR (`:163`) |
| 5 | `PLLE2_ADV` (HDMI in 0 output side) | `clocking.py:184-205` | `mmcm_clk0` (148.5 MHz, **uncompensated**) | `CLKFBOUT_MULT=10`, `DIVCLK_DIVIDE=1` | 1485 MHz | `CLKOUT0` /10 = 148.5 MHz → `pix_o` | BUFG (`:206`) |
| | | | | | | `CLKOUT2` /2 = 742.5 MHz → `pix5x_o` | BUFG (`:207`) |
| 6 | `MMCME2_ADV` (HDMI in 1) | `clocking.py:136-160` | `hdmi_in1_clk_p` via IBUFDS | as #4 | 742.5 MHz | `pix`, `pix1p25x`, `pix1p25x_r`, `pix5x` | as #4 |

Instances 4 and 5 come from the same `S7Clocking` module; instance 5 is built
only because `hdmi_in0` is constructed with `split_mmcm=True`
(`netv2mvp.py:837`), which reaches `S7Clocking` as `split_clocking`
(`clocking.py:90`, `109-115`, `181`). `hdmi_in1` is built with
`split_mmcm=False` (`netv2mvp.py:905`), so it has no `pix_o` side.

`cd_pix_raw` (`clocking.py:121-122`) is not a CMT output at all: it is the
IBUFDS output combinationally tied to a clock domain, used only by the
`FrequencyMeter` instances (`netv2mvp.py:838`, `:913`) so that frequency
measurement works before the MMCM has locked.

### 2.1 Two curiosities in the CRG

`CLKOUT1` of the data/DQS MMCM produces `pll_sys2x` (`netv2mvp.py:395-397`) but
no buffer consumes it; `cd_sys2x` is instead derived from `pll_sys4x` through a
`BUFR` with `BUFR_DIVIDE="2"` (`netv2mvp.py:448`). *Inference:* the BUFR route
was chosen so `sys2x` stays bank-local next to the DDR I/O, and the `CLKOUT1`
leg was left behind; Vivado will trim it.

The inline comments on the MMCM outputs ("400 MHz - BUFIO", "200 MHz - BUFR",
"100 MHz - routing fabric", `netv2mvp.py:391`, `:395`, `:405`) describe the
`iodelay_clk_freq = 400e6` configuration, not the 300 MHz one that shipped. At
`clkfbout_mult = 12` the real numbers are 300/150/75 MHz. Do not read the
comments as the frequencies.

## 3. Why `sys` is 75 MHz

The IDELAY reference frequency is a module-level constant:

```python
# legacy/netv2mvp.py:303-304
# valid values are 200e6, 300e6, and 400e6
iodelay_clk_freq = int(300e6)
```

and the system frequency is derived from it, not chosen independently:

```python
# legacy/netv2mvp.py:554-557
if iodelay_clk_freq == int(400e6) or iodelay_clk_freq == int(200e6):
    clk_freq = int(100e6)
elif iodelay_clk_freq == int(300e6):
    clk_freq = int(75e6)  # we achieve 300e6 by changing the master divider so the whole system goes slower
```

The mechanism is `clkfbout_mult`, selected at `netv2mvp.py:344-348`: 16 for the
200/400 MHz cases (VCO 800 MHz, `sys` = 800/8 = 100 MHz) and 12 for 300 MHz
(VCO 600 MHz, `sys` = 600/8 = 75 MHz). Because `sys4x` is a fixed /2 of the same
VCO, raising the IDELAY reference to 300 MHz necessarily drops the whole SoC to
75 MHz. That is the sentence in the comment: the 300 MHz IDELAY reference was
bought by slowing the system clock by 25 %.

`iodelay_clk_freq` is passed on to the DDR PHY (`netv2mvp.py:579`), exported to
the firmware as the `IDELAYCTRL_CLOCK_FREQUENCY` constant
(`netv2mvp.py:581`) — the firmware reads it at `legacy/firmware/hdmi_in0.c:19`
to pick tap-duration constants — and passed to both `HDMIIn` instances
(`netv2mvp.py:837`, `:909`) where it becomes `p_REFCLK_FREQUENCY` on the
`IDELAYE2` primitives (`legacy/deps/litevideo/litevideo/input/datacapture.py:352`,
`:410`).

### The `dqs_phase` knob

`CRG.__init__` takes `dqs_phase=112.5` with the comment "dqs_phase is multiple
of 22.50" (`netv2mvp.py:307`); it is applied as `p_CLKOUT2_PHASE` on the
data/DQS MMCM (`netv2mvp.py:400`). It is a build-time command-line argument,
`-d/--dqsphase`, restricted to the seven values 45.0 through 180.0
(`netv2mvp.py:1283-1285`), threaded through `VideoOverlaySoC` and `BaseSoC`
(`netv2mvp.py:1297`, `:821-822`, `:553`, `:571`) and echoed at build time
(`netv2mvp.py:349`). Both `make_images.sh` and `make_testing.sh` build at the
default 112.5 (`legacy/make_testing.sh:29`, `:38`); `make_phases.sh` exists to
sweep it. It shifts the DQS strobe relative to DQ for DDR3 write levelling; the
22.5 degree granularity is the MMCM's phase-shift resolution at this VCO.

## 4. IDELAYCTRL

There is exactly one `IDELAYCTRL`, in the CRG:

```python
# legacy/netv2mvp.py:527-535
reset_counter = Signal(4, reset=31)  # 77.5ns @ 400MHz, min 59.28ns
ic_reset = Signal(reset=1)
self.sync.delayrefclk += \
    If(reset_counter != 0,
        reset_counter.eq(reset_counter - 1)
    ).Else(
        ic_reset.eq(0)
    )
self.specials += Instance("IDELAYCTRL", i_REFCLK=ClockSignal("delayrefclk"), i_RST=ic_reset)
```

Its reference is `delayrefclk`, the 300 MHz BUFG output of the `PLLE2_BASE`
(`netv2mvp.py:444`), and the reset sequencer runs in the same domain. Note that
it sits outside the `use_ss` conditional, so it is built either way.

*Observation, marked as such:* `Signal(4, reset=31)` cannot hold 31 — four bits
top out at 15 — and the comment's own arithmetic ("77.5ns @ 400MHz") assumes a
count of 31 at 400 MHz. At the shipped 300 MHz with a truncated count of 15 the
reset is about 50 ns, below the 59.28 ns the comment itself quotes as the
minimum. Whether migen truncates silently here should be confirmed against a
build before the modern CRG copies this construct.

There is one IDELAYCTRL for the whole device, so every `IDELAYE2` in the DDR PHY
and in both HDMI data captures is calibrated against the same 300 MHz reference.

## 5. The DRP interface

Three separate DRP ports are exposed to the CPU, each as a six-register CSR
block with the same shape: `read` and `write` strobes, a `drdy` status bit, a
7-bit address, and 16-bit write and read data.

| Block | CSRs declared | CSR name | Firmware accessors |
|---|---|---|---|
| CRG (DDR data/DQS MMCM) | `netv2mvp.py:308-314`, wired `:411-418` | `crg` (`netv2mvp.py:539-546`) | `crg_mmcm_write` / `crg_mmcm_read`, `legacy/firmware/mmcm.c:641`, `:653` |
| HDMI in 0 MMCM | `clocking.py:96-101`, wired `:152-159` | `hdmi_in0_clocking` | `hdmi_in0_clocking_mmcm_write` / `_read`, `mmcm.c:29`, `:41` |
| HDMI in 0 PLLE2 (`_o`) | `clocking.py:110-113`, wired `:197-204` | same CSR block, `_o` strobes | `hdmi_in0_clocking_mmcm_write_o` / `_read_o`, `mmcm.c:55`, `:67` |
| HDMI in 1 MMCM | `clocking.py:96-101` | `hdmi_in1_clocking` | `hdmi_in1_clocking_mmcm_write` / `_read`, `mmcm.c:187`, `:199` |

The `_o` port shares the address and write-data registers with the master port
(`clocking.py:202-203`) and only the strobe, `drdy` and read-data registers are
duplicated, so firmware must not interleave a master and a slave transaction.

`i_DCLK=ClockSignal()` on every instance means DRP runs in the `sys` domain, at
75 MHz. `drdy` is latched in a small handshake (`netv2mvp.py:420-426`,
`clocking.py:168-174`, `:210-216`): cleared when a read or write strobe fires,
set when the primitive raises `DRDY`. The firmware spins on that bit with a
1,000,000-iteration timeout and prints a diagnostic if it expires
(`mmcm.c:6`, `:33-38`).

### How the firmware reprograms for 720p

`mmcm.c` does not compute register values; it replays captured register dumps.
The order matters:

```c
/* legacy/firmware/mmcm.c:668-670 */
#define S7_MMCM_MAP_LEN  23
// map order comes from xapp888 -- no explanation in docs for why the order is necessary, but it seems important
static int addr_map[S7_MMCM_MAP_LEN] = {0x28, 0x9, 0x8, 0xa, 0xb, 0xc, 0xd, 0xe, 0xf, 0x10, 0x11, 0x6, 0x7,
					0x12, 0x13, 0x16, 0x14, 0x15, 0x18, 0x19, 0x1a, 0x4e, 0x4f};
```

`mmcm_dump_code()` (`mmcm.c:672-...`, reachable from the REPL as `debug mmcm`
via `ci.c:635-638`) reads those 23 addresses back over DRP and prints them as C
array initialisers, with 0x28 forced to `0xffff` because xapp888 requires it
(`mmcm.c:351`, `:683-684`). The printed arrays were then pasted back into the
source as the `_table` functions. Each is 46 entries, address/value interleaved:

```c
/* legacy/firmware/mmcm.c:349, :379-383 — the 720p (60 to 120 MHz) table */
#define MTE 46  // MCM table entries
void hdmi_in_0_config_60_120mhz_table() {
  // hdmi0 MMCM  (bandwidth = OPTIMIZED/HIGH)
  int hdmi0_mmcm_opt[MTE] = {0x28, 0xffff, 0x9, 0x80, 0x8, 0x11c8, 0xa, 0x1186, 0xb, 0x0, 0xc, 0x1042, ...
  // hdmi0 PLLE (bandwidth = HIGH) high reduces output jitter, low maximizes input jitter tolerance
  int hdmi0_plle[MTE] = {0x28, 0xffff, 0x9, 0x0, 0x8, 0x128a, 0xa, 0x41, 0xb, 0x40, 0xc, 0x1082, ...
```

The two loops at `mmcm.c:388-394` write the MMCM table through the master port
and the PLLE2 table through the `_o` port. Registers 0x08 to 0x11 are the
CLKOUT0 to CLKOUT5 divider/phase pairs, 0x14/0x15 the feedback divider, 0x16 the
`DIVCLK_DIVIDE`, 0x18 to 0x1a the lock registers and 0x4e/0x4f the filter
registers — the same set the hand-written `hdmi_in_0_config_60_120mhz()` at
`mmcm.c:89-134` touches individually, with its lock and filter constants
(`mmcm.c:99-107`) and the comment recording the migen parameters they were
derived from. The table form superseded it; only the `_table` variants are
called from `mmcm_config_for_clock` (`mmcm.c:428-432`).

Dispatch is by pixel clock in units of 10 kHz:

| Pixel clock | Function | `mmcm.c` line |
|---|---|---|
| < 3000 (30 MHz) | refused, "Frequency too low for input MMCMs" | `:424` |
| < 6000 (60 MHz) | `hdmi_in_0_config_30_60mhz()` (hand-written, `:81`) | `:426` |
| < 12000 (120 MHz) | `hdmi_in_0_config_60_120mhz_table()` — 720p, 74.25 MHz | `:428` |
| < 24000 (240 MHz) | `hdmi_in_0_config_120_240mhz_table()` — 1080p, 148.5 MHz | `:430` |
| otherwise | refused, "Frequency too high for input MMCMs" | `:432` |

The same ladder runs for `hdmi_in1` at `mmcm.c:436-450`. The MMCM is held in
reset around the rewrite (`mmcm.c:421`, `:434`).

`debug filt <mult> <bw>` (`ci.c:1052-1055`) reaches `set_mmcm0_filt`
(`mmcm.c:834-871`), which recomputes only the 0x4e/0x4f filter fields from a
lookup table and then rewrites the whole 1080p MMCM table. It is a bring-up
tool, not part of normal operation.

Two consequences worth carrying forward: 720p is a **runtime DRP reprogramming
of the 1080p bitstream**, not a separate build; and the tables are opaque
captured values, so a modern rebuild that changes the migen `CLKOUT` parameters
invalidates them silently.

## 6. Timing exceptions

`grep -n "set_false_path\|set_multicycle_path" legacy/netv2mvp.py` returns 23
lines: 22 active platform commands plus one commented-out `set_false_path` at
`:968`. They are all in one block at `netv2mvp.py:928-970`.

The block is founded on three `create_clock` declarations and two
`set_clock_groups`:

| Line | Command | Effect |
|---|---|---|
| `:929-930` | `create_clock -name clk50 -period 20.0` | declares the 50 MHz root; everything downstream is derived by Vivado from the PLL/MMCM settings |
| `:931-932` | `create_clock -name hdmi_in0_clk_p -period 6.734006734006734` | declares HDMI in 0 as a 148.5 MHz root |
| `:933-934` | `create_clock -name hdmi_in1_clk_p -period 6.734006734006734` | same for HDMI in 1 |
| `:937` | `set_clock_groups ... sys_clk vs hdmi_in0_clk_p -asynchronous` | the two trees never meet synchronously |
| `:938` | same for `hdmi_in1_clk_p` | |

The HDMI roots are declared at 148.5 MHz even though the design also runs at
74.25 MHz after a DRP reprogramming. *Inference:* declaring the faster case is
conservative for setup analysis on the derived clocks, and the DRP path is
invisible to static timing anyway.

### The eight `set_false_path` commands

| Line | Path relaxed | Why (inference unless quoted) |
|---|---|---|
| `:941` | `-through [get_nets hdmi_in0_pix_rst]` | reset fan-out; the source comment at `:940` is "don't time the high-fanout reset paths" |
| `:942` | `hdmi_in1_pix_rst` | same, input 1 |
| `:943` | `hdmi_in0_pix1p25x_rst` | same; source marks it "degenerate, throws warning" — the net is optimised away |
| `:944` | `hdmi_in0_pix1p25x_r_rst` | the BUFR-sourced sibling domain's reset |
| `:945` | `hdmi_in1_pix1p25x_rst` | as `:943`, input 1, also marked degenerate |
| `:946` | `hdmi_in1_pix1p25x_r_rst` | as `:944`, input 1 |
| `:947` | `pix_o_rst` | the output-side reset, released by the PLLE2 lock (`clocking.py:228`) |
| `:948` | `soc_videooverlaysoc_s7hdmioutencoderserializer_ce` | source comment: "derived from reset". This is the OSERDESE2 `OCE`, driven by `~ResetSignal("pix_o")` at `legacy/deps/litevideo/litevideo/output/hdmi/s7.py:30` |

The resets are all produced by `AsyncResetSynchronizer` (`clocking.py:221-228`),
so they are asynchronously asserted and synchronously released; timing them
across a domain would be meaningless and would fail.

### The fourteen `set_multicycle_path` commands

They come in seven setup/hold pairs. The idiom throughout is `2 -setup -start`
paired with `1 -hold`, the standard slow-to-fast / fast-to-slow relaxation.

| Lines | From → To | Purpose |
|---|---|---|
| `:951-952` | `hdmi_in0_mmcm_clk1` → `hdmi_in0_mmcm_clk0` | source comment `:950`: "gearbox timing is a multi-cycle path: FAST to SLOW synchronous clock domains". `clk1` is `pix1p25x` (185.625 MHz), `clk0` is `pix` (148.5 MHz); the 8→10 `Gearbox` straddles them (`datacapture.py:458`) |
| `:953-954` | `hdmi_in1_mmcm_clk1` → `hdmi_in1_mmcm_clk0` | same gearbox, input 1 |
| `:956-957` | `hdmi_in0_pix1p25x_r_clk` → `hdmi_in0_mmcm_clk0` | source comment `:955`: "add _r variant (BUFR, same domain, different source)". The BUFR-divided copy of `pix1p25x` carries almost all the capture logic (`datacapture.py:355`, `:374`, `:552`) and is a distinct clock object to Vivado even though it is the same frequency |
| `:958-959` | `hdmi_in1_pix1p25x_r_clk` → `hdmi_in1_mmcm_clk0` | same, input 1 |
| `:961-962` | `hdmi_in0_mmcm_clk0` → `hdmi_in0_pix1p25x_r_clk` | source comment `:960`: "bitslip timing is also multi-cycle path". The reverse direction, `pix` → capture, for the bitslip pulse (`datacapture.py:518`) |
| `:963-964` | `hdmi_in1_mmcm_clk0` → `hdmi_in1_pix1p25x_r_clk` | same, input 1 |
| `:969-970` | `-through [get_nets ...a7ddrphy_oe_dq]` | the DDR DQ tri-state enable. The comment at `:966-968` is explicit that this was originally a `set_false_path` (still present, commented out, at `:968`) and was narrowed to a multicycle: "this should probably be a multi-cycle path and not a straight false_path. May need to adjust if the DQ tri-state timing seems to be a problem" |

Finally, eleven `add_false_path_constraints` calls (the migen helper, which
emits `set_false_path` into the XDC at elaboration time rather than as a literal
string) declare the sys-to-video crossings one pair at a time. The comment at
`netv2mvp.py:841` explains the style: "define path constraints individually to
sysclk to avoid accidentally declaring other inter-clock paths as false paths".

| Lines | Pair |
|---|---|
| `:842-845`, `:846-849`, `:850-853` | `sys` ↔ input 0 `pix`, `pix1p25x`, `pix5x` |
| `:854-857`, `:858-861` | `sys` ↔ input 0 `pix_o`, `pix5x_o` |
| `:863-866` | input 0 `pix_raw` → `sys`, for the frequency meter (comment `:862`) |
| `:914-917`, `:918-921`, `:922-925` | `sys` ↔ input 1 `pix`, `pix1p25x`, `pix5x` |
| `:1226-1229` | `sys` ↔ `eth` |
| `:1249-1252` | `eth` ↔ input 0 `pix_o`, for the I2C snoop into HDCP and the LiteScope path (comment `:1249`) |

Four `create_clock` calls on the DDR DQS input pads are generated in a loop at
`netv2mvp.py:972-978`, naming them `dqsin0` through `dqsin3` at a 2.5 ns period.

## 7. CMT budget

An Artix-7 CMT contains one MMCM and one PLL. The XC7A35T has 5 CMTs; the
XC7A100T has 6.

| Consumer | MMCME2_ADV | PLLE2 |
|---|---|---|
| CRG — DDR data/DQS | 1 | |
| CRG — DDR address/control | 1 | |
| CRG — IDELAY reference | | 1 (`PLLE2_BASE`) |
| HDMI in 0 | 1 | 1 (`PLLE2_ADV`, only because `split_mmcm=True`) |
| HDMI in 1 | 1 | |
| HDMI out 0 | 0 | 0 |
| **Total** | **4** | **2** |

That is 4 of 5 MMCMs and 2 of 5 PLLs on the 35T: one spare MMCM, three spare
PLLs. It matches the figure in the design spec, section 3.

The output has no CMT of its own because the top level does not instantiate
`S7HDMIOutClocking` (which does contain an `MMCME2_ADV`, at
`legacy/deps/litevideo/litevideo/output/hdmi/s7.py:77-124`, and assumes a
100 MHz base clock). Instead it instantiates only the serialiser and PHY and
renames their domains onto input 0's `pix_o`/`pix5x_o`:

```python
# legacy/netv2mvp.py:869-871
self.submodules.hdmi_out0_clk_gen = ClockDomainsRenamer({"pix":"pix_o", "pix5x":"pix5x_o"})(S7HDMIOutEncoderSerializer(hdmi_out0_pads.clk_p, hdmi_out0_pads.clk_n, bypass_encoder=True))
self.submodules.hdmi_out0_phy = ClockDomainsRenamer({"pix":"pix_o", "pix5x":"pix5x_o"})(S7HDMIOutPHY(hdmi_out0_pads, mode="raw"))
```

This is the structural reason the output is genlocked to input 0 and cannot free-run:
the output pixel clock is a PLL multiple of the input pixel clock, sourced
uncompensated from `mmcm_clk0` "for best phase match between master/slave"
(`clocking.py:190-192`). Any modern design that wants a self-timed output has to
add a CMT, which is what pushes the 35T to 5 of 5 MMCMs (design spec, section 4.4).

`pix5x_o` is on a BUFG rather than a BUFIO because a `PLLE2` output cannot drive
a BUFIO (`clocking.py:207`). A 742.5 MHz clock on a global buffer is the tightest
clock-tree constraint in the design.
