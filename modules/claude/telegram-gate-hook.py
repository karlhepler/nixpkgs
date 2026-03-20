#!/usr/bin/env python3
"""
telegram-gate-hook: PermissionRequest hook that intercepts permission requests
and routes them to Telegram, blocking until the user responds with Allow or Deny.

When a Claude session has an active Telegram gate (flagged in
~/.claude/claude-remote-telegram/sessions/<kanban_name>), permission requests
are intercepted. The request is written to a pending file, and this hook polls for
a response file written by the Telegram bot. The hook returns allow or deny
based on the user's response.

Output format (PermissionRequest hook):
    allow: {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    deny:  {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "deny", "reason": "<message>"}}}

Note: PermissionRequest hooks only fire when Claude Code has determined the user
must be prompted. This eliminates false positives from auto-approved calls.

Fails open: any error results in allowing the tool call unchanged (exit 0).

Skip conditions:
    - BURNS_SESSION=1 env var (Ralph is running)
    - CLAUDE_REMOTE_TELEGRAM_BOT_TOKEN or CLAUDE_REMOTE_TELEGRAM_CHAT_ID not set
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

TELEGRAM_DIR = Path.home() / ".claude" / "claude-remote-telegram"
SESSION_MAP_DIR = TELEGRAM_DIR / "session-map"
SESSIONS_DIR = TELEGRAM_DIR / "sessions"
PENDING_DIR = TELEGRAM_DIR / "pending"
RESPONSES_DIR = TELEGRAM_DIR / "responses"
LOG_PATH = Path.home() / ".claude" / "metrics" / "claude-remote-telegram-gate-hook.log"

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
    """Print allow decision to stdout (PermissionRequest format)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"}
        }
    }))


def deny_with_reason(reason: str) -> None:
    """Print deny decision with reason to stdout (PermissionRequest format)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "reason": reason}
        }
    }))


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def format_telegram_message(tool_name: str, tool_input: dict, kanban_name: str, machine_name: str) -> str:
    """
    Format a human-readable Telegram message describing what Claude wants to do.
    Shows the most relevant fields for each tool type so the user can approve/deny.
    """
    header = f"[{machine_name}] [{kanban_name}] Claude wants to use: {tool_name}"

    if tool_name == "Bash":
        command = tool_input.get("command", "(unknown)")
        description = tool_input.get("description", "")
        body = f"Command: {command}"
        if description:
            body += f"\nDescription: {description}"

    elif tool_name in ("Write", "Edit", "MultiEdit"):
        file_path = tool_input.get("file_path", "(unknown)")
        body = f"File: {file_path}"
        if tool_name == "Write":
            body += "\nAction: write (create/overwrite)"
        elif tool_name == "Edit":
            old = tool_input.get("old_string", "")
            body += f"\nAction: edit ({len(old)} chars replaced)"
        else:
            edits = tool_input.get("edits", [])
            body += f"\nAction: multi-edit ({len(edits)} edit(s))"

    elif tool_name == "Read":
        file_path = tool_input.get("file_path", "(unknown)")
        limit = tool_input.get("limit", "")
        offset = tool_input.get("offset", "")
        body = f"File: {file_path}"
        if limit:
            body += f"\nLines: {offset or 1}-{int(offset or 0) + int(limit)}"

    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "(unknown)")
        path = tool_input.get("path", "")
        body = f"Pattern: {pattern}"
        if path:
            body += f"\nIn: {path}"

    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "(unknown)")
        path = tool_input.get("path", "")
        body = f"Pattern: {pattern}"
        if path:
            body += f"\nIn: {path}"

    elif tool_name == "AskUserQuestion":
        question = tool_input.get("question", "(unknown)")
        options = tool_input.get("options", [])
        body = f"Question: {question}"
        if options:
            body += "\nOptions:\n" + "\n".join(f"  - {o}" for o in options)

    elif tool_name == "WebSearch":
        query = tool_input.get("query", "(unknown)")
        body = f"Query: {query}"

    elif tool_name == "WebFetch":
        url = tool_input.get("url", "(unknown)")
        prompt = tool_input.get("prompt", "")
        body = f"URL: {url}"
        if prompt:
            body += f"\nPrompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"

    elif tool_name == "Agent":
        description = tool_input.get("description", "")
        prompt = tool_input.get("prompt", "")
        body = f"Description: {description or '(none)'}"
        if prompt:
            body += f"\nPrompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}"

    else:
        body = json.dumps(tool_input, indent=2)[:400]

    return f"{header}\n\n{body}"


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
    # Read and parse stdin payload immediately
    raw = sys.stdin.read()

    # Skip condition: BURNS_SESSION=1 means Ralph is running
    if os.environ.get("BURNS_SESSION") == "1":
        allow_unchanged()
        return

    # Skip condition: Telegram credentials not configured
    if not os.environ.get("CLAUDE_REMOTE_TELEGRAM_BOT_TOKEN") or not os.environ.get("CLAUDE_REMOTE_TELEGRAM_CHAT_ID"):
        allow_unchanged()
        return

    if not raw.strip():
        allow_unchanged()
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log(f"JSON decode error: {exc}")
        allow_unchanged()
        return

    # Skip condition: permission_mode is dontAsk or bypassPermissions
    permission_mode = payload.get("permission_mode", "")
    if permission_mode in ("dontAsk", "bypassPermissions"):
        allow_unchanged()
        return

    # Extract fields from payload
    session_id = payload.get("session_id", "")
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
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

    # Build the human-readable message for Telegram
    machine_name = socket.gethostname()
    message = format_telegram_message(tool_name, tool_input, kanban_name, machine_name)

    # Generate unique request ID
    request_id = str(uuid.uuid4())

    # Write pending file
    pending_path = PENDING_DIR / f"{request_id}.json"
    response_path = RESPONSES_DIR / f"{request_id}.json"

    try:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
        pending_data = {
            "message": message,
            "options": ["Allow", "Deny"],
            "tool_name": tool_name,
            "tool_input": tool_input,
            "kanban_name": kanban_name,
            "machine_name": machine_name,
            "context_snippets": context_snippets,
            "transcript_path": transcript_path,
            "timestamp": time.time(),
        }
        pending_path.write_text(json.dumps(pending_data), encoding="utf-8")
        log(f"pending gate request written: {request_id} tool={tool_name} kanban={kanban_name}")
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
        if answer.lower() == "allow":
            allow_unchanged()
        else:
            deny_with_reason("User denied via Telegram")
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
