"""Client for the rpiz-3 source agent (see agent/netv2_source_agent.py).

python 3.5 compatible.  Includes NTP-style clock-offset estimation so that
flip timestamps from rpiz-3 can be compared with capture timestamps taken
on rpi3-netv2 (both CLOCK_MONOTONIC, different machines).
"""

import json
import socket
import time


class AgentError(Exception):
    pass


class SourceAgent(object):
    def __init__(self, host, port=5910, timeout=10.0):
        self.host = host
        self.port = port
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.sock.makefile("rw")
        self.offset = None      # remote_monotonic - local_monotonic
        self.offset_err = None  # +- bound (half of min RTT)

    def close(self):
        try:
            self.f.close()
        finally:
            self.sock.close()

    def call(self, cmd, **kw):
        req = dict(kw)
        req["cmd"] = cmd
        self.f.write(json.dumps(req) + "\n")
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise AgentError("agent closed connection")
        resp = json.loads(line)
        if not resp.get("ok"):
            raise AgentError(resp.get("error", "unknown error"))
        return resp

    # ---- convenience --------------------------------------------------------
    def info(self):
        return self.call("info")

    def edid(self):
        return bytes.fromhex(self.call("edid")["edid_hex"])

    def mode(self, w, h, refresh=60):
        return self.call("mode", w=w, h=h, refresh=refresh)

    def pattern(self, name, **params):
        return self.call("pattern", name=name, **params)

    def counter(self, enable, rgb_bg=(0, 0, 0)):
        return self.call("counter", enable=bool(enable), rgb_bg=list(rgb_bg))

    def flips(self, since=-1):
        return self.call("flips", since=since)["flips"]

    def dpms(self, on):
        return self.call("dpms", on=bool(on))

    def audio(self, hz, seconds):
        return self.call("audio", hz=hz, seconds=seconds)

    # ---- clock sync ---------------------------------------------------------
    def sync_clock(self, n=50):
        """Estimate remote-local monotonic offset from the min-RTT ping.

        Returns (offset, half_min_rtt).  local + offset == remote.
        """
        best = None
        rtts = []
        for _ in range(n):
            t0 = time.monotonic()
            r = self.call("ping")
            t1 = time.monotonic()
            rtt = t1 - t0
            rtts.append(rtt)
            off = r["t"] - (t0 + t1) / 2.0
            if best is None or rtt < best[0]:
                best = (rtt, off)
        self.offset = best[1]
        self.offset_err = best[0] / 2.0
        rtts.sort()
        self.rtt_stats = {"min_ms": rtts[0] * 1e3, "median_ms": rtts[len(rtts) // 2] * 1e3, "max_ms": rtts[-1] * 1e3, "n": n}
        return self.offset, self.offset_err

    def remote_to_local(self, t_remote):
        if self.offset is None:
            raise AgentError("sync_clock() not called")
        return t_remote - self.offset
