"""
Tests for modules/claude/senior-staff-cron-hook.py.

Covered paths:
- KANBAN_AGENT=senior-staff-engineer → silent (cron lifecycle managed by crew-lifecycle-hook)
- KANBAN_AGENT=anything-else → silent (no stdout)
- KANBAN_AGENT unset → silent (no stdout)
- Malformed JSON stdin → fail open (hook exits 0, no crash)
- Hook is always silent — no stdout output in any code path
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

_HOOK_PATH = Path(__file__).parent.parent / "senior-staff-cron-hook.py"


def load_hook():
    """Import senior-staff-cron-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("senior_staff_cron_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the senior-staff-cron-hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with env and stdin, capture stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, stdin_content: str, env_overrides: dict) -> dict | None:
    """
    Call hook_mod.main() with the given stdin content and environment.
    Returns the parsed JSON written to stdout, or None if nothing was printed.
    """
    captured_output: list[str] = []

    def fake_print(val, **kwargs):
        # Only capture stdout; ignore stderr writes (file=sys.stderr)
        if kwargs.get("file") is sys.stderr:
            return
        captured_output.append(val)

    base_env = {k: v for k, v in os.environ.items()}
    base_env.pop("KANBAN_AGENT", None)  # Remove from base; test supplies explicitly
    merged_env = {**base_env, **env_overrides}

    with patch.object(sys, "stdin", io.StringIO(stdin_content)):
        with patch("builtins.print", side_effect=fake_print):
            with patch.dict(os.environ, merged_env, clear=True):
                try:
                    hook_mod.main()
                except SystemExit:
                    pass

    if not captured_output:
        return None
    return json.loads(captured_output[-1])


def make_session_start_payload() -> str:
    """Build a minimal SessionStart hook payload as JSON string."""
    return json.dumps({
        "session_id": "test-session-abc",
        "hook_event_name": "SessionStart",
    })


# ---------------------------------------------------------------------------
# Silent: hook is always silent — cron lifecycle managed by crew-lifecycle-hook
# ---------------------------------------------------------------------------

class TestAlwaysSilent:
    """Hook emits no stdout in any scenario.

    Cron lifecycle is now managed by crew-lifecycle-hook (PostToolUse on
    'crew create' / 'crew dismiss'). This hook is retained for backward
    compatibility only and produces no output.
    """

    def test_silent_for_senior_staff_session(self, hook):
        """KANBAN_AGENT=senior-staff-engineer → no stdout output."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        assert result is None, (
            f"Expected no output for senior-staff-engineer (cron lifecycle delegated), got: {result}"
        )

    def test_silent_for_non_senior_staff_session(self, hook):
        """KANBAN_AGENT=staff-engineer → no stdout output."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "staff-engineer"},
        )
        assert result is None, f"Expected no output for staff-engineer, got: {result}"

    def test_silent_for_arbitrary_agent(self, hook):
        """KANBAN_AGENT=swe-backend → no stdout output."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "swe-backend"},
        )
        assert result is None, f"Expected no output for swe-backend, got: {result}"

    def test_silent_when_kanban_agent_unset(self, hook):
        """No KANBAN_AGENT env var → no stdout output."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {},  # No KANBAN_AGENT key at all
        )
        assert result is None, f"Expected no output when KANBAN_AGENT is unset, got: {result}"

    def test_silent_for_unknown_agent(self, hook):
        """KANBAN_AGENT=<unrecognized-agent-name> → no stdout output."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "unknown-agent"},
        )
        assert result is None, f"Expected no output for unknown agent, got: {result}"


# ---------------------------------------------------------------------------
# Fail-open: error conditions do not crash or emit unexpected output
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Hook fails open on error conditions — exits 0, no exception propagation."""

    def test_fail_open_on_malformed_json(self, hook):
        """Malformed JSON stdin → hook exits gracefully, no output."""
        result = run_hook_main(
            hook,
            "{bad json here :::}",
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        # Hook is always silent regardless of stdin content.
        assert result is None, f"Expected silence with malformed stdin, got: {result}"

    def test_fail_open_on_empty_stdin(self, hook):
        """Empty stdin → hook exits gracefully without crashing, no output."""
        result = run_hook_main(
            hook,
            "",
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        assert result is None, f"Expected silence with empty stdin, got: {result}"

    def test_fail_open_on_empty_stdin_non_senior_staff(self, hook):
        """Empty stdin + non-senior-staff env → silent (no exception)."""
        result = run_hook_main(
            hook,
            "",
            {"KANBAN_AGENT": "staff-engineer"},
        )
        assert result is None, f"Expected silence for staff-engineer with empty stdin, got: {result}"


# ---------------------------------------------------------------------------
# Always-silent: hook emits no CronCreate on any invocation
# ---------------------------------------------------------------------------

class TestAlwaysSilentOnRestart:
    """Hook emits no output on repeated SessionStart invocations.

    Cron lifecycle is managed by crew-lifecycle-hook (PostToolUse). This hook
    is a registered no-op retained for backward compatibility only.
    """

    def test_silent_on_every_session_start(self, hook):
        """Hook is always silent across multiple invocations."""
        payload = make_session_start_payload()
        env = {"KANBAN_AGENT": "senior-staff-engineer"}

        for invocation in range(1, 4):
            result = run_hook_main(hook, payload, env)
            assert result is None, (
                f"Expected silence on invocation {invocation}, got: {result}. "
                "Cron lifecycle is delegated to crew-lifecycle-hook."
            )
