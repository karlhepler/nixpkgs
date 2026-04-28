"""
Tests for modules/claude/kanban-subagent-stop-hook.py.

Covered paths:
- Card with all programmatic criteria + all passing → kanban done called directly
- Invalid AC (missing mov_commands or non-programmatic mov_type) → auto-fail with error message
- Card with unchecked criteria at stop → kanban review fails, agent sent back for redo
- Max retry cycles reached → stop allowed, failure surfaces
- Programmatic MoV command fails (exit nonzero) → kanban criteria fail called with diagnostic
- MoV exit 127/126/124 → mov_error diagnostic emitted (not a pass/fail)

All kanban CLI and subprocess calls are monkeypatched — no real
kanban cards are created or read during these tests.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from .conftest import (
    KanbanMockResponses,
    make_card_header_entry,
    make_kanban_criteria_bash_entry,
    make_stop_payload,
    make_substantive_tool_entry,
    make_transcript_jsonl,
)

# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "kanban-subagent-stop-hook.py"


def load_hook():
    """Import kanban-subagent-stop-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_subagent_stop_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    return load_hook()


# ---------------------------------------------------------------------------
# Helpers to assert decision outcomes
# ---------------------------------------------------------------------------

def assert_allow(result: dict):
    assert result.get("decision") == "allow", f"Expected allow, got: {result}"


def assert_block(result: dict, substring: str = ""):
    assert result.get("decision") == "block", f"Expected block, got: {result}"
    if substring:
        reason = result.get("reason", "")
        assert substring.lower() in reason.lower(), (
            f"Expected {substring!r} in block reason. Got: {reason!r}"
        )


# ---------------------------------------------------------------------------
# Helper: run process_subagent_stop with a transcript
# ---------------------------------------------------------------------------

def run_process_stop(hook_mod, payload: dict, env: dict | None = None) -> dict:
    """Call process_subagent_stop with optional env overrides."""
    env_patch = env or {}
    with patch.dict(os.environ, env_patch, clear=False):
        with patch.object(hook_mod, "log_error"):
            with patch.object(hook_mod, "log_info"):
                return hook_mod.process_subagent_stop(payload)


# ---------------------------------------------------------------------------
# All-programmatic criteria path (no LLM reviewer)
# ---------------------------------------------------------------------------

class TestAllProgrammaticCriteria:
    """Card with all programmatic criteria + all passing → kanban done called directly (no LLM reviewer)."""

    def test_all_programmatic_pass_calls_done_directly(self, hook, tmp_transcript):
        """When all criteria are programmatic and all pass, kanban done is called
        directly (no LLM reviewer launched)."""
        entries = [make_card_header_entry("10", "sess-a")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Card criteria: two programmatic, no semantic
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="10",
            session="sess-a",
            status="doing",
            criteria=[
                {"text": "File A exists", "mov_type": "programmatic", "mov_commands": [{"cmd": "test -f /tmp/a", "timeout": 5}]},
                {"text": "File B exists", "mov_type": "programmatic", "mov_commands": [{"cmd": "test -f /tmp/b", "timeout": 5}]},
            ],
        )

        subprocess_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            subprocess_calls.append(cmd if isinstance(cmd, list) else [cmd])
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.success(stdout="ok")
                if sub == "done":
                    return KanbanMockResponses.success(stdout="done")
                if sub == "criteria":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            # MoV commands run via shell=True — cmd is a string
            if isinstance(cmd, str) and "test -f" in cmd:
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        assert_allow(result)

        # Verify no claude -p was called (no LLM reviewer)
        claude_calls = [
            c for c in subprocess_calls
            if c and c[0] == "claude"
        ]
        assert len(claude_calls) == 0, (
            f"Expected no claude -p calls for all-programmatic card, but got: {claude_calls}"
        )

    def test_programmatic_criteria_calls_kanban_done(self, hook, tmp_transcript):
        """kanban done should be called on the programmatic-only path."""
        entries = [make_card_header_entry("11", "sess-b")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="11",
            session="sess-b",
            status="doing",
            criteria=[
                {"text": "Check", "mov_type": "programmatic", "mov_commands": [{"cmd": "true", "timeout": 5}]},
            ],
        )

        done_called = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.success()
                if sub == "done":
                    done_called.append(cmd)
                    return KanbanMockResponses.success()
                if sub == "criteria":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            if isinstance(cmd, str) and cmd.strip() == "true":
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            run_process_stop(hook, payload)

        assert len(done_called) >= 1, "Expected kanban done to be called on programmatic-only path"



# ---------------------------------------------------------------------------
# Invalid AC auto-fail (missing mov_commands or non-programmatic mov_type)
# ---------------------------------------------------------------------------

class TestInvalidACAutoFail:
    """Criteria with non-programmatic mov_type or missing mov_commands → auto-fail."""

    def test_missing_mov_commands_auto_fails_with_error_message(self, hook, tmp_transcript):
        """A criterion with mov_type programmatic but empty mov_commands is auto-failed
        with 'invalid AC: no programmatic verification provided'."""
        entries = [make_card_header_entry("25", "sess-invalid")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="25",
            session="sess-invalid",
            status="doing",
            criteria=[
                {"text": "Some check", "mov_type": "programmatic", "mov_commands": []},
            ],
        )

        criteria_fail_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.success()
                if sub == "criteria" and len(cmd) > 2 and cmd[2] == "fail":
                    criteria_fail_calls.append(cmd)
                    return KanbanMockResponses.success()
                if sub == "criteria":
                    return KanbanMockResponses.success()
                if sub == "redo":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                run_process_stop(hook, payload)

        assert len(criteria_fail_calls) >= 1, (
            "Expected kanban criteria fail to be called for criterion with empty mov_commands"
        )
        # Verify the required error message is present in the fail call
        fail_args = " ".join(str(a) for a in criteria_fail_calls[0])
        assert "invalid AC" in fail_args.lower() or "invalid ac" in fail_args.lower(), (
            f"Expected 'invalid AC' in fail reason. Got: {fail_args!r}"
        )

    def test_semantic_mov_type_auto_fails_with_error_message(self, hook, tmp_transcript):
        """A criterion with mov_type 'semantic' (instead of 'programmatic') is auto-failed
        with 'invalid AC: no programmatic verification provided'."""
        entries = [make_card_header_entry("26", "sess-semantic")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="26",
            session="sess-semantic",
            status="doing",
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic"},
            ],
        )

        criteria_fail_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.success()
                if sub == "criteria" and len(cmd) > 2 and cmd[2] == "fail":
                    criteria_fail_calls.append(cmd)
                    return KanbanMockResponses.success()
                if sub == "criteria":
                    return KanbanMockResponses.success()
                if sub == "redo":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                run_process_stop(hook, payload)

        assert len(criteria_fail_calls) >= 1, (
            "Expected kanban criteria fail to be called for criterion with mov_type='semantic'"
        )
        fail_args = " ".join(str(a) for a in criteria_fail_calls[0])
        assert "invalid AC" in fail_args.lower() or "invalid ac" in fail_args.lower(), (
            f"Expected 'invalid AC' in fail reason. Got: {fail_args!r}"
        )

    def test_no_claude_launched_for_invalid_ac(self, hook, tmp_transcript):
        """Invalid AC (semantic mov_type) must NOT launch claude -p — auto-fail only."""
        entries = [make_card_header_entry("27", "sess-no-claude")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="27",
            session="sess-no-claude",
            status="doing",
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic"},
            ],
        )

        subprocess_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            subprocess_calls.append(cmd if isinstance(cmd, list) else [cmd])
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.success()
                if sub == "redo":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                run_process_stop(hook, payload)

        claude_calls = [c for c in subprocess_calls if c and c[0] == "claude"]
        assert len(claude_calls) == 0, (
            f"Expected no claude -p calls for invalid AC, but got: {claude_calls}"
        )


# ---------------------------------------------------------------------------
# Unchecked criteria → kanban review fails, agent sent back
# ---------------------------------------------------------------------------

class TestUncheckedCriteriaBlocking:
    """Card with unchecked criteria at stop → kanban review fails, agent blocked."""

    def test_kanban_review_failure_blocks_agent(self, hook, tmp_transcript):
        """If kanban review fails (unchecked criteria), process_subagent_stop returns block."""
        entries = [make_card_header_entry("30", "sess-e")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="30",
            session="sess-e",
            status="doing",
            criteria=[
                {"text": "Unchecked", "mov_type": "programmatic", "mov_commands": [{"cmd": "test -f /missing", "timeout": 5}], "agent_met": "false"},
            ],
        )

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.failure(
                        stderr="1 acceptance criteria not yet checked", returncode=1
                    )
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        assert_block(result, "unchecked")

    def test_block_reason_contains_guidance(self, hook, tmp_transcript):
        """Block reason should instruct agent to investigate, not blindly check."""
        entries = [make_card_header_entry("31", "sess-f")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="31",
            session="sess-f",
            status="doing",
        )

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.failure(
                        stderr="unchecked acceptance criteria", returncode=1
                    )
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        reason = result.get("reason", "")
        assert "investigate" in reason.lower() or "unchecked" in reason.lower()


# ---------------------------------------------------------------------------
# Max retry cycles reached → stop allowed, failure surfaces
# ---------------------------------------------------------------------------

class TestMaxRetryCyclesReached:
    """Max retry cycles reached → stop allowed with failure summary."""

    def test_max_cycles_allows_stop(self, hook, tmp_transcript):
        entries = [make_card_header_entry("40", "sess-g")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Card already at max review cycles (3) with a failing programmatic criterion
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="40",
            session="sess-g",
            status="review",
            review_cycles=3,
            criteria=[
                {"text": "File exists", "mov_type": "programmatic",
                 "mov_commands": [{"cmd": "test -f /missing", "timeout": 5}],
                 "reviewer_met": "fail"},
            ],
        )

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="review")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=1)
                return KanbanMockResponses.success()
            if isinstance(cmd, str) and "test -f" in cmd:
                m = MagicMock()
                m.returncode = 1
                m.stdout = ""
                m.stderr = ""
                return m
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        # After inner loop exhausted and review_cycles >= MAX_OUTER_CYCLES, allow stop
        assert_allow(result)
        msg = result.get("reason", "") or ""
        assert "max" in msg.lower() or "manual" in msg.lower() or "intervention" in msg.lower() or "cycles" in msg.lower()

    def test_under_max_cycles_blocks_agent(self, hook, tmp_transcript):
        """When under max cycles, a failed programmatic MoV blocks the agent for redo."""
        entries = [make_card_header_entry("41", "sess-h")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Card at 0 review cycles with a failing programmatic criterion
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="41",
            session="sess-h",
            status="review",
            review_cycles=0,
            criteria=[
                {"text": "File exists", "mov_type": "programmatic",
                 "mov_commands": [{"cmd": "test -f /missing", "timeout": 5}],
                 "reviewer_met": "fail"},
            ],
        )

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="review")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=1)
                if sub == "redo":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            if isinstance(cmd, str) and "test -f" in cmd:
                m = MagicMock()
                m.returncode = 1
                m.stdout = ""
                m.stderr = ""
                return m
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert_block(result)


# ---------------------------------------------------------------------------
# Programmatic MoV failure → kanban criteria fail called
# ---------------------------------------------------------------------------

class TestProgrammaticMovFailure:
    """Programmatic MoV fails with nonzero exit → kanban criteria fail called."""

    def test_mov_failure_calls_criteria_fail(self, hook, tmp_transcript):
        """Exit code 1 from MoV command → kanban criteria fail is called.

        The card starts in 'review' status so process_subagent_stop skips the
        kanban review call and proceeds directly to run_inner_loop, where the
        programmatic MoV executes and fails.
        """
        entries = [make_card_header_entry("50", "sess-i")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Card in review so the hook skips kanban review and goes to inner loop
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="50",
            session="sess-i",
            status="review",
            criteria=[
                {"text": "Test passes", "mov_type": "programmatic", "mov_commands": [{"cmd": "false", "timeout": 5}]},
            ],
        )
        criteria_fail_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="review")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=1, stderr="criteria failed")
                if sub == "redo":
                    return KanbanMockResponses.success()
                if sub == "criteria" and len(cmd) > 2 and cmd[2] == "fail":
                    criteria_fail_calls.append(cmd)
                    return KanbanMockResponses.success()
                if sub == "criteria":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            # Shell command: "false" exits 1
            if isinstance(cmd, str) and cmd.strip() == "false":
                m = MagicMock()
                m.returncode = 1
                m.stdout = ""
                m.stderr = ""
                return m
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                run_process_stop(hook, payload)

        assert len(criteria_fail_calls) >= 1, (
            "Expected kanban criteria fail to be called when MoV exits 1"
        )

    def test_mov_pass_calls_criteria_pass(self, hook, tmp_transcript):
        """Exit code 0 from MoV command → kanban criteria pass is called."""
        entries = [make_card_header_entry("51", "sess-j")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="51",
            session="sess-j",
            status="doing",
            criteria=[
                {"text": "Test passes", "mov_type": "programmatic", "mov_commands": [{"cmd": "true", "timeout": 5}]},
            ],
        )
        criteria_pass_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.success()
                if sub == "done":
                    return KanbanMockResponses.success()
                if sub == "criteria" and len(cmd) > 2 and cmd[2] == "pass":
                    criteria_pass_calls.append(cmd)
                    return KanbanMockResponses.success()
                if sub == "criteria":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            if isinstance(cmd, str) and cmd.strip() == "true":
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            run_process_stop(hook, payload)

        assert len(criteria_pass_calls) >= 1, (
            "Expected kanban criteria pass to be called when MoV exits 0"
        )


# ---------------------------------------------------------------------------
# MoV error exit codes (126/127/124) → mov_error diagnostic, no pass/fail
# ---------------------------------------------------------------------------

class TestMovErrorExitCodes:
    """Exit codes 126/127/124 → mov_error diagnostic emitted, no pass/fail."""

    @pytest.mark.parametrize("exit_code,label", [
        (127, "command not found"),
        (126, "permission denied"),
        (124, "timeout"),
        (2, "bash syntax error"),
    ])
    def test_mov_error_exit_code_emits_diagnostic(self, hook, tmp_transcript, exit_code, label):
        """MoV exit 127/126/124 → no criteria fail/pass call; diagnostic surfaced."""
        entries = [make_card_header_entry("60", "sess-k")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="60",
            session="sess-k",
            status="doing",
            criteria=[
                {"text": "Check", "mov_type": "programmatic",
                 "mov_commands": [{"cmd": "nonexistent_command_xyz", "timeout": 5}]},
            ],
        )
        criteria_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.failure(returncode=1, stderr="not reviewed")
                if sub in ("criteria",):
                    criteria_calls.append(cmd)
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            # Shell command exits with the specified error code
            if isinstance(cmd, str):
                m = MagicMock()
                m.returncode = exit_code
                m.stdout = ""
                m.stderr = ""
                return m
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        # Criteria pass/fail should NOT have been called
        pass_fail_calls = [
            c for c in criteria_calls
            if len(c) > 2 and c[2] in ("pass", "fail")
        ]
        assert len(pass_fail_calls) == 0, (
            f"Exit {exit_code} should not call criteria pass/fail, but got: {pass_fail_calls}"
        )

    def test_run_programmatic_mov_returns_diagnostic_on_error_exit(self, hook, tmp_path):
        """Unit test run_programmatic_mov directly for error exit codes."""
        criterion = {
            "index": 1,
            "text": "Check",
            "mov_type": "programmatic",
            "mov_commands": [{"cmd": "nonexistent_xyz", "timeout": 5}],
            "agent_met": False,
            "reviewer_met": None,
        }

        mock_proc = MagicMock()
        mock_proc.returncode = 127
        mock_proc.stdout = ""
        mock_proc.stderr = "command not found"

        with patch("subprocess.run", return_value=mock_proc):
            with patch.object(hook, "run_kanban") as mock_kanban:
                with patch.object(hook, "log_info"):
                    with patch.object(hook, "log_error"):
                        diagnostic = hook.run_programmatic_mov(
                            criterion=criterion,
                            card_number="60",
                            session="sess-k",
                            git_root=str(tmp_path),
                        )

        assert diagnostic is not None, "Expected a diagnostic string for exit 127"
        assert "MoV ERROR" in diagnostic
        mock_kanban.assert_not_called()  # No pass/fail


# ---------------------------------------------------------------------------
# No transcript / no card found → fails open
# ---------------------------------------------------------------------------

class TestFailOpenBehavior:
    """Missing transcript or no card reference → fails open (allow)."""

    def test_missing_transcript_allows_stop(self, hook):
        payload = make_stop_payload(transcript_path="")
        result = run_process_stop(hook, payload)
        assert_allow(result)

    def test_nonexistent_transcript_allows_stop(self, hook):
        payload = make_stop_payload(transcript_path="/tmp/does-not-exist-transcript.jsonl")
        result = run_process_stop(hook, payload)
        assert_allow(result)

    def test_no_card_in_transcript_allows_stop(self, hook, tmp_transcript):
        """Transcript with no card reference → allows stop (not kanban-managed)."""
        entries = [{"role": "assistant", "content": "Some general output with no card reference."}]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)
        result = run_process_stop(hook, payload)
        assert_allow(result)


# ---------------------------------------------------------------------------
# Burns session skip
# ---------------------------------------------------------------------------

class TestBurnsSession:
    """BURNS_SESSION=1 → main() immediately allows stop."""

    def test_burns_session_allows_stop(self, hook):
        import io
        captured = []

        def fake_print(val, **kwargs):
            captured.append(val)

        payload = {"agent_transcript_path": "", "session_id": "x", "cwd": "/tmp"}
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with patch("builtins.print", side_effect=fake_print):
                with patch.dict(os.environ, {"BURNS_SESSION": "1"}, clear=False):
                    with patch.object(hook, "log_error"):
                        with patch.object(hook, "log_info"):
                            hook.main()

        assert captured, "Hook produced no output"
        result = json.loads(captured[-1])
        assert result.get("decision") == "allow"


# ---------------------------------------------------------------------------
# Transcript parsing unit tests
# ---------------------------------------------------------------------------

class TestTranscriptParsing:
    """Unit tests for extract_card_from_transcript."""

    def test_finds_card_from_header_pattern(self, hook, tmp_transcript):
        entries = [make_card_header_entry("77", "parse-session")]
        transcript = tmp_transcript(entries)
        result = hook.extract_card_from_transcript(transcript)
        assert result == ("77", "parse-session")

    def test_finds_card_from_xml_pattern(self, hook, tmp_transcript):
        entries = [
            {"role": "user", "content": '<card num="88" session="xml-session" status="doing">'}
        ]
        transcript = tmp_transcript(entries)
        result = hook.extract_card_from_transcript(transcript)
        assert result == ("88", "xml-session")

    def test_finds_card_from_kanban_cli_pattern(self, hook, tmp_transcript):
        entries = [
            {"role": "user", "content": "kanban criteria check 55 1 --session cli-session"}
        ]
        transcript = tmp_transcript(entries)
        result = hook.extract_card_from_transcript(transcript)
        assert result == ("55", "cli-session")

    def test_no_card_returns_none(self, hook, tmp_transcript):
        entries = [{"role": "assistant", "content": "Nothing about kanban here."}]
        transcript = tmp_transcript(entries)
        result = hook.extract_card_from_transcript(transcript)
        assert result is None


# ---------------------------------------------------------------------------
# Card-done-already path
# ---------------------------------------------------------------------------

class TestCardAlreadyDone:
    """Card already in done → allow immediately without AC review."""

    def test_card_already_done_allows_stop(self, hook, tmp_transcript):
        entries = [make_card_header_entry("90", "sess-done")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="done")
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        assert_allow(result)



# ---------------------------------------------------------------------------
# detect_criteria_gaming unit tests (F-01 — BLOCKING)
# ---------------------------------------------------------------------------

class TestCriteriaGaming:
    """Unit tests for detect_criteria_gaming() — anti-gaming gate."""

    def test_criteria_recheck_without_work_is_gaming(self, hook, tmp_transcript):
        """After a block-feedback message, only criteria rechecks → gaming detected."""
        feedback_entry = {
            "role": "user",
            "content": "AC review failed for card #42 — investigate each unchecked criterion.",
        }
        # Only criteria recheck after feedback — no substantive work
        recheck_entry = make_kanban_criteria_bash_entry("42", "test-session", n=1)

        entries = [
            make_card_header_entry("42", "test-session"),
            feedback_entry,
            recheck_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                result = hook.detect_criteria_gaming(transcript)

        assert result is True, "Expected gaming=True when only criteria rechecks after feedback"

    def test_substantive_work_after_feedback_not_gaming(self, hook, tmp_transcript):
        """After a block-feedback message, real tool use → NOT gaming."""
        feedback_entry = {
            "role": "user",
            "content": "AC review failed for card #42 — investigate each failed criterion.",
        }
        # Substantive work (Read) after feedback
        read_entry = make_substantive_tool_entry("Read")
        recheck_entry = make_kanban_criteria_bash_entry("42", "test-session", n=1)

        entries = [
            make_card_header_entry("42", "test-session"),
            feedback_entry,
            read_entry,
            recheck_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                result = hook.detect_criteria_gaming(transcript)

        assert result is False, "Expected gaming=False when real work done after feedback"

    def test_no_feedback_marker_not_gaming(self, hook, tmp_transcript):
        """Transcript with no block-feedback marker → cannot detect gaming (returns False)."""
        entries = [
            make_card_header_entry("42", "test-session"),
            make_kanban_criteria_bash_entry("42", "test-session", n=1),
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                result = hook.detect_criteria_gaming(transcript)

        assert result is False, "Expected gaming=False when no block-feedback marker in transcript"

    def test_mcp_tool_use_counts_as_substantive_work(self, hook, tmp_transcript):
        """MCP tool calls (mcp__ prefix) count as substantive work — not gaming."""
        feedback_entry = {
            "role": "user",
            "content": "unchecked acceptance criteria — investigate each unchecked criterion.",
        }
        # MCP tool use after feedback
        mcp_entry = {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "mcp__context7__query-docs",
                    "input": {"query": "pytest fixtures"},
                }
            ],
        }
        recheck_entry = make_kanban_criteria_bash_entry("42", "test-session", n=1)

        entries = [
            make_card_header_entry("42", "test-session"),
            feedback_entry,
            mcp_entry,
            recheck_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                result = hook.detect_criteria_gaming(transcript)

        assert result is False, "Expected gaming=False when MCP tool used after feedback"

    def test_only_feedback_no_subsequent_entries_not_gaming(self, hook, tmp_transcript):
        """Transcript ends at feedback with no subsequent entries → not gaming."""
        feedback_entry = {
            "role": "user",
            "content": "Anti-gaming gate triggered for card #42.",
        }
        entries = [
            make_card_header_entry("42", "test-session"),
            feedback_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                result = hook.detect_criteria_gaming(transcript)

        assert result is False, "Expected gaming=False when no entries after feedback"

    def test_nonexistent_transcript_returns_false(self, hook):
        """Nonexistent transcript file → returns False (fail open)."""
        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                result = hook.detect_criteria_gaming("/tmp/does-not-exist-xyz.jsonl")

        assert result is False, "Expected fail-open (False) for missing transcript"

    def test_edit_tool_after_feedback_not_gaming(self, hook, tmp_transcript):
        """Edit tool use after feedback → NOT gaming."""
        feedback_entry = {
            "role": "user",
            "content": "kanban review failed for card #42 — investigate each failed criterion.",
        }
        edit_entry = make_substantive_tool_entry("Edit")
        recheck_entry = make_kanban_criteria_bash_entry("42", "test-session", n=1)

        entries = [
            make_card_header_entry("42", "test-session"),
            feedback_entry,
            edit_entry,
            recheck_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                result = hook.detect_criteria_gaming(transcript)

        assert result is False


# ---------------------------------------------------------------------------
# detect_permission_stall unit tests (F-02 — HIGH)
# ---------------------------------------------------------------------------

class TestDetectPermissionStall:
    """Unit tests for detect_permission_stall() — permission-gate recovery."""

    def test_auto_denied_in_user_role_detected(self, hook, tmp_transcript):
        """'was automatically denied' in user-role tool_result → non-empty denied list."""
        denial_entry = {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": "This request was automatically denied by your current permissions settings.",
                }
            ],
        }
        entries = [
            make_card_header_entry("42", "test-session"),
            denial_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                denied = hook.detect_permission_stall(transcript)

        assert len(denied) > 0, "Expected at least one denial detected"

    def test_not_allowed_by_permissions_in_user_role_detected(self, hook, tmp_transcript):
        """'not allowed by.*permissions' phrase in user role → detected."""
        denial_entry = {
            "role": "user",
            "content": "Action not allowed by your current permissions configuration.",
        }
        entries = [
            make_card_header_entry("42", "test-session"),
            denial_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                denied = hook.detect_permission_stall(transcript)

        assert len(denied) > 0, "Expected denial detected for 'not allowed by' pattern"

    def test_denial_in_assistant_role_not_detected(self, hook, tmp_transcript):
        """Same denial phrase in assistant-role content → NOT detected (role filter)."""
        # The hook only looks at user-role entries
        assistant_denial_entry = {
            "role": "assistant",
            "content": "I see the request was automatically denied by permissions.",
        }
        entries = [
            make_card_header_entry("42", "test-session"),
            assistant_denial_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                denied = hook.detect_permission_stall(transcript)

        assert len(denied) == 0, "Expected no detection in assistant-role content (role filter)"

    def test_empty_transcript_returns_empty_list(self, hook, tmp_transcript):
        """Transcript with no entries → empty denied list."""
        transcript = tmp_transcript([])

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                denied = hook.detect_permission_stall(transcript)

        assert denied == [], "Expected empty list for empty transcript"

    def test_nonexistent_transcript_returns_empty_list(self, hook):
        """Nonexistent transcript file → empty list (fail open)."""
        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                denied = hook.detect_permission_stall("/tmp/no-such-file-xyz.jsonl")

        assert denied == [], "Expected empty list (fail open) for missing transcript"

    def test_corrupt_jsonl_returns_empty_list(self, hook, tmp_transcript):
        """Corrupt JSONL lines → gracefully returns empty list (fail open)."""
        import json

        def corrupt_transcript(tmp_path):
            p = tmp_path / "corrupt.jsonl"
            p.write_text("{bad line 1}\n{bad line 2}\n")
            return str(p)

        # Use pytest tmp_path directly
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("{bad line\n")
            f.write("not json at all\n")
            corrupt_path = f.name

        try:
            with patch.object(hook, "log_info"):
                with patch.object(hook, "log_error"):
                    denied = hook.detect_permission_stall(corrupt_path)
        finally:
            import os
            os.unlink(corrupt_path)

        assert denied == [], "Expected empty list for corrupt JSONL (fail open)"

    def test_clean_transcript_no_denials_returns_empty(self, hook, tmp_transcript):
        """Normal transcript with no permission denials → empty list."""
        entries = [
            make_card_header_entry("42", "test-session"),
            make_substantive_tool_entry("Read"),
            make_kanban_criteria_bash_entry("42", "test-session", n=1),
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                denied = hook.detect_permission_stall(transcript)

        assert denied == []


# ---------------------------------------------------------------------------
# extract_agent_output unit tests (F-07 — MEDIUM)
# ---------------------------------------------------------------------------

class TestExtractAgentOutput:
    """Unit tests for extract_agent_output() — transcript output parsing."""

    def test_string_content_returns_string(self, hook, tmp_transcript):
        """Transcript with assistant string content → returns that string."""
        entries = [
            make_card_header_entry("42", "test-session"),
            {
                "role": "assistant",
                "content": "This is the agent's final output with findings.",
            },
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_error"):
            result = hook.extract_agent_output(transcript)

        assert result == "This is the agent's final output with findings."

    def test_list_of_text_blocks_returns_joined_text(self, hook, tmp_transcript):
        """Transcript with list-of-text-blocks content → returns joined text."""
        entries = [
            make_card_header_entry("42", "test-session"),
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "First paragraph."},
                    {"type": "text", "text": "Second paragraph."},
                ],
            },
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_error"):
            result = hook.extract_agent_output(transcript)

        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_only_tool_use_blocks_returns_empty(self, hook, tmp_transcript):
        """Transcript where assistant only uses tool_use blocks → empty string."""
        entries = [
            make_card_header_entry("42", "test-session"),
            make_substantive_tool_entry("Read"),
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_error"):
            result = hook.extract_agent_output(transcript)

        assert result == "", f"Expected empty string for tool-only transcript, got: {result!r}"

    def test_empty_transcript_returns_empty(self, hook, tmp_transcript):
        """Empty transcript → returns empty string."""
        transcript = tmp_transcript([])

        with patch.object(hook, "log_error"):
            result = hook.extract_agent_output(transcript)

        assert result == ""

    def test_nonexistent_transcript_returns_empty(self, hook):
        """Nonexistent transcript file → returns empty string (fail open)."""
        with patch.object(hook, "log_error"):
            result = hook.extract_agent_output("/tmp/no-such-file-xyz.jsonl")

        assert result == ""

    def test_returns_last_assistant_content(self, hook, tmp_transcript):
        """When multiple assistant messages exist, returns content of the LAST one."""
        entries = [
            make_card_header_entry("42", "test-session"),
            {"role": "assistant", "content": "First assistant message."},
            {"role": "user", "content": "User follow-up."},
            {"role": "assistant", "content": "Final agent output here."},
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_error"):
            result = hook.extract_agent_output(transcript)

        assert result == "Final agent output here.", (
            f"Expected last assistant message, got: {result!r}"
        )

    def test_tool_use_blocks_not_included_in_output(self, hook, tmp_transcript):
        """tool_use blocks in list content are filtered out; only text blocks matter."""
        entries = [
            make_card_header_entry("42", "test-session"),
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/f"}},
                    {"type": "text", "text": "Analysis complete. Files look good."},
                ],
            },
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_error"):
            result = hook.extract_agent_output(transcript)

        assert "Analysis complete. Files look good." in result


# ---------------------------------------------------------------------------
# Auto-uncheck before redo (F5 — MEDIUM)
# ---------------------------------------------------------------------------

class TestAutoUncheckBeforeRedo:
    """kanban criteria uncheck must be called for each failing criterion BEFORE kanban redo."""

    def test_auto_uncheck_called_before_redo(self, hook, tmp_transcript):
        """When a programmatic MoV fails, uncheck is called before redo — in that order.

        If the auto-uncheck block at process_subagent_stop were deleted, this test must fail:
        no uncheck call would appear in the ordered call log before redo.
        """
        entries = [make_card_header_entry("70", "sess-uncheck")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Card in review with one failing programmatic criterion
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="70",
            session="sess-uncheck",
            status="review",
            review_cycles=0,
            criteria=[
                {"text": "Must be fixed", "mov_type": "programmatic",
                 "mov_commands": [{"cmd": "test -f /missing", "timeout": 5}],
                 "reviewer_met": "fail"},
            ],
        )

        # Track all kanban subcommand calls in order
        ordered_kanban_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                ordered_kanban_calls.append(list(cmd))
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="review")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=1)
                if sub in ("redo", "criteria"):
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            # Shell command: "test -f /missing" exits 1
            if isinstance(cmd, str) and "test -f" in cmd:
                m = MagicMock()
                m.returncode = 1
                m.stdout = ""
                m.stderr = ""
                return m
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert_block(result)

        # Extract uncheck and redo positions from the ordered call log
        uncheck_indices = [
            i for i, c in enumerate(ordered_kanban_calls)
            if len(c) > 2 and c[1] == "criteria" and c[2] == "uncheck"
        ]
        redo_indices = [
            i for i, c in enumerate(ordered_kanban_calls)
            if c[1] == "redo"
        ]

        assert len(uncheck_indices) >= 1, (
            f"Expected at least one 'kanban criteria uncheck' call, but none found. "
            f"Ordered calls: {ordered_kanban_calls}"
        )
        assert len(redo_indices) >= 1, (
            f"Expected at least one 'kanban redo' call, but none found. "
            f"Ordered calls: {ordered_kanban_calls}"
        )

        last_uncheck = max(uncheck_indices)
        first_redo = min(redo_indices)
        assert last_uncheck < first_redo, (
            f"Expected all uncheck calls to precede redo, but last uncheck at index "
            f"{last_uncheck} is not before first redo at index {first_redo}. "
            f"Ordered calls: {ordered_kanban_calls}"
        )


# ---------------------------------------------------------------------------
# LOCKED PASSED / MUST FIX partition in block reason (F6 — MEDIUM)
# ---------------------------------------------------------------------------

class TestLockedPassedMustFixPartition:
    """Block reason on redo must partition criteria into LOCKED PASSED and MUST FIX sections."""

    def test_block_reason_contains_locked_passed_and_must_fix_sections(self, hook, tmp_transcript):
        """Mixed-state card (one passing, one failing programmatic MoV) → block reason includes both sections.

        Asserts:
        - LOCKED PASSED section lists the passing criterion
        - MUST FIX section lists the failing criterion
        - LOCKED PASSED section does NOT include the failing criterion
        """
        entries = [make_card_header_entry("71", "sess-partition")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Card in review: criterion 1 passed (reviewer_met=pass), criterion 2 failed (reviewer_met=fail)
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="71",
            session="sess-partition",
            status="review",
            review_cycles=0,
            criteria=[
                {"text": "Already done criterion", "mov_type": "programmatic",
                 "mov_commands": [{"cmd": "true", "timeout": 5}],
                 "reviewer_met": "pass"},
                {"text": "Broken criterion", "mov_type": "programmatic",
                 "mov_commands": [{"cmd": "test -f /missing", "timeout": 5}],
                 "reviewer_met": "fail"},
            ],
        )

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="review")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=1)
                if sub in ("redo", "criteria"):
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            if isinstance(cmd, str) and cmd.strip() == "true":
                return KanbanMockResponses.success()
            if isinstance(cmd, str) and "test -f" in cmd:
                m = MagicMock()
                m.returncode = 1
                m.stdout = ""
                m.stderr = ""
                return m
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert_block(result)
        reason = result.get("reason", "")

        assert "LOCKED PASSED" in reason, (
            f"Expected 'LOCKED PASSED' section in block reason. Got:\n{reason}"
        )
        assert "MUST FIX" in reason, (
            f"Expected 'MUST FIX' section in block reason. Got:\n{reason}"
        )
        assert "Already done criterion" in reason, (
            f"Expected passing criterion text in LOCKED PASSED section. Got:\n{reason}"
        )
        assert "Broken criterion" in reason, (
            f"Expected failing criterion text in MUST FIX section. Got:\n{reason}"
        )

        # Verify the partition is clean: passing criterion should NOT appear in MUST FIX,
        # and failing criterion should NOT appear in LOCKED PASSED.
        locked_section_start = reason.find("LOCKED PASSED")
        must_fix_section_start = reason.find("MUST FIX")

        # Passing criterion should appear before MUST FIX (i.e., in LOCKED PASSED section)
        passing_text_pos = reason.find("Already done criterion")
        assert passing_text_pos < must_fix_section_start, (
            f"'Already done criterion' should appear in LOCKED PASSED (before MUST FIX), "
            f"but found at position {passing_text_pos} vs MUST FIX at {must_fix_section_start}. "
            f"Reason:\n{reason}"
        )

        # Failing criterion should appear after LOCKED PASSED (i.e., in MUST FIX section)
        failing_text_pos = reason.find("Broken criterion")
        assert failing_text_pos > locked_section_start, (
            f"'Broken criterion' should appear after LOCKED PASSED section, "
            f"but found at position {failing_text_pos} vs LOCKED PASSED at {locked_section_start}. "
            f"Reason:\n{reason}"
        )
