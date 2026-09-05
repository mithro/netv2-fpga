"""NeTV2 firmware console client (RUNTIME> prompt on /dev/ttyS0, 115200).

python 3.5 compatible; needs pyserial (present on rpi3-netv2).
"""

import json
import re
import time

import serial

PROMPT = "RUNTIME>"

STATUS_RE = re.compile(r"input(?P<idx>[01]):\s+(?P<h>\d+)x(?P<v>\d+)\s+\(@\s*(?P<mhz>[\d.\s]+)MHz\)")
XADC_RE = re.compile(r"xadc:\s+(?P<mc>-?\d+)\s+mC")
DDR_RE = re.compile(r"ddr: read:\s+(?P<r>\d+)Mbps\s+write:\s+(?P<w>\d+)Mbps\s+all:\s+(?P<a>\d+)Mbps")
DEBUG_RE = re.compile(
    r"hdmi_in0: ph:.*?charsync:(?P<charsync>\d{3}).*?WER:\s*(?P<wer0>\d+)\s+(?P<wer1>\d+)\s+(?P<wer2>\d+)"
    r".*?chansync:(?P<chansync>\d).*?res:(?P<h>\d+)x(?P<v>\d+)")


def parse_mhz(s):
    # firmware prints e.g. "148.49" or "  0. 0" (with a space after the dot)
    return float(s.replace(" ", ""))


class Console(object):
    def __init__(self, port="/dev/ttyS0", baud=115200):
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.log = []          # every raw chunk read, for evidence
        self.drain(0.3)

    def close(self):
        self.ser.close()

    def drain(self, seconds=0.2):
        deadline = time.monotonic() + seconds
        buf = b""
        while time.monotonic() < deadline:
            chunk = self.ser.read(4096)
            if chunk:
                buf += chunk
        if buf:
            self.log.append(buf.decode("utf-8", "replace"))
        return buf.decode("utf-8", "replace")

    def read_until_prompt(self, timeout=3.0):
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            chunk = self.ser.read(4096)
            if chunk:
                buf += chunk
                if buf.rstrip().endswith(PROMPT.encode()):
                    break
        text = buf.decode("utf-8", "replace")
        self.log.append(text)
        return text

    def command(self, cmd, timeout=3.0):
        """Send a command, return its output (echo and prompt stripped)."""
        self.drain(0.05)
        self.ser.write((cmd + "\r\n").encode())
        self.ser.flush()
        text = self.read_until_prompt(timeout)
        lines = text.replace("\r", "").split("\n")
        # drop the echoed command and prompt lines
        out = []
        for ln in lines:
            s = ln.strip()
            if s == cmd or s == PROMPT or s == "":
                continue
            if s.startswith(PROMPT):
                s = s[len(PROMPT):].strip()
                if not s:
                    continue
            out.append(ln.rstrip())
        return "\n".join(out)

    # ---- typed helpers ----------------------------------------------------
    def help(self):
        return self.command("help")

    def status(self):
        text = self.command("status")
        d = {"raw": text, "inputs": {}}
        for m in STATUS_RE.finditer(text):
            d["inputs"][int(m.group("idx"))] = {
                "hres": int(m.group("h")),
                "vres": int(m.group("v")),
                "mhz": parse_mhz(m.group("mhz")),
            }
        m = XADC_RE.search(text)
        if m:
            d["temp_c"] = int(m.group("mc")) / 1000.0
        m = DDR_RE.search(text)
        if m:
            d["ddr"] = {"read": int(m.group("r")), "write": int(m.group("w")), "all": int(m.group("a"))}
        return d

    def json_status(self):
        """One record from `json` (prints once when json mode is off)."""
        self.set_json(False)
        text = self.command("json", timeout=3.0)
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0:
            raise RuntimeError("no json record in: %r" % text)
        return json.loads(text[start:end + 1])

    def set_json(self, on):
        self.command("json on" if on else "json off")

    def dna(self):
        text = self.command("debug dna")
        m = re.search(r"DNA:\s*([0-9a-fA-F]+)", text)
        return m.group(1) if m else None

    def xadc_c(self):
        text = self.command("debug xadc")
        m = XADC_RE.search(text)
        return int(m.group("mc")) / 1000.0 if m else None

    def set_input0_debug(self, on):
        """`debug input0` toggles; normalise to the requested state."""
        for _ in range(2):
            text = self.command("debug input0")
            m = re.search(r"debug (on|off)", text)
            if m and (m.group(1) == "on") == on:
                return
        raise RuntimeError("could not set input0 debug to %r" % on)

    def input0_trace(self, seconds):
        """Collect `debug input0` lines for `seconds`; returns list of dicts."""
        self.set_input0_debug(True)
        try:
            deadline = time.monotonic() + seconds
            buf = b""
            while time.monotonic() < deadline:
                chunk = self.ser.read(4096)
                if chunk:
                    buf += chunk
        finally:
            self.set_input0_debug(False)
        text = buf.decode("utf-8", "replace")
        self.log.append(text)
        samples = []
        events = []
        for ln in text.replace("\r", "").split("\n"):
            m = DEBUG_RE.search(ln)
            if m:
                samples.append({
                    "charsync": m.group("charsync"),
                    "wer": [int(m.group("wer0")), int(m.group("wer1")), int(m.group("wer2"))],
                    "chansync": int(m.group("chansync")),
                    "hres": int(m.group("h")),
                    "vres": int(m.group("v")),
                })
            elif "hdmi_in0:" in ln:
                events.append(ln.strip())
        return {"samples": samples, "events": events, "raw_lines": text.count("\n")}

    # ---- overlay rectangle controls -----------------------------------------
    def rect_default(self):
        return self.command("debug rect")

    def rect_thresh(self, value):
        return self.command("debug rectthresh %d" % value)

    def set_rect(self, x0, x1, y0, y1):
        return self.command("debug setrect %d %d %d %d" % (x0, x1, y0, y1))

    def rect_off(self):
        return self.command("debug rectoff")
