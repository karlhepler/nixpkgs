#!/usr/bin/env python3
"""
telegram-notify-hook: Non-blocking Notification and Stop event hook.

Sends Telegram messages when Claude sessions go idle or complete,
so the user knows to check in.

Non-blocking hooks produce no stdout output and always exit 0.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ERROR_LOG_PATH = Path.home() / ".claude" / "metrics" / "claude-remote-telegram-gate-hook.log"
TELEGRAM_DIR = Path.home() / ".claude" / "claude-remote-telegram"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_error(message: str) -> None:
    """Append an error to the hook error log. Never raises."""
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> None:
    # Skip if running inside a Burns/Ralph session
    if os.environ.get("BURNS_SESSION") == "1":
        return

    # Read token and chat ID from environment
    bot_token = os.environ.get("CLAUDE_REMOTE_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("CLAUDE_REMOTE_TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return

    # Parse stdin JSON
    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log_error(f"JSON decode error: {exc}")
        return

    event_type = payload.get("hook_event_name", "")
    session_id = payload.get("session_id", "")

    # Look up kanban name from session map
    if not session_id:
        return

    session_map_path = TELEGRAM_DIR / "session-map" / session_id
    if not session_map_path.exists():
        return

    try:
        kanban_name = session_map_path.read_text(encoding="utf-8").strip()
    except OSError:
        return

    if not kanban_name:
        return

    # Check session flag
    session_flag_path = TELEGRAM_DIR / "sessions" / kanban_name
    if not session_flag_path.exists():
        return

    # Build message based on event type
    if event_type == "notification":
        notification_type = payload.get("notification_type", "")
        if notification_type not in ("idle_prompt", "permission_prompt"):
            return
        message = f"\U0001f514 {kanban_name}: Claude is waiting for input ({notification_type})"
    elif event_type == "stop":
        message = f"\U0001f3c1 Session {kanban_name} finished \u2014 waiting for next input"
    else:
        return

    # Build request body
    body: dict = {
        "chat_id": chat_id,
        "text": message,
    }

    # Check for thread root message ID
    thread_file = TELEGRAM_DIR / "threads" / kanban_name
    if thread_file.exists():
        try:
            root_id_str = thread_file.read_text(encoding="utf-8").strip()
            if root_id_str.isdigit():
                body["reply_parameters"] = {"message_id": int(root_id_str)}
        except OSError:
            pass

    # Send Telegram message
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    encoded = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_error(f"Unhandled exception: {exc}")
    sys.exit(0)
