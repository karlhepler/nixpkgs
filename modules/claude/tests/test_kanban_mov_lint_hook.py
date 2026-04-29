"""
Tests for modules/claude/kanban-mov-lint-hook.py.

Covered paths:
- Non-Bash tool call → allow
- Bash command without 'kanban do/todo --file' → allow
- File path doesn't exist → allow (let kanban CLI handle)
- File path exists but is invalid JSON → allow (let kanban CLI handle)
- JSON with no mov_commands field → allow
- JSON with clean mov_commands (no banned patterns) → allow
- JSON with rg -qiE in cmd → deny with actionable message
- JSON with rg -E (no other flags) in cmd → deny
- JSON with --no-verify in cmd → deny
- JSON with --no-gpg-sign in cmd → deny
- JSON with git commit -n in cmd → deny
- JSON with HUSKY=0 in cmd → deny
- JSON with HUSKY_SKIP_HOOKS=1 in cmd → deny
- Array-of-cards form → scans all cards
- rg -qi -e 'foo' (lowercase -e) → allow (NOT denied)
- grep -E (non-rg tool) → allow (NOT denied)
- rg -e (lowercase, no capital E) → allow
- Empty stdin → allow (fail open)
- Malformed JSON payload → allow (fail open)
- Malformed card JSON with hook-skip literal → block (fail closed)
- Malformed card JSON without hook-skip literal → allow (fail open)
- ANSI escape sequences in cmd → sanitized in denial message
- Path outside cwd → allow (fail open, path containment)
- git commit -m 'message with -n word' → allow (shlex false-positive guard)
- mov_commands array index in denial message (mov_idx)
- Backslash-pipe detection: rg/grep/sed/awk with \\| (should block); echo, bare pipe, double-escape, grep -P (should allow)
- rg -c absence idiom: test $(rg -c ...) -le 0 and bracket/grep/quoted variants (should block); ! rg -q, rg -c -ge 5, bare rg -c (should allow)
- rg -c absence idiom: backtick form, [[ double-bracket form, -lt 0/1/2, -le 1 variants (should block)
- Empty mov_commands: criterion with [] (should block); one valid entry (should allow)
- Missing mov_commands key: now blocked (policy change — missing key is same as empty list)
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "kanban-mov-lint-hook.py"


def load_hook():
    """Import kanban-mov-lint-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_mov_lint_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the kanban-mov-lint hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a JSON payload via monkeypatched stdin / stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, payload, env=None) -> "dict | None":
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


def make_card_json(cmd: str) -> dict:
    """Build a minimal card JSON object with a single criterion and one mov_command."""
    return {
        "action": "Test action",
        "intent": "Test intent",
        "criteria": [
            {
                "description": "Test criterion",
                "mov_commands": [
                    {"cmd": cmd, "timeout": 10},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Helpers to assert decision outcomes
# ---------------------------------------------------------------------------

def assert_blocked(result: "dict | None"):
    assert result is not None, "Expected a block response, got silent exit (allow)"
    assert result.get("decision") == "block", f"Expected block, got: {result}"


def assert_allowed(result: "dict | None"):
    assert result is None, f"Expected silent exit (allow), but got output: {result}"


# ---------------------------------------------------------------------------
# Helper: write a temp JSON file and run the hook
# ---------------------------------------------------------------------------

def run_with_temp_file(hook_mod, card_data, command_template: str = "kanban do --file {}") -> "dict | None":
    """
    Write card_data as JSON to a temp file inside the current directory, then run the hook with a
    'kanban do --file <path>' command pointing to that file.

    Files are created inside cwd so they pass the path-containment check.
    command_template: format string receiving the absolute file path.
    """
    cwd = os.getcwd()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=cwd, delete=False) as f:
        json.dump(card_data, f)
        tmp_path = os.path.abspath(f.name)
    try:
        command = command_template.format(tmp_path)
        payload = make_bash_payload(command)
        return run_hook_main(hook_mod, payload)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# TestNonBashTools — hook must be silent for non-Bash tools
# ---------------------------------------------------------------------------

class TestNonBashTools:
    """Hook only inspects Bash tool calls. All other tools pass through silently."""

    def test_edit_tool_allowed(self, hook):
        """Edit tool calls are not inspected."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/some/card.json", "old_string": "x", "new_string": "y"},
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_write_tool_allowed(self, hook):
        """Write tool calls are not inspected."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/some/card.json", "content": "{}"},
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_read_tool_allowed(self, hook):
        """Read tool calls are not inspected."""
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/card.json"},
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_agent_tool_allowed(self, hook):
        """Agent tool calls are not inspected."""
        payload = {
            "tool_name": "Agent",
            "tool_input": {"prompt": "kanban do --file card.json"},
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestCommandDetection — only intercept kanban do/todo --file
# ---------------------------------------------------------------------------

class TestCommandDetection:
    """Only 'kanban do --file' and 'kanban todo --file' should be intercepted."""

    def test_kanban_list_allowed(self, hook):
        """kanban list is not a do/todo command."""
        payload = make_bash_payload("kanban list")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_kanban_show_allowed(self, hook):
        """kanban show is not a do/todo command."""
        payload = make_bash_payload("kanban show 42")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_kanban_criteria_check_allowed(self, hook):
        """kanban criteria check is not a do/todo command."""
        payload = make_bash_payload("kanban criteria check 1563 1 --session gold-drift")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_rg_command_allowed(self, hook):
        """A plain rg command (not kanban) is not intercepted."""
        payload = make_bash_payload("rg -qiE 'foo' some-file.json")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_kanban_do_without_file_flag_allowed(self, hook):
        """kanban do without --file is allowed (no file to inspect)."""
        payload = make_bash_payload("kanban do 'Some action'")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_kanban_todo_without_file_flag_allowed(self, hook):
        """kanban todo without --file is allowed."""
        payload = make_bash_payload("kanban todo 'Some action'")
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestFileHandling — fail-open for missing or invalid files
# ---------------------------------------------------------------------------

class TestFileHandling:
    """Non-existent or invalid JSON files cause fail-open (allow)."""

    def test_nonexistent_file_allowed(self, hook):
        """If the --file path doesn't exist, allow (let kanban CLI handle it)."""
        payload = make_bash_payload("kanban do --file /tmp/does-not-exist-12345678.json")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_invalid_json_allowed(self, hook):
        """If the file contains invalid JSON with no hook-skip content, allow."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=".", delete=False) as f:
            f.write("{not valid json}")
            tmp_path = f.name
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            assert_allowed(result)
        finally:
            os.unlink(tmp_path)

    def test_empty_file_allowed(self, hook):
        """If the file is empty (not valid JSON), allow."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=".", delete=False) as f:
            f.write("")
            tmp_path = f.name
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            assert_allowed(result)
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# TestCleanCards — cards without banned patterns are allowed
# ---------------------------------------------------------------------------

class TestCleanCards:
    """Cards with no banned MoV patterns pass through silently."""

    def test_no_criteria_allowed(self, hook):
        """Card with no criteria field is allowed."""
        card = {"action": "Do something", "intent": "Why"}
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_no_mov_commands_blocked(self, hook):
        """Criterion with no mov_commands key is now blocked (policy change).

        Previously this was allowed (fail-open). Since a missing mov_commands key
        is semantically equivalent to an empty list, it is now rejected at creation
        time. See TestEmptyMovCommands for comprehensive coverage of this policy.
        """
        card = {
            "action": "Do something",
            "criteria": [
                {"description": "Some check"},
            ],
        }
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_clean_rg_command_allowed(self, hook):
        """rg -qi 'pattern' (no capital E) is allowed."""
        card = make_card_json("rg -qi 'verdict|approve' some-file.py")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_clean_rg_with_file_flag_allowed(self, hook):
        """rg -qi 'pattern' file is allowed."""
        card = make_card_json("rg -qi 'banned.{0,20}pattern' modules/claude/kanban-mov-lint-hook.py")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_rg_fixed_string_allowed(self, hook):
        """rg -qF 'literal' is allowed (no banned flags)."""
        card = make_card_json("rg -qF -- 'mov_commands' modules/claude/kanban-mov-lint-hook.py")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_git_commit_normal_allowed(self, hook):
        """Normal git commit (no bypass flags) is allowed."""
        card = make_card_json("git commit -m 'feat: add new feature'")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_test_command_allowed(self, hook):
        """test -f command is allowed."""
        card = make_card_json("test -f modules/claude/kanban-mov-lint-hook.py")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_pytest_command_allowed(self, hook):
        """pytest command is allowed."""
        card = make_card_json("pytest modules/claude/tests/test_kanban_mov_lint_hook.py -x --tb=short -q")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestBannedRgEVariants — rg with capital -E flag
# ---------------------------------------------------------------------------

class TestBannedRgEVariants:
    """Any rg invocation with a capital -E in the flag bundle must be denied."""

    def test_rg_qiE_denied(self, hook):
        """rg -qiE is the canonical banned pattern (case from CLAUDE.md)."""
        card = make_card_json("rg -qiE 'verdict|approve|reject|recommend'")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_E_alone_denied(self, hook):
        """rg -E (no other flags) is also banned."""
        card = make_card_json("rg -E 'some pattern' file.txt")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_qE_denied(self, hook):
        """rg -qE is banned."""
        card = make_card_json("rg -qE 'pattern' file.txt")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_iE_denied(self, hook):
        """rg -iE is banned."""
        card = make_card_json("rg -iE 'pattern' file.txt")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_qEi_denied(self, hook):
        """rg -qEi (E before i) is banned."""
        card = make_card_json("rg -qEi 'pattern' file.txt")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_EI_denied(self, hook):
        """rg -EI is banned (capital E with capital I)."""
        card = make_card_json("rg -EI 'pattern' file.txt")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_qi_lowercase_e_allowed(self, hook):
        """rg -qi -e 'foo' (lowercase -e) must NOT be denied."""
        card = make_card_json("rg -qi -e 'foo' file.txt")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_grep_E_not_denied(self, hook):
        """grep -E is a different tool — NOT covered by this hook (scope is strictly rg)."""
        card = make_card_json("grep -E 'pattern' file.txt")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_rg_lowercase_e_not_denied(self, hook):
        """rg -e 'pattern' (lowercase -e only) must NOT be denied."""
        card = make_card_json("rg -e 'some pattern' file.txt")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestBannedHookSkipFlags — no-verify and hook bypass patterns
# ---------------------------------------------------------------------------

class TestBannedHookSkipFlags:
    """Hook-skip flags in MoV commands must be denied."""

    def test_no_verify_in_cmd_denied(self, hook):
        """--no-verify in a MoV cmd is banned."""
        card = make_card_json("git commit --no-verify -m 'skip hooks'")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_no_gpg_sign_in_cmd_denied(self, hook):
        """--no-gpg-sign in a MoV cmd is banned."""
        card = make_card_json("git push --no-gpg-sign")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_git_commit_n_flag_denied(self, hook):
        """git commit -n (short form of --no-verify) is banned."""
        card = make_card_json("git commit -n -m 'skip hooks short form'")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_husky_zero_denied(self, hook):
        """HUSKY=0 in a MoV cmd is banned."""
        card = make_card_json("HUSKY=0 git commit -m 'skip husky'")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_husky_skip_hooks_denied(self, hook):
        """HUSKY_SKIP_HOOKS=1 in a MoV cmd is banned."""
        card = make_card_json("HUSKY_SKIP_HOOKS=1 git push")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_git_commit_n_word_in_message_allowed(self, hook):
        """git commit -m 'message with -n word' must NOT be blocked (shlex false-positive guard).

        The -n appears inside the commit message value, not as a flag.
        This is the negative test for the false-positive identified in AI Expert Finding 1.
        """
        card = make_card_json("git commit -m '-n items were processed'")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_git_commit_n_word_in_message_variant_allowed(self, hook):
        """git commit -m 'n items' should also be allowed (n as a word in message)."""
        card = make_card_json("git commit -m 'processed -n items total'")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestBackslashPipeDetection — backslash-pipe alternation trap detection
# ---------------------------------------------------------------------------

class TestBackslashPipeDetection:
    """Backslash-pipe in regex-context tools must be denied; safe patterns must be allowed."""

    def test_rg_backslash_pipe_denied(self, hook):
        """rg '\\|' file — primary positive case: backslash-pipe in rg must be blocked."""
        card = make_card_json(r"rg '\|' file")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_double_escape_pipe_allowed(self, hook):
        """rg '\\\\|' file — double-escape (two backslashes + pipe) must NOT be blocked.

        Two backslashes before pipe is a legitimate escape: the intent is to match
        a literal backslash character. The detection must not fire here.
        """
        card = make_card_json(r"rg '\\|' file")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_echo_backslash_pipe_allowed(self, hook):
        """echo 'foo\\|bar' — no regex tool present, must NOT be blocked."""
        card = make_card_json(r"echo 'foo\|bar'")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_grep_backslash_pipe_denied(self, hook):
        """grep '\\|' file — grep positive case: must be blocked."""
        card = make_card_json(r"grep '\|' file")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_sed_backslash_pipe_denied(self, hook):
        """sed 's/foo\\|bar/baz/' — sed positive case: must be blocked."""
        card = make_card_json(r"sed 's/foo\|bar/baz/'")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_awk_backslash_pipe_denied(self, hook):
        """awk '/foo\\|bar/' — awk positive case: must be blocked."""
        card = make_card_json(r"awk '/foo\|bar/'")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_bare_pipe_alternation_allowed(self, hook):
        """rg 'foo|bar' file — bare-pipe alternation with NO backslash: must NOT be blocked."""
        card = make_card_json("rg 'foo|bar' file")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_grep_pcre_short_flag_allowed(self, hook):
        """grep -P '\\|' file — PCRE mode makes \\| valid alternation: must NOT be blocked."""
        card = make_card_json(r"grep -P '\|' file")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_grep_perl_regexp_long_flag_allowed(self, hook):
        """grep --perl-regexp '\\|' file — long-form PCRE flag: must NOT be blocked."""
        card = make_card_json(r"grep --perl-regexp '\|' file")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_grep_pcre_combined_flags_allowed(self, hook):
        """grep -i -P '\\|' file — PCRE flag combined with other flags: must NOT be blocked."""
        card = make_card_json(r"grep -i -P '\|' file")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_grep_no_pcre_backslash_pipe_denied(self, hook):
        """grep '\\|' file without -P — BRE mode: must be blocked."""
        card = make_card_json(r"grep '\|' file")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# TestRgCountAbsencePattern — rg/grep -c absence-via-count idiom detection
# ---------------------------------------------------------------------------

class TestRgCountAbsencePattern:
    """test $(rg -c ...) -le N idiom must be denied; non-absence rg -c usage must be allowed."""

    # --- Positive cases (must block) ---

    def test_test_rg_c_le_0_denied(self, hook):
        """test $(rg -c 'pat' file) -le 0 — canonical blocked case."""
        card = make_card_json("test $(rg -c 'pattern' file.py) -le 0")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_bracket_rg_c_le_0_denied(self, hook):
        """[ $(rg -c 'pat' file) -le 0 ] — bracket form must be blocked."""
        card = make_card_json("[ $(rg -c 'pattern' file.py) -le 0 ]")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_test_rg_c_eq_0_denied(self, hook):
        """test $(rg -c 'pat' file) -eq 0 — -eq 0 variant must be blocked."""
        card = make_card_json("test $(rg -c 'pattern' file.py) -eq 0")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_test_rg_c_quoted_substitution_denied(self, hook):
        """test \"$(rg -c 'pat' file)\" -le 0 — quoted command substitution must be blocked."""
        card = make_card_json('test "$(rg -c \'pattern\' file.py)" -le 0')
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_test_grep_c_le_0_denied(self, hook):
        """test $(grep -c 'pat' file) -le 0 — grep -c variant must be blocked."""
        card = make_card_json("test $(grep -c 'pattern' file.py) -le 0")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_bracket_grep_c_eq_0_denied(self, hook):
        """[ $(grep -c 'pat' file) -eq 0 ] — bracket + grep -c variant must be blocked."""
        card = make_card_json("[ $(grep -c 'pattern' file.py) -eq 0 ]")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_backtick_rg_c_le_0_denied(self, hook):
        """test `rg -c 'pat' file` -le 0 — legacy backtick form must be blocked.

        The backtick command substitution is equally fragile: when rg -c finds
        zero matches it emits no stdout, producing empty expansion and exit 2.
        """
        card = make_card_json("test `rg -c 'pattern' file.py` -le 0")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_backtick_grep_c_eq_0_denied(self, hook):
        """test `grep -c 'pat' file` -eq 0 — backtick form with grep must be blocked."""
        card = make_card_json("test `grep -c 'pattern' file.py` -eq 0")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_double_bracket_rg_c_le_0_denied(self, hook):
        """[[ $(rg -c 'pat' file) -le 0 ]] — bash double-bracket form must be blocked."""
        card = make_card_json("[[ $(rg -c 'pattern' file.py) -le 0 ]]")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_c_lt_0_denied(self, hook):
        """-lt 0 variant — nonsensical but structurally equivalent; must be blocked."""
        card = make_card_json("test $(rg -c 'pattern' file.py) -lt 0")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_c_lt_1_denied(self, hook):
        """-lt 1 variant — equivalent to -eq 0 for non-negative counts; must be blocked."""
        card = make_card_json("test $(rg -c 'pattern' file.py) -lt 1")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_c_le_1_denied(self, hook):
        """-le 1 variant — 'at most one' threshold used as absence proxy; must be blocked."""
        card = make_card_json("test $(rg -c 'pattern' file.py) -le 1")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_rg_c_lt_2_denied(self, hook):
        """-lt 2 variant — 'less than 2' used as absence proxy; must be blocked."""
        card = make_card_json("test $(rg -c 'pattern' file.py) -lt 2")
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    # --- Negative cases (must allow) ---

    def test_negated_quiet_match_allowed(self, hook):
        """! rg -q 'pattern' file — correct absence idiom must NOT be blocked."""
        card = make_card_json("! rg -q 'pattern' file.py")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_rg_c_ge_5_allowed(self, hook):
        """test $(rg -c X) -ge 5 — non-absence rg -c use (checking presence count) must be allowed."""
        card = make_card_json("test $(rg -c 'TODO' src/) -ge 5")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_rg_c_no_test_prefix_allowed(self, hook):
        """rg -c 'pattern' file without test/[ prefix — plain count, not fragile idiom."""
        card = make_card_json("rg -c 'pattern' file.py")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_rg_count_in_echo_allowed(self, hook):
        """echo $(rg -c 'pat' file) — no test/[ prefix, must not be blocked."""
        card = make_card_json("echo $(rg -c 'pattern' file.py)")
        result = run_with_temp_file(hook, card)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestEmptyMovCommands — empty/missing mov_commands rejection at creation time
# ---------------------------------------------------------------------------

class TestEmptyMovCommands:
    """Criteria with empty or missing mov_commands must be rejected at creation time.

    Policy note: the behavior here is a deliberate inversion from the original
    design where empty mov_commands was allowed (fail-open). Both mov_commands: []
    and a missing mov_commands key are now blocked because both represent the same
    intent ('no programmatic check') and will always fail when kanban criteria check
    runs. Blocking at creation time provides earlier feedback.
    """

    def test_empty_mov_commands_blocked(self, hook):
        """A criterion with mov_commands: [] must be blocked."""
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "criteria": [
                {
                    "description": "Test criterion",
                    "mov_commands": [],
                }
            ],
        }
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_empty_mov_commands_second_criterion_blocked(self, hook):
        """Empty mov_commands on the second criterion must be blocked."""
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "criteria": [
                {
                    "description": "First criterion (clean)",
                    "mov_commands": [
                        {"cmd": "rg -qi 'pattern' file.py", "timeout": 10},
                    ],
                },
                {
                    "description": "Second criterion (empty movs)",
                    "mov_commands": [],
                },
            ],
        }
        result = run_with_temp_file(hook, card)
        assert_blocked(result)

    def test_denial_reason_mentions_empty_mov_commands(self, hook):
        """Denial reason for empty mov_commands criterion is actionable."""
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "criteria": [
                {
                    "description": "Test criterion",
                    "mov_commands": [],
                }
            ],
        }
        result = run_with_temp_file(hook, card)
        assert result is not None
        reason = result.get("reason", "")
        assert "mov_commands" in reason.lower(), f"Reason should mention mov_commands: {reason}"

    def test_one_cmd_entry_not_blocked(self, hook):
        """A criterion with one valid mov_commands entry must NOT be blocked."""
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "criteria": [
                {
                    "description": "Test criterion",
                    "mov_commands": [
                        {"cmd": "rg -qi 'pattern' file.py", "timeout": 10},
                    ],
                }
            ],
        }
        result = run_with_temp_file(hook, card)
        assert_allowed(result)

    def test_missing_mov_commands_key_blocked(self, hook):
        """A criterion with no mov_commands key at all must be BLOCKED.

        Policy change (deliberate): a missing key is semantically equivalent to
        an empty list — both represent 'no programmatic check'. The SubagentStop
        hook auto-fails both at check time, so creating such a card is always
        wasted effort. The lint hook now rejects both forms at creation time.

        (Previously this was test_missing_mov_commands_key_not_blocked which
        validated fail-open behavior. That policy was inverted by #1648.)
        """
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "criteria": [
                {
                    "description": "Test criterion without mov_commands key",
                }
            ],
        }
        result = run_with_temp_file(hook, card)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# TestDenialMessageContent — actionable error messages
# ---------------------------------------------------------------------------

class TestDenialMessageContent:
    """Denial messages must be actionable and contain required information."""

    def test_denial_has_decision_block(self, hook):
        """Denial response has decision='block'."""
        card = make_card_json("rg -qiE 'foo'")
        result = run_with_temp_file(hook, card)
        assert result is not None
        assert result.get("decision") == "block"

    def test_denial_has_reason(self, hook):
        """Denial response has non-empty reason."""
        card = make_card_json("rg -qiE 'foo'")
        result = run_with_temp_file(hook, card)
        assert result is not None
        assert "reason" in result
        assert len(result["reason"]) > 0

    def test_denial_reason_mentions_file_path(self, hook):
        """Denial reason includes the file path so coordinator can find it."""
        card = make_card_json("rg -qiE 'foo'")
        cwd = os.getcwd()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=cwd, delete=False) as f:
            json.dump(card, f)
            tmp_path = os.path.abspath(f.name)
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            assert result is not None
            reason = result.get("reason", "")
            assert tmp_path in reason, f"File path not in reason: {reason}"
        finally:
            os.unlink(tmp_path)

    def test_denial_reason_mentions_criterion_index(self, hook):
        """Denial reason mentions criteria index so coordinator can locate it."""
        card = make_card_json("rg -qiE 'foo'")
        result = run_with_temp_file(hook, card)
        assert result is not None
        reason = result.get("reason", "")
        assert "criteria[0]" in reason, f"criterion index not in reason: {reason}"

    def test_denial_reason_mentions_mov_commands_index(self, hook):
        """Denial reason mentions the mov_commands index (mov_idx) for precise location."""
        card = make_card_json("rg -qiE 'foo'")
        result = run_with_temp_file(hook, card)
        assert result is not None
        reason = result.get("reason", "")
        # Should reference mov_commands[0] (not mov_commands[*])
        assert "mov_commands[0]" in reason, f"mov_commands index not in reason: {reason}"

    def test_denial_reason_mentions_banned_pattern(self, hook):
        """Denial reason names the banned pattern."""
        card = make_card_json("rg -qiE 'foo'")
        result = run_with_temp_file(hook, card)
        assert result is not None
        reason = result.get("reason", "")
        # The reason should mention the pattern name or the specific flag
        assert "-E" in reason or "encoding" in reason.lower(), f"Pattern name not in reason: {reason}"

    def test_denial_reason_includes_fix(self, hook):
        """Denial reason includes a fix suggestion."""
        card = make_card_json("rg -qiE 'foo'")
        result = run_with_temp_file(hook, card)
        assert result is not None
        reason = result.get("reason", "")
        assert "Fix:" in reason or "fix" in reason.lower(), f"Fix suggestion not in reason: {reason}"

    def test_denial_reason_mentions_rg_qi(self, hook):
        """Denial reason for rg -E suggests the correct alternative."""
        card = make_card_json("rg -qiE 'verdict'")
        result = run_with_temp_file(hook, card)
        assert result is not None
        reason = result.get("reason", "")
        # Should suggest rg -qi as the fix
        assert "rg -qi" in reason or "PCRE2" in reason, f"Fix not in reason: {reason}"

    def test_denial_reason_mov_commands_index_second_command(self, hook):
        """Denial reason includes correct mov_commands index when banned pattern is second command."""
        card = {
            "action": "Test",
            "intent": "Test",
            "criteria": [
                {
                    "description": "Test",
                    "mov_commands": [
                        {"cmd": "rg -qi 'clean' file.txt", "timeout": 10},
                        {"cmd": "rg -qiE 'banned' file.txt", "timeout": 10},
                    ],
                }
            ],
        }
        result = run_with_temp_file(hook, card)
        assert result is not None
        reason = result.get("reason", "")
        # The banned pattern is at mov_commands[1]
        assert "mov_commands[1]" in reason, f"Expected mov_commands[1] in reason: {reason}"


# ---------------------------------------------------------------------------
# TestCardArrayForm — multiple cards in one file
# ---------------------------------------------------------------------------

class TestCardArrayForm:
    """Hook handles array-of-cards form, scanning all cards."""

    def test_array_all_clean_allowed(self, hook):
        """Array of clean cards → allowed."""
        cards = [
            make_card_json("rg -qi 'pattern' file.txt"),
            make_card_json("test -f some-file.py"),
        ]
        result = run_with_temp_file(hook, cards)
        assert_allowed(result)

    def test_array_first_card_banned_denied(self, hook):
        """First card has banned pattern → denied."""
        cards = [
            make_card_json("rg -qiE 'verdict'"),
            make_card_json("test -f clean.py"),
        ]
        result = run_with_temp_file(hook, cards)
        assert_blocked(result)

    def test_array_second_card_banned_denied(self, hook):
        """Second card has banned pattern → denied (all cards are scanned)."""
        cards = [
            make_card_json("rg -qi 'verdict'"),
            make_card_json("rg -E 'banned-pattern' file.txt"),
        ]
        result = run_with_temp_file(hook, cards)
        assert_blocked(result)

    def test_kanban_todo_file_form_intercepted(self, hook):
        """kanban todo --file is also intercepted (not just kanban do)."""
        card = make_card_json("rg -qiE 'verdict'")
        result = run_with_temp_file(hook, card, command_template="kanban todo --file {}")
        assert_blocked(result)

    def test_kanban_todo_file_clean_allowed(self, hook):
        """kanban todo --file with clean card is allowed."""
        card = make_card_json("rg -qi 'verdict'")
        result = run_with_temp_file(hook, card, command_template="kanban todo --file {}")
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestFilePathVariations — --file path extraction robustness
# ---------------------------------------------------------------------------

class TestFilePathVariations:
    """Hook correctly extracts file paths from various --file syntaxes."""

    def test_file_equals_syntax_detected(self, hook):
        """kanban do --file=/path/to/file.json (equals form) is intercepted."""
        card = make_card_json("rg -qiE 'foo'")
        cwd = os.getcwd()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=cwd, delete=False) as f:
            json.dump(card, f)
            tmp_path = os.path.abspath(f.name)
        try:
            payload = make_bash_payload(f"kanban do --file={tmp_path}")
            result = run_hook_main(hook, payload)
            assert_blocked(result)
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# TestFailOpen — error conditions must fail open
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Error conditions result in silent exit (allow), never block."""

    def test_empty_stdin_allowed(self, hook):
        """Empty stdin → no output, exits cleanly."""
        result = run_hook_main(hook, None)
        assert_allowed(result)

    def test_malformed_json_payload_allowed(self, hook):
        """Malformed hook payload JSON → fail open."""
        result = run_hook_main(hook, "{bad json here")
        assert_allowed(result)

    def test_missing_command_field_allowed(self, hook):
        """Bash payload with no command field → fail open."""
        payload = {"tool_name": "Bash", "tool_input": {}}
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestFailClosed — hook-skip flags in broken JSON fail closed
# ---------------------------------------------------------------------------

class TestFailClosed:
    """For hook-skip flags, parse failures fail CLOSED (block as precaution)."""

    def test_malformed_json_with_no_verify_blocked(self, hook):
        """Broken JSON file containing --no-verify literal → fail closed (block).

        This is the fail-closed behavior for the security boundary:
        a deliberately malformed JSON file cannot silently bypass hook-skip detection.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=".", delete=False) as f:
            f.write('{bad json, "cmd": "git commit --no-verify -m msg"}')
            tmp_path = f.name
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            assert_blocked(result), "Expected block for broken JSON with hook-skip literal"
            reason = result.get("reason", "")
            # Should explain the fail-closed behavior
            assert "could not be parsed" in reason.lower() or "blocked as a precaution" in reason.lower(), \
                f"Reason should explain fail-closed: {reason}"
        finally:
            os.unlink(tmp_path)

    def test_malformed_json_with_no_gpg_sign_blocked(self, hook):
        """Broken JSON file containing --no-gpg-sign literal → fail closed (block)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=".", delete=False) as f:
            f.write('{invalid json --no-gpg-sign here}')
            tmp_path = f.name
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            assert_blocked(result), "Expected block for broken JSON with hook-skip literal"
        finally:
            os.unlink(tmp_path)

    def test_malformed_json_with_husky_zero_blocked(self, hook):
        """Broken JSON file containing HUSKY=0 literal → fail closed (block)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=".", delete=False) as f:
            f.write('{invalid HUSKY=0 json}')
            tmp_path = f.name
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            assert_blocked(result), "Expected block for broken JSON with hook-skip literal"
        finally:
            os.unlink(tmp_path)

    def test_malformed_json_without_hook_skip_allowed(self, hook):
        """Broken JSON file without any hook-skip literal → fail open (allow).

        Only the rg -E lint (style guard) fails open on parse error.
        If there is no hook-skip literal, the file poses no hook-skip risk
        and the hook falls through to allow.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=".", delete=False) as f:
            f.write("{not valid json, but no hook skip flags here}")
            tmp_path = f.name
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            assert_allowed(result), "Expected allow for broken JSON without hook-skip content"
        finally:
            os.unlink(tmp_path)

    def test_malformed_json_with_git_commit_n_blocked(self, hook):
        """Broken JSON containing 'git commit -n' literal → fail closed."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=".", delete=False) as f:
            f.write('{broken json with git commit -n somewhere}')
            tmp_path = f.name
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            assert_blocked(result), "Expected block for broken JSON with git commit -n literal"
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# TestAnsiSanitization — ANSI escape sequences stripped from denial message
# ---------------------------------------------------------------------------

class TestAnsiSanitization:
    """ANSI escape sequences and non-printable chars must not appear in denial messages."""

    def test_ansi_escape_in_cmd_not_in_denial(self, hook):
        """A cmd containing an ANSI escape sequence must not produce an escape in the denial message.

        This guards against terminal injection via crafted cmd values.
        """
        # \x1b[2J is the ANSI clear-screen escape sequence
        ansi_cmd = "rg -qiE 'foo' \x1b[2Jfile.txt"
        card = make_card_json(ansi_cmd)
        result = run_with_temp_file(hook, card)
        assert result is not None, "Expected block for rg -qiE"
        reason = result.get("reason", "")
        # The ESC byte (0x1b) must not appear in the denial reason
        assert "\x1b" not in reason, (
            f"ANSI escape sequence (\\x1b) found in denial reason — injection risk: {reason!r}"
        )

    def test_null_byte_in_cmd_not_in_denial(self, hook):
        """A cmd containing a null byte must not produce a null byte in the denial message."""
        null_cmd = "rg -qiE 'foo' \x00file.txt"
        card = make_card_json(null_cmd)
        result = run_with_temp_file(hook, card)
        assert result is not None, "Expected block for rg -qiE"
        reason = result.get("reason", "")
        assert "\x00" not in reason, (
            f"Null byte found in denial reason: {reason!r}"
        )

    def test_non_printable_replaced_with_question_mark(self, hook):
        """Non-printable characters in cmd are replaced with '?' in the denial message."""
        non_print_cmd = "rg -qiE \x01\x02\x03 'foo'"
        card = make_card_json(non_print_cmd)
        result = run_with_temp_file(hook, card)
        assert result is not None, "Expected block for rg -qiE"
        reason = result.get("reason", "")
        # Non-printable control chars 0x01-0x03 should be replaced
        assert "\x01" not in reason and "\x02" not in reason and "\x03" not in reason, (
            f"Non-printable characters found in denial reason: {reason!r}"
        )


# ---------------------------------------------------------------------------
# TestPathContainment — paths outside cwd must not be read
# ---------------------------------------------------------------------------

class TestPathContainment:
    """Files outside the current working directory are not read (fail open)."""

    def test_path_outside_cwd_allowed(self, hook):
        """A --file path pointing outside the project tree is not read (fail open).

        This tests the path-containment check: paths outside cwd are ignored
        so the hook cannot be used to read sensitive files outside the project.
        """
        # /etc/passwd is outside any project cwd — should fail open
        payload = make_bash_payload("kanban do --file /etc/passwd")
        result = run_hook_main(hook, payload)
        assert_allowed(result), "Expected allow for path outside cwd (path containment)"

    def test_tmp_path_outside_cwd_allowed(self, hook):
        """A --file path in /tmp is outside cwd and should not be read (fail open)."""
        # Write a file with banned content to /tmp (outside project)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir="/tmp", delete=False) as f:
            json.dump(make_card_json("rg -qiE 'banned'"), f)
            tmp_path = f.name
        try:
            payload = make_bash_payload(f"kanban do --file {tmp_path}")
            result = run_hook_main(hook, payload)
            # File is outside cwd, so path containment causes fail-open regardless of content
            assert_allowed(result), (
                f"Expected allow for path outside cwd ({tmp_path}), but got: {result}"
            )
        finally:
            os.unlink(tmp_path)
