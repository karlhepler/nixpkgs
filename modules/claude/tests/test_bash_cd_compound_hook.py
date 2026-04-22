"""
Tests for modules/claude/bash-cd-compound-hook.py.

Covered paths:
- cd /path && cmd → blocked
- cd /path; cmd → blocked
- cd /path ; cmd → blocked
- cd /path ;ls → blocked (no space after semicolon)
- cd - && cmd → blocked
- cd && cmd → blocked (bare cd)
- cd ~ && cmd → blocked
- cd ~/path && cmd → blocked
- cd $VAR && cmd → blocked
- cd /a && cd /b && cmd → blocked (first triggers)
- multiline with cd compound on second line → blocked
- (cd /path && cmd) → allowed (subshell)
- bash -c 'cd /path && cmd' → allowed (quoted argument)
- echo 'cd /path && something' → allowed (cd inside string)
- find . -name 'cd' → allowed (cd as value)
- pcd something && cmd → allowed (not 'cd')
- ccd foo && cmd → allowed (not 'cd')
- cmd && cd /path → allowed (trailing cd, not compound)
- cd /path (no compound) → allowed
- rg "pattern" /path (no cd) → allowed
- non-Bash tool with cd in content → allowed
- empty stdin → allowed (fail open)
- malformed JSON → allowed (fail open)
- missing command field → allowed (fail open)
- unterminated quote → allowed (fail open)
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

_HOOK_PATH = Path(__file__).parent.parent / "bash-cd-compound-hook.py"


def load_hook():
    """Import bash-cd-compound-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("bash_cd_compound_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the bash-cd-compound hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a JSON payload via monkeypatched stdin / stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, payload, env=None) -> dict | None:
    """
    Call hook_mod.main() with the given payload as stdin JSON.
    Returns the parsed JSON written to stdout, or None if nothing was printed
    (silent exit = allow).

    If payload is None, sends empty string as stdin.
    If payload is a string, sends it raw (for malformed JSON tests).
    """
    captured_output: list[str] = []

    def fake_print(val, **kwargs):
        captured_output.append(val)

    if payload is None:
        raw = ""
    elif isinstance(payload, str):
        raw = payload
    else:
        raw = json.dumps(payload)

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
# TestCdCompoundBlocked — detection for all blocked forms
# ---------------------------------------------------------------------------

class TestCdCompoundBlocked:
    """cd-compound patterns that must be blocked."""

    def test_cd_ampersand_ampersand_blocked(self, hook):
        """cd /path && rg 'pattern' — classic anti-pattern."""
        payload = make_bash_payload('cd /path && rg "pattern"')
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_semicolon_blocked(self, hook):
        """cd /path; ls — semicolon compound form."""
        payload = make_bash_payload("cd /path; ls")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_space_semicolon_blocked(self, hook):
        """cd /path ; ls — space before semicolon."""
        payload = make_bash_payload("cd /path ; ls")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_semicolon_no_space_after_blocked(self, hook):
        """cd /path ;ls — no space after semicolon."""
        payload = make_bash_payload("cd /path ;ls")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_dash_compound_blocked(self, hook):
        """cd - && cmd — toggle-back cd is still a persistent state change."""
        payload = make_bash_payload("cd - && cmd")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_bare_compound_blocked(self, hook):
        """cd && ls — bare cd (go home) is still a persistent state change."""
        payload = make_bash_payload("cd && ls")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_tilde_compound_blocked(self, hook):
        """cd ~ && pwd — tilde home shorthand."""
        payload = make_bash_payload("cd ~ && pwd")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_tilde_path_compound_blocked(self, hook):
        """cd ~/some/path && rg 'x' — tilde with subpath."""
        payload = make_bash_payload('cd ~/some/path && rg "x"')
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_var_compound_blocked(self, hook):
        """cd $VAR && cmd — variable expansion, still top-level cd."""
        payload = make_bash_payload("cd $VAR && cmd")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_multiple_segments_blocked(self, hook):
        """cd /a && cd /b && cmd — multiple cd compounds, first triggers block."""
        payload = make_bash_payload("cd /a && cd /b && cmd")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_cd_compound_in_multiline_blocked(self, hook):
        """Multiline command: second line has cd compound."""
        payload = make_bash_payload('git status\ncd /path && rg "x"')
        result = run_hook_main(hook, payload)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# TestCdCompoundAllowed — false-positive avoidance
# ---------------------------------------------------------------------------

class TestCdCompoundAllowed:
    """Commands that must NOT be blocked."""

    def test_subshell_allowed(self, hook):
        """(cd /path && cmd) — subshell: cd does not persist to next Bash call."""
        payload = make_bash_payload("(cd /path && cmd)")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_subshell_semicolon_allowed(self, hook):
        """(cd /path; cmd) — subshell with semicolon."""
        payload = make_bash_payload("(cd /path; cmd)")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_c_quoted_allowed(self, hook):
        """bash -c 'cd /path && cmd' — cd is a quoted argument, not top-level."""
        payload = make_bash_payload("bash -c 'cd /path && cmd'")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_echo_quoted_cd_allowed(self, hook):
        """echo 'cd /path && something' — cd inside quoted string."""
        payload = make_bash_payload("echo 'cd /path && something'")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_find_name_cd_allowed(self, hook):
        """find . -name 'cd' — cd is a value, not a command token."""
        payload = make_bash_payload("find . -name 'cd'")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_pcd_compound_allowed(self, hook):
        """pcd something && cmd — 'pcd' is not 'cd' (word boundary)."""
        payload = make_bash_payload("pcd something && cmd")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_ccd_compound_allowed(self, hook):
        """ccd foo && cmd — 'ccd' is not 'cd' (word boundary)."""
        payload = make_bash_payload("ccd foo && cmd")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_trailing_cd_allowed(self, hook):
        """cmd && cd /path — trailing cd (not followed by more commands) is fine."""
        payload = make_bash_payload("cmd && cd /path")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bare_cd_only_allowed(self, hook):
        """cd /path (no compound operator) — standalone cd is fine."""
        payload = make_bash_payload("cd /path")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_no_cd_at_all_allowed(self, hook):
        """rg 'pattern' /path — no cd at all."""
        payload = make_bash_payload('rg "pattern" /path')
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_non_bash_tool_allowed(self, hook):
        """Non-Bash tool_name with cd in content — hook only inspects Bash."""
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/file.py"},
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_empty_stdin_allowed(self, hook):
        """Empty stdin — fail open."""
        result = run_hook_main(hook, None)
        assert_allowed(result)

    def test_malformed_json_allowed(self, hook):
        """Invalid JSON — fail open."""
        result = run_hook_main(hook, "{not valid json")
        assert_allowed(result)

    def test_missing_command_field_allowed(self, hook):
        """Payload with no command field — fail open (treated as empty command)."""
        payload = {"tool_name": "Bash", "tool_input": {}}
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestRejectionMessageFormat — message content verification
# ---------------------------------------------------------------------------

class TestRejectionMessageFormat:
    """Verify the block response content is correct."""

    def test_block_response_has_decision_field(self, hook):
        """Blocked command produces a response with decision='block'."""
        payload = make_bash_payload("cd /path && cmd")
        result = run_hook_main(hook, payload)
        assert result is not None
        assert result.get("decision") == "block"

    def test_block_response_has_reason_field(self, hook):
        """Blocked command response has a non-empty reason field."""
        payload = make_bash_payload("cd /path && cmd")
        result = run_hook_main(hook, payload)
        assert result is not None
        assert "reason" in result
        assert len(result["reason"]) > 0

    def test_reason_mentions_shell_state_persists(self, hook):
        """Reason explains that shell state persists between Bash calls."""
        payload = make_bash_payload("cd /path && cmd")
        result = run_hook_main(hook, payload)
        assert result is not None
        reason = result.get("reason", "")
        assert "shell state persists" in reason.lower() or "persists" in reason.lower()

    def test_reason_mentions_subshell_escape_valve(self, hook):
        """Reason mentions the subshell (cd X && cmd) escape valve."""
        payload = make_bash_payload("cd /path && cmd")
        result = run_hook_main(hook, payload)
        assert result is not None
        reason = result.get("reason", "")
        assert "subshell" in reason.lower() or "(cd" in reason

    def test_reason_mentions_no_bypass(self, hook):
        """Reason informs the agent there is no bypass mechanism."""
        payload = make_bash_payload("cd /path && cmd")
        result = run_hook_main(hook, payload)
        assert result is not None
        reason = result.get("reason", "")
        assert "no bypass" in reason.lower() or "hard block" in reason.lower()


# ---------------------------------------------------------------------------
# TestFailOpen — error condition handling
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Error conditions result in silent exit (allow), never block."""

    def test_empty_stdin_silent_exit(self, hook):
        """Empty stdin → no output, exits cleanly."""
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

    def test_malformed_json_silent_exit(self, hook):
        """Bad JSON → no output."""
        captured = []

        def fake_print(val, **kwargs):
            captured.append(val)

        with patch.object(sys, "stdin", io.StringIO("{bad json here")):
            with patch("builtins.print", side_effect=fake_print):
                try:
                    hook.main()
                except SystemExit:
                    pass

        assert not captured, f"Expected no output for malformed JSON, got: {captured}"

    def test_non_bash_tool_silent_exit(self, hook):
        """tool_name='Write' → no output (hook is silent for non-Bash tools)."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/test.txt", "content": "cd /path && ls"},
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_command_with_unterminated_quote_allowed(self, hook):
        """cd /path && "unterminated — shlex error → fail open (allow)."""
        payload = make_bash_payload('cd /path && "unterminated')
        result = run_hook_main(hook, payload)
        assert_allowed(result)
