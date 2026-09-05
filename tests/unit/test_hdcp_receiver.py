"""Unit tests for the H4 HDCP-receiver migen wrapper and its CDC helper.

Covers:
* ``HDCPReceiver`` elaborates to Verilog (``migen.fhdl.verilog.convert``).
* the AutoCSR map exposes every expected CSR.
* the ``km_source`` Km/Km_valid output mux selects the CPU vs the hardware path
  (pure-migen ``run_simulation`` with the Verilog instances omitted).
* ``release_comb_driver`` removes exactly one combinational driver and raises on
  0 or >1 -- verified against the real migen fragment structure.
"""

import pytest
from migen import Module, Signal, run_simulation
from migen.fhdl import verilog

from netv2.gateware.hdcp.comb_driver import release_comb_driver
from netv2.gateware.hdcp.receiver import HDCPReceiver

MASK56 = (1 << 56) - 1
CPU_KM = 0x0102030405060A & MASK56
HW_KM  = 0xA5A5A5A5A5A5A5 & MASK56


# --------------------------------------------------------------------------
# Elaboration + CSR map
# --------------------------------------------------------------------------

EXPECTED_CSRS = {
    "bksv", "key_index", "key_data_lo", "key_data_hi", "key_we", "keys_clear",
    "keys_loaded", "rx_enable", "km_source", "frame_offset",
    "r0", "ri", "aksv", "an", "ainfo", "km_hw", "status",
}


def test_hdcp_receiver_elaborates_to_verilog():
    dut = HDCPReceiver()
    out = verilog.convert(dut)
    src = out.main_source if hasattr(out, "main_source") else str(out)
    assert "module top" in src
    # the two receiver Verilog instances are present as black boxes
    assert "hdcp_rx" in src
    assert "hdcp_cipher_rx" in src


def test_hdcp_receiver_csr_map():
    dut = HDCPReceiver()
    names = {csr.name for csr in dut.get_csrs()}
    missing = EXPECTED_CSRS - names
    assert not missing, f"missing CSRs: {sorted(missing)} (have {sorted(names)})"


# --------------------------------------------------------------------------
# km_source Km / Km_valid output mux
# --------------------------------------------------------------------------

def test_km_source_mux_selects_cpu_vs_hardware():
    # with_instances=False: no Verilog black boxes, so the .v-driven signals are
    # free for the testbench to drive as stand-ins for the hardware Km path.
    dut = HDCPReceiver(with_instances=False)

    results = {}

    def gen():
        # stand-in hardware side (normally driven by hdcp_rx.v)
        yield dut._km_hw_eth.eq(HW_KM)
        yield dut._km_valid_hw_eth.eq(1)
        yield dut._keys_loaded_eth.eq(40)
        yield dut.rx_enable.storage.eq(1)
        # CPU side
        yield dut.cpu_km.eq(CPU_KM)
        yield dut.cpu_km_valid.eq(1)

        # --- km_source = 0 : CPU path ---
        yield dut.km_source.storage.eq(0)
        for _ in range(300):
            yield
        results["cpu_km"] = yield dut.Km
        results["cpu_valid"] = yield dut.Km_valid

        # --- km_source = 1 : hardware path ---
        yield dut.km_source.storage.eq(1)
        for _ in range(300):
            yield
        results["hw_km"] = yield dut.Km
        results["hw_valid"] = yield dut.Km_valid

        # --- hardware path, but disarmed: Km_valid must gate off ---
        yield dut.rx_enable.storage.eq(0)
        for _ in range(300):
            yield
        results["hw_km_disarmed"] = yield dut.Km
        results["hw_valid_disarmed"] = yield dut.Km_valid

    run_simulation(dut, gen(), clocks={"sys": 8, "eth": 20, "pix_o": 14})

    assert results["cpu_km"] == CPU_KM
    assert results["cpu_valid"] == 1
    assert results["hw_km"] == HW_KM
    assert results["hw_valid"] == 1
    # data still routes from the hardware side, but valid is gated by rx_enable_eff
    assert results["hw_km_disarmed"] == HW_KM
    assert results["hw_valid_disarmed"] == 0


# --------------------------------------------------------------------------
# release_comb_driver
# --------------------------------------------------------------------------

class _Toy(Module):
    def __init__(self):
        self.target = Signal()
        self.other = Signal()
        self.src = Signal()
        self.comb += [
            self.target.eq(0),
            self.other.eq(self.src),
        ]


class _NoDriver(Module):
    def __init__(self):
        self.target = Signal()
        self.other = Signal()
        self.comb += self.other.eq(1)


class _DoubleDriver(Module):
    def __init__(self):
        self.target = Signal()
        self.other = Signal()
        self.comb += [
            self.target.eq(0),
            self.other.eq(1),
            self.target.eq(0),
        ]


def _comb_targets(module):
    from migen.fhdl.structure import _Assign
    return [s.l for s in module._fragment.comb if isinstance(s, _Assign)]


def test_release_comb_driver_removes_exactly_one():
    toy = _Toy()
    # sanity: both drivers present before
    assert toy.target in _comb_targets(toy)
    assert toy.other in _comb_targets(toy)

    release_comb_driver(toy, toy.target)

    targets = _comb_targets(toy)
    assert toy.target not in targets, "target driver should be gone"
    assert toy.other in targets, "unrelated driver must remain"
    # after removal the fragment can still be converted (no dangling reference)
    toy.comb += toy.target.eq(toy.src)  # a new driver can now be installed
    verilog.convert(toy)


def test_release_comb_driver_raises_when_undriven():
    m = _NoDriver()
    with pytest.raises(ValueError):
        release_comb_driver(m, m.target)


def test_release_comb_driver_raises_when_double_driven():
    m = _DoubleDriver()
    with pytest.raises(ValueError):
        release_comb_driver(m, m.target)


def test_release_comb_driver_finds_driver_after_finalize():
    # exercise the real finalized-fragment path (spec 9: "walk the finalized
    # fragment comb list").
    toy = _Toy()
    toy.finalize()
    release_comb_driver(toy, toy.target)
    assert toy.target not in _comb_targets(toy)
    assert toy.other in _comb_targets(toy)
