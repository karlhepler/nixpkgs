#!/usr/bin/env python3
"""
kanban-mov-lint-hook: PreToolUse(Bash) hook — thin pass-through.

ARCHITECTURE NOTE: All banned-pattern validation has been moved into the kanban
CLI itself (modules/kanban/kanban.py — see validate_mov_commands_content). The
kanban CLI validates mov_commands[].cmd on BOTH the --file and inline-JSON code
paths for `kanban do` and `kanban todo`, so this hook is no longer the primary
defense.

This hook intentionally performs no validation and always allows. It is kept as
a no-op to avoid breaking the PreToolUse hook routing configuration (removing it
would require a modules/claude/default.nix change and an hms run).

The CLI-level validation (validate_mov_commands_content in kanban.py) is
sufficient and operates on all card-creation paths. Having both a hook-level
validator and a CLI-level validator would mean two separate copies of the same
logic drifting over time — worse than one authoritative copy.

Output format (PreToolUse hook — block-only format):
  {"decision": "block", "reason": "..."}  — block (never emitted)
  (exit 0 with no output)                 — allow
"""

import sys


def main() -> None:
    # Read and discard stdin (required to avoid broken pipe on hook invocation).
    sys.stdin.read()
    # Always allow — validation is now in the kanban CLI.
    sys.exit(0)


if __name__ == "__main__":
    main()
