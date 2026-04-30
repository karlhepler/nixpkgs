"""
Tests for modules/claude/kanban-mov-lint-hook.py (thin pass-through).

ARCHITECTURE NOTE: All banned-pattern validation has been moved into the kanban
CLI itself (kanban.py — see validate_mov_commands_content). This hook is now a
no-op that always allows. Tests verify that the hook:

  1. Imports and runs without error.
  2. Always exits 0 (allow) — never emits a block decision.
  3. Reads and discards stdin correctly.

The substantive validation tests live in:
  modules/kanban/tests/test_kanban_mov_validation.py
"""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "kanban-mov-lint-hook.py"


def load_hook():
    """Import kanban-mov-lint-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_mov_lint_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a given stdin string
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, stdin_content: str = "") -> "dict | None":
    """
    Call hook_mod.main() with stdin_content.
    Returns any JSON printed to stdout, or None if nothing was printed (allow).
    """
    captured_output: list[str] = []

    def fake_print(val, **kwargs):
        captured_output.append(val)

    with patch.object(sys, "stdin", io.StringIO(stdin_content)):
        with patch("builtins.print", side_effect=fake_print):
            try:
                hook_mod.main()
            except SystemExit:
                pass

    if not captured_output:
        return None
    try:
        return json.loads(captured_output[-1])
    except (json.JSONDecodeError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHookIsPassThrough:
    """The hook always allows — all validation is now in the kanban CLI."""

    def test_empty_stdin_allows(self, hook):
        """Empty stdin → hook exits 0 with no output (allow)."""
        result = run_hook_main(hook, "")
        assert result is None, f"Expected allow (None), got: {result}"

    def test_kanban_do_file_with_banned_pattern_allows(self, hook):
        """kanban do --file with backslash-pipe cmd → hook allows (CLI validates instead)."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "kanban do --file /tmp/card.json"},
        })
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"

    def test_kanban_todo_file_allows(self, hook):
        """kanban todo --file invocation → hook always allows."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "kanban todo --file /tmp/card.json"},
        })
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"

    def test_non_kanban_command_allows(self, hook):
        """Non-kanban command → hook allows."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "rg -q pattern file"},
        })
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"

    def test_malformed_json_stdin_allows(self, hook):
        """Malformed JSON stdin → hook allows (no crash)."""
        result = run_hook_main(hook, "{invalid json}")
        assert result is None, f"Expected allow (None), got: {result}"

    def test_non_bash_tool_call_allows(self, hook):
        """Non-Bash tool call → hook allows."""
        payload = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/test.py"},
        })
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"
