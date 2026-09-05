"""``HDCPReceiver`` -- migen wrapper for the NeTV2 HDCP-1.x receiver.

Task H4 of ``docs/superpowers/plans/2026-09-06-hdcp-receiver-plan.md``.
Implements spec sections 4 (CSR interface), 6 (Km path selection) and 7
(clock-domain crossings) of
``docs/superpowers/specs/2026-09-06-hdcp-receiver-design.md``.

This wrapper instantiates the two receiver Verilog modules and glues them to
LiteX CSRs across three clock domains:

* ``hdcp_rx``       (``netv2/gateware/hdcp/hdcp_rx.v``, H2/H3) -- I2C slave,
  register file, 40x56 sink-key store and Km accumulator.  **eth, 50 MHz.**
* ``hdcp_cipher_rx`` (``netv2/gateware/hdcp/hdcp_cipher_rx.v``, H1) -- the block
  cipher patched to expose ``Ri``/``R0_valid``.  **pix_o, 74.25/148.5 MHz.**

CSRs live in the **sys** domain (100 MHz).

Clock-domain crossings (spec section 7).  Each row names the migen primitive
used; ``#`` matches the spec's table:

    #   from  -> to     signals                     primitive
    --  --------------  --------------------------  -----------------------------
    1   pads  -> eth    SCL, SDA                    raw pin to hdcp_rx (the .v does
                                                    its own 2-FF + TRF_CYCLES=8
                                                    deglitch -- no migen primitive)
    2   sys   -> eth    key_we / keys_clear         PulseSynchronizer (one each);
                        key_index/lo/hi             quasi-static, .storage passed
                                                    through, sampled on the pulse
    3   sys   -> eth    bksv, rx_enable             MultiReg (quasi-static, written
                        km_source (sys->pix_o)      only while disarmed)
    4   eth   -> pix_o  km_hw[55:0], an[63:0]       BusSynchronizer (coherent word
                                                    snapshot; feeds the Km mux and
                                                    the cipher)
    5   eth   -> pix_o  auth_start                  PulseSynchronizer (pulsed on the
                                                    eth-domain rising edge of
                                                    Km_valid_hw = "Km ready")
    5b  eth   -> pix_o  km_valid_hw                 MultiReg (single-bit level; it
                                                    gates the pix_o Km_valid, spec
                                                    section 6 -- the row the review
                                                    added)
    6   pix_o -> eth    Ri' (for the I2C 0x08 read) BusSynchronizer (never bitwise,
                                                    or a two-byte read could tear)
    7   pix_o -> sys    R0', Ri'                    BusSynchronizer (per bus)
        pix_o -> sys    r0_valid                    PulseSynchronizer (-> sticky
                                                    status bit)
    8   eth   -> sys    km_hw, aksv, an, ainfo,     BusSynchronizer (wide buses)
                        keys_loaded                 / MultiReg (single bits)

What H5 (the bridge top level) must still connect -- these are pix_o signals
that only exist once the full SoC clocking / ``hdcp_mod`` FSM is present, so they
are exposed here as constructor ports and left unwired:

* ``cipher_init`` / ``cipher_auth`` / ``cipher_rekey`` / ``cipher_stream_adv`` --
  the cipher's ``hdcpBlockCipher_init`` / ``authentication`` / ``hdcpRekeyCipher``
  / ``hdcpStreamCipher`` control, driven by the ``hdcp_mod`` FSM in pix_o.
* ``cpu_km`` / ``cpu_km_valid`` / ``cpu_an`` -- the legacy CPU Km path
  (``hdcp.Km.storage`` / ``hdcp.Km_valid.storage`` / ``i2c_snoop.An``), selected
  when ``km_source == 0`` (spec section 6).  Quasi-static, wired directly as the
  legacy design does.
* ``r0_pix`` / ``ri_pix`` / ``r0_valid_pix`` -- the **latched** R0'/Ri_ddc from
  ``hdcp_mod_rx`` (spec section 5.2, the R0-vs-Ri distinction and the mod-128
  frame counter).  They default to the cipher's raw ``Ri``/``R0_valid`` so the
  wrapper is self-contained for H4; H5 should drive them from the hdcp_mod_rx
  latch for a correct DDC read.
* ``self.sda_drive_low`` -> ``hdmi_sda_over_dn`` (use ``release_comb_driver`` from
  ``comb_driver.py`` to drop the original ``.eq(0)`` first).
* ``self.Km`` / ``self.Km_valid`` / ``self.An_cipher`` -> the pix_o cipher/hdcp_mod
  inputs; ``self.cipher_stream`` / ``self.stream_ready`` are the cipher outputs to
  the overlay XOR; ``self.auth_start`` is the pix_o cipher trigger.

The wrapper does not create the eth/pix_o/sys ``ClockDomain`` objects -- the SoC
provides them.  For a standalone ``verilog.convert`` or ``run_simulation`` the
caller supplies the domains (a top module, or ``run_simulation(clocks=...)``).
Pass ``with_instances=False`` to omit the black-box Verilog ``Instance``\\s so the
Km mux can be exercised in a pure-migen simulation.
"""

from litex.soc.interconnect.csr import CSR, AutoCSR, CSRStatus, CSRStorage
from migen import (
    Cat,
    ClockSignal,
    If,
    Instance,
    Module,
    Record,
    ResetSignal,
    Signal,
)
from migen.genlib.cdc import BusSynchronizer, MultiReg, PulseSynchronizer

__all__ = ["HDCPReceiver"]


class HDCPReceiver(Module, AutoCSR):
    def __init__(self, pads=None, sda_override=None,
                 cpu_km=None, cpu_km_valid=None, cpu_an=None,
                 cipher_init=None, cipher_auth=None, cipher_rekey=None,
                 cipher_stream_adv=None,
                 r0_pix=None, ri_pix=None, r0_valid_pix=None,
                 with_instances=True):
        # ---------------------------------------------------------------
        # Injectable ports (kept minimal so the wrapper is unit-testable
        # without the whole SoC -- spec: "keep the pad wiring injectable").
        # ---------------------------------------------------------------
        if pads is None:
            pads = Record([("scl", 1), ("sda", 1)])
        self.pads = pads

        cpu_km        = cpu_km        if cpu_km        is not None else Signal(56)
        cpu_km_valid  = cpu_km_valid  if cpu_km_valid  is not None else Signal()
        cpu_an        = cpu_an        if cpu_an        is not None else Signal(64)
        self.cpu_km, self.cpu_km_valid, self.cpu_an = cpu_km, cpu_km_valid, cpu_an

        self.cipher_init       = cipher_init       if cipher_init       is not None else Signal()
        self.cipher_auth       = cipher_auth       if cipher_auth       is not None else Signal()
        self.cipher_rekey      = cipher_rekey      if cipher_rekey      is not None else Signal()
        self.cipher_stream_adv = cipher_stream_adv if cipher_stream_adv is not None else Signal()

        # ---------------------------------------------------------------
        # CSRs (sys domain).  Mirrors the HDCP / I2Csnoop house style.
        # ---------------------------------------------------------------
        self.bksv         = CSRStorage(40)          # KSV_sink, answered as Bksv (0x00)
        self.key_index    = CSRStorage(6)           # sink-key store write index
        self.key_data_lo  = CSRStorage(32)          # low 32 bits of a sink key
        self.key_data_hi  = CSRStorage(24)          # high 24 bits of a sink key
        self.key_we       = CSR()                   # key-store write strobe
        self.keys_clear   = CSR()                   # clear key store / keys_loaded
        self.keys_loaded  = CSRStatus(7)            # count of distinct indices loaded
        self.rx_enable    = CSRStorage(1)           # arm the I2C slave (0 = inert)
        self.km_source    = CSRStorage(1)           # 0 = CPU Km, 1 = hardware Km
        self.frame_offset = CSRStorage(8)           # frame-index trim (spec 5.3)

        self.r0           = CSRStatus(16)           # latched R0'
        self.ri           = CSRStatus(16)           # Ri'
        self.aksv         = CSRStatus(40)           # Aksv the source wrote (readback)
        self.an           = CSRStatus(64)           # An the source wrote (readback)
        self.ainfo        = CSRStatus(8)            # Ainfo (readback)
        self.km_hw        = CSRStatus(56)           # computed hardware Km (readback)
        self.status       = CSRStatus(8)            # {.., sda, r0_valid, km_valid, keys_ok, rx_armed}

        # ---------------------------------------------------------------
        # Signals crossing the Verilog instance boundary.
        # ---------------------------------------------------------------
        self.sda_drive_low = Signal()               # eth; -> hdmi_sda_over_dn (H5)
        self._an_eth        = Signal(64)
        self._aksv_eth      = Signal(40)
        self._ainfo_eth     = Signal(8)
        self._aksv_done_eth = Signal()
        self._keys_loaded_eth = Signal(7)
        self._km_hw_eth     = Signal(56)
        self._km_valid_hw_eth = Signal()
        self._bksv_eth      = Signal(40)

        self.Km        = Signal(56)                 # pix_o; muxed Km -> cipher/hdcp_mod
        self.Km_valid  = Signal()                   # pix_o
        self.An_cipher = Signal(64)                 # pix_o; muxed An -> cipher/hdcp_mod
        self.auth_start = Signal()                  # pix_o; cipher trigger (H5)
        self.cipher_stream = Signal(24)             # pix_o; -> overlay XOR
        self.stream_ready  = Signal()               # pix_o
        self._cipher_ri      = Signal(16)           # cipher raw Ri output
        self._cipher_r0_valid = Signal()            # cipher raw R0_valid strobe

        # ===============================================================
        # Crossing #2/#3: sys -> eth control.
        # ===============================================================
        self.submodules.key_we_sync = PulseSynchronizer("sys", "eth")
        self.comb += self.key_we_sync.i.eq(self.key_we.re)
        self.submodules.keys_clear_sync = PulseSynchronizer("sys", "eth")
        self.comb += self.keys_clear_sync.i.eq(self.keys_clear.re)

        self.specials += MultiReg(self.bksv.storage, self._bksv_eth, "eth")

        self._rx_enable_eth = Signal()
        self.specials += MultiReg(self.rx_enable.storage, self._rx_enable_eth, "eth")

        # rx_enable_eff = armed AND all 40 keys loaded (spec 2.8): a half-loaded
        # store can never answer an address match or produce a wrong R0'.
        self.rx_enable_eff = Signal()
        self.comb += self.rx_enable_eff.eq(
            self._rx_enable_eth & (self._keys_loaded_eth == 40))

        # ===============================================================
        # Crossing #4/#5/#5b: eth -> pix_o.
        # ===============================================================
        self.submodules.km_hw_pix_sync = BusSynchronizer(56, "eth", "pix_o")
        self.comb += self.km_hw_pix_sync.i.eq(self._km_hw_eth)
        self._km_hw_pix = Signal(56)
        self.comb += self._km_hw_pix.eq(self.km_hw_pix_sync.o)

        self.submodules.an_pix_sync = BusSynchronizer(64, "eth", "pix_o")
        self.comb += self.an_pix_sync.i.eq(self._an_eth)
        self._an_pix = Signal(64)
        self.comb += self._an_pix.eq(self.an_pix_sync.o)

        # #5b -- the single-bit km_valid_hw level MultiReg the review added.
        self._km_valid_hw_pix = Signal()
        self.specials += MultiReg(self._km_valid_hw_eth, self._km_valid_hw_pix, "pix_o")

        self._rx_enable_eff_pix = Signal()
        self.specials += MultiReg(self.rx_enable_eff, self._rx_enable_eff_pix, "pix_o")

        self._km_source_pix = Signal()
        self.specials += MultiReg(self.km_source.storage, self._km_source_pix, "pix_o")

        # #5 -- auth_start: an eth-domain pulse on the rising edge of Km_valid_hw
        # (= Km accumulator done, spec 4.4), synchronised into pix_o.
        self._km_valid_hw_eth_d = Signal()
        self.sync.eth += self._km_valid_hw_eth_d.eq(self._km_valid_hw_eth)
        self._auth_start_eth = Signal()
        self.comb += self._auth_start_eth.eq(
            self._km_valid_hw_eth & ~self._km_valid_hw_eth_d)
        self.submodules.auth_start_sync = PulseSynchronizer("eth", "pix_o")
        self.comb += self.auth_start_sync.i.eq(self._auth_start_eth)
        self.comb += self.auth_start.eq(self.auth_start_sync.o)

        # ===============================================================
        # Km / An path mux (pix_o) -- spec section 6.
        # ===============================================================
        self.comb += [
            If(self._km_source_pix,
                self.Km.eq(self._km_hw_pix),
                self.Km_valid.eq(self._km_valid_hw_pix & self._rx_enable_eff_pix),
                self.An_cipher.eq(self._an_pix),
            ).Else(
                self.Km.eq(self.cpu_km),
                self.Km_valid.eq(self.cpu_km_valid),
                self.An_cipher.eq(self.cpu_an),
            )
        ]

        # ===============================================================
        # pix_o readback source (default = cipher raw outputs; H5 overrides
        # with the hdcp_mod_rx latch of spec 5.2).
        # ===============================================================
        self.r0_pix       = r0_pix       if r0_pix       is not None else self._cipher_ri
        self.ri_pix       = ri_pix       if ri_pix       is not None else self._cipher_ri
        self.r0_valid_pix = r0_valid_pix if r0_valid_pix is not None else self._cipher_r0_valid

        # ===============================================================
        # Crossing #6: pix_o -> eth, Ri' for the I2C 0x08 read (never bitwise).
        # ===============================================================
        self.submodules.ri_eth_sync = BusSynchronizer(16, "pix_o", "eth")
        self.comb += self.ri_eth_sync.i.eq(self.ri_pix)
        self._ri_eth = Signal(16)
        self.comb += self._ri_eth.eq(self.ri_eth_sync.o)

        # ===============================================================
        # Crossing #7: pix_o -> sys readback.
        # ===============================================================
        self.submodules.r0_sys_sync = BusSynchronizer(16, "pix_o", "sys")
        self.comb += self.r0_sys_sync.i.eq(self.r0_pix)
        self.comb += self.r0.status.eq(self.r0_sys_sync.o)

        self.submodules.ri_sys_sync = BusSynchronizer(16, "pix_o", "sys")
        self.comb += self.ri_sys_sync.i.eq(self.ri_pix)
        self.comb += self.ri.status.eq(self.ri_sys_sync.o)

        self.submodules.r0_valid_sys_sync = PulseSynchronizer("pix_o", "sys")
        self.comb += self.r0_valid_sys_sync.i.eq(self.r0_valid_pix)
        self._r0_valid_sys = Signal()               # sticky: set on strobe, clear when disarmed
        self.sync += [
            If(~self.rx_enable.storage,
                self._r0_valid_sys.eq(0),
            ).Elif(self.r0_valid_sys_sync.o,
                self._r0_valid_sys.eq(1),
            )
        ]

        # ===============================================================
        # Crossing #8: eth -> sys readback.
        # ===============================================================
        self.submodules.km_hw_sys_sync = BusSynchronizer(56, "eth", "sys")
        self.comb += self.km_hw_sys_sync.i.eq(self._km_hw_eth)
        self.comb += self.km_hw.status.eq(self.km_hw_sys_sync.o)

        self.submodules.aksv_sys_sync = BusSynchronizer(40, "eth", "sys")
        self.comb += self.aksv_sys_sync.i.eq(self._aksv_eth)
        self.comb += self.aksv.status.eq(self.aksv_sys_sync.o)

        self.submodules.an_sys_sync = BusSynchronizer(64, "eth", "sys")
        self.comb += self.an_sys_sync.i.eq(self._an_eth)
        self.comb += self.an.status.eq(self.an_sys_sync.o)

        self.submodules.ainfo_sys_sync = BusSynchronizer(8, "eth", "sys")
        self.comb += self.ainfo_sys_sync.i.eq(self._ainfo_eth)
        self.comb += self.ainfo.status.eq(self.ainfo_sys_sync.o)

        self.submodules.keys_loaded_sys_sync = BusSynchronizer(7, "eth", "sys")
        self.comb += self.keys_loaded_sys_sync.i.eq(self._keys_loaded_eth)
        self.comb += self.keys_loaded.status.eq(self.keys_loaded_sys_sync.o)

        _km_valid_sys = Signal()
        self.specials += MultiReg(self._km_valid_hw_eth, _km_valid_sys)   # -> sys (default odomain)
        _sda_driving_sys = Signal()
        self.specials += MultiReg(self.sda_drive_low, _sda_driving_sys)   # -> sys

        _keys_ok = Signal()
        self.comb += _keys_ok.eq(self.keys_loaded.status == 40)
        self.comb += self.status.status.eq(Cat(
            self.rx_enable.storage & _keys_ok,   # bit0: rx_armed
            _keys_ok,                            # bit1: keys_ok
            _km_valid_sys,                       # bit2: km_valid_hw
            self._r0_valid_sys,                  # bit3: r0_valid (sticky)
            _sda_driving_sys,                    # bit4: sda_driving
            Signal(3),                           # bits 7:5 spare
        ))

        # optional local drive of the override pad
        if sda_override is not None:
            self.comb += sda_override.eq(self.sda_drive_low)

        # ===============================================================
        # Verilog instances (black boxes; omit for pure-migen simulation).
        # ===============================================================
        if with_instances:
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
                o_An=self._an_eth,
                o_Aksv=self._aksv_eth,
                o_Ainfo=self._ainfo_eth,
                o_aksv_done=self._aksv_done_eth,
                i_Bksv=self._bksv_eth,
                i_Ri=self._ri_eth,
                i_Pj=0,
                i_key_index=self.key_index.storage,
                i_key_lo=self.key_data_lo.storage,
                i_key_hi=self.key_data_hi.storage,
                i_key_we=self.key_we_sync.o,
                i_keys_clear=self.keys_clear_sync.o,
                o_keys_loaded=self._keys_loaded_eth,
                o_Km_hw=self._km_hw_eth,
                o_Km_valid_hw=self._km_valid_hw_eth,
            )
            self.specials += Instance(
                "hdcp_cipher_rx",
                i_clk=ClockSignal("pix_o"),
                i_reset=ResetSignal("pix_o"),
                i_Km=self.Km,
                i_An=self.An_cipher,
                i_hdcpBlockCipher_init=self.cipher_init,
                i_authentication=self.cipher_auth,
                i_hdcpRekeyCipher=self.cipher_rekey,
                i_hdcpStreamCipher=self.cipher_stream_adv,
                o_pr_data=self.cipher_stream,
                o_stream_ready=self.stream_ready,
                o_Ri=self._cipher_ri,
                o_R0_valid=self._cipher_r0_valid,
            )
