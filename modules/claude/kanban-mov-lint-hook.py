#!/usr/bin/env python3
"""
kanban-mov-lint-hook: PreToolUse(Bash) hook that lints MoV patterns in kanban card files.

Triggered by Claude Code's PreToolUse event when tool_name == 'Bash'.
Intercepts `kanban do --file <path>` and `kanban todo --file <path>` invocations,
reads the referenced JSON file, and rejects banned MoV patterns before the
kanban CLI runs.

Output format (PreToolUse hook — block-only format):
  {"decision": "block", "reason": "..."}  — block
  (exit 0 with no output)                 — allow (fail open)

Fails open: any error (JSON parse failure, file not found, missing fields)
results in allowing. Never accidentally block innocent commands.

For hook-skip-flag detection, parse failures fail CLOSED (block as a
precaution) — see LIMITATIONS section below.

BANNED PATTERNS:
  rg -E variants: rg -qiE, rg -qEi, rg -E, rg -iE, etc.
    (-E means --encoding in ripgrep, not extended regex. PCRE2 is the default.)
  Hook-skip flags: --no-verify, --no-gpg-sign, git commit -n, HUSKY=0,
    HUSKY_SKIP_HOOKS=1 (should never appear in MoVs).

LIMITATIONS / SCOPE:
  This hook is a discipline aid, not a hard security boundary.
  - Only intercepts `kanban do/todo --file`. Inline card JSON or direct
    file writes via Edit/Write tools are NOT checked.
  - Paths outside the current project working directory are not read
    (path-containment fail-open).
  - File paths containing spaces are not currently parsed (kanban CLI
    never produces such paths).
  - TOCTOU: the hook reads the file at PreToolUse time; the kanban CLI
    re-reads at execution. A racing process could swap the file between
    these two reads. Threat model: coordinator self-discipline, not
    adversarial defense.
  - For hook-skip-flag detection (--no-verify family), parse failures
    fail CLOSED (block as a precaution). For rg -E lint, parse failures
    fail open.
  - cmd values are echoed verbatim (after non-printable sanitization)
    in denial messages. Card authors must NOT put credentials in cmd
    fields; that is a card-authoring error.
"""

import json
import re
import shlex
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Banned pattern definitions
# ---------------------------------------------------------------------------
#
# Each entry is a tuple of (compiled_regex, name, fix_suggestion).
# To add a new banned pattern, add a one-liner tuple here.
#
# The regex is matched against each `cmd` string in mov_commands.
#
# HOOK_SKIP_PATTERNS contains the security-critical patterns for which
# parse failures fail CLOSED rather than open.

HOOK_SKIP_LITERALS: list[str] = [
    "--no-verify",
    "--no-gpg-sign",
    "HUSKY=0",
    "HUSKY_SKIP_HOOKS=1",
    "git commit -n",
]

BANNED_PATTERNS: list[tuple[re.Pattern, str, str, bool]] = [
    (
        # Match any rg invocation where the flag bundle contains capital E.
        # Handles: rg -E, rg -qE, rg -qiE, rg -qEi, rg -iE, rg -EI, etc.
        # Does NOT match: rg -qi -e 'foo' (lowercase -e is fine)
        # Does NOT match: grep -E or other non-rg tools
        re.compile(r'\brg\s+-[a-zA-Z]*E[a-zA-Z]*\b'),
        "rg -E (capital -E flag)",
        (
            "In ripgrep, `-E` means `--encoding`, NOT extended regex. "
            "PCRE2 regex is the default — no flag needed. "
            "Fix: replace `rg -qiE` with `rg -qi`, `rg -E` with `rg`, etc. "
            "If you need to pass a pattern starting with a dash, use `rg -qi -e 'pattern'` "
            "(lowercase `-e`)."
        ),
        False,  # rg -E lint: fail open on parse error
    ),
    (
        re.compile(r'--no-verify\b'),
        "--no-verify (hook-skip flag)",
        (
            "`--no-verify` skips git hooks and must never appear in a MoV. "
            "Remove the flag. If the underlying hook failure is the real issue, "
            "diagnose and fix it instead."
        ),
        True,  # hook-skip: fail closed on parse error
    ),
    (
        re.compile(r'--no-gpg-sign\b'),
        "--no-gpg-sign (hook-skip flag)",
        (
            "`--no-gpg-sign` bypasses commit signing and must never appear in a MoV. "
            "Remove the flag."
        ),
        True,  # hook-skip: fail closed on parse error
    ),
    (
        # Handled separately via shlex tokenization — see _is_git_commit_n()
        # This regex is kept as a fallback for regex-based scanning only.
        # shlex-based detection takes precedence for this pattern.
        re.compile(r'(?!x)x'),  # Never matches — shlex path handles this
        "git commit -n (hook-skip short flag)",
        (
            "`git commit -n` is shorthand for `--no-verify` and must never appear in a MoV. "
            "Remove the `-n` flag."
        ),
        True,  # hook-skip: fail closed on parse error
    ),
    (
        re.compile(r'\bHUSKY\s*=\s*0\b'),
        "HUSKY=0 (hook-skip env var)",
        (
            "`HUSKY=0` disables all husky hooks and must never appear in a MoV. "
            "Remove the env var assignment."
        ),
        True,  # hook-skip: fail closed on parse error
    ),
    (
        re.compile(r'\bHUSKY_SKIP_HOOKS\s*=\s*1\b'),
        "HUSKY_SKIP_HOOKS=1 (hook-skip env var)",
        (
            "`HUSKY_SKIP_HOOKS=1` disables husky hooks and must never appear in a MoV. "
            "Remove the env var assignment."
        ),
        True,  # hook-skip: fail closed on parse error
    ),
]


# ---------------------------------------------------------------------------
# shlex-based git commit -n detection
# ---------------------------------------------------------------------------

def _is_git_commit_n(cmd: str) -> bool:
    """
    Return True if cmd is a git commit invocation that includes -n as a flag
    (the short form of --no-verify).

    Uses shlex tokenization to avoid false-positives on commit messages that
    contain '-n' as a word (e.g., 'git commit -m "-n items processed"').

    Fails open (returns False) if shlex parsing fails.
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        # Unterminated quotes or other shlex errors — fail open
        return False

    if not tokens:
        return False

    # Find 'git' token
    try:
        git_idx = tokens.index("git")
    except ValueError:
        return False

    post_git = tokens[git_idx + 1:]

    # Find 'commit' subcommand (skip any pre-subcommand git flags)
    commit_idx = None
    for i, tok in enumerate(post_git):
        if tok == "commit":
            commit_idx = i
            break
        if not tok.startswith("-"):
            # Some other subcommand — not a commit
            return False

    if commit_idx is None:
        return False

    # Walk tokens after 'commit' looking for -n flag
    # Flags that take a value argument — skip their next token
    flags_with_args = frozenset(["-m", "--message", "-F", "--file",
                                 "-C", "--reuse-message", "--author", "--date"])
    post_commit = post_git[commit_idx + 1:]
    i = 0
    while i < len(post_commit):
        tok = post_commit[i]
        if tok in flags_with_args:
            # Skip the next token (it's the flag's value, not a flag itself)
            i += 2
            continue
        if tok == "--":
            # End of flags
            break
        if tok.startswith("-") and not tok.startswith("--"):
            # Short flag bundle: check if 'n' is in it
            flag_chars = tok[1:]  # strip leading '-'
            if "n" in flag_chars:
                return True
        i += 1

    return False


# ---------------------------------------------------------------------------
# Command detection
# ---------------------------------------------------------------------------

def _extract_file_path(command: str) -> "str | None":
    """
    Extract the --file <path> argument from a kanban do/todo command.

    Handles these forms:
      kanban do --file /path/to/file.json
      kanban do --file=/path/to/file.json
      kanban todo --file '/path/to/file.json'
      kanban todo --file "/path/to/file.json"

    Returns the file path string, or None if not found.
    """
    # Match --file=path or --file path (with optional quotes)
    pattern = re.compile(
        r'--file[=\s]+["\']?([^\s"\']+)["\']?'
    )
    m = pattern.search(command)
    if m:
        return m.group(1)
    return None


def _is_kanban_with_file(command: str) -> bool:
    """Return True if the command is a kanban do/todo invocation with --file."""
    if '--file' not in command:
        return False
    # Check for 'kanban do' or 'kanban todo' anywhere in the command
    return bool(re.search(r'\bkanban\s+(do|todo)\b', command))


# ---------------------------------------------------------------------------
# JSON card parsing
# ---------------------------------------------------------------------------

def _iter_cards(data) -> list:
    """Normalize card data to a list of card dicts."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _scan_card_for_banned(card: dict, card_index: int) -> "tuple[int, int, str, str, str] | None":
    """
    Scan a single card dict for banned MoV patterns.

    Returns (criterion_index, mov_idx, cmd, pattern_name, fix_suggestion) for
    the first match found, or None if the card is clean.

    Scans: criteria[*].mov_commands[*].cmd
    """
    criteria = card.get("criteria", [])
    if not isinstance(criteria, list):
        return None

    for crit_idx, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            continue
        mov_commands = criterion.get("mov_commands", [])
        if not isinstance(mov_commands, list):
            continue
        for mov_idx, mov in enumerate(mov_commands):
            if not isinstance(mov, dict):
                continue
            cmd = mov.get("cmd", "")
            if not cmd or not isinstance(cmd, str):
                continue

            # Check git commit -n via shlex (takes precedence over regex for this pattern)
            if _is_git_commit_n(cmd):
                # Find the git commit -n entry to get its fix suggestion
                for pattern, name, fix, _ in BANNED_PATTERNS:
                    if name == "git commit -n (hook-skip short flag)":
                        return (crit_idx, mov_idx, cmd, name, fix)

            # Check remaining patterns via regex
            for pattern, name, fix, _ in BANNED_PATTERNS:
                if name == "git commit -n (hook-skip short flag)":
                    # Already handled by shlex above — skip regex path
                    continue
                if pattern.search(cmd):
                    return (crit_idx, mov_idx, cmd, name, fix)

    return None


def _raw_text_has_hook_skip_flag(raw_text: str) -> bool:
    """
    Perform a text-level substring scan for hook-skip flag literals.

    Used as a fail-closed fallback when JSON parsing fails. If any hook-skip
    flag literal appears anywhere in the raw file text, return True (block).

    This is a conservative substring scan — not a precise parser. A legitimate
    file that happens to contain the substring '--no-verify' in a comment
    would be blocked. That is intentional: on parse failure, we err closed.
    """
    for literal in HOOK_SKIP_LITERALS:
        if literal in raw_text:
            return True
    return False


# ---------------------------------------------------------------------------
# ANSI / non-printable sanitization
# ---------------------------------------------------------------------------

def _sanitize_cmd(cmd: str) -> str:
    """
    Replace non-printable characters (other than \\n and \\t) in cmd with '?'.

    Prevents ANSI escape sequence injection in denial messages.
    """
    return ''.join(c if c.isprintable() or c in ('\n', '\t') else '?' for c in cmd)


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

    # Only activate for kanban do/todo --file invocations
    if not _is_kanban_with_file(command):
        sys.exit(0)

    file_path_str = _extract_file_path(command)
    if not file_path_str:
        # Could not extract path — fail open
        sys.exit(0)

    file_path = Path(file_path_str)

    # Path containment: resolve and verify the file is inside the current
    # working directory. If outside, fail open (not our concern).
    try:
        resolved = file_path.resolve()
        cwd_resolved = Path.cwd().resolve()
        if not str(resolved).startswith(str(cwd_resolved) + "/") and resolved != cwd_resolved:
            sys.exit(0)
    except OSError:
        sys.exit(0)

    # File doesn't exist or isn't readable — let kanban CLI handle it
    if not file_path.exists():
        sys.exit(0)

    # File size guard: abnormally large files fail open to avoid latency
    try:
        if file_path.stat().st_size > 1_000_000:
            sys.exit(0)
    except OSError:
        sys.exit(0)

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        sys.exit(0)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Invalid JSON — fail closed for hook-skip-flag detection.
        # Do a text-level fallback scan of raw file contents for hook-skip literals.
        if _raw_text_has_hook_skip_flag(content):
            reason = (
                "Card file could not be parsed — blocked as a precaution. "
                "Fix the JSON and retry.\n\n"
                "The raw file content appears to contain a hook-skip flag literal. "
                "Correct the card JSON before running kanban do/todo."
            )
            print(json.dumps({
                "decision": "block",
                "reason": reason,
            }, separators=(",", ":")))
        # For rg -E lint: fail open (let kanban CLI handle the JSON error)
        sys.exit(0)

    cards = _iter_cards(data)
    if not cards:
        sys.exit(0)

    for card_idx, card in enumerate(cards):
        result = _scan_card_for_banned(card, card_idx)
        if result is None:
            continue

        crit_idx, mov_idx, cmd, pattern_name, fix = result

        # Sanitize cmd before embedding in denial message (prevents ANSI injection)
        safe_cmd = _sanitize_cmd(cmd)

        # Format the denial reason
        card_label = f"card[{card_idx}]" if len(cards) > 1 else "card"
        reason = (
            f"BANNED MoV PATTERN detected in {file_path_str}:\n\n"
            f"  Location:  {card_label} → criteria[{crit_idx}] → mov_commands[{mov_idx}].cmd\n"
            f"  Command:   {safe_cmd!r}\n"
            f"  Pattern:   {pattern_name}\n\n"
            f"  Fix: {fix}\n\n"
            f"Correct the MoV before running kanban do/todo."
        )

        print(json.dumps({
            "decision": "block",
            "reason": reason,
        }, separators=(",", ":")))
        sys.exit(0)

    # All clean — allow
    sys.exit(0)


if __name__ == "__main__":
    main()
