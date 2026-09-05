#!/usr/bin/env python3
"""
Minimal single-socket bidirectional UDP relay (no external deps).

Used to reach the NeTV2 SoC's Etherbone UDP port from a host that is not on the
NeTV2's L2 segment: run this on the machine that IS cabled to the NeTV2 (the
rpi5 test rig), and point litex_server at this relay's host:port.

One socket bound to <listen port> is used for BOTH directions, so the source
port toward the NeTV2 is preserved as the listen port (1234) -- LiteX's
CommUDP binds and sends from port 1234, and some peers key replies on it, so
this matches native litex_server behaviour. Packets whose source IP is the
target are treated as replies (forwarded to the last client); everything else
is treated as a client request (forwarded to the target).

    python3 udp_relay.py --listen 0.0.0.0:1234 --target 10.0.11.2:1234
"""
import argparse
import socket


def parse_hostport(s, default_host="0.0.0.0"):
    if ":" in s:
        h, p = s.rsplit(":", 1)
        return (h or default_host, int(p))
    return (default_host, int(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="0.0.0.0:1234")
    ap.add_argument("--target", default="10.0.11.2:1234")
    args = ap.parse_args()

    listen = parse_hostport(args.listen)
    target = parse_hostport(args.target)
    target_ip = socket.gethostbyname(target[0])

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(listen)
    s.settimeout(120)

    print(f"relay {listen} <-> {target} (single-socket)", flush=True)
    client = None
    n = 0
    while True:
        try:
            data, addr = s.recvfrom(65535)
        except socket.timeout:
            print("idle timeout, exit", flush=True)
            return
        n += 1
        if addr[0] == target_ip:
            # Reply from the NeTV2 -> back to the last client.
            if client is not None:
                s.sendto(data, client)
                print(f"[{n}] netv2<-{addr} {len(data)}B -> {client}", flush=True)
        else:
            # Request from a client -> to the NeTV2.
            client = addr
            s.sendto(data, target)
            print(f"[{n}] client<-{addr} {len(data)}B -> {target} hex={data.hex()}", flush=True)


if __name__ == "__main__":
    main()
