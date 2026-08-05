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

All kanban CLI and subprocess calls are monkeypatched — no real
kanban cards are created or read during these tests.
"""

import importlib.util
import json
import os
import re
import subprocess
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


@pytest.fixture(autouse=True)
def _isolate_hook_log_paths(hook, tmp_path, monkeypatch):
    """Redirect the hook's log-path constants to a per-test tmp_path.

    Many tests already patch hook.log_error/hook.log_info directly for the
    specific call they're asserting on, but any OTHER code path reached
    incidentally during a test (e.g. a nested run_kanban() call, or a future
    test that forgets to patch log_error/log_info) would otherwise write to
    the real production paths — ~/.claude/metrics/kanban-subagent-stop-hook-
    errors.log and kanban-subagent-stop-hook.log — since ERROR_LOG_PATH and
    INFO_LOG_PATH are module-level constants computed once at import time.

    autouse=True means a newly added test cannot forget this and silently
    reintroduce the leak: every test in this module gets isolated log paths
    without having to opt in.
    """
    monkeypatch.setattr(hook, "ERROR_LOG_PATH", tmp_path / "isolated-error.log")
    monkeypatch.setattr(hook, "INFO_LOG_PATH", tmp_path / "isolated-info.log")


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
# Card #3312 regression: a non-empty-but-missing transcript_path must be
# surfaced distinctly from an empty transcript_path, not lumped into the
# same silent log_info branch. See .scratchpad/3312-hook-determination.md —
# this exact silent branch is what stranded cards #3292 and #3305 in
# 'doing' with every criterion met: card identification (and therefore
# `kanban done`) was never attempted because this guard fired first, and
# the failure was indistinguishable from the routine, benign "no path at
# all" case in the logs.
# ---------------------------------------------------------------------------

class TestMissingTranscriptPathSurfacing:
    """A non-empty transcript_path pointing to a missing file must be logged
    via log_error (an anomaly — the daemon told us to look at something
    specific and it wasn't there), never silently folded into the same
    log_info branch as a plain empty transcript_path (the benign, common
    case for non-kanban-managed Task calls).
    """

    def _fake_list_doing(self, card_nums: list[str]):
        """Build a fake subprocess.run side_effect for `kanban list --column
        doing ...`, returning the given card numbers (possibly empty) via the
        REAL `kanban list --output-style=xml` element shape:
        `<board session="...">`, a `<mine>` wrapper, and one `<c n="NN"
        ses="..." s="doing">...</c>` per card — captured live against this
        exact invocation for card #3425 (see that card's action text for the
        verbatim sample). Card #3424 built this fixture with a `num="N"`
        attribute that the real CLI never emits, which is why
        cards_in_doing_for_session's `num="(\\d+)"` regex could never match
        any real board output — the tests stayed green while the production
        code path was dead. Fixed as part of card #3425 alongside the
        production regex itself (now anchored on `<c n="(\\d+)"`).

        Still wrapped in `<board>...</board>` (not `<cards>...</cards>`) so
        the `<board` structural check in `cards_in_doing_for_session`
        (kanban-subagent-stop-hook.py) continues to see a well-formed,
        successfully-parsed response rather than routing to the ERROR
        fallback."""
        cards_xml = "".join(
            f'<c n="{n}" ses="fake-session" s="doing"><i></i><e></e></c>' for n in card_nums
        )

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and len(cmd) > 1 and cmd[1] == "list":
                return KanbanMockResponses.success(
                    stdout=f'<board session="fake-session"><mine>{cards_xml}</mine></board>'
                )
            return KanbanMockResponses.success()

        return fake_subprocess_run

    def test_nonexistent_nonempty_path_logs_error(self, hook):
        """Non-empty transcript_path + missing file, with a card IN 'doing'
        for this session → log_error is called, with the offending path
        present in the message. (A card in 'doing' means the stranding-risk
        report is warranted — see test_phantom_event_logs_below_error_when_
        no_card_in_doing below for the no-card-in-doing case, which now
        logs below error level.)"""
        payload = make_stop_payload(transcript_path="/tmp/does-not-exist-transcript-xyz.jsonl")

        with patch.object(hook, "log_error") as mock_error:
            with patch.object(hook, "log_info"):
                with patch("subprocess.run", side_effect=self._fake_list_doing(["77"])):
                    result = hook.process_subagent_stop(payload)

        assert_allow(result)
        assert mock_error.call_count >= 1, (
            "Expected log_error to be called for a non-empty, nonexistent "
            "transcript_path when a card IS in 'doing' for this session — "
            "this is the exact silent failure that stranded cards #3292 "
            "and #3305 (see .scratchpad/3312-hook-determination.md)."
        )
        logged_messages = " ".join(str(call.args[0]) for call in mock_error.call_args_list)
        assert "does-not-exist-transcript-xyz.jsonl" in logged_messages, (
            f"Expected the offending path in the log_error message. Got: {logged_messages!r}"
        )

    def test_nonexistent_nonempty_path_logs_agent_identity_fields(self, hook):
        """The missing-path log_error message names the agent: session_id,
        agent_id, agent_type, cwd, and tool_use_id from the payload must all
        appear, so the question of which agent (and which specific Task
        invocation) hit this defect becomes answerable.

        Uses a defaulting read (payload.get with a default) for agent_id/
        agent_type/tool_use_id since they may be absent from a given payload
        — this test asserts they still appear (as empty-string reprs) rather
        than raising, and does not alter the branch's existing control flow
        (still returns allow(), still logs via log_error). A card in 'doing'
        is mocked for this session so the ERROR branch (not the below-error
        branch) is the one exercised.

        Each assertion checks the FIELD-PREFIXED form (`<field>=<repr(value)>`)
        rather than a bare value substring — a bare substring can be
        satisfied incidentally by the pre-existing part of the message (see
        the cwd default '/tmp' being a substring of the transcript_path
        fixture below), which would let the assertion pass even if the field
        were never appended. See .scratchpad/verify-field-discrimination.py
        for a standalone proof that each field-prefixed assertion actually
        discriminates."""
        payload = make_stop_payload(transcript_path="/tmp/does-not-exist-transcript-xyz.jsonl")
        payload["agent_id"] = "agent-a1b2c3d4e5f6789"
        payload["agent_type"] = "swe-backend"
        payload["tool_use_id"] = "toolu_01a1b2c3d4e5f6g7h8"

        with patch.object(hook, "log_error") as mock_error:
            with patch.object(hook, "log_info"):
                with patch("subprocess.run", side_effect=self._fake_list_doing(["77"])):
                    result = hook.process_subagent_stop(payload)

        assert_allow(result)
        assert mock_error.call_count >= 1
        logged_messages = " ".join(str(call.args[0]) for call in mock_error.call_args_list)
        assert f"session_id={payload['session_id']!r}" in logged_messages, (
            f"Expected session_id= field in the log_error message. Got: {logged_messages!r}"
        )
        assert f"agent_id={payload['agent_id']!r}" in logged_messages, (
            f"Expected agent_id= field in the log_error message. Got: {logged_messages!r}"
        )
        assert f"agent_type={payload['agent_type']!r}" in logged_messages, (
            f"Expected agent_type= field in the log_error message. Got: {logged_messages!r}"
        )
        assert f"cwd={payload['cwd']!r}" in logged_messages, (
            f"Expected cwd= field in the log_error message. Got: {logged_messages!r}"
        )
        assert f"tool_use_id={payload['tool_use_id']!r}" in logged_messages, (
            f"Expected tool_use_id= field in the log_error message. Got: {logged_messages!r}"
        )

    def test_empty_path_does_not_log_error(self, hook):
        """A plain empty transcript_path is the benign case — must NOT
        trigger log_error (only log_info), so it stays out of the
        low-volume error log that the missing-file anomaly now uses."""
        payload = make_stop_payload(transcript_path="")

        with patch.object(hook, "log_error") as mock_error:
            with patch.object(hook, "log_info"):
                result = hook.process_subagent_stop(payload)

        assert_allow(result)
        assert mock_error.call_count == 0, (
            f"Expected log_error NOT to be called for an empty transcript_path "
            f"(benign case). Got calls: {mock_error.call_args_list}"
        )

    def test_phantom_event_logs_below_error_when_no_card_in_doing(self, hook):
        """Card #3421's discriminator: no card for this session is in
        'doing' → this occurrence cannot strand anything, so it must be
        logged BELOW error level (log_info, not log_error) — and the
        message must state the per-occurrence fact (no card in doing, so
        nothing is stranded), never a blanket claim that the whole class of
        event is spurious/phantom (the investigation's verdict explicitly
        declined to close that question — the producer was never
        identified)."""
        payload = make_stop_payload(transcript_path="/tmp/does-not-exist-nocard-xyz.jsonl")

        with patch.object(hook, "log_error") as mock_error:
            with patch.object(hook, "log_info") as mock_info:
                with patch("subprocess.run", side_effect=self._fake_list_doing([])):
                    result = hook.process_subagent_stop(payload)

        assert_allow(result)
        assert mock_error.call_count == 0, (
            f"Expected log_error NOT to be called when no card is in 'doing' "
            f"for this session. Got calls: {mock_error.call_args_list}"
        )
        assert mock_info.call_count >= 1, (
            "Expected log_info to be called (below-error report) when no "
            "card is in 'doing' for this session."
        )
        logged_messages = " ".join(str(call.args[0]) for call in mock_info.call_args_list)
        assert "does-not-exist-nocard-xyz.jsonl" in logged_messages, (
            f"Expected the offending path in the log_info message. Got: {logged_messages!r}"
        )
        assert "no card is stranded by this occurrence" in logged_messages, (
            f"Expected a per-occurrence fact statement, not a population-wide "
            f"'phantom' claim. Got: {logged_messages!r}"
        )
        # "phantom" as a standalone word must never appear -- checked as a
        # whole word (not substring) so this assertion is not incidentally
        # satisfied/defeated by unrelated text (e.g. a file path) containing
        # the same letters as a substring.
        assert not re.search(r"\bphantom\b", logged_messages, re.IGNORECASE), (
            f"Must not assert these ARE phantom events — the investigation's "
            f"verdict declined to close this question. Got: {logged_messages!r}"
        )

    def test_stranding_risk_logs_error_when_card_in_doing(self, hook):
        """Card #3421's discriminator: one or more cards ARE in 'doing' for
        this session → keep ERROR, and name the card number(s) so the
        reader has something concrete to check."""
        payload = make_stop_payload(transcript_path="/tmp/does-not-exist-stranding-xyz.jsonl")

        with patch.object(hook, "log_error") as mock_error:
            with patch.object(hook, "log_info") as mock_info:
                with patch("subprocess.run", side_effect=self._fake_list_doing(["55"])):
                    result = hook.process_subagent_stop(payload)

        assert_allow(result)
        assert mock_error.call_count >= 1, (
            "Expected log_error to be called when a card IS in 'doing' for "
            "this session."
        )
        logged_messages = " ".join(str(call.args[0]) for call in mock_error.call_args_list)
        assert "does-not-exist-stranding-xyz.jsonl" in logged_messages, (
            f"Expected the offending path in the log_error message. Got: {logged_messages!r}"
        )
        assert "#55" in logged_messages, (
            f"Expected the in-doing card number named concretely. Got: {logged_messages!r}"
        )
        assert "stranded" in logged_messages, (
            f"Expected stranding-risk wording to be kept for this branch. "
            f"Got: {logged_messages!r}"
        )
        assert mock_info.call_count == 0, (
            f"Expected log_info NOT to be called for this event when a card "
            f"is in 'doing' (the report goes to log_error only). Got calls: "
            f"{mock_info.call_args_list}"
        )

    @staticmethod
    def _doing_read_calls(mock_run):
        """Filter a MagicMock(side_effect=...)'s call_args_list down to the
        calls that actually invoked `kanban list --column doing ...`. Used
        to assert the discriminator subprocess was genuinely INVOKED, not
        merely that some fallback wording happened to survive — see card
        #3424 MEDIUM 2."""
        return [
            call
            for call in mock_run.call_args_list
            if isinstance(call.args[0], list)
            and call.args[0][:2] == ["kanban", "list"]
            and "doing" in call.args[0]
        ]

    def test_board_read_failure_falls_back_to_error_log(self, hook):
        """Card #3421's FAIL OPEN constraint: if the board read itself fails
        (kanban CLI returns non-zero), the discriminator cannot determine
        whether a card is at risk — fall back to the original,
        unconditional stranding-risk report, unchanged from before the
        discriminator existed.

        Strengthened per card #3424 MEDIUM 2: also asserts the discriminator's
        `kanban list --column doing` subprocess call was actually attempted,
        not merely that the fallback wording survived. Under the PRE-CHANGE
        code, `process_subagent_stop`'s missing-transcript-path branch
        returned allow() immediately after a single unconditional log_error
        call and never invoked any subprocess in that branch at all — so a
        mocked board-read failure was never exercised, and the wording
        assertions below were satisfied trivially by the pre-existing,
        unchanged message text. The `_doing_read_calls` assertion is what
        distinguishes "the discriminator is wired in" from "the discriminator
        is absent"."""
        payload = make_stop_payload(transcript_path="/tmp/does-not-exist-boardfail-xyz.jsonl")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and len(cmd) > 1 and cmd[1] == "list":
                return KanbanMockResponses.failure(stderr="kanban: board read failed", returncode=1)
            return KanbanMockResponses.success()

        mock_run = MagicMock(side_effect=fake_subprocess_run)

        # Note: run_kanban() itself calls log_info on any non-zero exit
        # (pre-existing, unrelated behavior — see run_kanban's own
        # "kanban {args} failed (exit {rc}): {stderr}" log line) — so
        # log_info is NOT asserted to be zero here; only that log_error
        # carries the correct fallback report is asserted.
        with patch.object(hook, "log_error") as mock_error:
            with patch.object(hook, "log_info"):
                with patch("subprocess.run", mock_run):
                    result = hook.process_subagent_stop(payload)

        assert_allow(result)

        assert len(self._doing_read_calls(mock_run)) >= 1, (
            f"Expected the discriminator to actually invoke "
            f"`kanban list --column doing ...` before falling back. Got "
            f"subprocess.run calls: {mock_run.call_args_list!r}"
        )

        assert mock_error.call_count >= 1, (
            "Expected log_error to be called (fail-open fallback) when the "
            "board read itself fails."
        )
        logged_messages = " ".join(str(call.args[0]) for call in mock_error.call_args_list)
        assert "does-not-exist-boardfail-xyz.jsonl" in logged_messages, (
            f"Expected the offending path in the log_error message. Got: {logged_messages!r}"
        )
        assert "may be silently stranded in 'doing'" in logged_messages, (
            f"Expected the original, unconditional stranding-risk wording "
            f"(unchanged fail-open fallback). Got: {logged_messages!r}"
        )

    def test_timeout_on_board_read_falls_back_to_error_log(self, hook):
        """Card #3424 MEDIUM 2: covers the *timeout* route to None
        specifically, distinct from test_board_read_failure_falls_back_to_
        error_log's non-zero-exit route. `run_kanban` (kanban-subagent-
        stop-hook.py) catches `subprocess.TimeoutExpired` internally and
        converts it to a synthetic returncode=124 CompletedProcess;
        `cards_in_doing_for_session` then sees that as a non-zero exit and
        returns None, reaching the same fail-open fallback as any other
        read failure. Also asserts the discriminator was actually invoked,
        for the same reason as the strengthened test above."""
        payload = make_stop_payload(transcript_path="/tmp/does-not-exist-boardtimeout-xyz.jsonl")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and len(cmd) > 1 and cmd[1] == "list":
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 10))
            return KanbanMockResponses.success()

        mock_run = MagicMock(side_effect=fake_subprocess_run)

        with patch.object(hook, "log_error") as mock_error:
            with patch.object(hook, "log_info"):
                with patch("subprocess.run", mock_run):
                    result = hook.process_subagent_stop(payload)

        assert_allow(result)

        assert len(self._doing_read_calls(mock_run)) >= 1, (
            f"Expected the discriminator to actually invoke "
            f"`kanban list --column doing ...` before falling back. Got "
            f"subprocess.run calls: {mock_run.call_args_list!r}"
        )

        assert mock_error.call_count >= 1, (
            "Expected log_error to be called (fail-open fallback) when the "
            "board read times out."
        )
        logged_messages = " ".join(str(call.args[0]) for call in mock_error.call_args_list)
        assert "does-not-exist-boardtimeout-xyz.jsonl" in logged_messages, (
            f"Expected the offending path in the log_error message. Got: {logged_messages!r}"
        )
        assert "may be silently stranded in 'doing'" in logged_messages, (
            f"Expected the original, unconditional stranding-risk wording "
            f"(unchanged fail-open fallback) for a timed-out board read. "
            f"Got: {logged_messages!r}"
        )

    def test_unparseable_board_output_falls_back_to_error_log(self, hook):
        """Card #3424 MEDIUM 1: exit code 0 with unparseable/garbled stdout
        (never containing kanban's `<board` root element) must reach the
        ERROR fallback branch — the same branch a genuine read failure
        reaches — NOT the below-ERROR log_info branch that a confirmed,
        successfully-parsed, genuinely-empty 'doing' column reaches. Before
        card #3424's fix, `re.findall(r'num="(\\d+)"', result.stdout)`
        returning `[]` was indistinguishable between "truly empty board" and
        "garbled/truncated output" — both silently routed to log_info. See
        cards_in_doing_for_session's updated docstring in
        kanban-subagent-stop-hook.py."""
        payload = make_stop_payload(transcript_path="/tmp/does-not-exist-boardgarbled-xyz.jsonl")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and len(cmd) > 1 and cmd[1] == "list":
                return KanbanMockResponses.success(stdout="not xml at all, definitely not a board\n")
            return KanbanMockResponses.success()

        mock_run = MagicMock(side_effect=fake_subprocess_run)

        with patch.object(hook, "log_error") as mock_error:
            with patch.object(hook, "log_info") as mock_info:
                with patch("subprocess.run", mock_run):
                    result = hook.process_subagent_stop(payload)

        assert_allow(result)

        assert len(self._doing_read_calls(mock_run)) >= 1, (
            f"Expected the discriminator to actually invoke "
            f"`kanban list --column doing ...`. Got subprocess.run calls: "
            f"{mock_run.call_args_list!r}"
        )

        assert mock_error.call_count >= 1, (
            "Expected log_error (ERROR fallback) when kanban list exits 0 "
            "but returns unparseable stdout — this must NOT be treated the "
            "same as a genuinely empty 'doing' column."
        )
        logged_messages = " ".join(str(call.args[0]) for call in mock_error.call_args_list)
        assert "does-not-exist-boardgarbled-xyz.jsonl" in logged_messages, (
            f"Expected the offending path in the log_error message. Got: {logged_messages!r}"
        )
        assert "may be silently stranded in 'doing'" in logged_messages, (
            f"Expected the original, unconditional stranding-risk wording "
            f"(unchanged fail-open fallback) for unparseable board output. "
            f"Got: {logged_messages!r}"
        )
        assert mock_info.call_count == 0, (
            f"Expected log_info NOT to be used for unparseable board output "
            f"— that below-ERROR branch is reserved for a confirmed-empty, "
            f"successfully-parsed board read. Got calls: "
            f"{mock_info.call_args_list!r}"
        )


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
# Personal Trainer session skip
# ---------------------------------------------------------------------------

class TestPersonalTrainerSession:
    """PERSONAL_TRAINER_SESSION=1 → main() immediately allows stop."""

    def test_personal_trainer_session_allows_stop(self, hook):
        import io
        captured = []

        def fake_print(val, **kwargs):
            captured.append(val)

        payload = {"agent_transcript_path": "", "session_id": "x", "cwd": "/tmp"}
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with patch("builtins.print", side_effect=fake_print):
                with patch.dict(os.environ, {"PERSONAL_TRAINER_SESSION": "1"}, clear=False):
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

    def test_extract_card_from_transcript_returns_latest_card(self, hook, tmp_transcript):
        """Regression: a continued agent's transcript spans multiple cards — the
        ORIGINAL card's injected XML header appears EARLY, and a NEWER card is
        referenced LATER via a `kanban criteria check` CLI call. The function
        must return the NEWER card, not the first (stale) match.
        """
        entries = [
            # Round 1: original card injected via PreToolUse XML header (early).
            {
                "role": "user",
                "content": '<card num="100" session="multi-session" status="doing" type="work">',
            },
            {"role": "assistant", "content": "Working on card 100..."},
            # Round 2 (continuation): agent is re-tasked with a new card and runs
            # a kanban CLI command against it — this appears LATER in the file.
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": "kanban criteria check 200 1 --session multi-session",
                        },
                    }
                ],
            },
        ]
        transcript = tmp_transcript(entries)
        result = hook.extract_card_from_transcript(transcript)
        assert result == ("200", "multi-session"), (
            f"Expected the LATEST card (200) to win over the stale original card "
            f"(100). Got: {result}"
        )

    def test_extract_card_from_transcript_repeated_same_card_unaffected(self, hook, tmp_transcript):
        """Edge case: a transcript that references the SAME card repeatedly (e.g.
        retries across cycles) is unaffected by the latest-match change — the
        same card number is returned either way.
        """
        entries = [
            make_card_header_entry("77", "retry-session"),
            make_kanban_criteria_bash_entry("77", "retry-session", n=1),
            make_kanban_criteria_bash_entry("77", "retry-session", n=2),
        ]
        transcript = tmp_transcript(entries)
        result = hook.extract_card_from_transcript(transcript)
        assert result == ("77", "retry-session")

    def test_extract_card_from_transcript_header_anchor_beats_trailing_prose(self, hook, tmp_transcript):
        """Trust-boundary regression: a hook-injected header for card X appears
        early, and LATER the agent's own free-text prose (its final-return-style
        narrative, not a real tool invocation) echoes a quoted `kanban` command
        example referencing a DIFFERENT card Y. Resolution must stay anchored to
        X — the hook-injected content — not be redirected by agent-controlled
        prose to Y.
        """
        entries = [
            # Hook-injected XML anchor for card X (trusted).
            {
                "role": "user",
                "content": '<card num="300" session="anchor-session" status="doing" type="work">',
            },
            {"role": "assistant", "content": "Working on card 300..."},
            # Agent's own final-return PROSE (plain string content, no tool_use)
            # quotes an unrelated command example — this is the exact untrusted
            # surface the trust-anchor fix closes.
            {
                "role": "assistant",
                "content": (
                    "For reference, here's an example invocation you could use: "
                    "kanban criteria check 999 1 --session other-session"
                ),
            },
        ]
        transcript = tmp_transcript(entries)
        result = hook.extract_card_from_transcript(transcript)
        assert result == ("300", "anchor-session"), (
            f"Expected the hook-injected anchor (300) to win over agent-authored "
            f"prose quoting an unrelated card (999). Got: {result}"
        )

    def test_extract_card_from_transcript_header_anchor_newer_round_wins(self, hook, tmp_transcript):
        """Trust-boundary regression: when a LEGITIMATE later hook-injected
        header exists for a new round, the newer card wins over the earlier
        anchor — the anchor is always the LAST hook-injected header, not the
        first.
        """
        entries = [
            {
                "role": "user",
                "content": '<card num="400" session="anchor-session" status="doing" type="work">',
            },
            {"role": "assistant", "content": "Working on card 400..."},
            # A fresh round re-injects a new card header (legitimate hook re-injection).
            make_card_header_entry("500", "anchor-session"),
        ]
        transcript = tmp_transcript(entries)
        result = hook.extract_card_from_transcript(transcript)
        assert result == ("500", "anchor-session"), (
            f"Expected the newer hook-injected header (500) to win over the "
            f"earlier anchor (400). Got: {result}"
        )

    def test_extract_card_from_transcript_empty_transcript_returns_none(self, hook, tmp_transcript):
        """Edge case: an empty transcript has no entries to scan — returns None."""
        transcript = tmp_transcript([])
        result = hook.extract_card_from_transcript(transcript)
        assert result is None

    def test_extract_card_from_transcript_corrupt_jsonl_line_skipped(self, hook, tmp_path):
        """Edge case: a corrupt (non-JSON) line is skipped without crashing, and
        a valid match on a surrounding line is still found.
        """
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(make_card_header_entry("66", "corrupt-session")),
            "{not valid json!!",
            json.dumps({"role": "assistant", "content": "All done."}),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        result = hook.extract_card_from_transcript(str(transcript))
        assert result == ("66", "corrupt-session")


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


# ---------------------------------------------------------------------------
# Stuck-criterion detection unit tests
# ---------------------------------------------------------------------------

# Sample kanban done stderr output with two unchecked criteria (indices 1 and 3)
_DONE_STDERR_TWO_UNCHECKED = (
    "Cannot complete card #42 — 2 of 3 acceptance criteria not fully passed:\n"
    "  [agent]  [reviewer]    criterion\n"
    "  [⬜]  [⬜ —]  1. Hook contains a new stuck-criterion warning\n"
    "  [✅]  [⬜ —]  2. Existing tests pass after change\n"
    "  [⬜]  [⬜ —]  3. No new state-file writes introduced\n"
)

# Prior block-feedback text that mentions criteria 1 and 3 as previously unchecked
_PRIOR_FEEDBACK_CRITERIA_1_AND_3 = (
    "kanban done failed for card #42:\n\n"
    "Cannot complete card #42 — 2 of 3 acceptance criteria not fully passed:\n"
    "  [agent]  [reviewer]    criterion\n"
    "  [⬜]  [⬜ —]  1. Hook contains a new stuck-criterion warning\n"
    "  [✅]  [⬜ —]  2. Existing tests pass after change\n"
    "  [⬜]  [⬜ —]  3. No new state-file writes introduced\n"
    "\n\nInvestigate each unchecked criterion..."
)


class TestDetectStuckCriteria:
    """Unit tests for detect_stuck_criteria() — stuck-criterion early warning."""

    def test_same_criterion_in_prior_feedback_returns_index(self, hook, tmp_transcript):
        """Criterion index that appears in both current output and prior feedback is stuck."""
        # Put the prior feedback in the transcript as a user-role block message
        prior_feedback_entry = {
            "role": "user",
            "content": _PRIOR_FEEDBACK_CRITERIA_1_AND_3,
        }
        entries = [
            make_card_header_entry("42", "test-session"),
            prior_feedback_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                # Current output has criteria 1 and 3 unchecked; prior had 1 and 3 too
                stuck = hook.detect_stuck_criteria(
                    _DONE_STDERR_TWO_UNCHECKED, transcript, "42"
                )

        assert 1 in stuck, f"Expected criterion 1 in stuck list, got: {stuck}"
        assert 3 in stuck, f"Expected criterion 3 in stuck list, got: {stuck}"

    def test_new_failure_not_in_prior_feedback_not_stuck(self, hook, tmp_transcript):
        """Criterion that fails for the first time (not in prior feedback) is not stuck."""
        prior_feedback_only_criterion_3 = (
            "kanban done failed for card #42:\n\n"
            "  [⬜]  [⬜ —]  3. No new state-file writes introduced\n"
        )
        prior_feedback_entry = {
            "role": "user",
            "content": prior_feedback_only_criterion_3,
        }
        entries = [
            make_card_header_entry("42", "test-session"),
            prior_feedback_entry,
        ]
        transcript = tmp_transcript(entries)

        # Current output shows criterion 1 unchecked for the first time
        current_only_criterion_1 = (
            "Cannot complete card #42 — 1 of 3 criteria not passed:\n"
            "  [⬜]  [⬜ —]  1. Hook contains a new stuck-criterion warning\n"
        )

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                stuck = hook.detect_stuck_criteria(
                    current_only_criterion_1, transcript, "42"
                )

        assert 1 not in stuck, (
            f"Expected criterion 1 not stuck (first failure), got: {stuck}"
        )

    def test_no_prior_feedback_returns_empty(self, hook, tmp_transcript):
        """Transcript with no prior block-feedback → no stuck criteria detected."""
        entries = [make_card_header_entry("42", "test-session")]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                stuck = hook.detect_stuck_criteria(
                    _DONE_STDERR_TWO_UNCHECKED, transcript, "42"
                )

        assert stuck == [], f"Expected empty list for no prior feedback, got: {stuck}"

    def test_feedback_for_different_card_not_matched(self, hook, tmp_transcript):
        """Prior feedback for card #99 does not affect stuck detection for card #42."""
        wrong_card_feedback = (
            "kanban done failed for card #99:\n\n"
            "  [⬜]  [⬜ —]  1. Some criterion\n"
        )
        prior_feedback_entry = {
            "role": "user",
            "content": wrong_card_feedback,
        }
        entries = [
            make_card_header_entry("42", "test-session"),
            prior_feedback_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                stuck = hook.detect_stuck_criteria(
                    _DONE_STDERR_TWO_UNCHECKED, transcript, "42"
                )

        assert stuck == [], (
            f"Expected no stuck criteria when prior feedback is for different card, got: {stuck}"
        )

    def test_nonexistent_transcript_returns_empty(self, hook):
        """Nonexistent transcript file → empty list (fail open)."""
        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                stuck = hook.detect_stuck_criteria(
                    _DONE_STDERR_TWO_UNCHECKED,
                    "/tmp/no-such-transcript-xyz.jsonl",
                    "42",
                )

        assert stuck == [], f"Expected fail-open (empty list) for missing transcript, got: {stuck}"

    def test_empty_done_output_returns_empty(self, hook, tmp_transcript):
        """Empty kanban done output → no indices to match, returns empty list."""
        prior_feedback_entry = {
            "role": "user",
            "content": _PRIOR_FEEDBACK_CRITERIA_1_AND_3,
        }
        entries = [
            make_card_header_entry("42", "test-session"),
            prior_feedback_entry,
        ]
        transcript = tmp_transcript(entries)

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                stuck = hook.detect_stuck_criteria("", transcript, "42")

        assert stuck == [], f"Expected empty list for empty done output, got: {stuck}"

    def test_result_is_sorted(self, hook, tmp_transcript):
        """Stuck criterion indices are returned in sorted order."""
        prior_feedback_all = (
            "kanban done failed for card #42:\n\n"
            "  [⬜]  [⬜ —]  3. Third criterion\n"
            "  [⬜]  [⬜ —]  1. First criterion\n"
        )
        prior_feedback_entry = {"role": "user", "content": prior_feedback_all}
        entries = [
            make_card_header_entry("42", "test-session"),
            prior_feedback_entry,
        ]
        transcript = tmp_transcript(entries)

        current_output = (
            "  [⬜]  [⬜ —]  3. Third criterion\n"
            "  [⬜]  [⬜ —]  1. First criterion\n"
        )

        with patch.object(hook, "log_info"):
            with patch.object(hook, "log_error"):
                stuck = hook.detect_stuck_criteria(current_output, transcript, "42")

        assert stuck == sorted(stuck), f"Expected sorted list, got: {stuck}"
        assert 1 in stuck and 3 in stuck

    def test_transcript_exceeding_max_bytes_returns_empty(self, hook, tmp_path):
        """Transcript file exceeding _TRANSCRIPT_MAX_BYTES early-returns without scanning."""
        # Write a transcript containing prior block feedback that would normally
        # trigger stuck detection — confirms the size guard short-circuits before scan.
        transcript_file = tmp_path / "large_transcript.jsonl"
        prior_line = json.dumps({
            "role": "user",
            "content": _PRIOR_FEEDBACK_CRITERIA_1_AND_3,
        })
        transcript_file.write_text(prior_line + "\n")

        # Patch Path.stat to report a size above the guard threshold
        import os as _os
        max_bytes = hook._TRANSCRIPT_MAX_BYTES
        fake_stat = _os.stat_result((0o644, 0, 0, 1, 0, 0, max_bytes + 1, 0, 0, 0))

        mock_path = MagicMock()
        mock_path.stat.return_value = fake_stat

        with patch.object(hook, "Path", return_value=mock_path):
            with patch.object(hook, "log_info"):
                with patch.object(hook, "log_error"):
                    stuck = hook.detect_stuck_criteria(
                        _DONE_STDERR_TWO_UNCHECKED,
                        str(transcript_file),
                        "42",
                    )

        assert stuck == [], (
            f"Expected empty list when transcript exceeds MAX_BYTES, got: {stuck}"
        )


# ---------------------------------------------------------------------------
# Integration test: stuck-criterion warning wired into process_subagent_stop
# ---------------------------------------------------------------------------

class TestStuckCriterionWarningWiring:
    """Integration tests verifying stuck-criterion warning is logged on exit 1."""

    def test_stuck_criterion_warning_logged_when_same_criterion_fails_twice(
        self, hook, tmp_transcript
    ):
        """When the same criterion fails on 2+ consecutive cycles, a WARNING is logged."""
        # Simulate prior block-feedback in transcript for criterion 1
        prior_feedback_entry = {
            "role": "user",
            "content": (
                "kanban done failed for card #300:\n\n"
                "  [⬜]  [⬜ —]  1. Hook contains stuck-criterion warning\n\n"
                "Investigate each unchecked criterion..."
            ),
        }
        entries = [
            make_card_header_entry("300", "sess-stuck"),
            prior_feedback_entry,
        ]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        # Current kanban done exit 1 output also shows criterion 1 unchecked
        current_done_stderr = (
            "Cannot complete card #300 — 1 of 2 criteria not passed:\n"
            "  [⬜]  [⬜ —]  1. Hook contains stuck-criterion warning\n"
            "  [✅]  [⬜ —]  2. Some passing criterion\n"
        )

        logged_warnings = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(
                        returncode=1, stderr=current_done_stderr
                    )
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        _WARNING_PATTERN = re.compile(
            r"Warning: Card #\d+ criterion .+ has failed AC verification on 2\+ consecutive cycles"
        )

        def capture_log_info(msg):
            if _WARNING_PATTERN.search(msg):
                logged_warnings.append(msg)

        # Call process_subagent_stop directly with our own log_info capture
        # (do NOT use run_process_stop — it patches log_info with a no-op MagicMock)
        with patch.object(hook, "log_info", side_effect=capture_log_info):
            with patch.object(hook, "log_error"):
                with patch("subprocess.run", side_effect=fake_subprocess_run):
                    result = hook.process_subagent_stop(payload)

        assert result.get("decision") == "block", f"Expected block, got: {result}"
        assert len(logged_warnings) >= 1, (
            f"Expected at least one warning log for stuck criterion, got: {logged_warnings}"
        )
        warning_text = logged_warnings[0]
        assert "300" in warning_text, f"Expected card number in warning: {warning_text}"
        assert "1" in warning_text, f"Expected criterion index in warning: {warning_text}"

    def test_no_warning_logged_when_first_failure(self, hook, tmp_transcript):
        """No warning logged when criterion fails for the first time (no prior feedback)."""
        entries = [make_card_header_entry("301", "sess-first")]
        transcript = tmp_transcript(entries)
        payload = make_stop_payload(transcript_path=transcript)

        current_done_stderr = (
            "Cannot complete card #301 — 1 of 1 criteria not passed:\n"
            "  [⬜]  [⬜ —]  1. Some new criterion\n"
        )

        logged_warnings = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban":
                sub = cmd[1] if len(cmd) > 1 else ""
                if sub == "status":
                    return KanbanMockResponses.success(stdout="doing")
                if sub == "done":
                    return KanbanMockResponses.failure(
                        returncode=1, stderr=current_done_stderr
                    )
                return KanbanMockResponses.success()
            return KanbanMockResponses.success()

        _WARNING_PATTERN = re.compile(
            r"Warning: Card #\d+ criterion .+ has failed AC verification on 2\+ consecutive cycles"
        )

        def capture_log_info(msg):
            if _WARNING_PATTERN.search(msg):
                logged_warnings.append(msg)

        # Call process_subagent_stop directly with our own log_info capture
        with patch.object(hook, "log_info", side_effect=capture_log_info):
            with patch.object(hook, "log_error"):
                with patch("subprocess.run", side_effect=fake_subprocess_run):
                    result = hook.process_subagent_stop(payload)

        assert result.get("decision") == "block", f"Expected block, got: {result}"
        assert len(logged_warnings) == 0, (
            f"Expected no WARNING for first failure, got: {logged_warnings}"
        )


# ---------------------------------------------------------------------------
# log_error() per-line length cap (card #3384)
# ---------------------------------------------------------------------------

_DIGEST_HOOK_PATH = Path(__file__).parent.parent / "hook-error-digest-hook.py"


def load_digest_hook():
    """Import hook-error-digest-hook.py as a module, for classifier reuse.

    Used only to verify a truncated log_error() line still lands in the same
    classifier bucket as its untruncated counterpart -- see
    TestLogErrorLineCap.test_capped_line_still_classifiable_by_digest_hook.
    """
    spec = importlib.util.spec_from_file_location("hook_error_digest_hook", _DIGEST_HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLogErrorLineCap:
    """log_error() caps a single message to _LOG_MAX_LINE_CHARS before writing.

    Guards against one pathological interpolated value (e.g. an oversized
    cwd) producing a single log line large enough for
    hook-error-digest-hook.py's PER_RUN_LINE_CAP (a line-COUNT cap, not a
    byte cap) to re-read whole on every digest run until rotation.
    """

    def test_log_error_caps_overlong_line(self, hook, tmp_path, monkeypatch):
        """An over-long log_error() message is truncated on disk, with an
        elision marker naming the original length -- and the assertion is
        shown to discriminate: the tail marker is reconstructed here, in the
        test's own scope, and its ABSENCE from the on-disk line is what is
        asserted. If the cap were not applied, the tail marker (part of the
        message's un-capped tail) would end up in the file and this
        assertion would fail -- without ever removing the cap from the hook
        itself.
        """
        log_path = tmp_path / "overlong-error.log"
        monkeypatch.setattr(hook, "ERROR_LOG_PATH", log_path)

        # Shape mirrors the real diagnostic-fields call site
        # (kanban-subagent-stop-hook.py:1413-1424 as of this change): a fixed
        # preamble, followed by a pathologically long interpolated field (a
        # giant cwd value), ending in a marker that only survives on disk if
        # no truncation is applied at all.
        unique_tail_marker = "UNIQUE_TAIL_MARKER_zzz999"
        oversized_cwd = "A" * (hook._LOG_MAX_LINE_CHARS + 500)
        message = (
            "SubagentStop received a non-empty transcript_path that does not "
            "exist on disk: '/tmp/x.jsonl'. "
            f"cwd={oversized_cwd!r} "
            f"{unique_tail_marker}"
        )
        # Precondition: the message genuinely exceeds the cap, and genuinely
        # contains the tail marker -- otherwise this test proves nothing.
        assert len(message) > hook._LOG_MAX_LINE_CHARS, (
            "Precondition failed: message must exceed _LOG_MAX_LINE_CHARS "
            "for this test to exercise truncation at all."
        )
        assert unique_tail_marker in message

        hook.log_error(message)

        logged = log_path.read_text(encoding="utf-8")

        assert unique_tail_marker not in logged, (
            "Expected the tail marker to be truncated away. Its presence "
            "would mean log_error() wrote the message uncapped -- this is "
            "the exact condition that would make this assertion fail if the "
            "cap were removed."
        )
        assert "truncated" in logged and str(len(message)) in logged, (
            f"Expected an elision marker naming the original message length "
            f"({len(message)}). Got: {logged!r}"
        )

    def test_capped_line_still_classifiable_by_digest_hook(self, hook, tmp_path, monkeypatch):
        """A truncated line must still land in the SAME digest classifier
        bucket as its untruncated counterpart.

        hook-error-digest-hook.py's _HOT_LOG_CLASSIFIERS[0]
        ("transcript-path-missing", matched against
        "non-empty transcript_path that does not exist" --
        hook-error-digest-hook.py:154) matches the fixed preamble text this
        hook writes BEFORE any of the appended, potentially-long fields
        (kanban-subagent-stop-hook.py:1413-1414) -- so truncating the TAIL
        of an over-long message must not change the classification.
        """
        log_path = tmp_path / "classify-error.log"
        monkeypatch.setattr(hook, "ERROR_LOG_PATH", log_path)

        oversized_cwd = "B" * (hook._LOG_MAX_LINE_CHARS + 1000)
        message = (
            "SubagentStop received a non-empty transcript_path that does not "
            "exist on disk: '/tmp/y.jsonl'. session_id='sess' agent_id='' "
            f"agent_type='' cwd={oversized_cwd!r} tool_use_id=''"
        )
        assert len(message) > hook._LOG_MAX_LINE_CHARS, (
            "Precondition failed: message must exceed _LOG_MAX_LINE_CHARS "
            "for this test to exercise truncation at all."
        )

        hook.log_error(message)
        logged_line = log_path.read_text(encoding="utf-8").splitlines()[0]
        assert "truncated" in logged_line, (
            "Precondition failed: expected the written line to actually be "
            "truncated (i.e. shorter than the original message) for this "
            "classifiability check to be meaningful."
        )

        digest_hook = load_digest_hook()
        classify = digest_hook.make_log_classifier(digest_hook._HOT_LOG_CLASSIFIERS)
        assert classify(logged_line) == "transcript-path-missing", (
            f"Expected the truncated line to still classify as "
            f"'transcript-path-missing'. Got a different classification for: "
            f"{logged_line[:120]!r}"
        )
