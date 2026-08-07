#!/usr/bin/env python3
"""
kanban-mov-lint-hook: PreToolUse(Bash) hook.

ARCHITECTURE NOTE: Card-JSON banned-pattern validation (backslash-pipe,
AND-chain, rg -E, absence-via-count idiom, hook-skip flags, dash-leading
patterns, empty mov_commands) lives in the kanban CLI itself
(modules/kanban/kanban.py — see validate_mov_commands_content), which
validates mov_commands[].cmd on BOTH the --file and inline-JSON code paths
for `kanban do` and `kanban todo`. This hook is not the primary defense for
that class of defect.

This hook DOES add one check of its own, scoped to the SAME layer as the
CLI-level checks above: a card being CREATED via `kanban do` / `kanban todo`,
inspected on its `mov_commands[].cmd` entries — never against the raw Bash
command line, and never against Bash calls that aren't a `kanban do`/`kanban
todo` invocation. Concretely, it looks for a mov_commands[].cmd whose
pipeline's FINAL stage is a formatting/slicing filter (head, tail, cut, sort,
tr). A pipe's overall exit status is that of its LAST stage —
head/tail/cut/sort/tr all exit 0 even on empty stdin, so a MoV command of the
form `rg -i 'pattern' file | head -1` can never fail: the upstream command's
exit code is discarded regardless of whether the pattern matched. Such a
criterion survives undetected precisely because it always passes.

This check is intentionally narrow to the FINAL top-level pipe stage of the
cmd string. A filter used as a NON-final stage feeding a surrounding
assertion is legitimate and explicitly allowed, e.g.:
  - test "$(rg -o 'pattern' file | wc -l)" -ge N
  - test $(rg -n PAT file | head -1 | cut -d: -f1) -lt $(...)
In both examples the filter's output is the `test` command's INPUT (via a
$(...) command substitution), and `test` is the assertion whose own exit
status the shell reports — so the check never even looks inside a
substitution for a "final stage."

A bare `(...)` subshell is NOT given this same treatment: a subshell's own
exit status (the exit status of the last command run inside it) propagates
to whatever chain contains it — unlike $(...), whose exit status is
discarded. `(rg -q x file | head -1)` is therefore exactly as unfailable as
the unwrapped form and is denied identically; see
_find_top_level_operators's docstring for the mechanism.

IMPORTANT — layer boundary: this hook is registered on matcher="Bash" (every
Bash tool call, from any agent), but it must only ever evaluate cmd strings
that are ABOUT to become mov_commands on a card being created — not the Bash
command that carries them. An everyday command like `git log --oneline |
head -20`, or the `rg ... | head -N` transcript-interrogation diagnostic
staff-engineer.md instructs agents to run, is not a MoV and must be left
alone by this hook regardless of its own final pipe stage. Only a
`kanban do`/`kanban todo` invocation's card JSON (from either the inline
positional argument or the file at --file) is inspected, and only that card
JSON's mov_commands[].cmd strings are passed to find_unfailable_pipe_reason.

This hook ALSO checks, on the same mov_commands[].cmd strings, for a quoted
pattern fused onto its very next path-like token with no separating
whitespace (e.g. `rg -q 'pattern'modules/foo.nix`) — see the "Abutted
quote/path detection" section below and find_abutted_quote_path_reason.
Bash tokenizes that as ONE shell word, so the tool receives no path
argument at all and the check fails identically regardless of file
content, unconditionally.

Output format (PreToolUse hook — documented hookSpecificOutput format):
  {"suppressOutput": False, "hookSpecificOutput": {
      "hookEventName": "PreToolUse", "permissionDecision": "deny",
      "permissionDecisionReason": "..."}}  — deny
  (exit 0 with no output)                  — allow (fail open)

This hook intentionally omits any top-level turn-halting field. Per the
deployed global policy at ~/.claude/CLAUDE.md section "Tool-Block Recovery",
this hook's one real denial site is mechanical — the rejection text names a
corrected form of the same MoV command — so only
hookSpecificOutput.permissionDecision = deny is emitted, denying just the
offending `kanban do`/`kanban todo` call and leaving the coordinator free to
retry the corrected form in the same turn.

Fails open: any error (JSON parse failure, empty stdin, non-UTF-8 stdin
bytes, missing fields, a non-dict tool_input, shlex error, unreadable
--file path, non-kanban-do/todo Bash command, or any other unexpected
exception raised while deciding) results in allowing. This is a structural
guarantee — main() wraps its entire decision logic in one outer
try/except Exception that falls open — not an incidental side effect of
Claude Code's exit-code-1-is-non-blocking contract. Never block innocent
commands, by design.
"""

import json
import shlex
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Banned final-pipe-stage filters
# ---------------------------------------------------------------------------

# Commands that always exit 0 as a BARE final pipe stage, regardless of
# whether upstream produced 0 or N lines of output — so a MoV criterion
# shaped `upstream | one-of-these` can never fail on the thing it's actually
# trying to assert. Rationale, checked individually per candidate (not
# assumed from "looks like a coreutils text filter") — see card #3287 ASK 3:
#
# Included — confirmed unfailable in ordinary/legitimate final-stage usage:
#   head, tail, cut, sort, tr — original set; pure slicing/formatting, no
#     match/no-match concept, exit 0 on empty stdin.
#   wc     — `wc -l` on 0 lines exits 0 exactly like `head -1` on empty
#            stdin, so a bare `... | wc -l` is unfailable. Still fine INSIDE
#            a command substitution (`test "$(... | wc -l)" -ge N`) because
#            that shape is never reached by this check at all: $(...)
#            content is opaque to the top-level chain scanner
#            (_find_top_level_operators), so `wc` never becomes "the final
#            stage of a top-level chain" in that shape — the substitution
#            and bare-final-stage cases are structurally distinct, not just
#            differently policied.
#   awk    — default usage (print/transform fields) exits 0 whether or not
#            any line matched a pattern; no exit-code signal for "matched
#            nothing" without an explicit `exit` statement in the program.
#   sed    — same reasoning: `sed -n '/pat/p'` exits 0 on zero matching
#            lines.
#   uniq   — dedup has no match/no-match concept; exits 0 on any input,
#            including empty stdin.
#   tee    — passes stdin through to stdout/file; exits 0 regardless of
#            content — this is the classic "exit status swallowed by tee"
#            pitfall `set -o pipefail` exists to guard against.
#   rev    — reverses each line; exits 0 on any input, including empty.
#   fold   — wraps lines to a width; exits 0 on any input, including empty.
#   column — formats input into columns; exits 0 on any input, including
#            empty.
#
# Excluded — genuinely CAN propagate a meaningful failure as a final stage,
# so banning them would reject correct MoVs (the more dangerous direction):
#   cat    — `cat missing-file` exits non-zero (file not found), so
#            `... | cat expected-output.txt` can fail meaningfully.
#   xargs  — propagates the exit status of the command it invokes (e.g.
#            `rg -l pat . | xargs pytest` reports pytest's own failure) —
#            banning it would reject a legitimate, useful MoV shape.
BANNED_FINAL_PIPE_FILTERS = frozenset(
    [
        "head", "tail", "cut", "sort", "tr",
        "wc", "awk", "sed", "uniq", "tee", "rev", "fold", "column",
    ]
)


# ---------------------------------------------------------------------------
# Top-level pipe-chain tokenizer
# ---------------------------------------------------------------------------

def _skip_balanced_group(cmd: str, open_idx: int, open_char: str, close_char: str) -> int:
    """Given cmd[open_idx] == open_char, return the index just past the
    matching close_char, treating quoted content inside the group as opaque
    (so a quoted paren/paren-like character inside doesn't unbalance it).

    Deliberate fail-open on already-malformed input: if close_char is never
    found (an unclosed $(...) or an unterminated quote inside it), this
    scans to end-of-string and the caller treats everything from open_idx on
    as swallowed/opaque. Such a cmd string is itself a shell syntax error
    (an unclosed subshell/substitution never executes as literally written)
    so this can never silently mis-scope a command that would actually run
    — it's a deliberate consequence of fail-open-on-error, not a bug.
    """
    n = len(cmd)
    depth = 1
    j = open_idx + 1
    while j < n and depth > 0:
        c = cmd[j]
        if c == "'":
            j += 1
            while j < n and cmd[j] != "'":
                j += 1
        elif c == '"':
            j += 1
            while j < n and cmd[j] != '"':
                if cmd[j] == "\\":
                    j += 1
                j += 1
        elif c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
        j += 1
    return j


def _find_top_level_operators(cmd: str) -> "list[tuple[int, int, str]]":
    """Return [(start, end, op), ...] for every top-level shell operator
    ('&&', '||', ';', '&', '|') in cmd, in order.

    "Top-level" means outside single/double quotes and outside any $(...) or
    `...` command substitution — pipes inside a command substitution never
    count, since a substitution's own exit status is discarded; only its
    stdout TEXT feeds something else (usually a surrounding assertion), not
    the shell's reported exit status.

    Bare `(...)` subshells are the OPPOSITE case and are deliberately NOT
    treated as opaque here (unlike $(...)): a subshell's own exit status —
    which is the exit status of the last command executed inside it — DOES
    propagate to whatever chain contains it. `(rg -q x file | head -1)` is
    therefore exactly as unfailable as the unwrapped `rg -q x file | head
    -1`, and ordinary command grouping (parens used for scoping/readability,
    with zero evasive intent) must not be able to hide an unfailable final
    pipe stage from this check. We achieve this by simply not skipping over
    `(` / `)` at all — treating them as ordinary characters — which flattens
    the subshell's contents into the same top-level scan, exposing any pipe
    inside it exactly as if the parens weren't there.
    """
    n = len(cmd)
    i = 0
    ops: "list[tuple[int, int, str]]" = []
    while i < n:
        c = cmd[i]
        if c == "'":
            i += 1
            while i < n and cmd[i] != "'":
                i += 1
            i += 1
            continue
        if c == '"':
            i += 1
            while i < n and cmd[i] != '"':
                if cmd[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "$" and i + 1 < n and cmd[i + 1] == "(":
            i = _skip_balanced_group(cmd, i + 1, "(", ")")
            continue
        if c == "`":
            i += 1
            while i < n and cmd[i] != "`":
                i += 1
            i += 1
            continue
        # NOTE: bare '(' / ')' are intentionally NOT special-cased here — see
        # the docstring above. They fall through to the plain `i += 1` at
        # the bottom of this loop, exactly like any other ordinary
        # character, so a pipe inside a bare subshell is scanned as if the
        # parens were never there.
        if c == "&":
            if i + 1 < n and cmd[i + 1] == "&":
                ops.append((i, i + 2, "&&"))
                i += 2
            else:
                ops.append((i, i + 1, "&"))
                i += 1
            continue
        if c == "|":
            if i + 1 < n and cmd[i + 1] == "|":
                ops.append((i, i + 2, "||"))
                i += 2
            else:
                ops.append((i, i + 1, "|"))
                i += 1
            continue
        if c == ";":
            ops.append((i, i + 1, ";"))
            i += 1
            continue
        i += 1
    return ops


def _split_into_pipe_chains(cmd: str) -> "list[list[str]]":
    """Split cmd into pipe chains: each chain is a list of segment strings
    joined by top-level '|' operators. A chain breaks at any other top-level
    operator ('&&', '||', ';', '&').
    """
    ops = _find_top_level_operators(cmd)
    chains: "list[list[str]]" = []
    current: "list[str]" = []
    last_end = 0
    for start, end, op in ops:
        current.append(cmd[last_end:start])
        if op != "|":
            chains.append(current)
            current = []
        last_end = end
    current.append(cmd[last_end:])
    chains.append(current)
    return chains


def _first_word(segment: str) -> str:
    """Return the first whitespace-delimited token of segment, with any
    leading path stripped (e.g. '/usr/bin/head' -> 'head')."""
    stripped = segment.strip()
    if not stripped:
        return ""
    first = stripped.split(None, 1)[0]
    if "/" in first:
        first = first.rsplit("/", 1)[-1]
    return first


def find_unfailable_pipe_reason(cmd: str) -> "str | None":
    """Return a deny reason if cmd contains a top-level pipe chain whose
    FINAL stage is one of BANNED_FINAL_PIPE_FILTERS. Returns None if cmd is
    fine (no such chain, or the filter is used as a non-final stage feeding
    a surrounding assertion via command substitution).
    """
    for chain in _split_into_pipe_chains(cmd):
        if len(chain) < 2:
            continue  # no top-level pipe in this chain at all
        last_word = _first_word(chain[-1])
        if last_word in BANNED_FINAL_PIPE_FILTERS:
            return (
                f"This command's pipeline ends in `{last_word}`, which exits 0 "
                "even on empty/no-match stdin — the upstream command's exit "
                "code is discarded, so this check can never fail regardless "
                "of whether the upstream command actually matched anything. "
                f"Fix: use the upstream tool's own quiet/check flag (e.g. "
                f"`rg -q`) instead of piping into `{last_word}`, or move "
                f"`{last_word}` inside a command substitution that feeds a "
                'surrounding assertion (e.g. `test "$(... | wc -l)" -ge N` or '
                f'`test $(... | {last_word} ...) -lt ...`).'
            )
    return None


# ---------------------------------------------------------------------------
# Abutted quote/path detection
# ---------------------------------------------------------------------------
#
# Defect this catches (issue #6, following #5's five-broken-MoV incident): a
# quoted pattern fused onto its very next path argument with no separating
# whitespace, e.g.
#
#     rg -q 'anything'modules/claude/default.nix
#
# Bash tokenizes the closing quote and the immediately-following text as ONE
# shell word, so the pattern-matching tool receives a single garbled
# argument and no path — it reads stdin instead of the file, and the check
# fails identically regardless of file content, every single time,
# regardless of whether the work is correct. A real incident produced five
# such commands across three sibling cards from a single `replace_all` edit
# that dropped one trailing space.
#
# Detection works by computing the FULL EXTENT of the single Bash word that
# begins immediately after a closing quote (_scan_abutted_word), then
# checking whether that word's raw text contains a literal '/' anywhere.
# Getting the word's extent right matters: a backslash-escape, a further
# quoted segment, a $(...) / `...` command substitution, or a ${...}
# parameter expansion all extend the current word rather than ending it —
# none of them is a shell operator the way `&&`/`|`/`;` are. An earlier
# version of this code (card #3518 review) treated all of those characters
# as if they were operators that ended the word, which let the exact defect
# this rule exists to catch slip through undetected whenever one of them
# immediately followed the closing quote (e.g.
# `'pattern'$(echo x)/foo.nix` fuses into ONE shell word in real Bash, but
# was allowed). Only real Bash word separators — whitespace, and the
# |&;()<> operator characters — actually end a word; everything else
# extends the current word, and _scan_abutted_word walks past all of it
# (including nested quoted segments and balanced $(...)/`...`/${...}
# groups) to find the word's true end before checking for a '/'.
#
# False positives this deliberately does NOT flag (verified against real
# Bash tokenization, not assumed — see card #3512, and re-verified for card
# #3518):
#
#   1. The embedded-single-quote idiom: closing a single-quoted string,
#      immediately opening a double-quoted one containing a literal
#      apostrophe, then closing that and reopening the single-quoted string
#      — e.g. 'don'"'"'t'. This is NOT special-cased as "any quote
#      immediately following a quote is exempt" — that blanket exemption
#      was too broad: it also waved through two independently-quoted
#      adjacent strings whose fused result is itself path-like (e.g.
#      'pattern'"/file", which collapses to the single word `pattern/file`
#      in real Bash and IS the defect). Instead the idiom is allowed
#      because it falls out naturally from the word-extent scan: the
#      concatenated content of 'don'"'"'t' is "don't", which contains no
#      '/', so it is correctly not path-like regardless of how many quoted
#      segments it is built from — while 'pattern'"/file" is still denied,
#      because ITS concatenated content does contain '/'.
#   2. Deliberate short token concatenation with no path semantics, e.g.
#      'foo'bar file (searches for the literal string "foobar"), or
#      'foo'.bar file (searches for the literal string "foo.bar"). Rare,
#      but valid shell and not an error. A bare '.' immediately after the
#      closing quote is NOT unconditionally treated as path-like — like
#      every other starting character, it only qualifies if the word it
#      starts actually contains a '/' (verified: real Bash tokenizes
#      `rg -q 'foo'.bar file` into 4 correct, separate arguments — not the
#      fused defect at all — so denying it was itself a false positive,
#      fixed here). The rule only fires when the abutting word actually
#      contains a '/' — a bare word with no slash never qualifies.
#   3. Brace expansion, e.g. 'pattern'{a,b}/file. Bash expands a bare
#      {x,y,...} group (distinct from a $-prefixed ${...} parameter
#      expansion) into MULTIPLE separate shell words at this position —
#      verified live: 'pattern'{a,b}/file becomes the two words
#      `patterna/file` and `patternb/file`, not one fused word with no path
#      argument at all. This is a real, sanctioned Bash mechanism distinct
#      from string concatenation, and _scan_abutted_word detects it (a bare
#      '{' whose balanced '}' group contains a top-level ',') and exempts
#      the whole word rather than flagging it.
#
# A candidate FOURTH false-positive shape was considered and deliberately
# NOT exempted: `"$VAR"/path/suffix` (expand a quoted variable, then
# concatenate a literal path suffix with no intended space — a real,
# recognized shell idiom for building paths from an env var). It was not
# given a carve-out because it is exactly as ambiguous, in shape, as the
# actual defect this rule exists to catch: `"$PATTERN"/some/broken/path`
# with a missing space is indistinguishable from the legitimate idiom by
# this simple a lint, and this hook is not a full shell interpreter that
# could tell "used as an expanded path" apart from "meant to be a separate
# argument". No instance of the legitimate idiom was found anywhere in this
# repository's actual MoV commands (checked via rg across modules/claude
# and modules/kanban) — so a carve-out here would trade a real, catchable
# defect for a false-positive class that has never actually occurred.
# Erring toward catching the bug is the safer default for a gate whose job
# is precisely to catch commands that "fail identically regardless of file
# content".
#
# KNOWN RESIDUAL GAP (card #3518 review; not fixed here — there is no
# reliable fix for a lint this simple): a fused bare word with NEITHER a
# leading '/' or '.' NOR any '/' anywhere in it — e.g. `rg -q 'pattern'file`
# against a real bare filename `file` that happens to exist in cwd — is
# indistinguishable, by this check, from the deliberate literal-string
# concatenation named in false-positive #2 above. Both produce the
# identical shape: "closing quote immediately followed by a run of
# non-separator characters with no slash anywhere in it." This residual gap
# cannot be closed without either a filesystem existence check against the
# actual working directory at lint time (fragile, environment-dependent,
# and wrong for a MoV that will run somewhere else entirely) or banning
# bare-word concatenation outright (which would reject the legitimate,
# documented idiom in #2). It is accepted as a known limitation, not
# silently assumed away.
# ---------------------------------------------------------------------------

_ABUT_TRUE_SEPARATORS = frozenset(" \t\n\r|&;()<>")


def _scan_abutted_word(cmd: str, start: int) -> "tuple[int, bool]":
    """Return (end, saw_brace_expansion) describing the single Bash word
    that begins at cmd[start] (start itself must not be a separator —
    callers check that via _ABUT_TRUE_SEPARATORS before calling).

    Backslash-escapes, further quoted segments, $(...) / `...` command
    substitutions, and ${...} parameter expansions all extend the current
    word rather than ending it — none of them is a shell operator the way
    `&&`/`|`/`;` are, so this scan walks past all of them (mirroring
    _find_top_level_operators's own quote/substitution skipping, applied to
    one word instead of a whole command line) rather than stopping at the
    first one encountered. Only a real Bash word separator — whitespace, or
    one of the |&;()<> operator characters — ends the word.

    A bare `{x,y,...}` group (brace expansion, distinct from a $-prefixed
    `${...}` parameter expansion) sets saw_brace_expansion=True: Bash
    expands that group into MULTIPLE separate words at this position, so
    the caller must not treat whatever surrounds it as fused into one
    argument.
    """
    n = len(cmd)
    i = start
    saw_brace_expansion = False
    while i < n:
        c = cmd[i]
        if c in _ABUT_TRUE_SEPARATORS:
            break
        if c == "\\" and i + 1 < n:
            i += 2  # backslash-escape: extends the current word
            continue
        if c == "'":
            i += 1
            while i < n and cmd[i] != "'":
                i += 1
            i += 1
            continue
        if c == '"':
            i += 1
            while i < n and cmd[i] != '"':
                if cmd[i] == "\\" and i + 1 < n:
                    i += 1
                i += 1
            i += 1
            continue
        if c == "$" and i + 1 < n and cmd[i + 1] == "(":
            i = _skip_balanced_group(cmd, i + 1, "(", ")")
            continue
        if c == "$" and i + 1 < n and cmd[i + 1] == "{":
            i = _skip_balanced_group(cmd, i + 1, "{", "}")
            continue
        if c == "`":
            i += 1
            while i < n and cmd[i] != "`":
                i += 1
            i += 1
            continue
        if c == "{":
            group_end = _skip_balanced_group(cmd, i, "{", "}")
            if "," in cmd[i + 1:group_end - 1]:
                saw_brace_expansion = True
            i = group_end
            continue
        i += 1
    return i, saw_brace_expansion


def _abutted_path_reason_at(cmd: str, close_idx: int) -> "str | None":
    """cmd[close_idx] is a closing quote character. Return a deny reason if
    the token immediately following it (no separating whitespace) is
    path-like, else None. See the module-level comment above this function
    for the false-positive shapes this deliberately excludes and the one
    known residual gap.
    """
    n = len(cmd)
    nxt = close_idx + 1
    if nxt >= n:
        return None  # closing quote is the last character — nothing abuts it

    if cmd[nxt] in _ABUT_TRUE_SEPARATORS:
        # Whitespace, or a real shell operator (`&&`, `|`, `;`, ...): the
        # quote is properly separated from whatever follows it — the
        # common, correct case.
        return None

    run_end, saw_brace_expansion = _scan_abutted_word(cmd, nxt)
    if saw_brace_expansion:
        # Bash expands {a,b} into multiple separate words at this position
        # — not the "one fused word, no separate path" defect at all.
        return None

    is_path_like = "/" in cmd[nxt:run_end]
    if not is_path_like:
        return None  # e.g. 'foo'bar or 'foo'.bar — concatenation, not a path

    context_start = max(0, close_idx - 20)
    fused = cmd[context_start:run_end]
    fixed = cmd[context_start:close_idx + 1] + " " + cmd[nxt:run_end]
    return (
        f"This command fuses a quoted pattern directly onto the very next "
        f"token with no separating space (`...{fused}...`) — Bash "
        "tokenizes the closing quote and the following text as ONE shell "
        "word, so the tool receives a single garbled argument and no path "
        "at all; it reads stdin instead of the file. This check fails "
        "identically regardless of file content. Fix: add a space after "
        f"the closing quote so the path is its own argument "
        f"(`...{fixed}...`)."
    )


def find_abutted_quote_path_reason(cmd: str) -> "str | None":
    """Scan cmd for a closing quote (single or double) immediately followed
    (no whitespace) by a path-like token, and return a deny reason for the
    first such occurrence, or None if cmd is clean.

    Deliberately narrow, matching the "closing quote -> path-like token"
    shape only — see the module-level comment above this section for the
    false positives this must not flag and the one candidate shape
    considered and rejected.
    """
    n = len(cmd)
    i = 0
    in_quote = None  # "'" or '"' or None
    while i < n:
        c = cmd[i]
        if in_quote is None:
            if c in ("'", '"'):
                in_quote = c
            elif c == "\\" and i + 1 < n:
                i += 1  # skip the escaped character too
            i += 1
            continue

        if in_quote == '"' and c == "\\" and i + 1 < n:
            i += 2  # backslash-escape inside a double-quoted string
            continue

        if c == in_quote:
            reason = _abutted_path_reason_at(cmd, i)
            if reason is not None:
                return reason
            in_quote = None
        i += 1
    return None


# ---------------------------------------------------------------------------
# Scope narrowing: only inspect mov_commands[].cmd of a card being created
# via `kanban do` / `kanban todo` — never the raw Bash command line.
# ---------------------------------------------------------------------------

# This hook runs on the *full text* of every Bash tool call from every
# session sharing this checkout (matcher = "Bash" in default.nix), so the
# shlex.split() tokenization cost below is paid even for commands that have
# nothing to do with kanban — this guard's performance benefit applies to
# every oversized Bash command, kanban-related or not. Measured
# tokenization cost is super-linear: 600KB -> 0.415s, 2.4MB -> 4.137s. The
# largest card JSON ever created anywhere in this board's history (checked
# across .kanban/done/, doing/, canceled/, and todo/ — not just done/) is
# 21,760 bytes, in .kanban/done/. Wrapping that exact card in shlex.quote()
# (it contains 68 embedded single-quote characters, a realistic worst case)
# measures a 1.013x quoting multiplier, i.e. 22,034 quoted bytes and a
# 22,044-byte full command line — not the ~2x a naive doubling estimate
# would suggest. 100_000 gives ~4.5x headroom over that measured worst case
# while staying an order of magnitude below the 600KB point where
# tokenization cost turns super-linear.
#
# Only an INLINE-JSON `kanban do`/`kanban todo` invocation can trip this
# guard's lint-skip consequence: a `--file <path>` invocation passes just
# the path on the command line, so the referenced card JSON never appears
# in the command string and can be any size without ever approaching this
# threshold.
_MAX_COMMAND_BYTES = 100_000


def _extract_kanban_do_todo_json(command: str) -> "str | None":
    """If `command` is a `kanban do` / `kanban todo` invocation, return the
    raw card JSON text it carries (from --file content, or the inline
    positional JSON argument). Returns None if `command` does not invoke
    `kanban do`/`kanban todo` at all, or if the JSON source can't be
    determined or read — callers must treat None as "nothing to check here",
    not as an error.
    """
    if len(command) > _MAX_COMMAND_BYTES:
        return None  # pathologically large command — fail open, skip parse
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None  # unbalanced quotes etc. — fail open

    kanban_idx = None
    for i, tok in enumerate(tokens):
        if tok.rsplit("/", 1)[-1] == "kanban":
            kanban_idx = i
            break
    if kanban_idx is None:
        return None  # not a kanban invocation at all

    rest = tokens[kanban_idx + 1:]
    if not rest or rest[0] not in ("do", "todo"):
        return None  # a kanban subcommand other than do/todo — not a card creation

    args = rest[1:]
    json_data = None
    json_file = None
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--file":
            if i + 1 < len(args):
                json_file = args[i + 1]
            i += 2
            continue
        if tok in ("--session", "--mov-cmd", "--mov-timeout"):
            i += 2  # flag that takes a value — skip both
            continue
        if tok.startswith("-"):
            i += 1  # flag with no value (e.g. --force)
            continue
        if json_data is None:
            json_data = tok
        i += 1

    if json_file:
        try:
            return Path(json_file).read_text(encoding="utf-8")
        except OSError:
            return None  # --file path unreadable — fail open
    return json_data


def find_unfailable_mov_reason(raw_card_json: str) -> "str | None":
    """Parse raw_card_json as a card (dict) or bulk-create (list of dicts)
    payload and return a deny reason if any criterion's mov_commands[].cmd
    contains an unfailable final-stage pipe, OR a quoted pattern abutting a
    path-like token with no separating whitespace (see "Abutted quote/path
    detection" above). Returns None if the JSON doesn't parse, isn't a card
    shape, or is clean — mirrors the card-shape handling in kanban.py's
    validate_mov_commands_content (criteria key is "criteria" or its legacy
    alias "ac"; mov_commands entries are objects with "cmd").
    """
    try:
        parsed = json.loads(raw_card_json)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None

    if isinstance(parsed, dict):
        cards = [parsed]
    elif isinstance(parsed, list):
        cards = [c for c in parsed if isinstance(c, dict)]
    else:
        return None

    for card in cards:
        criteria = card.get("criteria") or card.get("ac") or []
        if not isinstance(criteria, list):
            continue
        for criterion in criteria:
            if not isinstance(criterion, dict):
                continue
            mov_commands = criterion.get("mov_commands") or []
            if not isinstance(mov_commands, list):
                continue
            for entry in mov_commands:
                if not isinstance(entry, dict):
                    continue
                cmd = entry.get("cmd")
                if not isinstance(cmd, str) or not cmd:
                    continue
                reason = find_unfailable_pipe_reason(cmd) or find_abutted_quote_path_reason(cmd)
                if reason is not None:
                    return reason
    return None


# ---------------------------------------------------------------------------
# Denial output
# ---------------------------------------------------------------------------

def _deny_response(reason: str) -> dict:
    """Return a permissionDecision=deny response with a reason message.

    Documented PreToolUse deny shape (hookSpecificOutput.permissionDecision),
    not the legacy top-level {"decision": "block", ...} format.
    """
    return {
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


def _deny(reason: str) -> None:
    """Print a permissionDecision=deny response to stdout."""
    print(json.dumps(_deny_response(reason), separators=(",", ":")))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point. Fails open (exit 0, no output) on ANY error.

    This is enforced structurally: the ENTIRE decision below runs inside
    one outer try/except Exception that falls open. Two specific crash
    paths motivated this (non-UTF-8 stdin bytes; a `tool_input` that isn't
    a dict) and are ALSO handled explicitly further down for clarity and to
    keep their fail-open behaviour self-documenting — but the outer
    try/except is what makes "any error results in allowing" (see module
    docstring) an actual guarantee of this code, rather than something that
    merely happens to be true today because Claude Code treats a
    non-blocking hook's exit code 1 as "allow". A future exit-code-semantics
    change, or a not-yet-anticipated malformed-input shape, must not turn
    into a hard block on every Bash command.
    """
    try:
        _decide()
    except Exception:
        sys.exit(0)


def _decide() -> None:
    """The actual decision logic — see main()'s docstring for why this is
    wrapped in a catch-all at the call site instead of here."""
    try:
        raw = sys.stdin.read()
    except UnicodeDecodeError:
        # Fail-open: non-UTF-8 stdin bytes. Explicit (not just caught by
        # main()'s outer try/except) so this specific, previously-observed
        # crash path is self-documenting for future readers.
        sys.exit(0)

    # Fail-open: empty or whitespace-only stdin
    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Fail-open: invalid JSON
        sys.exit(0)

    if not isinstance(payload, dict):
        sys.exit(0)

    # Only inspect Bash tool calls
    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        # Fail-open: explicit (not just caught by main()'s outer
        # try/except) — a `tool_input` that isn't a dict (e.g. a future or
        # different Claude Code payload shape) must not crash via
        # AttributeError on the `.get` call below.
        sys.exit(0)

    command = tool_input.get("command", "")
    if not command or not isinstance(command, str):
        sys.exit(0)

    # Scope narrowing: only a `kanban do`/`kanban todo` invocation carries a
    # card being created — everyday Bash (e.g. `git log --oneline | head
    # -20`) has no mov_commands to inspect and is left alone entirely.
    raw_card_json = _extract_kanban_do_todo_json(command)
    if raw_card_json is None:
        sys.exit(0)

    reason = find_unfailable_mov_reason(raw_card_json)
    if reason is not None:
        _deny(reason)
        sys.exit(0)

    # Nothing flagged — allow.
    sys.exit(0)


if __name__ == "__main__":
    main()
