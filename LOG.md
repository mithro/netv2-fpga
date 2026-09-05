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
