#!/usr/bin/env python3
"""
kanban-subagent-cmd-hook: PreToolUse(Bash) hook enforcing two distinct prohibitions
on Bash tool calls made from inside a sub-agent.

Despite the name, this hook does not merely gate kanban CLI subcommands — it also
independently denies an entire class of shell-wrapper invocations, whether or not
the command mentions kanban at all. A reader who enumerates hooks by name alone
will underestimate what this module restricts for sub-agents; both prohibitions
below apply regardless of which one the module name evokes.

PROHIBITION 1 — kanban CLI subcommand allowlist:
  Sub-agent kanban CLI usage is restricted to only `kanban criteria check` and
  `kanban criteria uncheck` (plus `kanban --help` / `kanban help`, read-only and
  harmless). All other kanban subcommands (do, start, done, cancel, defer,
  criteria add/remove, list, show, session-hook, etc.) are denied when called
  from a sub-agent context.

PROHIBITION 2 — shell-wrapper denial:
  Sub-agents are denied outright, independent of whether kanban is invoked at
  all, for any shell-runner or script-runner segment carrying an inline -c/-e
  flag. Shell runners (bash, sh, zsh, dash, ksh, fish) are matched on -c; script
  runners (python, python3, perl, ruby) are matched on -c or -e. Examples:
  `bash -c '...'`, `sh -c '...'`, `zsh -c '...'`, `python3 -c '...'`,
  `perl -e '...'`, `ruby -e '...'`. These are blocked entirely because static
  analysis cannot inspect the inline script's content, making them equivalent
  to unrestricted shell access from the guard's perspective — sub-agents have
  direct Bash tool access and never need a shell-runner -c/-e layer.

Coordinators (main session, no agent_id) are unaffected by either prohibition.

Output format (PreToolUse hook — documented hookSpecificOutput format):
  {"suppressOutput": False, "hookSpecificOutput": {
      "hookEventName": "PreToolUse", "permissionDecision": "deny",
      "permissionDecisionReason": "..."}}  — deny
  (exit 0 with no output)                  — allow (fail open)

A deny response denies only the single offending Bash call. Per the deployed
global policy at ~/.claude/CLAUDE.md section "Tool-Block Recovery," a denial
is either MECHANICAL (the rejection message names a corrected form of the
same action — apply the correction and re-issue it in the same turn) or a
PROHIBITION (the action itself is forbidden in any form; the sub-agent must
stop and report the block in its own final return, not attempt a workaround).
Neither class halts the surrounding agent turn: doing so would make same-turn
recovery (mechanical) or the sub-agent's own final-return escalation
(prohibition) structurally impossible.

Fails open: any error (JSON parse failure, empty stdin, shlex error) results in
allowing. Never accidentally block innocent commands.

Sub-agent detection: `payload.get("agent_id")` is the discriminator. Present →
sub-agent. Absent → main session (coordinator). This mirrors the production
implementation in kanban-pretool-hook.py:361-374.

RELIABILITY NOTE (verified against Claude Code 2.1.118, 2026-04-23):
'agent_id' is a single-point-of-failure. If the field is absent from a sub-agent
payload (version regression, format change) the safeguard silently bypasses.
Revisit on major Claude Code version bumps.

ALLOWED sub-agent kanban commands:
  kanban criteria check <card> <n> [--session <session>]
  kanban criteria uncheck <card> <n> [--session <session>]
  kanban --help / kanban help  (read-only, harmless)

DENIED (all others):
  kanban do, kanban start, kanban done, kanban cancel, kanban defer
  kanban criteria add, kanban criteria remove
  kanban list, kanban show, kanban session-hook, etc.

BYPASS MITIGATIONS:
  1. env/command/exec wrappers: `env kanban done 5`, `command kanban done 5`,
     `exec kanban done 5`, `/usr/bin/env kanban done 5` — detected by advancing
     past wrapper tokens in _find_kanban_segment().
  2. shell -c wrappers: `bash -c 'kanban done 5'`, `sh -c '...'`, `python3 -c
     '...'`, etc. — denied entirely for sub-agents via _deny_shell_wrapper().
  3. bare shell env-var prefixes: `KANBAN_SESSION=x kanban list`,
     `FOO=1 BAR=2 kanban done 5` — detected by stripping leading
     VAR=value tokens in _strip_leading_env_assignments().
"""

import json
import re
import shlex
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Shell operator tokens — used to split compound commands.
_SHELL_OPS = frozenset(["&&", "||", ";", "|", "&"])

# Wrapper executables that transparently invoke another binary.
# When segment[0] is one of these, we advance past it to find the real binary.
_ENV_WRAPPERS = frozenset(["env", "/usr/bin/env"])
_COMMAND_WRAPPERS = frozenset(["command"])
_EXEC_WRAPPERS = frozenset(["exec"])
_ALL_WRAPPERS = _ENV_WRAPPERS | _COMMAND_WRAPPERS | _EXEC_WRAPPERS

# Regex that matches a bare shell env-var assignment token: VAR=value.
# Matches identifiers of the form [A-Za-z_][A-Za-z0-9_]* followed by '='
# and zero-or-more non-whitespace characters (including empty values).
# Used to strip leading inline env assignments like `KANBAN_SESSION=x kanban list`.
_ENV_ASSIGNMENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')

# Shell runner binaries that accept -c <inline-script> arguments.
# Sub-agents invoking these with -c are equivalent to having unrestricted shell
# access for the purpose of kanban guard bypasses, so we deny them outright.
#
# HONESTY NOTE (issue #32): BEFORE adding a new runner to _SHELL_RUNNERS,
# _SCRIPT_RUNNERS, or _ALL_INLINE_RUNNERS below -- or before treating the
# excluded-candidates list a few lines down as a closed, fully-surveyed
# set -- read this comment in full.
#
# _SHELL_RUNNERS, _SCRIPT_RUNNERS, and _ALL_INLINE_RUNNERS are
# deliberately-incomplete, best-effort enumerations of interpreter
# binaries confirmed reachable in this repo's Nix environment at time of
# writing -- this is not an exhaustive taxonomy of every inline-code-
# capable interpreter that could ever run here, and other interpreters may
# need adding as they are discovered. `node` was added after a
# reachability sweep (`.scratchpad/issue-32-decision.md`, DECISION-A)
# confirmed it resolves on PATH in this Nix profile
# (`modules/packages.nix:75` declares `nodejs_24`) and supports inline
# execution (`node -e`/`--eval`). `osascript` was added afterward as a
# coordinator extension to that same sweep, not analyzed in the
# DECISION-A record itself -- it was independently confirmed to ship at
# `/usr/bin/osascript` on macOS and to support inline execution
# (`osascript -e`, including via `do shell script` as a further
# shell-execution vector).
#
# Checked and confirmed NOT reachable on PATH in this environment, so deliberately
# excluded: `deno`, `bun`, `php`, `lua`, `julia`, `groovy`, `elixir`, `erl`, `R` (`Rscript` also absent).
# This excluded-candidates list reflects only the interpreters probed at
# time of writing, not an exhaustive survey of every interpreter that
# could exist -- absence from this list does not imply reachability, and
# presence on it does not mean every possible candidate has been
# considered.
#
# `tclsh` IS reachable (`/usr/bin/tclsh`) but was deliberately excluded
# because it has no inline-eval flag -- it only takes a script file or
# reads from stdin, so it is not an inline-code runner in this control's
# sense; do not re-investigate it without new evidence that tclsh gained
# an -e-equivalent flag.
#
# TAXONOMY LIMITATION (issue #32, surfaced by an independent security review
# of this diff): not every shell-execution vector is an interpreter. This
# enumeration and its excluded-candidates list above only ever answered
# "what language interpreters are installed" -- but the review reproduced
# live shell-command execution through `sed -e '.../e'`, `git -c
# alias.x='!cmd' x`, and `awk 'BEGIN{system("cmd")}'`, none of which is an
# interpreter by the intuition this list was built on, and the first two
# are reached through the exact `-e`/`-c` literals this hook already scans
# for. Closing that gap is open work tracked in issue #62, not something
# this enumeration solves.
_SHELL_RUNNERS = frozenset(["bash", "sh", "zsh", "dash", "ksh", "fish"])
_SCRIPT_RUNNERS = frozenset(["python", "python3", "perl", "ruby", "node", "osascript"])
_ALL_INLINE_RUNNERS = _SHELL_RUNNERS | _SCRIPT_RUNNERS

# The -c / -e flag that introduces an inline script for each runner family.
_SHELL_INLINE_FLAGS = frozenset(["-c"])
_SCRIPT_INLINE_FLAGS = frozenset(["-e", "-c"])


# ---------------------------------------------------------------------------
# Sub-agent detection
# ---------------------------------------------------------------------------

def _is_sub_agent(payload: dict) -> bool:
    """Return True if this hook call comes from inside a sub-agent.

    Claude Code populates 'agent_id' in the hook payload only when the hook
    fires inside a subagent call. The field is absent in main-session calls.

    RELIABILITY NOTE (verified against Claude Code 2.1.118, 2026-04-23):
    This is a single-point-of-failure. If 'agent_id' is ever absent from a
    sub-agent payload (version regression, format change) or present in a
    main-session payload (future session IDs), the safeguard silently bypasses.
    Recommend revisiting on major Claude Code version bumps to verify the
    'agent_id' field remains a reliable sub-agent discriminator.
    """
    return bool(payload.get("agent_id"))


# ---------------------------------------------------------------------------
# Command tokenization
# ---------------------------------------------------------------------------

def _normalize_semicolons(tokens: list) -> list:
    """Expand tokens that embed bare semicolons into separate operator tokens.

    shlex.split does not treat ';' as an operator — it merges it with adjacent
    content when there is no surrounding whitespace (e.g., 'cmd;next'). This
    function splits those embedded semicolons so _split_on_shell_ops can
    correctly identify command segment boundaries.
    """
    result = []
    for tok in tokens:
        if ';' not in tok:
            result.append(tok)
            continue
        parts = tok.split(';')
        for i, part in enumerate(parts):
            if part:
                result.append(part)
            if i < len(parts) - 1:
                result.append(';')
    return result


def _split_on_shell_ops(tokens: list) -> list:
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


def _join_continuation_lines(command: str) -> list:
    """Elide real shell backslash-newline continuations before tokenizing.

    Real bash removes a backslash immediately followed by a newline
    entirely (both characters vanish, joining the two physical lines with
    NO separator) whenever that backslash is the line's ODD-numbered
    trailing backslash AND that backslash is not inside a single-quoted
    region — an even trailing count, or a backslash inside single quotes,
    means the newline stands on its own as a real separator (or, inside
    single quotes, the backslash-newline pair is literal DATA, since bash
    gives backslash no special meaning there at all). Python's shlex does
    not model line-continuation at all: it treats a lone backslash as
    "escape the next character," which stops the newline from acting as a
    token SEPARATOR but leaves it embedded INSIDE the resulting token
    (e.g. shlex.split('kanban\\\n done 5') corrupts the binary token to
    'kanban\n', which then fails _is_kanban_binary's exact-string check).
    Eliding real continuations here, before any shlex call, keeps tokens
    clean and matches real shell execution:

      'kanban\\\n done 5'          -> ['kanban done 5']
      'python3 \\\n-c "import x"'  -> ['python3 -c "import x"']

    Returns a list of LOGICAL lines. Non-continued lines remain separate
    entries so the caller can still join them with a real embedded newline
    character, preserving support for multi-line quoted arguments (e.g.
    `kanban done 5 "summary\ntext"`).

    Single-quote awareness: this function tracks quote/escape state via
    the same _scan_quote_state used for balance detection, rather than a
    second, divergent backslash-counting model — reusing the model that
    already gates its escape branch on `not state["in_single"]`
    (kanban-subagent-cmd-hook.py's _scan_quote_state). A trailing
    backslash run only sets state["escaped"] when it appears outside a
    single-quoted region, exactly matching real bash. Without this, a
    backslash-newline spliced INSIDE a single-quoted kanban subcommand
    argument (e.g. `kanban criteria 'chec\\<NL>k' 5 1`) would elide into
    the allowlisted keyword "check", flipping a real DENY into an ALLOW.
    """
    logical: list = []
    current = ""
    state = _fresh_quote_state()
    lines = command.splitlines()
    last_index = len(lines) - 1
    for i, line in enumerate(lines):
        # Scan this physical line's characters into the running quote/escape
        # state (persists across lines, since a single-quoted region can
        # legitimately span several physical lines).
        _scan_quote_state(line, state)
        if state["escaped"] and i < last_index:
            # This line's trailing (odd-count, non-single-quoted) backslash
            # escapes its terminating newline, AND a further physical line
            # exists to actually absorb it — elide both, keep accumulating
            # into the same logical line. The escape is fully resolved by
            # the elided newline, so reset it before scanning the next
            # line's first character.
            current += line[:-1]
            state["escaped"] = False
            continue
        # Either this line ends balanced, or it is the LAST physical line
        # and ends in a dangling escape with no further newline to elide
        # (a genuinely incomplete/malformed command, not a continuation —
        # there is nothing after it to weld with). In the dangling case the
        # trailing backslash is left untouched here (never stripped), so
        # the quote/escape scan in _tokenize_command still sees it as an
        # unresolved trailing escape and correctly keeps buffering
        # (fail-closed) instead of this function silently discarding it.
        current += line
        logical.append(current)
        current = ""
    return logical


def _fresh_quote_state() -> dict:
    """Return a fresh incremental quote/escape scan state."""
    return {"in_single": False, "in_double": False, "escaped": False}


def _scan_quote_state(text: str, state: dict) -> None:
    """Advance the incremental quote/escape state by scanning `text`.

    Mutates `state` in place. Mirrors just enough of shlex's posix-mode
    quoting rules — backslash escapes the next character everywhere
    except inside single quotes; a quote character only toggles its own
    quote mode when not already inside the OTHER quote type — to cheaply
    detect whether the accumulated buffer is still inside an open quote or
    a dangling escape: the two conditions that make shlex.split() raise
    ValueError.

    This is an O(len(text)) pre-check that scans only the NEW text added
    since the last call rather than the whole growing buffer, so the
    caller can skip the expensive shlex.split() call on every line and
    invoke it only when this scan suggests the buffer might already be
    balanced. Being imprecise never trades correctness for speed:
    shlex.split() remains the sole authority on whether a candidate is
    actually a complete, valid token stream — if this scan under-reports
    balance, the caller just waits for more input before retrying shlex,
    never wrongly resolving a segment early.
    """
    for ch in text:
        if state["escaped"]:
            state["escaped"] = False
            continue
        if ch == "\\" and not state["in_single"]:
            state["escaped"] = True
            continue
        if ch == "'" and not state["in_double"]:
            state["in_single"] = not state["in_single"]
            continue
        if ch == '"' and not state["in_single"]:
            state["in_double"] = not state["in_double"]
            continue


def _quote_state_balanced(state: dict) -> bool:
    """Return True if the scan state represents a closed, non-escaping point."""
    return not state["in_single"] and not state["in_double"] and not state["escaped"]


def _strip_stray_quote_chars(token: str) -> str:
    """Strip leading/trailing quote characters from a fallback token.

    Only reached for genuinely malformed input that never balances (see
    _tokenize_command's fallback branch) — its naive whitespace `.split()`
    has no shlex-style quote awareness, so an unterminated quote fused
    directly onto a security-relevant token (e.g. '"kanban', with no
    closing quote anywhere in the command) would otherwise survive as
    part of the token and defeat the exact-string matches in
    _is_kanban_binary() / _is_shell_wrapper_invocation(). Stripping stray
    leading/trailing quote characters only ever makes token
    identification MORE likely to recognize kanban/-c/-e — it strengthens
    rather than weakens the downstream exact-match checks, so it cannot
    introduce a new bypass.
    """
    return token.strip("'\"")


def _segments_from_logical_lines(logical_lines: list) -> list:
    """Tokenize an already backslash-newline-elided logical-line list.

    Returns a list of segments where each segment is a list of tokens.
    Shared buffering/shlex core for _tokenize_command — factored out from
    the continuation-line elision itself so the buffering logic lives in
    one place.

    A single logical shell command can span multiple PHYSICAL lines when a
    quoted argument embeds a literal newline, e.g.:

        kanban done 5 "summary
        text"

    shlex.split() on the first physical line alone sees an unterminated
    quote and raises ValueError. The previous implementation caught that
    ValueError and silently `continue`d past the line — discarding it
    entirely, so no segment was ever produced and neither prohibition ever
    saw the command. That is a fail-OPEN outcome for a security guard: a
    sub-agent could bypass either prohibition (the shell-wrapper -c/-e
    denial, or the kanban subcommand allowlist) simply by splitting the
    interesting quoted argument across two lines.

    To fail CLOSED instead, physical lines are accumulated into a buffer.
    An incremental quote/escape scan (_scan_quote_state) decides cheaply,
    in O(line length) per line, whether the buffer LOOKS balanced; only
    then is the buffer joined and handed to the authoritative
    shlex.split():
      - If the scan says "not yet balanced" (inside an open quote or a
        dangling escape), keep buffering without paying for a join or a
        shlex call — this is what keeps the loop O(n) instead of O(n^2)
        for a quote that only closes on the very last of many lines.
      - If the scan says "looks balanced" and shlex.split() agrees, the
        buffer was a complete, balanced logical unit. Emit its segments
        and start a fresh buffer.
      - If shlex still raises ValueError despite the scan saying balanced
        (a rare escaping edge case the simplified scan doesn't model
        exactly), keep buffering — shlex is always the final word, never
        the cheap scan.
      - If input is exhausted with an unresolved buffer, the text was
        genuinely malformed (no continuation would ever balance it). Fail
        CLOSED: fall back to a naive whitespace split (with stray quote
        characters stripped from each token — see
        _strip_stray_quote_chars) so the downstream substring/token
        checks still get a chance to see this text, rather than the
        content vanishing with no segment formed at all.
    """
    segments_out = []
    buffer_lines: list = []
    quote_state = _fresh_quote_state()
    for line in logical_lines:
        buffer_lines.append(line)
        if len(buffer_lines) > 1:
            _scan_quote_state("\n", quote_state)
        _scan_quote_state(line, quote_state)
        if not _quote_state_balanced(quote_state):
            # Still inside an open quote or a dangling escape — the
            # logical unit may continue on the next physical line. Keep
            # buffering; skip the join + shlex call entirely.
            continue

        candidate = "\n".join(buffer_lines).strip()
        if not candidate:
            buffer_lines = []
            quote_state = _fresh_quote_state()
            continue
        try:
            tokens = shlex.split(candidate)
        except ValueError:
            # The cheap scan said "balanced" but shlex disagrees (a rare
            # escaping edge case the simplified scan doesn't model
            # exactly) — keep buffering; shlex is always the final
            # authority.
            continue
        tokens = _normalize_semicolons(tokens)
        segments_out.extend(_split_on_shell_ops(tokens))
        buffer_lines = []
        quote_state = _fresh_quote_state()

    # Anything left in the buffer never became a balanced shlex unit, even
    # after consuming every remaining line — genuinely malformed input.
    # Fail CLOSED rather than discarding it.
    if buffer_lines:
        remainder = "\n".join(buffer_lines).strip()
        if remainder:
            raw_tokens = [_strip_stray_quote_chars(tok) for tok in remainder.split()]
            tokens = _normalize_semicolons(raw_tokens)
            segments_out.extend(_split_on_shell_ops(tokens))

    return segments_out


def _tokenize_command(command: str) -> list:
    """Tokenize a shell command string into shell-operator-delimited segments.

    Returns a list of segments where each segment is a list of tokens.

    Elides real backslash-newline continuations with the single-quote-aware
    _join_continuation_lines (the bash-accurate reading — see its docstring
    for why single-quote awareness matters: a quote-blind elision would weld
    a single-quote-corrupted subcommand argument like 'chec\\<NL>k' into the
    allowlisted keyword "check", flipping a real DENY into a wrongly-granted
    ALLOW), then hands the resulting logical lines to
    _segments_from_logical_lines for shlex-based tokenization.
    """
    if not command or not command.strip():
        return []

    logical_lines = _join_continuation_lines(command)
    return _segments_from_logical_lines(logical_lines)


# ---------------------------------------------------------------------------
# Kanban command classification
# ---------------------------------------------------------------------------

def _is_kanban_binary(token: str) -> bool:
    """Return True if token is the kanban CLI binary name.

    Matches:
      - 'kanban'              (bare name, not followed by hyphen/word chars)
      - '.kanban-wrapped'     (the wrapped variant used by the CLI infra)
      - '/path/to/bin/kanban' (absolute path to kanban binary)

    Does NOT match:
      - 'kanban-foo'          (hyphen-prefixed binary — different tool)
      - 'cat' or 'echo'      (unrelated tools)
      - '.kanban/foo.json'   (path containing .kanban directory)
    """
    if not token:
        return False
    # Exact name (coordinator uses this)
    if token == "kanban":
        return True
    # Wrapped variant used by CLI infrastructure
    if token == ".kanban-wrapped":
        return True
    # Absolute path ending in /bin/kanban
    if token.endswith("/bin/kanban") and "/" in token:
        return True
    return False


def _is_shell_wrapper_invocation(segment: list) -> bool:
    """Return True if this segment is a shell/script runner with an inline -c/-e flag.

    Detects patterns like:
      bash -c 'kanban done 5'
      sh -c 'kanban cancel 5'
      zsh -c '...'
      python3 -c 'subprocess.run(["kanban", "done", "5"])'
      perl -e '...'
      ruby -e '...'

    These are blocked entirely for sub-agents because static analysis cannot
    inspect the inline script content, making them equivalent to unrestricted
    shell access from the guard's perspective. Sub-agents have direct Bash tool
    access and never need to wrap commands in shell-runner -c layers.

    Does NOT block:
      bash some-script.sh          (script-file invocation, not -c — but this
                                     is only true when some-script.sh's OWN
                                     arguments never include a literal -c/-e
                                     token; a shell runner invoked with a
                                     script file whose own args collide with
                                     -c, e.g. `bash deploy.sh -c prod`, IS
                                     denied by the scan below. See the
                                     accepted-trade note in the loop's
                                     comment for the full false-positive
                                     surface this covers.)
      bash                         (interactive shell, no -c)
    """
    if not segment:
        return False
    binary = segment[0].split("/")[-1]  # strip path prefix, e.g. /bin/bash → bash
    if binary not in _ALL_INLINE_RUNNERS:
        return False
    # Determine which inline flags apply to this runner family
    if binary in _SHELL_RUNNERS:
        inline_flags = _SHELL_INLINE_FLAGS
    else:
        inline_flags = _SCRIPT_INLINE_FLAGS
    # Root cause of a confirmed bypass: this loop used to stop scanning at the
    # first token that did not start with "-", on the assumption that such a
    # token must be the script argument and that flag territory had ended.
    # That assumption is false for any value-consuming flag whose own
    # argument token does not itself start with "-" (e.g. python3's
    # `-W error::SyntaxWarning`) — the scan would break on the flag's VALUE
    # before ever reaching a later `-c`/`-e`, silently allowing the inline
    # code to run. The fix: this loop now scans every token in the segment
    # for exact membership in inline_flags, with no early exit.
    #
    # An alternative fix was considered and rejected: a per-runner table of
    # "flags that consume a following argument token" (mirroring the
    # existing _skip_flags_with_args elsewhere in this module), used to skip
    # past a value-consuming flag's argument instead of scanning every
    # token unconditionally. That approach is the SAME defect class as the
    # early-break assumption above: any per-runner flag table is an
    # enumerable list of "flags that consume an argument," and enumerable
    # lists are inherently incomplete — the bypass that motivated this fix
    # was found by probing only two value-consuming flags out of an
    # open-ended set for a single runner. Do not reintroduce a per-runner
    # flag-skip table to make this scan "smarter"; it would just move the
    # same incompleteness one layer down.
    #
    # Accepted trade, deliberate and pinned by tests, not an oversight: this
    # unconditional scan now also denies any shell runner or script runner
    # whose OWN script/command arguments happen to contain a literal -c or
    # -e token — e.g. `python3 script.py -c config.ini` (script's own -c,
    # not the interpreter's) or `bash deploy.sh -c prod` (a shell runner's
    # script-file argument, not the runner's own -c) — as a false positive.
    # A false deny is loud and recoverable (the agent reports it and stops);
    # a bypass is silent. For a control whose entire job is resisting bypass,
    # that asymmetry decides it — do not reintroduce the early break to
    # "fix" this false positive.
    #
    # KNOWN, DELIBERATE OVER-MATCH (issue #32): _SCRIPT_INLINE_FLAGS applies
    # one flat {-e, -c} set to every _SCRIPT_RUNNERS member. For perl, ruby, and node, `-c` means
    # "check syntax only, do not execute" -- the opposite of inline
    # execution -- so `perl -c script.pl`, `ruby -c script.rb`, and `node
    # -c script.js` are all denied here despite being among the safest
    # possible invocations of each interpreter (verified live: `perl -h`,
    # `ruby -h`, and `node --help` each document `-c` as syntax-check-only,
    # not execution). This is a known, accepted
    # over-match, not a bug to "fix" with a per-runner flag map: a
    # dedicated per-runner override set scoped to each runner's own inline
    # flags would be its own enumerable list, and any such list can
    # silently omit a future inline-execution flag (e.g. a hypothetical
    # `-E`) the same way the runner-name enumeration above can silently
    # omit a runner -- trading a loud, recoverable false positive for a new
    # silent-bypass surface. See the runner-enumeration honesty note above
    # for the same trade-off reasoning applied one layer up.
    #
    # `osascript`'s `-c` is a fourth, differently-flavored instance of this
    # same flat-flag-set over-match, but with no usability cost: osascript
    # has no `-c` flag at all (confirmed live: `osascript -c 'foo'` exits 2
    # with "illegal option -- c"), so this scan denies an invocation that
    # would have failed on its own regardless of this hook -- unlike
    # perl/ruby/node's `-c`, no legitimate use is lost here.
    for tok in segment[1:]:
        if tok in inline_flags:
            return True
    return False


def _advance_past_env_wrapper(segment: list, start: int) -> int:
    """Advance index past `env` wrapper tokens to find the real binary.

    Handles:
      env kanban done 5              → advances 1 (past 'env')
      env KEY=VAL kanban done 5      → advances past 'env' and all KEY=VAL pairs
      env -i kanban done 5           → advances past 'env' and '-i'
      env -u VAR kanban done 5       → advances past 'env', '-u', 'VAR'
      env -- kanban done 5           → advances past 'env' and '--'
    """
    i = start + 1  # skip 'env' / '/usr/bin/env' itself
    while i < len(segment):
        tok = segment[i]
        if tok == "--":
            i += 1
            break
        if tok == "-i":
            i += 1
            continue
        if tok == "-u" and i + 1 < len(segment):
            i += 2  # skip '-u' and the variable name
            continue
        if tok.startswith("-"):
            i += 1  # other env flags (e.g., -0, --null) — skip
            continue
        if "=" in tok and not tok.startswith("-"):
            i += 1  # KEY=VALUE assignment — skip
            continue
        break  # first non-flag, non-assignment token is the real binary
    return i


def _advance_past_command_wrapper(segment: list, start: int) -> int:
    """Advance index past `command` builtin flags to find the real binary.

    Handles:
      command kanban done 5          → advances 1 (past 'command')
      command -p kanban done 5       → advances past 'command' and '-p'
      command -v kanban done 5       → advances past 'command' and '-v'
      command -V kanban done 5       → advances past 'command' and '-V'
    """
    i = start + 1  # skip 'command' itself
    while i < len(segment):
        tok = segment[i]
        if tok in ("-p", "-v", "-V"):
            i += 1
            continue
        break
    return i


def _advance_past_exec_wrapper(segment: list, start: int) -> int:
    """Advance index past `exec` builtin flags to find the real binary.

    Handles:
      exec kanban done 5             → advances 1 (past 'exec')
      exec -c kanban done 5          → advances past 'exec' and '-c'
      exec -l kanban done 5          → advances past 'exec' and '-l'
      exec -a NAME kanban done 5     → advances past 'exec', '-a', 'NAME'
    """
    i = start + 1  # skip 'exec' itself
    while i < len(segment):
        tok = segment[i]
        if tok == "-a" and i + 1 < len(segment):
            i += 2  # skip '-a' and the name argument
            continue
        if tok in ("-c", "-l"):
            i += 1
            continue
        break
    return i


def _strip_leading_env_assignments(segment: list) -> list:
    """Strip leading bare shell env-var assignment tokens from a segment.

    Bash allows inline env-var assignments before a command:
      KANBAN_SESSION=x kanban list
      FOO=1 BAR=2 BAZ=3 kanban done 5
      FOO=val_with_punct/.path kanban done 5
      KANBAN_SESSION= kanban list  (empty value)

    shlex.split preserves these as individual tokens (e.g. 'KANBAN_SESSION=x').
    This function advances past all leading tokens that match the pattern
    [A-Za-z_][A-Za-z0-9_]*= (i.e., a valid shell identifier followed by '=')
    and returns the remainder.  The first token NOT matching the pattern is
    treated as the real command.

    Examples:
      ['KANBAN_SESSION=x', 'kanban', 'list'] → ['kanban', 'list']
      ['FOO=1', 'BAR=2', 'kanban', 'done', '5'] → ['kanban', 'done', '5']
      ['KANBAN_SESSION=', 'kanban', 'list'] → ['kanban', 'list']
      ['kanban', 'done', '5'] → ['kanban', 'done', '5']  (unchanged)
      ['ls'] → ['ls']  (unchanged)
    """
    i = 0
    while i < len(segment) and _ENV_ASSIGNMENT_RE.match(segment[i]):
        i += 1
    return segment[i:]


def _skip_flags_with_args(tokens: list, start: int) -> int:
    """Advance index past any leading flags that take an argument value.

    Returns the index of the first non-flag token after `start`,
    or len(tokens) if we exhaust the list.
    """
    # kanban global flags that take a value argument
    flags_with_args = {"--session", "--output-style", "--output", "--format"}
    i = start
    while i < len(tokens):
        tok = tokens[i]
        if tok in flags_with_args:
            i += 2  # skip flag + value
            continue
        if tok.startswith("--") and "=" in tok:
            i += 1  # --flag=value, no separate arg token
            continue
        break
    return i


def _is_allowed_kanban_subcommand(tokens_after_kanban: list) -> bool:
    """Return True if the kanban subcommand is in the allow-list for sub-agents.

    Allowed:
      kanban criteria check <card> <n> [options]
      kanban criteria uncheck <card> <n> [options]
      kanban --help
      kanban help

    Denied: everything else.

    tokens_after_kanban: the tokens following the 'kanban' binary token,
    with global flags already stripped.
    """
    if not tokens_after_kanban:
        # `kanban` with no args — deny (not a useful read-only command)
        return False

    first = tokens_after_kanban[0]

    # Allow help (read-only, harmless)
    if first in ("--help", "-h", "help"):
        return True

    # Allow only `criteria check` and `criteria uncheck`
    if first == "criteria":
        if len(tokens_after_kanban) >= 2:
            second = tokens_after_kanban[1]
            if second in ("check", "uncheck"):
                return True
        # `criteria` with no subcommand or other subcommand (add, remove, etc.) → deny
        return False

    return False


def _resolve_kanban_slice(segment: list) -> "list | None":
    """Return the kanban portion of a SINGLE segment, or None if this segment
    does not invoke the kanban binary.

    Returns the sub-slice of the segment starting at the kanban binary token.
    The returned slice always has the kanban binary as its first element,
    enabling callers to strip it uniformly.

    We look for kanban as the BINARY name (first non-flag token of the
    segment), not as a substring anywhere (e.g., `cat .kanban/foo.json` is not
    a kanban CLI invocation).

    Wrapper handling — env/command/exec prefix the real binary. When segment[0]
    is one of these known wrappers, we advance past wrapper-specific flags and
    assignments to check whether the underlying binary is kanban. The returned
    slice starts at the kanban binary, not at the wrapper:

      env kanban done 5              → ['kanban', 'done', '5']
      env KEY=VAL kanban done 5      → ['kanban', 'done', '5']
      /usr/bin/env kanban done 5     → ['kanban', 'done', '5']
      command kanban done 5          → ['kanban', 'done', '5']
      exec kanban done 5             → ['kanban', 'done', '5']
      kanban done 5                  → ['kanban', 'done', '5']

    Bare shell env-var prefix handling — bash allows inline assignments before
    a command without the `env` binary. Strip these before binary detection:

      KANBAN_SESSION=x kanban list   → ['kanban', 'list']
      FOO=1 BAR=2 kanban done 5      → ['kanban', 'done', '5']
      KANBAN_SESSION= kanban list    → ['kanban', 'list']
    """
    if not segment:
        return None
    first_token = segment[0]
    if _is_kanban_binary(first_token):
        return segment  # starts at kanban binary already
    # Check for wrapper prefix: advance past wrapper tokens to find real binary
    if first_token in _ENV_WRAPPERS:
        real_idx = _advance_past_env_wrapper(segment, 0)
        if real_idx < len(segment) and _is_kanban_binary(segment[real_idx]):
            return segment[real_idx:]
    elif first_token in _COMMAND_WRAPPERS:
        real_idx = _advance_past_command_wrapper(segment, 0)
        if real_idx < len(segment) and _is_kanban_binary(segment[real_idx]):
            return segment[real_idx:]
    elif first_token in _EXEC_WRAPPERS:
        real_idx = _advance_past_exec_wrapper(segment, 0)
        if real_idx < len(segment) and _is_kanban_binary(segment[real_idx]):
            return segment[real_idx:]
    elif _ENV_ASSIGNMENT_RE.match(first_token):
        # Bare shell env-var assignment prefix: VAR=value cmd args
        # Strip all leading assignments to expose the real command binary.
        stripped = _strip_leading_env_assignments(segment)
        if stripped and _is_kanban_binary(stripped[0]):
            return stripped
    return None


def _kanban_slice_is_forbidden(kanban_slice: list) -> bool:
    """Return True if a resolved kanban slice's subcommand is NOT allowlisted.

    Mirrors main()'s own resolution of the subcommand from a kanban slice
    (strip the leading kanban binary token, skip any global flags-with-args,
    then check the remaining subcommand tokens against the allowlist) so that
    _find_kanban_segment can decide, per-segment, whether a match is a
    forbidden invocation without duplicating a divergent copy of that logic.
    """
    tokens_after_binary = kanban_slice[1:]
    start = _skip_flags_with_args(tokens_after_binary, 0)
    subcommand_tokens = tokens_after_binary[start:]
    return not _is_allowed_kanban_subcommand(subcommand_tokens)


def _find_kanban_segment(segments: list) -> "list | None":
    """Return the kanban slice that should decide this command's allow/deny
    outcome, scanning ALL segments rather than stopping at the first match.

    A compound command (`a && b`, `a ; b`, `a || b`, `a | b`, `a & b`) can
    invoke kanban more than once across different segments, and real bash
    executes every one of them (unconditionally for `;`/`|`/`&`, or
    conditionally on exit status for `&&`/`||` — `kanban criteria check`
    legitimately exits 0 on success, so the `&&` case is not a rare corner).
    A single-segment return contract that stops at the FIRST segment
    producing any kanban match — allowlisted or not — lets a forbidden
    invocation in a LATER segment slip through undetected whenever an
    earlier segment happens to resolve to an allowed `criteria check`/
    `criteria uncheck`/`--help` shape (or nothing at all, e.g. `kanban
    --help && kanban done 5`).

    Resolution rule: scan every segment's resolved kanban slice (via
    _resolve_kanban_slice). If ANY segment resolves to a FORBIDDEN kanban
    invocation, return that slice — a forbidden segment anywhere wins over
    an allowed segment earlier in the command, matching what real bash
    would actually execute. Only when no segment resolves to a forbidden
    invocation do we fall back to returning the first resolved match (or
    None if there was none at all), preserving this function's original
    single-segment return contract for the all-allowed / no-match cases.
    """
    first_match = None
    for segment in segments:
        resolved = _resolve_kanban_slice(segment)
        if resolved is None:
            continue
        if first_match is None:
            first_match = resolved
        if _kanban_slice_is_forbidden(resolved):
            return resolved
    return first_match


# ---------------------------------------------------------------------------
# Denial output
# ---------------------------------------------------------------------------

def _deny_response(reason: str) -> dict:
    """Return a permissionDecision=deny response with a reason message.

    This mirrors kanban-pretool-hook.py's deny_with_reason() — the
    documented PreToolUse deny shape (hookSpecificOutput.permissionDecision),
    not the legacy top-level {"decision": "block", ...} format.

    Deliberately omits the top-level turn-halting pair (see module
    docstring's "Tool-Block Recovery" reference) — do not re-add it: this denies only the single
    offending Bash call, leaving the sub-agent's turn free to either retry a
    corrected form (mechanical) or compose its own "stop and report" final
    return (prohibition) — both of which a turn-halting response would
    foreclose.
    """
    return {
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _deny(command: str) -> None:
    """Print a permissionDecision=deny response to stdout and exit."""
    # Sanitize for embedding in message (strip non-printable characters)
    safe_cmd = "".join(
        c for c in command if c.isprintable() or c in ("\t", "\n")
    )
    reason = (
        "Sub-agents may only call 'kanban criteria check' and "
        "'kanban criteria uncheck'. "
        f"Attempted: {safe_cmd!r}. "
        "The coordinator handles all other lifecycle commands "
        "(do/start/done/cancel/defer/criteria add/remove). "
        "This command is blocked in any form — do not attempt a workaround. "
        "Stop and report this block in your own final return so the "
        "coordinator can run the needed command instead."
    )
    print(json.dumps(_deny_response(reason), separators=(",", ":")))


def _deny_shell_wrapper(command: str) -> None:
    """Print a permissionDecision=deny response for shell-wrapper (-c/-e) invocations.

    Sub-agents may not use shell-wrapper invocations (bash -c, sh -c,
    python3 -c, etc.) because these are equivalent to unrestricted shell
    access for the purposes of the kanban guard. Static analysis cannot
    inspect inline script content. Sub-agents have direct Bash tool access
    and do not need shell-runner wrapper layers.
    """
    safe_cmd = "".join(
        c for c in command if c.isprintable() or c in ("\t", "\n")
    )
    reason = (
        "Sub-agents may not use shell-wrapper invocations "
        "(bash -c, sh -c, zsh -c, python -c, python3 -c, perl -e, ruby -e, etc.). "
        "Use direct command invocation instead. "
        "If the -c/-e token above actually belongs to your own script's or "
        "command's arguments rather than to the runner itself, this is a "
        "known, accepted false-positive trade-off, not a bug — do not "
        "rephrase or retry to work around it; "
        "report it in your final return instead. "
        f"Attempted: {safe_cmd!r}."
    )
    print(json.dumps(_deny_response(reason), separators=(",", ":")))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()

    # Fail-open: empty or whitespace-only stdin
    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Fail-open: invalid JSON
        sys.exit(0)

    # Only inspect Bash tool calls
    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    # Only restrict sub-agents — coordinators are unrestricted
    if not _is_sub_agent(payload):
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "")

    # Fail-open: empty command
    if not command:
        sys.exit(0)

    # Tokenize the command into segments split by shell operators
    segments = _tokenize_command(command)

    # If tokenization failed entirely (e.g., shlex errors), fail-open
    if not segments:
        sys.exit(0)

    # Check for shell/script runner -c invocations before kanban detection.
    # These bypass static kanban analysis entirely by embedding the kanban call
    # inside a string argument that shlex treats as a single opaque token.
    # Deny them outright — sub-agents have direct Bash tool access.
    for segment in segments:
        if _is_shell_wrapper_invocation(segment):
            _deny_shell_wrapper(command)
            sys.exit(0)

    # Find the segment to decide on: the first FORBIDDEN kanban segment if one
    # exists anywhere in the command, otherwise the first segment that invokes
    # the kanban binary. Forbidden-anywhere-wins - see _find_kanban_segment().
    kanban_segment = _find_kanban_segment(segments)

    # No kanban invocation found — allow (e.g., ls, git status)
    if kanban_segment is None:
        sys.exit(0)

    # NOTE: _kanban_slice_is_forbidden() carries a second copy of this same
    # three-step resolution (see its docstring, which points back here). An
    # edit to the steps below MUST be mirrored there, or the per-segment
    # forbidden check and this final decision will silently disagree.

    # Strip the leading kanban binary token and any global flags-with-args
    # to find the subcommand
    tokens_after_binary = kanban_segment[1:]
    start = _skip_flags_with_args(tokens_after_binary, 0)
    subcommand_tokens = tokens_after_binary[start:]

    if _is_allowed_kanban_subcommand(subcommand_tokens):
        sys.exit(0)

    # Denied — emit block decision
    _deny(command)
    sys.exit(0)


if __name__ == "__main__":
    main()
