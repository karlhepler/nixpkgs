#!/usr/bin/env python3
"""
claude-complete-hook: Claude Code completion event hook.

Consumes Claude Code completion events (Stop, SubagentStop) without
triggering any notifications or tmux attention flags.

Kanban state transition notifications and tmux red highlights are handled
exclusively by claude-kanban-transition-hook.py (notification = red tab).

Trigger: Stop and SubagentStop completion events.
Input:   JSON from stdin (Claude Code hook format).
Output:  None (completion hook has no JSON output contract).
"""

import sys

# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

_HELP = """\
claude-complete-hook - Internal Claude Code completion hook

DESCRIPTION:
  Internal hook script called automatically by Claude Code.
  Should not be invoked manually by users.

PURPOSE:
  Consumes Claude Code completion events without triggering any
  notifications or tmux attention flags. Kanban state transition
  notifications and tmux red highlights are handled exclusively by
  claude-kanban-transition-hook.py (notification = red tab).

TRIGGER:
  Automatically invoked by Claude Code on completion events:
  - Stop (main task completion)
  - SubagentStop (subagent task completion)

BEHAVIOR:
  - Consumes stdin (required by hook protocol)
  - Does NOT send macOS notifications
  - Does NOT set tmux @claude_attention (no notification = no red tab)

CONFIGURATION:
  Configured in modules/claude/default.nix as completion hook.
"""


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> None:
    # Consume stdin as required by the hook protocol
    sys.stdin.read()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(_HELP, end="")
        sys.exit(0)

    main()
