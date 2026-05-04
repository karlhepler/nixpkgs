#!/usr/bin/env python3
"""
orphan-agent-tracker-hook: Three-event hook that tracks active background agents
and warns the coordinator before each user prompt if any agents are still running.

Three subcommands (dispatched via argv[1]):

  pretool
    Triggered by PreToolUse(Agent). Reads hook payload from stdin, extracts
    tool_use_id and description, appends an entry to the session-scoped
    tracker file: .scratchpad/orphan-tracker-<session>.jsonl

  subagent-stop
    Triggered by SubagentStop. Reads hook payload from stdin, extracts
    tool_use_id, removes the matching entry from the tracker file.

  user-prompt-submit
    Triggered by UserPromptSubmit. Reads the tracker file and emits a warning
    to stdout if any agents are still running. The warning is injected into
    coordinator context by Claude Code.

Tracker file format (one JSON object per line):
  {"id": "tool_use_id", "description": "...", "started_at": "ISO8601"}

Constraints:
  - Exit 0 always — hook must never block coordinator.
  - Broad try/except — no unhandled exceptions.
  - Concurrent-safe writes via fcntl.flock (exclusive lock on the tracker file).
  - Session detection via KANBAN_SESSION env var; no-op cleanly if absent.
  - Stale entries (> 24h old) are pruned silently in user-prompt-submit.
  - BURNS_SESSION=1 → no-op (Ralph manages its own state).
  - Recent entries (< 5 min old) are suppressed from the warning (expected in-flight).

# Reinforces:
#   staff-engineer.md § BEFORE SENDING (No orphan agents checklist item)
#   staff-engineer.md § Phantom-Doing Recovery (Post-Compaction)
"""

import fcntl
import json
import os
import re
import sys
import tempfile
import traceback
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Suppress Python deprecation warnings to prevent stderr output,
# which Claude Code interprets as hook errors.
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ERROR_LOG_PATH = Path.home() / ".claude" / "metrics" / "orphan-agent-tracker-hook-errors.log"
INFO_LOG_PATH = Path.home() / ".claude" / "metrics" / "orphan-agent-tracker-hook.log"

_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB cap before rotation

# Entries older than this are treated as stale and pruned.
_STALE_THRESHOLD = timedelta(hours=24)

# Entries younger than this are considered expected in-flight and do not trigger a warning.
_INFLIGHT_THRESHOLD = timedelta(minutes=5)

# Session ID validation pattern (matches kanban CLI constraints).
_SESSION_ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _rotate_log_if_needed(path: Path) -> None:
    """Rotate path → path.1 when the file exceeds _LOG_MAX_BYTES. Never raises."""
    try:
        if path.exists() and path.stat().st_size >= _LOG_MAX_BYTES:
            rotated = path.with_suffix(path.suffix + ".1")
            path.rename(rotated)
    except Exception:
        pass


def _write_log(path: Path, message: str) -> None:
    """Append a timestamped message to a log file. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed(path)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
        os.chmod(path, 0o600)
    except Exception:
        pass


def log_error(message: str) -> None:
    """Append an error to the hook error log. Never raises."""
    _write_log(ERROR_LOG_PATH, message)


def log_info(message: str) -> None:
    """Append an info message to the hook info log. Never raises."""
    _write_log(INFO_LOG_PATH, message)


# ---------------------------------------------------------------------------
# Session and tracker path helpers
# ---------------------------------------------------------------------------

def get_session_id() -> str:
    """Return the current kanban session ID from env. Empty string if not set."""
    return os.environ.get("KANBAN_SESSION", "").strip()


def get_tracker_path(session_id: str) -> Path | None:
    """Return the tracker file path for the given session.

    Returns None if session_id is empty or fails validation (caller should no-op).
    Validates session_id against [a-z0-9][a-z0-9-]{0,63} to prevent path traversal.
    Derives the .scratchpad/ directory from the current working directory.
    """
    if not session_id:
        return None
    if not _SESSION_ID_RE.match(session_id):
        return None
    cwd = Path.cwd()
    return cwd / ".scratchpad" / f"orphan-tracker-{session_id}.jsonl"


# ---------------------------------------------------------------------------
# JSONL tracker file I/O (flock-protected)
# ---------------------------------------------------------------------------

def _read_entries(tracker_path: Path) -> list[dict]:
    """Read all entries from the tracker file. Returns empty list on any error.

    Does NOT acquire a lock — callers that need atomic read-modify-write must
    hold the lock themselves while calling this function.
    """
    entries = []
    if not tracker_path.exists():
        return entries
    try:
        with open(tracker_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line, strict=False)
                    if isinstance(entry, dict):
                        entries.append(entry)
                except json.JSONDecodeError:
                    pass
    except (OSError, IOError) as exc:
        log_error(f"_read_entries: failed to read {tracker_path}: {exc}")
    return entries


def _write_entries_atomic(tracker_path: Path, entries: list[dict]) -> None:
    """Write entries to the tracker file atomically using a temp file + rename.

    Must be called while holding a flock on the tracker file (or its parent
    directory lock file). The atomic rename prevents partial writes from being
    visible to concurrent readers.

    Never raises — errors are logged to stderr.
    """
    tmp_file = None
    try:
        tracker_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = tempfile.NamedTemporaryFile(
            dir=tracker_path.parent,
            prefix="orphan-tracker-",
            suffix=".tmp",
            delete=False,
            mode="w",
            encoding="utf-8",
        )
        for entry in entries:
            tmp_file.write(json.dumps(entry) + "\n")
        tmp_file.close()
        tmp_path = Path(tmp_file.name)
        os.chmod(tmp_path, 0o600)
        os.rename(str(tmp_path), str(tracker_path))
        os.chmod(tracker_path, 0o600)
    except Exception as exc:
        if tmp_file is not None:
            try:
                tmp_file.close()
            except Exception:
                pass
            try:
                os.unlink(tmp_file.name)
            except Exception:
                pass
        log_error(f"_write_entries_atomic: failed to write {tracker_path}: {exc}")


def _lock_path_for(tracker_path: Path) -> Path:
    """Return the flock sentinel file path for a given tracker path."""
    return tracker_path.with_suffix(".lock")


# ---------------------------------------------------------------------------
# Subcommand: pretool
# ---------------------------------------------------------------------------

def cmd_pretool(payload: dict) -> None:
    """PreToolUse(Agent): record the new agent in the tracker file.

    Reads tool_use_id and description from the hook payload and appends a
    new entry to the session-scoped tracker file.

    Fails open: any error is logged; the hook always exits 0.
    """
    session_id = get_session_id()
    tracker_path = get_tracker_path(session_id)
    if tracker_path is None:
        log_info("pretool: no session ID — skipping orphan tracking")
        return

    tool_use_id = payload.get("tool_use_id", "") or ""
    tool_input = payload.get("tool_input", {}) or {}
    description = tool_input.get("description", "") or ""

    if not tool_use_id:
        log_info("pretool: no tool_use_id in payload — skipping")
        return

    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    new_entry = {
        "id": tool_use_id,
        "description": description,
        "started_at": now_iso,
    }

    lock_path = _lock_path_for(tracker_path)
    try:
        tracker_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a", encoding="utf-8") as lock_fh:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                existing = _read_entries(tracker_path)
                existing.append(new_entry)
                _write_entries_atomic(tracker_path, existing)
                log_info(
                    f"pretool: recorded agent id={tool_use_id!r} "
                    f"description={description!r:.50} session={session_id}"
                )
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
    except Exception as exc:
        log_error(f"pretool: unexpected error for session={session_id}: {exc}")


# ---------------------------------------------------------------------------
# Subcommand: subagent-stop
# ---------------------------------------------------------------------------

def cmd_subagent_stop(payload: dict) -> None:
    """SubagentStop: remove the stopped agent from the tracker file.

    Reads tool_use_id from the hook payload and removes the matching entry
    from the session-scoped tracker file.

    Tolerates missing entry — a stop event may fire after a session restart
    where the tracker file was already cleared. This is always exit 0.
    """
    session_id = get_session_id()
    tracker_path = get_tracker_path(session_id)
    if tracker_path is None:
        log_info("subagent-stop: no session ID — skipping")
        return

    tool_use_id = payload.get("tool_use_id", "") or ""
    if not tool_use_id:
        log_info("subagent-stop: no tool_use_id in payload — skipping")
        return

    lock_path = _lock_path_for(tracker_path)
    try:
        tracker_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a", encoding="utf-8") as lock_fh:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                existing = _read_entries(tracker_path)
                before_count = len(existing)
                filtered = [e for e in existing if e.get("id") != tool_use_id]
                after_count = len(filtered)
                if before_count != after_count:
                    _write_entries_atomic(tracker_path, filtered)
                    log_info(
                        f"subagent-stop: removed agent id={tool_use_id!r} session={session_id}"
                    )
                else:
                    # Entry not found — tolerate gracefully (session restart, duplicate stop, etc.)
                    log_info(
                        f"subagent-stop: id={tool_use_id!r} not found in tracker "
                        f"(already removed or session restart) — no-op"
                    )
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
    except Exception as exc:
        log_error(f"subagent-stop: unexpected error for session={session_id}: {exc}")


# ---------------------------------------------------------------------------
# Subcommand: user-prompt-submit
# ---------------------------------------------------------------------------

def _human_duration(started_at: str) -> str:
    """Return a human-readable duration string from an ISO8601 start time.

    Examples: '5 minutes', '2 hours 14 minutes', '3 days'.
    Falls back to the raw started_at string on any parse error.
    """
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - start
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "just now"
        if total_seconds < 60:
            return f"{total_seconds} second{'s' if total_seconds != 1 else ''}"
        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if hours < 24:
            if remaining_minutes:
                return (
                    f"{hours} hour{'s' if hours != 1 else ''} "
                    f"{remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}"
                )
            return f"{hours} hour{'s' if hours != 1 else ''}"
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''}"
    except Exception:
        return started_at


def _is_stale(entry: dict) -> bool:
    """Return True if the entry's started_at is older than _STALE_THRESHOLD."""
    try:
        started_at = entry.get("started_at", "")
        if not started_at:
            return False
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - start
        return age > _STALE_THRESHOLD
    except Exception:
        return False


def _is_recent(entry: dict) -> bool:
    """Return True if the entry's started_at is younger than _INFLIGHT_THRESHOLD.

    Entries this young are considered expected in-flight and should not trigger
    a warning — they haven't had time to become orphaned yet.
    """
    try:
        started_at = entry.get("started_at", "")
        if not started_at:
            return False
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - start
        return age < _INFLIGHT_THRESHOLD
    except Exception:
        return False


def _truncate_description(description: str, max_len: int = 120) -> str:
    """Truncate description to max_len chars with ellipsis if needed."""
    if len(description) > max_len:
        return description[:max_len] + "..."
    return description


def cmd_user_prompt_submit(_payload: dict) -> None:
    """UserPromptSubmit: emit a warning if any non-recent agents are still running.

    Reads the tracker file under lock, prunes stale entries (> 24h), and emits a
    formatted warning to stdout if any active agents that are older than 5 minutes
    remain. Entries younger than 5 minutes are expected in-flight and suppressed.
    The warning is injected into coordinator context by Claude Code.

    Empty output when no agents are running or all are recent (common path — no noise).
    """
    session_id = get_session_id()
    tracker_path = get_tracker_path(session_id)
    if tracker_path is None:
        return

    try:
        lock_path = _lock_path_for(tracker_path)
        active = []
        try:
            tracker_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lock_path, "a", encoding="utf-8") as lock_fh:
                os.chmod(lock_path, 0o600)
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
                try:
                    entries = _read_entries(tracker_path)
                    if not entries:
                        return

                    # Separate stale from non-stale entries
                    non_stale = [e for e in entries if not _is_stale(e)]
                    stale_count = len(entries) - len(non_stale)

                    # Prune stale entries from the tracker file
                    if stale_count:
                        _write_entries_atomic(tracker_path, non_stale)
                        log_info(
                            f"user-prompt-submit: pruned {stale_count} stale "
                            f"entries for session={session_id}"
                        )

                    # Only warn about entries older than _INFLIGHT_THRESHOLD (5 min)
                    active = [e for e in non_stale if not _is_recent(e)]
                finally:
                    fcntl.flock(lock_fh, fcntl.LOCK_UN)
        except Exception as exc:
            log_error(f"user-prompt-submit: lock/read error for session={session_id}: {exc}")
            return

        if not active:
            return

        count = len(active)
        agent_word = "agent" if count == 1 else "agents"
        lines = [
            f"⚠️ {count} background {agent_word} still running:",
            (
                "This warns about agents launched in this session that haven't sent "
                "completion notifications — distinct from phantom-doing cards "
                "(cards in 'doing' with no agent ever launched)."
            ),
        ]
        for entry in active:
            agent_id = entry.get("id", "unknown")
            raw_description = entry.get("description", "(no description)")
            description = _truncate_description(raw_description)
            duration = _human_duration(entry.get("started_at", ""))
            lines.append(f"  - {agent_id} ({description}): started {duration} ago")
        lines.append(
            "Wait for their completion notifications, or use TaskStop if an agent "
            "appears stuck, before briefing the user."
        )
        warning = "\n".join(lines)
        print(warning)
        log_info(
            f"user-prompt-submit: emitted warning for {count} running "
            f"{agent_word} in session={session_id}"
        )

    except Exception as exc:
        log_error(f"user-prompt-submit: unexpected error for session={session_id}: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Skip if running inside a Burns/Ralph session
    if os.environ.get("BURNS_SESSION") == "1":
        return

    if len(sys.argv) < 2:
        log_error("orphan-agent-tracker-hook: missing subcommand (pretool|subagent-stop|user-prompt-submit)")
        return

    subcommand = sys.argv[1]

    # Read payload from stdin
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw, strict=False) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        log_error(f"orphan-agent-tracker-hook: JSON decode error: {exc}")
        payload = {}
    except Exception as exc:
        log_error(f"orphan-agent-tracker-hook: stdin read error: {exc}")
        payload = {}

    try:
        if subcommand == "pretool":
            cmd_pretool(payload)
        elif subcommand == "subagent-stop":
            cmd_subagent_stop(payload)
        elif subcommand == "user-prompt-submit":
            cmd_user_prompt_submit(payload)
        else:
            log_error(f"orphan-agent-tracker-hook: unknown subcommand: {subcommand!r}")
    except Exception as exc:
        log_error(
            f"orphan-agent-tracker-hook: unhandled error in subcommand={subcommand!r}: "
            f"{exc}\n{traceback.format_exc()}"
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_error(f"orphan-agent-tracker-hook: fatal error: {exc}\n{traceback.format_exc()}")
    # Always exit 0 — hook must never block the coordinator
    sys.exit(0)
