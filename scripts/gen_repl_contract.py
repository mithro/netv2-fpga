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
    """Extract ``(command, origin)`` pairs from one suite source file.

    CALL_RE only sees a ``.command(...)`` call that closes on its own line, so a
    call reformatted across two lines would silently drop out of the contract.
    Compare the number of matches with the raw number of ``.command(`` calls and
    fail loudly instead: a contract that quietly shrinks is worse than no
    contract at all.
    """
    calls = list(CALL_RE.finditer(source))
    written = source.count(".command(")
    if written != len(calls):
        raise SystemExit(
            f"{origin}: found {written} '.command(' calls but matched {len(calls)}; "
            "a call is probably split across lines. Fix the source or CALL_RE -- "
            "the REPL contract must not shrink silently."
        )
    out: set[tuple[str, str]] = set()
    for call in calls:
        for lit in LIT_RE.finditer(call.group(1)):
            out.add((lit.group(1), origin))
    return out


def render_markdown(cmds: set[tuple[str, str]], date: str) -> str:
    rows = sorted(cmds)
    manual = ", ".join(f"`{c}`" for c, _ in sorted(EXTRA))
    out = [
        "# NeTV2 console (REPL) contract",
        "",
        "<!-- Generated file. Do not edit by hand. -->",
        "",
        f"Generated {date} by `scripts/gen_repl_contract.py` from `tests/hdmi-suite/netv2test/`.",
        "The modern firmware must keep the text output of every command below",
        "byte-compatible with the 2019 firmware (`legacy/firmware/ci.c`), because the",
        "suite parses it. New commands are additive. `%d` marks an integer argument.",
        "",
        "## How to regenerate",
        "",
        "```bash",
        "uv run python scripts/gen_repl_contract.py --date <YYYY-MM-DD>",
        "```",
        "",
        "The generator scans every `.command(\"...\")` call in the suite's Python and",
        "fails if a call is split across lines, so the table cannot silently shrink.",
        "",
        "## Reading the table",
        "",
        "The **Used by** column names the suite source file under",
        "`tests/hdmi-suite/netv2test/` that issues the command. Rows marked `manual` are",
        "not issued by the suite: they are commands typed interactively during phase 1",
        f"diagnostics ({manual}), all of them",
        "sub-commands of the firmware's `debug` parser in `legacy/firmware/ci.c`.",
        "",
        "## Commands",
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
