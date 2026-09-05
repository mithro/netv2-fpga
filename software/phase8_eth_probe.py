#!/usr/bin/env python3
"""
Phase 8 host-side Ethernet probe for the NeTV2 LiteX SoC.

Runs on the machine wired to the NeTV2 BIOS UART (on the rpi5-netv2 test rig
that is ``/dev/ttyAMA0`` @ 115200). It:

  1. waits for the LiteX BIOS ``litex>`` prompt (capturing the boot log so the
     Ethernet core enumeration is on record);
  2. runs ``help`` to confirm the LiteEth BIOS command group is compiled in
     (``mdio_read`` / ``mdio_write`` / ``mdio_dump`` appear only when the SoC has
     an ``ethphy`` MDIO CSR);
  3. reads the RMII PHY over MDIO -- scanning PHY addresses and dumping the
     standard IEEE 802.3 registers -- to recover the **PHY OUI/model ID** and the
     **link / auto-negotiation status**. This proves the FPGA<->PHY path works
     even with nothing cabled to the RJ45.

The PHY ID is ``(PHYIDR1 << 16) | PHYIDR2`` (registers 2 and 3). Link-up is
BMSR (register 1) bit 2; auto-neg-complete is BMSR bit 5.

Usage (on the Pi):
    python3 phase8_eth_probe.py --port /dev/ttyAMA0

Nothing here writes flash or touches the board beyond the UART console.
"""

import argparse
import re
import sys
import time

import serial

BAUD          = 115200
BOOT_TIMEOUT  = 40
CMD_TIMEOUT   = 4

# Standard IEEE 802.3 MII registers we read from each PHY address.
MII_REGS = {
    0x00: "BMCR   (control)",
    0x01: "BMSR   (status)",
    0x02: "PHYIDR1(id hi)",
    0x03: "PHYIDR2(id lo)",
    0x04: "ANAR   (adv)",
    0x05: "ANLPAR (partner)",
}

VAL_RE = re.compile(r"0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)")


def read_until_prompt(ser, timeout, marker="litex>"):
    """Read lines until the BIOS prompt or timeout; return captured lines."""
    lines = []
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        raw = ser.read(256)
        if not raw:
            continue
        buf += raw.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            lines.append(line.rstrip("\r"))
        if marker in buf:
            lines.append(buf.strip())
            break
    return lines


def run_cmd(ser, cmd, timeout=CMD_TIMEOUT):
    """Send a BIOS command and capture the response up to the next prompt."""
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode())
    time.sleep(0.15)
    return read_until_prompt(ser, timeout)


def mdio_read(ser, phyadr, reg):
    """Return the 16-bit value of PHY <phyadr> register <reg>, or None."""
    out = run_cmd(ser, f"mdio_read {phyadr} {reg}")
    for line in out:
        m = VAL_RE.search(line)
        if m:
            got_reg = int(m.group(1), 16)
            val     = int(m.group(2), 16)
            if got_reg == reg:
                return val
    return None


def main():
    ap = argparse.ArgumentParser(description="NeTV2 phase-8 Ethernet/MDIO probe")
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=BAUD)
    ap.add_argument("--max-phy", type=int, default=8,
                    help="Highest PHY address to scan (0..N).")
    ap.add_argument("--skip-boot", action="store_true",
                    help="Assume already at litex> prompt.")
    args = ap.parse_args()

    print(f"# opening {args.port} @ {args.baud}")
    with serial.Serial(args.port, args.baud, timeout=0.5) as ser:
        if not args.skip_boot:
            print("# waiting for BIOS prompt (capturing boot log)...")
            boot = read_until_prompt(ser, BOOT_TIMEOUT)
            print("===== BOOT LOG =====")
            for l in boot:
                print(l)
            print("===== END BOOT LOG =====")
        # Nudge a prompt.
        run_cmd(ser, "")

        print("\n===== help (LiteEth command group?) =====")
        for l in run_cmd(ser, "help", timeout=3):
            print(l)

        print("\n===== MDIO PHY scan =====")
        found = []
        for phy in range(0, args.max_phy + 1):
            id1 = mdio_read(ser, phy, 0x02)
            id2 = mdio_read(ser, phy, 0x03)
            if id1 is None or id2 is None:
                print(f"phy {phy}: no response")
                continue
            phy_id = (id1 << 16) | id2
            live = id1 not in (0x0000, 0xffff)
            tag = "  <-- PHY PRESENT" if live else ""
            print(f"phy {phy}: PHYIDR1=0x{id1:04x} PHYIDR2=0x{id2:04x} "
                  f"ID=0x{phy_id:08x}{tag}")
            if live:
                found.append(phy)

        for phy in found:
            print(f"\n===== full register dump: phy {phy} =====")
            regs = {}
            for reg, name in MII_REGS.items():
                v = mdio_read(ser, phy, reg)
                regs[reg] = v
                vs = f"0x{v:04x}" if v is not None else "----"
                print(f"  reg 0x{reg:02x} {name} = {vs}")
            bmsr = regs.get(0x01)
            if bmsr is not None:
                link = bool(bmsr & 0x0004)
                aneg_cap = bool(bmsr & 0x0008)
                aneg_done = bool(bmsr & 0x0020)
                print(f"  -> LINK {'UP' if link else 'DOWN'}; "
                      f"auto-neg {'able' if aneg_cap else 'n/a'}, "
                      f"{'complete' if aneg_done else 'not complete'}")
            id1 = regs.get(0x02)
            id2 = regs.get(0x03)
            if id1 is not None and id2 is not None:
                oui = ((id1 << 6) | (id2 >> 10)) & 0x3fffff
                model = (id2 >> 4) & 0x3f
                rev = id2 & 0xf
                print(f"  -> PHY OUI=0x{oui:06x} model=0x{model:02x} rev=0x{rev:x}")

        if not found:
            print("\nNo PHY responded on any scanned address.")
            return 1
        print(f"\nPHY(s) present at address(es): {found}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
