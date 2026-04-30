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
  backslash-pipe in regex tools: rg/grep/sed/awk cmd containing \\| (one backslash + pipe).
    In ripgrep's default Rust regex engine, \\| is a LITERAL pipe, not alternation.
    Fix: use bare-pipe alternation (foo|bar) or split into separate mov_commands entries.
    Double-escape (\\\\|) is NOT flagged — it can be legitimate in some tools.
  Hook-skip flags: --no-verify, --no-gpg-sign, git commit -n, HUSKY=0,
    HUSKY_SKIP_HOOKS=1 (should never appear in MoVs).
  rg/grep -c absence idiom: test $(rg -c PATTERN FILE) -le N or equivalent,
    including the legacy backtick form `rg -c PATTERN FILE`, and the bash [[
    double-bracket form [[ $(rg -c ...) -le 0 ]].
    When rg -c produces zero matches it emits NO stdout, making test $(empty) -le 0
    structurally broken (exit 2 'unary operator expected').
    Fix: use the negated quiet-match idiom: ! rg -q 'pattern' file
  empty mov_commands: criteria[*].mov_commands must not be an empty list or absent.
    Both mov_commands: [] and a missing mov_commands key represent the same intent
    (no programmatic check). The SubagentStop hook auto-fails both at check time.
    Every acceptance criterion must have at least one {cmd, timeout} entry.
  dash-leading patterns: rg/grep invocations where the search pattern starts with
    '--' (double-dash) but no end-of-flags marker ('--') or explicit pattern flag
    ('-e') precedes it. rg/grep parses the pattern as a flag and returns exit 2
    'unrecognized flag'. Detection covers '--'-leading patterns only; single-dash
    patterns (e.g., '-foo') are indistinguishable from short-flag bundles after
    shlex tokenization and cannot be reliably detected.
    Fix: use rg -qF -- '--watch' file  (end-of-flags marker)
      or rg -qF -e '--watch' file  (explicit pattern flag)

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
  - The absence-count detection fires on the raw cmd string: a cmd that
    contains the forbidden pattern in a comment or quoted argument
    (false-positive risk) will be blocked even if the actual command is
    correct. Rephrase comments to avoid the pattern. Pipeline forms like
    `rg -c ... | { read c; test "$c" -le 0; }` evade detection (pipeline
    bypass) — the runtime failure backstop still applies.
  - Empty `mov_commands` detection requires valid JSON parsing — cannot
    fire on the fail-closed raw-text path.
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
        # Detect backslash-pipe alternation trap in regex-context tools (rg, grep, sed, awk).
        # In ripgrep's default Rust regex engine (and grep/sed/awk BRE mode), a backslash
        # followed by a pipe (\|) is a LITERAL pipe character — NOT an alternation operator.
        # Alternation in ripgrep/PCRE2 is a bare pipe: foo|bar
        #
        # Matching logic:
        #   - Only fires when cmd also contains a regex-context tool (rg, grep, sed, awk).
        #     The scoped check is applied in _is_backslash_pipe_in_regex_tool() below;
        #     this regex is intentionally never reached via the standard BANNED_PATTERNS loop
        #     (the pattern is a never-match sentinel, same technique as git commit -n).
        #     Detection is performed entirely via _is_backslash_pipe_in_regex_tool().
        re.compile(r'(?!x)x'),  # Never matches — _is_backslash_pipe_in_regex_tool handles this
        "backslash-pipe (literal pipe, not alternation)",
        (
            r"In ripgrep's default Rust regex engine, `\|` is a LITERAL pipe character — "
            r"not alternation. "
            r"(GNU grep treats `\|` as alternation in BRE as an extension; "
            r"sed/awk BRE behavior is implementation-defined.) "
            r"For ripgrep — the primary tool in this codebase — "
            r"fix: use bare-pipe alternation (`foo|bar`) OR split into separate "
            r"mov_commands entries, one per search term."
        ),
        False,  # backslash-pipe lint: fail open on parse error
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
    (
        # Never matches — _is_rg_count_absence() handles this pattern out-of-band.
        # This sentinel entry exists for table completeness so that BANNED_PATTERNS
        # is the single inventory of all banned patterns.
        re.compile(r'(?!x)x'),
        "test $(rg -c PATTERN FILE) -le N (absence-via-count idiom)",
        (
            "Pattern: test $(rg -c PATTERN FILE) -le N (absence-via-count idiom)\n"
            "Fix: Use the negated quiet-match idiom: `! rg -q 'pattern' file`."
        ),
        False,  # absence-count lint: fail open on parse error
    ),
    (
        # Never matches — empty/missing mov_commands detection is handled inline
        # in _scan_card_for_banned() before the command loop.
        # This sentinel entry exists for table completeness.
        re.compile(r'(?!x)x'),
        "empty or missing mov_commands array",
        (
            "Fix: Every acceptance criterion must have at least one `{cmd, timeout}` "
            "entry in `mov_commands`."
        ),
        False,  # empty mov_commands lint: fail open on parse error
    ),
    (
        # Never matches — _is_dash_leading_pattern() handles this out-of-band via
        # shlex tokenization. This sentinel entry exists for table completeness.
        re.compile(r'(?!x)x'),
        "rg/grep dash-leading pattern without `--` or `-e` separator",
        (
            "BANNED MoV PATTERN detected — rg/grep dash-leading pattern "
            "(--FOO style) without `--` or `-e` separator\n"
            "\n"
            "  Pattern: rg/grep dash-leading pattern (--FOO style) without "
            "`--` or `-e` separator\n"
            "\n"
            "  Fix: When the search pattern starts with `--`, use one of:\n"
            "    rg -qF -- '--watch' file    (end-of-flags marker)\n"
            "    rg -qF -e '--watch' file    (explicit pattern flag)\n"
            "  Otherwise rg/grep parses the pattern as a flag.\n"
            "  (Note: single-dash leading patterns like '-foo' are also a "
            "hazard but cannot be reliably detected by this hook — exercise "
            "discipline at authoring time per staff-engineer.md.)"
        ),
        False,  # dash-leading lint: fail open on parse error
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
# Backslash-pipe detection (regex-context tools only)
# ---------------------------------------------------------------------------

# Matches a single backslash followed by a pipe that is NOT preceded by
# another backslash. This catches \| (literal-pipe trap) but not \\|
# (two backslashes followed by pipe — can be a legitimate double-escape
# when matching a literal backslash character in some tools).
_BACKSLASH_PIPE_RE = re.compile(r'(?<!\\)\\[|]')

# Regex-context tools for which \| is meaningfully wrong.
# An escaped pipe inside a literal-string echo or plain variable assignment
# is not a regex and is not flagged.
_REGEX_TOOL_RE = re.compile(r'\b(?:rg|grep|sed|awk)\b')


# Matches grep invocations in PCRE mode, where \| IS valid alternation.
# In grep -P / --perl-regexp, backslash-pipe is a legitimate alternation operator.
_GREP_PCRE_RE = re.compile(r'(?<!\w)-P\b|--perl-regexp\b')


def _is_backslash_pipe_in_regex_tool(cmd: str) -> bool:
    """
    Return True if cmd invokes a regex-context tool (rg, grep, sed, awk)
    AND contains a single backslash immediately followed by a pipe character.

    A single \\| (one backslash + pipe) in a ripgrep pattern matches a
    LITERAL pipe, not alternation. This is a recurring card-authoring error.

    Does NOT fire on \\\\| (two backslashes + pipe) — that is a legitimate
    escape sequence when the intent is to match a literal backslash.

    Does NOT fire on grep -P / --perl-regexp invocations: in PCRE mode, \\|
    is a valid alternation operator.
    """
    if not _REGEX_TOOL_RE.search(cmd):
        return False
    # Exempt grep invocations using PCRE mode (-P / --perl-regexp):
    # in PCRE, \| is legitimate alternation, not a literal pipe trap.
    if re.search(r'\bgrep\b', cmd) and _GREP_PCRE_RE.search(cmd):
        return False
    return bool(_BACKSLASH_PIPE_RE.search(cmd))


# ---------------------------------------------------------------------------
# rg/grep -c absence idiom detection
# ---------------------------------------------------------------------------
#
# Matches the structural prefix of the fragile absence-via-count pattern:
#   test $(rg -c 'pat' file) -le 0
#   test "$(rg -c 'pat' file)" -le 0
#   test $(grep -c 'pat' file) -eq 0
#   [ $(rg -c ...) -lt 0 ]
#
# When rg -c produces zero matches it emits NO stdout, so the command
# substitution expands to an empty string. This makes `test  -le 0` break
# with exit 2 ("unary operator expected") instead of succeeding as intended.
#
# The correct idiom for absence is: ! rg -q 'pattern' file
#   (exits 0 when absent, 1 when present — no empty-expansion hazard).
#
# Detection: match the structural prefix — test/[/[[ followed by optional
# whitespace, optional quote, $( or backtick and then rg/grep -c — AND the
# command contains a comparison to zero (-le 0, -eq 0, -lt 1, -le 1, -lt 2).
# Requiring the comparison-to-zero signal ensures we don't fire on
# presence-count assertions like `test $(rg -c 'TODO') -ge 5`.
#
# The backtick form (` rg -c ...`) is included because it is equally fragile:
# an empty-output expansion inside backticks causes the same 'unary operator
# expected' exit-2 failure.
#
# The [[ double-bracket form is included because bash's [[ also suffers the
# same empty-expansion hazard with arithmetic comparisons.
_RG_COUNT_ABSENCE_RE = re.compile(
    r'(?:test|\[\[?)\s+"?(?:\$\(|`)\s*(?:rg|grep)\s+-c\b'
)

# Matches the zero-comparison half:
#   -le 0, -eq 0            — absent / exactly zero
#   -lt 1, -le 1, -lt 2     — "less than 1/2" or "at most 1"; all indicate
#                              an absence or near-absence threshold
#
# Note: -lt N and -le (N-1) are equivalent for non-negative integers.
# -lt 0 is included because rg -c cannot return negative counts, making
# it a nonsensical-but-structurally-equivalent form of the absence check.
_ZERO_COMPARE_RE = re.compile(r'-(?:le|eq)\s+[01]\b|-lt\s+[012]\b')

_RG_COUNT_ABSENCE_FIX = (
    "Pattern: test $(rg -c PATTERN FILE) -le N (absence-via-count idiom)\n"
    "Fix: This idiom is fragile — `rg -c` emits NO stdout when zero matches, "
    "breaking the `test` command structurally with exit 2. "
    "For pattern-absence assertions, use the negated quiet-match idiom: "
    "`! rg -q 'pattern' file` (exits 0 if absent, 1 if present)."
)

_RG_COUNT_ABSENCE_NAME = "test $(rg -c PATTERN FILE) -le N (absence-via-count idiom)"


def _is_rg_count_absence(cmd: str) -> bool:
    """
    Return True if cmd uses the fragile absence-via-count idiom:
      test $(rg -c ...) -le 0   (or -eq 0, -lt 1, -le 1, -lt 2, etc.)
      test "$(rg -c ...)" -le 0
      [ $(rg -c ...) -le 0 ]
      [[ $(rg -c ...) -le 0 ]]
      test `rg -c ...` -le 0   (legacy backtick form)

    Also matches the grep -c variant.

    Does NOT fire on presence-count assertions like `test $(rg -c X) -ge 5`.
    Requires both the structural prefix AND a comparison-to-zero signal.

    Note: fires on the raw cmd string. If the pattern appears inside a shell
    comment or quoted argument within cmd, it may trigger a false positive.
    See LIMITATIONS section in module docstring.
    """
    return bool(_RG_COUNT_ABSENCE_RE.search(cmd) and _ZERO_COMPARE_RE.search(cmd))


# ---------------------------------------------------------------------------
# Dash-leading pattern detection
# ---------------------------------------------------------------------------
#
# When a rg/grep invocation has a search pattern that starts with '-',
# the tool parses it as an unknown flag and exits 2 ('unrecognized flag').
#
# Safe invocations that must NOT be flagged:
#   rg -qF -- '--watch' file    (end-of-flags marker before pattern)
#   rg -qF -e '--watch' file    (explicit -e / --regexp before pattern)
#
# Unsafe invocations that must be flagged:
#   rg -qF '--watch' file       (pattern parsed as flag → exit 2)
#   grep '--debug' file         (same hazard)
#   rg -qi '--lint' file        (same hazard)

# Flags that consume the very next token as their value — skip that token.
# This prevents mistaking a flag value for the search pattern.
# Note: -e/--regexp are intentionally excluded here; they trigger an early
# return at the `-e`/`--regexp` guard in _is_dash_leading_pattern() before
# the with-value check is ever reached.
_RG_FLAGS_WITH_VALUE: frozenset[str] = frozenset([
    "-f", "--file",
    "--encoding", "-E",
    "--type-add",
    "--iglob", "--glob", "-g",
    "--replace", "-r",
    "--max-count", "-m",
    "--max-depth",
    "--context", "-C",
    "--before-context", "-B",
    "--after-context", "-A",
    "--color",
    "--colors",
    "--field-match-separator",
    "--field-context-separator",
    "--path-separator",
    "--sort", "--sortr",
    "--type", "-t",
    "--type-not", "-T",
])

# Known rg boolean long flags (take no value). Used to distinguish legitimate
# rg flags from a dash-leading pattern that looks like an unknown flag.
_RG_BOOL_LONG_FLAGS: frozenset[str] = frozenset([
    "--no-ignore", "--no-ignore-vcs", "--no-ignore-global", "--no-ignore-parent",
    "--no-ignore-dot", "--ignore", "--hidden", "--no-hidden",
    "--follow", "--no-follow",
    "--fixed-strings", "--no-fixed-strings",
    "--word-regexp", "--no-word-regexp",
    "--line-regexp", "--no-line-regexp",
    "--multiline", "--no-multiline",
    "--multiline-dotall",
    "--crlf", "--no-crlf",
    "--null", "--null-data",
    "--only-matching",
    "--passthru",
    "--invert-match",
    "--count", "--count-matches",
    "--files", "--files-with-matches", "--files-without-match",
    "--list-file-types",
    "--quiet",
    "--case-sensitive", "--ignore-case", "--smart-case",
    "--pcre2", "--no-pcre2",
    "--vimgrep",
    "--json",
    "--line-number", "--no-line-number",
    "--column", "--no-column",
    "--with-filename", "--no-filename",
    "--heading", "--no-heading",
    "--trim",
    "--glob-case-insensitive", "--no-glob-case-insensitive",
    "--binary", "--no-binary",
    "--text",
    "--search-zip", "--no-search-zip",
    "--mmap", "--no-mmap",
    "--unicode", "--no-unicode",
    "--one-file-system",
    "--no-messages",
    "--stats",
    "--debug", "--trace",
    "--version",
    "--help",
])

_GREP_FLAGS_WITH_VALUE: frozenset[str] = frozenset([
    "-e", "--regexp",
    "-f", "--file",
    "-m", "--max-count",
    "-A", "--after-context",
    "-B", "--before-context",
    "-C", "--context",
    "--label",
    "--include",
    "--exclude",
    "--color", "--colour",
])

# Known grep boolean long flags (take no value).
_GREP_BOOL_LONG_FLAGS: frozenset[str] = frozenset([
    "--extended-regexp", "--fixed-strings", "--basic-regexp", "--perl-regexp",
    "--ignore-case", "--no-ignore-case",
    "--word-regexp", "--line-regexp",
    "--count", "--line-number", "--only-matching",
    "--quiet", "--silent",
    "--recursive", "--dereference-recursive",
    "--invert-match",
    "--files-with-matches", "--files-without-match", "--with-filename", "--no-filename",
    "--null",
    "--binary", "--text",
    "--no-messages",
    "--version", "--help",
])


def _is_dash_leading_pattern(cmd: str) -> bool:
    """
    Return True if cmd invokes rg or grep with a search pattern that starts
    with '--' (double-dash), without a preceding '--' (end-of-flags) or
    '-e'/'--regexp' (explicit pattern flag).

    CONTRACT: This function detects double-dash leading patterns only (e.g.,
    '--watch', '--lint'). Single-dash leading patterns (e.g., '-foo') are
    indistinguishable from short-flag bundles after shlex tokenization and
    cannot be reliably detected — they are silently skipped as flags. Single-
    dash patterns are still a hazard; exercise discipline at authoring time
    per staff-engineer.md guidance.

    Uses shlex tokenization to distinguish flag tokens from positional arguments.
    Fails open (returns False) if shlex parsing fails.

    Algorithm:
      For each token after the rg/grep binary:
        - If token is '--', all subsequent tokens are positional (end-of-flags).
          → safe (caller explicitly ended flags). Return False.
        - If token is '-e' or '--regexp', the next token is the explicit pattern.
          → safe. Return False.
        - If token starts with '--', classify it:
            * Known long flag with value: skip it and the next token (the value).
            * Known boolean long flag: skip it (no value consumed).
            * Unknown long flag ('--foo' not in either known set): this is the
              double-dash leading hazard — rg/grep will parse it as an
              unrecognized flag and exit 2 → return True.
        - If token starts with '-' (single-dash), treat as a short flag bundle
          (e.g., -qiF, -qi, -q) and skip it. NOTE: single-dash leading patterns
          like '-foo' as a search argument are not detected here — they are
          consumed as short-flag bundles and silently pass through.
        - Otherwise, the token is the first positional argument (search pattern).
          The pattern is safe → return False.

    Note: shlex strips quotes, so '--watch' in the cmd string becomes --watch
    after splitting. An unknown '--watch' token cannot be a valid rg flag and
    would cause rg to exit 2 ('unrecognized flag') → correctly detected.
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        # Unterminated quotes or other shlex errors — fail open
        return False

    if not tokens:
        return False

    # Find rg or grep token; only check the first such invocation in the command.
    tool_idx = None
    for i, tok in enumerate(tokens):
        # Strip path prefix in case of /usr/bin/grep etc.
        base = tok.split("/")[-1]
        if base in ("rg", "grep"):
            tool_idx = i
            break

    if tool_idx is None:
        return False

    # Determine which flag sets to use based on the tool.
    base_tool = tokens[tool_idx].split("/")[-1]
    if base_tool == "rg":
        flags_with_value = _RG_FLAGS_WITH_VALUE
        bool_long_flags = _RG_BOOL_LONG_FLAGS
    else:
        flags_with_value = _GREP_FLAGS_WITH_VALUE
        bool_long_flags = _GREP_BOOL_LONG_FLAGS

    post_tool = tokens[tool_idx + 1:]
    i = 0
    while i < len(post_tool):
        tok = post_tool[i]

        if tok == "--":
            # End-of-flags marker — all following tokens are positional.
            # The caller explicitly ended flags, so any dash-leading pattern
            # after '--' is intentional and safe. Nothing to flag.
            return False

        if tok in ("-e", "--regexp"):
            # Explicit pattern flag — next token is the explicit pattern; safe.
            return False

        if tok.startswith("--"):
            # Long flag form.
            if tok in flags_with_value:
                # Known long flag that consumes the next token as its value.
                i += 2
                continue
            if tok in bool_long_flags:
                # Known boolean long flag — takes no value.
                i += 1
                continue
            # Unknown long flag: this is the dash-leading hazard.
            # rg/grep will parse it as an unrecognized flag and exit 2.
            return True

        if tok.startswith("-"):
            # Short flag or combined short flags (e.g. -qiF, -qi, -q).
            # Short combined bundles take no separate value token in combined
            # form. Skip the whole bundle.
            i += 1
            continue

        # Reached the first positional argument (the search pattern). All
        # dash-prefixed tokens (short or long flags) are handled above.
        # Pattern does not start with '-' → safe.
        return False

    # No positional argument found — no pattern to flag.
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

        # Check for missing or empty mov_commands — reject at creation time.
        # Both a missing key and an empty list represent the same intent:
        # no programmatic check. The SubagentStop hook auto-fails both at
        # check time, so creating such a card is always wasted effort.
        if len(mov_commands) == 0:
            empty_fix = (
                f"Pattern: empty or missing mov_commands on criterion {crit_idx}\n"
                "Fix: Every acceptance criterion must have at least one programmatic "
                "`{cmd, timeout}` entry in `mov_commands`. Semantic AC is not supported — "
                "the SubagentStop hook auto-fails any criterion with empty or missing "
                "mov_commands at check time, so creating the card is wasted effort. If you "
                "genuinely cannot write a programmatic check, see § Pre-Card MoV Check "
                "(Path A/B/C) in staff-engineer.md."
            )
            empty_name = f"empty or missing mov_commands on criterion {crit_idx}"
            # Use -1 as sentinel mov_idx to indicate no commands exist (not a real index).
            # The denial message formatter skips the index display when cmd == "(empty)".
            return (crit_idx, -1, "(empty)", empty_name, empty_fix)

        for mov_idx, mov in enumerate(mov_commands):
            if not isinstance(mov, dict):
                continue
            cmd = mov.get("cmd", "")
            if not cmd or not isinstance(cmd, str):
                continue

            # Check rg/grep -c absence idiom (fragile empty-expansion pattern)
            if _is_rg_count_absence(cmd):
                return (crit_idx, mov_idx, cmd, _RG_COUNT_ABSENCE_NAME, _RG_COUNT_ABSENCE_FIX)

            # Check git commit -n via shlex (takes precedence over regex for this pattern)
            if _is_git_commit_n(cmd):
                # Find the git commit -n entry to get its fix suggestion
                for pattern, name, fix, _ in BANNED_PATTERNS:
                    if name == "git commit -n (hook-skip short flag)":
                        return (crit_idx, mov_idx, cmd, name, fix)

            # Check backslash-pipe alternation trap in regex-context tools
            if _is_backslash_pipe_in_regex_tool(cmd):
                for pattern, name, fix, _ in BANNED_PATTERNS:
                    if name == "backslash-pipe (literal pipe, not alternation)":
                        return (crit_idx, mov_idx, cmd, name, fix)

            # Check dash-leading pattern without -- or -e separator
            if _is_dash_leading_pattern(cmd):
                for pattern, name, fix, _ in BANNED_PATTERNS:
                    if name == "rg/grep dash-leading pattern without `--` or `-e` separator":
                        return (crit_idx, mov_idx, cmd, name, fix)

            # Check remaining patterns via regex
            for pattern, name, fix, _ in BANNED_PATTERNS:
                if name == "git commit -n (hook-skip short flag)":
                    # Already handled by shlex above — skip regex path
                    continue
                if name == "backslash-pipe (literal pipe, not alternation)":
                    # Already handled by _is_backslash_pipe_in_regex_tool above — skip regex path
                    continue
                if name == "rg/grep dash-leading pattern without `--` or `-e` separator":
                    # Already handled by _is_dash_leading_pattern above — skip regex path
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
        # When mov_idx == -1 (sentinel for empty/missing mov_commands), omit the
        # index display since there is no specific command to point to.
        if cmd == "(empty)":
            location = f"{card_label} → criteria[{crit_idx}] → mov_commands: []"
        else:
            location = f"{card_label} → criteria[{crit_idx}] → mov_commands[{mov_idx}].cmd"
        reason = (
            f"BANNED MoV PATTERN detected in {file_path_str}:\n\n"
            f"  Location:  {location}\n"
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
