#!/usr/bin/env python3
"""
Phase 8 raw UART capture for the NeTV2 LiteX SoC Ethernet bring-up.

Deliberately dumb: open the port, drain the boot burst, then send a fixed list
of BIOS commands, printing every byte received back verbatim. No prompt parsing,
so nothing is silently swallowed. Intended to be reloaded/booted while this runs.

Usage (on the Pi, unbuffered):
    sudo python3 -u phase8_eth_rawcap.py --port /dev/ttyAMA0
"""
import argparse
import sys
import time

import serial


def drain(ser, seconds):
    end = time.monotonic() + seconds
    out = bytearray()
    while time.monotonic() < end:
        b = ser.read(4096)
        if b:
            out += b
            sys.stdout.write(b.decode("utf-8", "replace"))
            sys.stdout.flush()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--boot-wait", type=float, default=12.0)
    args = ap.parse_args()

    cmds = [
        "",
        "help",
        "ident",
        # RMII PHY MDIO: dump std regs at the likely PHY addresses.
        "mdio_dump 0 8",
        "mdio_dump 1 8",
        "mdio_dump 2 8",
        "mdio_dump 3 8",
        # Individual key regs at phy 0/1: 0=BMCR 1=BMSR 2=ID1 3=ID2 5=ANLPAR.
        "mdio_read 0 1",
        "mdio_read 0 2",
        "mdio_read 0 3",
        "mdio_read 1 1",
        "mdio_read 1 2",
        "mdio_read 1 3",
    ]

    with serial.Serial(args.port, args.baud, timeout=0.3) as ser:
        print(f"\n##### RAWCAP open {args.port} @ {args.baud} #####", flush=True)
        print(f"##### draining boot for {args.boot_wait}s #####", flush=True)
        drain(ser, args.boot_wait)
        for c in cmds:
            print(f"\n##### CMD: {c!r} #####", flush=True)
            ser.reset_input_buffer()
            ser.write((c + "\r\n").encode())
            drain(ser, 1.2)
    print("\n##### RAWCAP DONE #####", flush=True)


if __name__ == "__main__":
    main()
