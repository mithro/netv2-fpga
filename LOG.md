# NeTV2 modernisation work log

Newest entries first. Dates are ISO 8601. Every entry names the branch, what was
done, what was measured, and what is still open.

## 2026-09-05

- Cloned all 23 AlphamaxMedia repositories; forked or branch-archived them under
  `mithro` as `alphamax-<branch>` branches. `mithro/netv2-soc` pre-existed (2016,
  unrelated); only branches were added.
- Created `modern` from AlphamaxMedia `master` (4f4dd0d). Wrote the design spec
  (`docs/superpowers/specs/2026-09-05-netv2-modernisation-design.md`), reviewed
  three times (completeness twice, technical feasibility once); v2.3 committed.
  Round-3 fixes were applied without a fourth review (skill cap), flagged for the
  user.
- Blocked on the user: creating `mithro/netv2-testsuite` (classifier denied
  `gh repo create`); reaching the netboot Pi 3B+ nodes (tweed host key changed).
- Phase 0 started on branch `phase0-repo-setup`.
- Mirrored LiteX 2026.04's migen pin 4c2ae8d (git.m-labs.hk) to mithro/migen branch netv2-pin.
- Phase 0 complete on phase0-repo-setup: legacy/ move, uv project (LiteX 2026.04), subtree tests/hdmi-suite (which also brought in concurrent ten64 work: an hdcp/ directory about HDCP output from rpiz-3), REPL contract (28 commands), host table + golden guard, Pi 5 notes. Task 1 to 8 spec checks were done by the controller by direct inspection; the four-direction review runs on the whole branch before merge.
- Phase 0 four-direction review: security approved; docs approved; correctness and
  hardware safety requested changes, all applied: liteiclink was unpinned (2025.4 from
  PyPI) and is now at tag 2026.04; the golden-unit guard is now an allowlist with a
  masked-IDCODE comparison, a host resolver and a REPL command deny-list (reboot, mw,
  mc); the REPL contract generator now fails loudly on multi-line calls. Recorded for
  later phases: the guard is advisory until hardware scripts route through it; the
  ten64 source agent on rpiz-3 listens unauthenticated on all interfaces as root and
  the suite relies on broad passwordless sudo (pre-existing, fix when the suite is next
  edited); `git log modern..phase0-repo-setup` includes the 60 imported suite commits.
