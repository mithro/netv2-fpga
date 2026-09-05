#!/usr/bin/env python3
"""Send one or more commands to the NeTV2 firmware console and print replies.

Runs on rpi3-netv2 (python 3.5, pyserial). The NeTV2 LiteX firmware console
is on the RPi mini-UART (/dev/ttyS0 == /dev/serial0) at 115200 baud.

Usage:
    python3 netv2_serial.py [--port /dev/ttyS0] [--wait 2.0] "status" "debug edid"
    python3 netv2_serial.py --listen 10        # just print whatever arrives for 10s
"""
import argparse
import sys
import time

import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyS0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--wait", type=float, default=2.0,
                    help="seconds to collect output after each command")
    ap.add_argument("--listen", type=float, default=0.0,
                    help="seconds to listen before sending anything")
    ap.add_argument("commands", nargs="*")
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)

    def collect(seconds):
        deadline = time.monotonic() + seconds
        buf = b""
        while time.monotonic() < deadline:
            chunk = ser.read(4096)
            if chunk:
                buf += chunk
        text = buf.decode("utf-8", errors="replace")
        sys.stdout.write(text)
        sys.stdout.flush()
        return text

    if args.listen:
        print("--- listening for {}s ---".format(args.listen))
        collect(args.listen)

    for cmd in args.commands:
        print("\n--- sending: {!r} ---".format(cmd))
        ser.write((cmd + "\r\n").encode())
        ser.flush()
        collect(args.wait)
    print()
    ser.close()


if __name__ == "__main__":
    main()
