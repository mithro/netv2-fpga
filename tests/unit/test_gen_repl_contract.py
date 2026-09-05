import pytest

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


MULTILINE_SNIPPET = '''
class Console:
    def status(self):
        return self.command(
            "x")
'''


def test_multiline_call_is_a_hard_error():
    """A call split across lines must fail the run, not shrink the contract."""
    with pytest.raises(SystemExit) as exc:
        extract_commands(MULTILINE_SNIPPET, "console.py")
    assert "console.py" in str(exc.value)


def test_render_markdown_has_table_rows_sorted():
    md = render_markdown({("status", "console.py"), ("help", "tests.py")}, "2026-09-05")
    assert "| `help` | tests.py |" in md
    assert md.index("| `help` |") < md.index("| `status` |")


def test_render_markdown_explains_itself():
    md = render_markdown({("status", "console.py")}, "2026-09-05")
    assert "uv run python scripts/gen_repl_contract.py --date <YYYY-MM-DD>" in md
    assert "Used by" in md
    assert "`debug t4i`" in md
    assert "legacy/firmware/ci.c" in md
