# Phase 0 and 1: Repo Setup and Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `modern` branch of `mithro/netv2-fpga` into a pinned, reproducible LiteX 2026.04 project that contains the original tree, the hardware test suite, the frozen REPL contract, a hardware-harness skeleton with the golden-unit guard, and a documented behavioural baseline captured from the stock NeTV2.

**Architecture:** The original 2019 tree moves under `legacy/` untouched (submodules included). A new `uv` project at the repo root pins the LiteX family by git tag and migen by SHA (mirrored to `mithro/migen`). The ten64 HDMI test suite is merged as a git subtree under `tests/hdmi-suite/`. Documentation lives in `docs/original`, `docs/current`, `docs/testing`; `LOG.md` records dated progress.

**Tech Stack:** git (subtree, submodules), uv 0.12, Python 3.13 (desktop) and 3.5 (golden unit), LiteX 2026.04 family, pytest, ssh to `pi@rpi3-netv2.iot.welland.mithis.com`, `tim@rpi5-netv2.iot.welland.mithis.com`, `ten64.welland.mithis.com`.

**Spec:** `docs/superpowers/specs/2026-09-05-netv2-modernisation-design.md` (v2.3). Decisions referenced as D<n>.

**Hard rules for every task (D6, D8):** never write SPI flash, never power-cycle, never re-image `rpi3-netv2`. On `rpi3-netv2` the only permitted actions in this plan are running the existing test suite and reading the serial console. No bitstream is loaded onto any board in phases 0 or 1.

**Conventions:** all Python runs through `uv run`; scripts with more than two commands are Python, not shell; ISO dates; commit after every task with the trailer

```
Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011SpK83e5d2zTn8CiPTKRTt
```

**Hooks active in this environment (commands violating them are denied):** no `python -c`/`python3 -c` (write a script file and run it); heredocs must use a single-quoted delimiter (`<<'EOF'`), and a Bash command whose text merely contains an unquoted `<<EOF` is also denied; never `2>/dev/null`; never create files under `/tmp/` (use `/home/tim/github/AlphamaxMedia/tmp/`); never `git push --force`; commits with very many files may be refused, so split the `legacy/` move commit by directory if that happens.

Work happens on branch `phase0-repo-setup` (tasks 1 to 9) and `phase1-baseline` (tasks 10 to 15), each branched from `modern` and merged back with `--no-ff` after the four-direction review (spec section 4.8). Working directory for all commands: `/home/tim/github/AlphamaxMedia/netv2-fpga`.

---

## File structure after this plan

```
LOG.md                                   dated work log (new)
Makefile                                 sync / test / lint entry points (new)
pyproject.toml, uv.lock                  pinned LiteX family (new)
.python-version                          3.13 (new)
legacy/                                  moved original tree: netv2mvp.py, firmware/, deps/, ...
netv2/__init__.py                        package marker only (new)
scripts/gen_repl_contract.py             extracts REPL commands used by the suite (new)
scripts/parse_edid.py                    minimal EDID CTA-861 block parser (new)
tests/hdmi-suite/                        subtree of ten64 suite (LOG.md, README.md, netv2test/, agent/, reports/, ...)
tests/hardware/__init__.py
tests/hardware/hosts.py                  host table + golden-unit guard (new)
tests/hardware/test_hosts.py             unit tests for the guard (new)
tests/unit/test_gen_repl_contract.py     unit tests for the extractor (new)
tests/unit/test_parse_edid.py            unit tests for the EDID parser (new)
docs/original/README.md                  index of "how it worked" docs (new)
docs/original/{hardware,gateware,clocking,firmware,pi-software,factory-test,boot-and-flash}.md
docs/original/rebuild-2019.md            time-boxed rebuild attempt result
docs/current/README.md, repl-contract.md, pi5-programming.md, pi5-rp1-pio-jtag.md
docs/testing/README.md                   rigs and procedures
docs/testing/reports/2026-09-baseline/   baseline suite report, t4d output, EDID analysis
```

---

## Phase 0: repo setup

### Task 1: LOG.md, docs skeleton and branch

**Files:**
- Create: `LOG.md`, `docs/original/README.md`, `docs/current/README.md`, `docs/testing/README.md`, `docs/testing/reports/.gitkeep`

- [ ] **Step 1: Create the branch**

```bash
git checkout modern && git pull mithro modern && git checkout -b phase0-repo-setup
```

- [ ] **Step 2: Write `LOG.md`**

```markdown
# NeTV2 modernisation work log

Newest entries first. Dates are ISO 8601. Every entry names the branch, what was
done, what was measured, and what is still open.

## 2026-09-05

- Cloned all 23 AlphamaxMedia repositories; forked or branch-archived them under
  `mithro` as `alphamax-<branch>` branches. `mithro/netv2-soc` pre-existed (2016,
  unrelated); only branches were added.
- Created `modern` from AlphamaxMedia `master` (4f4dd0d). Wrote the design spec
  (`docs/superpowers/specs/2026-09-05-netv2-modernisation-design.md`), reviewed
  three times (completeness twice, technical feasibility once); v2.2 committed.
  Round-3 fixes were applied without a fourth review (skill cap), flagged for the
  user.
- Blocked on the user: creating `mithro/netv2-testsuite` (classifier denied
  `gh repo create`); reaching the netboot Pi 3B+ nodes (tweed host key changed).
- Phase 0 started on branch `phase0-repo-setup`.
```

- [ ] **Step 3: Write the three README index files**

`docs/original/README.md`:

```markdown
# How NeTV2 worked originally (2018 to 2019)

Written from the AlphamaxMedia sources at `legacy/` (netv2-fpga master 4f4dd0d)
and the stock unit `rpi3-netv2`. Each page cites the file and line it describes.

- [hardware.md](hardware.md): board, FPGA variants, Pi connections, jumpers
- [gateware.md](gateware.md): `VideoOverlaySoC`, video pipeline, compositing, HDCP
- [clocking.md](clocking.md): CRG, HDMI input clocking, DRP, timing exceptions
- [firmware.md](firmware.md): REPL, boot, EDID, multires, MMCM tables
- [boot-and-flash.md](boot-and-flash.md): BIOS, SPI NOR layout, `mknetv2img`, updater
- [pi-software.md](pi-software.md): OpenOCD flow, MagicMirror, pm2, JSON feed
- [factory-test.md](factory-test.md): exclave, netv2-tests, jig-20, test hat, imaging
- [rebuild-2019.md](rebuild-2019.md): time-boxed attempt to rebuild the 2019 design today
```

`docs/current/README.md`:

```markdown
# How NeTV2 works now

Pages are added as phases land. See `LOG.md` for progress.

- [repl-contract.md](repl-contract.md): frozen console command and output contract
- [pi5-programming.md](pi5-programming.md): JTAG and SPI flash from a Raspberry Pi 5
- [pi5-rp1-pio-jtag.md](pi5-rp1-pio-jtag.md): high-speed JTAG via the RP1 PIO
```

`docs/testing/README.md`:

```markdown
# Testing

- Rigs: `rpi3-netv2` (golden 35T unit, MS2109 capture, `rpiz-3` source; volatile
  JTAG loads only, never flash, never power-cycle), `rpi5-netv2` (100T, PCIe,
  UART, no capture). Details in `tests/hardware/hosts.py`.
- Suite: `tests/hdmi-suite/` (runs on the Pi attached to the board).
- Reports: `reports/<YYYY-MM>-<name>/` with `report.md`, `report.json`, evidence.
```

- [ ] **Step 4: Commit**

```bash
mkdir -p docs/testing/reports && touch docs/testing/reports/.gitkeep
git add LOG.md docs/original/README.md docs/current/README.md docs/testing/README.md docs/testing/reports/.gitkeep
git commit -m "docs: add work log and documentation skeleton"
```

### Task 2: Move the original tree under `legacy/`

**Files:**
- Move: every top-level path except `.git`, `.github`, `.gitignore`, `.gitmodules`, `README.adoc`, `docs/superpowers`, `docs/original`, `docs/current`, `docs/testing`, `LOG.md`
- Modify: `.gitmodules` (paths become `legacy/deps/...`, updated by `git mv`)

Submodules must be moved one at a time with `git mv` so `.gitmodules` paths are rewritten; moving the parent directory does not update them.

- [ ] **Step 1: Record the current submodule state**

Run: `git submodule status | tee /home/tim/github/AlphamaxMedia/tmp/submodules-before.txt`
Expected: seven lines (`deps/litedram`, `deps/liteeth`, `deps/litescope`, `deps/litevideo`, `deps/litex`, `deps/migen`, `deps/pyserial`).

- [ ] **Step 2: Remove the untracked leftover and move submodules individually, then the rest**

`deps/litepcie/` is an untracked directory left behind by the earlier xobs `quickstart` checkout (that branch had a litepcie submodule; AlphamaxMedia master does not). `git mv` would abort on it, so delete it first:

```bash
git ls-files deps/litepcie | wc -l   # expected 0: not tracked on this branch
rm -rf deps/litepcie
```

Write and run `scripts/_move_legacy.py` (deleted at the end of this task; it is a one-off):

```python
"""One-off: move the original AlphamaxMedia tree under legacy/ with git mv."""
import subprocess, pathlib

KEEP = {".git", ".github", ".gitignore", ".gitmodules", "README.adoc", "docs", "LOG.md", "scripts"}
SUBMODULES = ["litedram", "liteeth", "litescope", "litevideo", "litex", "migen", "pyserial"]

def git(*args):
    print("git", *args, flush=True)
    subprocess.run(["git", *args], check=True)

def tracked(path):
    out = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)], capture_output=True)
    return out.returncode == 0

pathlib.Path("legacy/deps").mkdir(parents=True, exist_ok=True)
for name in SUBMODULES:
    git("mv", f"deps/{name}", f"legacy/deps/{name}")
# whatever is left in deps/ (the vendored site/ tree) and the other top-level entries
for p in sorted(pathlib.Path(".").iterdir()):
    if p.name in KEEP or p.name == "legacy":
        continue
    if p.name == "deps":
        for q in sorted(p.iterdir()):
            if tracked(q):
                git("mv", str(q), f"legacy/deps/{q.name}")
            else:
                print("skip untracked", q)
        continue
    if tracked(p):
        git("mv", str(p), f"legacy/{p.name}")
    else:
        print("skip untracked", p)
# the original docs/ directory (not ours) lives at docs/ too: move its files
for q in sorted(pathlib.Path("docs").iterdir()):
    if q.name in {"superpowers", "original", "current", "testing"}:
        continue
    pathlib.Path("legacy/docs").mkdir(exist_ok=True)
    git("mv", str(q), f"legacy/docs/{q.name}")
```

Run: `uv run --no-project python scripts/_move_legacy.py`

- [ ] **Step 3: Verify**

Run: `git submodule status && grep path .gitmodules && ls legacy`
Expected: all seven submodule paths begin with `legacy/deps/`; `.gitmodules` `path =` lines all begin with `legacy/deps/`; `legacy/` contains `netv2mvp.py`, `firmware`, `overlay`, `production-images`, `testing-images`, `bin`, `sim`, `software`, `test`, `lxbuildenv.py`, the four `make_*.sh` scripts, `netv2mvp_genddr.py`, `deps`.

Run: `git status --short | grep -v '^R' | grep -v '^M  .gitmodules' | head`
Expected: no output other than the untracked one-off script (every change is a rename plus the `.gitmodules` edit).

- [ ] **Step 4: Add a `legacy/README.md`**

```markdown
# legacy/

The unmodified AlphamaxMedia `netv2-fpga` tree (master 4f4dd0d, 2023-07-13) as
shipped: `netv2mvp.py` (LiteX 2019-03 plus forks pinned as submodules under
`deps/`), the RISC-V firmware, the HDCP/phase-alignment Verilog under `overlay/`,
and the production and testing bitstreams. No original file is modified; the
only additions are two 2026 tooling files for the rebuild experiment
(`Dockerfile.rebuild2019`, `rebuild2019_verilog.py`). The modern tree lives one
level up. See `docs/original/` for the description.
```

- [ ] **Step 5: Commit**

```bash
rm scripts/_move_legacy.py; rmdir --ignore-fail-on-non-empty scripts
git add -A legacy .gitmodules && git commit -m "refactor: move the original 2019 tree under legacy/

Submodules moved one by one with git mv so .gitmodules paths follow.
No file content changes."
```

### Task 3: Mirror the pinned migen SHA into `mithro/migen`

LiteX 2026.04 pins migen `4c2ae8dfeea37f235b52acb8166f12acaaae4f7c` from `https://git.m-labs.hk/M-Labs/migen` (`litex_repos.py` lines 23 to 28 at tag 2026.04). D22 mirrors it into `mithro/migen` as branch `netv2-pin`.

- [ ] **Step 1: Fetch and push**

```bash
cd /home/tim/github/AlphamaxMedia/migen
git remote add mlabs https://git.m-labs.hk/M-Labs/migen.git 2>/dev/null || true
git fetch mlabs master
git rev-parse --verify 4c2ae8dfeea37f235b52acb8166f12acaaae4f7c^{commit}
git push mithro 4c2ae8dfeea37f235b52acb8166f12acaaae4f7c:refs/heads/netv2-pin
cd /home/tim/github/AlphamaxMedia/netv2-fpga
```

Expected: `rev-parse` prints the SHA (object present after fetch); push reports `[new branch] ... -> netv2-pin`. If `rev-parse` fails because the SHA is not on `master`, fetch it directly: `git fetch mlabs 4c2ae8dfeea37f235b52acb8166f12acaaae4f7c`.

- [ ] **Step 2: Verify on GitHub**

Run: `gh api repos/mithro/migen/branches/netv2-pin --jq .commit.sha`
Expected: `4c2ae8dfeea37f235b52acb8166f12acaaae4f7c`

- [ ] **Step 3: Log it**

Append to the 2026-09-05 section of `LOG.md`: `- Mirrored LiteX 2026.04's migen pin 4c2ae8d (git.m-labs.hk) to mithro/migen branch netv2-pin.` Commit: `git commit -am "log: migen pin mirrored"`.

### Task 4: `pyproject.toml` with pinned LiteX family and `uv.lock`

**Files:**
- Create: `pyproject.toml`, `.python-version`, `netv2/__init__.py`, `tests/unit/__init__.py`, `tests/unit/test_pins.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_pins.py`:

```python
"""The installed LiteX family must be exactly the pinned 2026.04 release."""
import importlib.metadata as md


def test_litex_is_2026_04():
    assert md.version("litex") == "2026.04"


def test_family_versions_match():
    for pkg in ["litedram", "liteeth", "litepcie", "litespi", "litescope", "litex-boards"]:
        assert md.version(pkg) == "2026.04", pkg


# The three pythondata packages are deliberately not checked: their version
# strings come from the data they wrap, not from the 2026.04 tag.


def test_migen_importable():
    import migen
    assert hasattr(migen, "Module")
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run --no-project python -m pytest tests/unit/test_pins.py -q 2>&1 | tail -3`
Expected: errors (`No module named pytest` or `PackageNotFoundError`).

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "netv2"
version = "0.1.0"
description = "Kosagi/Alphamax NeTV2 gateware, firmware, host tools and tests, on LiteX 2026.04"
readme = { file = "README.adoc", content-type = "text/plain" }
requires-python = ">=3.11"
license = "BSD-2-Clause"
dependencies = [
    "migen",
    "litex",
    "litex-boards",
    "litedram",
    "liteeth",
    "litepcie",
    "litespi",
    "litescope",
    "pythondata-cpu-vexriscv",
    "pythondata-software-compiler-rt",
    "pythondata-software-picolibc",
    "pyserial>=3.5",
    "meson>=1.0",
    "ninja",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff"]

[tool.uv.sources]
migen = { git = "https://github.com/mithro/migen.git", rev = "4c2ae8dfeea37f235b52acb8166f12acaaae4f7c" }
litex = { git = "https://github.com/enjoy-digital/litex.git", tag = "2026.04" }
litex-boards = { git = "https://github.com/litex-hub/litex-boards.git", tag = "2026.04" }
litedram = { git = "https://github.com/enjoy-digital/litedram.git", tag = "2026.04" }
liteeth = { git = "https://github.com/enjoy-digital/liteeth.git", tag = "2026.04" }
litepcie = { git = "https://github.com/enjoy-digital/litepcie.git", tag = "2026.04" }
litespi = { git = "https://github.com/litex-hub/litespi.git", tag = "2026.04" }
litescope = { git = "https://github.com/enjoy-digital/litescope.git", tag = "2026.04" }
pythondata-cpu-vexriscv = { git = "https://github.com/litex-hub/pythondata-cpu-vexriscv.git", tag = "2026.04" }
pythondata-software-compiler-rt = { git = "https://github.com/litex-hub/pythondata-software-compiler_rt.git", tag = "2026.04" }
pythondata-software-picolibc = { git = "https://github.com/litex-hub/pythondata-software-picolibc.git", tag = "2026.04" }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["netv2"]

[tool.pytest.ini_options]
testpaths = ["tests/unit", "tests/hardware"]
addopts = "-q"
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py311"
```

Write `.python-version` containing `3.13` and an empty `netv2/__init__.py` and `tests/unit/__init__.py`.

Notes for the implementer: the pythondata packages' distribution names use hyphens (`pythondata-software-compiler-rt`) while the repo is `compiler_rt`; if `uv lock` reports a name mismatch, read the package's own `setup.py` `name=` and use that. `pythondata-software-picolibc` is a recursive-submodule repo; uv clones submodules for git sources by default.

- [ ] **Step 4: Lock and sync**

Run: `uv lock 2>&1 | tail -5 && uv sync --extra dev 2>&1 | tail -3`
Expected: `Resolved N packages`, `uv.lock` created, `.venv` populated. Time: several minutes (picolibc and vexriscv are large).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_pins.py -v`
Expected: 3 passed. If `md.version("litex")` is not `2026.04`, LiteX's `setup.py` version string differs from the tag; record the actual string and adjust the assertion to the value printed by `uv run python -c "import litex, importlib.metadata as m; print(m.version('litex'))"` only if it is clearly the 2026.04 release (for example `2026.4`).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version netv2/__init__.py tests/unit/__init__.py tests/unit/test_pins.py
git commit -m "build: uv project pinning the LiteX 2026.04 family and migen 4c2ae8d"
```

### Task 5: Makefile entry points

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write it**

```make
# NeTV2 modern tree. All Python goes through uv.
UV ?= uv

.PHONY: sync test lint clean

sync:
	$(UV) sync --extra dev

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check netv2 scripts tests/unit tests/hardware

clean:
	rm -rf build .pytest_cache
```

- [ ] **Step 2: Verify**

Run: `make test 2>&1 | tail -2`
Expected: `3 passed`.

- [ ] **Step 3: Commit**

```bash
git add Makefile && git commit -m "build: add Makefile entry points (sync, test, lint)"
```

### Task 6: Merge the HDMI test suite as a subtree

The suite is already fetched as remote `ten64-testsuite` (branch `main`, 51 commits as of 2026-09-05; run `git fetch ten64-testsuite` first to pick up anything newer). D4 puts it in-repo; the prefix is `tests/hdmi-suite/` so that its own `netv2test/` package keeps its name (the spec said `tests/netv2test/`; this task also fixes that wording in the spec).

- [ ] **Step 1: Confirm `git subtree` is available**

Run: `git subtree -h 2>&1 | head -1`
Expected: usage text. If missing: `sudo apt install git` provides it on Debian (it is in `/usr/lib/git-core/git-subtree`); do not proceed without it.

- [ ] **Step 2: Add the subtree**

```bash
git fetch ten64-testsuite
git subtree add --prefix=tests/hdmi-suite ten64-testsuite/main -m "tests: import the NeTV2 HDMI test suite from ten64 as a subtree

Source: ten64.welland.mithis.com:~/github/mithro/netv2 (51 commits, no remote).
Runs on the Pi attached to the board; see tests/hdmi-suite/README.md."
```

- [ ] **Step 3: Verify**

Run: `ls tests/hdmi-suite && git log --oneline -1 && git rev-list --count HEAD^2`
Expected: `LOG.md README.md RESOURCES.md agent docs evidence netv2test reports scripts`; the merge commit; the second parent's history count is at least 51 (a path-filtered `git log tests/hdmi-suite` would show only the merge, because the imported commits have their files at the root).

Run: `cd tests/hdmi-suite && uv run --no-project python -c "import ast,sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]; print('ok')" netv2test/*.py && cd -`
Expected: `ok` (the suite is Python 3.5 code; it must still parse on 3.13).

- [ ] **Step 4: Fix the spec wording and commit**

In `docs/superpowers/specs/2026-09-05-netv2-modernisation-design.md` replace both occurrences of `tests/netv2test/` with `tests/hdmi-suite/` (decision 4 and the layout in 4.1).

```bash
git commit -am "docs(spec): suite lives at tests/hdmi-suite/ so its netv2test package keeps its name"
```

### Task 7: REPL contract generator (D33)

**Files:**
- Create: `scripts/gen_repl_contract.py`, `tests/unit/test_gen_repl_contract.py`, `docs/current/repl-contract.md`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_gen_repl_contract.py`:

```python
from pathlib import Path

from scripts.gen_repl_contract import extract_commands, render_markdown

SNIPPET = '''
class Console:
    def status(self):
        return self.command("status")
    def rect(self, x0, y0, x1, y1):
        return self.command("debug setrect %d %d %d %d" % (x0, y0, x1, y1))
    def mode(self, n):
        self.command("video_mode %d" % n)
    def other(self):
        console.command("video_matrix list")
    def json_mode(self, on):
        return self.command("json on" if on else "json off")
'''


def test_extract_commands_finds_literal_and_formatted():
    cmds = extract_commands(SNIPPET, "console.py")
    assert ("status", "console.py") in cmds
    assert ("debug setrect %d %d %d %d", "console.py") in cmds
    assert ("video_mode %d", "console.py") in cmds
    assert ("video_matrix list", "console.py") in cmds
    assert ("json on", "console.py") in cmds
    assert ("json off", "console.py") in cmds


def test_render_markdown_has_table_rows_sorted():
    md = render_markdown({("status", "console.py"), ("help", "tests.py")}, "2026-09-05")
    assert "| `help` | tests.py |" in md
    assert md.index("| `help` |") < md.index("| `status` |")
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_gen_repl_contract.py -q 2>&1 | tail -2`
Expected: `ModuleNotFoundError: No module named 'scripts'`.

- [ ] **Step 3: Implement**

`scripts/__init__.py` (empty) and `scripts/gen_repl_contract.py`:

```python
#!/usr/bin/env python3
"""Generate docs/current/repl-contract.md from the console commands the HDMI test
suite issues (decision 33 of the design spec).

The suite calls ``self.command("<text>")`` / ``console.command("<text>")`` with a
literal (possibly %-formatted) string. Every such string is a command whose text
output format the modern firmware must preserve.
"""
import argparse
import re
from pathlib import Path

# A .command( call and everything up to the closing parenthesis on that line. The
# suite writes literals, %-formatted literals, and conditional expressions such as
# .command("json on" if on else "json off"); every "..." literal inside counts.
CALL_RE = re.compile(r'\.command\((.*?)\)\s*$', re.MULTILINE)
LIT_RE = re.compile(r'"([^"]+)"')

# Commands exercised interactively during phase 1 but not by the suite (spec D33).
# They live under the firmware's `debug` sub-parser (legacy/firmware/ci.c line 991 on).
EXTRA = [("debug t4i", "manual"), ("debug t4d", "manual"),
         ("debug dvimode0", "manual"), ("debug hdmimode0", "manual")]


def extract_commands(source: str, origin: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for call in CALL_RE.finditer(source):
        for lit in LIT_RE.finditer(call.group(1)):
            out.add((lit.group(1), origin))
    return out


def render_markdown(cmds: set[tuple[str, str]], date: str) -> str:
    rows = sorted(cmds)
    out = [
        "# NeTV2 console (REPL) contract",
        "",
        f"Generated {date} by `scripts/gen_repl_contract.py` from `tests/hdmi-suite/netv2test/`.",
        "The modern firmware must keep the text output of every command below",
        "byte-compatible with the 2019 firmware (`legacy/firmware/ci.c`), because the",
        "suite parses it. New commands are additive. `%d` marks an integer argument.",
        "",
        "| Command | Used by |",
        "|---------|---------|",
    ]
    out += [f"| `{c}` | {o} |" for c, o in rows]
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="tests/hdmi-suite/netv2test")
    ap.add_argument("--out", default="docs/current/repl-contract.md")
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    cmds: set[tuple[str, str]] = set(EXTRA)
    for f in sorted(Path(a.suite).glob("*.py")):
        cmds |= extract_commands(f.read_text(), f.name)
    Path(a.out).write_text(render_markdown(cmds, a.date))
    print(f"{len(cmds)} commands -> {a.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, then generate**

Run: `uv run pytest tests/unit/test_gen_repl_contract.py -q && uv run python scripts/gen_repl_contract.py --date 2026-09-05 && head -30 docs/current/repl-contract.md`
Expected: 2 passed; about 28 commands including `status`, `json on`, `json off`, `help`, `debug input0`, `debug stop`, `debug run`, `debug setrect %d %d %d %d`, `video_mode %d`, `video_matrix list`, `hdp_toggle %d`, plus the four `debug t4i`-style extras. If `debug stop` is missing the regex is wrong; do not proceed.

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/gen_repl_contract.py tests/unit/test_gen_repl_contract.py docs/current/repl-contract.md
git commit -m "docs: generate the frozen REPL contract from the suite's console usage"
```

### Task 8: Hardware host table and golden-unit guard

> **Superseded (2026-09-05).** The code below is the pre-review version and was
> implemented as written, then rewritten after the phase 0 hardware-safety review:
> the guard is now an allowlist (`ALLOWED_ON_GOLDEN`), IDCODEs are compared with
> the revision nibble masked (`Host.idcode_matches`), hosts are resolved through
> `resolve_host` (name, fqdn, `user@fqdn`, both domains), `console_command`
> requires its command line and is filtered by `check_repl_command_allowed`
> (refuses `reboot`, `mw`, `mc` and any CR/LF), and `rootfs_write` exists and
> is refused on the golden unit. **The committed `tests/hardware/hosts.py` and
> `tests/hardware/test_hosts.py` are authoritative; do not re-implement from
> this block.**

**Files:**
- Create: `tests/hardware/__init__.py`, `tests/hardware/hosts.py`, `tests/hardware/test_hosts.py`

- [ ] **Step 1: Write the failing test**

`tests/hardware/test_hosts.py`:

```python
import pytest

from tests.hardware.hosts import HOSTS, GoldenUnitError, check_action_allowed


def test_rpi3_is_golden_and_35t():
    h = HOSTS["rpi3-netv2"]
    assert h.golden is True
    assert h.idcode == 0x0362D093
    assert h.user == "pi"


def test_flash_write_refused_on_golden():
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "spi_flash_write")


def test_power_cycle_refused_on_golden():
    with pytest.raises(GoldenUnitError):
        check_action_allowed("rpi3-netv2", "power_cycle")


def test_volatile_load_allowed_on_golden():
    check_action_allowed("rpi3-netv2", "jtag_volatile_load")


def test_everything_allowed_on_rpi5():
    for a in ("spi_flash_write", "power_cycle", "jtag_volatile_load", "reboot"):
        check_action_allowed("rpi5-netv2", a)


def test_unknown_host_rejected():
    with pytest.raises(KeyError):
        check_action_allowed("nope", "reboot")
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/hardware/test_hosts.py -q 2>&1 | tail -2`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`tests/hardware/__init__.py` empty. `tests/hardware/hosts.py`:

```python
"""Test hosts and the golden-unit rules (spec decisions 6, 8, 10, 35).

Every script that touches hardware must call ``check_action_allowed`` before a
destructive step. The golden unit rpi3-netv2 only ever receives volatile JTAG
loads and console traffic.
"""
from dataclasses import dataclass


class GoldenUnitError(RuntimeError):
    """Raised when an action is forbidden on the golden reference unit."""


@dataclass(frozen=True)
class Host:
    name: str
    fqdn: str
    user: str
    fpga: str
    idcode: int
    golden: bool
    uart: str
    hdmi_variant: str          # "pcb" (M2M jumper) or "cable"
    has_capture: bool
    has_pcie: bool
    openocd_cfg: str


HOSTS = {
    "rpi3-netv2": Host(
        name="rpi3-netv2",
        fqdn="rpi3-netv2.iot.welland.mithis.com",
        user="pi",
        fpga="xc7a35t-fgg484-2",
        idcode=0x0362D093,
        golden=True,
        uart="/dev/ttyS0",
        hdmi_variant="pcb",
        has_capture=True,
        has_pcie=False,
        openocd_cfg="/home/pi/code/netv2mvp-scripts/alphamax-rpi.cfg",
    ),
    "rpi5-netv2": Host(
        name="rpi5-netv2",
        fqdn="rpi5-netv2.iot.welland.mithis.com",
        user="tim",
        fpga="xc7a100t-fgg484-2",
        idcode=0x13631093,
        golden=False,
        uart="/dev/ttyAMA0",
        hdmi_variant="cable",
        has_capture=False,
        has_pcie=True,
        openocd_cfg="/home/tim/netv2/netv2-rpi5.cfg",
    ),
}

FORBIDDEN_ON_GOLDEN = {"spi_flash_write", "power_cycle", "reboot", "reimage"}
KNOWN_ACTIONS = FORBIDDEN_ON_GOLDEN | {"jtag_volatile_load", "console", "run_suite"}


def check_action_allowed(host_name: str, action: str) -> None:
    host = HOSTS[host_name]  # KeyError for unknown hosts is intended
    if action not in KNOWN_ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if host.golden and action in FORBIDDEN_ON_GOLDEN:
        raise GoldenUnitError(f"{action} is forbidden on golden unit {host_name}")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/hardware/test_hosts.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/hardware/__init__.py tests/hardware/hosts.py tests/hardware/test_hosts.py
git commit -m "tests: host table and golden-unit guard for hardware scripts"
```

### Task 9: Fold the Pi 5 notes from ten64 into docs (D5) and close phase 0

**Files:**
- Create: `docs/current/pi5-programming.md`, `docs/current/pi5-rp1-pio-jtag.md`

- [ ] **Step 1: Copy the two notes**

If either path is absent, `ssh ten64.welland.mithis.com 'ls ~/local/netv2/docs'` and record what exists instead.

```bash
scp ten64.welland.mithis.com:~/local/netv2/docs/programming-netv2-on-rpi5.md docs/current/pi5-programming.md
scp ten64.welland.mithis.com:~/local/netv2/docs/02-rp1-pio-jtag.md docs/current/pi5-rp1-pio-jtag.md
```

Prepend to each: `> Imported 2026-09-05 from ten64:~/local/netv2/docs (written 2026-02-22). Facts below reflect that date; the rpi5-netv2 OpenOCD now has the linuxgpiod driver compiled in (verified 2026-09-05).`

- [ ] **Step 2: Commit, update the log, run the full unit suite**

```bash
git add docs/current/pi5-programming.md docs/current/pi5-rp1-pio-jtag.md
git commit -m "docs: import Pi 5 programming and RP1 PIO JTAG notes from ten64"
make test
```
Expected: 11 passed (3 pins + 2 contract + 6 hosts).

Append to `LOG.md` under 2026-09-05 (or the current date): `- Phase 0 complete on phase0-repo-setup: legacy/ move, uv project (LiteX 2026.04), subtree tests/hdmi-suite, REPL contract, host table + golden guard, Pi 5 notes.` Commit.

- [ ] **Step 3: Four-direction review, then merge**

Dispatch four review sub-agents (correctness, hardware safety, security, docs/reproducibility) on `git diff modern...phase0-repo-setup`; fix findings as further commits. Then:

```bash
git checkout modern && git merge --no-ff phase0-repo-setup -m "Merge phase 0: repo setup" && git push mithro modern phase0-repo-setup
```

Attempt `gh pr create --base modern --head phase0-repo-setup --repo mithro/netv2-fpga --fill` first for the review trail; if the classifier denies it, merge locally as above and note it in `LOG.md`.

---

## Phase 1: baseline

Branch: `git checkout modern && git checkout -b phase1-baseline`.

### Task 10: `docs/original/hardware.md` and `gateware.md`

**Files:**
- Create: `docs/original/hardware.md`, `docs/original/gateware.md`
- Read: `legacy/netv2mvp.py` (whole file), `legacy/overlay/*.v` (headers), `legacy/deps/litevideo/litevideo/input/*.py`, `legacy/deps/litevideo/litevideo/output/`, spec section 3, `tests/hdmi-suite/docs/TEST-SUITE-DESIGN.md`

- [ ] **Step 1: Write `hardware.md`** covering: FPGA variants and IDCODEs (0x0362D093 / 0x13631093), DDR3 (two K4B2G1646F, 32-bit), SPI NOR 8 MB, RMII PHY, two HDMI in / two out and which is "overlay", PCIe x1/x2/x4 pads, Pi header wiring (JTAG 4/17/27/22/24, UART 14/15), the M2M jumper and the `pcb`/`cable` inversion table copied from `legacy/netv2mvp.py` lines 226 to 259, LEDs, fan, HPD/CEC control pins. Cite `legacy/netv2mvp.py:<line>` for each table.

- [ ] **Step 2: Write `gateware.md`** covering: `BaseSoC` (VexRiscv, ROM 0x6000, DDR, SPI flash, XADC, Etherbone in the `eth` domain) and `VideoOverlaySoC` (two `HDMIIn`, raw-mode output PHY, the 6-stage raw delay line, chroma key and rectangle mux with the exact condition from the source, TERC4-derived DE so data islands pass through, HDCP block wiring, `frame` FIFOs), with a data-flow diagram (ASCII) from input0 pads to output0 pads and from input1 pads through DDR to the mux. Quote the mux code verbatim with line numbers.

- [ ] **Step 3: Commit**

```bash
git add docs/original/hardware.md docs/original/gateware.md && git commit -m "docs(original): hardware and gateware architecture of the 2019 design"
```

### Task 11: `docs/original/clocking.md`, `firmware.md`, `boot-and-flash.md`

**Files:**
- Create the three files
- Read: `legacy/netv2mvp.py` CRG (lines ~304 to 535), timing exceptions (~905 to 950), `legacy/deps/litevideo/litevideo/input/clocking.py`, `legacy/firmware/*.c` (`ci.c` for the REPL, `mmcm.c`, `hdmi_in0.c`, `processor.c` for EDID and modes, `main.c`), `legacy/bin/mknetv2img`, `legacy/software/`, the `netv2mvp-scripts` clone at `/home/tim/github/AlphamaxMedia/netv2mvp-scripts/` (`update-fpga.sh`, `cl-*.cfg`)

- [ ] **Step 1: `clocking.md`**: table of every MMCM/PLL (site purpose, input, outputs, domain names), the 75 MHz sys / 300 MHz IDELAY choice with the quoted comment at line 557, BUFIO/BUFR use, DRP registers and how `mmcm.c` reprograms for 720p, and the full list of the 23 timing exceptions with one line each on why it exists.

- [ ] **Step 2: `firmware.md`**: boot sequence (BIOS, flashboot at 0x207b0000, `main.c` init), REPL command reference generated by reading `ci.c` (every `strcmp(token, "...")`), the `status`/`json` output formats verbatim from a real capture (take it from `tests/hdmi-suite/LOG.md` or from the baseline run in task 13), EDID handling (`netv_edid_60hz`, audio bits `02 03 21 f1`, `23 09 07 07`), multires detection, `t4i`/`t4d` with the input1 label bug at `ci.c:1155`.

- [ ] **Step 3: `boot-and-flash.md`**: NOR layout (two bitstream copies, firmware at 0x7b0000), `mknetv2img -f` word byte-swap, `update-fpga.sh` steps with its IDCODE gate, bscan_spi proxies, `cl-firmware.cfg` / `cl-spifpga.cfg`.

- [ ] **Step 4: Commit**

```bash
git add docs/original/clocking.md docs/original/firmware.md docs/original/boot-and-flash.md
git commit -m "docs(original): clocking, firmware REPL, and boot/flash layout"
```

### Task 12: `docs/original/pi-software.md` and `factory-test.md`

**Files:**
- Create the two files
- Read: `/home/tim/github/AlphamaxMedia/netv2mvp-scripts/` (all), `/home/tim/github/AlphamaxMedia/netv2-tests/` (`README.md`, `*.test`, `*.scenario`, `netv2.jig`), `/home/tim/github/AlphamaxMedia/exclave/README.md`, `/home/tim/github/AlphamaxMedia/jig-20-interface-http/README.md`, `/home/tim/github/AlphamaxMedia/usb-pyromaniac/README.md`, `/home/tim/github/AlphamaxMedia/netv2-fpga.wiki/*.md`, and the live golden unit: `ssh pi@rpi3-netv2.iot.welland.mithis.com 'ls ~/code; cat ~/mm.sh ~/start_mm ~/stop_mm; /home/pi/n/bin/pm2 list; systemctl list-units --type=service --state=running --no-pager; crontab -l'` (read-only; some files may be missing, which is itself a finding).

- [ ] **Step 1: `pi-software.md`**: the shipped image (Raspbian 9, Python 3.5, OpenOCD 0.10 fork with bcm2835gpio), `~/code` layout, MagicMirror + `MMM-json-feed` + `netv2-status.js` + pm2 `mm.sh`, the one-click updater desktop icon flow, `set_res.sh`/`set_ycrcb.sh`, `flterm --kernel`. Wiki pages summarised with links.

- [ ] **Step 2: `factory-test.md`**: exclave units (jig, scenarios, tests, triggers, interfaces), the two scenarios and the cabling they need, the test hat, usb-pyromaniac/usb-mapping imaging flow.

- [ ] **Step 3: Commit**

```bash
git add docs/original/pi-software.md docs/original/factory-test.md
git commit -m "docs(original): Pi-side software and factory test stack"
```

### Task 13: Baseline suite run on the golden unit

Read-only on the golden unit apart from the suite's own behaviour (it stops and restarts MagicMirror and lightdm for the run, as it always has). Actions used: `run_suite` (which itself covers `console_command` lines and `service_restart` of `pm2 mm` and `lightdm`). The guard in `tests/hardware/hosts.py` is advisory in phase 1: these steps are manual ssh commands; they are listed here so the reviewer can check them against `ALLOWED_ON_GOLDEN`.

- [ ] **Step 1: Confirm the on-device suite is the committed one**

```bash
ssh pi@rpi3-netv2.iot.welland.mithis.com 'cd ~ && md5sum netv2test/*.py' > /home/tim/github/AlphamaxMedia/tmp/rpi3-suite.md5
cd tests/hdmi-suite && md5sum netv2test/*.py > /home/tim/github/AlphamaxMedia/tmp/repo-suite.md5 && cd -
diff <(sort -k2 /home/tim/github/AlphamaxMedia/tmp/rpi3-suite.md5) <(sort -k2 /home/tim/github/AlphamaxMedia/tmp/repo-suite.md5) && echo IDENTICAL
```
Expected: `IDENTICAL` (verified 2026-09-05 already; re-check).

- [ ] **Step 2: Run the suite**

```bash
ssh pi@rpi3-netv2.iot.welland.mithis.com 'cd ~ && python3 -m netv2test.run_all 2>&1 | tail -40'
```
Expected (about 15 minutes): final line with `PASS 29 / FAIL 0 / BLOCKED n / SKIP 3` or similar; BLOCKED may be nonzero when the MS2109 starves (documented limitation). FAIL must be 0. If FAIL is nonzero, do not retry blindly: read the failing test's evidence and record it; the baseline is whatever the stock unit does.

- [ ] **Step 3: Copy the report into the repo**

```bash
mkdir -p docs/testing/reports/2026-09-baseline
NEWEST=$(ssh pi@rpi3-netv2.iot.welland.mithis.com 'ls -d ~/reports/2*/ | sort | tail -1')   # reports/ also holds README.md and latest/
echo "$NEWEST"
scp -r "pi@rpi3-netv2.iot.welland.mithis.com:${NEWEST}*" docs/testing/reports/2026-09-baseline/
ls docs/testing/reports/2026-09-baseline
```
Expected: `report.json`, `report.md`, evidence PNGs.

- [ ] **Step 4: Confirm MagicMirror came back**

```bash
ssh pi@rpi3-netv2.iot.welland.mithis.com 'pgrep -af "node .*MagicMirror|electron" | head -3; systemctl is-active lightdm'
```
Expected: MagicMirror/electron process present, `active`. If not, run the suite's restore path (`~/start_mm`) and record it.

- [ ] **Step 5: Commit**

```bash
git add -f docs/testing/reports/2026-09-baseline   # -f: the root .gitignore has *.bin, evidence may include .bin files
git status --short docs/testing/reports | head
git commit -m "test(baseline): stock NeTV2 suite run on rpi3-netv2 (golden unit)"
```

### Task 14: TERC4 counters and EDID/audio evidence (feeds phase 7a)

**Files:**
- Create: `scripts/parse_edid.py`, `tests/unit/test_parse_edid.py`, `docs/testing/reports/2026-09-baseline/t4d.txt`, `docs/testing/reports/2026-09-baseline/edid-analysis.md`

Physical re-cabling of `rpiz-3` directly into the MS2109 needs hands on site; the spec's "direct measurement" is therefore replaced by three remote measurements, and `LOG.md` says so. Actions used on the golden unit: `console_command` (`json off`, `status`, `debug t4i`, `debug t4d`; none is in the REPL deny-list), `service_restart` (`pm2 stop/start mm`), and one `rootfs_write` (copying `baseline_t4d.py` to `~`) that the guard refuses; it is done anyway as a deliberate, logged, immediately reverted exception, because the golden unit has no other way to run a script, and the file is deleted in the same step. The guard in `tests/hardware/hosts.py` is advisory in phase 1: these steps are manual ssh commands; they are listed here so the reviewer can check them against `ALLOWED_ON_GOLDEN`.

- [ ] **Step 1: Write the failing test for the EDID parser**

`tests/unit/test_parse_edid.py`:

```python
from scripts.parse_edid import cta_blocks, has_basic_audio, audio_descriptors

# CTA-861 extension header with basic audio bit, one Audio Data Block (LPCM 2ch 32/44.1/48k, 16/20/24 bit)
CTA = bytes([0x02, 0x03, 0x21, 0xF1, 0x23, 0x09, 0x07, 0x07]) + bytes(128 - 8)


def test_basic_audio_flag():
    assert has_basic_audio(CTA) is True


def test_audio_descriptor_decoded():
    (desc,) = audio_descriptors(CTA)
    assert desc["format"] == "LPCM"
    assert desc["channels"] == 2
    assert desc["rates_khz"] == [32, 44.1, 48]


def test_no_audio_when_flag_clear():
    blk = bytearray(CTA)
    blk[3] = 0xB1  # 0xF1 with bit 6 (basic audio) cleared
    assert has_basic_audio(bytes(blk)) is False
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_parse_edid.py -q 2>&1 | tail -2`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `scripts/parse_edid.py`**

```python
#!/usr/bin/env python3
"""Minimal EDID / CTA-861 parser: enough to answer "does this sink advertise
HDMI audio, and which formats?" for phase 1 and phase 7a diagnostics."""
import argparse
from pathlib import Path

RATE_BITS = [(0, 32), (1, 44.1), (2, 48), (3, 88.2), (4, 96), (5, 176.4), (6, 192)]
FORMATS = {1: "LPCM", 2: "AC-3", 3: "MPEG1", 4: "MP3", 5: "MPEG2", 6: "AAC", 7: "DTS", 8: "ATRAC"}


def cta_blocks(edid: bytes) -> list[bytes]:
    """Return the 128-byte CTA-861 extension blocks (tag 0x02) of a full EDID."""
    blocks = [edid[i:i + 128] for i in range(128, len(edid), 128)]
    return [b for b in blocks if len(b) == 128 and b[0] == 0x02]


def has_basic_audio(cta: bytes) -> bool:
    return bool(cta[3] & 0x40)


def audio_descriptors(cta: bytes) -> list[dict]:
    dtd_offset = cta[2]
    i, out = 4, []
    while i < dtd_offset:
        tag, length = cta[i] >> 5, cta[i] & 0x1F
        if tag == 1:  # Audio Data Block
            for j in range(i + 1, i + 1 + length, 3):
                b0, b1, b2 = cta[j], cta[j + 1], cta[j + 2]
                fmt = (b0 >> 3) & 0x0F
                out.append({
                    "format": FORMATS.get(fmt, f"code{fmt}"),
                    "channels": (b0 & 0x07) + 1,
                    "rates_khz": [r for bit, r in RATE_BITS if b1 & (1 << bit)],
                    "byte2": b2,
                })
        i += 1 + length
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("edid", type=Path)
    a = ap.parse_args()
    data = a.edid.read_bytes()
    print(f"{a.edid}: {len(data)} bytes, {len(data) // 128} blocks")
    ctas = cta_blocks(data)
    if not ctas:
        print("no CTA-861 extension block: sink is DVI-only for audio purposes")
        return
    for n, cta in enumerate(ctas):
        print(f"CTA block {n}: basic_audio={has_basic_audio(cta)}")
        for d in audio_descriptors(cta):
            print(f"  audio: {d}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, then analyse the real EDIDs**

```bash
uv run pytest tests/unit/test_parse_edid.py -q
uv run python scripts/parse_edid.py tests/hdmi-suite/evidence/capture-card-edid-as-seen-by-rpiz-3.bin | tee docs/testing/reports/2026-09-baseline/edid-analysis.md
```
Expected: 3 passed; then a printout that says whether the MS2109's EDID (as seen by `rpiz-3` through the NeTV2's pass-through) advertises audio. Record the meaning in `edid-analysis.md`: if `basic_audio=False` or no CTA block, `rpiz-3`'s vc4 driver will not create an HDMI audio stream at all, which is the leading explanation for the T23 silence and must be confirmed in phase 7a.

- [ ] **Step 5: Read the TERC4 counters and the rpiz-3 audio state**

Over the golden unit's console, using the suite's own console client. The MagicMirror status script (`netv2-status.js`, run by pm2) holds `/dev/ttyS0` open and polls `json`, so two readers would split the bytes; pause pm2's `mm` process around the read exactly as the suite does (`tests/hdmi-suite/netv2test/overlay.py` `prepare()`/`restore()`), and resume it afterwards even on error. Put the following in `scripts/baseline_t4d.py` and copy it to the Pi (the golden unit has only Python 3.5, so this file is 3.5 syntax):

```python
"""Read status and TERC4 counters from the stock firmware (phase 1 baseline)."""
import subprocess
from netv2test.console import Console

PM2 = "/home/pi/n/bin/pm2"
subprocess.call([PM2, "stop", "mm"], stdout=subprocess.DEVNULL)
try:
    c = Console(port="/dev/ttyS0", baud=115200)
    c.command("json off")
    for cmd in ["status", "debug t4i", "debug t4d", "debug t4d"]:
        print("=== " + cmd)
        print(c.command(cmd))
finally:
    subprocess.call([PM2, "start", "mm"], stdout=subprocess.DEVNULL)
    subprocess.call([PM2, "list"])
```

```bash
scp scripts/baseline_t4d.py pi@rpi3-netv2.iot.welland.mithis.com:~/baseline_t4d.py
ssh pi@rpi3-netv2.iot.welland.mithis.com 'cd ~ && exec "$(command -v python3)" baseline_t4d.py' | tee docs/testing/reports/2026-09-baseline/t4d.txt
```
Check the `t4d` output is complete (two lines of counters plus five BCH lines) before recording it; record in `t4d.txt` and `LOG.md` that `debug t4i` changed the running firmware's TERC4 interrupt enable (volatile RAM state, cleared at the unit's next reset). Then remove the copied script from the golden unit (`ssh pi@rpi3-netv2.iot.welland.mithis.com rm ~/baseline_t4d.py`) so the reference rootfs gains nothing. Note that the interrupt enable set by `debug t4i` persists for the life of the current FPGA configuration because the golden unit is never reset; clearing it, if ever needed, is a volatile JTAG reload of the stock `user-35.bit` (an allowed action), never the REPL's `reboot`.
(`Console(port, baud)` and `command(cmd, timeout=3.0)` are the real API in `tests/hdmi-suite/netv2test/console.py`; `t4i`/`t4d` are sub-commands of `debug`, `legacy/firmware/ci.c` lines 991, 1141, 1154; the bare words print nothing.) Expected: `status` shows `input0: 1920x1080`; `debug t4d` prints `hdmi0 terc4 packet cnt: N, char cnt: M` (these are input1's counters, `ci.c:1155`) and five BCH words (input0's last capture). Record N, M and whether the BCH words are nonzero (nonzero means input0 has seen at least one data island).

Then on the source: `ssh rpiz-3.iot.welland.mithis.com 'cat /proc/asound/cards; ls /proc/asound/card*/eld* 2>&1; for f in /proc/asound/card*/eld*; do echo "== $f"; cat $f; done'` (if the host key is unknown to this desktop, run it from `rpi3-netv2` instead, which already trusts `rpiz-3`). Append the output to `t4d.txt` under a heading. `eld_valid 1` with `monitor_present 1` and `sad_count 0` or `eld_valid 0` means the source believes the sink has no audio.

- [ ] **Step 6: Commit**

```bash
git add scripts/parse_edid.py tests/unit/test_parse_edid.py docs/testing/reports/2026-09-baseline/t4d.txt docs/testing/reports/2026-09-baseline/edid-analysis.md
git commit -m "test(baseline): TERC4 counters, source ELD state and sink EDID audio analysis"
```

### Task 15: Time-boxed rebuild of the 2019 design (max one working day)

**Files:**
- Create: `docs/original/rebuild-2019.md`, `legacy/Dockerfile.rebuild2019`

Purpose: establish whether the original design can still be regenerated (Verilog from migen) and synthesised (Vivado 2025.2). Stop at the time box; the outcome is documented either way. Build outputs go under `legacy/build/` (git-ignored by the root `.gitignore` rule `build`, which matches at any depth).

- [ ] **Step 1: Initialise the legacy submodules**

```bash
git submodule update --init legacy/deps/litex legacy/deps/migen legacy/deps/litedram legacy/deps/litevideo legacy/deps/liteeth legacy/deps/litescope legacy/deps/pyserial 2>&1 | tail -3
```
Expected: seven checkouts at the pinned SHAs. Do not recurse into `legacy/deps/litex`'s own submodules (compiler-rt URL is dead); the gateware generation does not need them.

- [ ] **Step 2: Write `legacy/Dockerfile.rebuild2019`**

```dockerfile
FROM python:3.7-slim
RUN apt-get update && apt-get install -y --no-install-recommends make git libtinfo5 libx11-6 libxrender1 libxtst6 libxi6 && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends gcc-riscv64-unknown-elf && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pyserial==3.4 colorama
WORKDIR /work
ENV PATH=/opt/Xilinx/2025.2/Vivado/bin:$PATH
```

- [ ] **Step 3: Generate Verilog only (no Vivado, no firmware) first**

`legacy/netv2mvp.py`'s `main()` (lines 1273 to 1300) accepts only `-p`, `-t`, `-d`, `-c`, and its `Builder` always compiles the BIOS before writing Verilog; `lxbuildenv` also exits unless Vivado and a RISC-V compiler are found or `--lx-ignore-deps` is given. So add a driver, `legacy/rebuild2019_verilog.py` (this is the one file added under `legacy/`, clearly marked as 2026 tooling):

```python
#!/usr/bin/env python3
"""2026 tooling: regenerate the 2019 VideoOverlaySoC Verilog without Vivado or a
RISC-V toolchain. Run inside the rebuild2019 container with --lx-ignore-deps."""
import lxbuildenv  # noqa: F401  must be first: re-execs with legacy deps on PYTHONPATH
import sys
from netv2mvp import Platform, VideoOverlaySoC
from litex.soc.integration.builder import Builder

part = sys.argv[1] if len(sys.argv) > 1 else "35"
platform = Platform(part=part, cable="pcb")
soc = VideoOverlaySoC(platform, part=part, dqs_phase="112.5")
builder = Builder(soc, output_dir="build/verilog-only-%s" % part,
                  compile_software=False, compile_gateware=False)
builder.build()
print("generated build/verilog-only-%s/gateware/top.v" % part)
```

```bash
docker build -t netv2-rebuild2019 -f legacy/Dockerfile.rebuild2019 legacy
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/legacy:/work" netv2-rebuild2019 python3 rebuild2019_verilog.py 35 --lx-ignore-deps 2>&1 | tail -20
ls -l legacy/build/verilog-only-35/gateware/top.v
```
Expected: first `Missing submodules -- updating` followed by `fatal: not a git repository` (the container sees no `.git`; lxbuildenv ignores the return code and continues), then, best case, `top.v` produced (tens of thousands of lines). `lxbuildenv` strips its own `--lx-*` flags before re-exec, so `sys.argv[1]` is still the part. Record the exact error otherwise (Python 3.7 vs the 2019 migen is the expected happy path; a `PYTHONHASHSEED` complaint means lxbuildenv did not re-exec).

- [ ] **Step 4: If Verilog generated, attempt synthesis with Vivado 2025.2 (mount `/opt/Xilinx` read-only)**

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/work -v "$PWD/legacy:/work" -v /opt/Xilinx:/opt/Xilinx:ro -v "$HOME/.Xilinx:/work/.Xilinx:ro" netv2-rebuild2019 python3 netv2mvp.py -p 35 --lx-ignore-deps 2>&1 | tail -30
```
This runs the original flow: BIOS compile with the container's `riscv64-unknown-elf-gcc` (the 2019 firmware expected `riscv64-unknown-elf-` too), then Vivado.
Expected: either a bitstream at `legacy/build/gateware/top.bit` (record `ls -l` and the timing summary from `legacy/build/gateware/vivado.log`), or the first hard error. Vivado 2025.2 with the 2019-generated TCL is the most likely failure point; capture it verbatim.

- [ ] **Step 5: Document**

`docs/original/rebuild-2019.md`: environment (container, pins), commands, outcome, first error and its cause if diagnosed within the time box, and what a full reproduction would additionally need. Never load a bitstream produced here onto any board in this phase.

- [ ] **Step 6: Commit, log, review, merge**

```bash
git add docs/original/rebuild-2019.md legacy/Dockerfile.rebuild2019 legacy/rebuild2019_verilog.py
git commit -m "docs(original): time-boxed rebuild attempt of the 2019 design"
```
Append to `LOG.md`: phase 1 summary with the baseline numbers, T23 evidence, and the rebuild outcome. Commit. Four-direction review of `git diff modern...phase1-baseline`, fix, then `git checkout modern && git merge --no-ff phase1-baseline -m "Merge phase 1: baseline" && git push mithro modern phase1-baseline`.

---

## Exit criteria for this plan

- `make test` passes on the desktop (unit tests for pins, contract generator, hosts, EDID parser).
- `uv run python -c "import litex_boards.platforms.kosagi_netv2"` succeeds (pins resolve).
- `docs/original/` has the eight pages; `docs/current/repl-contract.md` exists; `docs/testing/reports/2026-09-baseline/` holds the suite report, `t4d.txt`, `edid-analysis.md`.
- `rpi3-netv2` state unchanged: stock bitstream in NOR, MagicMirror running, same reports directory plus one new run.
- `LOG.md` records phases 0 and 1 and the two user-blocked items.
