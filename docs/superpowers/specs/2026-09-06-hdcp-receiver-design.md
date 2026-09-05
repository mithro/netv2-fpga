# NeTV2 HDCP 1.x receiver: design

Status: v1, 2026-09-06. Author: Claude (Fable 5.1) for Tim Ansell (mithro). Branch `phase1-baseline`.

Inputs: `~/netv2-hdcp-handoff/{docs/NETV2-HDCP-RECEIVER-BRIEF.md, hdcp/REGISTERS.md, hdcp/FINDINGS.md,
hdcp/keygen.py, KEYS_NOTE.txt, STATUS.md}`; `legacy/overlay/*.v`; `legacy/netv2mvp.py`;
`legacy/firmware/{ci.c,km.c}`; `docs/original/gateware.md` §3-4 and `docs/original/firmware.md` §6; the
schematic `~/github/AlphamaxMedia/netv2-mainboard/netv2mvp-pvt1.pdf`; and the public HDCP 1.4 spec
(Rev 1.4, 8 July 2009, DCP LLC), Tables 2-2, 2-4, 4-8, 4-9, 4-11 and receiver states B0-B3. Claims
about existing code cite `legacy/<file>:<line>`; schematic claims cite the PDF page. Inferences are
marked **(inferred)**.

## 0. Corrections to the brief

Three statements in the handoff are wrong about the existing code, and they change the shape of the work.

1. **`hdcp_mod.v` is not a decryptor.** `cipher_stream` is XORed only into the *overlay* encoder inputs
   (`legacy/netv2mvp.py:1070-1091`), gated on `hdcp.Km_valid.storage`, while the passthrough path carries
   the source's raw 10-bit TMDS characters untouched (`:1102-1126`). The 2019 design *re-encrypts overlay
   pixels into the source's keystream* so a substituted pixel decrypts correctly at the real sink; it
   never produces plaintext anywhere (`docs/original/gateware.md:531-545`). Brief DoD 3 (a clean capture)
   therefore needs **new** gateware — §11.4. `hdcp/REGISTERS.md:55` describes the overlay XOR, not a
   decrypt.
2. **R0/Ri exist nowhere today.** `hdcp_cipher.v` captures only `ostream[15:0]` into `Mi`
   (`legacy/overlay/hdcp_cipher.v:414-427`) and discards `ostream[23:16]`, which is exactly where Ri
   lives (HDCP 1.4 Table 4-11). The cipher must be patched — §5.
3. **The legacy CPU `Km` path cannot be reused with the keygen.py keys.** `legacy/firmware/km.c:82-83`
   derives both key sets from `compute_ksv.c`'s real 40x40 DCP master matrix; `hdcp/keygen.py` uses a
   different, symmetric matrix we own. They never agree, so `km_source` must be 1 (hardware Km). This
   also puts `compute_ksv.c` out of scope (§12).

Smaller point: the receiver "reuses `hdcp_cipher.v`" as the *same single instance* already inside
`hdcp_mod`, not a second copy — one cipher serves keystream, R0 and Ri.

## 1. Architecture

### 1.1 The DDC circuit as built (schematic page 5, `05io.SchDoc`)

The override is **both a pull-down and a pull-up**; only the pull-down is safe.

| Net | FPGA pin | Circuit (page 5) |
|---|---|---|
| `DDC_SDA_PD` | F20 = `hdmi_sda_over_dn` (`legacy/netv2mvp.py:174`) | gate of Q12H (BSS138, N-ch), R20H 1k gate pull-down; source GND; drain through **R18H 39R 1%** to `DDC_SDA`. Open-drain: asserting pulls SDA low through ~39R. |
| `DDC_SDA_PU` | G20 = `hdmi_sda_over_up` (`:173`) | gate of Q11H (BSS138, R17H 1k); Q11H drain pulls the gate of **Q10H (BSS84, P-ch)** down against R16H 1k to P5.0V. Q10H source = P5.0V, drain = `DDC_SDA` **directly, no series resistor**: asserting it *hard drives SDA to 5 V*. |
| `DDC_SDA` -> FPGA | V18 = `DDC_SDA_LV_N` (page 3) | via U10HD, a 74AHC14PW **inverting** Schmitt buffer (pin 13 in, 12 out). Hence `i_SDA=~pads.sda` (`legacy/netv2mvp.py:641`). |
| `DDC_SCL` -> FPGA | T18 = `DDC_SCL_LV_N` (page 3) | via U10HC, same part. Hence `i_SCL=~pads.scl` (`:642`). **The FPGA cannot drive SCL at all.** |
| bus bias | — | R49H, R50H 47k 1% from `TX_HDMI_5V` to `DDC_SCL`/`DDC_SDA`. Bias only; the real DDC pull-ups are on the source. |
| `HDMI_HPD` | U17 = `HDMI_HPD_LL_N`, `Inverted()` (`:148`) | pass-through from the downstream sink with overrides: Q15H (BSS138, gate `RX0_FORCEUNPLUG` = M22) pulls HPD to GND; Q13H (BSS84) via Q14H/R27H (gate `RX0_FORCEPLUG` = N22) drives HPD from `TX_HDMI_5V` through R32H 39R. `hdcp.hpd_ena` drives only `RX0_FORCEUNPLUG` (`:1060`). |

**The input0 DDC bus is passed through to the output0 connector.** Page 5 shows two 3-pin headers —
P11H (1 = `DDC_SCL`, 2 = `DDC_SCL_SRC`, 3 = `TX0_SCL`) and P14H (1 = `DDC_SDA`, 2 = `DDC_SDA_SRC`,
3 = `TX0_SDA`) — with shorting headers NT10H/NT11H annotated "**Both default in 1-2 position**", and
`DDC_*_SRC` are pins 15/16 of the HDMI-A *source* connector. So by default the Pi, the NeTV2 and the
downstream sink share one physical DDC bus. Hence our slave must **never ACK anything but 0x74/0x75**
(the downstream EDID at 0x50 must keep reaching the Pi, or it emits no video), and a real HDCP sink
downstream would also ACK 0x74 and wire-AND its read data with ours (§2.9, §11.1).

Non-negotiable: **`hdmi_sda_over_up` (G20) stays tied to 0** — a hard 5 V push into a bus other devices
pull low. The original ties both to 0 (`legacy/netv2mvp.py:874-877`); we take over only `_dn`.

### 1.2 Block diagram

```
 HDMI in0 (J11H) --- DDC_SCL/DDC_SDA ---[P11H/P14H shorted 1-2]--- HDMI out0 (sink EDID @0x50)
      |                                    ^  F20 = DDC_SDA_PD -> Q12H(BSS138) -> R18H 39R -> SDA low
   74AHC14 inverting buffers: T18 = DDC_SCL_LV_N, V18 = DDC_SDA_LV_N
      v                                    |
 +----------------------------------------------------------------------------+
 | eth, 50 MHz                                                                 |
 |  i2c_snoop.v (UNCHANGED)         hdcp_rx.v (NEW)                            |
 |   passive; An[63:0];              I2C slave @0x3A (0x74 wr / 0x75 rd)       |
 |   Aksv14_write;                   register file 0x00..0x44                  |
 |   edid_snoop_adr/dat CSR          sda_drive_low -------------------------->-+
 |                                   Aksv[39:0], An[63:0], Ainfo               |
 |                                   40x56 sink-key RAM (CSR loaded)           |
 |                                   Km accumulator (40 cyc) -> auth_start     |
 +-------------------------|------------------------------|-------------------+
       Km_hw, An, auth_start|         R0, Ri_ddc, frame_i, |auth_state
       (PulseSynchronizer)  v         (BusSynchronizer)    |
 +----------------------------------------------------------------------------+
 | pix_o, 74.25 / 148.5 MHz                                                    |
 |  HDCPReceiver mux: Km/An/trigger = km_source ? hdcp_rx : legacy CSR+snoop   |
 |  hdcp_mod_rx.v    (PATCHED: +R0, +Ri_ddc, +frame_i, +auth_state)            |
 |   +- hdcp_cipher_rx.v (PATCHED: +Ri[15:0], +ri_valid, +ri_is_r0)            |
 |       +- hdcp_block.v, hdcp_lfsr.v (UNCHANGED)                              |
 |  cipher_stream[23:0] -> overlay encoder XOR (unchanged, netv2mvp:1070)      |
 +----------------------------------------------------------------------------+
       ^ sys CSRs: keys, bksv, rx_enable, km_source, km_hw, r0, ri,
         frame_count, frame_offset, status
```

### 1.3 New files

| Path | Contents |
|---|---|
| `netv2/gateware/hdcp/hdcp_rx.v` | I2C slave + register file + key RAM + Km accumulator |
| `netv2/gateware/hdcp/hdcp_mod_rx.v` | patched copy of `legacy/overlay/hdcp_mod.v`, module renamed |
| `netv2/gateware/hdcp/hdcp_cipher_rx.v` | patched copy of `legacy/overlay/hdcp_cipher.v`, renamed |
| `netv2/gateware/hdcp/__init__.py` | `HDCPReceiver(Module, AutoCSR)` |
| `legacy/netv2mvp_hdcprx.py` | bridge top level (§9) |
| `netv2/hdcp/cipher.py` | Python reference model — **another agent's file, not touched here** |

`hdcp_block.v`, `hdcp_lfsr.v`, `diff_network.v`, `shuffle_network.v` and `i2c_snoop.v` are reused
unmodified from `legacy/overlay/`; the two cipher files are *renamed copies* so the original and the
receiver variant coexist in one build and the `netv2mvp.py` baseline stays bit-comparable.

### 1.4 Extend `i2c_snoop.v`, or add a parallel slave?

**Decision: parallel slave. `i2c_snoop.v` stays byte-identical.**

The snooper is an attractive base: proven SCL/SDA deglitch FSMs (`legacy/overlay/i2c_snoop.v:443-605`,
`TRF_CYCLES = 5'd8` at `:74`), a 14-state protocol FSM (`:79-203`), address match on `[7:1]` so 0x74
and 0x75 both hit (`:150`), `I2C_WAITSTOP` for foreign addresses (`:195-201`), and ACK states with the
right timing and bunnie's own comment "trigger the ack response (pull SDA low until next falling edge)"
(`:169-170`) — clearly written with a slave in mind. But its register file is only 32 bytes
(`RAM_ADDR_BITS = 5`, `:407`, `:429`), so 0x40 aliases onto 0x20 and Bcaps/Bstatus cannot be decoded;
its read path shifts `I2C_rdata` on **SCL rising** (`:334-344`), correct for snooping but wrong for a
slave transmitter, which must change SDA while SCL is low — a structural rewrite of the read branch;
and its write bound `< 0x20` (`:419`) and read cache `< 0x5` (`:420`) are behaviour the existing `km`
firmware depends on (`legacy/firmware/km.c:72-80`). Leaving it untouched preserves the shipping overlay
path and the `i2c_snoop.An`/`Aksv14_write` wiring at `legacy/netv2mvp.py:1045-1058` exactly, so a bug in
the new module cannot regress 2019 behaviour. `hdcp_rx.v` therefore *copies* the snooper's SCL/SDA
sampling blocks verbatim and adds a new protocol FSM, at a cost of ~60 FFs (§11.3). The two FSMs observe
the bus independently; because the snooper is passive a disagreement can only corrupt the snoop, and
comparing `hdcp_rx.an` against `i2c_snoop.An` becomes a built-in self test.

## 2. I2C slave details

7-bit address **0x3A** (`0x74` write, `0x75` read); compare `daddr[7:1] == 7'h3A` as `i2c_snoop.v:150`
does. Secondary link 0x76 not implemented.

**2.1 Sampling.** All logic in the **`eth` domain, 50 MHz**. Two-stage synchronisers on SCL and SDA
(copied from `legacy/overlay/i2c_snoop.v:612-624`, plus `ASYNC_REG="TRUE"`), then the 4-state rise/fall
FSMs with `TRF_CYCLES = 8` (`:74`) giving a 160 ns deglitch; at 100 kHz the shortest bus interval is
4.7 us, ~30x margin. Inputs are inverted by the board's 74AHC14, so the instance takes `~pads.scl` /
`~pads.sda` exactly as `legacy/netv2mvp.py:641-642`.

**2.2 Start / stop / repeated start.** Reused unchanged: stop = SDA rising while SCL high, which resets
the FSM to `I2C_START` (`:130-135`); start = SDA falling while SCL high (`:140`); repeated start detected
inside the data states (`:166`, `:179`).

**2.3 ACK generation.** `sda_drive_low` (driving `hdmi_sda_over_dn` high -> Q12H on -> SDA to ground
through R18H) is asserted in `I2C_ACK_DADDR` when `daddr[7:1] == 7'h3A && rx_enable_eff`; in
`I2C_ACK_ADDR` and `I2C_ACK_WR` unconditionally (we are addressed); and in `I2C_RD_DATA` when the
current shift bit is 0. Timing: the FSM enters `I2C_ACK_*` **on the SCL falling edge following the 8th
bit** (`:146`, `:158`, `:167`) and leaves on the next SCL falling edge (`:149`, `:161`, `:171`), so
driving low for exactly that state satisfies I2C — SDA goes low after SCL falls, with ~3.2 us of setup
before SCL rises at 100 kHz (allowing the 160 ns deglitch), and is released after the 9th falling edge.
The address match must be evaluated **combinationally** inside `I2C_ACK_DADDR`, because the snooper only
uses the match in its *next-state* logic (`:149-153`) whereas a slave must decide during the ACK bit
itself; `daddr` is fully shifted by then (last shift on the 8th rising edge, `:234-248`).

**2.4 Read data driving.** The snooper's rising-edge read shift (`:334-344`) is replaced. On entering
`I2C_RD_DATA` (from `I2C_ACK_DADDR` on a 0x75 match, or from `I2C_ACK_RD`), load
`rd_shift <= regfile[reg_ptr]` and present `rd_shift[7]`; `sda_drive_low = (state == I2C_RD_DATA) &&
!rd_shift[7]`, so SDA is only ever pulled low and a `1` is left to the bus pull-up. The shift is
**qualified on the SCL falling-edge state** (`SCL_cstate == SCL_FALL`), *not* on every `eth` cycle — the
mirror image of the snooper's `SCL_cstate == SCL_RISE` guard on its own read shift
(`legacy/overlay/i2c_snoop.v:333-345`) — so data changes exactly once per bit, while SCL is low. After 8
bits enter `I2C_ACK_RD`, release SDA and sample it on the SCL rising edge (`:184`): low = ACK ->
auto-increment and continue; high = NACK -> back to `I2C_START`.

**2.5 Clock stretching: not used and not possible.** SCL (T18) is an FPGA *input* only and there is no
`DDC_SCL_PD` net on the board (page 5). Every response is combinational out of registers, and the one
multi-cycle operation — the 40-cycle Km accumulation, 800 ns — fits inside one 10 us SCL low period.

**2.6 Register pointer.** One 8-bit `reg_ptr`, set by the address byte after a 0x74 write, incremented
after every byte written or read (mirroring `:324` and `:363`), wrapping at 0xFF. A repeated start does
not clear it — that is what makes the standard `write ptr, Sr, read` combined transfer (HDCP 1.4
Figure 2-11) work. It persists across transactions as `I2C_addr` does at `:212`.

**2.7 Foreign addresses.** If `daddr[7:1] != 7'h3A` the FSM goes to `I2C_WAITSTOP` (`:152`) and
`sda_drive_low` is held 0 until a stop or repeated start, so **EDID at 0x50 is never touched** and the
downstream sink's EDID keeps reaching the Pi (§1.1).

**2.8 Reset.** `ResetSignal("eth")` resets the FSMs. `rx_enable` is 0 by CSR default, so the slave is
inert at power-on and a bitstream load cannot disturb the DDC bus. Bksv and the key RAM come up zero and
`keys_loaded` = 0; the wrapper computes `rx_enable_eff = rx_enable & (keys_loaded == 40)` so a
half-loaded key set can never produce a wrong R0'. Per HDCP 1.4 transition B1:B1, writing the last Aksv
byte during a computation abandons and restarts it — `hdcp_rx` re-arms the accumulator on every
`aksv14_write`; Ainfo resets to 0 on that write (Table 2-2, offset 0x15).

**2.9 If the downstream sink also answers 0x74.** Both slaves ACK (both pull low — harmless), but on a
read both drive and the bus wire-ANDs, so Bksv and R0' come back as the bitwise AND of two devices and
authentication fails. **Documented limitation.** The supported configuration is a non-HDCP device
downstream — the MS2109 capture card is not HDCP (`hdcp/FINDINGS.md:35`). Removing the downstream device,
or moving NT10H/NT11H to 2-3, both cut EDID and HPD and leave the Pi emitting no video. STATUS.md open
question 1 asks the RPi side to confirm the MS2109 is the only other device on the bus; that answer is a
precondition for the hardware run.

## 3. Register map

Little-endian multi-byte (HDCP 1.4 §2.6). Anything not listed reads 0x00. Writes to read-only offsets are ACKed and discarded (the spec has no NACK for this).

| Offset | Name | Size | R/W | Value / behaviour | CSR |
|---|---|---|---|---|---|
| 0x00 | Bksv | 5 | Rd | from the `bksv` CSR (KSV_sink, 20 ones / 20 zeros) | `bksv` RW |
| 0x08 | Ri' | 2 | Rd | latched R0', then Ri' (§5) | `r0`, `ri` RO |
| 0x0A | Pj' | 1 | Rd | 0x00 — 1.1_FEATURES is 0, Pj never updated | — |
| 0x10 | Aksv | 5 | Wr | stored; the write to **0x14** triggers auth | `aksv_rx` RO |
| 0x15 | Ainfo | 1 | Wr | stored, **no-op**; cleared on the 0x14 write | `ainfo_rx` RO |
| 0x18 | An | 8 | Wr | stored, feeds the cipher | `an_rx` RO |
| 0x20-0x33 | V'.H0-H4 | 20 | Rd | 0x00 — repeater only, out of scope | — |
| 0x40 | Bcaps | 1 | Rd | **0x80** | — |
| 0x41 | Bstatus | 2 | Rd | **0x1000** (LE: 0x00 at 0x41, 0x10 at 0x42) | — |
| 0x43 | KSV FIFO | 1 | Rd | 0x00 (REPEATER == 0, Table 2-2) | — |
| 0x05, 0x0B, 0x16, 0x34, 0x44+ | Rsvd | | Rd | 0x00; 0xC0 dbg not implemented | — |

Bcaps 0x80 sets only bit 7 HDMI_RESERVED. REPEATER = 0, READY = 0, **FAST = 0** (100 kHz only — the
shared bus carries an unknown EDID ROM and the spec forbids 400 kHz unless every device supports it),
1.1_FEATURES = 0 (no Advance Cipher, no Pj, no Enhanced Link Verification), FAST_REAUTHENTICATION = 0.
Bstatus 0x1000 sets HDMI_MODE (bit 12, Table 2-4), asserted statically rather than derived from
`decode_terc4` data-island activity because the Pi is known to drive HDMI mode; deriving it is a
possible refinement. **(inferred** that static is safe: the spec only requires the bit be clear when no
data island has been seen in 30 frames, which a transmitter cannot police.**)** 0x0A is present as an
always-zero read because `STATUS.md:26-29` lists it and a transmitter may auto-increment 0x08..0x0B.

## 4. Km computation

**4.1 Key storage.** 40 x 56-bit sink keys, declared 64 deep for a clean 6-bit index:
`(* RAM_STYLE = "distributed" *) reg [55:0] sink_keys [0:63];`. Distributed (LUTRAM), **not BRAM** — this
is a hard requirement, not a preference: the 2019 overlay baseline already uses 47.5 of 50 BRAM36
(95%, §11.3), leaving only 2.5 blocks free, so a BRAM key store risks pushing the design over. 2240 bits
of LUTRAM is cheap by comparison.

**4.2 CSR interface** (`HDCPReceiver`, `sys` domain). Note `csr_data_width = 8`
(`legacy/deps/litex/litex/soc/integration/soc_core.py:128`), so a 56-bit CSRStorage occupies 7 byte-wide
addresses, MSB first — the layout `legacy/firmware/km.c:154-162` already walks for `Km`.

| CSR | Type | Purpose |
|---|---|---|
| `key_index`/`key_lo`/`key_hi` | Storage(6/32/24) | one key; `key_we`, `keys_clear` are `CSR()` strobes |
| `keys_loaded` | Status(6) | distinct indices written |
| `bksv` | Storage(40) | KSV_sink |
| `rx_enable` / `km_source` | Storage() | arm the slave / 0 = CPU `hdcp.Km`, 1 = hardware Km |
| `frame_offset` | Storage(8) | trim the frame index (§5.3) |
| `km_hw`; `aksv_rx`/`an_rx`/`ainfo_rx` | Status(56; 40/64/8) | computed Km; what the source wrote |
| `r0` / `ri` / `frame_count` | Status(16) | §5 |
| `status` | Status(8) | `{auth_state[3:0], km_valid_hw, keys_ok, sda_driving, rx_armed}` |
| `i2c_txn_count` | Status(16) | transactions to 0x74/0x75 — a liveness counter |

`key_we.re` crosses to `eth` via `PulseSynchronizer`; `key_index/lo/hi` are quasi-static and sampled on
the synchronised pulse. The RAM write port is gated on `~rx_enable.storage`, so a mid-session load
cannot corrupt an in-flight authentication.

**4.3 The accumulator.**

```
on aksv14_write (last Aksv byte, offset 0x14):
    km_acc <= 0; idx <= 0; km_valid_hw <= 0; state <= KM_RUN
KM_RUN (40 cycles):
    if (aksv[idx]) km_acc <= (km_acc + sink_keys[idx]) & 56'hff_ffff_ffff_ffff
    idx <= idx + 1; if (idx == 39) state <= KM_DONE
KM_DONE:
    km_hw <= km_acc; km_valid_hw <= 1; auth_start <= 1; state <= IDLE
```

56-bit truncating add, matching `hdcp/keygen.py:55` (`& MASK`, MASK = 2^56-1) and
`legacy/firmware/km.c:96-97`. 40 cycles at 50 MHz = 800 ns. Distributed RAM reads are asynchronous, so
no extra pipeline stage; if timing needs one it becomes 41 cycles.

**4.4 The trigger.** Aksv occupies 0x10..0x14 and **0x14 is the last byte**. `i2c_snoop.v` already
strobes on exactly this (`legacy/overlay/i2c_snoop.v:391-401`: `I2C_addr == 8'h14 && I2C_cstate ==
I2C_ACK_WR`) and `hdcp_mod.v:169-170` forces `HDCP_AUTH_PULSE` on it. `hdcp_rx.v` reproduces the
condition on its own FSM but does **not** forward the strobe directly: Km must be valid before the
cipher starts, so `auth_start` is emitted at `KM_DONE`, 40 cycles later, with `km_hw` and `an` already
stable. This is why the unreachable `HDCP_WAIT_KMRDY` state (`hdcp_mod.v:190-192`) is *not* re-enabled —
delaying the strobe achieves the same without touching the proven FSM topology.

## 5. R0 / Ri source

### 5.1 Where they live (HDCP 1.4 Tables 4-8, 4-9, 4-11)

`hdcpBlockCipher` is: load B/K; **48** block clocks; save the low 56 bits of B as Ks/Ki; B->K; reload B;
init LFSR; assert rekey; **56** warm-up clocks; de-assert rekey. During the last four warm-up clocks
(Table 4-11): clock 53 gives Mi[63:48] and 54 Mi[47:32] from `output[15:0]`; clock 55 gives Mi[31:16]
and `ri[15:8]` from `output[23:16]`; clock 56 gives Mi[15:0] and `ri[7:0]`. At authentication the
outputs are (R0, M0); at each vertical blank they are (Ri, Mi) (Table 4-9).

In the Verilog the 48 clocks are `BLOCK_2` (`legacy/overlay/hdcp_cipher.v:159`, `statecnt >= 6'd47`),
the 56 warm-up clocks are `BLOCK_8` (`:177`, `statecnt >= 6'd55`), and `Mi` shifts 16 bits per clock
from `ostream[15:0]` while `cstate` is `BLOCK_8`, `BLOCK_9` or `GET_M` (`:414-427`). `ostream` is
`hdcp_block`'s registered output function (`legacy/overlay/hdcp_block.v:39`, `:123`, bits at
`:680-726`). **`ostream[23:16]` is discarded**, so the patch mirrors the `Mi` shift exactly:

```verilog
   reg [15:0] Ri_r;
   always @(posedge clk or posedge reset)
     if (reset) Ri_r <= 16'b0;
     else if ((cstate == BLOCK_8) || (cstate == BLOCK_9) || (cstate == GET_M)) begin
        Ri_r[15:8] <= Ri_r[7:0];
        Ri_r[7:0]  <= ostream[23:16];
     end
```

Same window and cadence as `Mi`, so the last two captures land in the clocks that produce Mi[31:16] and
Mi[15:0] — warm-up clocks 55 and 56 — giving `Ri_r[15:8] = ri[15:8]` and `Ri_r[7:0] = ri[7:0]`, exactly
Table 4-11. New `hdcp_cipher_rx` outputs: `Ri[15:0] = Ri_r`, `ri_valid` (one cycle on the
`GET_M -> STREAM` transition), and `ri_is_r0 = auth_mode` sampled at that instant. `Ri_r` is stable from
the first `STREAM` cycle, one cycle before `stream_ready` asserts (`:372`).

The correctness of this two-clock capture window (that 55/56 and not 53/54 are the clocks that carry
`ri`) is **not** proven by inspection — it is proven by tb #2 (§10.2): a `R0' == model R0` match confirms
the window; a mismatch means the window is wrong (off by a clock, or the wrong `ostream` slice), **not**
that the reference model is wrong. The model is the oracle, so triage a failure by shifting the capture
window, never by editing the model.

### 5.2 R0 versus Ri — the trap

`hdcp_mod.v` runs the cipher **twice** back to back at authentication: `HDCP_AUTH_PULSE` with
`auth_mode = 1` (`:312-316`) produces (Ks, M0, R0), then `HDCP_AUTH_VSYNC_PULSE` with `auth_mode = 0`
(`:328-332`) immediately produces (K1, M1, R1). The cipher's live Ri register therefore holds **R1, not
R0**, a microsecond later. R0 must be latched inside `hdcp_mod_rx.v`, in `pix_o`, at
`ri_valid & ri_is_r0`:

```verilog
   always @(posedge clk)
     if (rst | hpd) begin R0 <= 0; Ri_ddc <= 0; frame_i <= 0; end
     else if (ri_valid) begin
        if (ri_is_r0) begin R0 <= Ri; Ri_ddc <= Ri; frame_i <= 16'd0; end
        else begin
           frame_i <= frame_i + 16'd1;
           if ((((frame_i + 16'd1) + frame_offset) & 16'd127) == 16'd0) Ri_ddc <= Ri;
        end
     end
```

That is the whole of HDCP 1.4 states B1->B2->B3: Ri' holds R0' from the end of the authentication
computation and is replaced only when (i mod 128) == 0 (Table 2-2 offset 0x08, state B3).

### 5.3 Frame counting and EESS

`hdcp_mod` counts frames by running one `hdcpBlockCipher` per vertical blank: `vsync_rising`
(`legacy/overlay/hdcp_mod.v:74-79`) drives `HDCP_READY -> HDCP_VSYNC_PULSE` (`:264`), which pulses
`hdcp_init` (`:355-359`). Before returning to `HDCP_READY` it waits for the EESS marker in
`HDCP_WAIT_1001`/`HDCP_WAIT_1001_END` (`:235-242`): `vsync && ctl_code == 4'b1001`, with `ctl_code` from
`hdmi_in0.decode_terc4.ctl_code` (`legacy/netv2mvp.py:1058`). So the index advances once per encrypted
frame, synchronised to the source's encryption-status signalling. Index alignment with the transmitter is
the genuinely uncertain part, and `hdcp_mod.v:220-232` says so in bunnie's own words ("I don't know if
there is more than 1 vsync period between the conclusion of auth and the first 1001 assertion"). The
counter above assumes the `HDCP_AUTH_VSYNC` run is i = 1; `frame_offset` (CSR, reset 0) trims it without a
rebuild, and `frame_count` is exported so the offset can be swept against the Pi's `CP_INTEGRITY`.

### 5.4 Latching for a stable DDC read

`Ri_ddc` (pix_o) crosses to `eth` through a 16-bit `BusSynchronizer` (req/ack toggle). `hdcp_rx.v` holds
a further copy refreshed only between I2C transactions (`state == I2C_START`), so both bytes of one read
come from a single consistent Ri — a mid-read update would look to the transmitter like a link failure.

### 5.5 Latency, Aksv to R0' valid

Last Aksv bit to `aksv14_write` ~3 eth cycles (60 ns); Km accumulation 40 eth cycles (800 ns);
`auth_start` PulseSynchronizer 3 pix_o cycles (40 ns @ 74.25 MHz); cipher 1 + 48 + 3 + 1 + 1 + 56 + 1 + 1
= 112 pix_o cycles (1.51 us @ 74.25 MHz); R0 latch and BusSynchronizer back to `eth` ~4 cycles (100 ns).
**Total ~2.6 us.** Worst case at the rig's lowest pixel clock (25.2 MHz, 480p) is ~6 us, against a 100 ms budget (state B1,
Table 2-2 offset 0x08) — four orders of magnitude of margin. The transmitter is in fact *forbidden* from
reading R0' sooner than 100 ms after writing Aksv (state A3), so the receiver is never the limiting
party. The real hazard is that all of this runs in `pix_o`, which exists only when the input0 MMCM is
locked (`legacy/deps/litevideo/litevideo/input/clocking.py:194-228`): if the Pi writes Aksv before video
is up, no R0 is produced. `status` exports a `pix_o` heartbeat so the firmware can report it; recovery is
an HPD pulse via `hdcp.hpd_ena` after lock.

## 6. Km path selection

`km_source` (CSRStorage, `sys`, default 0):

| `km_source` | Km | An | cipher trigger | `Km_valid` |
|---|---|---|---|---|
| 0 (legacy) | `hdcp.Km.storage` | `i2c_snoop.An` | `Aksv14_write` (`legacy/netv2mvp.py:1050-1053`) | `hdcp.Km_valid.storage` |
| 1 (receiver) | `km_hw` | `hdcp_rx.an` | `auth_start` (§4.4) | `km_valid_hw & rx_enable_eff` |

The mux is in `pix_o` inside `HDCPReceiver`; `km_source` is quasi-static and `MultiReg`'d in, and
switching it while authenticated is undefined — the firmware sets it once at init. In hardware mode
`Km_valid` is asserted by the gateware at `KM_DONE` and cleared on `hpd`, on `rx_enable` falling, and on
every new `aksv14_write` (transition B1:B1); note it also gates the overlay XOR
(`legacy/netv2mvp.py:1072`, `:1082`), so asserting it turns overlay re-encryption on, which is correct
once authenticated. `Aksv_mode`/`Aksv_manual` (`:673-674`, `:689-697`) are unchanged and still select
between the snooper strobe and a CSR pulse **within** `km_source == 0`; when `km_source == 1` they are
bypassed entirely. The existing `hdcp_init()` sets `Aksv_mode = 1` (`legacy/firmware/km.c:37`), which
then becomes irrelevant; `hdcp status` prints both so the state is never ambiguous.

## 7. Clock domains and CDC

`eth` 50 MHz (I2C, Km, key RAM); `pix_o` 74.25/148.5 MHz (cipher, R0/Ri, frame counter); `sys` 100 MHz (CSRs).

| # | From -> to | Signals | Mechanism |
|---|---|---|---|
| 1 | pads -> `eth` | SCL, SDA | 2-FF sync with `ASYNC_REG`, then the `TRF_CYCLES = 8` deglitch FSMs (`legacy/overlay/i2c_snoop.v:443-624`) |
| 2 | `sys` -> `eth` | `key_index/lo/hi`, `key_we` | `PulseSynchronizer` on `key_we.re`; data quasi-static, sampled on the pulse |
| 3 | `sys` -> `eth`/`pix_o` | `bksv`, `rx_enable`, `km_source`, `frame_offset` | `MultiReg` per bit; quasi-static, written only while disarmed |
| 4 | `eth` -> `pix_o` | `km_hw[55:0]`, `an[63:0]` | held stable >= 8 `eth` cycles before the strobe, captured in `pix_o` on the synchronised `auth_start`; buses false-pathed |
| 5 | `eth` -> `pix_o` | `auth_start` | `PulseSynchronizer` |
| 5b | `eth` -> `pix_o` | `km_valid_hw` | single-bit level, its own `MultiReg` (it gates the `pix_o` cipher's `Km_valid`, §6) |
| 6 | `pix_o` -> `eth` | `R0`, `Ri_ddc`, `frame_i`, `auth_state` | `BusSynchronizer` per bus — never bit-wise `MultiReg`, or a read could tear |
| 7 | `pix_o` -> `sys` | same, for CSRStatus | `MultiReg` off the already-stable `eth` copies |
| 8 | `eth` -> `sys` | `km_hw`, `an_rx`, `aksv_rx`, counters | `BusSynchronizer` for wide buses, `MultiReg` for single bits |

The `eth <-> pix_o` false path already exists (`legacy/netv2mvp.py:1249-1252`). The bridge adds the
equivalent for the new `eth <-> sys` and `pix_o <-> sys` buses — verified by reading the generated XDC,
not assumed.

## 8. Firmware and host tooling

**8.1 `hdcp` command group.** A new `legacy/firmware/hdcp_rx.c` with a hook in `ci.c`'s dispatcher
alongside the existing `km` / `hpdforce` / `hpdrelax` tokens (`legacy/firmware/ci.c:1101-1106`):
`hdcp status`; `hdcp keyload <idx> <hi24hex> <lo32hex>`; `hdcp keyclear`; `hdcp bksv <10hex>`;
`hdcp rx on|off` (sets `rx_enable` and `km_source` together); `hdcp foffset <n>`; `hdcp hpdpulse <ms>`
(assert then release `hpd_ena` to force re-auth). `hdcp status` output, one `key: value` per line with
stable field names so a test can regex them:

```
hdcp rx: enabled
hdcp km_source: hw
hdcp keys_loaded: 40
hdcp bksv: 59cabe3384
hdcp aksv_rx: 108df2b8de
hdcp an_rx: 46b6537884e56c78
hdcp ainfo_rx: 00
hdcp km_hw: f26625c3367e6e
hdcp km_valid: 1
hdcp r0: a1b2
hdcp ri: a1b2
hdcp frame: 384
hdcp foffset: 0
hdcp auth_state: HDCP_READY
hdcp i2c_txns: 17
hdcp sda_driving: 0
hdcp pixo_alive: 1
```

`auth_state` decodes the one-hot `HDCP_cstate` (`legacy/overlay/hdcp_mod.v:108-124`) to its parameter
name; every value is read live from CSRs. The REPL contract (`scripts/gen_repl_contract.py`) is
regenerated so `tests/hardware/hosts.py`'s allowlist knows the new tokens; `hdcp keyload` carries secret
material over the console, so it is added to the golden-unit allowlist explicitly and never logged.

**8.2 Host-side loader.** `tests/hdmi-suite/hdcp/netv2_load_sink_keys.py`, **Python 3.5 compatible** (the
golden unit `rpi3-netv2` runs an old Raspbian: no f-strings, no `subprocess.run(capture_output=)`, `%`
formatting, `argparse` + `pyserial`, as `tests/hdmi-suite/scripts/netv2_serial.py` does). Usage:
`netv2_load_sink_keys.py --keys sink_keys.bin --manifest manifest.json [--port /dev/ttyS0] [--verify]`.
It reads the 40 x 7-byte little-endian keys from `sink_keys.bin` (`hdcp/keygen.py:62-66`) and `ksv_sink`
from `manifest.json` (`:86-92`), then issues `hdcp rx off`, `hdcp keyclear`, `hdcp bksv <ksv_sink>`,
forty `hdcp keyload <i> <hi> <lo>`, `hdcp rx on`, `hdcp status`; `--verify` checks `keys_loaded: 40` and
the expected `bksv`. It never prints key bytes and refuses to run if the key file is world-readable.

**Keys are never stored in a flash image.** The FPGA key RAM is volatile and loaded at runtime;
`sink_keys.bin` lives only on the host, is git-ignored, and the manifest (KSVs only) is the sole thing
shared between the two sides (`KEYS_NOTE.txt`). The outstanding key-set collision in `STATUS.md:5-22`
(the shared set with KSV_sink `0x59cabe3384` is not on this machine) blocks only the hardware run — RTL
and loader are key-agnostic.

## 9. Build targets

`legacy/netv2mvp_hdcprx.py` — a **new** file importing `legacy/netv2mvp.py`, which stays untouched:

```python
from netv2mvp import Platform, VideoOverlaySoC, csr_map_update

class VideoOverlayHDCPRxSoC(VideoOverlaySoC):
    csr_map = dict(VideoOverlaySoC.csr_map)        # copy: csr_map_update mutates in place
    csr_map_update(csr_map, ["hdcp_rx"])
    def __init__(self, platform, part, dqs_phase, *a, **kw):
        VideoOverlaySoC.__init__(self, platform, part, dqs_phase, *a, **kw)
        pads   = platform.lookup_request("hdmi_in", 0)
        sda_dn = platform.lookup_request("hdmi_sda_over_dn", 0)
        _release_comb_driver(self, sda_dn)         # see below
        self.submodules.hdcp_rx = HDCPReceiver(pads, self.hdcp, self.i2c_snoop)
        self.comb += sda_dn.eq(self.hdcp_rx.sda_drive_low)
```

Two real integration details, both handled in this one file. `hdmi_in0_pads` is a local inside
`VideoOverlaySoC.__init__`, so the bridge recovers it with `platform.lookup_request` (present in the
pinned migen, `legacy/deps/migen/migen/build/generic_platform.py:180`), not a second `request`, which
would raise `ConstraintError`. And `legacy/netv2mvp.py:874-877` already drives both override pads to 0 in
`self.comb`, where a second driver is a migen error — `_release_comb_driver` walks `soc._fragment.comb`,
removes the single `_Assign` targeting that signal and **asserts exactly one was removed**, so if the
parent ever changes the build fails loudly rather than silently mis-driving a FET gate.
`hdmi_sda_over_up` (G20) is left driven to 0 by the original (§1.1).

`main()` mirrors `legacy/netv2mvp.py:1273-1300` with no new arguments. Targets, run in the `rebuild2019`
container as in `docs/superpowers/plans/2026-09-05-phase0-1-repo-setup-and-baseline.md:1076-1085` with
`PYTHONHASHSEED=1` (`legacy/netv2mvp.py:1274-1276`): Verilog-only 35T via
`rebuild2019_hdcprx_verilog.py 35 --lx-ignore-deps` (a copy of `legacy/rebuild2019_verilog.py` pointing
at the new SoC); bitstreams via `netv2mvp_hdcprx.py -p 100 -c pcb` and `-p 35 -c pcb`. **The 100T is the
only hardware target** until the 35T baseline closes timing (§11.3): the 35T build is run as a
synthesis/fit check and to track WNS, but its bitstream is never loaded (§10.3). The CSR bank budget
must be checked: `csr_address_width = 14` gives 32 banks and `hdcp_rx` adds one; the build fails
explicitly at `soc_core.py:316-317` on overflow.

Later the same `netv2/gateware/hdcp/` package is instantiated from the modern LiteX tree; the Verilog and
`HDCPReceiver` use only plain `Instance`, `CSRStorage`, `MultiReg`, `PulseSynchronizer` and
`BusSynchronizer`, so only the top level changes.

## 10. Verification plan

Nothing reaches hardware until 10.1 and 10.2 pass.

**10.1 Python reference model** (in progress, another agent). `netv2/hdcp/cipher.py` implements the HDCP
1.4 cipher from the public spec (§4.1-4.5, Tables 4-7 to 4-11) plus the spec's own block-cipher trace
vectors. Unit tests in `tests/unit/test_hdcp_cipher.py`: the block trace matches the spec's per-round
table; `Km = sum(sink_keys[j] for j in setbits(Aksv))` matches `hdcp/keygen.py:58-59` and the manifest's
`km_agreed`; (Ks, M0, R0) reproduce from (Km, An); and the mod-128 Ri schedule.

**10.2 xsim testbenches**, run in the `rebuild2019` container (Vivado 2025.2 already synthesises this
design, `LOG.md`), sources from `netv2/gateware/hdcp/` plus the untouched `legacy/overlay/` files.

1. `tb_hdcp_rx_i2c.v` — a Verilog task-based I2C **master** model driving SCL and an open-drain SDA with
   a bus pull-up at 100 kHz: start/stop/repeated start; the combined `write ptr, Sr, read` form; 5-byte
   Bksv read from 0x00; 2-byte Ri' read from 0x08; An (0x18) and Aksv (0x10) writes; Bcaps/Bstatus at
   0x40/0x41; foreign addresses 0x50 and 0xA0, which must be **NACKed and never driven**; a write to a
   read-only offset; auto-increment across 0x40->0x44. Asserts `sda_drive_low` timing against SCL edges.
   The Bcaps/Bstatus "expected" bytes are those the Pi's HDCP driver actually parses, byte-order
   included, **not** merely self-consistent with §3: Bcaps read at 0x40 = `0x80`; Bstatus is 2 bytes
   little-endian, so the byte read at 0x41 = `0x00` and at 0x42 = `0x10` (HDMI_MODE, bit 12), which the
   Pi reassembles as the 16-bit `0x1000`.
2. `tb_hdcp_rx_auth.v` — the full handshake with the shared keys. Stimulus (An, Aksv, the 40 sink keys,
   expected R0/Ri) is generated by a Python script from `netv2/hdcp/cipher.py` into a `$readmemh` file,
   so the model is the oracle. Drives a synthetic `pix_o` with vsync and an EESS `ctl_code == 4'b1001`
   per vertical blank, runs 300 frames, and asserts: R0' readable over I2C within 100 ms of the Aksv
   write (~2.6 us in practice, §5.5); **R0' == model R0** (the gate that proves the §5.1 capture window
   — see §5.1); Ri' unchanged until frame 128; Ri' == model Ri at frames 128, 256.
3. `tb_hdcp_decrypt.v` — the model encrypts a small frame with (Km, An); the testbench feeds the
   ciphertext through `hdcp_mod_rx`'s keystream and checks the XOR reproduces the plaintext byte for
   byte across a rekey (line end) and a vertical blank.
4. A regression that `i2c_snoop.v` still produces the same `An` and `Aksv14_write` as `hdcp_rx.v` for
   identical stimulus (§1.4).

The following six cases are **required before any hardware run**, not optional:

5. **Aksv rewritten mid-`KM_RUN`.** A second last-Aksv-byte write while the accumulator is running must
   abandon and restart it (§2.8, HDCP 1.4 transition B1:B1); assert `km_valid_hw` never asserts for the
   abandoned run and the final `km_hw` matches the model for the *restarted* Aksv.
6. **Half-loaded key set.** With `keys_loaded < 40`, a full handshake must produce **no R0'** — `Ri'`
   reads its reset value and `sda_drive_low` never asserts for a 0x74 address match, because
   `rx_enable_eff = rx_enable & (keys_loaded == 40)` is 0 (§2.8). This guards against a wrong R0' from a
   partial load.
7. **Ri' read straddling an update.** Start a 2-byte read of 0x08 and drive a (i mod 128 == 0) frame
   boundary *during* the transaction; assert the two bytes returned are one consistent Ri value, proving
   the §5.4 "refresh `ri_ddc_eth` only at `I2C_START`" latch prevents a torn read.
8. **Lowest supported pixel clock.** Repeat tb #2 with `pix_o` at 25.2 MHz (480p, the rig's slowest
   mode, §5.5); R0' must still be valid well within 100 ms.
9. **`pix_o` not locked when Aksv arrives.** Write An+Aksv with the synthetic `pix_o` held in reset
   (MMCM unlocked, §5.5); assert no spurious R0' is produced and that R0' becomes valid only after
   `pix_o` starts and a fresh Aksv (or HPD-forced re-auth) drives the cipher.

**10.3 Hardware, in order.** **No bitstream is loaded on `rpi3-netv2` without Tim's explicit go-ahead,
and only volatile JTAG loads are ever used there** (`tests/hardware/hosts.py` `ALLOWED_ON_GOLDEN` =
`jtag_volatile_load`, `restore_stock_bitstream`; spec decision 6). NOR flash is never written; every run
ends by reloading the stock `user-35.bit`. The recovery path (`~/alphamax-rpi.cfg` on `rpi3-netv2`) is
confirmed present and the stock bitstream checksummed *before* any load.

**A bitstream that does not close timing is never loaded, not even volatile.** Per §11.3 the 35T
baseline currently routes with WNS -7.5 ns; a build with negative WNS can mis-sample the DDR or video
clocks and hang or corrupt the running system, so H1-H6 below are gated on a build with **post-route
WNS >= 0 and no failing endpoints**. Until the 35T baseline itself closes (§11.3), all hardware steps run
on a **100T** bitstream; the 35T is deferred, not merely deprioritised.

| Step | Check | Evidence |
|---|---|---|
| H1 | with `rx_enable = 0` the DDC bus behaves exactly as stock (EDID reads from the Pi still work) | `tests/hdmi-suite/hdcp/i2c_ddc_probe.py` |
| H2 | with `rx_enable = 1`, `i2cget` at 0x74 returns Bksv = KSV_sink and Bcaps = 0x80 | Pi-side i2c-tools |
| H3 | the Pi's `AUTH_REQUEST` reaches `CORE_AUTHENTICATED` and `O_RI` advances (DoD 1) | `hdcp/mon_ri.py`, `hdcp status` |
| H4 | the Pi emits encrypted video: capture entropy ~8 bits (DoD 2) | `tests/hdmi-suite/hdcp/netv2_capture_stats.py` |
| H5 | `hdcp status` `ri` matches the Pi's `CP_INTEGRITY` at each 128-frame boundary | both sides logged |
| H6 | decrypted capture, entropy ~4 bits (DoD 3) | needs the §11.4 decrypt path; separate build |

## 11. Risks

**11.1 Electrical.** `hdmi_sda_over_up` must stay 0 — Q10H (BSS84) drives SDA to 5 V with no series
resistance (§1.1), and if asserted while the Pi pulls SDA low the current is limited only by the Pi's
driver; enforced in RTL, since the bridge never requests it as a driver and the original's `.eq(0)` stays.
Pull-down strength: R18H 39R plus Q12H's R_DS(on) (~3R) against a typical 1.5k-2.2k HDMI DDC pull-up to
5 V gives V_OL ~ 0.09-0.13 V, well under the 0.4 V I2C limit **(inferred** from the standard HDMI
source-side pull-up; the actual value is on the Pi, not this board**)**. Bus capacitance — three
connectors of trace plus the shared pass-through and two 47k bias resistors — is fine at 100 kHz against
the 400 pF I2C limit and is another reason FAST = 0; a slow SDA rise (~1 us worst case) costs latency,
not correctness, since the 160 ns deglitch only advances the FSM on a clean level. The **shared
downstream sink** (§2.9) is the highest-probability practical failure, and it is a rig configuration
issue rather than a design one.

**11.2 Protocol.** *Ri cadence*: the Pi's `CP_INTEGRITY_CFG` has `I_RATE[7:0]` and `J_RATE[15:8]`
(`hdcp/REGISTERS.md:32`); anything other than 128 will not line up. STATUS.md open question 2 asks for
the values — `frame_offset` trims phase, not rate; if the rate differs the mod-128 constant becomes a CSR
too. *Frame index alignment*: the `HDCP_AUTH_VSYNC` ambiguity (`legacy/overlay/hdcp_mod.v:220-232`),
mitigated by `frame_offset` and by logging both sides' first mismatch. *EESS*: `hdcp_mod` will not leave
`HDCP_WAIT_1001` until it sees `vsync && ctl_code == 4'b1001` (`:236`), and `hdcp/README.md:43-52`
records that the Pi was **not** emitting EESS in the last experiment. If it still does not, the receiver
still authenticates — **R0' does not depend on EESS; the 128-frame link check does** — a distinction that
matters for triage. *R0' read timing*: the spec forbids reading before 100 ms; an early read gets our
value anyway. *`pix_o` not locked at Aksv time*: §5.5.

**11.3 Resources — the 35T is over budget before we add anything.** Real post-route numbers now exist
and are worse than any earlier estimate assumed. The **2019 overlay design, unmodified**, placed and
routed on the golden-unit part **xc7a35t-fgg484-2** with Vivado 2025.2 gives:

| Metric | 2019 baseline on 35T | Headroom |
|---|---|---|
| Post-route **WNS** | **-7.5 ns**, 515 failing endpoints (hold clean) | **negative — does not close** |
| **BRAM36** | **47.5 / 50 = 95%** | 2.5 blocks |
| LUT | 73.6% | ~26% |

**(a) Precondition.** The 35T baseline **does not currently close timing on its own**, so no 35T
receiver build can be validated on hardware until that pre-existing failure is fixed. This is a blocker
inherited from the baseline, independent of anything in this design.

**(b) Split by domain and gate the pix_o additions.** The receiver's own logic is estimated (still
**inferred**, but now against a nearly-full part):

| Block | domain | LUT | FF | on 35T? |
|---|---|---|---|---|
| I2C slave: SCL/SDA sync+deglitch + protocol FSM + `reg_ptr` | eth | 220 | 150 | eligible |
| register file read mux (0x00..0x44) + write decode | eth | 150 | 140 | eligible |
| 40x56 key RAM (distributed/LUTRAM, 64x56) + Km accumulator | eth | 126 | 65 | eligible |
| CSR bank + CDC (Bus/PulseSynchronizers) | sys/eth | 100 | 590 | eligible |
| **`hdcp_cipher_rx` Ri shift register** (the §5.1 patch) | **pix_o** | 20 | 20 | **gated** |
| **`hdcp_mod_rx` R0/Ri_ddc/frame comparator + adder** (the §5.2 patch) | **pix_o** | 60 | 90 | **gated** |

The eth/sys-domain blocks (~600 LUT / ~950 FF, no BRAM, no DSP) are 35T-eligible on LUT/FF budget and
add no BRAM — which is precisely why the key store is LUTRAM, not a RAMB18 (§4.1): with only 2.5 BRAM36
free, a BRAM key store could tip the design over. But the two **new pix_o-domain additions add logic to
the exact clock domain that already misses timing by 7.5 ns**. They are therefore **gated on a fresh
post-route WNS** for the combined design and are **100T-first**: they go into a 100T build, and reach
the 35T only after the baseline closes and a receiver build re-routes with WNS >= 0.

**(c) 35T hardware is deferred** until the pre-existing baseline timing closes. All of §10.3's H1-H6 run
on the 100T until then; §9's "build 100T first" becomes "build 100T *only* for hardware", with the 35T
kept as a synthesis/fit check, never loaded.

**(d)** Reinforced in §10.3: a -7.5 ns bitstream is never loaded, not even volatile.

If a 35T fit is later pursued, the cheapest cuts are (i) drop `i2c_txn_count` and the debug CSRs,
(ii) drop the `an_rx`/`aksv_rx` readback, (iii) narrow the register-file mux — but none of these help the
WNS, which is the actual gate.

**11.4 The decrypt path (DoD 3) is not free.** Per §0.1 no decrypt exists. Adding one means XORing
`cipher_stream` into input0's RGB before the DMA. That path is in the `pix` domain but the cipher runs in
`pix_o`, and with `split_mmcm = True` (`legacy/netv2mvp.py:837`) `pix` and `pix_o` come from **two
separate MMCMs** (`legacy/deps/litevideo/litevideo/input/clocking.py:146-206`) with independent BUFGs
and no guaranteed phase relationship, so a single-cycle register cross of the keystream is not safe. Two
options, both deferred to a separate build after H4: **R3a**, a second `hdcp_mod_rx` in `pix` fed the
same Km/An and a `pix`-resynchronised `auth_start`, timed from `hdmi_in0.syncpol`/`decode_terc4`
directly — costs one more cipher (**inferred** ~1200-1800 LUTs, since `hdcp_block.v` is 84 + 84 bits of
state with seven S-boxes and eight diff networks per round), so almost certainly 100T-only; or **R3b**,
one cipher plus a CSR-adjustable 0..15 pixel skid on the `pix` side, swept while watching capture
entropy — cheaper, but relying on the two MMCM outputs being frequency-locked with bounded drift (true,
same `pix_raw` source) though not phase-aligned. Recommendation: prove authentication and encryption
(H1-H5) with no decrypt at all — the MS2109 downstream sees the raw ciphertext through the pass-through,
so DoD 1 and 2 are fully testable today — then take R3a on the 100T.

**11.5 Open questions for the RPi side** (`STATUS.md:46-55`, plus two new): (1) is the MS2109 the only
other device on input0's DDC (§2.9 — blocking for hardware); (2) what `I_RATE`/`J_RATE` does the Pi use,
and does it tolerate R0' appearing in microseconds (§11.2); (3) where does the KSV manifest live
(`mithro/netv2-testsuite` under `hdcp/`; KSVs only, never key `.bin` files); (4) **new** — does the Pi
emit EESS (`ctl_code == 1001` at vsync) once `CORE_AUTHENTICATED` (§11.2); (5) **new** — re-stage the
shared key set (`STATUS.md:5-22`).

## 12. Out of scope

* **Repeater support.** Bcaps REPEATER = 0, Bstatus DEVICE_COUNT/DEPTH = 0, KSV FIFO (0x43) and
  V'.H0-H4 (0x20-0x33) read 0x00. No SHA-1, no second part of the authentication protocol.
* **HDCP 2.x.** Different cipher (AES-CTR), key exchange and port. Nothing here applies.
* **Real DCP device keys and `legacy/firmware/compute_ksv.c`.** The closed loop uses `hdcp/keygen.py`'s
  symmetric matrix, which we own; the leaked master key in `compute_ksv.c` is not used, extended or
  exercised by any new code, and §0.3 explains why the two systems are mutually exclusive anyway.
* **Enhanced Link Verification (Pj')** (1.1_FEATURES = 0, 0x0A reads 0x00), **Advance Cipher / Ainfo**
  (accepted and discarded, §3), and **the secondary link (0x76)**.
* **Faking EDID or HPD.** Both keep coming from the downstream device through the pass-through (§1.1).
