#!/usr/bin/env python3
"""NeTV2 status reporter for Raspberry Pi OS "trixie".

Python 3 replacement for the 2019 ``netv2-status.js`` (node ``serialport`` +
``pm2``). It reads the SoC telemetry stream off the console UART and republishes
the latest record as JSON on ``http://127.0.0.1:6502/`` for the MagicMirror
``MMM-json-feed`` module to poll -- the same contract the node version served,
so ``config.js`` needs no change.

Behaviour, matching the original:

* open the UART at 115200 (``/dev/ttyS0`` on Pi 3, ``/dev/ttyAMA0`` on Pi 5);
* write ``json on`` once to ask the firmware REPL to emit telemetry;
* accumulate bytes, and on a line break parse the buffer as JSON only if it is
  longer than the length threshold (the original's "expect large JSON record"
  heuristic, default 200 chars) -- this ignores the REPL's own echo/banner;
* serve the last successfully parsed object at ``/``; ``{}`` until one arrives.

Improvements over the 2019 version: it reconnects if the serial port drops, it
takes host/port/threshold from the environment (see the systemd unit), and it
survives malformed lines without wedging.

The telemetry field names the firmware emits (readbw, writebw, per-input
ph0..2/charsync/sp0..2/wer0..2/chansync, x, y, pclk, temp) are defined by the
**overlay gateware/firmware**, which is a separate modernisation track. This
reporter is format-agnostic: it forwards whatever JSON object the firmware
sends. Until the modern overlay firmware emits that stream, ``/`` returns ``{}``.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover - environments without pyserial
    serial = None  # type: ignore[assignment]

DEFAULT_UART = os.environ.get("NETV2_STATUS_UART", "/dev/ttyS0")
DEFAULT_BAUD = int(os.environ.get("NETV2_STATUS_BAUD", "115200"))
DEFAULT_HTTP_HOST = os.environ.get("NETV2_STATUS_HTTP_HOST", "127.0.0.1")
DEFAULT_HTTP_PORT = int(os.environ.get("NETV2_STATUS_HTTP_PORT", "6502"))
# The original ignored anything shorter than 200 chars ("expect large JSON").
DEFAULT_MIN_LEN = int(os.environ.get("NETV2_STATUS_MIN_LEN", "200"))


class StatusStore:
    """Thread-safe holder for the most recent parsed telemetry object."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict = {}

    def set(self, obj: dict) -> None:
        with self._lock:
            self._latest = obj

    def get_json(self) -> bytes:
        with self._lock:
            return json.dumps(self._latest).encode("utf-8")


def parse_line(buffer: str, min_len: int = DEFAULT_MIN_LEN) -> dict | None:
    """Return a parsed JSON object from ``buffer`` if it qualifies, else None.

    Mirrors the node heuristic: only attempt ``json.loads`` on buffers longer
    than ``min_len`` and yielding a JSON object. Any parse failure returns None
    (the caller clears the buffer), so REPL echo lines are ignored.
    """
    if len(buffer) <= min_len:
        return None
    try:
        obj = json.loads(buffer)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def make_handler(store: StatusStore):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = store.get_json()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):  # silence default stderr logging
            pass

    return Handler


def serial_loop(
    store: StatusStore,
    uart: str = DEFAULT_UART,
    baud: int = DEFAULT_BAUD,
    min_len: int = DEFAULT_MIN_LEN,
    stop: threading.Event | None = None,
) -> None:
    """Read telemetry from the UART forever, updating ``store``.

    Reconnects with backoff if the port cannot be opened or drops.
    """
    if serial is None:
        raise RuntimeError("pyserial is not installed; cannot read the UART")
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            with serial.Serial(uart, baud, timeout=1) as port:
                port.write(b"json on\n\r")
                buffer = ""
                while not stop.is_set():
                    chunk = port.read(256)
                    if not chunk:
                        continue
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer or "\r" in buffer:
                        idx = min(
                            (buffer.index(c) for c in "\r\n" if c in buffer),
                        )
                        line, buffer = buffer[:idx], buffer[idx + 1 :]
                        obj = parse_line(line, min_len)
                        if obj is not None:
                            store.set(obj)
        except (OSError, ValueError):
            # serial.SerialException is an OSError; port disappeared or open
            # failed. Back off and retry.
            time.sleep(2.0)


def main() -> int:
    store = StatusStore()
    reader = threading.Thread(
        target=serial_loop,
        args=(store, DEFAULT_UART, DEFAULT_BAUD, DEFAULT_MIN_LEN),
        daemon=True,
    )
    reader.start()
    server = ThreadingHTTPServer((DEFAULT_HTTP_HOST, DEFAULT_HTTP_PORT), make_handler(store))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
