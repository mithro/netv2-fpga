#!/usr/bin/env python3
"""Sample CP_INTEGRITY (Ri) + CP_STATUS over time to see if the HDCP cipher is
advancing. Also decodes SCHEDULER_CONTROL. Read-only."""
import mmap, os, struct, time
PERI=0x20000000; PAGE=4096
fd=os.open("/dev/mem", os.O_RDONLY|os.O_SYNC)
base=((0x7e902000&0xFFFFFF)|PERI)&~(PAGE-1)
m=mmap.mmap(fd,PAGE,mmap.MAP_SHARED,mmap.PROT_READ,offset=base)
def r(o): m.seek(o); return struct.unpack("<I",m.read(4))[0]
prev=None
for i in range(12):
    ri=r(0x4c); st=r(0x48); sc=r(0xc0)
    chg = "" if prev is None else ("  <-- Ri CHANGED" if ri!=prev else "")
    print("t=%4.1fs CP_INTEGRITY=0x%08x CP_STATUS=0x%08x SCHED=0x%08x%s"%(i*0.4,ri,st,sc,chg))
    prev=ri; time.sleep(0.4)
m.close(); os.close(fd)
