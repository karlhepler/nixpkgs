#!/usr/bin/env python3
"""
git-no-verify-hook: PreToolUse(Bash) hook that denies git --no-verify bypass flags.

Triggered by Claude Code's PreToolUse event when tool_name == 'Bash'.
Blocks git push, git commit, and git merge commands that include hook-bypass
flags (--no-verify, --no-gpg-sign, -c commit.gpgsign=false) unless the user
has explicitly opted in via the CLAUDE_NOVERIFY_AUTHORIZED environment variable.

Output format (PreToolUse hook):
    {"decision": "block", "reason": "..."} — block the command
    (exit 0 with no output)               — allow (fail open)

Fails open: any error (JSON parse failure, missing fields) results in allowing.

BYPASS FLAGS DETECTED:
  --no-verify
  --no-gpg-sign
  -c commit.gpgsign=false

ENVIRONMENT:
  CLAUDE_NOVERIFY_AUTHORIZED=1  — Set to permit bypass flags (user opt-in).
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path


def show_help() -> None:
    print("git-no-verify-hook - PreToolUse hook that denies git --no-verify bypass flags")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  Prevents Claude Code from running git commands with --no-verify,")
    print("  --no-gpg-sign, or GPG-bypass env assignments unless the user has")
    print("  explicitly opted in via the CLAUDE_NOVERIFY_AUTHORIZED env variable.")
    print()
    print("TRIGGER:")
    print("  PreToolUse(Bash) — fires before every Bash tool call.")
    print("  Only blocks when the command targets git push, git commit, or git merge")
    print("  AND includes a hook-bypass flag.")
    print()
    print("BYPASS FLAGS DETECTED:")
    print("  --no-verify")
    print("  --no-gpg-sign")
    print("  -c commit.gpgsign=false")
    print()
    print("ENVIRONMENT:")
    print("  CLAUDE_NOVERIFY_AUTHORIZED=1  — Set to permit bypass flags (user opt-in).")
    print()
    print("CONFIGURATION:")
    print("  Configured in modules/claude/default.nix as PreToolUse(Bash) hook.")


_GIT_OP_PATTERN = re.compile(
    r'(^|[\s])git\s+(push|commit|merge)([\s]|$)',
)

# Also matches 'git -c commit.gpgsign=false commit/push/merge' where the
# -c flag precedes the subcommand (valid git invocation, same bypass effect).
_GIT_OP_WITH_PREARG_PATTERN = re.compile(
    r'(^|[\s])git\s+(-[^\s]+\s+)*(-c\s+commit\.gpgsign=false)\s+.*\b(push|commit|merge)\b',
)

_BYPASS_PATTERN = re.compile(
    r'(--no-verify|--no-gpg-sign|-c\s+commit\.gpgsign=false)',
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

    tool_name = payload.get("tool_name", "")
    # Only inspect Bash tool calls
    if tool_name != "Bash":
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "")

    # Check if the command involves a git operation that respects hooks.
    # Also detect 'git -c commit.gpgsign=false commit/push/merge' where the
    # bypass flag precedes the subcommand.
    has_git_op = _GIT_OP_PATTERN.search(command) or _GIT_OP_WITH_PREARG_PATTERN.search(command)
    if not has_git_op:
        sys.exit(0)

    # Check for hook-bypass flags
    if not _BYPASS_PATTERN.search(command):
        sys.exit(0)

    # Bypass flag detected — check for explicit user opt-in
    if os.environ.get("CLAUDE_NOVERIFY_AUTHORIZED") == "1":
        # Log the authorized bypass for audit trail
        msg = (
            f"[{datetime.datetime.now().isoformat()}] "
            f"AUTHORIZED: git hook bypass via CLAUDE_NOVERIFY_AUTHORIZED "
            f"for command: {command!r}"
        )
        try:
            log_path = Path.home() / ".claude" / "metrics" / "git-no-verify-bypass.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(msg + "\n")
        except Exception:
            pass
        sys.exit(0)

    # Block the command
    print(json.dumps({
        "decision": "block",
        "reason": (
            "git --no-verify / --no-gpg-sign requires explicit user approval per CLAUDE.md. "
            "Set CLAUDE_NOVERIFY_AUTHORIZED=1 in environment to opt in, "
            "or remove the flag and fix the underlying hook failure."
        ),
    }, separators=(",", ":")))
    sys.exit(0)


if __name__ == "__main__":
    main()
