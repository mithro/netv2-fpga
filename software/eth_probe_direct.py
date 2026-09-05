#!/usr/bin/env python3
"""
Direct Etherbone probe (no external deps) for running ON the machine cabled to
the NeTV2. Sends the exact 12-byte LiteX Etherbone probe packet
(magic 0x4e6f, version 1, pf=1, addr/port size 4, + 4B padding) to the SoC's
UDP:1234 and waits for the probe reply (pr=1).

    python3 eth_probe_direct.py --ip 10.0.11.2
"""
import argparse
import socket
import sys

import os
PROBE = bytes.fromhex(os.environ.get("PROBE_HEX", "4e6f114400000000" "00000000"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="10.0.11.2")
    ap.add_argument("--port", type=int, default=1234)
    ap.add_argument("--bind-port", type=int, default=0,
                    help="Local source port (0=ephemeral, 1234=match litex).")
    ap.add_argument("--retries", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=1.0)
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", args.bind_port))
    s.settimeout(args.timeout)
    local = s.getsockname()
    print(f"probe -> {args.ip}:{args.port} from local port {local[1]} "
          f"payload={PROBE.hex()}", flush=True)

    for r in range(args.retries):
        s.sendto(PROBE, (args.ip, args.port))
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            print(f"  timeout {r+1}/{args.retries}", flush=True)
            continue
        print(f"REPLY from {addr}: {data.hex()} ({len(data)}B)", flush=True)
        # Byte 2 holds version/flags; pr is bit1.
        if len(data) >= 3:
            flags = data[2]
            print(f"  flags=0x{flags:02x} pr={ (flags>>1)&1 } pf={flags&1}", flush=True)
        print("ETHERBONE PROBE OK", flush=True)
        return 0
    print("NO REPLY (etherbone probe failed)", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
