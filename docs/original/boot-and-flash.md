# Boot and flash in the 2019 design

The SPI NOR layout, the image format, and the one-click update path from a
Raspberry Pi 3B+ over bit-banged JTAG. Every claim cites `legacy/<file>:<line>`
or a path under the `netv2mvp-scripts` repository.

> ## Do not run any of this against `rpi3-netv2`
>
> `rpi3-netv2` is the untouched 2018 reference unit and the behavioural baseline
> for the whole modernisation. `tests/hardware/hosts.py` allows it **volatile
> JTAG loads, serial firmware boot, filtered console traffic, restarts of the
> services the suite itself pauses, and runs of the imported suite — nothing
> else**. Every command on this page except `idcode.cfg` writes or erases the
> SPI NOR, resets the FPGA, or both: `update-fpga.sh`, `testing-fpga.sh`,
> `cl-firmware.cfg`, `cl-spifpga.cfg`, `spi-jtag.cfg`, `firmware-jtag.cfg`,
> `spi-erase.cfg`, `spi-erase-firmware.cfg` and `reboot.cfg` are all forbidden
> there. `reboot.cfg` is forbidden even though it writes nothing, because
> `xc7_program` resets the part. The reference unit's stock flash contents are
> not reproducible; there is no recovery from overwriting them.

## 1. SPI NOR layout

The flash is an 8 MB (0x800000) part. The SoC maps it at `0x20000000`:

```python
# legacy/netv2mvp.py:539-542, :548-550, :628
mem_map = {
    "spiflash" : 0x20000000, # (default shadow @0xa0000000)
}
...
self.add_wb_slave(mem_decoder(self.mem_map["spiflash"]), self.spiflash.bus)
self.add_memory_region(
    "spiflash", self.mem_map["spiflash"] | self.shadow_base, 8*1024*1024)
...
self.flash_boot_address = 0x207b0000  # hard-coded to be just above the second copy of 100T bitfile
```

| Offset | Size | Contents | Source |
|---|---|---|---|
| `0x000000` | up to ~3.65 MB | FPGA bitstream (the one the part loads at power-up) | `cl-spifpga.cfg:13`, `spi-jtag.cfg:13`, `cl-spifpga-rpi4.cfg:13` — all `jtagspi_program <image> 0` |
| ~`0x3a6000` | up to ~3.65 MB | **reserved** for a second copy of the bitstream; nothing in the tree writes it | inferred from the two comments below |
| `0x7b0000` | `0x50000` = 327,680 B (320 KiB) | RISC-V firmware, as an FBI image | `cl-firmware.cfg:13`, `firmware-jtag.cfg:13`, `spi-erase-firmware.cfg:15` |
| `0x800000` | — | end of device | `spi-erase.cfg:15` erases `0x0` to `0x800000` |

The reserved second-copy region is documented only in comments, in two places
that agree:

```tcl
# netv2mvp-scripts/spi-erase.cfg:14 and spi-erase-firmware.cfg:14
# 0x7B0000 = 0x800000 - 0x50000 offset from top, so we can fit in two 100T FPGA images
```

and `netv2mvp.py:628`, "hard-coded to be just above the second copy of 100T
bitfile". The arithmetic works: `user-100.bit` is 3,825,888 bytes, so two copies
are 7,651,776 bytes, which fits below `0x7b0000` = 8,060,928 with 409,152 bytes
to spare. *Inference:* the layout was sized for a Xilinx MultiBoot golden-image
fallback that was never wired up — no `.cfg`, no shell script and no
`BITSTREAM.CONFIG.NEXT_CONFIG_ADDR` property in `netv2mvp.py:265-278` programs a
second copy or a warm-boot address.

Firmware sizes against the 320 KiB budget:

| Image | Size | Share of `0x50000` |
|---|---|---|
| `legacy/production-images/user-firmware.bin` | 69,524 B | 21 % |
| `legacy/testing-images/testing-firmware.bin` | 69,524 B | 21 % |
| what the updater actually writes (padded, plus 8-byte header) | 131,080 B | 40 % |

Bitstream sizes for the two variants, both written at offset 0:

| Image | Size |
|---|---|
| `legacy/production-images/user-35.bit` | 2,192,111 B |
| `legacy/production-images/user-100.bit` | 3,825,888 B |

The bitstream is loaded by the FPGA's own configuration engine in x2 SPI mode at
66 MHz, set as bitstream properties in the platform
(`legacy/netv2mvp.py:265-278`):

```python
"set_property BITSTREAM.CONFIG.CONFIGRATE 66 [current_design]",
"set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 2 [current_design]",
```

with a matching note at `netv2mvp.py:263-264` that quad-SPI would need the QE
bit set in the flash status register, which OpenOCD could not do. The
`STARTUPE2` instance at `netv2mvp.py:611-613` routes the user SPI clock after
configuration, and the SPI flash core is built with `dummy=8, div=2`
(`netv2mvp.py:614-620`) — the 8 dummy cycles are called out as "specific to the
device populated on the board".

The build also emits a raw `.bin` alongside the `.bit`
(`netv2mvp.py:279-281`), which is what `spi-jtag.cfg` expects as `top.bin`;
the shipped `production-images` are `.bit` files and `jtagspi_program` accepts
them directly.

## 2. `legacy/bin/mknetv2img`

A 53-line Python 3 script (`legacy/bin/mknetv2img`). It is a **standalone fork
of LiteX's `mkmscimg`**: `legacy/bin/mkmscimg` is a two-line shim that imports
`litex.soc.tools.mkmscimg`, whereas `mknetv2img` inlines and modifies the
implementation so it can be run on the Pi without a LiteX checkout.

Two modes, selected by `-f`/`--fbi` (`mknetv2img:46`):

- **without `-f`** — append the CRC32 to the file unchanged (`mknetv2img:37-39`);
- **with `-f`** — write a flash boot image: an 8-byte header followed by the
  payload with every 32-bit word byte-reversed.

The whole transformation:

```python
# legacy/bin/mknetv2img:15-36
    fcrc = binascii.crc32(fdata).to_bytes(4, byteorder=endian)
    flength = len(fdata).to_bytes(4, byteorder=endian)

    i = 0
    temp = bytearray(4)
    o_array = bytearray()
    for x in fdata:
        temp[i] = x
        i = i + 1
        if i == 4:
            o_array.append(temp[3])
            o_array.append(temp[2])
            o_array.append(temp[1])
            o_array.append(temp[0])
            i = 0

    with open(o_filename, "wb") as f:
        if fbi_mode:
            f.write(flength)
            f.write(fcrc)
            f.write(o_array)
```

Points that matter for a reimplementation:

1. **The header is big-endian by default.** `endian` is `"big"` unless
   `-l`/`--little` is passed (`mknetv2img:8`, `:47`), and neither
   `update-fpga.sh` nor `testing-fpga.sh` passes it. So a 131,072-byte payload
   writes the length as `00 02 00 00`.
2. **The length and CRC describe the *unswapped* data.** `flength` is
   `len(fdata)` and `fcrc` is `crc32(fdata)`, both taken before the swap loop.
   Only the payload is byte-reversed. *Inference:* the BIOS reads the flash
   through a 32-bit memory-mapped window whose word endianness is the opposite
   of the byte stream the programmer writes, so the swap cancels out and the
   BIOS's CRC over the loaded image matches `fcrc`.
3. **Bytes past the last whole word are silently dropped.** `temp` is only
   flushed into `o_array` when `i == 4` (`mknetv2img:24`), and there is no
   final partial-word flush. If the input length is not a multiple of 4, the
   written payload is shorter than `flength` says and the BIOS's CRC check
   fails. This is exactly the failure the updater's padding step exists to
   avoid, and its comment says so (`update-fpga.sh:73-78`).

Resulting FBI image for the shipped firmware: 4-byte length + 4-byte CRC +
131,072-byte payload = **131,080 bytes**, written at `0x7b0000`.

## 3. `update-fpga.sh`, step by step

`netv2mvp-scripts/update-fpga.sh` is the supported one-click updater. It assumes
`/home/pi/code/netv2-fpga` and `/home/pi/code/netv2mvp-scripts`
(`update-fpga.sh:8-9`) and refuses to guess if either is not a git checkout with
the expected origin.

| Step | Lines | What it does |
|---|---|---|
| 1. Update scripts | `:11-20` | `git pull origin master` in `netv2mvp-scripts`; aborts with a message naming the expected remote if it fails |
| 2. Update images | `:22-30` | `git pull origin master` in `netv2-fpga` — the production images are versioned in that repo, so "updating the firmware" is a git pull |
| 3. **IDCODE gate** | `:33-52` | runs `openocd -f idcode.cfg`, greps `tap/device found: <hex>` out of the output, and maps it: `0x0362d093` → 35T, `0x13631093` → 100T, **anything else aborts**. This is the only guard against writing a 100T bitstream to a 35T part |
| 4. Select images | `:54-68` | 35T → `user-35.bit` + `bscan_spi_xc7a35t.bit`; 100T → `user-100.bit` + `bscan_spi_xc7a100t.bit` |
| 5. Pad | `:69-86` | `cp` the firmware to `/tmp/ufirmware.bin`, then `dd if=/dev/zero of=/tmp/ufirmware.bin bs=1 count=1 seek=131071` — a single zero byte at offset 131,071, which extends the file to exactly 131,072 bytes with the gap read back as zeros |
| 6. Wrap | `:80` | `mknetv2img -f --output /tmp/ufirmware.upl /tmp/ufirmware.bin` |
| 7. Burn firmware | `:87-98` | `openocd -c 'set FIRMWARE_FILE /tmp/ufirmware.upl' -c 'set BSCAN_FILE …' -f cl-firmware.cfg` |
| 8. Burn gateware | `:100-111` | `openocd -c 'set FPGAIMAGE …' -c 'set BSCAN_FILE …' -f cl-spifpga.cfg`, described in the script as taking about a minute |
| 9. Wait for a keypress | `:113-116` | `read dummy` before exiting, so the window stays open on a desktop |

Every step checks `$?` and stops on failure. All four OpenOCD invocations run
under `sudo`, because bit-banged GPIO JTAG needs direct `/dev/mem` access.

Note that the padding target, 131,072 bytes, is 128 KiB — not the 320 KiB the
region reserves. The comment at `:73-78` explains the real purpose: the padding
is there to force a length divisible by 4 so the CRC succeeds, and 128 KiB was
chosen as a convenient deterministic fill.

`legacy/testing-images/testing-fpga.sh` is the same script with three
differences: it takes a `pcb`/`cable` argument selecting which overlay-cabling
build to install (`testing-fpga.sh:13-30`, `:76-88`), it pulls images from
`testing-images/` rather than `production-images/` (`:100`, `:125`), and its
second `git pull origin` at `:45` is missing the branch name.

### The OpenOCD config chain

Each `cl-*.cfg` is four lines of setup and three of work. `cl-firmware.cfg` in
full:

```tcl
# netv2mvp-scripts/cl-firmware.cfg:5-17
source [find interface/alphamax-rpi.cfg]

source [find cpld/xilinx-xc7.cfg]
source [find cpld/jtagspi.cfg]

init

jtagspi_init 0 $BSCAN_FILE
jtagspi_program $FIRMWARE_FILE 0x7b0000

xc7_program xc7.tap

exit
```

`cl-spifpga.cfg` is identical except for `jtagspi_program $FPGAIMAGE 0`
(`cl-spifpga.cfg:13`). The trailing `xc7_program xc7.tap` reloads the part from
the freshly written flash, so the update takes effect without a power cycle.

`jtagspi_init 0 $BSCAN_FILE` loads a **bscan_spi proxy bitstream** into the FPGA
first. This is a small design that bridges the JTAG USER chain to the FPGA's SPI
pins so that OpenOCD can drive the flash through the FPGA. The two proxies
shipped in the scripts repo, `bscan_spi_xc7a35t.bit` (251,209 B) and
`bscan_spi_xc7a100t.bit` (404,986 B), are the standard
[quartiq/bscan_spi_bitstreams](https://github.com/quartiq/bscan_spi_bitstreams)
builds; `docs/current/pi5-programming.md:219-228` documents fetching the same
two files from that upstream. The proxy is volatile — it lives in configuration
memory only until the `xc7_program` at the end of the script.

`interface/alphamax-rpi.cfg` is the Pi 3B+ adapter definition and must be
symlinked into OpenOCD's `scripts/interface/` directory
(`netv2mvp-scripts/README.md`, "assumes you have a symlink to alphamax-rpi.cfg
installed in `${INSTALLDIR}/interface/`"). Its substance:

| Setting | Value | Line |
|---|---|---|
| driver | `bcm2835gpio` | `:3` |
| transport | `jtag` | `:5` |
| chip name | `xc7a35t` | `:7` |
| peripheral base | `0x3F000000` (Pi 2/3) | `:10` |
| speed coefficients | `100000 5` | `:12` |
| TCK, TMS, TDI, TDO | GPIO 4, 17, 27, 22 | `:20` |
| SRST | GPIO 24, but `reset_config none` | `:26`, `:29` |
| adapter speed | `adapter_khz 10000` | `:33` |

The comment block at `:34-46` records two things that matter to anyone
reproducing this: the practical ceiling is about 5 MHz, not the 10 MHz
requested, because the driver has to read the GPIO state back to force a sync;
and the NeTV2 case needs a source patch raising the pad drive strength to 10 mA
at line 472 of `bcm2835gpio.c`. That, plus a separate speed fix, is why the
repository insists on the AlphamaxMedia OpenOCD fork rather than mainline
(`netv2mvp-scripts/README.md`, "Significantly, you *will* need to compile your
own version of openocd"; it claims roughly 20× the throughput of mainline).

`alphamax-rpi-4.cfg` is the same file translated to modern OpenOCD command
syntax (`adapter driver`, `adapter gpio tck 4`, `adapter speed 10000`;
`alphamax-rpi-4.cfg:3`, `:20-23`, `:36`) and is paired with
`cl-spifpga-rpi4.cfg`.

## 4. The other config scripts

| Script | Lines | What it does | Writes flash? | Resets FPGA? |
|---|---|---|---|---|
| `idcode.cfg` | 5-13 | sources the interface and `cpld/xilinx-xc7.cfg`, `init`, `scan_chain`, `exit` — prints the JTAG chain so the IDCODE can be grepped out. The **only** read-only script here | no | no |
| `reboot.cfg` | 3-13 | `scan_chain` then `xc7_program xc7.tap` — reports the IDCODE and reboots the FPGA from whatever is already in flash. Comment: "Report ID code and reboot the FPGA" | no | **yes** |
| `spi-erase.cfg` | 5-17 | loads the 35T proxy with `pld load 0 bscan_spi_xc7a35t.bit`, then `flash erase_address 0x0 0x800000` — **erases the entire 8 MB device**, bitstream and firmware alike, leaving the board unbootable until both are rewritten | **yes, all of it** | no |
| `spi-erase-firmware.cfg` | 5-17 | same proxy load, then `flash erase_address 0x7b0000 0x50000` — erases only the 320 KiB firmware region, leaving the bitstream intact so the BIOS still comes up and can be serial-booted | **yes, 320 KiB** | no |
| `cl-fpga.cfg` | 5-13 | `pld load 0 $BITFILE` — a **volatile** JTAG configuration load; nothing is written to flash and the next reset reverts | no | replaces config |
| `fpga-jtag.cfg` | 11 | as above with the filename hard-coded to `top.bit` | no | replaces config |
| `spi-jtag.cfg` | 13-15 | `jtagspi_program top.bin 0` then `xc7_program` — burn a locally built bitstream | **yes** | yes |
| `firmware-jtag.cfg` | 13-15 | `jtagspi_program firmware.bin 0x7b0000` then `xc7_program` — burn a locally built firmware. Note it expects a **raw** `firmware.bin`, not an FBI image | **yes** | yes |

Both `spi-erase*.cfg` hard-code the 35T proxy bitstream (`spi-erase.cfg:12`,
`spi-erase-firmware.cfg:12`) and take no `$BSCAN_FILE` variable, so they cannot
be used unmodified on a 100T board.

`cl-fpga.cfg` and `fpga-jtag.cfg` are the only entries in this table that are
non-destructive to flash. They are the mechanism behind the golden unit's
permitted "volatile JTAG load", together with the requirement that every such
run ends by reloading the stock bitstream.
