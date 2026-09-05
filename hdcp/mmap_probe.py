#!/usr/bin/env python3
"""Read-only probe of the BCM2835 HDCP register blocks via /dev/mem.

Answers the decisive question: do the HDCP key-loader (0x7e809000) and the
HDMI-core CP registers (0x7e902000) respond, or are they power/enable-gated?

BCM2835: VideoCore bus 0x7Exxxxxx == ARM-physical 0x20xxxxxx.
Register names/offsets from Broadcom's generated headers (rpi-open-firmware
broadcom/bcm2708_chip/hdcp.h + hdmicore.h), cross-checked against the GPL STB
bchp_hdmi.h and the paulwratt RE map (all three agree).

Read-only: no writes, no key material, no encryption enable. Safe on a live
display.
"""
import mmap
import os
import struct
import sys

PERI_BASE = 0x20000000  # BCM2835 ARM-physical base for VC bus 0x7E000000
PAGE = 4096


def bus_to_phys(bus):
    return (bus & 0x00FFFFFF) | PERI_BASE


BLOCKS = [
    ("HDCP key-loader (0x7e809000)", 0x7E809000, [
        ("KEY_CTL", 0x00), ("KEY_ADR", 0x04), ("KEY_KY0", 0x08), ("KEY_KY1", 0x0C),
    ]),
    ("HDMI core (0x7e902000)", 0x7E902000, [
        ("CORE_REV", 0x00), ("SW_RESET", 0x04), ("HOTPLUG_INT", 0x08), ("HOTPLUG", 0x0C),
        ("BKSV0", 0x10), ("BKSV1", 0x14), ("AN0", 0x18), ("AN1", 0x1C),
        ("KSV_FIFO_0", 0x30), ("KSV_FIFO_1", 0x34),
        ("HDCP_KEY_1", 0x3C), ("HDCP_KEY_2", 0x40), ("HDCP_CTL", 0x44),
        ("CP_STATUS", 0x48), ("CP_INTEGRITY", 0x4C), ("CP_INTEGRITY_CFG", 0x50),
        ("CP_CONFIG", 0x54), ("CP_TST", 0x58),
    ]),
]


def probe():
    try:
        fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    except PermissionError as e:
        print("cannot open /dev/mem (need root): %r" % e)
        return 1
    rc = 0
    for name, bus, regs in BLOCKS:
        phys = bus_to_phys(bus)
        base = phys & ~(PAGE - 1)
        delta = phys - base
        print("== %s  ARM-phys=0x%08x ==" % (name, phys))
        try:
            m = mmap.mmap(fd, PAGE, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
        except (OSError, ValueError) as e:
            print("  mmap FAILED: %r  (likely STRICT_DEVMEM / driver-claimed)" % e)
            rc = 2
            continue
        vals = []
        for rn, ro in regs:
            m.seek(delta + ro)
            v = struct.unpack("<I", m.read(4))[0]
            vals.append(v)
            print("  %-16s @+0x%02x = 0x%08x" % (rn, ro, v))
        m.close()
        allzero = all(v == 0 for v in vals)
        allff = all(v == 0xFFFFFFFF for v in vals)
        if allff:
            print("  -> all 0xFFFFFFFF: block likely UNPOWERED / bus not responding")
        elif allzero:
            print("  -> all zero: could be reset state or gated; inconclusive alone")
        else:
            print("  -> varied values: block IS responding")
    os.close(fd)
    return rc


if __name__ == "__main__":
    sys.exit(probe())
