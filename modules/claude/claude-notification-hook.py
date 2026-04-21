#!/usr/bin/env python3
"""
claude-notification-hook: Claude Code Notification event hook.

Sends macOS notifications and sets tmux window attention flags when Claude
Code requires user input (permission prompts, elicitation dialogs).

Trigger: Notification events (permission_prompt, elicitation_dialog).
Input:   JSON from stdin (Claude Code hook format).
Output:  None (notification hook has no JSON output contract).
"""

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

_HELP = """\
claude-notification-hook - Internal Claude Code notification hook

DESCRIPTION:
  Internal hook script called automatically by Claude Code.
  Should not be invoked manually by users.

PURPOSE:
  Sends macOS notifications and sets tmux window attention flags
  when Claude Code requires user input (permission prompts, elicitation dialogs).

TRIGGER:
  Automatically invoked by Claude Code on Notification events.
  Only fires on: permission_prompt, elicitation_dialog

BEHAVIOR:
  - Parses JSON input from stdin (Claude Code hook format)
  - Sends macOS notification via Alacritty (title: '❓ Question')
  - Sets tmux @claude_attention window option
  - Plays 'Ping' notification sound

CONFIGURATION:
  Configured in modules/claude/default.nix as notification hook.
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_common():
    """Import claude_hook_common from the same directory as this script."""
    sys.path.insert(0, str(Path(__file__).parent))
    import claude_hook_common  # noqa: PLC0415
    return claude_hook_common


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> None:
    common = _load_common()

    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    notification_type = data.get("notification_type", "")

    # Only notify for question/input events
    if notification_type not in ("permission_prompt", "elicitation_dialog"):
        return

    message = data.get("message", "Claude needs input")

    # Prepend tmux context to message if available
    tmux_context = common.get_tmux_context()
    if tmux_context:
        message = f"{tmux_context}\n{message}"

    common.send_notification("❓ Question", message, "Ping")
    common.set_tmux_attention()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(_HELP, end="")
        sys.exit(0)

    main()
