"""
Tests for modules/claude/orphan-agent-tracker-hook.py.

Covered paths:
- pretool subcommand: appends entry to tracker file with correct shape
- pretool: appends without overwriting existing entries (concurrent-safe)
- subagent-stop: removes matching entry by tool_use_id
- subagent-stop: tolerates missing entry (session restart) — no error
- user-prompt-submit: emits warning to stdout when tracker is non-empty
- user-prompt-submit: emits nothing when tracker is empty
- user-prompt-submit: warning includes count, IDs, descriptions, durations
- user-prompt-submit: prunes stale entries (>24h) silently
- user-prompt-submit: BURNS_SESSION=1 → no-op (no output, no write)
- pretool: no-op when session ID absent (KANBAN_SESSION not set)
- pretool: no-op when tool_use_id absent from payload
- user-prompt-submit: warning suppressed for entries <5min old (expected in-flight)
- user-prompt-submit: warning emitted for entries >5min old
- user-prompt-submit: description truncated to 120 chars in warning output
- get_tracker_path: invalid session_id (containing /) returns None
- pretool: tracker file created with mode 0600
- user-prompt-submit: stale file from different session not read when KANBAN_SESSION unset
- user-prompt-submit: warning text leads with 'Wait' before 'TaskStop'
- user-prompt-submit: warning includes phantom-doing distinguishing line

All file I/O uses tmp_path (pytest) — no real scratchpad files are written.
"""

import importlib.util
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "orphan-agent-tracker-hook.py"


def load_hook():
    """Import orphan-agent-tracker-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("orphan_agent_tracker_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the orphan agent tracker hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pretool_payload(
    tool_use_id: str = "toolu_abc123",
    description: str = "swe-devex working on card #42",
) -> dict:
    """Build a minimal PreToolUse(Agent) hook payload."""
    return {
        "tool_name": "Agent",
        "tool_use_id": tool_use_id,
        "tool_input": {
            "description": description,
            "run_in_background": True,
        },
    }


def _make_stop_payload(tool_use_id: str = "toolu_abc123") -> dict:
    """Build a minimal SubagentStop hook payload."""
    return {
        "tool_use_id": tool_use_id,
    }


def _make_user_prompt_payload() -> dict:
    """Build a minimal UserPromptSubmit hook payload."""
    return {
        "prompt": "How are things going?",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _old_iso(hours: float = 25.0) -> str:
    """Return an ISO timestamp that is `hours` hours in the past."""
    ts = datetime.now(timezone.utc) - timedelta(hours=hours)
    return ts.strftime('%Y-%m-%dT%H:%M:%SZ')


def _minutes_ago_iso(minutes: float) -> str:
    """Return an ISO timestamp that is `minutes` minutes in the past."""
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return ts.strftime('%Y-%m-%dT%H:%M:%SZ')


def _write_tracker(tracker_path: Path, entries: list) -> None:
    """Write a list of entries to the tracker file as JSONL."""
    tracker_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tracker_path, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def _read_tracker(tracker_path: Path) -> list:
    """Read all entries from the tracker JSONL file."""
    if not tracker_path.exists():
        return []
    entries = []
    with open(tracker_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _run_subcommand(hook_mod, subcommand: str, payload: dict,
                    env: dict = None, cwd: Path = None) -> str:
    """
    Invoke a hook subcommand via main() with argv and stdin mocked.
    Returns captured stdout as a string.
    """
    raw = json.dumps(payload)
    captured = []

    def fake_print(*args, **kwargs):
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        text = sep.join(str(a) for a in args) + end
        captured.append(text)

    env_patch = env or {}
    argv_patch = ["orphan-agent-tracker-hook", subcommand]

    cwd_context = cwd if cwd is not None else Path.cwd()

    with patch.object(sys, "argv", argv_patch):
        with patch.object(sys, "stdin", io.StringIO(raw)):
            with patch("builtins.print", side_effect=fake_print):
                with patch.dict(os.environ, env_patch, clear=False):
                    with patch.object(hook_mod, "log_error"):
                        with patch.object(hook_mod, "log_info"):
                            with patch.object(Path, "cwd", return_value=cwd_context):
                                hook_mod.main()

    return "".join(captured)


# ---------------------------------------------------------------------------
# Tests: pretool subcommand
# ---------------------------------------------------------------------------

def test_pretool_appends_entry_with_correct_shape(hook, tmp_path):
    """pretool writes a single entry with id, description, and started_at."""
    payload = _make_pretool_payload(
        tool_use_id="toolu_test1",
        description="swe-devex on card #42",
    )
    env = {"KANBAN_SESSION": "test-session"}

    _run_subcommand(hook, "pretool", payload, env=env, cwd=tmp_path)

    tracker = tmp_path / ".scratchpad" / "orphan-tracker-test-session.jsonl"
    entries = _read_tracker(tracker)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == "toolu_test1"
    assert entry["description"] == "swe-devex on card #42"
    assert "started_at" in entry
    # Verify started_at is a parseable ISO8601 timestamp
    dt = datetime.fromisoformat(entry["started_at"].replace("Z", "+00:00"))
    assert dt.tzinfo is not None


def test_pretool_appends_without_overwriting_existing_entries(hook, tmp_path):
    """pretool appends without destroying previously recorded entries."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-multi-session.jsonl"
    existing_entry = {
        "id": "toolu_existing",
        "description": "first agent",
        "started_at": _now_iso(),
    }
    _write_tracker(tracker, [existing_entry])

    payload = _make_pretool_payload(
        tool_use_id="toolu_new",
        description="second agent",
    )
    env = {"KANBAN_SESSION": "multi-session"}

    _run_subcommand(hook, "pretool", payload, env=env, cwd=tmp_path)

    entries = _read_tracker(tracker)
    assert len(entries) == 2
    ids = {e["id"] for e in entries}
    assert "toolu_existing" in ids
    assert "toolu_new" in ids


def test_pretool_noop_when_no_session(hook, tmp_path):
    """pretool does nothing when KANBAN_SESSION is not set."""
    payload = _make_pretool_payload(tool_use_id="toolu_noop")
    env = {"KANBAN_SESSION": ""}

    _run_subcommand(hook, "pretool", payload, env=env, cwd=tmp_path)

    scratchpad = tmp_path / ".scratchpad"
    tracker_files = list(scratchpad.glob("orphan-tracker-*.jsonl")) if scratchpad.exists() else []
    assert tracker_files == []


def test_pretool_noop_when_no_tool_use_id(hook, tmp_path):
    """pretool does nothing when tool_use_id is absent from payload."""
    payload = {"tool_name": "Agent", "tool_input": {"description": "some agent"}}
    env = {"KANBAN_SESSION": "noid-session"}

    _run_subcommand(hook, "pretool", payload, env=env, cwd=tmp_path)

    tracker = tmp_path / ".scratchpad" / "orphan-tracker-noid-session.jsonl"
    assert not tracker.exists()


def test_pretool_burns_session_noop(hook, tmp_path):
    """pretool no-ops when BURNS_SESSION=1."""
    payload = _make_pretool_payload(tool_use_id="toolu_burns")
    env = {"KANBAN_SESSION": "burns-session", "BURNS_SESSION": "1"}

    _run_subcommand(hook, "pretool", payload, env=env, cwd=tmp_path)

    tracker = tmp_path / ".scratchpad" / "orphan-tracker-burns-session.jsonl"
    assert not tracker.exists()


# ---------------------------------------------------------------------------
# Tests: subagent-stop subcommand
# ---------------------------------------------------------------------------

def test_subagent_stop_removes_matching_entry(hook, tmp_path):
    """subagent-stop removes the entry matching the given tool_use_id."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-stop-session.jsonl"
    _write_tracker(tracker, [
        {"id": "toolu_agent1", "description": "agent one", "started_at": _now_iso()},
        {"id": "toolu_agent2", "description": "agent two", "started_at": _now_iso()},
    ])

    payload = _make_stop_payload(tool_use_id="toolu_agent1")
    env = {"KANBAN_SESSION": "stop-session"}

    _run_subcommand(hook, "subagent-stop", payload, env=env, cwd=tmp_path)

    entries = _read_tracker(tracker)
    assert len(entries) == 1
    assert entries[0]["id"] == "toolu_agent2"


def test_subagent_stop_tolerates_missing_entry(hook, tmp_path):
    """subagent-stop is a no-op (exit 0) when the entry does not exist."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-miss-session.jsonl"
    _write_tracker(tracker, [
        {"id": "toolu_other", "description": "other agent", "started_at": _now_iso()},
    ])

    payload = _make_stop_payload(tool_use_id="toolu_nonexistent")
    env = {"KANBAN_SESSION": "miss-session"}

    # Must not raise; file content unchanged
    _run_subcommand(hook, "subagent-stop", payload, env=env, cwd=tmp_path)

    entries = _read_tracker(tracker)
    assert len(entries) == 1
    assert entries[0]["id"] == "toolu_other"


def test_subagent_stop_tolerates_empty_tracker_file(hook, tmp_path):
    """subagent-stop is a no-op when the tracker file does not exist."""
    payload = _make_stop_payload(tool_use_id="toolu_nofile")
    env = {"KANBAN_SESSION": "empty-session"}

    # Must not raise; no file created
    _run_subcommand(hook, "subagent-stop", payload, env=env, cwd=tmp_path)

    tracker = tmp_path / ".scratchpad" / "orphan-tracker-empty-session.jsonl"
    assert not tracker.exists()


# ---------------------------------------------------------------------------
# Tests: user-prompt-submit subcommand
# ---------------------------------------------------------------------------

def test_user_prompt_submit_emits_nothing_when_tracker_empty(hook, tmp_path):
    """No output when the tracker file is empty."""
    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "quiet-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert output.strip() == ""


def test_user_prompt_submit_emits_nothing_when_no_tracker_file(hook, tmp_path):
    """No output when the tracker file does not exist."""
    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "nofile-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert output.strip() == ""


def test_user_prompt_submit_emits_warning_when_nonempty(hook, tmp_path):
    """Warning is emitted to stdout when tracker has active entries older than 5 minutes."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-warn-session.jsonl"
    _write_tracker(tracker, [
        {
            "id": "toolu_running",
            "description": "swe-backend working on card #99",
            "started_at": _minutes_ago_iso(10),
        }
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "warn-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert "background agent" in output.lower() or "background agents" in output.lower()
    assert "⚠️" in output


def test_user_prompt_submit_warning_includes_count(hook, tmp_path):
    """Warning includes the number of running agents."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-count-session.jsonl"
    _write_tracker(tracker, [
        {"id": "toolu_a1", "description": "agent one", "started_at": _minutes_ago_iso(10)},
        {"id": "toolu_a2", "description": "agent two", "started_at": _minutes_ago_iso(10)},
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "count-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert "2" in output


def test_user_prompt_submit_warning_includes_ids_and_descriptions(hook, tmp_path):
    """Warning includes agent IDs and descriptions."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-detail-session.jsonl"
    _write_tracker(tracker, [
        {
            "id": "toolu_xyzabc",
            "description": "swe-devex on orphan card",
            "started_at": _minutes_ago_iso(10),
        }
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "detail-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert "toolu_xyzabc" in output
    assert "swe-devex on orphan card" in output


def test_user_prompt_submit_warning_includes_duration(hook, tmp_path):
    """Warning includes a human-readable duration (e.g. 'minutes ago')."""
    started = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-dur-session.jsonl"
    _write_tracker(tracker, [
        {"id": "toolu_dur", "description": "long-running agent", "started_at": started}
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "dur-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    # Should mention "minute" or "minutes" as duration (30 min ago)
    assert "minute" in output.lower()


def test_user_prompt_submit_prunes_stale_entries(hook, tmp_path):
    """Entries older than 24h are pruned; no warning emitted for them."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-stale-session.jsonl"
    _write_tracker(tracker, [
        {
            "id": "toolu_stale",
            "description": "stale agent from yesterday",
            "started_at": _old_iso(hours=25),
        }
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "stale-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    # No warning should be emitted for stale entries
    assert output.strip() == ""

    # Stale entry should be pruned from the file
    entries = _read_tracker(tracker)
    assert all(e["id"] != "toolu_stale" for e in entries)


def test_user_prompt_submit_only_active_in_warning(hook, tmp_path):
    """A mix of active and stale entries: only non-recent active ones appear in the warning."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-mix-session.jsonl"
    _write_tracker(tracker, [
        {
            "id": "toolu_fresh",
            "description": "active agent over threshold",
            "started_at": _minutes_ago_iso(10),  # 10 min old — over 5-min threshold
        },
        {
            "id": "toolu_old",
            "description": "old stale agent",
            "started_at": _old_iso(hours=30),
        },
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "mix-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert "toolu_fresh" in output
    assert "toolu_old" not in output
    assert "1 background agent" in output.lower()


def test_user_prompt_submit_includes_taskstop_instruction(hook, tmp_path):
    """Warning text instructs coordinator to use TaskStop or wait."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-instr-session.jsonl"
    _write_tracker(tracker, [
        {"id": "toolu_live", "description": "running agent", "started_at": _minutes_ago_iso(10)}
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "instr-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert "TaskStop" in output


def test_user_prompt_submit_noop_when_no_session(hook, tmp_path):
    """No output when KANBAN_SESSION is not set."""
    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": ""}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert output.strip() == ""


def test_user_prompt_submit_burns_session_noop(hook, tmp_path):
    """No output when BURNS_SESSION=1."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-burns2-session.jsonl"
    _write_tracker(tracker, [
        {"id": "toolu_burns", "description": "burns agent", "started_at": _now_iso()}
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "burns2-session", "BURNS_SESSION": "1"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    # BURNS_SESSION=1 → hook exits immediately, no output
    assert output.strip() == ""


# ---------------------------------------------------------------------------
# New tests: duration threshold filter (F7 / F1)
# ---------------------------------------------------------------------------

def test_user_prompt_submit_suppresses_warning_for_recent_entries(hook, tmp_path):
    """Warning is suppressed for entries younger than 5 minutes (expected in-flight)."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-recent-session.jsonl"
    _write_tracker(tracker, [
        {
            "id": "toolu_recent",
            "description": "freshly launched agent",
            "started_at": _minutes_ago_iso(2),  # 2 minutes ago — under threshold
        }
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "recent-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert output.strip() == ""


def test_user_prompt_submit_emits_warning_for_old_entries(hook, tmp_path):
    """Warning is emitted for entries older than 5 minutes (possibly orphaned)."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-old-session.jsonl"
    _write_tracker(tracker, [
        {
            "id": "toolu_old_agent",
            "description": "long-running background agent",
            "started_at": _minutes_ago_iso(10),  # 10 minutes ago — over threshold
        }
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "old-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert "toolu_old_agent" in output
    assert "⚠️" in output


# ---------------------------------------------------------------------------
# New tests: description truncation (security F4)
# ---------------------------------------------------------------------------

def test_user_prompt_submit_truncates_long_description(hook, tmp_path):
    """Description longer than 120 chars is truncated with ellipsis in warning output."""
    long_desc = "x" * 200  # 200 chars — well over 120
    started = _minutes_ago_iso(10)
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-trunc-session.jsonl"
    _write_tracker(tracker, [
        {"id": "toolu_trunc", "description": long_desc, "started_at": started}
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "trunc-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert "..." in output
    # Full 200-char description should NOT appear verbatim
    assert long_desc not in output
    # Truncated prefix (first 120 chars) + ellipsis should appear
    assert long_desc[:120] + "..." in output


# ---------------------------------------------------------------------------
# New tests: session ID validation (security F1)
# ---------------------------------------------------------------------------

def test_get_tracker_path_rejects_invalid_session_id(hook):
    """get_tracker_path returns None for session IDs containing '/' (path traversal)."""
    result = hook.get_tracker_path("../evil")
    assert result is None


def test_pretool_noop_for_invalid_session_id(hook, tmp_path):
    """pretool does nothing when KANBAN_SESSION contains '/' (invalid session ID)."""
    payload = _make_pretool_payload(tool_use_id="toolu_traversal")
    env = {"KANBAN_SESSION": "../evil"}

    _run_subcommand(hook, "pretool", payload, env=env, cwd=tmp_path)

    # No tracker files should have been written
    scratchpad = tmp_path / ".scratchpad"
    tracker_files = list(scratchpad.glob("orphan-tracker-*.jsonl")) if scratchpad.exists() else []
    assert tracker_files == []


# ---------------------------------------------------------------------------
# New tests: file mode 0600 (security F2 + F6)
# ---------------------------------------------------------------------------

def test_pretool_tracker_file_created_with_mode_0600(hook, tmp_path):
    """Tracker file is created with mode 0600 (not world-readable)."""
    payload = _make_pretool_payload(tool_use_id="toolu_mode_test")
    env = {"KANBAN_SESSION": "mode-session"}

    _run_subcommand(hook, "pretool", payload, env=env, cwd=tmp_path)

    tracker = tmp_path / ".scratchpad" / "orphan-tracker-mode-session.jsonl"
    assert tracker.exists()
    mode = tracker.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0600, got {oct(mode)}"


# ---------------------------------------------------------------------------
# New test: stale file not read when KANBAN_SESSION unset (ai-expert F9)
# ---------------------------------------------------------------------------

def test_user_prompt_submit_does_not_read_stale_file_when_session_unset(hook, tmp_path):
    """user-prompt-submit does not read any tracker file when KANBAN_SESSION is unset.

    A stale tracker file from a prior session exists in the scratchpad, but
    with no session ID the hook must return immediately without reading it.
    """
    # Write a stale tracker file as if left by a previous session
    stale_tracker = tmp_path / ".scratchpad" / "orphan-tracker-prior-session.jsonl"
    _write_tracker(stale_tracker, [
        {
            "id": "toolu_stale_prior",
            "description": "agent from prior session",
            "started_at": _minutes_ago_iso(10),
        }
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": ""}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    # No warning should be emitted — session is absent
    assert output.strip() == ""


# ---------------------------------------------------------------------------
# New tests: warning text ordering and phantom-doing line
# ---------------------------------------------------------------------------

def test_user_prompt_submit_warning_leads_with_wait_before_taskstop(hook, tmp_path):
    """Warning text mentions 'Wait' before 'TaskStop' (non-destructive action first)."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-order-session.jsonl"
    _write_tracker(tracker, [
        {
            "id": "toolu_order",
            "description": "agent for ordering test",
            "started_at": _minutes_ago_iso(10),
        }
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "order-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    wait_pos = output.find("Wait")
    taskstop_pos = output.find("TaskStop")
    assert wait_pos != -1, "'Wait' not found in warning output"
    assert taskstop_pos != -1, "'TaskStop' not found in warning output"
    assert wait_pos < taskstop_pos, "'Wait' should appear before 'TaskStop' in the warning"


def test_user_prompt_submit_warning_includes_phantom_doing_distinguishing_line(hook, tmp_path):
    """Warning includes a line distinguishing in-flight agents from phantom-doing cards."""
    tracker = tmp_path / ".scratchpad" / "orphan-tracker-phantom-session.jsonl"
    _write_tracker(tracker, [
        {
            "id": "toolu_phantom_test",
            "description": "agent for phantom-doing test",
            "started_at": _minutes_ago_iso(10),
        }
    ])

    payload = _make_user_prompt_payload()
    env = {"KANBAN_SESSION": "phantom-session"}

    output = _run_subcommand(hook, "user-prompt-submit", payload, env=env, cwd=tmp_path)

    assert "phantom-doing" in output
