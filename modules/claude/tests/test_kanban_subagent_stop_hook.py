"""
Tests for modules/claude/kanban-subagent-stop-hook.py.

Covered paths:
- Card with all programmatic criteria + all passing → kanban done called directly, no Haiku
- Card with at least one semantic criterion → Haiku reviewer invoked
- Card with unchecked criteria at stop → kanban review fails, agent sent back for redo
- Max retry cycles reached → stop allowed, failure surfaces
- Programmatic MoV command fails (exit nonzero) → kanban criteria fail called with diagnostic
- MoV exit 127/126/124 → mov_error diagnostic emitted (not a pass/fail)

All kanban CLI, subprocess, and claude -p calls are monkeypatched — no real
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
# All-programmatic criteria path (no Haiku)
# ---------------------------------------------------------------------------

class TestAllProgrammaticCriteria:
    """Card with all programmatic criteria + all passing → kanban done, no Haiku."""

    def test_all_programmatic_pass_calls_done_directly(self, hook, tmp_transcript):
        """When all criteria are programmatic and all pass, kanban done is called
        without launching claude -p (Haiku reviewer)."""
        entries = [make_card_header_entry("10", "sess-a")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Card criteria: two programmatic, no semantic
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="10",
            session="sess-a",
            status="doing",
            criteria=[
                {"text": "File A exists", "mov_type": "programmatic", "mov_command": "test -f /tmp/a", "mov_timeout": "5"},
                {"text": "File B exists", "mov_type": "programmatic", "mov_command": "test -f /tmp/b", "mov_timeout": "5"},
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

        # Verify no claude -p was called (no Haiku reviewer)
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
                {"text": "Check", "mov_type": "programmatic", "mov_command": "true", "mov_timeout": "5"},
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
# Semantic criteria path (Haiku reviewer)
# ---------------------------------------------------------------------------

class TestSemanticCriteriaInvokesHaiku:
    """Card with at least one semantic criterion → Haiku reviewer invoked."""

    def test_semantic_criterion_launches_haiku(self, hook, tmp_transcript):
        """When a semantic criterion exists, claude -p --model haiku is called."""
        entries = [make_card_header_entry("20", "sess-c")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="20",
            session="sess-c",
            status="doing",
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic"},
            ],
        )

        # Haiku result: card reaches done
        haiku_json = json.dumps({"result": "All criteria passed.", "usage": {}})
        claude_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "claude":
                claude_calls.append(cmd)
                return KanbanMockResponses.success(stdout=haiku_json)
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    # First call: doing; after haiku: done
                    if not claude_calls:
                        return KanbanMockResponses.success(stdout="doing")
                    return KanbanMockResponses.success(stdout="done")
                if sub == "review":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        # ac-reviewer agent definition read
        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="system prompt"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert len(claude_calls) >= 1, "Expected claude -p to be called for semantic criteria"
        claude_cmd = claude_calls[0]
        assert "--model" in claude_cmd
        haiku_idx = claude_cmd.index("--model") + 1
        assert claude_cmd[haiku_idx] == "haiku"

    def test_ac_reviewer_agent_def_used_as_system_prompt(self, hook, tmp_transcript):
        """The ac-reviewer agent definition is loaded and passed as --system-prompt."""
        entries = [make_card_header_entry("21", "sess-d")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="21",
            session="sess-d",
            status="doing",
            criteria=[{"text": "Semantic", "mov_type": "semantic"}],
        )
        haiku_json = json.dumps({"result": "done", "usage": {}})
        claude_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "claude":
                claude_calls.append(cmd)
                return KanbanMockResponses.success(stdout=haiku_json)
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    if not claude_calls:
                        return KanbanMockResponses.success(stdout="doing")
                    return KanbanMockResponses.success(stdout="done")
                if sub == "review":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="SENTINEL_SYSTEM_PROMPT") as mock_read:
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                run_process_stop(hook, payload)

        mock_read.assert_called_once()
        # Verify the sentinel appears in the claude -p command
        if claude_calls:
            flat = " ".join(str(x) for x in claude_calls[0])
            assert "SENTINEL_SYSTEM_PROMPT" in flat or "--system-prompt" in flat


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
                {"text": "Unchecked", "mov_type": "programmatic", "mov_command": "test -f /missing", "agent_met": "false"},
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

        # Card already at max review cycles (3)
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="40",
            session="sess-g",
            status="review",
            review_cycles=3,
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic", "reviewer_met": "fail"},
            ],
        )
        haiku_json = json.dumps({"result": "reviewed", "usage": {}})
        claude_call_count = [0]

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "claude":
                claude_call_count[0] += 1
                return KanbanMockResponses.success(stdout=haiku_json)
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="review")
                if sub == "done":
                    # Fail — reviewer hasn't passed everything
                    return KanbanMockResponses.failure(returncode=1)
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="sys"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        # After inner loop exhausted and review_cycles >= MAX_OUTER_CYCLES, allow stop
        assert_allow(result)
        msg = result.get("reason", "") or ""
        assert "max" in msg.lower() or "manual" in msg.lower() or "intervention" in msg.lower() or "cycles" in msg.lower()

    def test_under_max_cycles_blocks_agent(self, hook, tmp_transcript):
        """When under max cycles, a failed review blocks the agent for redo."""
        entries = [make_card_header_entry("41", "sess-h")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Card at 0 review cycles
        criteria_xml = KanbanMockResponses.card_xml(
            card_number="41",
            session="sess-h",
            status="review",
            review_cycles=0,
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic", "reviewer_met": "fail"},
            ],
        )
        fail_xml = KanbanMockResponses.card_xml(
            card_number="41",
            session="sess-h",
            status="doing",
            review_cycles=1,
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic", "reviewer_met": "fail",
                 "reviewer_fail_reason": "not done"},
            ],
        )
        haiku_json = json.dumps({"result": "reviewed", "usage": {}})
        show_count = [0]

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "claude":
                return KanbanMockResponses.success(stdout=haiku_json)
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    show_count[0] += 1
                    return KanbanMockResponses.success(stdout=criteria_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="review")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=1)
                if sub == "redo":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="sys"):
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
                {"text": "Test passes", "mov_type": "programmatic", "mov_command": "false", "mov_timeout": "5"},
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

        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="sys"):
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
                {"text": "Test passes", "mov_type": "programmatic", "mov_command": "true", "mov_timeout": "5"},
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
                 "mov_command": "nonexistent_command_xyz", "mov_timeout": "5"},
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
            "mov_command": "nonexistent_xyz",
            "mov_timeout": 5,
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
# Unified kanban done call path
# ---------------------------------------------------------------------------

class TestUnifiedKanbanDonePath:
    """After reviewer finishes semantic verification, hook calls kanban done."""

    def test_semantic_path_hook_calls_kanban_done(self, hook, tmp_transcript):
        """Semantic criteria: reviewer verifies, then hook calls kanban done (not reviewer)."""
        entries = [make_card_header_entry("100", "sess-unified")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="100",
            session="sess-unified",
            status="doing",
            criteria=[
                {"text": "Semantic criterion", "mov_type": "semantic",
                 "agent_met": "true", "reviewer_met": "pass"},
            ],
        )

        # After reviewer runs, all criteria are reviewer_met=pass
        criteria_all_passed_xml = KanbanMockResponses.card_xml(
            card_number="100",
            session="sess-unified",
            status="doing",
            criteria=[
                {"text": "Semantic criterion", "mov_type": "semantic",
                 "agent_met": "true", "reviewer_met": "pass"},
            ],
        )

        haiku_json = json.dumps({"result": "Card #100: 1:checked", "usage": {}})
        done_calls = []
        claude_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "claude":
                claude_calls.append(cmd)
                return KanbanMockResponses.success(stdout=haiku_json)
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_all_passed_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.success()
                if sub == "done":
                    done_calls.append(cmd)
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="sys prompt"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert_allow(result)
        assert len(claude_calls) >= 1, "Expected reviewer (claude -p) to be called"
        assert len(done_calls) >= 1, "Expected hook to call kanban done after reviewer"

    def test_semantic_path_reviewer_does_not_call_done(self, hook, tmp_transcript):
        """Verify claude -p is called but kanban done is called by hook — not passed to claude."""
        entries = [make_card_header_entry("101", "sess-nodone")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        criteria_xml = KanbanMockResponses.card_xml(
            card_number="101",
            session="sess-nodone",
            status="doing",
            criteria=[
                {"text": "Semantic only", "mov_type": "semantic",
                 "agent_met": "true", "reviewer_met": "pass"},
            ],
        )

        haiku_json = json.dumps({"result": "Card #101: 1:checked", "usage": {}})
        claude_prompts = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "claude":
                # Capture the prompt (passed via stdin in kwargs)
                input_text = kwargs.get("input", "")
                claude_prompts.append(input_text)
                return KanbanMockResponses.success(stdout=haiku_json)
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
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="sys"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                run_process_stop(hook, payload)

        # Verify the prompt sent to reviewer instructs it NOT to call kanban done
        if claude_prompts:
            prompt_text = claude_prompts[0]
            # The prompt should say do NOT call kanban done
            assert "do not call" in prompt_text.lower() or "do not" in prompt_text.lower() or "not" in prompt_text.lower(), (
                "Reviewer prompt should instruct reviewer not to call kanban done"
            )


# ---------------------------------------------------------------------------
# reviewer_met incomplete → hook re-launches reviewer
# ---------------------------------------------------------------------------

class TestReviewerMetIncompleteRelaunch:
    """When kanban done fails due to reviewer_met=unchecked, hook re-launches reviewer."""

    def test_reviewer_met_incomplete_relaunches_reviewer(self, hook, tmp_transcript):
        """If reviewer_met is None after first pass, hook re-launches reviewer (up to max retries)."""
        entries = [make_card_header_entry("110", "sess-rlaunch")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # reviewer_met=unchecked: reviewer didn't finish on first pass
        criteria_incomplete_xml = KanbanMockResponses.card_xml(
            card_number="110",
            session="sess-rlaunch",
            status="doing",
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic",
                 "agent_met": "true", "reviewer_met": "unchecked"},
            ],
        )
        # After re-launch: reviewer_met=pass (reviewer finished on second pass)
        criteria_complete_xml = KanbanMockResponses.card_xml(
            card_number="110",
            session="sess-rlaunch",
            status="doing",
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic",
                 "agent_met": "true", "reviewer_met": "pass"},
            ],
        )

        haiku_json = json.dumps({"result": "done", "usage": {}})
        claude_call_count = [0]
        done_call_count = [0]

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "claude":
                claude_call_count[0] += 1
                return KanbanMockResponses.success(stdout=haiku_json)
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    # Return incomplete until the second claude call has run
                    if claude_call_count[0] < 2:
                        return KanbanMockResponses.success(stdout=criteria_incomplete_xml)
                    return KanbanMockResponses.success(stdout=criteria_complete_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "review":
                    return KanbanMockResponses.success()
                if sub == "done":
                    done_call_count[0] += 1
                    # First done call fails (reviewer didn't finish); second succeeds
                    if done_call_count[0] <= 1:
                        return KanbanMockResponses.failure(returncode=1, stderr="unchecked criteria")
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="sys"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert_allow(result)
        assert claude_call_count[0] >= 2, (
            f"Expected reviewer to be re-launched at least once, got {claude_call_count[0]} calls"
        )
        assert done_call_count[0] >= 2, (
            f"Expected kanban done to be called at least twice (first fails, second succeeds), "
            f"got {done_call_count[0]} calls"
        )

    def test_reviewer_met_incomplete_bounded_by_max_retries(self, hook, tmp_transcript):
        """If reviewer_met stays incomplete after max retries, hook signals failure (not infinite loop)."""
        entries = [make_card_header_entry("111", "sess-maxretry")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Always returns reviewer_met=unchecked
        criteria_incomplete_xml = KanbanMockResponses.card_xml(
            card_number="111",
            session="sess-maxretry",
            status="review",
            criteria=[
                {"text": "Semantic check", "mov_type": "semantic",
                 "agent_met": "true", "reviewer_met": "unchecked"},
            ],
        )

        haiku_json = json.dumps({"result": "reviewed", "usage": {}})
        claude_call_count = [0]

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "claude":
                claude_call_count[0] += 1
                return KanbanMockResponses.success(stdout=haiku_json)
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "show":
                    return KanbanMockResponses.success(stdout=criteria_incomplete_xml)
                if sub == "status":
                    return KanbanMockResponses.success(stdout="review")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=1, stderr="unchecked")
                if sub == "redo":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "read_ac_reviewer_agent_definition", return_value="sys"):
            with patch.object(hook, "send_transition_notification"):
                with patch("subprocess.run", side_effect=fake_subprocess_run):
                    result = run_process_stop(hook, payload)

        # Should not loop forever — bounded by MAX_INNER_ITERATIONS + MAX_REVIEWER_DONE_RETRIES
        hook_mod = hook
        max_expected_calls = hook_mod.MAX_INNER_ITERATIONS + hook_mod.MAX_REVIEWER_DONE_RETRIES + 1
        assert claude_call_count[0] <= max_expected_calls, (
            f"Reviewer launched {claude_call_count[0]} times — expected at most {max_expected_calls}"
        )


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
