#!/usr/bin/env python3
"""
telegram-gate-hook: PreToolUse hook that intercepts AskUserQuestion calls
and routes them to Telegram, blocking until the user responds.

When a Claude session has an active Telegram gate (flagged in
~/.claude/telegram/sessions/<kanban_name>), any AskUserQuestion tool call is
intercepted. The question is written to a pending file, and this hook polls
for a response file written by the Telegram bot. The hook returns deny with
the user's answer as the reason, which causes Claude Code to surface the
answer as context.

Output format (PreToolUse hook):
    allow: {"decision": "allow"}
    deny:  {"decision": "deny", "reason": "<message>"}

Fails open: any error results in allowing the tool call unchanged (exit 0).

Skip conditions:
    - BURNS_SESSION=1 env var (Ralph is running)
    - TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set
    - permission_mode is 'dontAsk' or 'bypassPermissions'
    - tool_name is not 'AskUserQuestion'
    - session map file missing for session_id
    - session flag file missing for kanban_name
"""

import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TELEGRAM_DIR = Path.home() / ".claude" / "telegram"
SESSION_MAP_DIR = TELEGRAM_DIR / "session-map"
SESSIONS_DIR = TELEGRAM_DIR / "sessions"
PENDING_DIR = TELEGRAM_DIR / "pending"
RESPONSES_DIR = TELEGRAM_DIR / "responses"
LOG_PATH = Path.home() / ".claude" / "metrics" / "telegram-gate-hook.log"

POLL_INTERVAL_SECONDS = 1
POLL_TIMEOUT_SECONDS = 3600


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    """Append a timestamped message to the log file. Never raises."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        import datetime
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def allow_unchanged() -> None:
    """Print allow decision to stdout."""
    print(json.dumps({"decision": "allow"}))


def deny_with_reason(reason: str) -> None:
    """Print deny decision with reason to stdout."""
    print(json.dumps({"decision": "deny", "reason": reason}))


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------

def read_context_snippets(transcript_path: str) -> list:
    """
    Read last 3 assistant messages from the transcript JSON-lines file.
    Returns a list of text strings. Never raises.
    """
    snippets = []
    try:
        p = Path(transcript_path)
        if not p.exists():
            return snippets
        lines = p.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if len(snippets) >= 3:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                snippets.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            snippets.append(text)
                            break
    except Exception as exc:
        log(f"context extraction error: {exc}")
    return list(reversed(snippets))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Skip condition: BURNS_SESSION=1 means Ralph is running
    if os.environ.get("BURNS_SESSION") == "1":
        allow_unchanged()
        return

    # Skip condition: Telegram credentials not configured
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        allow_unchanged()
        return

    # Read and parse stdin payload
    raw = sys.stdin.read()
    if not raw.strip():
        allow_unchanged()
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log(f"JSON decode error: {exc}")
        allow_unchanged()
        return

    # Skip condition: not an AskUserQuestion tool call
    tool_name = payload.get("tool_name", "")
    if tool_name != "AskUserQuestion":
        allow_unchanged()
        return

    # Skip condition: permission_mode is dontAsk or bypassPermissions
    permission_mode = payload.get("permission_mode", "")
    if permission_mode in ("dontAsk", "bypassPermissions"):
        allow_unchanged()
        return

    # Extract fields from payload
    session_id = payload.get("session_id", "")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    question = tool_input.get("question", "")
    options = tool_input.get("options", [])
    transcript_path = payload.get("transcript_path", "")

    # Skip condition: no session_id
    if not session_id:
        allow_unchanged()
        return

    # Look up kanban name from session map
    session_map_file = SESSION_MAP_DIR / session_id
    if not session_map_file.exists():
        allow_unchanged()
        return

    try:
        kanban_name = session_map_file.read_text(encoding="utf-8").strip()
    except Exception as exc:
        log(f"session map read error for {session_id}: {exc}")
        allow_unchanged()
        return

    if not kanban_name:
        allow_unchanged()
        return

    # Check session flag: gate is only active if sessions/<kanban_name> exists
    session_flag = SESSIONS_DIR / kanban_name
    if not session_flag.exists():
        allow_unchanged()
        return

    # Read context snippets from transcript
    context_snippets = read_context_snippets(transcript_path) if transcript_path else []

    # Generate unique request ID
    request_id = str(uuid.uuid4())

    # Write pending file
    pending_path = PENDING_DIR / f"{request_id}.json"
    response_path = RESPONSES_DIR / f"{request_id}.json"

    try:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
        pending_data = {
            "question": question,
            "options": options,
            "kanban_name": kanban_name,
            "machine_name": socket.gethostname(),
            "context_snippets": context_snippets,
            "transcript_path": transcript_path,
            "timestamp": time.time(),
        }
        pending_path.write_text(json.dumps(pending_data), encoding="utf-8")
        log(f"pending question written: {request_id} kanban={kanban_name}")
    except Exception as exc:
        log(f"failed to write pending file {request_id}: {exc}")
        allow_unchanged()
        return

    # Poll for response
    elapsed = 0
    answer = None
    while elapsed < POLL_TIMEOUT_SECONDS:
        if response_path.exists():
            try:
                response_data = json.loads(response_path.read_text(encoding="utf-8"))
                answer = response_data.get("answer", "")
                # Clean up both files
                try:
                    pending_path.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    response_path.unlink(missing_ok=True)
                except Exception:
                    pass
                log(f"response received for {request_id}: {answer!r}")
                break
            except Exception as exc:
                log(f"failed to read response file {request_id}: {exc}")
                break
        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

    if answer is not None:
        deny_with_reason("User answered via Telegram: " + answer)
    else:
        # Timeout: clean up pending file if still present
        try:
            pending_path.unlink(missing_ok=True)
        except Exception:
            pass
        log(f"timeout waiting for response: {request_id}")
        allow_unchanged()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"hook error: {exc}")
        allow_unchanged()
    sys.exit(0)
