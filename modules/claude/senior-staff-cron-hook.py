#!/usr/bin/env python3
"""
senior-staff-cron-hook: SessionStart hook that injects a CronCreate prompt
for Senior Staff sessions only.

Triggered by Claude Code's SessionStart event. Reads the session payload from
stdin, checks KANBAN_AGENT environment variable, and — when the session is a
Senior Staff session — emits a {"result": "..."} JSON response that injects
a mandatory CronCreate directive into the model's initial context.

Output format (SessionStart hook):
    {"result": "<prompt_text>"} — injects text into session context
    (exit 0 with no stdout) — silent for non-Senior-Staff sessions

Fails open: any unhandled exception results in silent exit 0.
"""

import argparse
import json
import os
import sys

_CRON_PROMPT = (
    "[Senior Staff Harness] Session started. You are a Senior Staff Engineer session.\n"
    "\n"
    "REQUIRED IMMEDIATE ACTION: Call CronCreate now to schedule the 10-minute crew status pulse.\n"
    "- Schedule: */10 * * * *  (every 10 minutes)\n"
    "- Command: crew status --lines 20\n"
    "- Purpose: detect stalled, completed, or errored Staff sessions without waiting for user prompts\n"
    "- This is mandatory per § Periodic Crew Status Polling in your output style. Do not skip.\n"
    "\n"
    "If and only if CronCreate does not exist as a callable tool in this session, acknowledge this limitation in your next response to the user. Uncertainty about tool availability is NOT grounds for skipping — attempt CronCreate first."
)


class Send:
    """Output port for the hook."""

    def detected_senior_staff(self) -> None:
        """Emit the CronCreate prompt to stdout for injection into session context."""
        print(json.dumps({"result": _CRON_PROMPT}))
        print(
            "[senior-staff-cron-hook] CronCreate prompt injected for Senior Staff session",
            file=sys.stderr,
        )

    def skipped(self, reason: str) -> None:
        """Silent skip — log to stderr only."""
        print(f"[senior-staff-cron-hook] skipped: {reason}", file=sys.stderr)


def run(send: Send) -> None:
    """Core hook logic — pure, testable, send is the sole output."""
    kanban_agent = os.environ.get("KANBAN_AGENT")
    if kanban_agent != "senior-staff-engineer":
        send.skipped("not a Senior Staff session")
        return
    send.detected_senior_staff()


def show_help() -> None:
    print("senior-staff-cron-hook - SessionStart hook that injects CronCreate prompt for Senior Staff sessions")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code at session start.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  Injects a mandatory CronCreate directive into Senior Staff session context")
    print("  so the model schedules a recurring 'crew status' poll at startup.")
    print()
    print("TRIGGER:")
    print("  SessionStart — fires once at session start.")
    print("  Only emits a prompt when KANBAN_AGENT=senior-staff-engineer.")
    print("  Silent for all other sessions.")
    print()
    print("OUTPUT:")
    print("  Emits {\"result\": \"...\"} JSON with the CronCreate directive.")
    print("  Silent (no stdout) when KANBAN_AGENT is not 'senior-staff-engineer'.")
    print()
    print("CONFIGURATION:")
    print("  Configured in modules/claude/default.nix as SessionStart hook.")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    args, _ = parser.parse_known_args()
    if args.help:
        show_help()
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        if raw.strip():
            try:
                json.loads(raw)  # validate well-formed JSON; payload content is unused by design
            except json.JSONDecodeError:
                pass  # Fail open — empty payload is fine

        send = Send()
        run(send)
    except Exception:
        pass  # Fail open — never break SessionStart for all sessions


if __name__ == "__main__":
    main()
