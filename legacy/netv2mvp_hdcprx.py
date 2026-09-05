#!/usr/bin/env python3
"""HDCP-receiver bridge top level (task H5).

2026 tooling.  Extends the *proven* 2019 ``VideoOverlaySoC`` from
``legacy/netv2mvp.py`` (which is NEVER modified) and adds an HDCP-1.x receiver
on hdmi_in0's DDC bus, so an HDCP source (the RPi transmitter) can authenticate
against the NeTV2 and emit encrypted video (DoD 1 + 2).

Architecture note
-----------------
This bridge deliberately builds on the *2019* migen/litex toolchain (the
``legacy/deps`` submodules, run inside the ``rebuild2019`` container), reusing
the whole ``VideoOverlaySoC``.  The three receiver modules are plain,
version-agnostic Verilog and are instantiated DIRECTLY with migen ``Instance``
and 2019-style CSRs -- mirroring how ``netv2mvp.py``'s ``HDCP`` and
``I2Csnoop`` classes already wrap ``hdcp_mod`` / ``i2c_snoop``.  The modern
``netv2/gateware/hdcp/receiver.py`` (written against migen 0.9.2 / LiteX
2026.04) is the design of record for the eventual *modern* port and is
deliberately NOT imported here.

  * ``hdcp_rx``       -- I2C slave + 40x56 key store + Km accumulator.  eth (50 MHz).
  * ``hdcp_mod_rx``   -- receiver FSM; it instantiates ``hdcp_cipher_rx``
                         internally.  Produces R0'/Ri'.  pix_o (74.25/148.5 MHz).

The shared block-cipher primitives (``hdcp_block``, ``hdcp_lfsr``,
``shuffle_network``, ``diff_network``) that ``hdcp_cipher_rx`` references are
already added to the design by ``VideoOverlaySoC`` from ``legacy/overlay/``, so
only the three receiver ``.v`` files are added here.

Safety (spec section 10.3)
--------------------------
``hdmi_sda_over_up`` (G20, a 5 V push-pull) stays tied 0 exactly as the original
does; only ``hdmi_sda_over_dn`` (F20, the open-drain FET gate) is handed to the
receiver.  Because ``over_up`` is never driven high, the mutual-exclusion
invariant (netv2mvp.py:172, :874-877) holds trivially.  The receiver's
``sda_drive_low`` only asserts when the I2C slave ACKs *and* ``rx_enable_eff``
(armed AND all 40 keys loaded), so a bitstream load never disturbs the DDC bus.

NO sink keys are baked into the bitstream; firmware loads them at runtime over
the CSRs (task H7).  There is no key material in this file.
"""

# lxbuildenv must be imported first (re-execs with the pinned deps on PYTHONPATH
# and pins PYTHONHASHSEED for deterministic builds), exactly as netv2mvp.py.
import lxbuildenv  # noqa: F401

LX_DEPENDENCIES = ["riscv", "vivado"]

import os
import argparse

from migen import *
from migen.genlib.cdc import MultiReg, PulseSynchronizer, BusSynchronizer
from migen.fhdl.structure import _Assign, If as _If, Case as _Case

from litex.soc.interconnect.csr import CSR, CSRStorage, CSRStatus, AutoCSR
from litex.soc.integration.builder import Builder

from netv2mvp import Platform, VideoOverlaySoC, csr_map_update


# ============================================================================
# 2019-migen fragment surgery helpers.
#
# The modern netv2/gateware/hdcp/comb_driver.py shows the *intent*; these are
# re-implemented here against the pinned 2019 migen (migen b80116b) because that
# module lives in the modern tree and is not importable inside the rebuild2019
# container (which mounts only legacy/).  Verified against
# legacy/deps/migen/migen/fhdl/structure.py in THIS migen:
#   * Module keeps statements on module._fragment (a _Fragment);
#     _fragment.comb is a plain list (fhdl/module.py _ModuleComb).
#   * _Assign.l is wrap(target); for a plain Signal target wrap() is identity,
#     so `assign.l is signal` is exact.
#   * If nests on .t / .f (lists); Case nests on .cases (dict of lists).
#   * Instance keeps its ports on .items (a list of Instance.Input/.Output/...);
#     each has .name and .expr = wrap(expr).
# ============================================================================

def _find_comb_assigns(stmts, signal, found):
    for i, s in enumerate(stmts):
        if isinstance(s, _Assign):
            if s.l is signal:
                found.append((stmts, i))
        elif isinstance(s, _If):
            _find_comb_assigns(s.t, signal, found)
            _find_comb_assigns(s.f, signal, found)
        elif isinstance(s, _Case):
            for sub in s.cases.values():
                _find_comb_assigns(sub, signal, found)
        elif isinstance(s, (list, tuple)):
            _find_comb_assigns(s, signal, found)


def release_comb_driver(module, signal):
    """Remove the single combinational ``_Assign`` whose target is *signal*.

    Asserts EXACTLY one such assignment exists, so a mismatch (the parent design
    changed and the signal is now undriven or double-driven) fails loudly rather
    than letting the receiver silently double-drive a FET gate.
    """
    frag = getattr(module, "_fragment", module)
    comb = getattr(frag, "comb", None)
    if comb is None:
        raise ValueError("release_comb_driver: %r has no combinational statements" % (module,))
    found = []
    _find_comb_assigns(comb, signal, found)
    if len(found) != 1:
        raise ValueError(
            "release_comb_driver: signal %r has %d combinational drivers, expected exactly 1"
            % (signal, len(found)))
    container, index = found[0]
    if not isinstance(container, list):
        raise TypeError("release_comb_driver: assignment lives in immutable %r" % (type(container),))
    del container[index]


def _iter_specials(module):
    frag = getattr(module, "_fragment", module)
    return getattr(frag, "specials", set())


def rebind_instance_inputs(module, of, mapping):
    """Re-point named input ports of the single ``Instance`` of type *of*.

    *mapping* is ``{port_name: new_expr}``.  Asserts exactly one matching
    Instance and exactly one item per named port, so a rename in the underlying
    Verilog fails loudly instead of silently leaving the old wiring.  Used to
    feed the km_source mux into the pre-existing ``hdcp_mod`` decrypt Instance,
    which lives inside the ``self.hdcp`` submodule and cannot be rewired by
    editing netv2mvp.py.
    """
    insts = [s for s in _iter_specials(module)
             if isinstance(s, Instance) and s.of == of]
    if len(insts) != 1:
        raise ValueError("rebind_instance_inputs: found %d Instances of %r, expected 1"
                         % (len(insts), of))
    inst = insts[0]
    for name, expr in mapping.items():
        items = [it for it in inst.items
                 if isinstance(it, Instance.Input) and it.name == name]
        if len(items) != 1:
            raise ValueError("rebind_instance_inputs: %r has %d inputs named %r, expected 1"
                             % (of, len(items), name))
        items[0].expr = wrap(expr)


# ============================================================================
# HDCP receiver wrapper: I2C slave + key store + Km accumulator (eth domain),
# CSRs (sys domain) and the sys/eth/pix_o clock-domain crossings.
#
# The pix_o cipher/receiver-FSM (hdcp_mod_rx) lives in the SoC subclass below,
# because its de/hsync/vsync/ctl_code/... inputs only exist once the full SoC
# clocking is present.  This wrapper exposes injectable pix_o Signals (r0_pix,
# ri_link_pix, r0_valid_pix) that the SoC drives from hdcp_mod_rx, and does the
# pix_o<->eth / pix_o<->sys crossings for them.
# ============================================================================

class HDCPReceiverRx(Module, AutoCSR):
    def __init__(self, pads):
        # --- CSRs (sys domain), litex-2019 house style (cf. HDCP/I2Csnoop) ---
        self.bksv         = CSRStorage(40)   # KSV_sink, answered as Bksv (DDC 0x00)
        self.key_index    = CSRStorage(6)    # sink-key store write index (0..39)
        self.key_data_lo  = CSRStorage(32)   # low 32 bits of a sink key
        self.key_data_hi  = CSRStorage(24)   # high 24 bits of a sink key
        self.key_we       = CSR()            # key-store write strobe
        self.keys_clear   = CSR()            # clear key store / keys_loaded
        self.keys_loaded  = CSRStatus(7)     # count of distinct indices loaded
        self.rx_enable    = CSRStorage(1)    # arm the I2C slave (0 = inert)
        self.km_source    = CSRStorage(1)    # 0 = CPU Km CSR, 1 = hardware Km (USE 1)

        self.r0    = CSRStatus(16)           # latched R0' (authentication response)
        self.ri    = CSRStatus(16)           # Ri' (the DDC 0x08 value, mod-128)
        self.aksv  = CSRStatus(40)           # Aksv the source wrote (readback)
        self.an    = CSRStatus(64)           # An the source wrote (readback)
        self.ainfo = CSRStatus(8)            # Ainfo (readback)
        self.km_hw = CSRStatus(56)           # computed hardware Km (readback)
        self.status = CSRStatus(8)           # {.., sda, r0_valid, km_valid, keys_ok, rx_armed}

        # --- pix_o-domain signals the SoC drives from hdcp_mod_rx ---
        self.ri_link_pix  = Signal(16)       # hdcp_mod_rx.Ri_link -> DDC 0x08
        self.r0_pix       = Signal(16)       # hdcp_mod_rx.R0
        self.r0_valid_pix = Signal()         # hdcp_mod_rx.R0_valid_out

        # --- eth-domain signals the SoC consumes (Km/An mux, false paths) ---
        self.km_hw_eth       = Signal(56)
        self.an_eth          = Signal(64)
        self.aksv_eth        = Signal(40)
        self.ainfo_eth       = Signal(8)
        self.aksv_done_eth   = Signal()
        self.keys_loaded_eth = Signal(7)
        self.km_valid_hw_eth = Signal()
        self.rx_enable_eff   = Signal()      # eth: armed AND all 40 keys loaded
        self.sda_drive_low   = Signal()      # eth: open-drain, -> hdmi_sda_over_dn

        # === Crossing #2: sys -> eth control pulses ===
        self.submodules.key_we_sync = PulseSynchronizer("sys", "eth")
        self.comb += self.key_we_sync.i.eq(self.key_we.re)
        self.submodules.keys_clear_sync = PulseSynchronizer("sys", "eth")
        self.comb += self.keys_clear_sync.i.eq(self.keys_clear.re)

        # === Crossing #3: sys -> eth quasi-static (written only while disarmed) ===
        bksv_eth = Signal(40)
        self.specials += MultiReg(self.bksv.storage, bksv_eth, "eth")
        rx_enable_eth = Signal()
        self.specials += MultiReg(self.rx_enable.storage, rx_enable_eth, "eth")
        # rx_enable_eff = armed AND all 40 keys loaded (spec 2.8): a half-loaded
        # store can never answer an address match or produce a wrong R0'.
        self.comb += self.rx_enable_eff.eq(rx_enable_eth & (self.keys_loaded_eth == 40))

        # === Crossing #6: pix_o -> eth, Ri' for the DDC 0x08 read (never bitwise) ===
        self.submodules.ri_eth_sync = BusSynchronizer(16, "pix_o", "eth")
        ri_eth = Signal(16)
        self.comb += [self.ri_eth_sync.i.eq(self.ri_link_pix), ri_eth.eq(self.ri_eth_sync.o)]

        # === hdcp_rx: I2C slave + key store + Km accumulator (eth) ===
        self.specials += Instance(
            "hdcp_rx",
            # Crossing #1: raw DDC pins (board 74AHC14 inverts, so pass the
            # inverted level exactly as legacy i2c_snoop; the .v does its own
            # 2-FF + TRF_CYCLES=8 deglitch in the eth domain).
            i_SCL=~pads.scl,
            i_SDA=~pads.sda,
            i_clk=ClockSignal("eth"),
            i_reset=ResetSignal("eth"),
            i_rx_enable=self.rx_enable_eff,
            o_sda_drive_low=self.sda_drive_low,
            o_An=self.an_eth,
            o_Aksv=self.aksv_eth,
            o_Ainfo=self.ainfo_eth,
            o_aksv_done=self.aksv_done_eth,
            i_Bksv=bksv_eth,
            i_Ri=ri_eth,
            i_Pj=0,
            i_key_index=self.key_index.storage,
            i_key_lo=self.key_data_lo.storage,
            i_key_hi=self.key_data_hi.storage,
            i_key_we=self.key_we_sync.o,
            i_keys_clear=self.keys_clear_sync.o,
            o_keys_loaded=self.keys_loaded_eth,
            o_Km_hw=self.km_hw_eth,
            o_Km_valid_hw=self.km_valid_hw_eth,
        )

        # === Crossing #7: pix_o -> sys readback ===
        self.submodules.r0_sys = BusSynchronizer(16, "pix_o", "sys")
        self.comb += [self.r0_sys.i.eq(self.r0_pix), self.r0.status.eq(self.r0_sys.o)]
        self.submodules.ri_sys = BusSynchronizer(16, "pix_o", "sys")
        self.comb += [self.ri_sys.i.eq(self.ri_link_pix), self.ri.status.eq(self.ri_sys.o)]
        self.submodules.r0v_sys = PulseSynchronizer("pix_o", "sys")
        self.comb += self.r0v_sys.i.eq(self.r0_valid_pix)
        r0_valid_sticky = Signal()   # set on strobe, cleared when disarmed
        self.sync += [
            If(~self.rx_enable.storage,
                r0_valid_sticky.eq(0),
            ).Elif(self.r0v_sys.o,
                r0_valid_sticky.eq(1),
            )
        ]

        # === Crossing #8: eth -> sys readback ===
        self.submodules.kmhw_sys = BusSynchronizer(56, "eth", "sys")
        self.comb += [self.kmhw_sys.i.eq(self.km_hw_eth), self.km_hw.status.eq(self.kmhw_sys.o)]
        self.submodules.aksv_sys = BusSynchronizer(40, "eth", "sys")
        self.comb += [self.aksv_sys.i.eq(self.aksv_eth), self.aksv.status.eq(self.aksv_sys.o)]
        self.submodules.an_sys = BusSynchronizer(64, "eth", "sys")
        self.comb += [self.an_sys.i.eq(self.an_eth), self.an.status.eq(self.an_sys.o)]
        self.submodules.ainfo_sys = BusSynchronizer(8, "eth", "sys")
        self.comb += [self.ainfo_sys.i.eq(self.ainfo_eth), self.ainfo.status.eq(self.ainfo_sys.o)]
        self.submodules.kl_sys = BusSynchronizer(7, "eth", "sys")
        self.comb += [self.kl_sys.i.eq(self.keys_loaded_eth), self.keys_loaded.status.eq(self.kl_sys.o)]

        km_valid_sys = Signal()
        self.specials += MultiReg(self.km_valid_hw_eth, km_valid_sys)   # -> sys
        sda_sys = Signal()
        self.specials += MultiReg(self.sda_drive_low, sda_sys)          # -> sys
        keys_ok = Signal()
        self.comb += keys_ok.eq(self.keys_loaded.status == 40)
        self.comb += self.status.status.eq(Cat(
            self.rx_enable.storage & keys_ok,   # bit0: rx_armed
            keys_ok,                            # bit1: keys_ok
            km_valid_sys,                       # bit2: km_valid_hw
            r0_valid_sticky,                    # bit3: r0_valid (sticky)
            sda_sys,                            # bit4: sda_driving
            Signal(3),                          # bits 7:5 spare
        ))


# ============================================================================
# Bridge SoC: VideoOverlaySoC + HDCP receiver.
# ============================================================================

class VideoOverlayHDCPRxSoC(VideoOverlaySoC):
    csr_peripherals = ["hdcprx"]
    csr_map_update(VideoOverlaySoC.csr_map, csr_peripherals)

    def __init__(self, platform, part, dqs_phase, *args, **kwargs):
        VideoOverlaySoC.__init__(self, platform, part, dqs_phase, *args, **kwargs)

        # --- add the three receiver Verilog sources ---
        # The .v files live in netv2/gateware/hdcp; inside the rebuild2019
        # container that tree is bind-mounted (default /netv2/gateware/hdcp,
        # overridable via HDCPRX_SRC).
        src_dir = os.environ.get("HDCPRX_SRC", "/netv2/gateware/hdcp")
        for f in ("hdcp_rx.v", "hdcp_cipher_rx.v", "hdcp_mod_rx.v"):
            platform.add_source(os.path.join(src_dir, f))

        # --- receiver wrapper (eth + CSR + CDC) on the hdmi_in0 DDC bus ---
        hdmi_in0_pads = platform.lookup_request("hdmi_in", 0)   # already requested
        self.submodules.hdcprx = rx = HDCPReceiverRx(hdmi_in0_pads)

        # === Km / An path mux (spec section 6), pix_o domain ===
        # Crossing #4: eth -> pix_o coherent word snapshots.
        km_hw_pix = Signal(56)
        self.submodules.km_hw_pix_sync = BusSynchronizer(56, "eth", "pix_o")
        self.comb += [self.km_hw_pix_sync.i.eq(rx.km_hw_eth), km_hw_pix.eq(self.km_hw_pix_sync.o)]
        an_hw_pix = Signal(64)
        self.submodules.an_hw_pix_sync = BusSynchronizer(64, "eth", "pix_o")
        self.comb += [self.an_hw_pix_sync.i.eq(rx.an_eth), an_hw_pix.eq(self.an_hw_pix_sync.o)]
        # Crossing #5b: single-bit levels, eth/sys -> pix_o.
        km_valid_hw_pix = Signal()
        self.specials += MultiReg(rx.km_valid_hw_eth, km_valid_hw_pix, "pix_o")
        rx_enable_eff_pix = Signal()
        self.specials += MultiReg(rx.rx_enable_eff, rx_enable_eff_pix, "pix_o")
        km_source_pix = Signal()
        self.specials += MultiReg(rx.km_source.storage, km_source_pix, "pix_o")

        # km_source = 1 -> hardware Km from the accumulator (USE THIS: the legacy
        # CPU km.c path uses the real DCP matrix and is incompatible with our
        # closed-loop keys).  km_source = 0 -> the legacy CPU Km CSR path.
        Km_mux      = Signal(56)
        Kmvalid_mux = Signal()
        An_mux      = Signal(64)
        self.comb += [
            If(km_source_pix,
                Km_mux.eq(km_hw_pix),
                Kmvalid_mux.eq(km_valid_hw_pix & rx_enable_eff_pix),
                An_mux.eq(an_hw_pix),
            ).Else(
                Km_mux.eq(self.hdcp.Km.storage),
                Kmvalid_mux.eq(self.hdcp.Km_valid.storage),
                An_mux.eq(self.hdcp.An),
            )
        ]

        # === receiver cipher + FSM (pix_o) for R0'/Ri' ===
        # hdcp_mod_rx instantiates hdcp_cipher_rx internally.  It is fed the SAME
        # framing signals the legacy decrypt hdcp_mod uses (reused verbatim from
        # self.hdcp, all pix_o) so the two stay perfectly aligned.
        _cs   = Signal(24)   # cipher_stream (unused: overlay-decrypt is DoD 3)
        _sr   = Signal()     # stream_ready (unused here)
        _fc   = Signal(16)   # frame_count (debug)
        _rif  = Signal(16)   # Ri_frame (debug)
        self.specials += Instance(
            "hdcp_mod_rx",
            i_clk=ClockSignal("pix_o"),
            i_rst=ResetSignal("pix_o"),
            i_de=self.hdcp.de,
            i_hsync=self.hdcp.hsync,
            i_vsync=self.hdcp.vsync,
            i_line_end=self.hdcp.line_end,
            i_hpd=self.hdcp.hpd,
            i_Aksv14_write=self.hdcp.Aksv14_auto,
            i_An=An_mux,
            i_Km=Km_mux,
            i_Km_valid=Kmvalid_mux,
            i_hdcp_ena=self.hdcp.hdcp_ena,
            i_ctl_code=self.hdcp.ctl_code,
            o_cipher_stream=_cs,
            o_stream_ready=_sr,
            o_R0=rx.r0_pix,
            o_R0_valid_out=rx.r0_valid_pix,
            o_Ri_link=rx.ri_link_pix,
            o_frame_count=_fc,
            o_Ri_frame=_rif,
        )

        # Feed the same (Km, An, Km_valid) into the pre-existing decrypt hdcp_mod
        # Instance (spec section 6).  That Instance is frozen inside the
        # self.hdcp submodule with Km/Km_valid from a CSR; rebind its inputs to
        # the mux without editing netv2mvp.py.  Exactly-one asserts guard the
        # rewire.
        rebind_instance_inputs(self.hdcp, "hdcp_mod", {
            "Km": Km_mux,
            "Km_valid": Kmvalid_mux,
            "An": An_mux,
        })

        # === DDC override pad handoff (SAFETY, spec section 10.3) ===
        # Keep hdmi_sda_over_up (G20, 5 V push-pull) tied 0 -- the original
        # comb assignment is left in place -- and hand hdmi_sda_over_dn (F20,
        # open-drain FET) to the receiver.  Remove exactly the original
        # hdmi_sda_over_dn.eq(0) so the receiver can drive it without a
        # double-driver error; assert exactly one assignment was removed.
        sda_over_dn = platform.lookup_request("hdmi_sda_over_dn")
        release_comb_driver(self, sda_over_dn)
        self.comb += sda_over_dn.eq(rx.sda_drive_low)

        # All new CDC pairs (sys/eth/pix_o) are already async-constrained by the
        # existing design: sys<->eth and eth<->pix_o via add_false_path_constraints
        # (both directions), sys<->pix_o via the sys/hdmi_in0 clock-group, and
        # every MultiReg destination FF (incl. those inside BusSynchronizer /
        # PulseSynchronizer) via the toolchain's global mr_ff set_false_path.
        # No new timing constraints are required.


def main():
    parser = argparse.ArgumentParser(description="Build the NeTV2 HDCP-receiver bridge bitstream")
    parser.add_argument("-p", "--part", choices=["35", "50", "100"], default="100",
                        help="FPGA part (35, 50, or 100)")
    parser.add_argument("-d", "--dqsphase",
                        choices=["45.0", "67.5", "90.0", "112.5", "135.0", "157.5", "180.0"],
                        default="112.5")
    parser.add_argument("-c", "--cable", choices=["pcb", "cable"], default="pcb")
    parser.add_argument("--verilog-only", action="store_true",
                        help="elaborate + emit top.v only (no BIOS, no Vivado) -- smoke test")
    args = parser.parse_args()

    platform = Platform(part=args.part, cable=args.cable)
    soc = VideoOverlayHDCPRxSoC(platform, part=args.part, dqs_phase=args.dqsphase)
    output_dir = "build/hdcprx-%s" % args.part
    if args.verilog_only:
        builder = Builder(soc, output_dir=output_dir,
                          csr_csv=os.path.join(output_dir, "csr.csv"),
                          compile_software=False, compile_gateware=False)
        builder.build()
        print("generated %s/gateware/top.v" % output_dir)
        return
    builder = Builder(soc, output_dir=output_dir, csr_csv=os.path.join(output_dir, "csr.csv"))
    vns = builder.build()
    soc.do_exit(vns)


if __name__ == "__main__":
    main()
