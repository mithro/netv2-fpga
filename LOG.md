# NeTV2 modernisation work log

Newest entries first. Dates are ISO 8601. Every entry names the branch, what was
done, what was measured, and what is still open.

## 2026-09-05 (phase 1, branch phase1-baseline)

- Phase 0 merged into `modern` (137c709). The merge commit's `Co-Authored-By`
  trailer has a typo in the domain; it stays, since force-pushing is not allowed.
- **Defect found and fixed (a1af75e):** five `legacy/deps/*` gitlinks (litedram,
  liteeth, litescope, litevideo, pyserial) recorded the commits of an earlier
  xobs `quickstart` working-tree checkout instead of AlphamaxMedia master's pins.
  Cause: `git commit -qam` in commit df02245 (a spec edit) staged the dirty
  submodule pointers; the later `legacy/` move then carried them as R100 renames,
  which is why the review's rename check did not flag them. `legacy/deps` now
  matches `alphamax/master` exactly. Lesson recorded: never `git commit -a` in a
  checkout with modified submodules. `modern` carries the wrong pins between
  df02245 and the phase 1 merge; nothing was built from them.
- Phase 1 tasks 10, 11, 12 (docs), 13 (baseline run) and 15 (2019 rebuild) run in
  parallel without committing; the controller commits. Task 14 follows 13.
- Phase 1 complete on `phase1-baseline`: eight `docs/original/` pages, the
  baseline suite report (29/0/3), EDID+console audio evidence, and the 2019
  rebuild. Rebuild findings: the 2019 design regenerates and synthesises on
  Vivado 2025.2 but fails timing by ~7.5 ns post-route and fills the 35T (BRAM
  95%, MMCM 4/5); firmware on the golden unit predates `debug t4i/t4d`; the
  MS2109 EDID advertises audio so EDID does not explain the T23 silence. These
  drive phase 2/3 (the modern LiteX port is the path, not patching 2019; the
  per-part feature matrix D36 matters because the 35T is nearly full).
- HDCP receiver work (inserted as higher priority per Tim, via the RPi-side
  coordinator): a Python HDCP 1.4 cipher reference model (bit-exact vs the spec
  Appendix A and vs bunnie's Verilog in xsim) and the receiver design spec landed
  on this branch as non-hardware groundwork; the receiver spec is under review;
  RTL follows on a dedicated branch off `modern`. Key finding relayed to the RPi
  side: `hdcp_mod.v` re-encrypts the overlay, it does not decrypt the
  passthrough, so DoD 3 (clean decode) is new gateware, separate from the
  receiver (DoD 1+2). Shared closed-loop keys verified (the agreed Km, held only in the handoff dir, never committed); no
  real device keys used; key .bin files never committed.
- Two `git submodule` commands issued to the rebuild agent were blocked by the
  auto-mode classifier; the agent found `sync` was unnecessary and used
  single-path `update --init`, which was allowed.
- User instruction: created `mithro/netv2-testsuite` (public) with the GitHub.md
  settings; pushed the ten64 suite history (65 commits, `main` at c30a0af, tag
  `v0.0` on the root commit); ten64's `~/github/mithro/netv2` now tracks it. The
  subtree in `tests/hdmi-suite/` is refreshed from it with `git subtree pull`.
  User also said: accept the changed tweed host key, and use IPv6 or private IPv4
  (never the public IPv4) for the lab hosts.

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
- Re-review of the fixes: correctness approved; hardware safety found that the
  REPL filter could be bypassed with an embedded newline (the firmware executes
  every line) and that the plan still carried the rejected deny-list code. Fixed:
  CR/LF refused outright, case-folded token check, `console_command` requires
  its line and is filtered, `service_restart` (pm2 mm, lightdm) allowed on the
  golden unit as the suite already does it, `rootfs_write` added and refused,
  plan Task 8 marked superseded. 28 unit tests.
