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
# Scope narrowing: only inspect mov_commands[].cmd of a card being created
# via `kanban do` / `kanban todo` — never the raw Bash command line.
# ---------------------------------------------------------------------------

def _extract_kanban_do_todo_json(command: str) -> "str | None":
    """If `command` is a `kanban do` / `kanban todo` invocation, return the
    raw card JSON text it carries (from --file content, or the inline
    positional JSON argument). Returns None if `command` does not invoke
    `kanban do`/`kanban todo` at all, or if the JSON source can't be
    determined or read — callers must treat None as "nothing to check here",
    not as an error.
    """
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
    contains an unfailable final-stage pipe. Returns None if the JSON doesn't
    parse, isn't a card shape, or is clean — mirrors the card-shape handling
    in kanban.py's validate_mov_commands_content (criteria key is "criteria"
    or its legacy alias "ac"; mov_commands entries are objects with "cmd").
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
                reason = find_unfailable_pipe_reason(cmd)
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
