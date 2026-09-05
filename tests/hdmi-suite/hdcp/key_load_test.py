#!/usr/bin/env python3
"""Step 2: exercise the BCM2835 HDCP key-RAM loader START/DONE handshake.

Loads a few test key indices into the key RAM at 0x7e809000 and observes the
KEY_CTL handshake. This does NOT enable encryption and does not touch the video
datapath (the key loader is a separate block), so it is safe on a live display.
Test key values are arbitrary (mechanism check only) -- no real key material.
"""
import mmap
import os
import struct
import time

PERI_BASE = 0x20000000
PAGE = 4096
KEY_BUS = 0x7E809000

CTL, ADR, KY0, KY1 = 0x00, 0x04, 0x08, 0x0C
START, DONE, DISHDCP = 1 << 0, 1 << 1, 1 << 2


def phys(bus):
    return (bus & 0x00FFFFFF) | PERI_BASE


def main():
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    base = phys(KEY_BUS) & ~(PAGE - 1)
    m = mmap.mmap(fd, PAGE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=base)

    def rd(off):
        m.seek(off)
        return struct.unpack("<I", m.read(4))[0]

    def wr(off, val):
        m.seek(off)
        m.write(struct.pack("<I", val & 0xFFFFFFFF))

    print("initial KEY_CTL = 0x%08x (START=%d DONE=%d DISHDCP=%d)" % (
        rd(CTL), bool(rd(CTL) & START), bool(rd(CTL) & DONE), bool(rd(CTL) & DISHDCP)))

    # load 4 test key indices; observe handshake per index
    tests = [(0, 0xAABBCCDD, 0x00112233),
             (1, 0x01234567, 0x00089ABC),
             (2, 0xDEADBEEF, 0x00C0FFEE),
             (39, 0xFFFFFFFF, 0x00FFFFFF)]
    for idx, ky0, ky1 in tests:
        wr(ADR, idx)
        wr(KY0, ky0)
        wr(KY1, ky1)
        pre = rd(CTL)
        wr(CTL, START)                 # kick the load
        seq = []
        done = False
        t0 = time.time()
        for _ in range(200):
            c = rd(CTL)
            seq.append(c & 0x7)
            if c & DONE:
                done = True
                break
            if time.time() - t0 > 0.5:
                break
        # de-dup consecutive identical status nibbles for readability
        compact = []
        for s in seq:
            if not compact or compact[-1] != s:
                compact.append(s)
        print("idx %2d: pre=0x%x  after START, KEY_CTL[2:0] seq=%s  DONE=%s (%d polls)" % (
            idx, pre & 0x7, "->".join("0x%x" % s for s in compact), done, len(seq)))

    print("final KEY_CTL = 0x%08x" % rd(CTL))
    m.close()
    os.close(fd)


if __name__ == "__main__":
    main()
