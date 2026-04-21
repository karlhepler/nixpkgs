"""
Tests for modules/claude/kanban-done-reminder-hook.py.

Covered paths:
- 'kanban done <N>' → emits additionalContext reminder
- 'kanban done <N>' with leading whitespace → emits reminder
- 'kanban done-something' → silent (regex boundary check)
- 'kanban show <N>' → silent (unrelated kanban command)
- 'kanban redo <N>' → silent
- 'npm test' → silent
- Empty stdin → silent (fail open)
- Malformed JSON → silent (fail open)
- Response structure: hookEventName, additionalContext fields present and correct
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

_HOOK_PATH = Path(__file__).parent.parent / "kanban-done-reminder-hook.py"


def load_hook():
    """Import kanban-done-reminder-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_done_reminder_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the done-reminder hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a JSON payload via monkeypatched stdin / stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, payload: dict | None) -> dict | None:
    """
    Call hook_mod.main() with the given payload dict as stdin JSON.
    Returns the parsed JSON written to stdout, or None if nothing was printed.
    """
    captured_output: list[str] = []

    def fake_print(val, **kwargs):
        captured_output.append(val)

    raw = json.dumps(payload) if payload is not None else ""

    with patch.object(sys, "stdin", io.StringIO(raw)):
        with patch("builtins.print", side_effect=fake_print):
            try:
                hook_mod.main()
            except SystemExit:
                pass

    if not captured_output:
        return None
    return json.loads(captured_output[-1])


def make_bash_posttool_payload(command: str) -> dict:
    """Build a minimal PostToolUse(Bash) hook payload."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"output": ""},
    }


# ---------------------------------------------------------------------------
# Fires: kanban done <N> emits reminder
# ---------------------------------------------------------------------------

class TestKanbanDoneFiresReminder:
    """'kanban done <N>' commands trigger the mandatory review reminder."""

    def test_kanban_done_with_number_emits_reminder(self, hook):
        payload = make_bash_posttool_payload("kanban done 42 --session test-session")
        result = run_hook_main(hook, payload)
        assert result is not None, "Expected reminder output for 'kanban done 42'"

    def test_kanban_done_with_session_flag_emits_reminder(self, hook):
        payload = make_bash_posttool_payload("kanban done 100 --session firm-frost")
        result = run_hook_main(hook, payload)
        assert result is not None, "Expected reminder output for 'kanban done 100'"

    def test_reminder_contains_mandatory_review_language(self, hook):
        payload = make_bash_posttool_payload("kanban done 42")
        result = run_hook_main(hook, payload)
        assert result is not None
        additional_context = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "mandatory review" in additional_context.lower() or "review" in additional_context.lower()

    def test_leading_whitespace_command_emits_reminder(self, hook):
        """'kanban done' after leading whitespace (e.g. in a compound command) fires reminder."""
        payload = make_bash_posttool_payload("  kanban done 42")
        result = run_hook_main(hook, payload)
        assert result is not None, "Expected reminder for '  kanban done 42' (leading spaces)"


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------

class TestReminderResponseStructure:
    """Verify the reminder response has the correct structure."""

    def test_response_has_hook_specific_output(self, hook):
        payload = make_bash_posttool_payload("kanban done 1 --session s")
        result = run_hook_main(hook, payload)
        assert result is not None
        assert "hookSpecificOutput" in result

    def test_response_hook_event_name_is_post_tool_use(self, hook):
        payload = make_bash_posttool_payload("kanban done 1 --session s")
        result = run_hook_main(hook, payload)
        assert result is not None
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("hookEventName") == "PostToolUse"

    def test_response_has_additional_context(self, hook):
        payload = make_bash_posttool_payload("kanban done 1 --session s")
        result = run_hook_main(hook, payload)
        assert result is not None
        hook_output = result.get("hookSpecificOutput", {})
        assert "additionalContext" in hook_output
        assert len(hook_output["additionalContext"]) > 0


# ---------------------------------------------------------------------------
# Silent: non-matching kanban commands
# ---------------------------------------------------------------------------

class TestNonMatchingCommandsSilent:
    """Commands that should NOT trigger the reminder."""

    def test_kanban_show_silent(self, hook):
        payload = make_bash_posttool_payload("kanban show 42 --session test")
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected silent for 'kanban show', got: {result}"

    def test_kanban_redo_silent(self, hook):
        payload = make_bash_posttool_payload("kanban redo 42 --session test")
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected silent for 'kanban redo', got: {result}"

    def test_kanban_criteria_check_silent(self, hook):
        payload = make_bash_posttool_payload("kanban criteria check 42 1 --session test")
        result = run_hook_main(hook, payload)
        assert result is None

    def test_kanban_status_silent(self, hook):
        payload = make_bash_posttool_payload("kanban status --session test")
        result = run_hook_main(hook, payload)
        assert result is None

    def test_npm_test_silent(self, hook):
        payload = make_bash_posttool_payload("npm test")
        result = run_hook_main(hook, payload)
        assert result is None

    def test_git_push_silent(self, hook):
        payload = make_bash_posttool_payload("git push origin main")
        result = run_hook_main(hook, payload)
        assert result is None


# ---------------------------------------------------------------------------
# Regex boundary: subcommands that contain "done" should NOT match
# ---------------------------------------------------------------------------

class TestRegexBoundary:
    """Regex must not fire on 'kanban done-something' or similar."""

    def test_kanban_done_subcommand_variant_silent(self, hook):
        """'kanban done-something' must NOT match (boundary check)."""
        payload = make_bash_posttool_payload("kanban done-something 42")
        result = run_hook_main(hook, payload)
        assert result is None, (
            f"Expected silent for 'kanban done-something' (regex boundary), got: {result}"
        )

    def test_kanban_done_without_argument_silent(self, hook):
        """'kanban done' with no argument after it should NOT match (requires \\S after 'done ')."""
        payload = make_bash_posttool_payload("kanban done")
        result = run_hook_main(hook, payload)
        assert result is None, (
            f"Expected silent for 'kanban done' (no argument), got: {result}"
        )

    def test_done_without_kanban_prefix_silent(self, hook):
        """Plain 'done' without kanban prefix → silent."""
        payload = make_bash_posttool_payload("done 42")
        result = run_hook_main(hook, payload)
        assert result is None


# ---------------------------------------------------------------------------
# Fail-open: error conditions → silent exit
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Error conditions result in silent exit."""

    def test_empty_stdin_silent(self, hook):
        captured = []

        def fake_print(val, **kwargs):
            captured.append(val)

        with patch.object(sys, "stdin", io.StringIO("")):
            with patch("builtins.print", side_effect=fake_print):
                try:
                    hook.main()
                except SystemExit:
                    pass

        assert not captured, f"Expected no output for empty stdin, got: {captured}"

    def test_malformed_json_silent(self, hook):
        captured = []

        def fake_print(val, **kwargs):
            captured.append(val)

        with patch.object(sys, "stdin", io.StringIO("{bad json }")):
            with patch("builtins.print", side_effect=fake_print):
                try:
                    hook.main()
                except SystemExit:
                    pass

        assert not captured, f"Expected no output for malformed JSON, got: {captured}"

    def test_missing_command_field_silent(self, hook):
        """Payload without command → treated as empty string → silent."""
        payload = {"tool_name": "Bash", "tool_input": {}}
        result = run_hook_main(hook, payload)
        assert result is None
