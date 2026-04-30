"""
Starter tests for modules/claude/kanban-pretool-hook.py.

Test Pyramid:
  Tier 1 (this directory) — fast unit tests for hook and lint logic.
    Run: pytest modules/claude/tests/
    Pattern: hooks accept JSON on stdin; tests construct synthetic payloads
    and pipe them via subprocess or monkeypatched stdin.

  Tier 2 — manual e2e runbook for full-stack validation.
    Run on-demand (not in CI). Located at:
    .scratchpad/kanban-staff-engineer-stress-test.md

This file demonstrates the pretool hook test pattern that future maintainers
can follow when adding new test cases. Comprehensive coverage of the pretool
hook lives in test_kanban_pretool_hook.py (Tier 1, same directory).

Remaining test files to be added in follow-up cards:
  - test_kanban_cli.py
  - test_subagentstop_hook.py
  - test_prompt_coverage.py
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK_PATH = Path(__file__).parent.parent / "kanban-pretool-hook.py"


def _run_hook_subprocess(payload: dict) -> subprocess.CompletedProcess:
    """Run the pretool hook script directly with a JSON payload on stdin.

    This exercises the hook via the standard Claude Code hook protocol:
    the hook reads JSON from stdin and writes JSON to stdout.

    Hermeticity note: These tests only reach the early-exit deny paths
    (cardless agent, general-purpose subagent type). Those paths exit before
    any kanban DB writes occur, so no mocking or isolation is needed for the
    current test suite. Future tests that exercise card-injection paths (where
    the hook calls `kanban show` to fetch card XML) would need either mocked
    subprocess.run calls or a KANBAN_TEST_MODE env var to avoid real DB side
    effects. See test_kanban_pretool_hook.py for the monkeypatch pattern used
    in those deeper tests.
    """
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def _make_agent_payload(
    prompt: str = "KANBAN CARD #42 | Session: test-session\nDo some work.",
    run_in_background: bool = True,
    description: str = "Test description",
    subagent_type: str = "swe-devex",
) -> dict:
    """Build a minimal PreToolUse Agent JSON payload."""
    return {
        "tool_name": "Agent",
        "tool_input": {
            "prompt": prompt,
            "run_in_background": run_in_background,
            "description": description,
            "subagent_type": subagent_type,
        },
        "session_id": "outer-session-abc",
    }


class TestCardlessDenial:
    """Agent call missing a card reference must be denied."""

    def test_cardless_agent_denied(self):
        """Synthesize a PreToolUse payload with no card reference; assert hook exits non-zero."""
        payload = _make_agent_payload(prompt="Please do some work without any card reference.")
        result = _run_hook_subprocess(payload)
        # Hook always exits 0 by design — denial signaled via stdout JSON, not exit code
        assert _is_denied(result.stdout), f"Expected denial in stdout: {result.stdout!r}"


class TestGeneralPurposeSubagentDenial:
    """Agent call with subagent_type 'general-purpose' must be denied."""

    def test_general_purpose_subagent_denied(self):
        """Synthesize a PreToolUse payload with subagent_type=general-purpose; assert denial."""
        payload = _make_agent_payload(subagent_type="general-purpose")
        result = _run_hook_subprocess(payload)
        # Hook always exits 0 by design — denial signaled via stdout JSON, not exit code
        assert _is_denied(result.stdout), f"Expected denial in stdout: {result.stdout!r}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_denied(stdout: str) -> bool:
    """Return True if the hook output JSON contains a 'deny' permissionDecision."""
    try:
        data = json.loads(stdout)
        decision = data.get("hookSpecificOutput", {}).get("permissionDecision", "")
        return decision == "deny"
    except (json.JSONDecodeError, AttributeError):
        return False
