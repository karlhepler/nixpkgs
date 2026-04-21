#!/usr/bin/env python3
"""
kanban-permission-hook: PermissionRequest hook that auto-approves kanban commands.

Triggered by Claude Code on every PermissionRequest event (before the user is
asked to approve a tool call). Auto-approves any Bash tool call whose command
starts with "kanban", removing the need for interactive approval prompts on
every kanban invocation by background sub-agents.

Output format (PermissionRequest hook):
    {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    (exit 0 with no output) — falls through to next hook or normal flow

Fails open: any error (JSON parse failure, missing fields) results in silent exit 0.

INPUT (stdin):
  Claude Code PermissionRequest JSON with at minimum:
    { "tool_name": "Bash", "tool_input": { "command": "kanban ..." } }
"""

import json
import sys


def main() -> None:
    raw = sys.stdin.read()

    # Empty stdin — fail open
    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    command = payload.get("tool_input", {}).get("command", "")

    # Only act on Bash tool calls whose command is "kanban" or starts with "kanban ".
    # Require a word boundary to avoid matching hypothetical "kanbanctl" or similar.
    if tool_name == "Bash" and (command == "kanban" or command.startswith("kanban ")):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {"behavior": "allow"},
            }
        }))

    sys.exit(0)


if __name__ == "__main__":
    main()
