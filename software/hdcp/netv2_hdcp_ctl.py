#!/usr/bin/env python3
# ruff: noqa: UP032
# ruff UP032 (".format() -> f-string") is intentionally suppressed for this
# file: it must stay Python 3.5-syntax-valid (f-strings are 3.6+) so it can run
# on the golden-unit rig rpi3-netv2 (Raspbian 9, CPython 3.5).
"""Host-side control tool for the NeTV2 HDCP receiver.

Loads the receiver's 40 sink device keys and reads back its state over the
FPGA serial console using the LiteX BIOS ``mr`` / ``mw`` commands.  The most
important read-back is the *received* Aksv (``hdcprx_aksv``): the source
(a Raspberry Pi BCM2835) has no writable Aksv register and transmits whatever
KSV its provisioning yields, which need not equal any provisional
KSV_source.  The receiver latches whatever Aksv it sees, and ``status`` prints
it as ``A_actual`` so the RPi side can regenerate matching source keys and
close the provisioning loop.

Python 3.5 compatible on purpose: it runs on the golden-unit rig rpi3-netv2
(Raspbian 9, CPython 3.5) over ``/dev/ttyS0``.  Only the standard library and
pyserial are used -- no f-strings, no dataclasses, no walrus operator.  (The
repository's own interpreter is 3.13, so ``py_compile`` here proves nothing
stronger than the syntax being valid; the 3.5 constraint is honoured by
construction.)

CSR map / word order (verified, not guessed)
--------------------------------------------
The receiver's CSRs live in the LiteX SoC CSR map.  Addresses and word counts
are parsed from ``csr.csv`` (default ``legacy/build/hdcprx-35/csr.csv``) so a
rebuild that shifts the map is picked up automatically.

A LiteX CSR wider than the CSR bus word is broken into several sub-registers at
*consecutive word addresses* (stride 4 bytes), **most-significant word first**.
This is confirmed against the 2019 LiteX in
``legacy/deps/litex/litex/soc/interconnect/csr.py`` and its C accessor
generator ``legacy/deps/litex/litex/soc/integration/cpu_interface.py``:

  * ``CSRStatus.do_finalize`` / ``CSRStorage`` iterate
    ``for i in reversed(range(nwords))`` when emitting the sub-CSRs, so the
    first (lowest-address) sub-CSR carries the highest-order bits.
  * ``_get_rw_functions_c`` reads ``r = csr_readl(base); r <<= busword;
    r |= csr_readl(base + 4*byte)`` -- the word at ``base`` ends up in the most
    significant position -- and writes ``value >> ((nwords-word-1)*busword)`` to
    ``base + 4*word``.  Both are MSW-first with a 4-byte stride per sub-word.

The CSR bus word width (``csr_data_width``) for this build is **8 bits**, not
32.  That is proven by the ``csr.csv`` word-count column: ``get_csr_csv`` writes
``nr = (size_bits + busword - 1)//busword`` and lists ``hdcprx_bksv`` (a 40-bit
register) with ``nr = 5``, which only holds for ``busword == 8`` (40/8 = 5;
40/32 would give 2).  ``hdcprx_an`` (64b) -> 8, ``hdcprx_km_hw`` (56b) -> 7 and
``hdcprx_r0`` (16b) -> 2 all agree.  Each byte-wide sub-CSR occupies one 32-bit
CPU word slot (``origin += 4*nr``), so ``mr`` returns the byte in the low 8
bits; every read is masked to ``busword`` bits before assembly.
"""

import argparse
import json
import sys
import time

# CSR bus word width (csr_data_width) of this SoC build, in bits.  See the
# module docstring for the proof that this build uses a byte-wide CSR bus.
DEFAULT_BUSWORD = 8

# Sub-word address stride in the CPU memory map: each CSR sub-register occupies
# one 32-bit word slot regardless of csr_data_width (LiteX ``origin += 4*nr``).
WORD_STRIDE = 4

# HDCP device-key geometry (spec 1.4 section 2.2.1).
N_KEYS = 40
KEY_BYTES = 7  # one 56-bit device key, little-endian on disk

# Default CSR map shipped in the tree.
DEFAULT_CSR_CSV = "legacy/build/hdcprx-35/csr.csv"

# hdcprx_status bit layout, from netv2/gateware/hdcp/receiver.py (the Cat that
# drives self.status.status): bit0 rx_armed, bit1 keys_ok, bit2 km_valid,
# bit3 r0_valid (sticky), bit4 sda_driving.
STATUS_BITS = [
    (0, "rx_armed"),
    (1, "keys_ok"),
    (2, "km_valid"),
    (3, "r0_valid"),
    (4, "sda_driving"),
]


# --------------------------------------------------------------------------
# Serial console transport
# --------------------------------------------------------------------------
class Console:
    """Word-addressed transport interface: ``read_word`` / ``write_word``."""

    def read_word(self, addr):
        raise NotImplementedError

    def write_word(self, addr, val):
        raise NotImplementedError


class SerialConsole(Console):
    """A LiteX BIOS REPL reached over pyserial, driven with ``mr`` / ``mw``.

    ``mr <hexaddr> [count]`` prints ``0xADDR: 0xVAL0 0xVAL1 ...`` and
    ``mw <hexaddr> <hexval> [count]`` writes.  A single 32-bit word is read and
    written at a time; multi-word CSR assembly happens one level up.
    """

    def __init__(self, port, baud=115200, timeout=1.0):
        # Imported lazily so that MockConsole (and the unit tests) work with no
        # pyserial installed.
        import serial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.timeout = timeout

    def close(self):
        self.ser.close()

    def _send(self, line):
        self.ser.write((line + "\n").encode("ascii"))
        self.ser.flush()

    def _read_reply(self, addr):
        # Collect lines until we see the echoed "0xADDR:" data line for addr.
        want = "{:x}".format(addr)
        deadline = time.time() + max(self.timeout, 0.5) * 4
        buf = ""
        while time.time() < deadline:
            chunk = self.ser.read(256)
            if chunk:
                buf += chunk.decode("ascii", "replace")
            for raw in buf.splitlines():
                line = raw.strip()
                if ":" not in line:
                    continue
                left, right = line.split(":", 1)
                left = left.strip().lower()
                if left.endswith(want) and left.startswith("0x"):
                    return _parse_hex_words(right)
            if not chunk:
                time.sleep(0.02)
        raise OSError("no mr reply for address 0x{:08x}".format(addr))

    def read_word(self, addr):
        self._send("mr 0x{:x} 1".format(addr))
        words = self._read_reply(addr)
        if not words:
            raise OSError("empty mr reply for 0x{:08x}".format(addr))
        return words[0]

    def write_word(self, addr, val):
        self._send("mw 0x{:x} 0x{:x}".format(addr, val & 0xFFFFFFFF))


class MockConsole(Console):
    """Dict-backed fake console with the same interface, for the unit tests.

    ``writes`` records every ``(addr, val)`` in order so tests can assert on the
    exact word sequence a command emits.
    """

    def __init__(self, initial=None):
        self.mem = dict(initial or {})
        self.writes = []

    def read_word(self, addr):
        return self.mem.get(addr, 0) & 0xFFFFFFFF

    def write_word(self, addr, val):
        val = val & 0xFFFFFFFF
        self.mem[addr] = val
        self.writes.append((addr, val))


def _parse_hex_words(text):
    """Extract the ``0x..`` hex words from the data portion of an mr reply."""
    out = []
    for token in text.replace(",", " ").split():
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token, 16))
        except ValueError:
            continue
    return out


# --------------------------------------------------------------------------
# CSR map: parse csr.csv and read/write multi-word CSRs MSW-first
# --------------------------------------------------------------------------
class CsrMap:
    """Names -> (base address, sub-word count) parsed from ``csr.csv``."""

    def __init__(self, regs, busword=DEFAULT_BUSWORD):
        self.regs = regs  # name -> (addr, nwords, mode)
        self.busword = busword

    @classmethod
    def from_csv(cls, path, busword=DEFAULT_BUSWORD):
        regs = {}
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or not line.startswith("csr_register,"):
                    continue
                parts = line.split(",")
                if len(parts) < 5:
                    continue
                name = parts[1]
                addr = int(parts[2], 16)
                nwords = int(parts[3])
                mode = parts[4]
                regs[name] = (addr, nwords, mode)
        if not regs:
            raise ValueError("no csr_register rows found in {}".format(path))
        return cls(regs, busword)

    def addr(self, name):
        return self.regs[name][0]

    def nwords(self, name):
        return self.regs[name][1]

    def read(self, console, name):
        """Read an M-byte CSR: read its sub-words MSW-first and concatenate."""
        addr = self.regs[name][0]
        nwords = self.regs[name][1]
        mask = (1 << self.busword) - 1
        value = 0
        for i in range(nwords):
            word = console.read_word(addr + WORD_STRIDE * i) & mask
            value = (value << self.busword) | word
        return value

    def write(self, console, name, value):
        """Write a value into a CSR, splitting it MSW-first across sub-words."""
        addr = self.regs[name][0]
        nwords = self.regs[name][1]
        mask = (1 << self.busword) - 1
        for i in range(nwords):
            shift = (nwords - i - 1) * self.busword
            console.write_word(addr + WORD_STRIDE * i, (value >> shift) & mask)

    def pulse(self, console, name):
        """Strobe a one-shot CSR (LiteX ``CSR()`` write-to-trigger)."""
        self.write(console, name, 1)


# --------------------------------------------------------------------------
# Key / manifest loading (self-contained; no f-strings, stdlib only)
# --------------------------------------------------------------------------
def load_keys_bin(path):
    """Load the 280-byte device-key blob: 40 keys of 7 bytes, little-endian."""
    with open(path, "rb") as f:
        blob = f.read()
    want = N_KEYS * KEY_BYTES
    if len(blob) != want:
        raise ValueError(
            "{}: expected {} bytes, got {}".format(path, want, len(blob)))
    keys = []
    for i in range(N_KEYS):
        chunk = blob[i * KEY_BYTES:(i + 1) * KEY_BYTES]
        keys.append(_int_from_le(chunk))
    return keys


def _int_from_le(chunk):
    value = 0
    for i, byte in enumerate(bytearray(chunk)):
        value |= byte << (8 * i)
    return value


def load_manifest(path):
    """Load ``manifest.json`` and return ksv_sink as an int (from its hex str)."""
    with open(path) as f:
        manifest = json.load(f)
    ksv_sink = manifest.get("ksv_sink")
    if ksv_sink is None:
        raise ValueError("{}: manifest has no 'ksv_sink' field".format(path))
    if isinstance(ksv_sink, str):
        ksv_sink = int(ksv_sink, 16)
    return {"ksv_sink": manifest.get("ksv_sink"), "ksv_sink_int": ksv_sink}


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_load_keys(console, csrmap, keys_path, manifest_path, out=None):
    """Load 40 sink keys and Bksv into the receiver; verify keys_loaded == 40.

    Never prints any key byte -- only counts, indices and the (public) Bksv.
    """
    if out is None:
        out = sys.stdout
    keys = load_keys_bin(keys_path)
    manifest = load_manifest(manifest_path)

    for index in range(N_KEYS):
        key = keys[index]
        lo = key & 0xFFFFFFFF          # low 32 bits -> key_data_lo
        hi = (key >> 32) & 0xFFFFFF    # high 24 bits -> key_data_hi
        csrmap.write(console, "hdcprx_key_index", index)
        csrmap.write(console, "hdcprx_key_data_lo", lo)
        csrmap.write(console, "hdcprx_key_data_hi", hi)
        csrmap.pulse(console, "hdcprx_key_we")

    csrmap.write(console, "hdcprx_bksv", manifest["ksv_sink_int"])

    loaded = csrmap.read(console, "hdcprx_keys_loaded")
    out.write("loaded {} device keys\n".format(N_KEYS))
    out.write("Bksv (KSV_sink): 0x{:010x}\n".format(manifest["ksv_sink_int"]))
    out.write("keys_loaded (readback): {}\n".format(loaded))
    if loaded != N_KEYS:
        raise RuntimeError(
            "keys_loaded is {}, expected {}".format(loaded, N_KEYS))
    return loaded


def cmd_arm(console, csrmap, out=None):
    """Arm the receiver: km_source=1 (hardware Km), rx_enable=1."""
    if out is None:
        out = sys.stdout
    csrmap.write(console, "hdcprx_km_source", 1)
    csrmap.write(console, "hdcprx_rx_enable", 1)
    out.write("armed: km_source=1 rx_enable=1\n")


def cmd_clear(console, csrmap, out=None):
    """Clear the key store and keys_loaded counter."""
    if out is None:
        out = sys.stdout
    csrmap.pulse(console, "hdcprx_keys_clear")
    out.write("cleared key store\n")


def decode_status(value):
    """Return a list of (name, bit_value) for the hdcprx_status bits."""
    return [(name, (value >> bit) & 1) for bit, name in STATUS_BITS]


def cmd_status(console, csrmap, show_km=False, out=None):
    """Read and print the receiver state, surfacing the received Aksv."""
    if out is None:
        out = sys.stdout
    keys_loaded = csrmap.read(console, "hdcprx_keys_loaded")
    rx_enable = csrmap.read(console, "hdcprx_rx_enable")
    km_source = csrmap.read(console, "hdcprx_km_source")
    bksv = csrmap.read(console, "hdcprx_bksv")
    aksv = csrmap.read(console, "hdcprx_aksv")
    an = csrmap.read(console, "hdcprx_an")
    r0 = csrmap.read(console, "hdcprx_r0")
    ri = csrmap.read(console, "hdcprx_ri")
    status = csrmap.read(console, "hdcprx_status")

    out.write("keys_loaded : {}\n".format(keys_loaded))
    out.write("rx_enable   : {}\n".format(rx_enable))
    out.write("km_source   : {} ({})\n".format(
        km_source, "hardware Km" if km_source else "CPU Km"))
    out.write("Bksv        : 0x{:010x}\n".format(bksv))
    # The milestone read-back: the Aksv the source actually transmitted.
    out.write("received Aksv (A_actual): 0x{:010x}\n".format(aksv))
    out.write("An          : 0x{:016x}\n".format(an))
    out.write("R0'         : 0x{:04x}\n".format(r0))
    out.write("Ri'         : 0x{:04x}\n".format(ri))

    if show_km:
        km_hw = csrmap.read(console, "hdcprx_km_hw")
        out.write("Km (hw)     : 0x{:014x}\n".format(km_hw))
    else:
        out.write("Km (hw)     : <hidden; pass --show-km to reveal the secret>\n")

    out.write("status      : 0x{:02x}\n".format(status))
    for name, bit in decode_status(status):
        out.write("  {:<11}: {}\n".format(name, bit))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        description="NeTV2 HDCP receiver host control tool")
    parser.add_argument(
        "--port", default="/dev/ttyS0",
        help="serial port of the FPGA BIOS console "
             "(/dev/ttyS0 golden unit, /dev/ttyAMA0 Pi 5)")
    parser.add_argument(
        "--baud", type=int, default=115200, help="serial baud rate")
    parser.add_argument(
        "--csr", default=DEFAULT_CSR_CSV,
        help="path to the LiteX csr.csv CSR map")
    parser.add_argument(
        "--busword", type=int, default=DEFAULT_BUSWORD,
        help="CSR bus word width in bits (csr_data_width; this build is 8)")

    sub = parser.add_subparsers(dest="command")

    p_load = sub.add_parser("load-keys", help="load the 40 sink keys and Bksv")
    p_load.add_argument("--keys", required=True, help="sink_keys.bin path")
    p_load.add_argument("--manifest", required=True, help="manifest.json path")

    sub.add_parser("arm", help="set km_source=1 and rx_enable=1")

    p_status = sub.add_parser("status", help="print receiver state")
    p_status.add_argument(
        "--show-km", action="store_true",
        help="reveal the hardware Km shared secret (masked by default)")

    sub.add_parser("clear", help="pulse keys_clear")

    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    csrmap = CsrMap.from_csv(args.csr, busword=args.busword)
    console = SerialConsole(args.port, baud=args.baud)
    try:
        if args.command == "load-keys":
            cmd_load_keys(console, csrmap, args.keys, args.manifest)
        elif args.command == "arm":
            cmd_arm(console, csrmap)
        elif args.command == "status":
            cmd_status(console, csrmap, show_km=args.show_km)
        elif args.command == "clear":
            cmd_clear(console, csrmap)
        else:
            parser.print_help()
            return 2
    finally:
        close = getattr(console, "close", None)
        if close is not None:
            close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
