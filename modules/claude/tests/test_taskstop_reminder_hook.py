"""
Tests for modules/claude/taskstop-reminder-hook.py.

Covered paths:
- Normal TaskStop payload → always emits orphan-cleanup reminder
- Empty stdin → still emits reminder (fail open = always remind)
- Malformed JSON → still emits reminder (fail open = always remind)
- Whitespace-only stdin → still emits reminder
- Response structure: hookEventName=PostToolUse, additionalContext present
- Reminder content includes orphan-cleanup language
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

_HOOK_PATH = Path(__file__).parent.parent / "taskstop-reminder-hook.py"


def load_hook():
    """Import taskstop-reminder-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("taskstop_reminder_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the taskstop-reminder hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with raw stdin content
# ---------------------------------------------------------------------------

def run_hook_with_stdin(hook_mod, stdin_content: str) -> dict | None:
    """
    Call hook_mod.main() with the given stdin content.
    Returns the parsed JSON written to stdout, or None if nothing was printed.
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
    return json.loads(captured_output[-1])


def run_hook_with_payload(hook_mod, payload: dict) -> dict | None:
    """Helper for dict payloads."""
    return run_hook_with_stdin(hook_mod, json.dumps(payload))


# ---------------------------------------------------------------------------
# Always fires: reminder is always emitted
# ---------------------------------------------------------------------------

class TestTaskStopAlwaysFiresReminder:
    """taskstop-reminder-hook always emits the orphan-cleanup reminder."""

    def test_normal_taskstop_payload_emits_reminder(self, hook):
        payload = {
            "tool_name": "TaskStop",
            "tool_input": {"reason": "Task completed"},
            "session_id": "test-session",
        }
        result = run_hook_with_payload(hook, payload)
        assert result is not None, "Expected reminder output for TaskStop"

    def test_minimal_taskstop_payload_emits_reminder(self, hook):
        payload = {"tool_name": "TaskStop"}
        result = run_hook_with_payload(hook, payload)
        assert result is not None

    def test_empty_stdin_still_emits_reminder(self, hook):
        """Empty stdin → hook still emits the reminder (fail open behavior)."""
        result = run_hook_with_stdin(hook, "")
        assert result is not None, "Expected reminder even with empty stdin"

    def test_malformed_json_still_emits_reminder(self, hook):
        """Malformed JSON → hook still emits the reminder (fail open)."""
        result = run_hook_with_stdin(hook, "{bad json}")
        assert result is not None, "Expected reminder even with malformed JSON"

    def test_whitespace_only_stdin_still_emits_reminder(self, hook):
        """Whitespace-only stdin → hook still emits the reminder."""
        result = run_hook_with_stdin(hook, "   \n   ")
        assert result is not None, "Expected reminder for whitespace-only stdin"


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------

class TestReminderResponseStructure:
    """Verify the reminder response has the correct structure."""

    def test_response_has_hook_specific_output(self, hook):
        payload = {"tool_name": "TaskStop"}
        result = run_hook_with_payload(hook, payload)
        assert result is not None
        assert "hookSpecificOutput" in result

    def test_response_hook_event_name_is_post_tool_use(self, hook):
        payload = {"tool_name": "TaskStop"}
        result = run_hook_with_payload(hook, payload)
        assert result is not None
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("hookEventName") == "PostToolUse"

    def test_response_has_additional_context(self, hook):
        payload = {"tool_name": "TaskStop"}
        result = run_hook_with_payload(hook, payload)
        assert result is not None
        hook_output = result.get("hookSpecificOutput", {})
        assert "additionalContext" in hook_output

    def test_additional_context_is_non_empty(self, hook):
        payload = {"tool_name": "TaskStop"}
        result = run_hook_with_payload(hook, payload)
        assert result is not None
        additional_context = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert len(additional_context) > 0


# ---------------------------------------------------------------------------
# Reminder content: orphan-cleanup language
# ---------------------------------------------------------------------------

class TestReminderContent:
    """Verify the reminder contains orphan-cleanup guidance."""

    def test_reminder_mentions_orphan_cleanup(self, hook):
        payload = {"tool_name": "TaskStop"}
        result = run_hook_with_payload(hook, payload)
        assert result is not None
        context = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        # Should mention orphan cleanup or child processes
        assert "orphan" in context.lower() or "child process" in context.lower()

    def test_reminder_mentions_taskstop(self, hook):
        payload = {"tool_name": "TaskStop"}
        result = run_hook_with_payload(hook, payload)
        assert result is not None
        context = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "taskstop" in context.lower() or "task" in context.lower()

    def test_reminder_mentions_pkill_or_kill(self, hook):
        payload = {"tool_name": "TaskStop"}
        result = run_hook_with_payload(hook, payload)
        assert result is not None
        context = result.get("hookSpecificOutput", {}).get("additionalContext", "")
        # Should mention how to kill processes
        assert "pkill" in context.lower() or "kill" in context.lower()

    def test_reminder_consistent_across_calls(self, hook):
        """Two consecutive calls return the same reminder content."""
        payload = {"tool_name": "TaskStop"}
        result1 = run_hook_with_payload(hook, payload)
        result2 = run_hook_with_payload(hook, payload)
        assert result1 is not None
        assert result2 is not None
        ctx1 = result1.get("hookSpecificOutput", {}).get("additionalContext", "")
        ctx2 = result2.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert ctx1 == ctx2, "Reminder content should be deterministic"
