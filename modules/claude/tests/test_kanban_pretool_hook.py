"""
Tests for modules/claude/kanban-pretool-hook.py.

Covered paths:
- Agent call missing run_in_background → denied with expected error message
- Agent call missing description → denied
- Agent call missing subagent_type → denied
- Agent call with invalid subagent_type (general-purpose) → denied
- Agent call with card number → card XML injected into prompt
- Agent call without card number → denied unless SKILL_AGENT_BYPASS marker
- Agent call with FOREGROUND_AUTHORIZED marker → allows run_in_background: false
- Agent call with SKILL_AGENT_BYPASS marker → bypasses all enforcement

All kanban CLI and subprocess calls are monkeypatched — no real kanban cards
are created or read during these tests.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from .conftest import KanbanMockResponses, make_pretool_payload

# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "kanban-pretool-hook.py"


def load_hook():
    """Import kanban-pretool-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_pretool_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the pretool hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a JSON payload via monkeypatched stdin / stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, payload: dict, env: dict | None = None) -> dict:
    """
    Call hook_mod.main() with the given payload dict as stdin JSON.
    Returns the parsed JSON written to stdout.
    """
    import io

    raw = json.dumps(payload)

    captured_output: list[str] = []

    def fake_print(val, **kwargs):
        captured_output.append(val)

    env_patch = env or {}

    with patch.object(sys, "stdin", io.StringIO(raw)):
        with patch("builtins.print", side_effect=fake_print):
            with patch.dict(os.environ, env_patch, clear=False):
                # Suppress log writes
                with patch.object(hook_mod, "log_error"):
                    with patch.object(hook_mod, "log_info"):
                        hook_mod.main()

    assert captured_output, "Hook produced no output"
    return json.loads(captured_output[-1])


# ---------------------------------------------------------------------------
# Helpers to assert decision outcomes
# ---------------------------------------------------------------------------

def assert_denied(result: dict, substring: str = ""):
    decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "deny", f"Expected deny, got {decision!r}. Full result: {result}"
    if substring:
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert substring.lower() in reason.lower(), (
            f"Expected {substring!r} in deny reason. Got: {reason!r}"
        )


def assert_allowed(result: dict):
    decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "allow", f"Expected allow, got {decision!r}. Full result: {result}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMissingRunInBackground:
    """Agent call missing run_in_background → denied with expected error message."""

    def test_false_run_in_background_denied(self, hook):
        payload = make_pretool_payload(run_in_background=False)
        result = run_hook_main(hook, payload)
        assert_denied(result, "run_in_background")

    def test_missing_run_in_background_denied(self, hook):
        # Omit the key entirely from tool_input
        payload = make_pretool_payload(run_in_background=None)
        # Remove the key — make_pretool_payload omits it when None
        result = run_hook_main(hook, payload)
        assert_denied(result, "run_in_background")

    def test_deny_reason_mentions_background(self, hook):
        payload = make_pretool_payload(run_in_background=False)
        result = run_hook_main(hook, payload)
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert "run_in_background" in reason
        assert "true" in reason.lower() or "background" in reason.lower()


class TestMissingDescription:
    """Agent call missing or empty description → denied."""

    def test_empty_description_denied(self, hook):
        payload = make_pretool_payload(description="")
        result = run_hook_main(hook, payload)
        assert_denied(result, "description")

    def test_whitespace_only_description_denied(self, hook):
        payload = make_pretool_payload(description="   ")
        result = run_hook_main(hook, payload)
        assert_denied(result, "description")

    def test_deny_reason_mentions_description(self, hook):
        payload = make_pretool_payload(description="")
        result = run_hook_main(hook, payload)
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert "description" in reason.lower()


class TestMissingSubagentType:
    """Agent call missing or empty subagent_type → denied."""

    def test_empty_subagent_type_denied(self, hook):
        payload = make_pretool_payload(subagent_type="")
        result = run_hook_main(hook, payload)
        assert_denied(result, "subagent_type")

    def test_whitespace_only_subagent_type_denied(self, hook):
        payload = make_pretool_payload(subagent_type="  ")
        result = run_hook_main(hook, payload)
        assert_denied(result, "subagent_type")

    def test_deny_reason_mentions_subagent_type(self, hook):
        payload = make_pretool_payload(subagent_type="")
        result = run_hook_main(hook, payload)
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert "subagent_type" in reason.lower()


class TestInvalidSubagentType:
    """Agent call with 'general-purpose' subagent_type → denied."""

    def test_general_purpose_denied(self, hook):
        payload = make_pretool_payload(subagent_type="general-purpose")
        result = run_hook_main(hook, payload)
        assert_denied(result, "general-purpose")

    def test_general_purpose_case_insensitive(self, hook):
        payload = make_pretool_payload(subagent_type="General-Purpose")
        result = run_hook_main(hook, payload)
        assert_denied(result, "general-purpose")

    def test_specific_subagent_allowed(self, hook):
        """swe-backend is a valid subagent type — hook proceeds past the subagent_type check."""
        payload = make_pretool_payload(subagent_type="swe-backend")
        # The card reference check fires next; mock kanban show to succeed
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)
        # Must be allowed (card injected) — not denied for subagent_type
        assert_allowed(result)


class TestCardInjection:
    """Agent call with card number → card XML injected into prompt."""

    def test_card_xml_injected_into_prompt(self, hook):
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        new_prompt = updated_input.get("prompt", "")
        assert "Kanban card #42" in new_prompt
        assert "injected by PreToolUse hook" in new_prompt

    def test_card_injection_preserves_original_fields(self, hook):
        """updatedInput must contain ALL original tool_input fields."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
            description="Test description",
            run_in_background=True,
        )
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        assert updated_input.get("subagent_type") == "swe-devex"
        assert updated_input.get("description") == "Test description"
        assert updated_input.get("run_in_background") is True

    def test_kanban_show_failure_fails_open(self, hook):
        """If kanban show fails, hook should fail open (allow unchanged)."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.failure(returncode=1)
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        # No updatedInput — fails open means no injection
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput")
        assert updated_input is None

    def test_fetch_card_xml_failure_logs_error(self, hook):
        """fetch_card_xml logs an error when kanban show fails (diagnostic path)."""
        # Test fetch_card_xml directly to assert log_error is called on failure
        mock_result = KanbanMockResponses.failure(returncode=1, stderr="not found")
        with patch("subprocess.run", return_value=mock_result):
            with patch.object(hook, "log_error") as mock_log_error:
                result = hook.fetch_card_xml("42", "test-session")
        assert result is None
        mock_log_error.assert_called_once()

    def test_sqlite_backfill_called_on_successful_kanban_agent(self, hook):
        """After successful kanban agent call, sqlite3.connect is called to backfill DB."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("sqlite3.connect", return_value=mock_conn) as mock_sqlite:
                result = run_hook_main(hook, payload)

        assert_allowed(result)
        mock_sqlite.assert_called_once()
        # Verify the UPDATE was executed with expected parameters
        execute_calls = mock_conn.execute.call_args_list
        update_calls = [c for c in execute_calls if "UPDATE" in str(c) and "kanban_card_events" in str(c)]
        assert len(update_calls) >= 1, "Expected UPDATE kanban_card_events to be called"
        # Verify the normalized agent value and card number are passed
        update_args = update_calls[0][0]  # positional args of the first UPDATE call
        params = update_args[1] if len(update_args) > 1 else ()
        assert "swe-devex" in params, f"Expected swe-devex in UPDATE params: {params}"
        assert "42" in params, f"Expected card number 42 in UPDATE params: {params}"

    def test_sqlite_backfill_not_called_when_kanban_agent_fails(self, hook):
        """If kanban agent call fails, sqlite3.connect should NOT be called."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                # kanban agent fails
                return KanbanMockResponses.failure(returncode=1)
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("sqlite3.connect") as mock_sqlite:
                result = run_hook_main(hook, payload)

        assert_allowed(result)
        mock_sqlite.assert_not_called()

    def test_sqlite_exception_swallowed_does_not_propagate(self, hook):
        """If sqlite3.connect raises, the error is swallowed and hook still allows."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("sqlite3.connect", side_effect=Exception("DB not available")):
                # Must not raise — exception must be swallowed
                result = run_hook_main(hook, payload)

        # Hook should still allow despite DB failure
        assert_allowed(result)


class TestNoCardReference:
    """Agent call without card number → denied unless SKILL_AGENT_BYPASS."""

    def test_no_card_reference_denied(self, hook):
        payload = make_pretool_payload(prompt="Please do some work without any card reference.")
        result = run_hook_main(hook, payload)
        assert_denied(result, "kanban card")

    def test_deny_reason_explains_card_requirement(self, hook):
        payload = make_pretool_payload(prompt="Work without a card.")
        result = run_hook_main(hook, payload)
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert "kanban" in reason.lower() or "card" in reason.lower()


class TestForegroundAuthorized:
    """FOREGROUND_AUTHORIZED marker → allows run_in_background: false."""

    def test_foreground_authorized_bypasses_background_check(self, hook):
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="FOREGROUND_AUTHORIZED\nKANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)

    def test_foreground_authorized_with_whitespace_padding_bypasses(self, hook):
        """FOREGROUND_AUTHORIZED with leading/trailing whitespace on its own line is allowed."""
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="  FOREGROUND_AUTHORIZED  \nKANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)

    def test_foreground_authorized_still_enforces_description(self, hook):
        """FOREGROUND_AUTHORIZED does NOT bypass description check."""
        payload = make_pretool_payload(
            run_in_background=False,
            description="",
            prompt="FOREGROUND_AUTHORIZED\nKANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        result = run_hook_main(hook, payload)
        assert_denied(result, "description")

    def test_foreground_authorized_in_negation_prose_is_denied(self, hook):
        """FOREGROUND_AUTHORIZED embedded in prose (negation) must NOT bypass check.

        Bug fix: 'no FOREGROUND_AUTHORIZED marker' used to bypass the check via
        substring match. The line-anchored regex must reject prose that merely
        contains the marker text — the marker must occupy its own line.
        """
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="This prompt says no FOREGROUND_AUTHORIZED marker is present.",
        )
        result = run_hook_main(hook, payload)
        assert_denied(result, "run_in_background")


class TestSkillAgentBypass:
    """SKILL_AGENT_BYPASS marker → bypasses all enforcement."""

    def test_bypass_skips_description_check(self, hook):
        payload = make_pretool_payload(
            run_in_background=None,
            description=None,
            subagent_type=None,
            prompt="SKILL_AGENT_BYPASS\nsome skill invocation",
        )
        result = run_hook_main(hook, payload)
        # Should be allow (no card found so fails open)
        assert_allowed(result)

    def test_bypass_skips_subagent_type_check(self, hook):
        payload = make_pretool_payload(
            subagent_type=None,
            prompt="SKILL_AGENT_BYPASS\nsome skill invocation",
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bypass_skips_run_in_background_check(self, hook):
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="SKILL_AGENT_BYPASS\nsome skill invocation",
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_skill_agent_bypass_with_whitespace_padding_bypasses(self, hook):
        """SKILL_AGENT_BYPASS with leading/trailing whitespace on its own line is allowed."""
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="  SKILL_AGENT_BYPASS  \nsome skill invocation",
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_skill_agent_bypass_in_negation_prose_is_denied(self, hook):
        """SKILL_AGENT_BYPASS embedded in prose must NOT trigger bypass.

        Bug fix: 'no SKILL_AGENT_BYPASS marker' used to bypass enforcement
        via substring match. The line-anchored regex must reject prose that
        merely contains the marker text.
        """
        payload = make_pretool_payload(
            run_in_background=False,
            description="",
            subagent_type="",
            prompt="This prompt says no SKILL_AGENT_BYPASS marker should be here.",
        )
        result = run_hook_main(hook, payload)
        # Without bypass, empty description triggers deny
        assert_denied(result, "description")

    def test_bypass_with_card_reference_still_injects(self, hook):
        """With SKILL_AGENT_BYPASS and a card reference, injection still occurs."""
        payload = make_pretool_payload(
            run_in_background=None,
            description=None,
            subagent_type=None,
            prompt="SKILL_AGENT_BYPASS\nKANBAN CARD #99 | Session: bypass-session\nDo work.",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="99", session="bypass-session")

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        new_prompt = updated_input.get("prompt", "")
        # Both the card reference AND the injection marker must be present
        assert "Kanban card #99" in new_prompt, (
            f"Expected 'Kanban card #99' in injected prompt, got: {new_prompt[:200]!r}"
        )
        assert "injected by PreToolUse hook" in new_prompt, (
            f"Expected injection marker in prompt, got: {new_prompt[:200]!r}"
        )


class TestBurnsSession:
    """BURNS_SESSION=1 → hook skips all processing and allows unchanged."""

    def test_burns_session_allows_unchanged(self, hook):
        payload = make_pretool_payload(run_in_background=False, description="", subagent_type="")
        result = run_hook_main(hook, payload, env={"BURNS_SESSION": "1"})
        assert_allowed(result)
        # No updatedInput — completely unchanged
        assert "updatedInput" not in result.get("hookSpecificOutput", {})


class TestNonAgentTool:
    """Non-Agent tool_name → allow unchanged (hook is Agent-only)."""

    def test_non_agent_tool_allowed(self, hook):
        payload = make_pretool_payload()
        payload["tool_name"] = "Bash"
        result = run_hook_main(hook, payload)
        assert_allowed(result)


class TestResponseStructure:
    """Verify the hook always produces structurally valid JSON output."""

    def test_allow_response_has_required_fields(self, hook):
        payload = make_pretool_payload()
        card_xml = KanbanMockResponses.card_xml()
        with patch("subprocess.run", return_value=KanbanMockResponses.success(stdout=card_xml)):
            result = run_hook_main(hook, payload)
        assert "continue" in result
        assert "hookSpecificOutput" in result
        hook_out = result["hookSpecificOutput"]
        assert "hookEventName" in hook_out
        assert hook_out["hookEventName"] == "PreToolUse"
        assert "permissionDecision" in hook_out

    def test_deny_response_has_required_fields(self, hook):
        payload = make_pretool_payload(run_in_background=False)
        result = run_hook_main(hook, payload)
        assert result["continue"] is False
        hook_out = result["hookSpecificOutput"]
        assert hook_out["permissionDecision"] == "deny"
        assert "permissionDecisionReason" in hook_out


class TestCardPatternExtraction:
    """Unit tests for extract_card_and_session directly."""

    def test_full_pattern(self, hook):
        prompt = "KANBAN CARD #123 | Session: my-session\nDo work."
        result = hook.extract_card_and_session(prompt)
        assert result == ("123", "my-session")

    def test_card_session_pattern(self, hook):
        prompt = "#456 --session another-session do something"
        result = hook.extract_card_and_session(prompt)
        assert result == ("456", "another-session")

    def test_bare_card_pattern(self, hook):
        prompt = "Work on card #789 please.\nSession: bare-session"
        result = hook.extract_card_and_session(prompt)
        assert result == ("789", "bare-session")

    def test_no_match_returns_none(self, hook):
        prompt = "No card reference here at all."
        result = hook.extract_card_and_session(prompt)
        assert result is None

    def test_card_session_pattern_requires_same_line(self, hook):
        """Pattern 2 (_CARD_SESSION_PATTERN) requires card # and --session on the same line.
        When they are on different lines, it falls through to Pattern 3 (bare card + bare session).
        """
        # Card number on one line, --session on a different line — Pattern 2 must NOT match.
        # Pattern 3 (bare card + bare session) should pick this up instead.
        prompt = "card #456\n--session cross-line-session\nDo work."
        result = hook.extract_card_and_session(prompt)
        # Pattern 3 (bare card + bare session) can still match here
        # The important thing is Pattern 2 didn't match (which would also give the right answer)
        # We verify the result is correct regardless of which pattern matched
        assert result is not None, "Expected some match via Pattern 3 fallthrough"
        assert result[0] == "456"
        assert result[1] == "cross-line-session"


# ---------------------------------------------------------------------------
# Helpers for destructive-git safeguard tests
# ---------------------------------------------------------------------------

def make_bash_payload(
    command: str,
    agent_id: str | None = "agent-abc123",
    session_id: str = "test-session",
    cwd: str = "/repo",
) -> dict:
    """Build a minimal PreToolUse Bash payload."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session_id,
        "cwd": cwd,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return payload


def make_kanban_list_xml(card_number: str = "42") -> str:
    """Build a minimal kanban list XML response containing one card."""
    return f'<cards><c n="{card_number}" status="doing"/></cards>'


def make_kanban_show_xml(card_number: str = "42", edit_files: list | None = None) -> str:
    """Build a minimal kanban show XML with optional edit-files entries."""
    if edit_files is None:
        edit_files = ["modules/claude/kanban-pretool-hook.py"]
    ef_entries = "".join(f"<f>{f}</f>" for f in edit_files)
    ef_block = f"<edit-files>{ef_entries}</edit-files>" if ef_entries else "<edit-files/>"
    return (
        f'<card num="{card_number}" session="test-session" status="doing">'
        f"<intent>Test card</intent>"
        f"{ef_block}"
        f"</card>"
    )


def patch_kanban_for_editfiles(edit_files: list | None = None, card_number: str = "42"):
    """Return a fake subprocess.run that simulates successful kanban list + show."""
    list_xml = make_kanban_list_xml(card_number)
    show_xml = make_kanban_show_xml(card_number, edit_files)

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "kanban":
            if cmd[1] == "list":
                return KanbanMockResponses.success(stdout=list_xml)
            if cmd[1] == "show":
                return KanbanMockResponses.success(stdout=show_xml)
        return KanbanMockResponses.failure()

    return fake_run


class TestDestructiveGitSafeguard:
    """Tests for the destructive git operation safeguard in _validate_bash_destructive_git.

    All kanban CLI calls are patched via subprocess.run — no real kanban state is read.
    """

    # 1. Sub-agent + git checkout -- <in-scope-file> → ALLOW
    def test_checkout_in_scope_file_allowed(self, hook):
        """git checkout -- on a file that IS in editFiles must be allowed."""
        payload = make_bash_payload("git checkout -- modules/claude/kanban-pretool-hook.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 2. Sub-agent + git checkout -- <out-of-scope-file> → DENY
    def test_checkout_out_of_scope_file_denied(self, hook):
        """git checkout -- on a file NOT in editFiles must be denied with card + file info."""
        payload = make_bash_payload("git checkout -- secret.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "secret.py" in reason
        assert "editFiles" in reason

    # 3. Sub-agent + git restore <out-of-scope-file> → DENY
    def test_restore_out_of_scope_file_denied(self, hook):
        """git restore on an out-of-scope file must be denied."""
        payload = make_bash_payload("git restore other_module.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 4. Sub-agent + git restore --staged <out-of-scope-file> → DENY
    def test_restore_staged_out_of_scope_denied(self, hook):
        """git restore --staged on an out-of-scope file must be denied."""
        payload = make_bash_payload("git restore --staged other_module.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 5. Sub-agent + git reset -- <out-of-scope-file> → DENY
    def test_reset_file_out_of_scope_denied(self, hook):
        """git reset -- <file> on an out-of-scope file must be denied."""
        payload = make_bash_payload("git reset -- secret.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 6. Sub-agent + git reset --hard HEAD → DENY unconditionally
    def test_reset_hard_denied_unconditionally(self, hook):
        """git reset --hard is blocked regardless of editFiles — reverts ALL tracked files."""
        payload = make_bash_payload("git reset --hard HEAD")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "reset --hard" in reason or "all tracked" in reason.lower()

    # 7. Sub-agent + git stash drop → DENY unconditionally
    def test_stash_drop_denied_unconditionally(self, hook):
        """git stash drop is always denied for sub-agents."""
        payload = make_bash_payload("git stash drop")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash drop" in reason

    # 8. Sub-agent + git clean -f → DENY (synthetic <all-untracked> target)
    def test_clean_denied_all_untracked(self, hook):
        """git clean -f is denied — no specific file, affects all untracked."""
        payload = make_bash_payload("git clean -f")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 9. Sub-agent + git checkout <branch> → ALLOW (non-destructive branch switch)
    def test_checkout_branch_allowed(self, hook):
        """git checkout <branch> is a non-destructive branch switch and must be allowed."""
        payload = make_bash_payload("git checkout main")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 10. Sub-agent + git checkout -b <branch> → ALLOW
    def test_checkout_new_branch_allowed(self, hook):
        """git checkout -b <branch> creates a new branch — non-destructive, must be allowed."""
        payload = make_bash_payload("git checkout -b feature/my-feature")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 11. Main thread (no agent_id) + git checkout -- <any-file> → ALLOW (staff bypass)
    def test_main_thread_bypasses_safeguard(self, hook):
        """Without agent_id, the safeguard does not apply — staff engineer is allowed."""
        payload = make_bash_payload(
            "git checkout -- secret.py",
            agent_id=None,  # No agent_id → main session
        )
        # Even with a mocked kanban that could respond, the guard should not be reached
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 12. Compound git status && git checkout -- <out-of-scope> → DENY
    def test_compound_and_operator_denied(self, hook):
        """Compound command with && must still catch the destructive git checkout."""
        payload = make_bash_payload("git status && git checkout -- secret.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 13. Compound git status; git checkout -- <out-of-scope> → DENY
    def test_compound_semicolon_operator_denied(self, hook):
        """Compound command with ; must still catch the destructive git checkout."""
        payload = make_bash_payload("git status; git checkout -- secret.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 14. Kanban lookup failure → ALLOW (fails open — documents accepted trade-off)
    def test_kanban_lookup_failure_fails_open(self, hook):
        """When kanban CLI is unavailable, the safeguard fails open to avoid blocking work.

        This is an accepted trade-off: a kanban outage creates a bypass window,
        but blocking all git ops during infrastructure issues is worse.
        """
        payload = make_bash_payload("git checkout -- secret.py")
        with patch("subprocess.run", side_effect=subprocess.SubprocessError("kanban not found")):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 15. Card with empty editFiles → DENY all destructive ops
    def test_empty_edit_files_denies_all_destructive(self, hook):
        """A card with no editFiles must deny all destructive git ops."""
        payload = make_bash_payload("git checkout -- any_file.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(edit_files=[])):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "none listed" in reason.lower() or "no editFiles" in reason.lower() or "editfiles" in reason.lower()

    # 16. git checkout -p with no file target → DENY with clear error (not confusing sentinel)
    def test_checkout_p_no_file_denied_with_clear_message(self, hook):
        """git checkout -p (no file) must produce a human-readable error, not a sentinel name."""
        payload = make_bash_payload("git checkout -p")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        # Must NOT expose the raw sentinel token as a filename
        assert "<interactive-hunk-revert>" not in reason
        # Must explain WHY it was blocked
        assert "interactive" in reason.lower() or "checkout -p" in reason.lower()

    # 17. fnmatch basename fallback: bare 'foo.py' editFile + target 'src/foo.py' → NO match
    def test_basename_fallback_not_over_permissive(self, hook):
        """A bare 'foo.py' editFiles entry must NOT match 'src/foo.py' after the M3 fix.

        The tightened basename fallback only applies when the pattern contains no path
        separator, but the pattern 'foo.py' should only match a file literally named
        'foo.py' at the root — NOT 'src/foo.py'.
        """
        # Use _file_in_editfiles directly to test the matching logic in isolation
        hook_mod = hook
        # 'foo.py' as a bare pattern should NOT match 'src/foo.py'
        result = hook_mod._file_in_editfiles("src/foo.py", ["foo.py"], "/repo")
        assert result is False, (
            "bare 'foo.py' in editFiles must not match 'src/foo.py' after M3 basename fix"
        )

    # 18. git stash push → DENY unconditionally for sub-agents
    def test_stash_push_blocked_for_sub_agent(self, hook):
        """git stash push is blocked unconditionally for sub-agents."""
        payload = make_bash_payload("git stash push")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash" in reason.lower()
        assert "cross-card" in reason.lower() or "parallel" in reason.lower() or "working-tree" in reason.lower() or "working tree" in reason.lower()
        assert "stop" in reason.lower() or "report" in reason.lower()

    # 19. git stash save → DENY unconditionally for sub-agents
    def test_stash_save_blocked_for_sub_agent(self, hook):
        """git stash save is blocked unconditionally for sub-agents."""
        payload = make_bash_payload("git stash save 'WIP changes'")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash" in reason.lower()

    # 20. git stash (bare, no subcommand) → DENY unconditionally for sub-agents
    def test_stash_bare_blocked_for_sub_agent(self, hook):
        """Bare 'git stash' (equivalent to git stash push) is blocked for sub-agents."""
        payload = make_bash_payload("git stash")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash" in reason.lower()

    # 21. git stash --keep-index → DENY unconditionally for sub-agents
    def test_stash_keep_index_blocked_for_sub_agent(self, hook):
        """git stash --keep-index is blocked unconditionally for sub-agents."""
        payload = make_bash_payload("git stash --keep-index")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash" in reason.lower()

    # 22. git stash pop → ALLOW (non-destructive restore, not blocked)
    def test_stash_pop_allowed(self, hook):
        """git stash pop restores working tree from stash — not a push operation, must be allowed."""
        payload = make_bash_payload("git stash pop")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 23. git stash apply → ALLOW (non-destructive restore, not blocked)
    def test_stash_apply_allowed(self, hook):
        """git stash apply restores working tree from stash — not a push operation, must be allowed."""
        payload = make_bash_payload("git stash apply stash@{0}")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 24. git stash list → ALLOW (read-only inspection)
    def test_stash_list_allowed(self, hook):
        """git stash list is a read-only inspection command — must be allowed."""
        payload = make_bash_payload("git stash list")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 25. git stash drop → still DENY (regression — pre-existing block must not break)
    def test_stash_drop_still_blocked(self, hook):
        """Regression: git stash drop was already blocked — verify it stays blocked."""
        payload = make_bash_payload("git stash drop stash@{0}")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash drop" in reason

    # 26. Main thread (no agent_id) + git stash push → ALLOW (staff engineer bypass)
    def test_main_thread_stash_push_allowed(self, hook):
        """Without agent_id, stash push is not blocked — staff engineer may use git stash."""
        payload = make_bash_payload(
            "git stash push",
            agent_id=None,  # No agent_id → main session (staff engineer)
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# Helpers for .kanban/ path guard tests
# ---------------------------------------------------------------------------

def make_edit_payload(file_path: str) -> dict:
    """Build a minimal PreToolUse Edit payload."""
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": "foo",
            "new_string": "bar",
        },
    }


def make_write_payload(file_path: str) -> dict:
    """Build a minimal PreToolUse Write payload."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": "{}",
        },
    }


def make_multiedit_payload(file_path: str) -> dict:
    """Build a minimal PreToolUse MultiEdit payload."""
    return {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": file_path,
            "edits": [],
        },
    }


def make_notebook_edit_payload(notebook_path: str) -> dict:
    """Build a minimal PreToolUse NotebookEdit payload."""
    return {
        "tool_name": "NotebookEdit",
        "tool_input": {
            "notebook_path": notebook_path,
            "cell_type": "code",
            "source": "",
        },
    }


class TestKanbanPathGuard:
    """Tests for the .kanban/ path guard in _check_kanban_path_guard.

    Verifies that direct file writes to .kanban/ are denied, reads are allowed,
    and kanban CLI commands are always allowed.
    """

    # --- Edit ---

    def test_edit_kanban_path_denied(self, hook):
        """Edit on .kanban/doing/123.json must be denied."""
        payload = make_edit_payload(".kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_edit_kanban_nested_denied(self, hook):
        """Edit on a nested .kanban/ path must be denied."""
        payload = make_edit_payload(".kanban/done/456.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_edit_normal_file_allowed(self, hook):
        """Edit on src/foo.py (outside .kanban/) must be allowed."""
        payload = make_edit_payload("src/foo.py")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- Write ---

    def test_write_kanban_path_denied(self, hook):
        """Write on .kanban/.perm-tracking.json must be denied."""
        payload = make_write_payload(".kanban/.perm-tracking.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_write_normal_file_allowed(self, hook):
        """Write on src/config.py (outside .kanban/) must be allowed."""
        payload = make_write_payload("src/config.py")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- MultiEdit ---

    def test_multiedit_kanban_path_denied(self, hook):
        """MultiEdit on .kanban/done/456.json must be denied."""
        payload = make_multiedit_payload(".kanban/done/456.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- NotebookEdit ---

    def test_notebook_edit_kanban_path_denied(self, hook):
        """NotebookEdit on .kanban/whatever.ipynb must be denied."""
        payload = make_notebook_edit_payload(".kanban/whatever.ipynb")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- Bash: mutation patterns → DENY ---

    def test_bash_python_mutation_denied(self, hook):
        """Bash with python3 -c '... .kanban/ ...' must be denied."""
        payload = make_bash_payload("python3 -c 'import json; open(\".kanban/doing/123.json\", \"w\")'")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_sed_inplace_kanban_denied(self, hook):
        """Bash with sed -i on .kanban/ path must be denied."""
        payload = make_bash_payload("sed -i 's/foo/bar/' .kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_redirect_kanban_denied(self, hook):
        """Bash with shell redirection writing to .kanban/ must be denied."""
        payload = make_bash_payload("echo {} > .kanban/file.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_rm_kanban_denied(self, hook):
        """Bash with rm .kanban/doing/123.json must be denied."""
        payload = make_bash_payload("rm .kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- Bash: reads → ALLOW ---

    def test_bash_cat_kanban_allowed(self, hook):
        """Bash with cat .kanban/doing/123.json (read) must be allowed."""
        payload = make_bash_payload("cat .kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- Bash: kanban CLI → ALLOW ---

    def test_bash_kanban_criteria_check_allowed(self, hook):
        """Bash with 'kanban criteria check 123 1' must be allowed."""
        payload = make_bash_payload("kanban criteria check 123 1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_kanban_list_allowed(self, hook):
        """Bash with 'kanban list' must be allowed."""
        payload = make_bash_payload("kanban list")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_kanban_show_allowed(self, hook):
        """kanban show reads from .kanban/ internally — still allowed via CLI allowlist."""
        payload = make_bash_payload("kanban show 42 --session test-session")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- Denial message content ---

    def test_denial_message_includes_kanban_cli_guidance(self, hook):
        """Denial message must include kanban CLI guidance and prohibition text."""
        payload = make_edit_payload(".kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "kanban CLI" in reason or "kanban criteria" in reason
        assert ".kanban/" in reason

    # --- Unit tests for helper functions ---

    def test_is_under_kanban_dir_relative(self, hook):
        """_is_under_kanban_dir: relative .kanban/ path → True."""
        assert hook._is_under_kanban_dir(".kanban/doing/123.json") is True

    def test_is_under_kanban_dir_nested(self, hook):
        """_is_under_kanban_dir: nested .kanban/ component → True."""
        assert hook._is_under_kanban_dir(".kanban/done/456.json") is True

    def test_is_under_kanban_dir_normal_path(self, hook):
        """_is_under_kanban_dir: normal path → False."""
        assert hook._is_under_kanban_dir("src/foo.py") is False

    def test_is_under_kanban_dir_empty(self, hook):
        """_is_under_kanban_dir: empty string → False."""
        assert hook._is_under_kanban_dir("") is False

    def test_is_kanban_cli_command_kanban(self, hook):
        """_is_kanban_cli_command: 'kanban list' → True."""
        assert hook._is_kanban_cli_command("kanban list") is True

    def test_is_kanban_cli_command_kanban_show(self, hook):
        """_is_kanban_cli_command: 'kanban show 42' → True."""
        assert hook._is_kanban_cli_command("kanban show 42") is True

    def test_is_kanban_cli_command_not_kanban(self, hook):
        """_is_kanban_cli_command: 'rm .kanban/foo' → False."""
        assert hook._is_kanban_cli_command("rm .kanban/foo") is False

    def test_is_kanban_cli_command_python_not_kanban(self, hook):
        """_is_kanban_cli_command: python mutation command → False."""
        assert hook._is_kanban_cli_command("python3 -c 'open(\".kanban/x\", \"w\")'") is False

    # --- Allowlist anchor: kanban-prefixed binary NOT allowlisted ---

    def test_is_kanban_cli_command_kanban_prefixed_binary_false(self, hook):
        """_is_kanban_cli_command: 'kanban-foo ...' → False (not the kanban CLI).

        kanban-foo is a different binary. The anchored regex must not match it
        as a kanban CLI command. (Whether the bash call is denied depends on
        whether a deny pattern also fires — e.g. if it redirects to .kanban/.)
        """
        assert hook._is_kanban_cli_command("kanban-foo write .kanban/file.json") is False

    def test_bash_kanban_prefixed_binary_with_redirect_denied(self, hook):
        """Bash with 'kanban-foo write > .kanban/file.json' must be DENIED.

        kanban-foo is not the kanban CLI (allowlist doesn't fire), and the
        shell redirect to .kanban/ matches the deny pattern.
        """
        payload = make_bash_payload("kanban-foo write > .kanban/file.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_nix_shell_p_kanban_denied(self, hook):
        """Bash with 'nix-shell -p kanban -c ...' writing to .kanban/ must be DENIED.

        'kanban' here is a flag argument to nix-shell — not an invocation of the
        kanban CLI. The anchored regex must not allowlist this.
        The command also writes to .kanban/ so it is caught by the redirect deny pattern.
        """
        payload = make_bash_payload("nix-shell -p kanban -c 'echo x > .kanban/foo.json'")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_is_kanban_cli_command_nix_shell_false(self, hook):
        """_is_kanban_cli_command: 'nix-shell -p kanban -c ...' → False."""
        assert hook._is_kanban_cli_command("nix-shell -p kanban -c 'kanban list'") is False

    def test_bash_echo_kanban_allowed(self, hook):
        """Bash with 'echo kanban' must be ALLOWED — no .kanban/ path involved."""
        payload = make_bash_payload("echo kanban")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- Symlink bypass: ln / cp -s → DENY ---

    def test_bash_ln_kanban_denied(self, hook):
        """Bash with 'ln -s real .kanban/symlink' must be DENIED.

        ln creates a symlink (or hard link) that could allow mutation via the
        symlink target. This is a symlink-bypass vector — block it.
        """
        payload = make_bash_payload("ln -s real .kanban/symlink")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_link_kanban_denied(self, hook):
        """Bash with 'link src .kanban/dst' must be DENIED."""
        payload = make_bash_payload("link src .kanban/dst")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_cp_s_kanban_denied(self, hook):
        """Bash with 'cp -s src .kanban/foo' must be DENIED.

        cp -s creates a symbolic link — this is a symlink bypass vector.
        """
        payload = make_bash_payload("cp -s src .kanban/foo")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_cp_symbolic_kanban_denied(self, hook):
        """Bash with 'cp --symbolic src .kanban/foo' must be DENIED."""
        payload = make_bash_payload("cp --symbolic src .kanban/foo")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- jq --argfile is a read, not a write → ALLOW ---

    def test_bash_jq_argfile_kanban_allowed(self, hook):
        """Bash with 'jq --argfile X .kanban/x.json \".\"' must be ALLOWED.

        jq --argfile reads the file as input — it does not mutate it. The
        false-positive deny pattern for jq --argfile has been removed.
        """
        payload = make_bash_payload("jq --argfile X .kanban/x.json '\"$X\"' input.json")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_jq_i_kanban_denied(self, hook):
        """Bash with 'jq -i \".\" .kanban/x.json' must be DENIED.

        jq -i edits the file in place (in-place mutation) — block it.
        """
        payload = make_bash_payload("jq -i \".\" .kanban/x.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- python3 word boundary: no trailing slash → DENY ---

    def test_bash_python3_no_trailing_slash_denied(self, hook):
        """Bash with python3 -c '...' referencing .kanban without trailing slash → DENIED.

        The updated pattern uses \\b instead of trailing / so it catches references
        like open(\".kanban\", \"w\") without a path separator after .kanban.
        """
        payload = make_bash_payload("python3 -c 'import os; os.chdir(\".kanban\")'")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_python3_open_no_trailing_slash_denied(self, hook):
        """Bash with python3 -c 'open(\".kanban/x\",\"w\")' must be DENIED (regression)."""
        payload = make_bash_payload("python3 -c 'open(\".kanban/x\",\"w\")'")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")


# ---------------------------------------------------------------------------
# Tests: agent_launch_pending clear callback
# ---------------------------------------------------------------------------

class TestAgentLaunchPendingClear:
    """Pretool hook calls clear-agent-launch-pending on Agent launch with card reference."""

    def test_clear_agent_launch_pending_called_on_agent_launch(self, hook):
        """Hook calls 'kanban clear-agent-launch-pending <N> --session <s>' on Agent launch."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        called_commands = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list):
                called_commands.append(cmd)
                if cmd[0] == "kanban" and cmd[1] == "show":
                    return KanbanMockResponses.success(stdout=card_xml)
                if cmd[0] == "kanban" and cmd[1] == "clear-agent-launch-pending":
                    return KanbanMockResponses.success()
                if cmd[0] == "kanban" and cmd[1] == "agent":
                    return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)

        # Verify clear-agent-launch-pending was called with correct args
        clear_calls = [
            c for c in called_commands
            if c[0] == "kanban" and c[1] == "clear-agent-launch-pending"
        ]
        assert len(clear_calls) == 1, (
            f"Expected exactly 1 clear-agent-launch-pending call, got {len(clear_calls)}: {clear_calls}"
        )
        clear_cmd = clear_calls[0]
        assert "42" in clear_cmd, f"Expected card number 42 in clear command: {clear_cmd}"
        assert "--session" in clear_cmd, f"Expected --session in clear command: {clear_cmd}"
        assert "test-session" in clear_cmd, f"Expected session in clear command: {clear_cmd}"

    def test_clear_agent_launch_pending_fails_open(self, hook):
        """If clear-agent-launch-pending fails, hook still allows the agent launch."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "clear-agent-launch-pending":
                # Simulate failure
                return KanbanMockResponses.failure(returncode=1, stderr="card not found")
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        # Hook must still allow even if clear-agent-launch-pending fails
        assert_allowed(result)

    def test_clear_agent_launch_pending_not_called_when_no_card_xml(self, hook):
        """If kanban show fails (no card XML), clear-agent-launch-pending is not called."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )

        called_commands = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list):
                called_commands.append(cmd)
                if cmd[0] == "kanban" and cmd[1] == "show":
                    return KanbanMockResponses.failure(returncode=1)
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        # Hook allows (fails open) when show fails
        assert_allowed(result)

        # clear-agent-launch-pending must NOT be called when card XML is unavailable
        clear_calls = [
            c for c in called_commands
            if isinstance(c, list) and c[0] == "kanban" and c[1] == "clear-agent-launch-pending"
        ]
        assert len(clear_calls) == 0, (
            f"clear-agent-launch-pending must not be called when kanban show fails, got: {clear_calls}"
        )

    def test_clear_agent_launch_pending_called_before_agent_update(self, hook):
        """clear-agent-launch-pending is invoked as part of Agent launch processing."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        call_order = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list):
                if cmd[0] == "kanban" and cmd[1] == "show":
                    return KanbanMockResponses.success(stdout=card_xml)
                if cmd[0] == "kanban" and cmd[1] == "clear-agent-launch-pending":
                    call_order.append("clear-agent-launch-pending")
                    return KanbanMockResponses.success()
                if cmd[0] == "kanban" and cmd[1] == "agent":
                    call_order.append("agent")
                    return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("sqlite3.connect", return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
                execute=MagicMock(),
                commit=MagicMock(),
                close=MagicMock(),
            )):
                result = run_hook_main(hook, payload)

        assert_allowed(result)
        assert "clear-agent-launch-pending" in call_order, (
            f"clear-agent-launch-pending must be called during agent launch processing; "
            f"call_order: {call_order}"
        )
