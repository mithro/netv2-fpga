#!/usr/bin/env python3
"""Probe the HDMI DDC (i2c-2 on rpiz-3) for EDID (0x50) and an HDCP receiver (0x3a).

Tells us whether anything downstream presents an HDCP receiver (BKSV) that the
Pi transmitter would authenticate against.
"""
import fcntl
import os
import sys

I2C_SLAVE = 0x0703
BUS = int(sys.argv[1]) if len(sys.argv) > 1 else 2


def rd(addr, offset, n):
    fd = os.open("/dev/i2c-%d" % BUS, os.O_RDWR)
    try:
        fcntl.ioctl(fd, I2C_SLAVE, addr)
        os.write(fd, bytes([offset]))
        return os.read(fd, n)
    finally:
        os.close(fd)


def show(label, addr, offset, n):
    try:
        d = rd(addr, offset, n)
        print("  %-22s addr 0x%02x +0x%02x: %s" % (label, addr, offset, " ".join("%02x" % b for b in d)))
        return d
    except Exception as e:  # noqa: BLE001
        print("  %-22s addr 0x%02x +0x%02x: FAIL %r" % (label, addr, offset, e))
        return None


print("== DDC probe on i2c-%d ==" % BUS)
edid = show("EDID header", 0x50, 0x00, 8)
if edid and edid[:8] == bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00]):
    print("    -> valid EDID header (a sink EEPROM is present)")
bksv = show("HDCP BKSV", 0x3A, 0x00, 5)
if bksv:
    ones = bin(int.from_bytes(bksv, "little")).count("1")
    print("    -> BKSV ones=%d (valid HDCP receiver needs exactly 20)" % ones)
show("HDCP BCAPS", 0x3A, 0x40, 1)
show("HDCP BSTATUS", 0x3A, 0x41, 2)
show("HDCP Ri'", 0x3A, 0x08, 2)
