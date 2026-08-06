"""
Tests for modules/claude/kanban-subagent-cmd-hook.py.

Covered paths:
1.  Sub-agent calls `kanban criteria check 5 1 --session foo` → ALLOW
2.  Sub-agent calls `kanban criteria uncheck 5 1 --session foo` → ALLOW
3.  Sub-agent calls `kanban done 5` → DENY with clear message
4.  Sub-agent calls `kanban cancel 5` → DENY
5.  Sub-agent calls `kanban criteria remove 5 1 "reason"` → DENY
6.  Sub-agent calls `kanban criteria add 5 "text"` → DENY
7.  Sub-agent calls `kanban list` → DENY (only criteria check/uncheck allowed)
8.  Sub-agent calls `kanban show 5` → DENY
9.  Coordinator (no agent_id) calls `kanban done 5` → ALLOW
10. Coordinator calls anything → ALLOW (hook only restricts sub-agents)
11. Sub-agent calls non-kanban command (`ls`, `git status`) → ALLOW
12. Invalid JSON payload → ALLOW (fail-open)
13. Empty command → ALLOW
14. Sub-agent calls `kanban --help` → ALLOW
"""

import importlib.util
import io
import json
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "kanban-subagent-cmd-hook.py"


def load_hook():
    """Import kanban-subagent-cmd-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_subagent_cmd_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the kanban-subagent-cmd hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a JSON payload via monkeypatched stdin / stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, payload) -> "dict | None":
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

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(sys, "stdin", io.StringIO(raw))
        mp.setattr("builtins.print", fake_print)
        try:
            hook_mod.main()
        except SystemExit:
            pass

    if not captured_output:
        return None
    return json.loads(captured_output[-1])


def make_bash_payload(
    command: str,
    agent_id: "str | None" = "agent-abc123",
    session_id: str = "test-session",
) -> dict:
    """Build a minimal Bash PreToolUse payload.

    agent_id=None → coordinator (main session)
    agent_id="agent-abc123" → sub-agent (default)
    """
    payload: dict = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session_id,
        "cwd": "/repo",
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return payload


# ---------------------------------------------------------------------------
# Helpers to assert decision outcomes
# ---------------------------------------------------------------------------

def assert_blocked(result: "dict | None"):
    assert result is not None, "Expected a block response, got silent exit (allow)"
    assert "decision" not in result, (
        f"Legacy top-level 'decision' key must not be present: {result}"
    )
    hook_output = result.get("hookSpecificOutput", {})
    assert hook_output.get("permissionDecision") == "deny", f"Expected deny, got: {result}"
    assert "permissionDecisionReason" in hook_output, (
        "Block response must contain a 'permissionDecisionReason' field"
    )


def block_reason(result: dict) -> str:
    """Extract the human-readable deny reason from a deny response."""
    return result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def assert_allowed(result: "dict | None"):
    assert result is None, f"Expected silent exit (allow), but got output: {result}"


# ---------------------------------------------------------------------------
# TestAllowedSubagentCommands — criteria check/uncheck + help must pass
# ---------------------------------------------------------------------------

class TestAllowedSubagentCommands:
    """Sub-agents may call only criteria check/uncheck and help."""

    def test_criteria_check_allowed(self, hook):
        """AC 1: Sub-agent calls `kanban criteria check 5 1 --session foo` → ALLOW."""
        payload = make_bash_payload("kanban criteria check 5 1 --session foo")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_criteria_uncheck_allowed(self, hook):
        """AC 2: Sub-agent calls `kanban criteria uncheck 5 1 --session foo` → ALLOW."""
        payload = make_bash_payload("kanban criteria uncheck 5 1 --session foo")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_criteria_check_no_session_allowed(self, hook):
        """criteria check without --session is also allowed."""
        payload = make_bash_payload("kanban criteria check 42 3")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_criteria_uncheck_no_session_allowed(self, hook):
        """criteria uncheck without --session is also allowed."""
        payload = make_bash_payload("kanban criteria uncheck 42 3")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_help_flag_allowed(self, hook):
        """AC 14: Sub-agent calls `kanban --help` → ALLOW."""
        payload = make_bash_payload("kanban --help")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_help_subcommand_allowed(self, hook):
        """Sub-agent calls `kanban help` → ALLOW."""
        payload = make_bash_payload("kanban help")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_short_help_flag_allowed(self, hook):
        """Sub-agent calls `kanban -h` → ALLOW."""
        payload = make_bash_payload("kanban -h")
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestDeniedSubagentCommands — lifecycle and non-criteria subcommands denied
# ---------------------------------------------------------------------------

class TestDeniedSubagentCommands:
    """Sub-agents must be blocked from all kanban commands except the allow-list."""

    def test_done_denied(self, hook):
        """AC 3: Sub-agent calls `kanban done 5` → DENY with clear message."""
        payload = make_bash_payload("kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        assert "criteria check" in block_reason(result)
        assert "criteria uncheck" in block_reason(result)

    def test_cancel_denied(self, hook):
        """AC 4: Sub-agent calls `kanban cancel 5` → DENY."""
        payload = make_bash_payload("kanban cancel 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_criteria_remove_denied(self, hook):
        """AC 5: Sub-agent calls `kanban criteria remove 5 1 "reason"` → DENY."""
        payload = make_bash_payload('kanban criteria remove 5 1 "reason"')
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_criteria_add_denied(self, hook):
        """AC 6: Sub-agent calls `kanban criteria add 5 "text"` → DENY."""
        payload = make_bash_payload('kanban criteria add 5 "text"')
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_list_denied(self, hook):
        """AC 7: Sub-agent calls `kanban list` → DENY."""
        payload = make_bash_payload("kanban list")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_show_denied(self, hook):
        """AC 8: Sub-agent calls `kanban show 5` → DENY."""
        payload = make_bash_payload("kanban show 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_do_denied(self, hook):
        """Sub-agent calls `kanban do 5` → DENY."""
        payload = make_bash_payload("kanban do 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_start_denied(self, hook):
        """Sub-agent calls `kanban start 5` → DENY."""
        payload = make_bash_payload("kanban start 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_defer_denied(self, hook):
        """Sub-agent calls `kanban defer 5` → DENY."""
        payload = make_bash_payload("kanban defer 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_denial_message_contains_attempted_command(self, hook):
        """The denial message must quote the attempted command."""
        payload = make_bash_payload("kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        assert "kanban done 5" in block_reason(result)

    def test_kanban_done_multiline_quoted_arg_denied(self, hook):
        """Regression (card #3468): kanban done 5 "summary\ntext" — a
        quoted trailing argument that spans two PHYSICAL lines — must
        still be DENIED. Before the fix, _tokenize_command's per-line
        shlex.split() raised ValueError on the first physical line
        ('kanban done 5 "summary') because its quote is unterminated on
        that line alone; the bare `except ValueError: continue` silently
        discarded the line instead of forming a segment, so
        _find_kanban_segment() never saw a 'kanban' token and the kanban
        subcommand allowlist (PROHIBITION 1) never ran against this
        command, allowing it through."""
        payload = make_bash_payload('kanban done 5 "summary\ntext"')
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        assert "criteria check" in block_reason(result)
        assert "criteria uncheck" in block_reason(result)

    def test_kanban_done_backslash_newline_continuation_denied(self, hook):
        """Regression (card #3474, finding F3): 'kanban\\\n done 5' — a
        real bash backslash-newline LINE CONTINUATION between the binary
        and its subcommand — must still be DENIED. Real bash elides the
        backslash and the newline entirely and executes this literally as
        `kanban done 5`. Before this fix, _tokenize_command handed the
        raw text straight to shlex.split(), which does NOT elide
        backslash-newline as a continuation — it treats the backslash as
        "escape the next character," corrupting the binary token to
        'kanban\\n' (embedded newline). 'kanban\\n' != 'kanban', so
        _is_kanban_binary()'s exact-string match failed and
        _find_kanban_segment() returned None, allowing the command
        through with PROHIBITION 1 never seeing it."""
        payload = make_bash_payload("kanban\\\n done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        assert "criteria check" in block_reason(result)
        assert "criteria uncheck" in block_reason(result)

    def test_criteria_with_no_subcommand_denied(self, hook):
        """Sub-agent calls `kanban criteria` alone → DENY."""
        payload = make_bash_payload("kanban criteria")
        result = run_hook_main(hook, payload)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# TestCoordinatorUnrestricted — main session (no agent_id) is always allowed
# ---------------------------------------------------------------------------

class TestCoordinatorUnrestricted:
    """Coordinators (no agent_id) must be unrestricted — hook is sub-agent-only."""

    def test_coordinator_done_allowed(self, hook):
        """AC 9: Coordinator (no agent_id) calls `kanban done 5` → ALLOW."""
        payload = make_bash_payload("kanban done 5", agent_id=None)
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_coordinator_cancel_allowed(self, hook):
        """AC 10: Coordinator calls `kanban cancel 5` → ALLOW."""
        payload = make_bash_payload("kanban cancel 5", agent_id=None)
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_coordinator_list_allowed(self, hook):
        """Coordinator calls `kanban list` → ALLOW."""
        payload = make_bash_payload("kanban list", agent_id=None)
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_coordinator_criteria_add_allowed(self, hook):
        """Coordinator calls `kanban criteria add` → ALLOW."""
        payload = make_bash_payload('kanban criteria add 5 "text"', agent_id=None)
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_coordinator_any_command_allowed(self, hook):
        """Coordinator always passes through regardless of command."""
        for command in ["kanban done 5", "kanban cancel 5", "kanban show 5",
                        "kanban list", "kanban criteria remove 5 1 x"]:
            payload = make_bash_payload(command, agent_id=None)
            result = run_hook_main(hook, payload)
            assert_allowed(result), f"Coordinator should be allowed for: {command}"


# ---------------------------------------------------------------------------
# TestNonKanbanCommands — non-kanban commands always pass through
# ---------------------------------------------------------------------------

class TestNonKanbanCommands:
    """Non-kanban commands must never be intercepted, even from sub-agents."""

    def test_ls_allowed(self, hook):
        """AC 11: Sub-agent calls `ls` → ALLOW."""
        payload = make_bash_payload("ls")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_git_status_allowed(self, hook):
        """AC 11: Sub-agent calls `git status` → ALLOW."""
        payload = make_bash_payload("git status")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_rg_allowed(self, hook):
        """Sub-agent calls `rg 'pattern' file` → ALLOW."""
        payload = make_bash_payload("rg 'pattern' file")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_cat_dotkanban_allowed(self, hook):
        """Sub-agent reads from .kanban/ path via cat → ALLOW (not a kanban CLI invocation)."""
        payload = make_bash_payload("cat .kanban/foo.json")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_pytest_allowed(self, hook):
        """Sub-agent calls pytest → ALLOW."""
        payload = make_bash_payload("pytest modules/claude/tests/")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_git_commit_multiline_message_allowed(self, hook):
        """Survival guard (card #3468): a benign multi-line quoted commit
        message — git commit -m "line one\nline two" — must remain
        ALLOWED. The multi-line-quote fix must not over-correct into
        denying ordinary multi-line arguments that have nothing to do with
        kanban or shell-wrapper -c/-e invocations."""
        payload = make_bash_payload('git commit -m "line one\nline two"')
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_echo_multiline_quoted_allowed(self, hook):
        """Survival guard (card #3468): echo "a\nb" — a benign multi-line
        quoted argument — must remain ALLOWED."""
        payload = make_bash_payload('echo "a\nb"')
        result = run_hook_main(hook, payload)
        assert_allowed(result)


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
            "agent_id": "agent-abc123",
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_read_tool_allowed(self, hook):
        """Read tool calls are not inspected."""
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/file.txt"},
            "agent_id": "agent-abc123",
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_write_tool_allowed(self, hook):
        """Write tool calls are not inspected."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/out.txt", "content": "hello"},
            "agent_id": "agent-abc123",
        }
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestFailOpen — edge cases that must fail open
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Any unexpected error must fail open (allow). Never block innocent commands."""

    def test_invalid_json_allowed(self, hook):
        """AC 12: Invalid JSON payload → ALLOW (fail-open)."""
        result = run_hook_main(hook, "not-json-at-all{{{")
        assert_allowed(result)

    def test_empty_stdin_allowed(self, hook):
        """AC 12: Empty stdin → ALLOW (fail-open)."""
        result = run_hook_main(hook, None)
        assert_allowed(result)

    def test_empty_command_allowed(self, hook):
        """AC 13: Empty command string → ALLOW (fail-open)."""
        payload = make_bash_payload("")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_whitespace_only_command_allowed(self, hook):
        """Whitespace-only command → ALLOW (fail-open)."""
        payload = make_bash_payload("   \t  ")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_missing_tool_input_allowed(self, hook):
        """Payload without tool_input → ALLOW (fail-open)."""
        payload = {"tool_name": "Bash", "agent_id": "agent-abc123"}
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_missing_command_key_allowed(self, hook):
        """Payload with tool_input but no command key → ALLOW (fail-open)."""
        payload = {"tool_name": "Bash", "tool_input": {}, "agent_id": "agent-abc123"}
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestEdgeCases — path, binary detection, and compound command edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases for kanban-as-binary detection and compound commands."""

    def test_kanban_as_path_substring_allowed(self, hook):
        """rg 'kanban' file.py — kanban as search pattern, not binary → ALLOW."""
        payload = make_bash_payload("rg 'kanban' modules/")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_echo_kanban_allowed(self, hook):
        """echo 'kanban' — kanban as shell text, not binary invocation → ALLOW."""
        payload = make_bash_payload("echo 'kanban done'")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_criteria_check_with_session_flag_allowed(self, hook):
        """criteria check with session flag in various positions → ALLOW."""
        payload = make_bash_payload("kanban --session gold-drift criteria check 5 1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_kanban_hyphenated_binary_not_matched(self, hook):
        """kanban-foo binary — not the kanban CLI, must not be intercepted → ALLOW."""
        # kanban-pretool-hook is a different binary
        payload = make_bash_payload("kanban-pretool-hook --help")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_absolute_path_kanban_criteria_check_allowed(self, hook):
        """Absolute path to kanban binary with criteria check → ALLOW."""
        payload = make_bash_payload("/nix/store/abc123-kanban-1.0/bin/kanban criteria check 5 1 --session foo")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_absolute_path_kanban_done_denied(self, hook):
        """Absolute path to kanban binary with `done` → DENY."""
        payload = make_bash_payload("/nix/store/abc123-kanban-1.0/bin/kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_fused_quote_binary_fallback_denied(self, hook):
        """Regression (card #3474, finding [medium] from review #3470):
        '"kanban done 5' — an unterminated quote character fused
        directly onto the front of the 'kanban' binary token, with no
        closing quote anywhere in the command — must still be DENIED.
        This never balances, so it reaches _tokenize_command's
        whitespace-split fallback. Before this fix, the fallback's naive
        `.split()` produced the token '"kanban' (quote still attached),
        which matched neither the exact 'kanban' string nor a
        '/bin/kanban' path suffix in _is_kanban_binary(), so
        _find_kanban_segment() returned None and the command was
        allowed through with PROHIBITION 1 never seeing it."""
        payload = make_bash_payload('"kanban done 5')
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        assert "criteria check" in block_reason(result)
        assert "criteria uncheck" in block_reason(result)

    def test_single_quote_backslash_newline_continuation_subcommand_denied(self, hook):
        """Regression (card #3477, Finding 1 from the #3474 review):
        `kanban criteria 'chec\\\n k' 5 1` — a backslash-newline pair
        spliced INSIDE a single-quoted subcommand argument — must still be
        DENIED. Real bash treats backslash as a plain literal character
        inside single quotes, so it never escapes a following newline
        there; the actual argv bash passes is the 6-character literal
        'chec\\<newline>k', not the clean 5-character string 'check'.
        Before this fix, _join_continuation_lines elided the
        backslash-newline unconditionally (quote-blind), welding the two
        physical lines into the allowlisted keyword 'check' and flipping
        a real DENY into a wrongly-granted ALLOW. Also covers the
        'criteria' token itself splicing the same way
        (`kanban 'criteri\\\n a' check 5 1`).

        A third payload, `'kan\\\n ban' done 5` — the same single-quote
        weld landing on the BINARY token instead of a subcommand keyword —
        is asserted ALLOWED (card #3482): real bash reports "command not found"
        for this literal argv[0], so kanban never executes and the hook has
        nothing to guard. Verified against real bash (see
        .scratchpad/realbash-divergence-check.py). This is not a
        regression: the now-removed legacy quote-blind tokenizer variant
        used to weld this into the allowlisted 'kanban' binary token and
        deny it, but that denial guarded an input bash itself can never
        run, so dropping it costs nothing."""
        payload = make_bash_payload("kanban criteria 'chec\\\nk' 5 1")
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        assert "criteria check" in block_reason(result)
        assert "criteria uncheck" in block_reason(result)

        payload2 = make_bash_payload("kanban 'criteri\\\na' check 5 1")
        result2 = run_hook_main(hook, payload2)
        assert_blocked(result2)

        payload3 = make_bash_payload("'kan\\\nban' done 5")
        result3 = run_hook_main(hook, payload3)
        assert_allowed(result3)

    def test_tokenizer_never_closes_fallback_denied(self, hook):
        """Regression (card #3477, Finding 3 from the #3474 review): a
        quote that opens and then NEVER closes at all — as opposed to the
        checked-in perf probe (tokenizer-hardening-probe.py), which only
        exercises a quote that closes on the very last line — takes a
        different code path (the fail-closed whitespace-split fallback in
        _tokenize_command, reached only once input is fully exhausted with
        an unresolved buffer) and previously had no permanent regression
        guard. Must still be DENIED (the fallback's naive `.split()` still
        exposes the 'kanban'/'done' tokens to the downstream checks), and
        must complete in roughly linear time — a modest line count with a
        generous time budget, since this guards against an O(n^2)
        reintroduction rather than measuring an exact benchmark."""
        lines = 300
        filler = "\n".join(f"filler line {i}" for i in range(lines))
        payload = make_bash_payload(f'kanban done 5 "never closes\n{filler}')
        start = time.monotonic()
        result = run_hook_main(hook, payload)
        elapsed = time.monotonic() - start
        assert_blocked(result)
        assert elapsed < 5.0, f"never-closes fallback took {elapsed:.2f}s for {lines} lines"


# ---------------------------------------------------------------------------
# TestEnvCommandExecWrapperBypasses — env/command/exec wrapper bypass vectors
# ---------------------------------------------------------------------------

class TestEnvCommandExecWrapperBypasses:
    """env/command/exec wrappers must be detected and applied the same guard."""

    def test_env_kanban_done_denied(self, hook):
        """Test 1: env kanban done 5 from sub-agent → DENY."""
        payload = make_bash_payload("env kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_env_keyval_kanban_done_denied(self, hook):
        """Test 2: env KEY=val kanban done 5 from sub-agent → DENY."""
        payload = make_bash_payload("env KEY=val kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_usr_bin_env_kanban_done_denied(self, hook):
        """Test 3: /usr/bin/env kanban done 5 from sub-agent → DENY."""
        payload = make_bash_payload("/usr/bin/env kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_command_kanban_done_denied(self, hook):
        """Test 4: command kanban done 5 from sub-agent → DENY."""
        payload = make_bash_payload("command kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_exec_kanban_done_denied(self, hook):
        """Test 5: exec kanban done 5 from sub-agent → DENY."""
        payload = make_bash_payload("exec kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_env_kanban_criteria_check_allowed(self, hook):
        """Test 9: env kanban criteria check 5 1 from sub-agent → ALLOW (allowed subcommand even with wrapper)."""
        payload = make_bash_payload("env kanban criteria check 5 1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_env_kanban_cancel_denied(self, hook):
        """env kanban cancel 5 from sub-agent → DENY (cancel is not allowed)."""
        payload = make_bash_payload("env kanban cancel 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_command_kanban_criteria_check_allowed(self, hook):
        """command kanban criteria check 5 1 → ALLOW (allowed subcommand even with command wrapper)."""
        payload = make_bash_payload("command kanban criteria check 5 1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_exec_kanban_criteria_uncheck_allowed(self, hook):
        """exec kanban criteria uncheck 5 1 → ALLOW (allowed subcommand even with exec wrapper)."""
        payload = make_bash_payload("exec kanban criteria uncheck 5 1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# TestShellWrapperDenial — bash/sh/zsh/python -c shell wrapper bypass vectors
# ---------------------------------------------------------------------------

class TestShellWrapperDenial:
    """Shell/script runner -c invocations from sub-agents must be denied outright."""

    def test_bash_c_kanban_done_denied(self, hook):
        """Test 6: bash -c 'kanban done 5' from sub-agent → DENY (with shell-wrapper message)."""
        payload = make_bash_payload("bash -c 'kanban done 5'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        reason = block_reason(result)
        assert "shell-wrapper" in reason.lower() or "bash -c" in reason

    def test_sh_c_kanban_cancel_denied(self, hook):
        """Test 7: sh -c 'kanban cancel 5' from sub-agent → DENY."""
        payload = make_bash_payload("sh -c 'kanban cancel 5'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_python3_c_kanban_denied(self, hook):
        """Test 8: python3 -c 'kanban done' from sub-agent → DENY."""
        payload = make_bash_payload("python3 -c 'kanban done'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_coordinator_bash_c_kanban_done_allowed(self, hook):
        """Test 10: Coordinator (no agent_id) calling bash -c 'kanban done 5' → ALLOW."""
        payload = make_bash_payload("bash -c 'kanban done 5'", agent_id=None)
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_no_c_allowed(self, hook):
        """Test 11: Sub-agent calling bash (no -c) → ALLOW (only -c form is blocked)."""
        payload = make_bash_payload("bash")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_script_file_allowed(self, hook):
        """Test 12: Sub-agent calling bash some-script.sh → ALLOW (script invocation is not -c shell wrapper)."""
        payload = make_bash_payload("bash some-script.sh")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_zsh_c_denied(self, hook):
        """zsh -c 'kanban done 5' from sub-agent → DENY."""
        payload = make_bash_payload("zsh -c 'kanban done 5'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_perl_e_denied(self, hook):
        """perl -e '...' from sub-agent → DENY."""
        payload = make_bash_payload("perl -e 'system(\"kanban done 5\")'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_ruby_e_denied(self, hook):
        """ruby -e '...' from sub-agent → DENY."""
        payload = make_bash_payload("ruby -e 'system(\"kanban done 5\")'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_python_c_denied(self, hook):
        """python -c '...' from sub-agent → DENY."""
        payload = make_bash_payload("python -c 'import subprocess; subprocess.run([\"kanban\",\"done\",\"5\"])'")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_python3_c_multiline_quoted_arg_denied(self, hook):
        """Regression (card #3468): python3 -c "import x\nprint(1)" — a
        quoted -c script argument that spans two PHYSICAL lines — must
        still be DENIED. Before the fix, _tokenize_command called
        shlex.split() per physical line; the first line ('python3 -c
        "import x') has an unterminated quote, shlex.split raised
        ValueError, and the bare `except ValueError: continue` silently
        dropped the line. No segment was ever formed, so
        _is_shell_wrapper_invocation() never ran against it and the
        command was allowed through."""
        payload = make_bash_payload('python3 -c "import x\nprint(1)"')
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        reason = block_reason(result)
        assert "shell-wrapper" in reason.lower() or "python3 -c" in reason

    def test_python3_c_backslash_newline_continuation_denied(self, hook):
        """Regression (card #3474, finding F3): 'python3 \\\n-c "import
        x"' — a real bash backslash-newline LINE CONTINUATION between the
        interpreter name and its -c flag — must still be DENIED. Real
        bash elides the backslash and the newline and executes this
        literally as `python3 -c "import x"`. Before this fix,
        shlex.split() on the raw (un-elided) text corrupted the flag
        token to '\\n-c' (embedded newline prefix), which failed the
        exact `tok in inline_flags` check in
        _is_shell_wrapper_invocation() and let the shell-wrapper
        invocation through unchecked."""
        payload = make_bash_payload('python3 \\\n-c "import x"')
        result = run_hook_main(hook, payload)
        assert_blocked(result)
        reason = block_reason(result)
        assert "shell-wrapper" in reason.lower() or "python3 -c" in reason


# ---------------------------------------------------------------------------
# TestBareEnvPrefixBypasses — VAR=value cmd bypass vectors
# ---------------------------------------------------------------------------

class TestBareEnvPrefixBypasses:
    """Bare shell env-var prefixes (VAR=value cmd) must be detected and denied."""

    def test_single_env_prefix_kanban_list_denied(self, hook):
        """Test 1: KANBAN_SESSION=x kanban list from sub-agent → DENY."""
        payload = make_bash_payload("KANBAN_SESSION=x kanban list")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_multi_env_prefix_kanban_list_denied(self, hook):
        """Test 2: FOO=1 BAR=2 kanban list from sub-agent → DENY (multi-prefix)."""
        payload = make_bash_payload("FOO=1 BAR=2 kanban list")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_env_prefix_with_punct_kanban_done_denied(self, hook):
        """Test 3: FOO=val_with_punct/.path kanban done 5 from sub-agent → DENY."""
        payload = make_bash_payload("FOO=val_with_punct/.path kanban done 5")
        result = run_hook_main(hook, payload)
        assert_blocked(result)

    def test_env_prefix_kanban_criteria_check_allowed(self, hook):
        """Test 4: KANBAN_SESSION=x kanban criteria check 5 1 from sub-agent → ALLOW."""
        payload = make_bash_payload("KANBAN_SESSION=x kanban criteria check 5 1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_env_prefix_kanban_criteria_uncheck_allowed(self, hook):
        """Test 5: KANBAN_SESSION=x kanban criteria uncheck 5 1 from sub-agent → ALLOW."""
        payload = make_bash_payload("KANBAN_SESSION=x kanban criteria uncheck 5 1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_coordinator_env_prefix_kanban_done_allowed(self, hook):
        """Test 6: Coordinator (no agent_id) calling KANBAN_SESSION=x kanban done 5 → ALLOW."""
        payload = make_bash_payload("KANBAN_SESSION=x kanban done 5", agent_id=None)
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_env_prefix_on_non_kanban_command_allowed(self, hook):
        """Test 7: KANBAN=val ls (env-prefix on non-kanban command) from sub-agent → ALLOW."""
        payload = make_bash_payload("KANBAN=val ls")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_empty_value_env_prefix_kanban_list_denied(self, hook):
        """Test 8: KANBAN_SESSION= kanban list (empty value) from sub-agent → DENY."""
        payload = make_bash_payload("KANBAN_SESSION= kanban list")
        result = run_hook_main(hook, payload)
        assert_blocked(result)


# ---------------------------------------------------------------------------
# TestCompositionRootDenyFormat — smoke test guarding the real hook entry
# point (main()) emits the documented hookSpecificOutput.permissionDecision
# deny shape, not the legacy top-level {"decision": "block", ...} format.
# Covers both deny call-sites: _deny() and _deny_shell_wrapper().
# ---------------------------------------------------------------------------

class TestCompositionRootDenyFormat:
    """Exercise the real hook.main() entry point end-to-end and assert the
    emitted deny JSON uses the documented hookSpecificOutput.permissionDecision
    shape rather than the legacy top-level "decision" key. This is the
    regression guard that catches a future runtime dropping legacy support.
    """

    def test_forbidden_kanban_command_emits_permission_decision_deny(self, hook):
        """Sub-agent invokes a forbidden kanban command (`kanban done 5`) →
        deny via the _deny() call-site, using the documented
        hookSpecificOutput.permissionDecision shape."""
        payload = make_bash_payload("kanban done 5")
        result = run_hook_main(hook, payload)

        assert result is not None, "Expected a deny response, got silent exit (allow)"
        assert result.get("continue") is False
        assert "decision" not in result, (
            f"Legacy top-level 'decision' key must not be present: {result}"
        )
        hook_output = result.get("hookSpecificOutput")
        assert hook_output is not None, f"Expected hookSpecificOutput, got: {result}"
        assert hook_output.get("hookEventName") == "PreToolUse"
        assert hook_output.get("permissionDecision") == "deny"
        assert "kanban done 5" in hook_output.get("permissionDecisionReason", "")

        # Top-level stopReason must be present (user-facing halt message) and
        # non-empty — see card #2905.
        assert len(result.get("stopReason", "")) > 0, (
            f"Expected non-empty top-level stopReason: {result}"
        )

    def test_shell_wrapper_invocation_emits_permission_decision_deny(self, hook):
        """Sub-agent invokes a forbidden shell-wrapper command
        (`bash -c 'kanban done 5'`) → deny via the _deny_shell_wrapper()
        call-site, using the documented hookSpecificOutput.permissionDecision
        shape."""
        payload = make_bash_payload("bash -c 'kanban done 5'")
        result = run_hook_main(hook, payload)

        assert result is not None, "Expected a deny response, got silent exit (allow)"
        assert "decision" not in result, (
            f"Legacy top-level 'decision' key must not be present: {result}"
        )
        hook_output = result.get("hookSpecificOutput")
        assert hook_output is not None, f"Expected hookSpecificOutput, got: {result}"
        assert hook_output.get("hookEventName") == "PreToolUse"
        assert hook_output.get("permissionDecision") == "deny"
        reason = hook_output.get("permissionDecisionReason", "")
        assert "shell-wrapper" in reason.lower() or "bash -c" in reason

        # Top-level stopReason must be present (user-facing halt message) and
        # non-empty — see card #2905.
        assert len(result.get("stopReason", "")) > 0, (
            f"Expected non-empty top-level stopReason: {result}"
        )
