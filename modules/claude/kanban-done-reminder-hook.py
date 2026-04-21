#!/usr/bin/env python3
"""
kanban-done-reminder-hook: PostToolUse(Bash) hook that reminds coordinator to
run Mandatory Review Check after 'kanban done <N>'.

Triggered by Claude Code's PostToolUse event when tool_name == 'Bash'.
Emits an additionalContext reminder whenever the command matches
'kanban done <something>' so the Mandatory Review Check is never silently
skipped (the assembly-line anti-pattern).

Output format (PostToolUse hook):
    {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}
    (exit 0 with no output) — silent for all other commands

Fails open: any error results in silent exit 0.
"""

import argparse
import json
import re
import sys


def show_help() -> None:
    print("kanban-done-reminder-hook - PostToolUse hook that reminds coordinator to run Mandatory Review Check")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  Injects a reminder into Claude's context whenever the coordinator")
    print("  runs 'kanban done <N>' so the Mandatory Review Check is never")
    print("  silently skipped (the assembly-line anti-pattern).")
    print()
    print("TRIGGER:")
    print("  PostToolUse(Bash) — fires after every Bash tool call.")
    print("  Only emits a reminder when the command starts with 'kanban done '")
    print("  followed by a card number or other arguments.")
    print("  Silent for all other commands.")
    print()
    print("OUTPUT:")
    print("  Emits hookSpecificOutput.additionalContext with the review reminder.")
    print("  Silent (no stdout) when command does not match.")
    print()
    print("CONFIGURATION:")
    print("  Configured in modules/claude/default.nix as PostToolUse(Bash) hook.")


# Match "kanban done <something>" anchored to the start of the command (after
# stripping leading whitespace). Avoids false positives on:
# - "kanban done-something" (no space after "done")
# - "git commit -m 'kanban done 42'" ("kanban done" appears mid-string, not at start)
# Pattern: start-of-string, "kanban done ", then at least one non-space character.
_KANBAN_DONE_PATTERN = re.compile(
    r'^kanban\s+done\s+\S',
)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    args, _ = parser.parse_known_args()
    if args.help:
        show_help()
        sys.exit(0)

    raw = sys.stdin.read()

    # Empty stdin — fail open
    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "").lstrip()

    if _KANBAN_DONE_PATTERN.match(command):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    "Reminder: Run the Mandatory Review Check per "
                    "§ Mandatory Review Protocol before briefing user, "
                    "creating follow-up cards, or performing git ops. "
                    "Check tier matrix."
                ),
            }
        }))

    sys.exit(0)


if __name__ == "__main__":
    main()
