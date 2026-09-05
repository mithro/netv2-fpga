#!/usr/bin/env python3
"""
Minimal raw-socket sniffer (AF_PACKET) for one interface, no external deps.
Prints a one-line summary of each Ethernet frame's IPv4/UDP/ICMP contents.
Run with sudo. Used to see whether the NeTV2 emits any Etherbone reply.

    sudo python3 eth_sniff.py --iface eth-netv2 --seconds 8
"""
import argparse
import socket
import struct
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iface", default="eth-netv2")
    ap.add_argument("--seconds", type=float, default=8.0)
    args = ap.parse_args()

    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
    s.bind((args.iface, 0))
    s.settimeout(0.5)
    print(f"sniffing {args.iface} for {args.seconds}s", flush=True)
    end = time.monotonic() + args.seconds
    n = 0
    while time.monotonic() < end:
        try:
            frame = s.recv(65535)
        except socket.timeout:
            continue
        if len(frame) < 14:
            continue
        dst = frame[0:6].hex(":")
        src = frame[6:12].hex(":")
        etype = struct.unpack(">H", frame[12:14])[0]
        if etype != 0x0800:
            print(f"eth {src}->{dst} type=0x{etype:04x}", flush=True)
            continue
        ip = frame[14:]
        ihl = (ip[0] & 0xf) * 4
        proto = ip[9]
        sip = socket.inet_ntoa(ip[12:16])
        dip = socket.inet_ntoa(ip[16:20])
        if proto == 17:  # UDP
            udp = ip[ihl:]
            sport, dport, ulen = struct.unpack(">HHH", udp[0:6])
            payload = udp[8:8 + (ulen - 8 if ulen >= 8 else 0)]
            print(f"UDP {sip}:{sport} -> {dip}:{dport} len={ulen} "
                  f"payload={payload[:32].hex()}", flush=True)
        elif proto == 1:  # ICMP
            print(f"ICMP {sip} -> {dip} type={ip[ihl]}", flush=True)
        else:
            print(f"IP proto={proto} {sip} -> {dip}", flush=True)
        n += 1
    print(f"done, {n} IP frames", flush=True)


if __name__ == "__main__":
    main()
