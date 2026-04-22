#!/usr/bin/env python3
"""
bash-cd-compound-hook: PreToolUse(Bash) hook that blocks cd-compound anti-patterns.

Triggered by Claude Code's PreToolUse event when tool_name == 'Bash'.
Blocks commands matching: cd <path> && cmd, cd <path>; cmd, cd <path> ; cmd

ALLOWED (subshell form — cd does not persist):
  (cd /path && cmd)
  bash -c 'cd /path && cmd'

BLOCKED (persistent cd):
  cd /path && cmd
  cd /path; cmd
  cd /path ; cmd
  cd - && cmd
  cd && cmd
  cd ~/path && cmd
  cd $VAR && cmd

Output format (PreToolUse hook — block-only format):
  {"decision": "block", "reason": "..."}  — block
  (exit 0 with no output)                 — allow (fail open)

Fails open: any error (JSON parse failure, shlex error) results in allowing.
No bypass mechanism — use subshell form (cd X && cmd) instead.
"""

import json
import shlex
import sys


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SHELL_OPS = frozenset(["&&", "||", ";", "|", "&"])

_REJECTION_REASON = (
    "cd-compound anti-pattern detected. Shell state persists between Bash tool calls "
    "— the working directory is already set from previous calls, so prepending "
    "`cd <dir>` is unnecessary.\n\n"
    "Run the command directly without the `cd` prefix:\n"
    "  WRONG:   cd /some/path && rg \"pattern\"\n"
    "  CORRECT: rg \"pattern\" /some/path\n"
    "  OR:      rg \"pattern\"   (if already in /some/path)\n\n"
    "If the command does not accept a path argument (npm test, make build), ensure\n"
    "the working directory is correct BEFORE this Bash call — shell state persists,\n"
    "so you can rely on pwd being set from earlier in the session.\n\n"
    "If you genuinely need an isolated cd that does NOT affect subsequent Bash calls, "
    "use a subshell:\n"
    "  ALLOWED: (cd /tmp && some-command)\n\n"
    "This is a hard block with no bypass — use the subshell form or remove the cd."
)


# ---------------------------------------------------------------------------
# Detection logic
# ---------------------------------------------------------------------------

def _normalize_semicolons(tokens: list) -> list:
    """
    Expand tokens that embed bare semicolons into separate tokens.

    shlex.split does not treat ';' as an operator — it merges it with adjacent
    content when there is no surrounding whitespace (e.g., '/path;' or ';ls').
    This function splits those embedded semicolons so that _split_on_operators
    can correctly identify command segment boundaries.

    Examples:
      ['/path;', 'ls']   → ['/path', ';', 'ls']
      ['/path', ';ls']   → ['/path', ';', 'ls']
    """
    result = []
    for tok in tokens:
        if ';' not in tok:
            result.append(tok)
            continue
        # Split token on ';' and re-insert ';' as a standalone operator token
        # between the parts. Empty parts (from leading/trailing ';') are omitted.
        parts = tok.split(';')
        for i, part in enumerate(parts):
            if part:
                result.append(part)
            if i < len(parts) - 1:
                result.append(';')
    return result


def _split_on_operators(tokens: list) -> list:
    """Split token list on shell control operators into command segments."""
    segments = []
    current = []
    for tok in tokens:
        if tok in _SHELL_OPS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def _check_line(line: str) -> bool:
    """
    Return True if this single command line contains a cd-compound pattern.

    Uses shlex tokenization to correctly handle quoted strings (so cd inside
    echo '...' or bash -c '...' is not a false positive).
    """
    line = line.strip()
    if not line or 'cd' not in line:
        return False

    try:
        tokens = shlex.split(line)
    except ValueError:
        # Unterminated quotes or shlex error — fail open
        return False

    if not tokens:
        return False

    segments = _split_on_operators(_normalize_semicolons(tokens))

    # Block if cd is the first token of any segment that is NOT the last segment.
    # "Not the last segment" means there's a command following it — the compound form.
    for i, segment in enumerate(segments):
        if not segment:
            continue

        first = segment[0]

        # Subshell guard: token starts with '(' → skip (subshell, cd doesn't persist)
        if first.startswith('('):
            continue

        # Word-boundary check: must be exactly 'cd', not 'pcd', 'ccd', etc.
        if first == 'cd' and i < len(segments) - 1:
            return True

    return False


def is_cd_compound(command: str) -> bool:
    """
    Return True if the command contains a cd-compound anti-pattern.

    Fails open (returns False) on any error.
    """
    if not command or 'cd' not in command:
        return False

    # Check each line (multi-line commands)
    for line in command.splitlines():
        if _check_line(line):
            return True

    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()

    # Empty stdin — fail open (allow)
    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # Only inspect Bash tool calls
    tool_name = payload.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "")

    if not is_cd_compound(command):
        sys.exit(0)

    # Block the command
    print(json.dumps({
        "decision": "block",
        "reason": _REJECTION_REASON,
    }, separators=(",", ":")))
    sys.exit(0)


if __name__ == "__main__":
    main()
