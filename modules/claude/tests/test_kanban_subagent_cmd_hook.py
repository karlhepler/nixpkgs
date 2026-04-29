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
    assert result.get("decision") == "block", f"Expected block, got: {result}"
    assert "reason" in result, "Block response must contain a 'reason' field"


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
        assert "criteria check" in result["reason"]
        assert "criteria uncheck" in result["reason"]

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
        assert "kanban done 5" in result["reason"]

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
        assert "shell-wrapper" in result["reason"].lower() or "bash -c" in result["reason"]

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
