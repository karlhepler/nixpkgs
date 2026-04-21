"""
Tests for modules/claude/kanban-permission-hook.py.

Covered paths:
- Bash tool with kanban command → decision allow emitted
- Bash tool with non-kanban command → silent exit (no output)
- Non-Bash tool with kanban-containing input → silent exit (no output)
- Empty stdin → silent exit (fail open)
- Malformed JSON → silent exit (fail open)
- Session propagation: decision contains the correct hookEventName

The hook auto-approves any Bash tool call whose command starts with "kanban",
and is silent for everything else.
"""

import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "kanban-permission-hook.py"


def load_hook():
    """Import kanban-permission-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_permission_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the kanban permission hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a JSON payload via monkeypatched stdin / stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, payload: dict | None) -> dict | None:
    """
    Call hook_mod.main() with the given payload dict as stdin JSON.
    Returns the parsed JSON written to stdout, or None if nothing was printed
    (silent exit = no auto-approve action taken).
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


def make_bash_payload(command: str) -> dict:
    """Build a minimal Bash PermissionRequest payload."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "test-session",
    }


# ---------------------------------------------------------------------------
# Allowed: kanban commands get auto-approved
# ---------------------------------------------------------------------------

class TestKanbanCommandsAutoApproved:
    """Bash tool calls with kanban commands → decision allow emitted."""

    def test_kanban_show_emits_allow(self, hook):
        payload = make_bash_payload("kanban show 42 --session test-session")
        result = run_hook_main(hook, payload)
        assert result is not None, "Expected allow output for kanban show"
        hook_output = result.get("hookSpecificOutput", {})
        decision = hook_output.get("decision", {})
        assert decision.get("behavior") == "allow"

    def test_kanban_criteria_check_emits_allow(self, hook):
        payload = make_bash_payload("kanban criteria check 42 1 --session test-session")
        result = run_hook_main(hook, payload)
        assert result is not None
        decision = result.get("hookSpecificOutput", {}).get("decision", {})
        assert decision.get("behavior") == "allow"

    def test_kanban_done_emits_allow(self, hook):
        payload = make_bash_payload("kanban done 42 --session test-session")
        result = run_hook_main(hook, payload)
        assert result is not None
        decision = result.get("hookSpecificOutput", {}).get("decision", {})
        assert decision.get("behavior") == "allow"

    def test_kanban_review_emits_allow(self, hook):
        payload = make_bash_payload("kanban review 42 --session test-session")
        result = run_hook_main(hook, payload)
        assert result is not None
        decision = result.get("hookSpecificOutput", {}).get("decision", {})
        assert decision.get("behavior") == "allow"

    def test_kanban_redo_emits_allow(self, hook):
        payload = make_bash_payload("kanban redo 42 --session test-session")
        result = run_hook_main(hook, payload)
        assert result is not None
        decision = result.get("hookSpecificOutput", {}).get("decision", {})
        assert decision.get("behavior") == "allow"


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------

class TestAllowResponseStructure:
    """Verify the allow response has the correct hookSpecificOutput structure."""

    def test_response_has_hook_specific_output(self, hook):
        payload = make_bash_payload("kanban show 1 --session s")
        result = run_hook_main(hook, payload)
        assert result is not None
        assert "hookSpecificOutput" in result

    def test_response_hook_event_name(self, hook):
        payload = make_bash_payload("kanban show 1 --session s")
        result = run_hook_main(hook, payload)
        assert result is not None
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("hookEventName") == "PermissionRequest"

    def test_response_decision_behavior_allow(self, hook):
        payload = make_bash_payload("kanban status --session s")
        result = run_hook_main(hook, payload)
        assert result is not None
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("decision", {}).get("behavior") == "allow"


# ---------------------------------------------------------------------------
# Silent: non-kanban commands are not auto-approved
# ---------------------------------------------------------------------------

class TestNonKanbanCommandsSilent:
    """Bash tool calls with non-kanban commands → silent exit (no output)."""

    def test_npm_test_silent(self, hook):
        payload = make_bash_payload("npm test")
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected silent exit for npm test, got: {result}"

    def test_git_push_silent(self, hook):
        payload = make_bash_payload("git push origin main")
        result = run_hook_main(hook, payload)
        assert result is None

    def test_pytest_silent(self, hook):
        payload = make_bash_payload("pytest modules/ -x")
        result = run_hook_main(hook, payload)
        assert result is None

    def test_echo_kanban_silent(self, hook):
        """Command containing 'kanban' but not starting with it → silent."""
        payload = make_bash_payload("echo 'run kanban show 42'")
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected silent for echo kanban, got: {result}"

    def test_kanban_in_middle_of_command_silent(self, hook):
        """'kanban' in the middle (not the start) → silent."""
        payload = make_bash_payload("cat /tmp/kanban-output.txt")
        result = run_hook_main(hook, payload)
        assert result is None


# ---------------------------------------------------------------------------
# Silent: non-Bash tool
# ---------------------------------------------------------------------------

class TestNonBashToolSilent:
    """Non-Bash tool_name → hook is silent regardless of input."""

    def test_read_tool_silent(self, hook):
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/file.py"},
        }
        result = run_hook_main(hook, payload)
        assert result is None

    def test_agent_tool_with_kanban_in_prompt_silent(self, hook):
        """Agent tool with 'kanban' in prompt → silent (only Bash is auto-approved)."""
        payload = {
            "tool_name": "Agent",
            "tool_input": {"prompt": "kanban show 42 --session test"},
        }
        result = run_hook_main(hook, payload)
        assert result is None


# ---------------------------------------------------------------------------
# Fail-open: error conditions → silent exit
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Error conditions result in silent exit, never crash."""

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

        with patch.object(sys, "stdin", io.StringIO("{bad json")):
            with patch("builtins.print", side_effect=fake_print):
                try:
                    hook.main()
                except SystemExit:
                    pass

        assert not captured, f"Expected no output for malformed JSON, got: {captured}"

    def test_missing_tool_input_silent(self, hook):
        """Payload missing tool_input → silent exit (command defaults to empty)."""
        payload = {"tool_name": "Bash"}
        result = run_hook_main(hook, payload)
        assert result is None

    def test_missing_command_key_silent(self, hook):
        """Payload where 'command' key is absent → command defaults to empty string → silent."""
        payload = {"tool_name": "Bash", "tool_input": {"other_key": "value"}}
        result = run_hook_main(hook, payload)
        assert result is None
