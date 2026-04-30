"""
Tests for modules/claude/kanban-subagent-stop-hook.py.

Covered paths:
- Card identified from transcript → kanban done called
- kanban done exit 0 → allow with success notification
- kanban done exit 1 → block with kanban's stderr/stdout as feedback
- kanban done exit 2 → allow with max-cycles surface notification
- kanban done other exit → block with error
- Permission stall detection: ≥2 denials → allow with stall diagnostic
- Anti-gaming detection: criteria recheck without substantive work → block
- No transcript / no card found → fails open (allow)
- Burns session → allow immediately

All kanban CLI and subprocess calls are monkeypatched — no real
kanban cards are created or read during these tests.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
# kanban done exit 0 → allow
# ---------------------------------------------------------------------------

class TestKanbanDoneExitZero:
    """kanban done exit 0 → hook returns allow with success notification."""

    def test_done_exit_0_returns_allow(self, hook, tmp_transcript):
        """When kanban done exits 0, process_subagent_stop returns allow."""
        entries = [make_card_header_entry("10", "sess-a")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.success(stdout="Card #10 done.")
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert_allow(result)

    def test_done_exit_0_calls_done_notification(self, hook, tmp_transcript):
        """When kanban done exits 0, a 'done' macOS notification is sent."""
        entries = [make_card_header_entry("11", "sess-b")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        notification_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        def fake_notify(card_number, new_state, intent):
            notification_calls.append((card_number, new_state))

        with patch.object(hook, "send_transition_notification", side_effect=fake_notify):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert_allow(result)
        done_notifications = [c for c in notification_calls if c[1] == "done"]
        assert len(done_notifications) >= 1, (
            f"Expected a 'done' notification, but got: {notification_calls}"
        )

    def test_done_exit_0_kanban_done_called(self, hook, tmp_transcript):
        """kanban done is called with card number and session."""
        entries = [make_card_header_entry("12", "sess-c")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        done_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    done_calls.append(cmd)
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                run_process_stop(hook, payload)

        assert len(done_calls) >= 1, "Expected kanban done to be called"
        done_cmd = done_calls[0]
        assert "12" in done_cmd, f"Expected card number 12 in done call: {done_cmd}"
        assert "--session" in done_cmd, f"Expected --session in done call: {done_cmd}"
        assert "sess-c" in done_cmd, f"Expected session name in done call: {done_cmd}"


# ---------------------------------------------------------------------------
# kanban done exit 1 → block with kanban feedback
# ---------------------------------------------------------------------------

class TestKanbanDoneExitOne:
    """kanban done exit 1 → hook returns block with kanban's stderr/stdout as feedback."""

    def test_done_exit_1_returns_block(self, hook, tmp_transcript):
        """When kanban done exits 1, process_subagent_stop returns block."""
        entries = [make_card_header_entry("20", "sess-d")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(
                        returncode=1,
                        stderr="Cycle 1/3. Unchecked: 'foo bar'",
                    )
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        assert_block(result)

    def test_done_exit_1_block_reason_contains_kanban_output(self, hook, tmp_transcript):
        """Block reason must contain kanban's stderr/stdout verbatim."""
        entries = [make_card_header_entry("21", "sess-e")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        kanban_message = "Cycle 2/3. Unchecked: 'missing file check'"

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(
                        returncode=1,
                        stderr=kanban_message,
                    )
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        reason = result.get("reason", "")
        assert kanban_message in reason, (
            f"Expected kanban's message verbatim in block reason. Got:\n{reason}"
        )

    def test_done_exit_1_block_reason_contains_guidance(self, hook, tmp_transcript):
        """Block reason should instruct agent to investigate and re-check."""
        entries = [make_card_header_entry("22", "sess-f")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=1, stderr="some criteria unchecked")
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        reason = result.get("reason", "").lower()
        assert "investigate" in reason or "unchecked" in reason, (
            f"Expected guidance in block reason. Got:\n{reason}"
        )


# ---------------------------------------------------------------------------
# kanban done exit 2 → allow with max-cycles notification
# ---------------------------------------------------------------------------

class TestKanbanDoneExitTwo:
    """kanban done exit 2 → hook returns allow with max-cycles surface notification."""

    def test_done_exit_2_returns_allow(self, hook, tmp_transcript):
        """When kanban done exits 2, process_subagent_stop returns allow."""
        entries = [make_card_header_entry("30", "sess-g")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(
                        returncode=2,
                        stderr="Max cycles reached. Unchecked: 'foo bar'. Surfacing to staff.",
                    )
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        assert_allow(result)

    def test_done_exit_2_reason_contains_max_cycles(self, hook, tmp_transcript):
        """Allow reason for exit 2 must reference max cycles or manual intervention."""
        entries = [make_card_header_entry("31", "sess-h")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        kanban_message = "Max cycles reached. Unchecked: 'test criterion'. Surfacing to staff."

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=2, stderr=kanban_message)
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        reason = result.get("reason", "").lower()
        assert "max" in reason or "manual" in reason or "cycles" in reason or "staff" in reason, (
            f"Expected max-cycles language in allow reason. Got:\n{reason}"
        )

    def test_done_exit_2_reason_contains_kanban_output(self, hook, tmp_transcript):
        """Allow reason for exit 2 must include kanban's stderr/stdout."""
        entries = [make_card_header_entry("32", "sess-i")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        kanban_message = "Max cycles reached. Unchecked: 'specific criterion'."

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=2, stderr=kanban_message)
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        reason = result.get("reason", "")
        assert kanban_message in reason, (
            f"Expected kanban's message in allow reason. Got:\n{reason}"
        )


# ---------------------------------------------------------------------------
# kanban done other exit codes → block with error
# ---------------------------------------------------------------------------

class TestKanbanDoneOtherExit:
    """kanban done returns unexpected exit code → hook returns block with error."""

    @pytest.mark.parametrize("exit_code", [3, 42, 124, 127])
    def test_done_other_exit_returns_block(self, hook, tmp_transcript, exit_code):
        """Any exit code other than 0, 1, 2 → block with error description."""
        entries = [make_card_header_entry("40", "sess-j")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(returncode=exit_code, stderr="unexpected error")
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        assert_block(result)


# ---------------------------------------------------------------------------
# Permission stall detection
# ---------------------------------------------------------------------------

class TestPermissionStallDetection:
    """Permission stall: ≥2 denials → allow with stall diagnostic."""

    def test_two_denials_triggers_stall_allow(self, hook, tmp_transcript):
        """Two Bash auto-denials → process_subagent_stop returns allow with stall message."""
        denial_entry_1 = {
            "role": "user",
            "content": "This request was automatically denied by your current permissions settings.",
        }
        denial_entry_2 = {
            "role": "user",
            "content": "This action was automatically denied by permissions.",
        }
        entries = [
            make_card_header_entry("50", "sess-stall"),
            denial_entry_1,
            denial_entry_2,
        ]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        assert_allow(result)
        reason = result.get("reason", "").lower()
        assert "permission" in reason or "stall" in reason or "denied" in reason, (
            f"Expected stall language in allow reason. Got:\n{reason}"
        )

    def test_one_denial_does_not_trigger_stall(self, hook, tmp_transcript):
        """Single denial does not trigger stall short-circuit."""
        denial_entry = {
            "role": "user",
            "content": "This request was automatically denied by your current permissions settings.",
        }
        entries = [
            make_card_header_entry("51", "sess-one-denial"),
            denial_entry,
        ]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        done_called = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    done_called.append(cmd)
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                run_process_stop(hook, payload)

        # With only one denial, the hook should proceed to kanban done
        assert len(done_called) >= 1, (
            "Expected kanban done to be called when only one denial present"
        )

    def test_stall_only_fires_when_card_in_doing(self, hook, tmp_transcript):
        """Permission stall check only short-circuits if card is in 'doing' status."""
        denial_entry_1 = {
            "role": "user",
            "content": "This request was automatically denied.",
        }
        denial_entry_2 = {
            "role": "user",
            "content": "This action was automatically denied by permissions.",
        }
        entries = [
            make_card_header_entry("52", "sess-stall-done"),
            denial_entry_1,
            denial_entry_2,
        ]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        done_called = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                # Card is already done — stall check should not fire
                if sub == "status":
                    return KanbanMockResponses.success(stdout="done")
                if sub == "done":
                    done_called.append(cmd)
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        # Card in 'done' — stall check doesn't fire; kanban done is called
        assert len(done_called) >= 1 or result.get("decision") == "allow", (
            "Expected allow or kanban done call when card is in 'done' status"
        )


# ---------------------------------------------------------------------------
# Anti-gaming detection
# ---------------------------------------------------------------------------

class TestAntiGamingDetection:
    """Anti-gaming: criteria recheck without substantive work → block."""

    def test_gaming_detected_returns_block(self, hook, tmp_transcript):
        """After a block-feedback, only criteria rechecks → block with anti-gaming message."""
        feedback_entry = {
            "role": "user",
            "content": "AC review failed for card #60 — investigate each unchecked criterion.",
        }
        # Only criteria recheck after feedback — no substantive work
        recheck_entry = make_kanban_criteria_bash_entry("60", "sess-gaming", n=1)

        entries = [
            make_card_header_entry("60", "sess-gaming"),
            feedback_entry,
            recheck_entry,
        ]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "show":
                    return KanbanMockResponses.success(stdout=(
                        '<card num="60" session="sess-gaming" status="doing" review-cycles="0">'
                        '  <acceptance-criteria>'
                        '    <ac agent-met="true">Some criterion</ac>'
                        '  </acceptance-criteria>'
                        '</card>'
                    ))
                if sub == "criteria":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_process_stop(hook, payload)

        assert_block(result, "anti-gaming")

    def test_gaming_uncheck_called_on_gaming(self, hook, tmp_transcript):
        """When gaming is detected, kanban criteria uncheck is called."""
        feedback_entry = {
            "role": "user",
            "content": "AC review failed for card #61 — investigate each unchecked criterion.",
        }
        recheck_entry = make_kanban_criteria_bash_entry("61", "sess-gaming2", n=1)

        entries = [
            make_card_header_entry("61", "sess-gaming2"),
            feedback_entry,
            recheck_entry,
        ]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        uncheck_calls = []

        card_xml = (
            '<card num="61" session="sess-gaming2" status="doing" review-cycles="0">'
            '  <acceptance-criteria>'
            '    <ac agent-met="true">Criterion one</ac>'
            '  </acceptance-criteria>'
            '</card>'
        )

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "show":
                    return KanbanMockResponses.success(stdout=card_xml)
                if sub == "criteria" and len(cmd) > 2 and cmd[2] == "uncheck":
                    uncheck_calls.append(cmd)
                    return KanbanMockResponses.success()
                if sub == "criteria":
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            run_process_stop(hook, payload)

        assert len(uncheck_calls) >= 1, (
            f"Expected kanban criteria uncheck to be called on gaming. Got: {uncheck_calls}"
        )

    def test_substantive_work_after_feedback_not_gaming(self, hook, tmp_transcript):
        """After feedback, real tool use → NOT gaming → proceeds to kanban done."""
        feedback_entry = {
            "role": "user",
            "content": "AC review failed for card #62 — investigate each failed criterion.",
        }
        # Substantive work (Read) after feedback, then criteria check
        read_entry = make_substantive_tool_entry("Read")
        recheck_entry = make_kanban_criteria_bash_entry("62", "sess-legit", n=1)

        entries = [
            make_card_header_entry("62", "sess-legit"),
            feedback_entry,
            read_entry,
            recheck_entry,
        ]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        done_called = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    done_called.append(cmd)
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        # With legitimate work, no gaming block — proceeds to kanban done
        assert len(done_called) >= 1, (
            "Expected kanban done to be called when substantive work done after feedback"
        )


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
# Card already done
# ---------------------------------------------------------------------------

class TestCardAlreadyDone:
    """Card already in done → allow immediately without calling kanban done again."""

    def test_card_already_done_allows_stop(self, hook, tmp_transcript):
        entries = [make_card_header_entry("90", "sess-done")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        done_calls = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="done")
                if sub == "done":
                    done_calls.append(cmd)
                    return KanbanMockResponses.success()
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        # Card in done: stall check skips (status != "doing"), proceeds to kanban done
        # which succeeds (exit 0), so allow is returned.
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
# detect_criteria_gaming unit tests
# ---------------------------------------------------------------------------

class TestCriteriaGaming:
    """Unit tests for detect_criteria_gaming() — anti-gaming gate."""

    def test_criteria_recheck_without_work_is_gaming(self, hook, tmp_transcript):
        """After a block-feedback message, only criteria rechecks → gaming detected."""
        feedback_entry = {
            "role": "user",
            "content": "AC review failed for card #42 — investigate each unchecked criterion.",
        }
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
# detect_permission_stall unit tests
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

    def test_corrupt_jsonl_returns_empty_list(self, hook):
        """Corrupt JSONL lines → gracefully returns empty list (fail open)."""
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
# extract_agent_output unit tests
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
# Hedge-word audit unit tests
# ---------------------------------------------------------------------------

# A sufficiently long text (>= 200 chars) with no hedge words — the baseline.
_CLEAN_RETURN = (
    "The implementation is complete. "
    "The file src/config.py:42 defines the timeout constant. "
    "The handler at src/handler.py:18 uses the constant directly. "
    "Integration tests at tests/test_handler.py:55 verify the behavior end-to-end. "
    "All criteria are satisfied by the code as written."
)

# A sufficiently long text with multiple hedge words but no citations.
_HEDGED_NO_CITATIONS = (
    "The implementation is essentially complete and should work for the use case. "
    "The daemon basically registers the handler, which effectively means it will "
    "generally respond to incoming events. The behavior is roughly as expected and "
    "likely covers all the cases described in the acceptance criteria. "
    "The code appears to handle edge cases and should be fine in production. "
    "Overall the feature is conceptually done and the integration is functionally present."
)

# A sufficiently long hedged text that IS grounded with 3+ citations.
# Note: each citation is unique — duplicate citations would inflate the count
# and mask threshold regressions. Text must exceed _HEDGE_MIN_LENGTH (400 chars).
_HEDGED_WITH_CITATIONS = (
    "The implementation essentially wraps the existing logic and delegates event handling. "
    "See src/daemon.py:14 for the registration call, src/handler.py:72 for the "
    "dispatch logic, and src/parser.py:108 for the coverage. "
    "The approach is generally aligned with the existing pattern and should work "
    "in the typical case. The daemon basically delegates to the handler "
    "and appears to process events correctly based on the implementation reviewed."
)


class TestHedgeWordAudit:
    """Unit tests for hedge_audit() — hedge-word audit gate."""

    def test_clean_return_no_system_reminder(self, hook):
        """Return text with no hedge words → empty string (no SystemReminder emitted)."""
        result = hook.hedge_audit(
            _CLEAN_RETURN,
            card_number="100",
            session="test-session",
            card_type="work",
        )
        assert result == "", (
            f"Expected empty string for clean return, got: {result!r}"
        )

    def test_hedges_zero_citations_emit_system_reminder(self, hook):
        """Hedged return with 0 citations → non-empty SystemReminder emitted."""
        result = hook.hedge_audit(
            _HEDGED_NO_CITATIONS,
            card_number="101",
            session="test-session",
            card_type="work",
        )
        assert result != "", "Expected SystemReminder for hedged return with no citations"
        assert "Hedge-word audit" in result, (
            f"Expected 'Hedge-word audit' in SystemReminder. Got: {result!r}"
        )
        assert "101" in result, "Expected card number in SystemReminder"

    def test_hedges_with_three_citations_no_system_reminder(self, hook):
        """Hedged return grounded by ≥3 file:line citations → empty string (grounded)."""
        result = hook.hedge_audit(
            _HEDGED_WITH_CITATIONS,
            card_number="102",
            session="test-session",
            card_type="work",
        )
        assert result == "", (
            f"Expected empty string (grounded) for hedged return with 3 citations, got: {result!r}"
        )

    def test_research_card_type_skips_audit(self, hook):
        """card_type='research' → audit skipped, empty string returned."""
        result = hook.hedge_audit(
            _HEDGED_NO_CITATIONS,
            card_number="103",
            session="test-session",
            card_type="research",
        )
        assert result == "", (
            f"Expected empty string for research card (audit skipped), got: {result!r}"
        )

    def test_terse_return_skips_audit(self, hook):
        """Return text < 400 chars → audit skipped, empty string returned."""
        terse = "The work is essentially done."
        assert len(terse) < 400, "Precondition: terse text must be < 400 chars"
        result = hook.hedge_audit(
            terse,
            card_number="104",
            session="test-session",
            card_type="work",
        )
        assert result == "", (
            f"Expected empty string for terse return (audit skipped), got: {result!r}"
        )

    def test_system_reminder_contains_hedge_list(self, hook):
        """SystemReminder for hedged return should list detected hedge words."""
        result = hook.hedge_audit(
            _HEDGED_NO_CITATIONS,
            card_number="105",
            session="test-session",
            card_type="work",
        )
        assert result, "Expected non-empty SystemReminder"
        # At least one hedge word from the text should appear in the reminder.
        any_hedge_mentioned = any(
            word in result.lower()
            for word in ["essentially", "should work", "basically", "effectively",
                         "generally", "likely", "conceptually", "functionally", "roughly"]
        )
        assert any_hedge_mentioned, (
            f"Expected at least one hedge word listed in reminder. Got: {result!r}"
        )

    def test_system_reminder_contains_citation_count(self, hook):
        """SystemReminder should report the citation count found."""
        result = hook.hedge_audit(
            _HEDGED_NO_CITATIONS,
            card_number="106",
            session="test-session",
            card_type="work",
        )
        assert result, "Expected non-empty SystemReminder"
        # The reminder should mention the citation count (0 in this case).
        assert "0" in result or "Citations found" in result, (
            f"Expected citation count in reminder. Got: {result!r}"
        )

    def test_hedges_inside_code_blocks_not_detected(self, hook):
        """Hedge words inside triple-backtick code blocks must NOT trigger the audit.

        This verifies that _strip_code_and_quotes correctly suppresses false positives
        from code blocks containing hedge-word identifiers or comments.
        """
        # Construct a text with enough non-hedge prose (> 400 chars) and hedge words
        # that appear ONLY inside code blocks.
        prose = (
            "The implementation is complete and all tests pass. "
            "The configuration file defines the required constants. "
            "All acceptance criteria have been verified against the live system. "
            "The handler processes requests correctly and returns expected results. "
            "No regressions were found during the verification pass."
        )
        # Hedge words buried inside code blocks — should be stripped before scan.
        code_block = (
            "```python\n"
            "# This should work — basically a no-op\n"
            "# essentially wraps the underlying call\n"
            "def roughly_equal(a, b): return abs(a - b) < 0.01\n"
            "```"
        )
        text = prose + "\n\n" + code_block
        assert len(text) > 400, f"Precondition: text must exceed 400 chars, got {len(text)}"

        result = hook.hedge_audit(
            text,
            card_number="107",
            session="test-session",
            card_type="work",
        )
        assert result == "", (
            f"Expected empty string (hedge words in code blocks should be ignored), got: {result!r}"
        )

    def test_review_card_type_skips_audit(self, hook):
        """card_type='review' → audit skipped, empty string returned."""
        result = hook.hedge_audit(
            _HEDGED_NO_CITATIONS,
            card_number="108",
            session="test-session",
            card_type="review",
        )
        assert result == "", (
            f"Expected empty string for review card (audit skipped), got: {result!r}"
        )


# ---------------------------------------------------------------------------
# Integration test: process_subagent_stop hedge_audit wiring
# ---------------------------------------------------------------------------

class TestProcessSubagentStopHedgeWiring:
    """Integration test verifying hedge_audit is wired into process_subagent_stop."""

    def test_process_subagent_stop_includes_system_message_when_hedged(
        self, hook, tmp_transcript
    ):
        """When the agent's final return is hedged and ungrounded, process_subagent_stop
        returns a systemMessage key in the allow response (exit 0 path).

        This verifies that the hedge_audit result is not silently discarded — if the
        wiring at 'return allow(message, system_message=hedge_reminder)' were accidentally
        removed, this test would fail.
        """
        # Build a transcript whose last assistant message is a hedged return (no citations).
        entries = [
            make_card_header_entry("200", "sess-hedge"),
            {
                "role": "assistant",
                "content": _HEDGED_NO_CITATIONS,
            },
        ]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.success(stdout="Card #200 done.")
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        with patch.object(hook, "send_transition_notification"):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                result = run_process_stop(hook, payload)

        assert result.get("decision") == "allow", f"Expected allow, got: {result}"
        assert "systemMessage" in result, (
            f"Expected 'systemMessage' key in allow response when hedged, got: {result}"
        )
        system_msg = result["systemMessage"]
        assert "Hedge-word audit" in system_msg, (
            f"Expected 'Hedge-word audit' in systemMessage. Got: {system_msg!r}"
        )
