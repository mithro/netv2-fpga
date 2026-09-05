# The 2019 RISC-V firmware

The soft-core firmware in `legacy/firmware/`: how it boots, every command its
serial REPL accepts, the exact text it prints, and the state machines behind
EDID, multi-resolution detection and HDCP. Every claim cites
`legacy/<file>:<line>`.

The shipped binary is `legacy/production-images/user-firmware.bin`, 69,524
bytes. `legacy/testing-images/testing-firmware.bin` is a byte-identical size and
is built by the same `make` invocation (`legacy/make_images.sh:34-35`,
`legacy/make_testing.sh:42-43`).

## 1. Boot

### 1.1 Two-stage boot

The CPU is a VexRiscv with a 24 KB integrated ROM and 4 KB of integrated SRAM:

```python
# legacy/netv2mvp.py:559-566
SoCSDRAM.__init__(self, platform, clk_freq,
    integrated_rom_size=0x6000,
    integrated_sram_size=0x1000,
    ident="NeTV2 LiteX Base SoC",
    reserve_nmi_interrupt=False,
    cpu_type="vexriscv",
    csr_address_width=17,
```

The ROM holds the LiteX BIOS, baked into the bitstream. The BIOS brings up DDR3
(`BOOT_MEMTEST` is added as a constant at `netv2mvp.py:825` to enable the extra
memory characterisation) and then attempts a flash boot from a fixed address:

```python
# legacy/netv2mvp.py:628
self.flash_boot_address = 0x207b0000  # hard-coded to be just above the second copy of 100T bitfile
```

`0x20000000` is the SPI flash window (`netv2mvp.py:548-550`), so the byte offset
in the NOR is `0x7b0000`. The image format and the update path are covered in
[boot-and-flash.md](boot-and-flash.md).

The BIOS also accepts a serial boot, which is how `flterm --kernel firmware.bin`
loads a firmware without touching the flash (`netv2mvp-scripts/README.md`,
"REPL shell"). That is the only route the golden reference unit may ever use.

### 1.2 `main()` initialisation order

```c
/* legacy/firmware/main.c:27-47 */
int main(void)
{
	hdcp_hpd_ena_write(1);  // de-assert hot plug detect while booting
	irq_setmask(0);
	irq_setie(1);
	uart_init();

	puts("\nNeTV2 software built "__DATE__" "__TIME__);

	config_init();
	time_init();

	processor_init();
	processor_update();
	processor_start(config_get(CONFIG_KEY_RESOLUTION));

	ci_prompt();
```

The order is load-bearing: hot-plug detect is forced asserted *first*
(`main.c:29`) so no source tries to train a link while the MMCMs are being
reprogrammed, and is only released after the main loop has been running for more
than one second (`main.c:54`, `:62-69`). `link_redo`, set by the HDCP ISR
(`km.c:46-47`), re-arms that hold-off (`main.c:72-77`).

The banner at `main.c:36` is the first line on the console after a boot, and
carries the compiler's `__DATE__`/`__TIME__`, which is how a running unit's
firmware build is identified.

`processor_start()` (`processor.c:554-589`) is the whole video bring-up: drop
HPD on both inputs, stop and clear both capture paths, fill the pattern
framebuffer, reprogram all input MMCMs for the mode's pixel clock
(`mmcm_config_for_clock`, `processor.c:573`), set the output timing, write both
EDID RAMs, re-init both inputs, raise HPD, then `hdcp_init()` and `init_rect()`.

### 1.3 Interrupts

`irq_setmask(0)` then `irq_setie(1)` at `main.c:30-31` enables the global
interrupt-enable with every source masked; each subsystem then unmasks its own
line. `isr()` (`isr.c:9-37`) dispatches four sources:

| Source | Guard | Handler | Unmasked by |
|---|---|---|---|
| UART | always | `uart_isr()` | `uart_init()` |
| `HDMI_IN1_INTERRUPT` | `#ifdef HDMI_IN1_INTERRUPT` | `hdmi_in1_isr()` (`hdmi_in1.c:131`) — DMA slot management | `hdmi_in1_init_video` |
| `HDCP_INTERRUPT` | `#ifdef HDCP_INTERRUPT` | `hdcp_isr()` (`km.c:41`) | `hdcp_init()` (`km.c:28-30`) |
| `HDMI_IN0_INTERRUPT` | `#ifdef CSR_HDMI_IN0_DECODE_TERC4_EV_ENABLE_ADDR` | `hdmi_in0_terc4_isr()` (`hdmi_in0.c:150`) | only by `debug t4i` |

`isr()` raises `hdcp_debug_write(1)` on entry and clears it on exit
(`isr.c:13`, `:36`) so ISR latency is visible on a scope or in LiteScope. The
comment at `isr.c:32` is candid about the naming: the HDMI_IN0 line is "actually
handling a terc4 decode, not a DMA ISR. Awful API, I know."

The main loop (`main.c:56-78`) polls `processor_service()`, `ci_service()` and
`uptime_service()`; there is no scheduler and no sleep.

## 2. REPL command reference

The parser is `ci_service()` (`ci.c:755-1180`). One line is assembled by
`readstr()` (`ci.c:179-205`), which returns on CR or LF, supports backspace
(0x7f and 0x08) and caps the line at 63 characters. Tokens are split on single
spaces by `get_token()` (`ci.c:233-236`). Dispatch is a chain of `strcmp` on the
first token; an unrecognised first token silently does nothing (`ci.c:1171-1175`).
The prompt is written by `ci_prompt()`:

```c
/* legacy/firmware/ci.c:672-675 */
void ci_prompt(void)
{
	wprintf("RUNTIME>");
}
```

Note there is no newline and no trailing space: the exact prompt string is
`RUNTIME>`. A line whose first token starts with `dummy` (`ci.c:772`) suppresses
the prompt reprint (`ci.c:1176-1178`); this is how the internal no-input path
avoids spamming prompts.

`wprintf`/`wputs`/`wputsnonl` (`stdio_wrap.c:9-28`) are thin wrappers over
`printf`/`puts`/`putsnonl`, so `wputs` appends a newline and `wprintf` does not.

### 2.1 Top-level commands

**Contract-frozen** marks commands listed in `docs/current/repl-contract.md`,
whose output the modern firmware must reproduce byte for byte.

| Command | Line | Effect | Contract |
|---|---|---|---|
| `help` | `ci.c:774` | prints `Available commands:` then the full list via `ci_help()` (`ci.c:131-168`) | frozen |
| `help <topic>` | `ci.c:777-798` | topic-specific help for `video_matrix`, `video_mode`, `hdp_toggle`, `output0`, `output1`, `encoder`, `debug`; anything else falls through to `ci_help()` | |
| `reboot` | `ci.c:800` | `reboot()` (`ci.c:238-241`) executes the `REBOOT` macro — jumps back to the BIOS, losing all runtime state | **forbidden on the golden unit** |
| `mr <addr> <len>` | `ci.c:801` | memory read/dump (`dump.c:53`) | **forbidden on the golden unit** |
| `mw <addr> <val> <count>` | `ci.c:802` | arbitrary 32-bit write anywhere in the address map (`dump.c:81`) | **forbidden on the golden unit** |
| `mc <dst> <src> <count>` | `ci.c:803` | memory copy (`dump.c:115`) | **forbidden on the golden unit** |
| `video_matrix list` | `ci.c:806-808` | lists sinks and sources (`video_matrix_list`, `ci.c:472`) | frozen |
| `video_matrix connect <src> <sink>` | `ci.c:809-847` | sources `input0`/`input1`/`pattern`, sinks `output0`/`output1`/`encoder`; unknown names print `Unknown video source: '%s'` / `Unknown video sink: '%s'` (`ci.c:825`, `:841`) and fall back to `help_video_matrix()` | |
| `video_mode list` | `ci.c:853-854` | lists the modes (`video_mode_list`, `ci.c:532`) | frozen |
| `video_mode <n>` | `ci.c:856` | `video_mode_set(atoi(token))` (`ci.c:544`) | frozen |
| `hdp_toggle <src>` | `ci.c:858-861` | prints `Toggling HDP on output%d` then drops and re-raises `edid_hpd_en` on that input across a 65,536-iteration busy loop (`ci.c:555-579`) — note the message says "output" for what is an input | frozen |
| `output0 on` / `off` | `ci.c:863-873` | enable/disable HDMI out 0 initiator | |
| `output1 on` / `off` | `ci.c:874-884` | as above for out 1; compiled out unless `CSR_HDMI_OUT1_BASE` | |
| `encoder on`/`off`/`quality <q>`/`fps <f>` | `ci.c:885-899` | JPEG encoder controls; compiled out unless `ENCODER_BASE` | |
| `sdram_test` | `ci.c:900-903` | `bist_test()`; compiled out unless `CSR_GENERATOR_BASE` | |
| `dma_writer on`/`off` | `ci.c:905-918` | prints `dma_writer on` / `dma_writer off`; compiled out unless `CSR_DMA_WRITER_BASE` | |
| `dma_reader on`/`off` | `ci.c:919-932` | prints `dma_reader on` / `dma_reader off` | |
| `status` | `ci.c:940` | one-shot `status_print()` | frozen |
| `status on` / `off` | `ci.c:935-938` | prints `Enabling status` / `Disabling status` and toggles the 1 Hz auto-print | frozen (`status` only) |
| `json` | `ci.c:950` | one-shot `json_print()` | frozen |
| `json on` / `off` | `ci.c:945-948` | prints `Enabling json status` / `Disabling json status` | frozen |
| `chromalo <hex>` | `ci.c:952-955` | `rectangle_chroma_key_lo_write` | |
| `chromahi <hex>` | `ci.c:956-959` | `rectangle_chroma_key_hi_write` | |
| `chromapol <n>` | `ci.c:960-962` | `rectangle_chroma_polarity_write` | |
| `chromamode <n>` | `ci.c:963-965` | `rectangle_chroma_mode_write` | |
| `720p` | `ci.c:966-972` | force 720p: 60-120 MHz MMCM table, pixel clock 7425, `hdmi_in0_init_video(1280,720,7425)`, `init_rect(9,1)`, interlace off | |
| `1080i` | `ci.c:973-983` | force 1080i: 60-120 MHz table, `init_rect(15,2)`, `field_pos = 1320`, interlace 1 or 3 | |
| `1080p` | `ci.c:984-990` | force 1080p: 120-240 MHz table, pixel clock 14850, `init_rect(11,0)`, interlace off | |
| `debug <sub>` | `ci.c:991` | see below | |

`1080i` has a parsing bug worth recording: at `ci.c:979` it tests
`strcmp(token, "odd")` against the token that was already consumed as `"1080i"`
itself, never fetching the next one, so the `odd` variant is unreachable and the
command always takes the `else` branch (`interlace = 3`).

### 2.2 `debug` sub-commands

| Command | Line | Effect | Contract |
|---|---|---|---|
| `debug mmcm` | `ci.c:993` | `debug_mmcm()` → `mmcm_dump_code()` (`ci.c:635-638`, `mmcm.c:672`): dumps all three CMTs' DRP registers as C array initialisers | |
| `debug inter` | `ci.c:995-998` | prints `even pos: %d` and `odd pos: %d` | |
| `debug interswap` | `ci.c:999-1008` | swaps interlace field parity 1↔3; prints `Not in interlace mode, aborting!` and returns if not interlaced | |
| `debug input0` | `ci.c:1010-1013` | toggles `hdmi_in0_debug`; prints `HDMI Input 0 debug on`/`off` | frozen |
| `debug input1` | `ci.c:1016-1019` | same for input 1 | frozen |
| `debug ddr` | `ci.c:1022-1023` | `debug_ddr()` (`ci.c:642-657`): `read:%5dMbps  write:%5dMbps  all:%5dMbps` | frozen |
| `debug dna` | `ci.c:1026-1027` | `print_board_dna()` (`ci.c:661-668`): `Board's DNA: ` then hex bytes | frozen |
| `debug edid output0`/`output1` | `ci.c:1029-1045` | dumps the monitor EDID read over I2C; if the port has no such capability prints `%s port has no EDID capabilities` | |
| `debug rect` | `ci.c:1046-1047` | re-runs `init_rect()` for the configured resolution | frozen |
| `debug nudge <chan> <amt>` | `ci.c:1048-1051` | `hdmi_in0_nudge_eye()` — manual IDELAY tap adjustment on one channel | |
| `debug filt <mult> <bw>` | `ci.c:1052-1055` | `set_mmcm0_filt()` (`mmcm.c:834`) — recompute MMCM filter registers and rewrite the whole table | |
| `debug algo <bit_time>` | `ci.c:1056-1068` | switch all three capture channels to the auto-delay state machine (`algorithm = 2`, `auto_ctl = 7`) | |
| `debug freeze` | `ci.c:1069-1072` | `auto_ctl = 0` on all three channels — stop delay adaptation | |
| `debug thaw` | `ci.c:1073-1076` | `auto_ctl = 3` — resume | |
| `debug orig` | `ci.c:1077-1081` | back to `algorithm = 0`, the original phase-detector algorithm | |
| `debug setrect <h0> <h1> <v0> <v1>` | `ci.c:1082-1091` | enable the overlay rectangle with those bounds; the vertical bounds are offset by `video_modes[12].v_blanking` | frozen |
| `debug rectoff` | `ci.c:1092-1093` | `rectangle_rect_enable_write(0)` | frozen |
| `debug overlayoff` | `ci.c:1094-1095` | `hdmi_core_out0_initiator_enable_write(0)` | |
| `debug delay <n>` | `ci.c:1096-1098` | sets the DMA delay base; prints `delay value: %d` | |
| `debug xadc` | `ci.c:1099-1100` | prints `xadc: %d mC` | frozen |
| `debug km` | `ci.c:1101-1102` | `derive_km()` (`km.c:58`) — see section 6 | |
| `debug hpdforce` | `ci.c:1103-1104` | `hdcp_hpd_ena_write(1)` — force HPD asserted | frozen |
| `debug hpdrelax` | `ci.c:1105-1106` | `hdcp_hpd_ena_write(0)` | frozen |
| `debug dumpe` | `ci.c:1107-1116` | dumps 256 bytes of the I2C-snooped EDID, 16 per line, `\r\n %02x: ` then `%02x ` per byte | frozen |
| `debug dvimode0` | `ci.c:1117-1118` | `hdmi_in0_decode_terc4_dvimode_write(1)` — treat input 0 as DVI (no data islands) | frozen (manual) |
| `debug hdmimode0` | `ci.c:1119-1120` | `..._dvimode_write(0)` — HDMI mode | frozen (manual) |
| `debug dvimode1` | `ci.c:1121-1122` | same for input 1 | |
| `debug hdmimode1` | `ci.c:1123-1124` | same for input 1 | |
| `debug stop` | `ci.c:1125-1127` | marks both input 1 DMA slots empty — freezes overlay capture | frozen |
| `debug run` | `ci.c:1128-1130` | marks both slots loaded — resumes | frozen |
| `debug override` | `ci.c:1131-1132` | toggles `rectangle_pipe_override` | frozen |
| `debug a1` | `ci.c:1133-1136` | `auto_ctl = 0x6f` on all three channels | |
| `debug a2` | `ci.c:1137-1140` | `auto_ctl = 0x2f` | |
| `debug t4i` | `ci.c:1141-1153` | enable the TERC4 interrupt — see section 5 | frozen (manual) |
| `debug t4d` | `ci.c:1154-1164` | print TERC4 counters and BCH registers — see section 5 | frozen (manual) |
| `debug align <n>` | `ci.c:1165-1168` | `hdmi_core_out0_dma_line_align_write(n)`; prints `set line alignmnent position to %d` (spelling as in the source) | |
| anything else | `ci.c:1169-1170` | `help_debug()` | |

That is **24 top-level commands** (the 24 first-token `strcmp` tests in the
main chain, plus the `strncmp` on `dummy` at `ci.c:772`) and **36 `debug`
sub-commands**, 60 in total. Several top-level commands take a second token of
their own (`list`, `connect`, `on`, `off`), which the tables above break out as
separate rows.

**Contradiction with the REPL contract.** `docs/current/repl-contract.md` lists
`debug rectthresh %d` as issued by `console.py`, but no such token exists in
`ci.c` — `grep -n thresh legacy/firmware/ci.c` finds only the two help lines at
`ci.c:140-141` and a local `int rect_thresh = 20` at `ci.c:735` whose only use,
`rectangle_rect_thresh_write(rect_thresh)`, is commented out at `ci.c:745`.
Sending `debug rectthresh 20` to the 2019 firmware falls through to
`help_debug()`. The contract row should be treated as a suite-side command that
the firmware ignores, not as behaviour to reproduce.

`help_debug()` (`ci.c:121-129`) documents only four of the 36 sub-commands
(`mmcm`, `ddr`, `dna`, `edid`); the rest are undocumented at the console.

## 3. `status` and `json` output formats

Both are printed once per second from `status_service()` when enabled, and
`json_enabled` defaults to **1** while `status_enabled` defaults to **0**
(`ci.c:35-36`), so a freshly booted unit emits a JSON line every second without
being asked:

```c
/* legacy/firmware/ci.c:444-458 */
static void status_service(void)
{
	static int last_event;

	if(elapsed(&last_event, SYSTEM_CLOCK_FREQUENCY)) {
		if(status_enabled) {
			status_print();
			wprintf("\r\n");
		}
		if(json_enabled) {
			json_print();
			wprintf("\r\n");
		}
	}
}
```

`status_service()` is called at the top of every `ci_service()` iteration
(`ci.c:762`), so the cadence is bounded by main-loop latency, not a timer
interrupt.

### 3.1 `status`

`status_print()` is `ci.c:349-442`. The format strings, verbatim:

```c
/* legacy/firmware/ci.c:353-361 */
	wprintf(
		"input0:  %dx%d",
		hdmi_in0_resdetection_hres_read(),
		hdmi_in0_resdetection_vres_read());
	wprintf(" (@ %3d.%2d MHz)", hdmi_in0_freq_value_read() * 10 / 1000000,
		                        (hdmi_in0_freq_value_read() * 10 / 10000) % 100);
	wprintf("\r\n");
```

Note `input0:` is followed by **two** spaces and `%3d.%2d` pads with spaces, not
zeros, so `74.25 MHz` prints as `(@  74.25 MHz)` and a value below 10 in the
fractional field prints with an embedded space. Input 1 uses the same shape
(`ci.c:364-374`) but without the `* 10` scaling, because its `FrequencyMeter` is
configured with a full-second period (`netv2mvp.py:902`) where input 0's is a
tenth of a second (`netv2mvp.py:835`).

The remaining lines, in order:

| Line | Format string | Source |
|---|---|---|
| xadc | `"xadc: %d mC\n\r"` — note `\n\r`, reversed | `ci.c:375` |
| output0 | `"output0: "` then either `"%dx%d@%dHz from %s (underflows: %d)"` or `"off"`, then `"\r\n"` | `ci.c:377-396` |
| output1 | `"output1: "` then `"%dx%d@%uHz from %s (underflows: %d)"` (`%u`, unlike output0's `%d`) or `"off"` | `ci.c:398-417` |
| encoder | `"encoder: "` then `"%dx%d @ %dfps from %s (q: %d)"` or `"off"` | `ci.c:418-431` |
| ddr | `"ddr: "` then `debug_ddr()`'s `"read:%5dMbps  write:%5dMbps  all:%5dMbps\r\n"` | `ci.c:433-434`, `:656` |
| dma_writer | `"DMA_WRITER overflows: %d\n"` | `ci.c:437` |
| dma_reader | `"DMA_READER underflows: %d\n"` | `ci.c:440` |

`%s` for the source is `processor_get_source_name()` (`processor.c:604-611`),
which returns `pattern` or `input%d`. Reading the underflow counter also
re-arms it (`ci.c:381-383`, `:391-392`), so `status` is not side-effect free.

### 3.2 `json`

`json_print()` is `ci.c:283-347`. It emits one line, opening with `{`
(`ci.c:284`) and closing with `}\n\r` (`ci.c:346`) — again `\n\r`, not `\r\n`.
The key strings, in emission order and exactly as spelled:

```c
/* legacy/firmware/ci.c:290-292 */
  wprintf( "\"hdmi_Rx_hres\" : %d, ", hdmi_in0_resdetection_hres_read() );
  wprintf( "\"hdmi_Rx_vres\" : %d, ", hdmi_in0_resdetection_vres_read() );
  wprintf( "\"hdmi_Rx_pixel_clock\" : %d, ", hdmi_in0_freq_value_read()*10); // modded to converge faster
```

| # | Key | Type | Line |
|---|---|---|---|
| 1 | `hdmi_Rx_hres` | int | `:290` |
| 2 | `hdmi_Rx_vres` | int | `:291` |
| 3 | `hdmi_Rx_pixel_clock` | int (already `×10`) | `:292` |
| 4 | `hdmi_Rx_phase` | string, `"%d %d %d"` | `:297` |
| 5 | `hdmi_Rx_symbol_sync` | **bare `%d%d%d`, unquoted** | `:297` |
| 6 | `hdmi_Rx_sync_pos` | string, `"%d %d %d"` | `:302` |
| 7 | `hdmi_Rx_symbol_errors` | string, `"%d %d %d"` | `:302` |
| 8 | `overlay_hres` | int | `:310` |
| 9 | `overlay_vres` | int | `:311` |
| 10 | `overaly_pixel_clock` | int — **misspelt in the wire format** | `:312` |
| 11 | `overlay_phase` | string | `:317` |
| 12 | `overlay_symbol_sync` | bare `%d%d%d` | `:317` |
| 13 | `overlay_sync_pos` | string | `:322` |
| 14 | `overlay_symbol_errors` | string | `:322` |
| 15 | `ddr_read_Mbps` | int | `:337` |
| 16 | `ddr_write_Mbps` | int | `:337` |
| 17 | `hdmi_Rx_eye_opening` | string, popcount of the eye mask per channel | `:339` |
| 18 | `overlay_eye_opening` | string | `:341` |
| 19 | `fpga_die_temp` | **string with a `C` suffix**, `"%dC"` | `:344` |

Three of these must be preserved exactly despite being wrong: the misspelt
`overaly_pixel_clock` (`:312`), the unquoted `%d%d%d` for both `symbol_sync`
fields, and the `"%dC"` string for a numeric temperature. Every field except the
last is followed by `, ` (comma space); `fpga_die_temp` is followed by a space
and then `}`.

`json_print()` also has side effects: it strobes `wer_update` on all six data
channels (`ci.c:294-296`, `:314-316`) and `sdram_controller_bandwidth_update`
(`ci.c:325`) before reading them.

## 4. EDID

### 4.1 What the unit presents

`processor.c` carries four 256-byte EDID blobs: `lg_edid` (`:452`), a captured
real LG monitor kept "to help with debugging connection issues in case the Pi
has a firmware update" (comment `:448-450`), and three synthetic ones,
`netv_edid_60hz` (`:471`), `netv_edid_30hz` (`:490`) and `netv_edid_720p`
(`:509`).

`netv_edid_60hz` block 0 declares manufacturer bytes `05 b8` with product code
`4e 54` (ASCII "NT"), week 0x13 year 0x1c (2018), EDID 1.3, digital input, and a
monitor-name descriptor reading `Alphamax` (`processor.c:479`). Its preferred
timing is the `02 3a 80 18 71 38 2d 40 53 2c 45 00` detailed descriptor at
`processor.c:475-476` — 1920×1080 at 148.5 MHz — followed by a 1280×720
descriptor. The three variants differ only in which detailed timing comes first
and in the checksum; `netv_edid_720p` puts the 720p descriptor first
(`processor.c:512-513`).

### 4.2 The CEA-861 extension block

All four blobs share the same extension block, at byte 128
(`processor.c:480-482` for `netv_edid_60hz`). Decoding the header and the two
data blocks the task calls out:

| Bytes | Meaning |
|---|---|
| `02` | CEA extension tag |
| `03` | revision 3 |
| `21` | byte offset 0x21 (33) where the detailed timing descriptors begin |
| `f1` | flags: bit 7 underscan, bit 6 **basic audio**, bit 5 YCbCr 4:4:4, bit 4 YCbCr 4:2:2 all set; low nibble `1` = one native detailed timing |
| `4e 90 04 03 01 14 12 05 1f 10 13` | a video data block (tag 2, length 0x0e): the short video descriptors, VIC 0x4e/0x90 with the native bit, then VIC 4 (720p60), 3, 1, 20, 18, 5, 31, 16, 19 |
| `23 09 07 07` | audio data block: tag 1 (`0x23 >> 5 == 1`), length 3; one short audio descriptor `09 07 07` = format 1 (**LPCM**), 2 channels, sample rates bit 0 32 kHz, bit 1 44.1 kHz, bit 2 48 kHz, bit depths 16/20/24 |
| `83 01 00 00` | speaker allocation block (tag 4, length 3): front left/front right |
| `65 03 0c 00 10 00` | vendor-specific data block: tag 3, length 5, IEEE OUI `00 0c 03` little-endian = **HDMI Licensing LLC**, so this is the HDMI VSDB; physical address `1.0.0.0` (`10 00`) |

So the unit advertises basic audio, two-channel LPCM at 32/44.1/48 kHz, and
identifies itself as an HDMI (not DVI) sink at CEC address 1.0.0.0. This is the
basis for expecting audio to pass through untouched, which the 2026 baseline
suite's T23 did not observe (design spec, section 3).

### 4.3 How the EDID RAMs are written

```c
/* legacy/firmware/processor.c:528-545 */
static void edid_set_mode(const struct video_timing *mode)
{
	unsigned char edid[256];
	int i;
	generate_edid(&edid, "OHW", "TV", 2015, "HDMI2USB 1", mode);
	for(i=0;i<sizeof(edid);i++)
	  MMPTR(CSR_HDMI_IN0_EDID_MEM_BASE+4*i) = netv_edid_60hz[i]; // note netv_edid
	generate_edid(&edid, "OHW", "TV", 2015, "HDMI2USB 2", mode);
	for(i=0;i<sizeof(edid);i++)
	  MMPTR(CSR_HDMI_IN1_EDID_MEM_BASE+4*i) = netv_edid_60hz[i]; // note netv_edid
}
```

Both inputs get **the same** blob, `netv_edid_60hz`, regardless of the mode
argument. `generate_edid()` (`edid.c:195-248`) is still called and its output is
still computed into a stack buffer — including a real checksum
(`edid.c:247`) — and then discarded; the comment "note netv_edid" is the
author flagging the substitution. The `netv_edid_30hz` and `netv_edid_720p`
blobs are never written by any code path.

The write stride is 4 bytes per EDID byte because the EDID RAM is a CSR-mapped
memory with one byte per 32-bit word.

`edid.c` also provides the read side used by `debug edid`: `validate_edid()`
(`:97-106`) checks the 8-byte header and the checksum, `get_monitor_name()`
(`:108`) extracts the `0xfc` descriptor, and `compute_checksum()` (`:85-95`)
is the standard "sum of first 127 bytes, negated".

The `hpd_en` sequencing around EDID changes matters: `processor_start()` drops
HPD on both inputs (`processor.c:562-563`), writes the EDID
(`processor.c:578`), and only then raises HPD (`processor.c:583-584`), which is
what makes the source re-read.

## 5. Multi-resolution detection

### 5.1 The state machine

`hdmi_in0_service()` (`hdmi_in0.c:837-939`) is called once per main-loop
iteration from `processor_service()` (`processor.c:630`). Its states are held in
`static` locals: `was_connected`, `clock_measured`, `rescount`, `lastres`
(`hdmi_in0.c:839-844`).

1. **Disconnected.** If `hdmi_in0_edid_hpd_notif_read()` goes high, mark
   connected and release the MMCM reset (`hdmi_in0.c:926-935`).
2. **Connected, clock not yet measured.** 900 ms after the link came up
   (`hdmi_in0.c:860-865`), call `guess_freq()`. The delay lets the
   `FrequencyMeter` on `cd_pix_raw` settle before anything is reprogrammed.
3. **`guess_freq()`** (`hdmi_in0.c:777-796`) reads the measured clock and
   switches the MMCM band only if the band actually changed:

   | Measured | Band | Action |
   |---|---|---|
   | 141–150 MHz | `PLL_HIGH` | `hdmi_in_0_config_120_240mhz_table()`, set pixclk, `hdmi_in0_init_video_freq()` |
   | 71–76 MHz | `PLL_LOW` | `hdmi_in_0_config_60_120mhz_table()`, same |

   It prints `hdmi_in0: measured clock %d` (`:779`) and
   `hdmi_in0: changing to PLL_HIGH` / `PLL_LOW` (`:782`, `:790`).
4. **Locked, resolution settling.** Every service call compares
   `hdmi_in0_resdetection_hres_read()` with `lastres`; a change resets
   `rescount` to 0, a match increments it (`hdmi_in0.c:875-880`). At exactly
   `rescount == 3` (`:882`) it calls `guess_res(lastres)` — so the resolution
   must be stable for three consecutive service calls, and `guess_res` fires
   once per settling event rather than repeatedly.
5. **`guess_res()`** (`hdmi_in0.c:799-834`) decides the mode from the *pair*
   (clock band, horizontal resolution):

   | Clock | `lastres` | Mode | Actions |
   |---|---|---|---|
   | 141–150 MHz | any | 1080p | `init_rect(11, 0)`, interlace 0 (`:803-811`) |
   | 71–76 MHz | 1920 | 1080i | `init_rect(15, 2)`, `field_pos = 1320`, interlace 3 (`:812-823`) |
   | 71–76 MHz | 1280 | 720p | re-apply the 60-120 MHz table, set pixclk, `init_rect(9, 1)`, interlace 0 (`:824-833`) |

   Each prints `*** setting mode to 1080p ***` / `1080i` / `720p` and is guarded
   by a comparison against `hdmi_in0_mode`, so a mode is entered at most once
   per change. 1080i and 720p are distinguished purely by horizontal resolution
   because they share the 74.25 MHz pixel clock.

   `init_rect()`'s second argument is the "hack" selector (`ci.c:677-751`):
   0 = 1080p, 1 = 720p (line skip 1920−1280, initiator length 1920×720×4, line
   align 1183), 2 = 1080i (vres −2, no line skip).

6. **Locked, running.** Every 1/16 s (`hdmi_in0.c:887`) the word-error counters
   are strobed and compared against `HDMI_IN0_PHASE_ADJUST_WER_THRESHOLD`. Under
   the original algorithm this drives `hdmi_in0_adjust_phase()`; under the auto
   algorithm (`algorithm == 2`) a second threshold instead increments `trip_hpd`
   (`:893-899`), and once `trip_hpd > 48` (`hdmi_in0.c:846-853`) HPD is toggled
   to force the source to retrain. Below threshold the current phases are
   latched as `converged_phase` (`:901-905`).

The MMCM table switch and the mode switch are therefore two separate decisions
made ~900 ms apart: frequency first (which reprograms the CMTs), resolution
second (which only reprograms the output DMA and overlay geometry).

`hdmi_in1_service()` is only called when input 0 is locked
(`processor.c:633-635`), so the overlay path is subordinate to the source path.

### 5.2 `debug t4i` and `debug t4d`

`t4i` arms the TERC4 data-island decoder's interrupt:

```c
/* legacy/firmware/ci.c:1141-1153 */
} else if (strcmp(token, "t4i") == 0 ) {
  unsigned int mask;
  // setup terc4 handler
  hdmi_in0_decode_terc4_ev_pending_write(3);

  mask = irq_getmask();
  mask |= 1 << HDMI_IN0_INTERRUPT;
  irq_setmask(mask);
  printf("interrupt mask (t4i): %x\n", mask);

  hdmi_in0_decode_terc4_ev_enable_write(3);
  printf("terc4_ev_enable_read: %d\n", hdmi_in0_decode_terc4_ev_enable_read());
```

It clears both pending bits, unmasks `HDMI_IN0_INTERRUPT`, enables both event
bits, and prints two lines. The handler it enables is `hdmi_in0_terc4_isr()`
(`hdmi_in0.c:150-164`), which re-arms itself and prints
`hdmi0 terc4 bch4: 0x%08x` only on every 120th interrupt "to limit debug spew
rate" (`hdmi_in0.c:159`).

`t4d` (`ci.c:1154-1164`) prints six lines: a packet/character count line and
five BCH register lines, the first four assembled from 64-bit reads split into
two 32-bit halves.

**The label bug at `ci.c:1155`:**

```c
		  printf( "hdmi0 terc4 packet cnt: %d, char cnt: %d\n", hdmi_in1_decode_terc4_t4d_count_read(), hdmi_in1_decode_terc4_t4d_char_read());
```

Both reads are `hdmi_in1_*` while the label says `hdmi0`, and every one of the
five following lines (`ci.c:1156-1164`) correctly reads `hdmi_in0_*`. So the
first line of `debug t4d` reports the **overlay** input's packet and character
counts under the source input's name, while the BCH payload below it comes from
the source input. Any modern reimplementation has to decide deliberately whether
to keep the bug (the contract freezes the output text) or fix it; they cannot
both be true.

## 6. HDCP key handling

`km.c` implements the HDCP 1.4 key exchange in software so that the overlay can
be re-encrypted onto an already-encrypted link.

`hdcp_init()` (`km.c:25-39`) unmasks `HDCP_INTERRUPT`, enables the event, and
selects "manual Aksv mode" (`hdcp_Aksv_mode_write(1)`), having first cleared the
rising-edge-triggered `Aksv_manual` strobe. The interrupt source is the I2C
snooper in the gateware (`netv2mvp.py:631-652`), which watches address 0x74 and
raises `Aksv14_write` when the 15th KSV byte completes.

`hdcp_isr()` (`km.c:41-56`) clears the event, calls `derive_km()`, sets
`link_redo` if it succeeded (which makes `main()` re-toggle HPD), pulses
`Aksv_manual`, and prints `Km: %08x %08x`.

`derive_km()` (`km.c:58-...`) reads the sink KSV from snoop registers 0..4 and
the source KSV from registers 0x10..0x14 (`km.c:70-80`), then computes the
shared secret by summing the private-key rows selected by the other party's KSV
bits, and writes the result to the gateware's `Km` register with a `Km_valid`
handshake. It prints a diagnostic when the result is zero: `Km is zero. This
probably means derive_km was fired spuriously on disconnect.` (`km.c:139`).
`debug km` (`ci.c:1101-1102`) invokes it manually.

`compute_ksv.c` supplies the key material as a 40×40 table of 56-bit values
(`compute_ksv.c:30`). **This file does contain real HDCP private key data**, and
its header comment names the corresponding transmitter Aksv
(`compute_ksv.c:26-28`). The file is GPL v3 headed (`compute_ksv.c:1-20`). No
key values, no KSV, and no `CHECK_KM` constant from `km.c:17-18` are reproduced
in this documentation set, and none should be quoted into any modern source,
issue, log or test fixture. Treat both `km.c` and `compute_ksv.c` as
export-sensitive when planning what the modern tree carries forward.

## 7. Nothing the REPL does persists

```c
/* legacy/firmware/config.c:7-26 */
static const unsigned char config_defaults[CONFIG_KEY_COUNT] = CONFIG_DEFAULTS;
static unsigned char config_values[CONFIG_KEY_COUNT];

void config_init(void)
{
	memcpy(config_values, config_defaults, CONFIG_KEY_COUNT);
}

void config_write_all(void)
{
}

unsigned char config_get(unsigned char key)
{
	return config_values[key];
}

void config_set(unsigned char key, unsigned char value)
{
}
```

`config_write_all()` is an empty function and `config_set()` **discards its
argument without writing `config_values`**. The only thing that ever populates
`config_values` is `config_init()` copying the compile-time defaults
(`main.c:40`). There is no flash-backed configuration, no EEPROM, and no code
path from the REPL to non-volatile storage.

Two consequences:

- Every setting made from the console — resolution, chroma keys, rectangle
  bounds, debug toggles, the MMCM band — is lost on the next reset. Power-cycling
  or `reboot` restores the built-in defaults.
- The 2019 REPL has **no flash command of its own**. The only route from the
  console to the SPI NOR is a raw `mw` into the SPI flash core's CSRs, which is
  exactly why `tests/hardware/hosts.py` denies `mw`, `mc` and `reboot` on the
  golden unit while permitting everything else.

`config_get(CONFIG_KEY_RESOLUTION)` at `main.c:45` therefore always returns the
compiled-in default resolution, and the unit's actual operating mode is decided
at runtime by `guess_freq()`/`guess_res()` rather than by stored configuration.
