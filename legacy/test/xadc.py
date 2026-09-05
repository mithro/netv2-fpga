#!/usr/bin/env python3
import time

from litex.soc.tools.remote import RemoteClient

wb = RemoteClient()
wb.open()

#print("trigger_mem_full: ")
#t = wb.read(0xe000b838)
#print(t)

print("Temperature: ")
t = wb.read(0xe0005800)
t <<= 8
t |= wb.read(0xe0005804)
print(t * 503.975 / 4096 - 273.15, "C")

print("VCCint: ")
t = wb.read(0xe0005808)
t <<= 8
t |= wb.read(0xe000580c)
print(t / 0x555, "V")

print("VCCaux: ")
t = wb.read(0xe0005810)
t <<= 8
t |= wb.read(0xe0005814)
print(t / 0x555, "V")

print("VCCbram: ")
t = wb.read(0xe0005818)
t <<= 8
t |= wb.read(0xe000581c)
print(t / 0x555, "V")

wb.close()
