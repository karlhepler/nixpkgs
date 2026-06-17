"""
Regression test for the run_in_background parsing bug in kanban-pretool-hook.py.

Bug: The hook denied Agent tool calls with "missing run_in_background: true" even
when the caller set run_in_background — because Claude Code models sometimes emit
run_in_background as the JSON string "true" instead of the boolean true.

Fix: line 1055 — the hook now accepts both boolean true and string "true" (case-
insensitive) as equivalent. Any other value (False, "false", None, absent) is
denied unless FOREGROUND_AUTHORIZED is present.

This test invokes the hook as a subprocess feeding a realistic PreToolUse JSON
payload on stdin, per the Claude Code hook protocol.

Cases:
    (a) run_in_background: true (boolean)       → PERMIT (explicit allow)
    (b) run_in_background: "true" (string)      → PERMIT (the bug case; explicit allow)
    (b2) run_in_background: "True" (uppercase)  → PERMIT (case-insensitive)
    (b3) run_in_background: "TRUE" (uppercase)  → PERMIT (case-insensitive)
    (c) run_in_background absent, no escape     → DENY
    (d) run_in_background: false (boolean)      → DENY
    (e) run_in_background: "false" (string)     → DENY
    (f) run_in_background: "" (empty string)    → DENY
    (g) run_in_background: 1 (integer)          → DENY (only bool True via identity)
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK_PATH = Path(__file__).parent / "kanban-pretool-hook.py"


def _run_hook(payload: dict) -> dict:
    """Invoke the hook as a subprocess with the payload on stdin.

    Returns the parsed JSON from stdout. The hook always exits 0 (fail-open
    contract), so we do not check the exit code — the decision lives in stdout.
    """
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Hook exited {result.returncode} (should always be 0). "
        f"stderr: {result.stderr!r}"
    )
    assert result.stdout.strip(), "Hook produced no stdout"
    return json.loads(result.stdout.strip())


def _permission_decision(output: dict) -> str:
    """Extract the permissionDecision from hook output."""
    return output.get("hookSpecificOutput", {}).get("permissionDecision", "")


def _permission_reason(output: dict) -> str:
    """Extract the permissionDecisionReason from hook output."""
    return output.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def _build_payload(run_in_background) -> dict:
    """Build a minimal but realistic PreToolUse Agent payload.

    Includes a card reference so the hook proceeds past the card-check gate.
    The kanban CLI will fail (no real card), but the hook fails-open on that
    path — the run_in_background check fires BEFORE the card fetch, and the
    card fetch failure returns allow_unchanged() (decision="allow"). This
    guarantees that permit-path test cases receive decision="allow" when the
    run_in_background check passes.

    run_in_background is passed as-is (boolean, string, or omitted when None).
    """
    tool_input = {
        "prompt": "KANBAN CARD #9999 | Session: test-session\nDo the work.",
        "description": "Regression test agent launch",
        "subagent_type": "swe-backend",
    }
    if run_in_background is not None:
        tool_input["run_in_background"] = run_in_background

    return {
        "tool_name": "Agent",
        "tool_input": tool_input,
        "session_id": "outer-test-session",
    }


# ---------------------------------------------------------------------------
# Permit cases — affirmative run_in_background values must result in "allow"
# ---------------------------------------------------------------------------
# The hook:
#   1. Validates run_in_background — denies immediately if not affirmative.
#   2. Extracts the card reference and fetches card XML via kanban CLI.
#   3. Falls open (allow) if the kanban CLI fails (card #9999 does not exist).
# Therefore any payload that passes the run_in_background gate will produce
# decision="allow", making explicit allow assertions reliable in these tests.
# ---------------------------------------------------------------------------

def test_run_in_background_boolean_true_is_permitted():
    """Boolean true is the canonical form — hook must explicitly allow."""
    payload = _build_payload(run_in_background=True)
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "allow", (
        f"Boolean true should be permitted (decision='allow'), got {decision!r}. "
        f"Full output: {output}"
    )


def test_run_in_background_string_true_is_permitted():
    """String 'true' must be accepted as equivalent to boolean true.

    Claude Code models sometimes emit run_in_background as the JSON string 'true'
    instead of the boolean. This was the root cause of the production denials
    observed on 2026-06-17 across two maze-monorepo staff sessions.
    """
    payload = _build_payload(run_in_background="true")
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "allow", (
        f"String 'true' should be permitted (decision='allow'), got {decision!r}. "
        f"Full output: {output}"
    )


def test_run_in_background_string_True_uppercase_is_permitted():
    """String 'True' (Python-style capitalization) must be accepted.

    The comparison strips whitespace and lowercases before comparing to 'true',
    so 'True', 'TRUE', '  true  ' are all treated as affirmative.
    """
    payload = _build_payload(run_in_background="True")
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "allow", (
        f"String 'True' should be permitted (decision='allow'), got {decision!r}. "
        f"Full output: {output}"
    )


def test_run_in_background_string_TRUE_uppercase_is_permitted():
    """String 'TRUE' (all-caps) must be accepted (case-insensitive comparison)."""
    payload = _build_payload(run_in_background="TRUE")
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "allow", (
        f"String 'TRUE' should be permitted (decision='allow'), got {decision!r}. "
        f"Full output: {output}"
    )


# ---------------------------------------------------------------------------
# Deny cases — non-affirmative run_in_background values must result in "deny"
# ---------------------------------------------------------------------------

def test_missing_run_in_background_is_denied():
    """Absent run_in_background (no FOREGROUND_AUTHORIZED escape) must be denied."""
    payload = _build_payload(run_in_background=None)
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "deny", (
        f"Expected deny for missing run_in_background, got {decision!r}. "
        f"Full output: {output}"
    )
    reason = _permission_reason(output)
    assert "run_in_background" in reason, (
        f"Deny reason should mention run_in_background. Got: {reason!r}"
    )


def test_run_in_background_boolean_false_is_denied():
    """Boolean false must be denied — only boolean True (identity) is accepted.

    Guards against future `== True` drift: integer 1 == True in Python, but
    1 is not True. This test confirms the identity check (`is True`) is used,
    not equality.
    """
    payload = _build_payload(run_in_background=False)
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "deny", (
        f"Expected deny for boolean false, got {decision!r}. "
        f"Full output: {output}"
    )
    reason = _permission_reason(output)
    assert "run_in_background" in reason, (
        f"Deny reason should mention run_in_background. Got: {reason!r}"
    )


def test_run_in_background_string_false_is_denied():
    """String 'false' must be denied — only 'true' (case-insensitive) is accepted."""
    payload = _build_payload(run_in_background="false")
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "deny", (
        f"Expected deny for string 'false', got {decision!r}. "
        f"Full output: {output}"
    )
    reason = _permission_reason(output)
    assert "run_in_background" in reason, (
        f"Deny reason should mention run_in_background. Got: {reason!r}"
    )


def test_run_in_background_empty_string_is_denied():
    """Empty string must be denied — not an affirmative value."""
    payload = _build_payload(run_in_background="")
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "deny", (
        f"Expected deny for empty string, got {decision!r}. "
        f"Full output: {output}"
    )
    reason = _permission_reason(output)
    assert "run_in_background" in reason, (
        f"Deny reason should mention run_in_background. Got: {reason!r}"
    )


def test_run_in_background_integer_1_is_denied():
    """Integer 1 must be denied — only the boolean singleton True passes.

    Python's `== True` equality check would accept integer 1 (since 1 == True).
    The hook uses `is True` (identity check) to guard against this. This test
    catches any future drift from `is True` to `== True`.
    """
    payload = _build_payload(run_in_background=1)
    output = _run_hook(payload)
    decision = _permission_decision(output)
    assert decision == "deny", (
        f"Expected deny for integer 1 (not bool True), got {decision!r}. "
        f"Full output: {output}"
    )
    reason = _permission_reason(output)
    assert "run_in_background" in reason, (
        f"Deny reason should mention run_in_background. Got: {reason!r}"
    )
