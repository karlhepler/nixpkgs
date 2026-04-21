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

Fails open: any error (JSON parse failure, shlex error, missing fields) results
in allowing. Never accidentally block innocent commands.

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
import shlex
import sys
from pathlib import Path

# Flags that consume the next token as their argument value.
# Bypass-flag strings appearing as values to these flags are NOT bypass flags.
# Note: -c is intentionally excluded here — it is handled via its own dedicated
# branch in both _check_git_tokens and _check_subcommand_flags so that the
# commit.gpgsign=false value can be inspected before being skipped.
_FLAGS_WITH_ARGS = frozenset([
    "-m", "--message",
    "-F", "--file",
    "-C", "--reuse-message",
    "--reedit-message",
    "--author",
    "--date",
])

# Git subcommands that this hook cares about.
_WATCHED_SUBCOMMANDS = frozenset(["push", "commit", "merge"])

# The -c key=value pattern that disables GPG signing.
_GPG_BYPASS_C_VALUE = "commit.gpgsign=false"

# Standalone bypass flags (not -c form).
_BYPASS_FLAGS = frozenset(["--no-verify", "--no-gpg-sign"])


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


def _check_git_tokens(tokens: list[str]) -> bool:
    """
    Walk shell tokens to determine if a watched git subcommand is being called
    with a bypass flag in actual flag position (not inside a -m message value, etc.).

    Returns True if a bypass flag is detected in argument position.

    Token-walking rules:
    1. Find the 'git' token (skip any leading env-var assignments like FOO=bar).
    2. Walk post-'git' tokens:
       a. Pre-subcommand: git may have its own flags like -c <key>=<value> or --no-pager.
          - If we see '-c', the next token is a key=value config entry:
              * If it equals 'commit.gpgsign=false' → bypass detected (if a watched
                subcommand follows).
              * Otherwise skip the value token.
          - Other pre-subcommand git flags that take a value: skip the value token.
       b. Once the subcommand is found (push/commit/merge/other):
          - If subcommand not in _WATCHED_SUBCOMMANDS → no bypass concern, return False.
          - Walk remaining tokens as subcommand flags:
              * If token is in _FLAGS_WITH_ARGS → skip the NEXT token (it's a value, not a flag).
              * If token is in _BYPASS_FLAGS → bypass detected, return True.
              * If token starts with '-c' in combined form (e.g. -ccommit.gpgsign=false) → check value.
    3. Fail safe: if anything looks off, return False (allow).
    """
    # Find 'git' in the token list (skip env assignments before it).
    git_idx = None
    for i, tok in enumerate(tokens):
        if tok == "git":
            git_idx = i
            break
        # Allow env-variable assignments (FOO=bar) and sudo/env wrappers before git.
        if tok in ("sudo", "env"):
            continue
        if "=" in tok and not tok.startswith("-"):
            continue
        # Any other token before 'git' means this isn't a simple git invocation.
        return False

    if git_idx is None:
        return False

    post_git = tokens[git_idx + 1:]

    # Pre-subcommand phase: git's own flags appear before the subcommand.
    # Track whether we've seen a pending -c bypass before a watched subcommand.
    pending_c_bypass = False
    i = 0

    while i < len(post_git):
        tok = post_git[i]

        # Subcommand reached?
        if not tok.startswith("-"):
            # This is the subcommand (or a non-flag argument).
            if tok not in _WATCHED_SUBCOMMANDS:
                return False
            # Found a watched subcommand.
            # If a pending -c bypass was seen before this subcommand → block.
            if pending_c_bypass:
                return True
            # Now walk subcommand flags.
            return _check_subcommand_flags(post_git[i + 1:])

        # Pre-subcommand git flag.
        if tok == "-c":
            # Next token is key=value.
            i += 1
            if i < len(post_git):
                val = post_git[i]
                if val == _GPG_BYPASS_C_VALUE:
                    pending_c_bypass = True
        elif tok.startswith("-c") and len(tok) > 2:
            # Combined form: -ccommit.gpgsign=false
            val = tok[2:]
            if val == _GPG_BYPASS_C_VALUE:
                pending_c_bypass = True
        elif tok in _FLAGS_WITH_ARGS:
            # Skip the next token (it's the flag's value).
            i += 1
        # Other pre-subcommand flags (--no-pager, --git-dir=, etc.) are skipped.

        i += 1

    # Fell off end of tokens without finding a subcommand.
    return False


def _check_subcommand_flags(flags: list[str]) -> bool:
    """
    Walk tokens after the git subcommand to find bypass flags in flag position.
    Tokens that are values to argument-taking flags are skipped.
    Returns True if a bypass flag is found.
    """
    i = 0
    while i < len(flags):
        tok = flags[i]

        if tok in _BYPASS_FLAGS:
            return True

        if tok in _FLAGS_WITH_ARGS:
            # Next token is a value (e.g. the message after -m). Skip it.
            i += 2
            continue

        # Check for -c commit.gpgsign=false in subcommand flag position.
        if tok == "-c":
            i += 1
            if i < len(flags) and flags[i] == _GPG_BYPASS_C_VALUE:
                return True
            continue

        if tok.startswith("-c") and len(tok) > 2:
            val = tok[2:]
            if val == _GPG_BYPASS_C_VALUE:
                return True

        i += 1

    return False


def has_bypass_flag(command: str) -> bool:
    """
    Return True if the command is a watched git operation containing a bypass
    flag in argument position (not in a message body or other value).

    Fails open: returns False on any parsing error.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Unterminated quotes or other shlex errors → fail open.
        return False

    if not tokens:
        return False

    # The command may contain multiple semicolon/&&/||-separated statements.
    # shlex.split doesn't split on these operators — they remain as tokens.
    # Walk through and find any git invocation segment.
    # Split on shell operators to handle chained commands.
    segments = _split_on_shell_operators(tokens)
    for segment in segments:
        if segment and _check_git_tokens(segment):
            return True
    return False


def _split_on_shell_operators(tokens: list[str]) -> list[list[str]]:
    """
    Split a token list on shell control operators (&&, ||, ;, |, etc.) to
    produce individual command segments. Each segment is a list of tokens
    for one command.
    """
    shell_ops = frozenset(["&&", "||", ";", "|", "&"])
    segments: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in shell_ops:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


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

    # Use token-aware bypass detection (not substring matching).
    if not has_bypass_flag(command):
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
