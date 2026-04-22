"""
Tests for modules/claude/senior-staff-cron-hook.py.

Covered paths:
- KANBAN_AGENT=senior-staff-engineer → emits {"result": "..."} with CronCreate directive
- KANBAN_AGENT=anything-else → silent (no stdout)
- KANBAN_AGENT unset → silent (no stdout)
- Malformed JSON stdin → fail open (hook exits 0, no crash)
- Response structure: "result" key present with CronCreate prompt content
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
# Fires: KANBAN_AGENT=senior-staff-engineer → emits CronCreate prompt
# ---------------------------------------------------------------------------

class TestEmitsCronPromptForSeniorStaff:
    """Hook emits CronCreate directive when KANBAN_AGENT=senior-staff-engineer."""

    def test_emits_cron_prompt_for_senior_staff_session(self, hook):
        """KANBAN_AGENT=senior-staff-engineer → hook emits {"result": "..."} JSON."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        assert result is not None, "Expected JSON output for senior-staff-engineer session"
        assert "result" in result, f"Expected 'result' key in output, got: {result}"

    def test_result_contains_croncreate_directive(self, hook):
        """result field mentions CronCreate."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        assert result is not None
        prompt = result.get("result", "")
        assert "CronCreate" in prompt, f"Expected 'CronCreate' in result, got: {prompt[:200]}"

    def test_result_contains_crew_status_command(self, hook):
        """result field contains the 'crew status' command to schedule."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        assert result is not None
        prompt = result.get("result", "")
        assert "crew status" in prompt, f"Expected 'crew status' in result, got: {prompt[:200]}"

    def test_result_contains_schedule_expression(self, hook):
        """result field contains the cron schedule expression."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        assert result is not None
        prompt = result.get("result", "")
        assert "*/10 * * * *" in prompt, f"Expected cron schedule in result, got: {prompt[:200]}"

    def test_result_contains_senior_staff_harness_header(self, hook):
        """result field contains the [Senior Staff Harness] header."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        assert result is not None
        prompt = result.get("result", "")
        assert "Senior Staff Harness" in prompt


# ---------------------------------------------------------------------------
# Silent: non-Senior-Staff sessions produce no stdout
# ---------------------------------------------------------------------------

class TestSilentForNonSeniorStaff:
    """Hook is silent when KANBAN_AGENT is not 'senior-staff-engineer'."""

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

    def test_silent_for_ac_reviewer_agent(self, hook):
        """KANBAN_AGENT=ac-reviewer → no stdout output."""
        result = run_hook_main(
            hook,
            make_session_start_payload(),
            {"KANBAN_AGENT": "ac-reviewer"},
        )
        assert result is None, f"Expected no output for ac-reviewer, got: {result}"


# ---------------------------------------------------------------------------
# Fail-open: error conditions do not crash or emit unexpected output
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Hook fails open on error conditions — exits 0, no exception propagation."""

    def test_fail_open_on_malformed_json(self, hook):
        """Malformed JSON stdin → hook still exits gracefully (no exception)."""
        result = run_hook_main(
            hook,
            "{bad json here :::}",
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        # Even with malformed JSON, senior-staff sessions still emit the prompt
        # because the hook fails open on JSON parse and uses empty payload.
        # The important thing: no exception is raised.
        # The hook behavior with bad JSON + senior-staff env = emit prompt (payload is empty dict).
        assert result is not None, "Expected prompt even with malformed stdin (fail open)"
        assert "result" in result

    def test_fail_open_on_empty_stdin(self, hook):
        """Empty stdin → hook exits gracefully without crashing."""
        result = run_hook_main(
            hook,
            "",
            {"KANBAN_AGENT": "senior-staff-engineer"},
        )
        # Empty stdin is treated as empty payload — senior-staff sessions still emit prompt
        assert result is not None, "Expected prompt with empty stdin (fail open)"
        assert "result" in result

    def test_fail_open_on_empty_stdin_non_senior_staff(self, hook):
        """Empty stdin + non-senior-staff env → silent (no exception)."""
        result = run_hook_main(
            hook,
            "",
            {"KANBAN_AGENT": "staff-engineer"},
        )
        assert result is None, f"Expected silence for staff-engineer with empty stdin, got: {result}"
