#!/usr/bin/env python3
"""
senior-staff-cron-hook: SessionStart hook for Senior Staff sessions.

Triggered by Claude Code's SessionStart event. Previously injected an
unconditional CronCreate directive. Now a no-op: pulse cron lifecycle is
managed by crew-lifecycle-hook (PostToolUse) — cron is created on first
'crew create' and deleted when the last Staff session is dismissed.

Retained as a registered hook so that existing sstaff sessions running the
old cron design are not disrupted (backward compatibility). No output is
emitted for new sessions.

Output format (SessionStart hook):
    (exit 0 with no stdout) — always silent

Fails open: any unhandled exception results in silent exit 0.
"""

import argparse
import os
import sys


class Send:
    """Output port for the hook."""

    def skipped(self, reason: str) -> None:
        """Silent skip — log to stderr only."""
        print(f"[senior-staff-cron-hook] skipped: {reason}", file=sys.stderr)


def run(send: Send) -> None:
    """Core hook logic — pure, testable, send is the sole output.

    Cron lifecycle is now managed by crew-lifecycle-hook (PostToolUse on
    'crew create' / 'crew dismiss'). SessionStart no longer installs a cron
    so that no tokens are spent when no Staff sessions exist.
    """
    kanban_agent = os.environ.get("KANBAN_AGENT")
    if kanban_agent != "senior-staff-engineer":
        send.skipped("not a Senior Staff session")
        return
    send.skipped("cron lifecycle delegated to crew-lifecycle-hook (PostToolUse)")


def show_help() -> None:
    print("senior-staff-cron-hook - SessionStart hook for Senior Staff sessions (no-op)")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code at session start.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  Previously injected a CronCreate directive at session start.")
    print("  Cron lifecycle is now managed by crew-lifecycle-hook (PostToolUse):")
    print("  cron is created on first 'crew create' and deleted when the last")
    print("  Staff session is dismissed. No tokens wasted on idle SessionStart.")
    print()
    print("TRIGGER:")
    print("  SessionStart — fires once at session start.")
    print("  Always silent (no stdout). Logs to stderr only.")
    print()
    print("OUTPUT:")
    print("  No output (cron lifecycle managed by crew-lifecycle-hook).")
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
        sys.stdin.read()  # consume stdin; payload unused by design
        send = Send()
        run(send)
    except Exception:
        pass  # Fail open — never break SessionStart for all sessions


if __name__ == "__main__":
    main()
