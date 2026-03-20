#!/usr/bin/env python3
"""
telegram-notify-hook: Non-blocking Notification and Stop event hook.

Sends Telegram messages when Claude sessions go idle or complete,
so the user knows to check in.

For permission_prompt notifications, writes a pending file for the bot
to pick up and present as an inline keyboard in Telegram.

Non-blocking hooks produce no stdout output and always exit 0.
"""

import json
import os
import socket
import sys
import urllib.request
import uuid
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
    # Parse stdin JSON
    raw = sys.stdin.read()

    # Debug: log full raw payload as first operation
    log_error(f"NOTIFY_DEBUG: {raw}")

    # Skip if running inside a Burns/Ralph session
    if os.environ.get("BURNS_SESSION") == "1":
        return

    # Check if we got anything
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

    # Handle Stop event: do NOT clean up session flag or pane file
    # The Stop event fires after EVERY Claude turn, not just session exit.
    # Cleanup happens via SessionEnd or claude-remote-telegram-ctl off.
    if event_type == "Stop":
        pass

    # Handle SessionEnd event: clean up session flag and pane file when session exits
    if event_type == "SessionEnd":
        pane_file_path = TELEGRAM_DIR / "panes" / kanban_name
        for cleanup_path in [session_flag_path, pane_file_path]:
            try:
                cleanup_path.unlink(missing_ok=True)
            except OSError:
                pass

    # Handle PostToolUse: resolve any pending permission prompts for this session
    if event_type == "PostToolUse":
        pending_dir = TELEGRAM_DIR / "pending"
        responses_dir = TELEGRAM_DIR / "responses"
        if pending_dir.exists():
            for pending_file in pending_dir.glob("*.json"):
                try:
                    data = json.loads(pending_file.read_text(encoding="utf-8"))
                except OSError:
                    continue
                if data.get("kanban_name") != kanban_name:
                    continue
                # Write cli_resolved response so the bot dismisses the Telegram message
                file_uuid = pending_file.stem
                response_file = responses_dir / f"{file_uuid}.json"
                if not response_file.exists():
                    try:
                        responses_dir.mkdir(parents=True, exist_ok=True)
                        response_file.write_text(
                            json.dumps({"answer": "cli_resolved"}),
                            encoding="utf-8",
                        )
                    except OSError as exc:
                        log_error(f"Failed to write cli_resolved for {file_uuid}: {exc}")
                # Remove the pending file so the bot stops watching it
                try:
                    pending_file.unlink(missing_ok=True)
                except OSError:
                    pass
        return

    # Handle permission_prompt: write pending file for the bot to pick up
    if event_type == "Notification":
        notification_type = payload.get("notification_type", "")

        if notification_type == "permission_prompt":
            pending_dir = TELEGRAM_DIR / "pending"
            pending_dir.mkdir(parents=True, exist_ok=True)
            pending_file = pending_dir / f"{uuid.uuid4()}.json"
            pending_payload = {
                "message": payload.get("message", "Claude needs your permission"),
                "options": ["Allow", "Deny"],
                "kanban_name": kanban_name,
                "machine_name": socket.gethostname(),
                "context_snippets": [],
                "transcript_path": payload.get("transcript_path", ""),
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            }
            try:
                pending_file.write_text(json.dumps(pending_payload), encoding="utf-8")
            except OSError as exc:
                log_error(f"Failed to write pending file: {exc}")
            return

        if notification_type != "idle_prompt":
            return

    # Read token and chat ID from environment (needed for Telegram send)
    bot_token = os.environ.get("CLAUDE_REMOTE_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("CLAUDE_REMOTE_TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return

    # Build message based on event type
    if event_type == "Notification":
        notification_type = payload.get("notification_type", "")
        message = f"\U0001f514 {kanban_name}: Claude is waiting for input ({notification_type})"
    elif event_type == "Stop":
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
