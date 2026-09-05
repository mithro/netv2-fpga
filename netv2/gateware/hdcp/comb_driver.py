"""Helper to drop a single combinational driver from a migen Module/fragment.

Task H4 of ``docs/superpowers/plans/2026-09-06-hdcp-receiver-plan.md`` (spec
section 9 of ``docs/superpowers/specs/2026-09-06-hdcp-receiver-design.md``).

``legacy/netv2mvp.py:874-877`` already ties both DDC-override pads to 0 in
``self.comb``::

    self.comb += [
        platform.request("hdmi_sda_over_up").eq(0),
        platform.request("hdmi_sda_over_dn").eq(0),
    ]

The HDCP-receiver bridge top level (H5) must instead let ``HDCPReceiver`` drive
``hdmi_sda_over_dn`` (via ``sda_drive_low``).  migen raises on a second
combinational driver of the same signal, so the bridge first removes the
existing ``hdmi_sda_over_dn.eq(0)`` with :func:`release_comb_driver`, then adds
its own assignment.

``release_comb_driver`` asserts that **exactly one** combinational assignment to
the signal existed and was removed.  If the parent design ever changes so that
the signal is undriven (0 assignments) or double-driven (>1), the function
raises loudly rather than silently mis-driving a FET gate.

migen fragment structure (verified against the pinned migen,
``migen/fhdl/structure.py`` in the ``uv`` env, migen 0.9.2 / rev 4c2ae8d):

* A ``Module`` keeps its statements on ``module._fragment`` (a ``_Fragment``);
  ``_fragment.comb`` is a plain ``list`` of statements (``migen/fhdl/module.py``
  ``_ModuleComb`` appends to ``self._fm._fragment.comb``).
* A combinational assignment ``sig.eq(0)`` is an ``_Assign`` whose ``.l``
  attribute is the (wrapped) target -- for a plain ``Signal`` target, ``.l`` is
  that same ``Signal`` object, so identity comparison is exact
  (``migen/fhdl/structure.py`` ``_Assign.__init__`` / ``wrap``).
* Control flow nests statements in lists: ``If`` on ``.t`` / ``.f``, ``Case`` on
  the lists in ``.cases``.  We recurse into those so a driver buried in an
  ``If``/``Case`` is still found (the netv2mvp case is top-level).
"""

from migen.fhdl.structure import Case, If, _Assign

__all__ = ["release_comb_driver"]


def _find_assigns(stmts, signal, found):
    """Collect ``(container_list, index)`` for every ``_Assign`` targeting *signal*."""
    for i, s in enumerate(stmts):
        if isinstance(s, _Assign):
            if s.l is signal:
                found.append((stmts, i))
        elif isinstance(s, If):
            _find_assigns(s.t, signal, found)
            _find_assigns(s.f, signal, found)
        elif isinstance(s, Case):
            for sub in s.cases.values():
                _find_assigns(sub, signal, found)
        elif isinstance(s, (list, tuple)):
            _find_assigns(s, signal, found)


def release_comb_driver(module, signal):
    """Remove the single combinational ``_Assign`` whose target is *signal*.

    *module* may be a migen ``Module`` (its ``_fragment.comb`` list is walked) or
    a raw fragment / anything exposing a ``.comb`` list.

    Raises ``ValueError`` unless exactly one such assignment exists.  On success
    the assignment is removed in place and the function returns ``None``.
    """
    frag = getattr(module, "_fragment", module)
    comb = getattr(frag, "comb", None)
    if comb is None:
        raise ValueError(
            f"release_comb_driver: object {module!r} has no combinational statements "
            "(no _fragment.comb / .comb)")

    found = []
    _find_assigns(comb, signal, found)

    if len(found) == 0:
        raise ValueError(
            f"release_comb_driver: signal {signal!r} has no combinational driver to "
            "release (expected exactly one)")
    if len(found) > 1:
        raise ValueError(
            f"release_comb_driver: signal {signal!r} is driven by {len(found)} combinational "
            "assignments (expected exactly one); refusing to guess which to "
            "remove")

    container, index = found[0]
    if not isinstance(container, list):
        raise TypeError(
            f"release_comb_driver: the assignment to {signal!r} lives in an immutable "
            f"container {type(container)!r} and cannot be removed")
    del container[index]
