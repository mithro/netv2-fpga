"""Minimal V4L2 mmap capture in pure python (python 3.5 compatible).

Targets a 32-bit ARM kernel (struct layouts below are for armhf).  Used on
rpi3-netv2 (Raspbian 9, kernel 4.14) to stream from the "HD TO USB" capture
card so that (a) HPD stays asserted toward the NeTV2 and (b) every frame
carries the kernel's CLOCK_MONOTONIC timestamp.

    cap = Capture("/dev/video0")
    cap.set_format(720, 480, "YUYV", fps=60)
    cap.start()
    frames = cap.record(120)          # list of Frame
    f = cap.latest()                  # most recent Frame (copy)
    cap.stop(); cap.close()
"""

import fcntl
import mmap
import os
import select
import struct
import threading
import time

# ---- ioctl plumbing --------------------------------------------------------
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2


def _IOC(d, t, nr, size):
    return (d << _IOC_DIRSHIFT) | (ord(t) << _IOC_TYPESHIFT) | (nr << _IOC_NRSHIFT) | (size << _IOC_SIZESHIFT)


def _IOWR(t, nr, size):
    return _IOC(_IOC_READ | _IOC_WRITE, t, nr, size)


def _IOW(t, nr, size):
    return _IOC(_IOC_WRITE, t, nr, size)


SIZEOF_V4L2_FORMAT = 204         # 32-bit ARM: union at offset 4 (verified with gcc on rpi3-netv2)
SIZEOF_V4L2_STREAMPARM = 204
SIZEOF_V4L2_REQUESTBUFFERS = 20
SIZEOF_V4L2_BUFFER = 68          # 32-bit ARM, timeval = 2 x 32-bit long

VIDIOC_S_FMT = _IOWR("V", 5, SIZEOF_V4L2_FORMAT)
VIDIOC_G_FMT = _IOWR("V", 4, SIZEOF_V4L2_FORMAT)
VIDIOC_REQBUFS = _IOWR("V", 8, SIZEOF_V4L2_REQUESTBUFFERS)
VIDIOC_QUERYBUF = _IOWR("V", 9, SIZEOF_V4L2_BUFFER)
VIDIOC_QBUF = _IOWR("V", 15, SIZEOF_V4L2_BUFFER)
VIDIOC_DQBUF = _IOWR("V", 17, SIZEOF_V4L2_BUFFER)
VIDIOC_STREAMON = _IOW("V", 18, 4)
VIDIOC_STREAMOFF = _IOW("V", 19, 4)
VIDIOC_S_PARM = _IOWR("V", 22, SIZEOF_V4L2_STREAMPARM)

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_NONE = 1


def fourcc(s):
    return struct.unpack("<I", s.encode("ascii"))[0]


class Frame(object):
    __slots__ = ("data", "timestamp", "sequence", "bytesused", "width", "height", "pixfmt", "t_dequeued")

    def __init__(self, data, timestamp, sequence, bytesused, width, height, pixfmt, t_dequeued):
        self.data = data
        self.timestamp = timestamp
        self.sequence = sequence
        self.bytesused = bytesused
        self.width = width
        self.height = height
        self.pixfmt = pixfmt
        self.t_dequeued = t_dequeued


class Capture(object):
    def __init__(self, device="/dev/video0", nbufs=4):
        self.device = device
        self.fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
        self.nbufs = nbufs
        self.bufs = []
        self.width = 0
        self.height = 0
        self.pixfmt = ""
        self.sizeimage = 0
        self.streaming = False
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Condition()
        self._latest = None
        self._recording = None      # list being filled, or None
        self._record_want = 0
        self.frames_total = 0
        self.frames_dropped = 0     # sequence gaps reported by the driver
        self.frames_short = 0       # incomplete raw frames discarded
        self._last_seq = None

    # ---- format ---------------------------------------------------------
    def set_format(self, width, height, pixfmt, fps=None):
        was = self.streaming
        if was:
            self.stop()
        fmt = bytearray(SIZEOF_V4L2_FORMAT)
        struct.pack_into("<I", fmt, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into("<IIII", fmt, 4, width, height, fourcc(pixfmt), V4L2_FIELD_NONE)
        fcntl.ioctl(self.fd, VIDIOC_S_FMT, fmt)
        w, h, pf, field, bpl, size = struct.unpack_from("<IIIIII", fmt, 4)
        if w != width or h != height or pf != fourcc(pixfmt):
            raise RuntimeError("driver refused %dx%d %s (got %dx%d %08x)" % (width, height, pixfmt, w, h, pf))
        self.width, self.height, self.pixfmt, self.sizeimage = w, h, pixfmt, size
        if fps:
            parm = bytearray(SIZEOF_V4L2_STREAMPARM)
            struct.pack_into("<I", parm, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
            # capability, capturemode, timeperframe.numerator, .denominator
            struct.pack_into("<IIII", parm, 4, 0, 0, 1, int(fps))
            fcntl.ioctl(self.fd, VIDIOC_S_PARM, parm)
            num, den = struct.unpack_from("<II", parm, 12)
            self.fps = float(den) / float(num) if num else 0.0
        else:
            self.fps = None
        if was:
            self.start()

    # ---- buffers / streaming ---------------------------------------------
    def _reqbufs(self, count):
        rb = bytearray(SIZEOF_V4L2_REQUESTBUFFERS)
        struct.pack_into("<III", rb, 0, count, V4L2_BUF_TYPE_VIDEO_CAPTURE, V4L2_MEMORY_MMAP)
        fcntl.ioctl(self.fd, VIDIOC_REQBUFS, rb)
        return struct.unpack_from("<I", rb, 0)[0]

    def _buffer_struct(self, index):
        b = bytearray(SIZEOF_V4L2_BUFFER)
        struct.pack_into("<II", b, 0, index, V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into("<I", b, 48, V4L2_MEMORY_MMAP)   # memory field
        return b

    def start(self):
        if self.streaming:
            return
        n = self._reqbufs(self.nbufs)
        if n < 2:
            raise RuntimeError("only %d buffers" % n)
        self.bufs = []
        for i in range(n):
            b = self._buffer_struct(i)
            fcntl.ioctl(self.fd, VIDIOC_QUERYBUF, b)
            length = struct.unpack_from("<I", b, 56)[0]
            offset = struct.unpack_from("<I", b, 52)[0]   # union m.offset
            m = mmap.mmap(self.fd, length, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=offset)
            self.bufs.append((m, length))
            fcntl.ioctl(self.fd, VIDIOC_QBUF, self._buffer_struct(i))
        fcntl.ioctl(self.fd, VIDIOC_STREAMON, struct.pack("<I", V4L2_BUF_TYPE_VIDEO_CAPTURE))
        self.streaming = True
        self._last_seq = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="v4l2cap")
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        if not self.streaming:
            return
        self._stop.set()
        self._thread.join(timeout=5)
        try:
            fcntl.ioctl(self.fd, VIDIOC_STREAMOFF, struct.pack("<I", V4L2_BUF_TYPE_VIDEO_CAPTURE))
        finally:
            for m, _ in self.bufs:
                m.close()
            self.bufs = []
            self._reqbufs(0)
            self.streaming = False

    def close(self):
        self.stop()
        os.close(self.fd)

    # ---- capture loop ------------------------------------------------------
    def _dequeue(self, timeout=2.0):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        b = self._buffer_struct(0)
        try:
            fcntl.ioctl(self.fd, VIDIOC_DQBUF, b)
        except OSError:
            return None
        index, btype, bytesused, flags, field = struct.unpack_from("<IIIII", b, 0)
        tv_sec, tv_usec = struct.unpack_from("<ii", b, 20)
        sequence = struct.unpack_from("<I", b, 44)[0]
        ts = tv_sec + tv_usec / 1e6
        m, length = self.bufs[index]
        data = bytes(m[:bytesused])
        fcntl.ioctl(self.fd, VIDIOC_QBUF, self._buffer_struct(index))
        return Frame(data, ts, sequence, bytesused, self.width, self.height, self.pixfmt, time.monotonic())

    def _loop(self):
        while not self._stop.is_set():
            f = self._dequeue()
            if f is None:
                continue
            if f.bytesused == 0:
                continue
            if self.pixfmt != "MJPG" and f.bytesused != self.sizeimage:
                # USB isochronous drop -> short raw frame; discard it.
                self.frames_short += 1
                continue
            self.frames_total += 1
            if self._last_seq is not None and f.sequence > self._last_seq + 1:
                self.frames_dropped += f.sequence - self._last_seq - 1
            self._last_seq = f.sequence
            with self._lock:
                self._latest = f
                if self._recording is not None:
                    self._recording.append(f)
                    if len(self._recording) >= self._record_want:
                        self._record_want = 0
                self._lock.notify_all()

    # ---- consumer API ---------------------------------------------------
    def latest(self, min_timestamp=None, timeout=5.0):
        """Newest frame; if min_timestamp is given, wait for a frame captured
        after that monotonic time (so callers can 'wait for a fresh frame')."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while True:
                f = self._latest
                if f is not None and (min_timestamp is None or f.timestamp > min_timestamp):
                    return f
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("no frame within %.1fs" % timeout)
                self._lock.wait(remaining)

    def fresh(self, settle=0.3, timeout=5.0):
        """A frame captured at least `settle` seconds from now (lets the
        pipeline propagate a change made just before the call)."""
        return self.latest(min_timestamp=time.monotonic() + settle, timeout=timeout + settle)

    def record(self, n, timeout=30.0):
        with self._lock:
            self._recording = []
            self._record_want = n
        deadline = time.monotonic() + timeout
        with self._lock:
            while len(self._recording) < n:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._lock.wait(remaining)
            out = self._recording
            self._recording = None
            self._record_want = 0
        return out
