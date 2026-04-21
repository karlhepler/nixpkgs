"""
Tests for modules/claude/git-no-verify-hook.py.

Covered paths:
- git commit --no-verify → blocked
- git commit --no-verify with CLAUDE_NOVERIFY_AUTHORIZED=1 → allowed
- git commit -m "msg" (no bypass flag) → allowed
- git commit -m "message body mentions --no-verify" → NOT blocked (false-positive fix)
- git push --no-verify → blocked
- git push --no-gpg-sign → blocked
- git commit -c commit.gpgsign=false → blocked
- non-git Bash command → allowed
- empty stdin → allowed (fail open)
- malformed JSON → allowed (fail open)
- non-Bash tool → allowed (fail open)
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

_HOOK_PATH = Path(__file__).parent.parent / "git-no-verify-hook.py"


def load_hook():
    """Import git-no-verify-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("git_no_verify_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the git-no-verify hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a JSON payload via monkeypatched stdin / stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, payload: dict | None, env: dict | None = None) -> dict | None:
    """
    Call hook_mod.main() with the given payload dict as stdin JSON.
    Returns the parsed JSON written to stdout, or None if nothing was printed
    (silent exit = allow).
    """
    captured_output: list[str] = []

    def fake_print(val, **kwargs):
        captured_output.append(val)

    raw = json.dumps(payload) if payload is not None else ""
    env_patch = env or {}

    with patch.object(sys, "stdin", io.StringIO(raw)):
        with patch("builtins.print", side_effect=fake_print):
            with patch.dict(os.environ, env_patch, clear=False):
                try:
                    hook_mod.main()
                except SystemExit:
                    pass

    if not captured_output:
        return None
    return json.loads(captured_output[-1])


def make_bash_payload(command: str) -> dict:
    """Build a minimal Bash PreToolUse payload."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "test-session",
    }


# ---------------------------------------------------------------------------
# Helpers to assert decision outcomes
# ---------------------------------------------------------------------------

def assert_blocked(result: dict | None):
    assert result is not None, "Expected a block response, got silent exit (allow)"
    assert result.get("decision") == "block", f"Expected block, got: {result}"


def assert_allowed(result: dict | None):
    assert result is None, f"Expected silent exit (allow), but got output: {result}"


# ---------------------------------------------------------------------------
# Blocked: --no-verify
# ---------------------------------------------------------------------------

class TestNoVerifyBlocked:
    """Commands with --no-verify are blocked."""

    def test_git_commit_no_verify_blocked(self, hook):
        payload = make_bash_payload("git commit --no-verify -m 'skip hooks'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_git_push_no_verify_blocked(self, hook):
        payload = make_bash_payload("git push --no-verify")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_block_reason_mentions_noverify(self, hook):
        payload = make_bash_payload("git commit --no-verify -m 'msg'")
        result = run_hook_main(hook, payload)
        assert result is not None
        reason = result.get("reason", "")
        assert "--no-verify" in reason or "CLAUDE_NOVERIFY_AUTHORIZED" in reason

    def test_git_merge_no_verify_blocked(self, hook):
        payload = make_bash_payload("git merge --no-verify feature-branch")
        result = run_hook_main(hook, payload)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# Blocked: --no-gpg-sign
# ---------------------------------------------------------------------------

class TestNoGpgSignBlocked:
    """Commands with --no-gpg-sign are blocked."""

    def test_git_push_no_gpg_sign_blocked(self, hook):
        payload = make_bash_payload("git push --no-gpg-sign origin main")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_git_commit_no_gpg_sign_blocked(self, hook):
        payload = make_bash_payload("git commit --no-gpg-sign -m 'test'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# Blocked: -c commit.gpgsign=false
# ---------------------------------------------------------------------------

class TestGpgSignFalseBlocked:
    """Commands with -c commit.gpgsign=false are blocked."""

    def test_git_commit_gpgsign_false_blocked(self, hook):
        payload = make_bash_payload("git -c commit.gpgsign=false commit -m 'msg'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_git_commit_gpgsign_false_with_spaces_blocked(self, hook):
        payload = make_bash_payload("git commit -c commit.gpgsign=false -m 'msg'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# Allowed: bypass authorized via env var
# ---------------------------------------------------------------------------

class TestAuthorizedBypass:
    """CLAUDE_NOVERIFY_AUTHORIZED=1 allows bypass flags."""

    def test_no_verify_with_authorized_env_allowed(self, hook):
        payload = make_bash_payload("git commit --no-verify -m 'authorized'")
        # Remove the key first, then set it to 1
        result = run_hook_main(hook, payload, env={"CLAUDE_NOVERIFY_AUTHORIZED": "1"})
        assert_allowed(result)

    def test_no_gpg_sign_with_authorized_env_allowed(self, hook):
        payload = make_bash_payload("git push --no-gpg-sign origin main")
        result = run_hook_main(hook, payload, env={"CLAUDE_NOVERIFY_AUTHORIZED": "1"})
        assert_allowed(result)

    def test_gpgsign_false_with_authorized_env_allowed(self, hook):
        payload = make_bash_payload("git -c commit.gpgsign=false commit -m 'msg'")
        result = run_hook_main(hook, payload, env={"CLAUDE_NOVERIFY_AUTHORIZED": "1"})
        assert_allowed(result)

    def test_authorized_value_0_still_blocks(self, hook):
        """CLAUDE_NOVERIFY_AUTHORIZED=0 does NOT authorize — must be exactly '1'."""
        payload = make_bash_payload("git commit --no-verify -m 'test'")
        result = run_hook_main(hook, payload, env={"CLAUDE_NOVERIFY_AUTHORIZED": "0"})
        assert_blocked(result)


# ---------------------------------------------------------------------------
# Allowed: legitimate git commands (no bypass flags)
# ---------------------------------------------------------------------------

class TestLegitimateGitCommands:
    """Normal git commands without bypass flags are allowed."""

    def test_git_commit_with_message_allowed(self, hook):
        payload = make_bash_payload("git commit -m 'normal commit'")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_git_push_without_flags_allowed(self, hook):
        payload = make_bash_payload("git push origin main")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_git_status_allowed(self, hook):
        payload = make_bash_payload("git status")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_git_diff_allowed(self, hook):
        payload = make_bash_payload("git diff HEAD~1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_git_add_allowed(self, hook):
        payload = make_bash_payload("git add -A")
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# Allowed: bypass-flag strings in commit message body (false-positive regression)
# ---------------------------------------------------------------------------

class TestBypassStringInMessageBody:
    """
    Bypass-flag strings appearing only inside a -m message value must NOT block.
    Regression tests for the false-positive bug fixed by shlex tokenization.
    """

    def test_no_verify_in_message_body_allowed(self, hook):
        """The string --no-verify in the commit message body is NOT a bypass flag."""
        payload = make_bash_payload(
            'git commit -m "this commit skips --no-verify bypass pattern"'
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_no_gpg_sign_in_message_body_allowed(self, hook):
        """The string --no-gpg-sign in the commit message body is NOT a bypass flag."""
        payload = make_bash_payload(
            'git commit -m "do not use --no-gpg-sign in production"'
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_gpgsign_false_in_message_body_allowed(self, hook):
        """The string commit.gpgsign=false in the commit message body is NOT a bypass flag."""
        payload = make_bash_payload(
            "git commit -m 'message mentions commit.gpgsign=false configuration'"
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_no_verify_in_long_message_flag_form_allowed(self, hook):
        """--message flag form: bypass string in message value is NOT a bypass flag."""
        payload = make_bash_payload(
            'git commit --message "chore: document --no-verify hook bypass"'
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_real_bypass_after_message_still_blocked(self, hook):
        """Even when a message contains a bypass string, an actual bypass flag still blocks."""
        payload = make_bash_payload(
            'git commit -m "remove --no-verify from CI" --no-verify'
        )
        result = run_hook_main(hook, payload)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# Allowed: non-git commands
# ---------------------------------------------------------------------------

class TestNonGitCommands:
    """Non-git Bash commands are always allowed."""

    def test_npm_test_allowed(self, hook):
        payload = make_bash_payload("npm test --no-verify")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_echo_no_verify_allowed(self, hook):
        """echo containing --no-verify text is allowed — not a git command."""
        payload = make_bash_payload("echo 'use --no-verify to skip hooks'")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_pytest_allowed(self, hook):
        payload = make_bash_payload("pytest modules/claude/tests/ -x")
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# Allowed: non-Bash tool
# ---------------------------------------------------------------------------

class TestNonBashTool:
    """Non-Bash tool_name → hook is silent (allowed)."""

    def test_read_tool_allowed(self, hook):
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/file.py"},
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_edit_tool_with_git_content_allowed(self, hook):
        """Edit tool with git --no-verify in content is allowed — only Bash is inspected."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"command": "git commit --no-verify -m 'test'"},
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# Fail-open: error conditions
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Error conditions result in silent exit (allow), never block."""

    def test_empty_stdin_allowed(self, hook):
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

    def test_malformed_json_allowed(self, hook):
        captured = []

        def fake_print(val, **kwargs):
            captured.append(val)

        with patch.object(sys, "stdin", io.StringIO("{not valid json")):
            with patch("builtins.print", side_effect=fake_print):
                try:
                    hook.main()
                except SystemExit:
                    pass

        assert not captured, f"Expected no output for malformed JSON, got: {captured}"

    def test_missing_command_field_allowed(self, hook):
        """Payload with no command field → allowed (treated as empty command)."""
        payload = {"tool_name": "Bash", "tool_input": {}}
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# Block response structure
# ---------------------------------------------------------------------------

class TestBlockResponseStructure:
    """Verify the block response is structurally correct."""

    def test_block_response_has_decision_field(self, hook):
        payload = make_bash_payload("git commit --no-verify -m 'test'")
        result = run_hook_main(hook, payload)
        assert result is not None
        assert "decision" in result
        assert result["decision"] == "block"

    def test_block_response_has_reason_field(self, hook):
        payload = make_bash_payload("git commit --no-verify -m 'test'")
        result = run_hook_main(hook, payload)
        assert result is not None
        assert "reason" in result
        assert len(result["reason"]) > 0

    def test_block_reason_mentions_opt_in_mechanism(self, hook):
        """Block reason should tell the agent how to get authorized."""
        payload = make_bash_payload("git push --no-verify")
        result = run_hook_main(hook, payload)
        assert result is not None
        reason = result.get("reason", "")
        assert "CLAUDE_NOVERIFY_AUTHORIZED" in reason
