import mmap,os,struct,sys
PERI=0x20000000;PAGE=4096
fd=os.open("/dev/mem",os.O_RDONLY|os.O_SYNC)
base=((0x7e902000&0xFFFFFF)|PERI)&~(PAGE-1)
m=mmap.mmap(fd,PAGE,mmap.MAP_SHARED,mmap.PROT_READ,offset=base)
for name,off in [("ENCODER_CTL",0x70),("SCHEDULER_CONTROL",0xc0),("HDCP_CTL",0x44),
                 ("CP_STATUS",0x48),("CP_CONFIG",0x54),("CP_TST",0x58),
                 ("CP_INTEGRITY",0x4c),("MISC_CONTROL",0xe4),("FIFO_CTL",0x5c)]:
    m.seek(off);print("  %-18s @+0x%02x = 0x%08x"%(name,off,struct.unpack("<I",m.read(4))[0]))
m.close();os.close(fd)
