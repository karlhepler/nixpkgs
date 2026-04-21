#!/usr/bin/env python3
"""
taskstop-reminder-hook: PostToolUse(TaskStop) hook that reminds coordinator to
run orphan cleanup after TaskStop.

Triggered by Claude Code's PostToolUse event when tool_name == 'TaskStop'.
Always emits an additionalContext reminder that child processes spawned via
the agent's Bash tool are NOT killed by TaskStop and require manual orphan
cleanup per § Card Lifecycle.

Output format (PostToolUse hook):
    {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}

Always emits the reminder regardless of TaskStop input.
Fails open: any JSON parse error is silently ignored (reminder still emits).
"""

import argparse
import json
import sys


def show_help() -> None:
    print("taskstop-reminder-hook - PostToolUse hook that reminds coordinator to run orphan cleanup after TaskStop")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  After TaskStop kills a sub-agent, injects a reminder that child")
    print("  processes spawned via the agent's Bash tool are NOT killed and")
    print("  require manual orphan cleanup per § Card Lifecycle.")
    print()
    print("TRIGGER:")
    print("  PostToolUse(TaskStop) — fires after every TaskStop tool call.")
    print("  Always emits the orphan-cleanup reminder regardless of TaskStop input.")
    print()
    print("OUTPUT:")
    print("  Always emits hookSpecificOutput.additionalContext with the orphan cleanup reminder.")
    print()
    print("CONFIGURATION:")
    print("  Configured in modules/claude/default.nix as PostToolUse(TaskStop) hook.")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    args, _ = parser.parse_known_args()
    if args.help:
        show_help()
        sys.exit(0)

    raw = sys.stdin.read()

    # Consume stdin — validate JSON if present, but always emit regardless
    if raw.strip():
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            pass  # Fail open — emit reminder anyway

    # Always emit the orphan-cleanup reminder
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                "Reminder: TaskStop killed the agent but NOT its child processes. "
                "Run orphan cleanup per § Card Lifecycle. Check the card's action "
                "field for long-running processes (test runners, dev servers, watchers) "
                "and kill them via pkill before proceeding."
            ),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
