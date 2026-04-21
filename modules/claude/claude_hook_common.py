#!/usr/bin/env python3
"""
claude_hook_common: Shared utilities for Claude Code hook scripts.

Provides common helpers used by claude-notification-hook.py,
claude-complete-hook.py, and claude-kanban-transition-hook.py.

Usage:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import claude_hook_common
"""

import os
import subprocess


def get_tmux_context() -> str:
    """Return 'session → window' if running inside tmux, otherwise empty string."""
    tmux = os.environ.get("TMUX", "")
    tmux_pane = os.environ.get("TMUX_PANE", "")
    if not tmux or not tmux_pane:
        return ""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-t", tmux_pane, "-p", "#S|#W"],
            capture_output=True, text=True, timeout=3,
        )
        session, _, window = result.stdout.strip().partition("|")
        if session and window:
            return f"{session} → {window}"
    except Exception:
        pass
    return ""


def send_notification(title: str, message: str, sound: str = "Ping") -> None:
    """Send a macOS notification via Alacritty using osascript.

    Escapes title and message for safe embedding in an AppleScript string
    literal: backslashes are doubled, double-quotes are backslash-escaped.
    This matches the bash send_notification escaping in claude-hook-common.bash.
    """
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
    safe_sound = sound.replace('"', '\\"')
    script = (
        f'tell application id "org.alacritty" to display notification '
        f'"{safe_message}" with title "{safe_title}" sound name "{safe_sound}"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def set_tmux_attention() -> None:
    """Set tmux window and session attention flags for the current pane."""
    tmux = os.environ.get("TMUX", "")
    tmux_pane = os.environ.get("TMUX_PANE", "")
    if not tmux or not tmux_pane:
        return
    try:
        subprocess.run(
            ["tmux", "set-window-option", "-t", tmux_pane, "@claude_attention", "1"],
            capture_output=True, timeout=3,
        )
        result = subprocess.run(
            ["tmux", "display-message", "-t", tmux_pane, "-p", "#S"],
            capture_output=True, text=True, timeout=3,
        )
        session = result.stdout.strip()
        if session:
            subprocess.run(
                ["tmux", "set-option", "-t", session, "@session_needs_attention", "1"],
                capture_output=True, timeout=3,
            )
    except Exception:
        pass
