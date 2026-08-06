"""
Tests for modules/claude/kanban-mov-lint-hook.py.

ARCHITECTURE NOTE: Card-JSON banned-pattern validation (backslash-pipe,
AND-chain, rg -E, absence-via-count idiom, hook-skip flags, dash-leading
patterns, empty mov_commands) lives in the kanban CLI itself (kanban.py —
see validate_mov_commands_content), not in this hook. The substantive tests
for that class of check live in:
  modules/kanban/tests/test_kanban_mov_validation.py

This hook DOES perform one check of its own, scoped to the SAME layer as the
CLI-level checks in kanban.py: a card being CREATED via `kanban do` / `kanban
todo`. It parses that invocation's card JSON (inline positional arg or
--file content) and rejects a mov_commands[].cmd whose pipeline's FINAL
top-level stage is a formatting/slicing filter (head, tail, cut, sort, tr) —
such a pipeline's exit status is always 0 regardless of whether an upstream
command (e.g. rg) actually matched anything, so a criterion built on it can
never fail.

Critically, this check must NEVER fire on an everyday Bash command that
isn't a `kanban do`/`kanban todo` invocation — e.g. `git log --oneline |
head -20` — even though such a command's own final pipe stage is also
`head`. The hook is registered on matcher="Bash" (every Bash tool call from
every agent), so misapplying the mov_commands check to the raw command line
instead of to the card JSON it carries would deny ordinary shell usage
repo-wide. TestScopeIsCardMovCommandsOnly pins both directions of this
decision.

TestHookIsPassThrough verifies the hook otherwise stays out of the way
(imports cleanly, discards stdin, allows non-Bash/non-matching commands).
TestUnfailablePipeDetection verifies the final-stage-filter check itself via
`kanban do` card payloads, including both legitimate non-final-stage forms
(`wc -l` and `head`/`cut` feeding a `test` assertion via command
substitution) that must continue to be accepted.
"""

import importlib.util
import io
import json
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "kanban-mov-lint-hook.py"


def load_hook():
    """Import kanban-mov-lint-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_mov_lint_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a given stdin string
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, stdin_content: str = "") -> "dict | None":
    """
    Call hook_mod.main() with stdin_content.
    Returns any JSON printed to stdout, or None if nothing was printed (allow).
    """
    captured_output: list[str] = []

    def fake_print(val, **kwargs):
        captured_output.append(val)

    with patch.object(sys, "stdin", io.StringIO(stdin_content)):
        with patch("builtins.print", side_effect=fake_print):
            try:
                hook_mod.main()
            except SystemExit:
                pass

    if not captured_output:
        return None
    try:
        return json.loads(captured_output[-1])
    except (json.JSONDecodeError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHookIsPassThrough:
    """The hook always allows — all validation is now in the kanban CLI."""

    def test_empty_stdin_allows(self, hook):
        """Empty stdin → hook exits 0 with no output (allow)."""
        result = run_hook_main(hook, "")
        assert result is None, f"Expected allow (None), got: {result}"

    def test_kanban_do_file_with_banned_pattern_allows(self, hook):
        """kanban do --file with backslash-pipe cmd → hook allows (CLI validates instead)."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "kanban do --file /tmp/card.json"},
        })
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"

    def test_kanban_todo_file_allows(self, hook):
        """kanban todo --file invocation → hook always allows."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "kanban todo --file /tmp/card.json"},
        })
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"

    def test_non_kanban_command_allows(self, hook):
        """Non-kanban command → hook allows."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "rg -q pattern file"},
        })
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"

    def test_malformed_json_stdin_allows(self, hook):
        """Malformed JSON stdin → hook allows (no crash)."""
        result = run_hook_main(hook, "{invalid json}")
        assert result is None, f"Expected allow (None), got: {result}"

    def test_non_bash_tool_call_allows(self, hook):
        """Non-Bash tool call → hook allows."""
        payload = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/test.py"},
        })
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"


# ---------------------------------------------------------------------------
# Helper: run a Bash command string through the hook and return the parsed
# deny decision (or None if allowed).
# ---------------------------------------------------------------------------

def _run_bash_command(hook_mod, command: str) -> "dict | None":
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
    })
    return run_hook_main(hook_mod, payload)


def _kanban_do_command(mov_cmd: str, subcommand: str = "do") -> str:
    """Build a `kanban <subcommand> '<card-json>'` Bash command string whose
    one criterion has one mov_commands entry with the given cmd — the exact
    payload shape the hook must parse via `_extract_kanban_do_todo_json` /
    `find_unfailable_mov_reason` (card dict, `criteria` list, `mov_commands`
    list of {"cmd": ..., "timeout": ...} objects; see kanban.py's
    resolve_json_input + validate_mov_commands_content for the schema this
    mirrors).

    shlex.quote (not a hand-rolled single-quote wrap) is used so mov_cmd
    strings containing single quotes (as most of ours do, e.g. `rg -qi
    'pattern' file | head -1`) round-trip correctly through shlex.split —
    the same tokenizer the hook itself uses on tool_input.command.
    """
    card = {
        "title": "t",
        "action": "a",
        "intent": "i",
        "criteria": [
            {"text": "c1", "mov_commands": [{"cmd": mov_cmd, "timeout": 10}]},
        ],
    }
    card_json = json.dumps(card)
    return f"kanban {subcommand} {shlex.quote(card_json)}"


class TestUnfailablePipeDetection:
    """A card's mov_commands[].cmd whose pipeline's FINAL top-level stage is
    a formatting/slicing filter (head/tail/cut/sort/tr) can never fail —
    that filter exits 0 even on empty stdin, discarding the upstream
    command's exit status. The hook must reject exactly this shape when it
    appears in a `kanban do`/`kanban todo` card payload, while continuing to
    accept the same filters used as NON-final stages feeding a surrounding
    `test` assertion via command substitution.
    """

    # -- Rejected: final pipeline stage is a formatting/slicing filter -----

    def test_final_stage_head_is_rejected(self, hook):
        """`rg ... | head -1` in a card's mov_commands can never fail —
        head exits 0 on empty stdin."""
        result = _run_bash_command(
            hook, _kanban_do_command("rg -qi 'nonexistent-xyz' /etc/hosts | head -1")
        )
        assert result is not None, "Expected a deny decision, got allow"
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("permissionDecision") == "deny", (
            f"Expected deny, got: {result}"
        )
        assert "continue" not in result, (
            "Deny response must not carry a top-level 'continue' key — per "
            "CLAUDE.md's Tool-Block Recovery policy, a mechanical denial "
            "must not halt the agent turn; only "
            "hookSpecificOutput.permissionDecision may deny the single "
            f"offending call. Got: {result}"
        )

    def test_final_stage_rejection_names_cause_and_fix(self, hook):
        """The deny reason must name the cause (exit code/status discarded)
        and the fix (quiet flag or terminate in an assertion) — an
        unactionable rejection message gets the lint disabled."""
        result = _run_bash_command(
            hook, _kanban_do_command("rg -qi 'pattern' file | head -1")
        )
        reason = result.get("hookSpecificOutput", {}).get(
            "permissionDecisionReason", ""
        )
        assert "exit code is discarded" in reason.lower() or (
            "exit status is discarded" in reason.lower()
        ), f"Reason does not name the cause: {reason!r}"
        assert "rg -q" in reason or "assertion" in reason.lower(), (
            f"Reason does not name a fix: {reason!r}"
        )

    def test_final_stage_via_or_fallback_is_rejected(self, hook):
        """`A | cut ... || echo fallback` — the `||` fallback can never fire
        because the pipe it guards always exits 0 (ends in `cut`). This is
        the exact shape that motivated this check."""
        result = _run_bash_command(
            hook,
            _kanban_do_command("rg -q 'pattern' file | cut -d: -f1 || echo fallback"),
        )
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny", (
            f"Expected deny, got: {result}"
        )

    def test_final_stage_tail_is_rejected(self, hook):
        result = _run_bash_command(hook, _kanban_do_command("rg -n 'foo' file | tail -5"))
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_final_stage_sort_is_rejected(self, hook):
        result = _run_bash_command(hook, _kanban_do_command("rg -n 'foo' file | sort"))
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_final_stage_tr_is_rejected(self, hook):
        result = _run_bash_command(hook, _kanban_do_command("echo abc | tr 'a-z' 'A-Z'"))
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_final_stage_head_is_rejected_via_todo_subcommand(self, hook):
        """`kanban todo` (not just `kanban do`) carries the same card-JSON
        shape and must be checked identically."""
        result = _run_bash_command(
            hook,
            _kanban_do_command("rg -n 'foo' file | head -1", subcommand="todo"),
        )
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_final_stage_head_is_rejected_via_file_flag(self, hook, tmp_path):
        """`kanban do --file <path>` carries the card JSON on disk, not
        inline — the hook must read and check that file's content too."""
        card = {
            "title": "t",
            "action": "a",
            "intent": "i",
            "criteria": [
                {
                    "text": "c1",
                    "mov_commands": [
                        {"cmd": "rg -n 'foo' file | head -1", "timeout": 10}
                    ],
                }
            ],
        }
        card_path = tmp_path / "card.json"
        card_path.write_text(json.dumps(card), encoding="utf-8")
        result = _run_bash_command(hook, f"kanban do --file {card_path}")
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny", (
            f"Expected deny, got: {result}"
        )

    # -- Accepted: filter feeds a surrounding assertion (non-final stage) --

    def test_wc_l_inside_test_substitution_is_allowed(self, hook):
        """`test "$(... | wc -l)" -ge N` — wc's output is test's input, and
        test is the assertion whose exit status the shell reports. This is
        the regression guard that matters most: ~19 existing usages of this
        exact shape live in staff-engineer.md and must never be blocked."""
        result = _run_bash_command(
            hook,
            _kanban_do_command('test "$(rg -o \'pattern\' file | wc -l)" -ge 3'),
        )
        assert result is None, f"Expected allow (None), got: {result}"

    def test_head_and_cut_inside_test_substitution_is_allowed(self, hook):
        """`test $(rg ... | head -1 | cut -d: -f1) -lt $(...)` — the
        documented line-ordering MoV form. It contains BOTH rejected filter
        names (head, cut) but only as non-final stages feeding `test`."""
        result = _run_bash_command(
            hook,
            _kanban_do_command(
                "test $(rg -n PAT file | head -1 | cut -d: -f1) -lt "
                "$(rg -n OTHER file | head -1 | cut -d: -f1)"
            ),
        )
        assert result is None, f"Expected allow (None), got: {result}"

    def test_no_pipe_allows(self, hook):
        """A command with no pipe at all has nothing to flag."""
        result = _run_bash_command(hook, _kanban_do_command("rg -q 'pattern' file"))
        assert result is None, f"Expected allow (None), got: {result}"

    def test_single_quoted_pipe_character_is_not_a_pipe_operator(self, hook):
        """A `|` character inside single quotes is regex alternation, not a
        shell pipe operator, and must not be mistaken for a pipe boundary."""
        result = _run_bash_command(hook, _kanban_do_command("rg -q 'foo|bar' file"))
        assert result is None, f"Expected allow (None), got: {result}"


class TestBareSubshellEvasion:
    """A bare `(...)` subshell's own exit status propagates to whatever
    chain contains it — unlike `$(...)`, whose exit status is discarded and
    only its stdout text feeds something else. `(rg -q x file | head -1)`
    is therefore exactly as unfailable as the unwrapped form; wrapping in
    ordinary command-grouping parens must not evade the check (card #3287
    ASK 1)."""

    def test_bare_subshell_final_filter_is_rejected(self, hook):
        """`(rg -qi 'nonexistent-xyz' /etc/hosts | head -1)` — a bare
        subshell wrapping the exact canonical unfailable-pipe shape — must
        be denied identically to the unwrapped form."""
        result = _run_bash_command(
            hook,
            _kanban_do_command("(rg -qi 'nonexistent-xyz' /etc/hosts | head -1)"),
        )
        assert result is not None, "Expected a deny decision, got allow"
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("permissionDecision") == "deny", (
            f"Expected deny, got: {result}"
        )

    def test_bare_subshell_followed_by_and_operator_is_rejected(self, hook):
        """`(rg -q x file | head -1) && true` — the trailing `&& true`
        cannot rescue the pipe inside the subshell; the subshell's own exit
        status (0, from `head`) is what determines whether the `&&`
        right-hand side even matters, and the check must still see the
        `head` inside as the culprit."""
        result = _run_bash_command(
            hook,
            _kanban_do_command(
                "(rg -qi 'nonexistent-xyz' /etc/hosts | head -1) && true"
            ),
        )
        assert result is not None, "Expected a deny decision, got allow"
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("permissionDecision") == "deny", (
            f"Expected deny, got: {result}"
        )

    def test_bare_subshell_used_for_ordinary_grouping_without_unfailable_pipe_is_allowed(
        self, hook
    ):
        """Parens are a legitimate, common construct for scoping/readability
        with zero evasive intent (e.g. an OR-fallback with no pipe at all
        inside). Flattening bare-paren scanning must not turn ordinary
        command grouping into a false positive."""
        result = _run_bash_command(
            hook,
            _kanban_do_command("(rg -q 'a' file || rg -q 'b' file)"),
        )
        assert result is None, f"Expected allow (None), got: {result}"


class TestFilterListCoverage:
    """`BANNED_FINAL_PIPE_FILTERS` was extended (card #3287 ASK 2 + ASK 3)
    to cover every final-pipe-stage filter that genuinely cannot propagate
    a meaningful failure, while explicitly excluding filters that CAN
    (`cat`, `xargs`) — banning those would reject correct MoVs, which is
    the more dangerous direction for a lint gate. See the rationale comment
    beside BANNED_FINAL_PIPE_FILTERS in kanban-mov-lint-hook.py."""

    # -- wc: unfailable bare, still fine inside a command substitution -----

    def test_wc_as_bare_final_stage_is_rejected(self, hook):
        """`rg -c 'pattern' file | wc -l` used bare (no `test $(...)`
        wrapper) is exactly as unfailable as `| head -1` — `wc -l` exits 0
        on 0 lines too."""
        result = _run_bash_command(
            hook, _kanban_do_command("rg -c 'pattern' file | wc -l")
        )
        assert result is not None, "Expected a deny decision, got allow"
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("permissionDecision") == "deny", (
            f"Expected deny, got: {result}"
        )

    # -- newly-banned filters: each genuinely unfailable as a final stage --

    def test_awk_as_final_stage_is_rejected(self, hook):
        """`awk` as a bare final pipe stage exits 0 whether or not any line
        matched — no exit-code signal for "matched nothing" absent an
        explicit `exit` statement in the program."""
        result = _run_bash_command(
            hook, _kanban_do_command("rg -n 'foo' file | awk '{print $1}'")
        )
        assert result is not None, "Expected a deny decision, got allow"
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("permissionDecision") == "deny", (
            f"Expected deny, got: {result}"
        )

    def test_sed_as_final_stage_is_rejected(self, hook):
        result = _run_bash_command(
            hook, _kanban_do_command("rg -n 'foo' file | sed -n '1p'")
        )
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_uniq_as_final_stage_is_rejected(self, hook):
        result = _run_bash_command(hook, _kanban_do_command("rg -n 'foo' file | uniq"))
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_tee_as_final_stage_is_rejected(self, hook):
        result = _run_bash_command(
            hook, _kanban_do_command("rg -n 'foo' file | tee /tmp/out")
        )
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_rev_as_final_stage_is_rejected(self, hook):
        result = _run_bash_command(hook, _kanban_do_command("rg -n 'foo' file | rev"))
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_fold_as_final_stage_is_rejected(self, hook):
        result = _run_bash_command(
            hook, _kanban_do_command("rg -n 'foo' file | fold -w 10")
        )
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    def test_column_as_final_stage_is_rejected(self, hook):
        result = _run_bash_command(
            hook, _kanban_do_command("rg -n 'foo' file | column")
        )
        hook_output = result.get("hookSpecificOutput", {}) if result else {}
        assert hook_output.get("permissionDecision") == "deny"

    # -- deliberately excluded: genuinely fallible as a final stage --------

    def test_cat_as_final_stage_is_allowed(self, hook):
        """`cat` can propagate a meaningful failure as a final stage (e.g.
        `cat missing-file` exits non-zero) — must NOT be banned."""
        result = _run_bash_command(
            hook, _kanban_do_command("rg -l 'pattern' . | cat")
        )
        assert result is None, f"Expected allow (None), got: {result}"

    def test_xargs_as_final_stage_is_allowed(self, hook):
        """`xargs` propagates the exit status of the command it invokes
        (e.g. `... | xargs pytest` reports pytest's own failure) — must NOT
        be banned."""
        result = _run_bash_command(
            hook, _kanban_do_command("rg -l 'pattern' . | xargs pytest")
        )
        assert result is None, f"Expected allow (None), got: {result}"


class TestScopeIsCardMovCommandsOnly:
    """Pins the scope decision in both directions: this hook is registered
    on matcher="Bash" (every Bash tool call, from any agent) but must only
    ever evaluate mov_commands[].cmd strings from a `kanban do`/`kanban
    todo` card payload — never the raw Bash command line of an arbitrary
    command. A regression here denies ordinary shell usage repo-wide (see
    kanban-mov-lint-hook.py's ARCHITECTURE NOTE / IMPORTANT — layer boundary
    section).
    """

    def test_everyday_git_log_head_pipe_is_allowed(self, hook):
        """`git log --oneline | head -20` is an everyday command, not a MoV
        — it must be allowed even though its own final pipe stage is
        `head`, because it is not a `kanban do`/`kanban todo` invocation at
        all and therefore has no mov_commands to inspect."""
        result = _run_bash_command(hook, "git log --oneline | head -20")
        assert result is None, f"Expected allow (None), got: {result}"

    def test_transcript_interrogation_rg_head_pipe_is_allowed(self, hook):
        """The transcript-interrogation diagnostic staff-engineer.md
        instructs agents to run (rg over a transcript piped into head) must
        not be denied merely for ending in `head`."""
        result = _run_bash_command(
            hook, "rg -n 'tool_use' transcript.jsonl | head -5"
        )
        assert result is None, f"Expected allow (None), got: {result}"

    def test_kanban_do_card_with_unfailable_mov_is_still_denied(self, hook):
        """The complementary direction: a `kanban do` card payload whose
        mov_commands genuinely contains an unfailable pipeline must still
        be denied — narrowing scope away from raw Bash must not also
        silently disable the check where it actually applies."""
        result = _run_bash_command(
            hook, _kanban_do_command("rg -qi 'nonexistent-xyz' /etc/hosts | head -1")
        )
        assert result is not None, "Expected a deny decision, got allow"
        hook_output = result.get("hookSpecificOutput", {})
        assert hook_output.get("permissionDecision") == "deny", (
            f"Expected deny, got: {result}"
        )


class TestFailsOpenByDesign:
    """The hook's docstring claims 'any error... results in allowing'
    (card #3287 ASK 4). Two unhandled-exception paths previously
    contradicted that claim (non-UTF-8 stdin bytes; a non-dict
    `tool_input`), and only failed open in practice as an incidental
    consequence of Claude Code treating a hook's exit code 1 as
    non-blocking. These tests pin the fix: fail-open is now a structural
    guarantee (main()'s outer try/except) plus explicit handling of both
    specific paths, not an accident of platform exit-code semantics.
    """

    def test_malformed_stdin_fails_open(self, hook):
        """Non-UTF-8 stdin bytes must not crash the hook process with an
        unhandled UnicodeDecodeError traceback — run the REAL script via
        subprocess (not the in-process module) because the in-process test
        harness (io.StringIO) cannot reproduce a raw-bytes decode error the
        way a real piped stdin can."""
        result = subprocess.run(
            [sys.executable, str(_HOOK_PATH)],
            input=(
                b"\xff\xfe{\"tool_name\":\"Bash\",\"tool_input\":"
                b"{\"command\":\"kanban do x\"}}"
            ),
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"Expected exit 0 (fail open), got {result.returncode}. "
            f"stderr={result.stderr!r}"
        )
        assert b"Traceback" not in result.stderr, (
            f"Hook crashed with an unhandled exception instead of failing "
            f"open by design: {result.stderr!r}"
        )

    def test_non_dict_tool_input_fails_open(self, hook):
        """`tool_input` present but not a dict (e.g. a string) must not
        crash via AttributeError on `.get(...)` — fail open instead."""
        payload = json.dumps({"tool_name": "Bash", "tool_input": "not-a-dict"})
        result = run_hook_main(hook, payload)
        assert result is None, f"Expected allow (None), got: {result}"
