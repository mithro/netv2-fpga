"""Migen simulations for the ported litevideo HDMI-input decode blocks.

These exercise the pure-logic core of the ported pipeline -- character
alignment (:class:`CharSync`), TMDS control/data decode (:class:`Decoding`),
and the TERC4 data-island state machine (:class:`DecodeTERC4`) -- against
hand-built token streams. They need no FPGA and no toolchain.

The blocks are written in the ``pix`` clock domain; for simulation we rename
``pix`` -> ``sys`` so migen's default single-clock simulator drives them.

Run directly:

    uv run python tests/sim/video/test_terc4_decoder.py

or under pytest:

    uv run pytest tests/sim/video/test_terc4_decoder.py
"""

from migen import *

from netv2.gateware.video.input.common import control_tokens
from netv2.gateware.video.input.charsync import CharSync
from netv2.gateware.video.input.decoding import (
    Decoding, DecodeTERC4, terc4_tokens, data_gb_tokens, video_gb_tokens,
)


def _sys(m):
    """Rename the block's ``pix`` domain to ``sys`` for simulation."""
    return ClockDomainsRenamer({"pix": "sys"})(m)


# ---------------------------------------------------------------------------
# CharSync: find the control-token alignment in a raw 10-bit TMDS stream.
# ---------------------------------------------------------------------------
def test_charsync_locks_on_aligned_control():
    dut = _sys(CharSync(required_controls=8))

    def gen():
        token = control_tokens[0]
        # Feed the same aligned control token every cycle; after
        # required_controls consecutive matches at a stable position the
        # module must assert 'synced' and pass the token through unshifted.
        for _ in range(20):
            yield dut.raw_data.eq(token)
            yield
        assert (yield dut.synced) == 1, "CharSync failed to synchronise"
        assert (yield dut._char_synced.status) == 1
        assert (yield dut.data) == token, "aligned data not passed through"

    run_simulation(dut, gen())


# ---------------------------------------------------------------------------
# Decoding: control tokens -> de=0 + 2-bit c; anything else -> de=1 (data).
# ---------------------------------------------------------------------------
def test_decoding_control_tokens():
    dut = _sys(Decoding())

    def gen():
        yield dut.valid_i.eq(1)
        # Each control token decodes to de=0 and c == its index.
        for ci, tok in enumerate(control_tokens):
            yield dut.input.eq(tok)
            yield
            yield  # 1-cycle registered output
            assert (yield dut.output.de) == 0, f"ctl token {ci} not flagged as control"
            assert (yield dut.output.c) == ci, f"ctl token {ci} wrong c code"
            assert (yield dut.valid_o) == 1

        # A non-control word decodes as active data (de=1).
        yield dut.input.eq(terc4_tokens[3])
        yield
        yield
        assert (yield dut.output.de) == 1, "data word wrongly flagged as control"

    run_simulation(dut, gen())


# ---------------------------------------------------------------------------
# DecodeTERC4: drive a full data-island (preamble -> data guardband ->
# 32-char TERC4 packet -> guardband) and check the packet/char counters and
# the island event, then drive a video period and check de_hdmi.
# ---------------------------------------------------------------------------
def _drive(dut, raw0, raw1, raw2, cycles=1):
    for _ in range(cycles):
        yield dut.data_in0.raw.eq(raw0)
        yield dut.data_in1.raw.eq(raw1)
        yield dut.data_in2.raw.eq(raw2)
        yield


def test_terc4_data_island_counts():
    dut = _sys(DecodeTERC4())

    CTL1 = control_tokens[1]          # decodes to c=1 on ch1/ch2
    DGB  = data_gb_tokens[0]          # data guardband token
    T4   = terc4_tokens[5]            # an ordinary TERC4 data character

    def gen():
        yield dut.valid_i.eq(1)

        # --- control period: ctl_code = {ch2.c, ch1.c} = 0b0101 -> PREAM_T4
        yield from _drive(dut, CTL1, CTL1, CTL1, cycles=4)
        # --- data guardband (ch1 & ch2 dgb) -> GOING_T4
        yield from _drive(dut, DGB, DGB, DGB, cycles=3)
        # --- TERC4 payload: > 32 chars so the char counter wraps at 31 and
        #     the packet counter increments (t4packet event).
        yield from _drive(dut, T4, T4, T4, cycles=40)
        char_after = (yield dut.t4d_char.status)
        count_after = (yield dut.t4d_count.status)
        # --- closing data guardband -> LEAVE_T4 (t4island event) -> INIT.
        # Then idle a few cycles so the pulse-latched pending bit settles.
        yield from _drive(dut, DGB, DGB, DGB, cycles=3)
        yield from _drive(dut, CTL1, CTL1, CTL1, cycles=4)
        island_pending = (yield dut.ev.t4island.pending)

        assert count_after >= 1, f"expected >=1 completed 32-char packet, got {count_after}"
        assert char_after != 0, "char counter never advanced inside the island"
        assert island_pending == 1, "t4island event did not latch on island end"

    run_simulation(dut, gen())


def test_terc4_video_period_sets_de():
    dut = _sys(DecodeTERC4())

    def gen():
        PIX = 0b1111100000  # an active pixel word: not control/guardband/terc4

        yield dut.valid_i.eq(1)
        # All-channel video guardbands -> GOING_VID ...
        yield from _drive(dut,
                          video_gb_tokens[0], video_gb_tokens[1], video_gb_tokens[2],
                          cycles=3)
        # ... then active pixels (all_vgb drops) -> VIDEO, where de_hdmi=1.
        # dvimode defaults 0, so de_o follows de_hdmi.
        yield from _drive(dut, PIX, PIX, PIX, cycles=5)
        assert (yield dut.de_hdmi) == 1, "VIDEO state did not assert de_hdmi"
        assert (yield dut.de_o) == 1, "de_o did not follow de_hdmi in DVI-off mode"

    run_simulation(dut, gen())


if __name__ == "__main__":
    test_charsync_locks_on_aligned_control()
    print("charsync: OK")
    test_decoding_control_tokens()
    print("decoding: OK")
    test_terc4_data_island_counts()
    print("terc4 data island: OK")
    test_terc4_video_period_sets_de()
    print("terc4 video period: OK")
    print("all video-input sim tests passed")
