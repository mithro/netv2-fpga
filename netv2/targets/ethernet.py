#!/usr/bin/env python3
"""
NeTV2 modern Ethernet-control SoC (phase 8).

Extends the phase-2 :class:`NeTV2BaseSoC` (UART + DDR3 on LiteX 2026.04) with the
NeTV2's RMII Ethernet PHY brought up under LiteX, wired for **control over
Ethernet**:

  * hardware **Etherbone** (``LiteEthEtherbone``) as a Wishbone master, so
    ``litex_server`` / ``litex_cli`` on a host can read and write the SoC's CSRs
    over the NeTV2's own RJ45 -- no UART or JTAG bridge required; and
  * a CPU-visible **LiteEth MAC** sharing the same UDP/IP crossbar
    (``add_etherbone(..., with_ethmac=True)``, design-spec decision 14), so the
    VexRiscv BIOS enumerates an ``ethmac`` core and can drive a normal network
    stack alongside Etherbone.

Clock domains (see ``docs/original/clocking.md`` and ``legacy/netv2mvp.py``):
the RMII stack runs in the **50 MHz ``eth`` domain**. The upstream
``kosagi_netv2`` ``_CRG`` already synthesises ``cd_eth`` at 50 MHz off the
sys PLL, and ``LiteEthPHYRMII(refclk_cd="eth")`` (its default) uses that domain
as the RMII reference clock, driving the PHY ``ref_clk`` pad (D17) via a
``DDROutput``. So the MAC/PHY RX/TX path is 50 MHz -- the 2019 design's
``fast_eth=False`` choice ("100 MHz domain works but timing closure is hard",
``legacy/netv2mvp.py:1197-1199``) is the modern default here. ``add_etherbone``
places the Etherbone bridge in its own ``etherbone`` clock domain sourced from
``sys`` (100 MHz), and auto-emits the ``eth`` <-> ``sys`` false-path / period
constraints.

Static addressing (reuses the documented 2019 values,
``legacy/netv2mvp.py:1202-1213``):

  * Etherbone : MAC ``0x1337320dbabe``, IP ``10.0.11.2``, UDP port 1234.
  * CPU MAC   : MAC ``0x1337320dbabf``, IP ``10.0.11.3`` (must differ from the
    Etherbone endpoint; LiteX asserts this).

Build (from repo root):

    uv run python -m netv2.targets.ethernet --build --toolchain vivado

The bitstream is written to:

    build/netv2-eth/gateware/kosagi_netv2.bit

and the generated CSR map to:

    build/netv2-eth/csr.csv
"""

import os

from litex.build.parser import LiteXArgumentParser
from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2

from liteeth.phy.rmii import LiteEthPHYRMII

from netv2.targets.base import NeTV2BaseSoC

REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT = os.path.join(REPO_ROOT, "build", "netv2-eth")

# Documented static addressing (from the 2019 design, legacy/netv2mvp.py).
ETHERBONE_MAC = 0x1337320dbabe
ETHERBONE_IP  = "10.0.11.2"
ETHMAC_MAC    = 0x1337320dbabf
ETHMAC_IP     = "10.0.11.3"
REMOTE_IP     = "10.0.11.1"


class NeTV2EthernetSoC(NeTV2BaseSoC):
    """NeTV2 SoC with RMII Ethernet: hardware Etherbone + CPU LiteEth MAC.

    Builds the phase-2 base (VexRiscv + UART + DDR3) and adds the RMII PHY on the
    NeTV2's ``eth`` pads, then ``add_etherbone`` with ``with_ethmac=True`` so a
    host can reach the CSRs over Etherbone while the CPU also owns a MAC on the
    shared UDP crossbar.
    """
    def __init__(self, variant="a7-100",
                 with_ethmac   = True,
                 eth_data_width = 32,
                 etherbone_ip  = ETHERBONE_IP,
                 etherbone_mac = ETHERBONE_MAC,
                 ethmac_ip     = ETHMAC_IP,
                 ethmac_mac    = ETHMAC_MAC,
                 remote_ip     = REMOTE_IP,
                 **kwargs):
        # Base SoC: UART + DDR3. Do NOT enable the upstream --with-ethernet path
        # (that calls add_ethernet); we add Etherbone (+ optional CPU MAC) here.
        super().__init__(variant=variant, with_ethernet=False, **kwargs)

        # RMII PHY on the NeTV2 eth pads. refclk_cd defaults to "eth" -> the
        # 50 MHz sys-PLL eth domain drives the RMII ref_clk (D17) via DDROutput,
        # so RX/TX run at 50 MHz. MDIO (mdc F14 / mdio F13) is present, so the
        # PHY's LiteEthPHYMDIO CSR is instantiated (BIOS mdio_read/mdio_dump).
        self.ethphy = LiteEthPHYRMII(
            clock_pads = self.platform.request("eth_clocks"),
            pads       = self.platform.request("eth"))

        # Etherbone (Wishbone master over UDP:1234) + optional CPU-visible MAC
        # sharing the same UDP/IP core (hybrid crossbar).
        #
        # data_width=32 selects LiteX's `with_sys_datapath` path: the UDP/IP
        # stack runs 32-bit in the sys (100 MHz) domain, with the PHY's 8-bit
        # 50 MHz eth_tx/eth_rx bridged via the MAC's RX/TX CDC FIFOs. This is
        # the canonical hybrid (`with_ethmac`) recipe and is the configuration
        # proven end-to-end on hardware in phase 8 (Etherbone CSR read/write
        # from a host over the NeTV2 RJ45; see the phase-8 report). data_width=8
        # (the LiteX default) also builds and closes timing here; 32 is kept as
        # the default because it is the well-trodden hybrid datapath.
        #
        # NB for host tooling: the LiteEth Etherbone core replies to the
        # requester's IP on the *fixed* UDP port 1234, not the request's source
        # port -- so a client must send from and listen on port 1234 (LiteX's
        # litex_server/CommUDP already binds 1234). A relay/NAT in the path must
        # preserve port 1234 in both directions.
        self.add_etherbone(
            phy              = self.ethphy,
            data_width       = eth_data_width,
            ip_address       = etherbone_ip,
            mac_address      = etherbone_mac,
            with_ethmac      = with_ethmac,
            ethmac_address   = ethmac_mac,
            ethmac_local_ip  = ethmac_ip,
            ethmac_remote_ip = remote_ip,
        )


def main():
    parser = LiteXArgumentParser(
        platform=kosagi_netv2.Platform,
        description="NeTV2 modern Ethernet-control SoC (phase 8): UART + DDR3 + Etherbone (+CPU MAC).",
    )
    parser.add_target_argument("--variant",       default="a7-100",
        help="Board variant (a7-35 or a7-100). Phase 8 targets a7-100.")
    parser.add_target_argument("--sys-clk-freq",  default=100e6, type=float,
        help="System clock frequency.")
    parser.add_target_argument("--no-ethmac",     dest="with_ethmac", action="store_false",
        help="Build Etherbone only, without the CPU-visible LiteEth MAC.")
    parser.add_target_argument("--etherbone-ip",  default=ETHERBONE_IP,
        help="Etherbone (hardware Wishbone bridge) IP address.")
    parser.add_target_argument("--ethmac-ip",     default=ETHMAC_IP,
        help="CPU MAC IP address (must differ from --etherbone-ip).")
    args = parser.parse_args()

    soc = NeTV2EthernetSoC(
        variant       = args.variant,
        sys_clk_freq  = args.sys_clk_freq,
        with_ethmac   = args.with_ethmac,
        etherbone_ip  = args.etherbone_ip,
        ethmac_ip     = args.ethmac_ip,
        **parser.soc_argdict,
    )

    builder_kwargs = parser.builder_argdict
    output_dir = builder_kwargs.get("output_dir") or DEFAULT_OUT
    builder_kwargs["output_dir"] = output_dir
    if not builder_kwargs.get("csr_csv"):
        builder_kwargs["csr_csv"] = os.path.join(output_dir, "csr.csv")

    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
