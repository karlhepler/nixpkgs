"""
Tests for the non-blocking non-discriminating-MoV pre-pass warning in kanban.py
(`warn_nondiscriminating_movs` / `_mov_prepass_run_criterion`).

Covers the check that flags any acceptance criterion whose full mov_commands
chain already exits 0 against the current tree, BEFORE any work has been
done — a criterion that structurally cannot fail is not a check at all. See
kanban.py's module comment immediately above `warn_nondiscriminating_movs`
for the incident history this guards against.

Covered:
- _mov_prepass_run_criterion: already-passing -> True, not-yet-passing ->
  False, no mov_commands (semantic criterion) -> None, malformed entry ->
  None, pre-pass timeout -> None (inconclusive, ignores the criterion's own
  declared per-command timeout), first-failing-command short-circuits without
  running later commands in the array.
- warn_nondiscriminating_movs: fires a warning naming the criterion when its
  MoV already passes; stays completely silent when it does not; never raises
  SystemExit (warn-only); fails open on an internal error (no warning, no
  crash); bulk-array input reports the correct card[idx].
- validate_and_build_card integration: card creation succeeds regardless of
  whether the warning fires — this check must never block.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

_KANBAN_PATH = Path(__file__).parent.parent / "kanban.py"


def load_kanban():
    """Import kanban.py as a module with watchdog stubbed out."""
    watchdog_stub = MagicMock()
    sys.modules.setdefault("watchdog", watchdog_stub)
    sys.modules.setdefault("watchdog.observers", watchdog_stub)
    sys.modules.setdefault("watchdog.events", watchdog_stub)
    watchdog_stub.events.FileSystemEventHandler = object

    spec = importlib.util.spec_from_file_location("kanban_mov_prepass", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_criterion(cmd, timeout=10, text="Check something"):
    """Build a minimal programmatic criterion dict with a single mov_commands entry."""
    return {
        "text": text,
        "mov_type": "programmatic",
        "mov_commands": [{"cmd": cmd, "timeout": timeout}],
        "met": False,
    }


def make_card(action="Do the thing", criteria=None):
    """Build a minimal card dict (as passed to warn_nondiscriminating_movs /
    validate_and_build_card).
    """
    if criteria is None:
        criteria = [make_criterion("true")]
    return {
        "action": action,
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-devex",
        "criteria": criteria,
    }


# ---------------------------------------------------------------------------
# Unit tests: _mov_prepass_run_criterion
# ---------------------------------------------------------------------------

class TestMovPrepassRunCriterion:
    def test_already_passing_command_returns_true(self, kanban, tmp_path):
        """FIRE-CASE FIXTURE: a criterion whose command already exits 0 against
        the current tree -> True. Perturbing this fixture's cmd to one that does
        NOT already pass (e.g. searching for a token absent from the file) must
        flip this assertion to False — see .scratchpad/movprepass-failure-demo.md.
        """
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        criterion = make_criterion("rg -q hello existing.txt")
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is True

    def test_not_yet_passing_command_returns_false(self, kanban, tmp_path):
        """SILENT-CASE FIXTURE: a criterion whose command does NOT yet pass
        against the current tree -> False. Perturbing this fixture's cmd to one
        that already passes (e.g. searching for a token present in the file)
        must flip this assertion to True — see
        .scratchpad/movprepass-failure-demo.md.
        """
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        criterion = make_criterion("rg -q nonexistent_token existing.txt")
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is False

    def test_no_mov_commands_returns_none(self, kanban, tmp_path):
        """A semantic criterion (no mov_commands) is inconclusive, not a finding."""
        criterion = {"text": "Semantic check", "mov_type": "semantic", "met": False}
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is None

    def test_empty_mov_commands_returns_none(self, kanban, tmp_path):
        criterion = {"text": "x", "mov_type": "semantic", "mov_commands": [], "met": False}
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is None

    def test_malformed_entry_returns_none(self, kanban, tmp_path):
        """A non-dict mov_commands entry is inconclusive, never crashes."""
        criterion = {"text": "x", "mov_commands": ["not-a-dict"], "met": False}
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is None

    def test_missing_cmd_returns_none(self, kanban, tmp_path):
        criterion = {"text": "x", "mov_commands": [{"timeout": 10}], "met": False}
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is None

    def test_prepass_timeout_returns_none_ignoring_declared_timeout(self, kanban, tmp_path, monkeypatch):
        """The pre-pass uses its own short hard cap (MOV_PREPASS_TIMEOUT_SECS),
        never the criterion's own declared per-command timeout — a slow command
        with a generous declared timeout (here 1800, the schema max) still times
        out at the short cap and is treated as inconclusive.
        """
        monkeypatch.setattr(kanban, "MOV_PREPASS_TIMEOUT_SECS", 0.05)
        criterion = make_criterion("sleep 2", timeout=1800)
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is None

    def test_first_failing_command_short_circuits(self, kanban, tmp_path):
        """Multiple commands in the array: the first failing command returns
        False immediately, mirroring cmd_criteria_check's short-circuit-on-
        first-failure semantics — later commands are never reached.
        """
        criterion = {
            "text": "x",
            "mov_commands": [
                {"cmd": "false", "timeout": 10},
                {"cmd": "true", "timeout": 10},
            ],
            "met": False,
        }
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is False

    def test_all_passing_commands_returns_true(self, kanban, tmp_path):
        criterion = {
            "text": "x",
            "mov_commands": [
                {"cmd": "true", "timeout": 10},
                {"cmd": "true", "timeout": 10},
            ],
            "met": False,
        }
        assert kanban._mov_prepass_run_criterion(criterion, str(tmp_path)) is True

    def test_destructive_command_is_not_executed(self, kanban, tmp_path):
        """SAFETY-CRITICAL: a command shape that WOULD mutate the working
        tree if executed must never actually run. Uses a harmless observable
        proxy (a marker file under tmp_path) instead of a real destructive
        command — the marker must never come into existence, and the
        criterion must resolve to None (inconclusive), never True/False.

        Each shape below has an ALLOWLISTED first token (rg/test) but is
        dangerous only because of what follows — this is exactly the trap
        the guard must defeat: checking only the first token is not enough,
        since shell=True hands the whole string to /bin/sh.
        """
        marker = tmp_path / "marker.txt"
        shapes = [
            f"rg -q x {tmp_path}; touch {marker}",
            f"rg -q x {tmp_path} && touch {marker}",
            f"rg -q x {tmp_path} | tee {marker}",
            f"test -f {tmp_path} > {marker}",
            f'rg -q "$(touch {marker})"',
            f"rg -q `touch {marker}`",
        ]
        for cmd in shapes:
            marker.unlink(missing_ok=True)
            criterion = make_criterion(cmd)
            result = kanban._mov_prepass_run_criterion(criterion, str(tmp_path))
            assert result is None, f"cmd should be refused (None), got {result!r}: {cmd!r}"
            assert not marker.exists(), f"destructive shape was actually executed: {cmd!r}"


# ---------------------------------------------------------------------------
# Unit tests: _mov_prepass_command_is_safe (the execution safety guard)
# ---------------------------------------------------------------------------

class TestMovPrepassCommandIsSafe:
    def test_admitted_exact_shapes_are_safe(self, kanban):
        """Only the small, exact-shape-verified set from the current design
        is admitted: test -f/-d/-e PATH, rg [-q/-i/-F combo] PATTERN PATH,
        and true/false (any arguments). See kanban.py's module comment above
        _mov_prepass_shape_is_exact for the full admitted/excluded list and
        rationale (card #3400, narrowing a first-token NAME allowlist down
        to exact verified shapes after .scratchpad/review-movguard-security.md
        found 6 confirmed bypasses in the prior design).
        """
        for cmd in [
            "rg -q hello file.txt",
            "rg -qi hello file.txt",
            "rg -qF hello file.txt",
            "rg -qiF hello file.txt",
            "test -f file.txt",
            "test -d some_dir",
            "test -e file.txt",
            "true",
            "false",
        ]:
            assert kanban._mov_prepass_command_is_safe(cmd) is True, cmd

    def test_formerly_allowlisted_commands_are_now_excluded(self, kanban):
        """cat/wc/ls/jq were admitted under the prior first-token-NAME
        allowlist (any argument, no per-tool check). The current exact-shape
        design excludes all four outright for minimalism (near-zero corpus
        usage — see the module comment) rather than re-verifying and
        re-admitting each one's flag surface.
        """
        for cmd in ["cat file.txt", "wc -l file.txt", "ls -la", "jq .foo file.json"]:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

    def test_semicolon_chain_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("rg -q x; rm -rf y") is False

    def test_double_ampersand_chain_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("rg -q x && rm -rf y") is False

    def test_pipe_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("rg -q x | tee y") is False

    def test_redirection_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("test -f x > y") is False

    def test_dollar_paren_substitution_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe('rg -q "$(rm -rf y)"') is False

    def test_backtick_substitution_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("rg -q `rm -rf y`") is False

    def test_non_allowlisted_first_token_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("mv a b") is False

    def test_sed_is_excluded_entirely_even_without_inplace_flag(self, kanban):
        """sed is excluded OUTRIGHT under the current design, not merely
        checked for -i: sed's own script language contains write/exec
        builtins (`w FILE`, `e COMMAND`) that a flag-level check cannot see.
        See review-movguard-security.md bypass #6 — `sed 'e touch pwned'
        file` and `sed -n 'w pwned.txt' file` both defeated the prior
        design's dedicated in-place-flag check while carrying no -i flag at
        all. No sed invocation is admitted any more, regardless of flags.
        """
        assert kanban._mov_prepass_command_is_safe("sed -n 1p file.txt") is False

    def test_sed_with_inplace_flag_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("sed -i s/a/b/ file.txt") is False

    def test_sed_with_combined_short_inplace_flag_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("sed -ni 1p file.txt") is False

    def test_sed_with_long_inplace_flag_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("sed --in-place=.bak s/a/b/ file.txt") is False

    def test_git_is_excluded_entirely_even_for_read_only_subcommands(self, kanban):
        """git is excluded OUTRIGHT under the current design, not merely
        checked for subcommand membership: the prior design's git subcommand
        allowlist checked ONLY the subcommand name, never the flags that
        followed it, which is exactly review-movguard-security.md bypass #4
        (`git diff|log|show --output=FILE` — an arbitrary file overwrite
        through a subcommand the prior guard already trusted). Enumerating a
        safe flag/positional matrix per subcommand was judged too complex to
        justify for this repo's near-zero git-MoV usage, so no git
        invocation is admitted any more, regardless of subcommand or flags.
        """
        for cmd in ["git diff --stat", "git log -1", "git show HEAD", "git status"]:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

    def test_git_commit_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("git commit -m x") is False

    def test_git_with_no_subcommand_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("git") is False

    def test_malformed_quoting_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("rg -q 'unterminated") is False

    def test_empty_command_is_unsafe(self, kanban):
        assert kanban._mov_prepass_command_is_safe("") is False

    # -----------------------------------------------------------------
    # Issue #56: the metachar veto must be quote-aware (skip
    # single-quoted spans) so a literal metacharacter sitting inside a
    # quoted PATTERN argument doesn't trip the same veto as a live
    # shell metacharacter — WITHOUT reopening the arbitrary-code-
    # execution / arbitrary-file-overwrite bypasses a naive
    # (non-escape-aware or reordered) fix would introduce. See
    # .scratchpad/issue-56-swe-security.md for the full adversarial
    # analysis behind every case below.
    # -----------------------------------------------------------------

    def test_quoted_metachar_in_pattern_is_admitted(self, kanban):
        """DISCRIMINATES: YES — pre-change, _MOV_PREPASS_SHELL_METACHARS'
        raw substring scan (kanban.py's `any(bad in cmd for bad in
        _MOV_PREPASS_SHELL_METACHARS)`, run before any tokenization) sees
        the `;` inside the single-quoted PATTERN argument and rejects the
        whole cmd, even though shlex would tokenize it as a single quoted
        argument and the exact-shape allowlist (`rg [-qiF]* PATTERN PATH`)
        would otherwise fully admit it. This is the card's own motivating
        example (issue #56).
        """
        assert kanban._mov_prepass_command_is_safe(
            "rg -qF 'stakes are real; default-idle' modules/kanban/kanban.py"
        ) is True

    def test_unspaced_pipe_is_unsafe(self, kanban):
        """Mirror-image coverage for test_pipe_is_unsafe: every existing
        metachar-rejection test in this class uses a SPACED metachar
        (`x | tee y`). A pipe glued with no surrounding whitespace
        (`x|touch y`) must be rejected identically — a quote-aware veto
        that only detects spaced metachars would let this glued form
        through, since shlex (used downstream by the exact-shape check)
        glues `x|touch` into a single ordinary-looking token with no
        whitespace for it to split on.
        """
        assert kanban._mov_prepass_command_is_safe("rg -q x|touch y") is False

    def test_unspaced_redirection_is_unsafe(self, kanban):
        """Mirror-image coverage for test_redirection_is_unsafe: a redirect
        glued with no surrounding whitespace (`x>y`) must be rejected
        identically to the spaced form (`x > y`) already pinned above.
        """
        assert kanban._mov_prepass_command_is_safe("test -f x>y") is False

    def test_backslash_escaped_quote_injection_is_rejected(self, kanban):
        """Attack 3 from the design review: a single backslash-escaped
        quote glued (no whitespace) to a zero-argument injected command,
        in both the `test` and `rg` admitted shapes. Outside a quote, `\\'`
        is an escaped literal quote character — it does NOT open a quoted
        span — so the `;` immediately following it is a LIVE shell command
        separator to the real shell. A scanner that (incorrectly) toggles
        quote state on every raw apostrophe, escaped or not, would treat
        the following `;` as hidden inside a phantom quoted span and admit
        this cmd; the escape-aware scanner must reject it instead.
        """
        assert kanban._mov_prepass_command_is_safe("test -f x\\';touch y") is False
        assert kanban._mov_prepass_command_is_safe("rg -q x\\';touch y") is False

    def test_backslash_escaped_quote_injection_is_never_executed(self, kanban, tmp_path):
        """SAFETY-CRITICAL, live check mirroring
        test_destructive_command_is_not_executed /
        test_all_six_bypass_shapes_are_never_actually_executed: a
        classifier-return-value assertion alone would not have caught the
        naive (non-escape-aware) scanner bypass found during design review
        — that naive scanner's parity confusion let `shape_is_exact` see a
        3-token `test -f PATH` shape (the injected command has zero
        arguments, so there is no extra whitespace for shlex to split on)
        and `_mov_prepass_command_is_safe` returned True, and the injected
        command actually ran under subprocess.run(shell=True, ...). Only a
        live marker-file check proves subprocess.run was never reached.
        """
        marker = tmp_path / "marker.txt"
        poke = tmp_path / "poke"
        poke.write_text(f"#!/bin/sh\ntouch {marker}\n")
        poke.chmod(0o755)
        cmd = f"test -f x\\';{poke}"
        marker.unlink(missing_ok=True)
        criterion = make_criterion(cmd)
        result = kanban._mov_prepass_run_criterion(criterion, str(tmp_path))
        assert result is None, f"cmd should be refused (None), got {result!r}: {cmd!r}"
        assert not marker.exists(), f"backslash-escaped-quote injection was actually executed: {cmd!r}"

    def test_apostrophe_embedding_idiom_is_not_falsely_rejected(self, kanban):
        """The standard POSIX `'a'\\''b'` idiom for embedding a literal
        apostrophe inside a single-quoted argument (quote-close,
        escaped-apostrophe, quote-reopen) contains no live metacharacter at
        all and must be admitted. An over-rejecting scanner that flags this
        common, legitimate quoting idiom as dangerous would cost nothing in
        security (Direction A is already the conservative side of the
        trade-off) but would erode trust in the warning for no benefit.
        """
        assert kanban._mov_prepass_command_is_safe(
            "rg -qF 'it'\\''s here' modules/kanban/kanban.py"
        ) is True

    def test_trailing_backslash_fails_closed_standalone(self, kanban):
        """Issue #59 / security-review finding L1: `_mov_prepass_has_live_metachar`
        must fail closed on its OWN, called directly, when a bare backslash
        is the FINAL character of `cmd` outside any quote — a dangling
        escape with no character left to escape. Pre-fix, the outside-quote
        backslash branch does `i += 2` unconditionally and walks `i` past
        the end of the string, so the scan loop exits having never detected
        the malformed escape or set `in_quote`, and the function falls
        through to `return False` ("no live metachar") even though the
        input is malformed.

        This asserts on `_mov_prepass_has_live_metachar` DIRECTLY, not on
        `_mov_prepass_command_is_safe`. A caller-level test is worthless
        here: `_mov_prepass_command_is_safe` already returns False for this
        exact input on the pre-fix code too, via its own downstream
        `shlex.split(cmd)` call raising `ValueError` on the same malformed
        trailing backslash (caught by `except ValueError: return False`) —
        so a caller-level assertion would pass identically before and after
        this fix and would gate nothing. Direct invocation is what makes
        this test discriminating: pre-fix the function returns False here
        and this assertion fails; post-fix it returns True and the
        assertion passes.
        """
        assert kanban._mov_prepass_has_live_metachar("rg -q x/some/path\\") is True


# ---------------------------------------------------------------------------
# Unit tests: the two narrowly-admitted compound idioms (issue #55) —
# `test $(rg -c 'P' PATH || echo 0) -ge N` and
# `sed -n '/A/,/B/p' PATH | rg [-qiF]* 'P'`. Both necessarily contain a
# banned metacharacter (`$(`, `|`) yet are structurally incapable of
# chaining an arbitrary command — see the module comment above
# _MOV_PREPASS_COUNT_THRESHOLD_RE / _MOV_PREPASS_SED_RANGE_PIPE_RG_RE.
# ---------------------------------------------------------------------------

class TestMovPrepassCompoundIdiomAdmission:
    def test_count_threshold_idiom_is_safe(self, kanban):
        # DISCRIMINATES: yes. Pre-change, the blanket metachar veto
        # (`_MOV_PREPASS_SHELL_METACHARS`, which bans `$(`) rejects every
        # cmd here outright before the exact-shape check ever runs — the
        # `assert ... is True` fails pre-change (verdict was False).
        for cmd in [
            "test $(rg -c 'alpha' existing.txt || echo 0) -ge 4",
            "test $(rg -c '^def test_|^    def test_' modules/kanban/tests/test_kanban_mov_prepass.py || echo 0) -ge 47",
            "test $(rg -c 'x' file.txt || echo 0) -eq 0",
            "test $(rg -c 'x' file.txt || echo 0) -gt 1",
        ]:
            assert kanban._mov_prepass_command_is_safe(cmd) is True, cmd

    def test_sed_range_piped_to_rg_idiom_is_safe(self, kanban):
        # DISCRIMINATES: yes. Pre-change, the blanket metachar veto (which
        # bans `|`) rejects every cmd here outright — the `assert ... is
        # True` fails pre-change (verdict was False).
        for cmd in [
            "sed -n '/^## Section A/,/^## Section B/p' existing.txt | rg -q 'alpha'",
            "sed -n '/^## Critical Anti-Patterns/,/^## Self-Improvement Protocol/p' file.md | rg -q 'Unit-contradiction'",
            "sed -n '/start/,/end/p' file.txt | rg -qi 'PATTERN'",
        ]:
            assert kanban._mov_prepass_command_is_safe(cmd) is True, cmd

    def test_count_threshold_idiom_rejects_injection_via_semicolon(self, kanban):
        """A `;` anywhere breaks the anchored end-to-end match and falls
        through to the strict metachar veto, regardless of where it's
        placed inside the idiom's structure.

        DISCRIMINATES: no. Every cmd here already contains a bare `;` as a
        substring, which the PRE-EXISTING, unchanged-by-this-diff blanket
        metachar veto (`_MOV_PREPASS_SHELL_METACHARS`) already rejects on
        its own, regardless of the two new regexes existing at all. This
        test passes identically before and after this diff — it guards
        against a future loosening of the new regexes' own `;` exclusion,
        it does not gate this diff's fix.
        """
        for cmd in [
            "test $(rg -c 'x' file; touch pwned || echo 0) -ge 1",
            "test $(rg -c 'x' file || echo 0; touch pwned) -ge 1",
            "test $(rg -c 'x' file || echo 0) -ge 1; touch pwned",
        ]:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

    def test_count_threshold_idiom_rejects_dangerous_path_or_flags(self, kanban):
        # DISCRIMINATES: no. Both cmds still contain `$(` as a substring
        # (the new regex just fails to match this exact shape and falls
        # through to the same pre-existing metachar veto that already
        # caught `$(` before this diff existed). Passes identically before
        # and after — guards the new regex's own precision, not this fix.
        for cmd in [
            "test $(rg -c 'x' --pre=evil.sh file || echo 0) -ge 1",
            "test $(rg -c 'x' -pre file || echo 0) -ge 1",
        ]:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

    def test_sed_range_idiom_rejects_write_and_exec_script_commands(self, kanban):
        """The sed-DSL bypasses (`w`/`e` script commands, extra `;`-chained
        commands) must still be rejected even when embedded inside an
        otherwise idiom-shaped quoted argument — the shell's own quote
        parsing does not protect against sed's OWN script language.

        DISCRIMINATES: no. Every cmd here contains `|` (piped to rg) as a
        substring, already rejected by the pre-existing metachar veto
        regardless of the new sed-range regex's own content restrictions.
        Passes identically before and after this diff — guards the new
        regex's own precision, not this fix.
        """
        for cmd in [
            "sed -n 'w pwned.txt' file.txt | rg -q x",
            "sed -n '/a/,/b/p;w pwned.txt' file.txt | rg -q x",
            "sed -n '/a;touch pwned/,/b/p' file.txt | rg -q x",
            "sed -n '/a/,/b/p' file.txt | rg --pre evil.sh -q x",
            "sed -n 1p file.txt | rg -q x",
        ]:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

    def test_compound_idiom_shapes_are_never_actually_destructive(self, kanban, tmp_path):
        """Live check mirroring test_all_six_bypass_shapes_are_never_actually_executed:
        run rejected variants of both idioms through _mov_prepass_run_criterion
        and confirm a marker file never comes into existence.

        DISCRIMINATES: no. Both injected shapes contain `;`/`|`, already
        refused (verdict None, nothing executed) by the pre-existing
        metachar veto before this diff existed. Passes identically before
        and after — it is a live-execution safety pin for the new regexes,
        not a test that gates this diff's under-report fix.
        """
        marker = tmp_path / "marker.txt"
        shapes = [
            f"test $(rg -c 'x' {tmp_path} || echo 0; touch {marker}) -ge 1",
            f"sed -n '/a/,/b/p;touch {marker}' {tmp_path} | rg -q x",
        ]
        for cmd in shapes:
            marker.unlink(missing_ok=True)
            criterion = make_criterion(cmd)
            result = kanban._mov_prepass_run_criterion(criterion, str(tmp_path))
            assert result is None, f"cmd should be refused (None), got {result!r}: {cmd!r}"
            assert not marker.exists(), f"injected shape was actually executed: {cmd!r}"

    def test_count_threshold_idiom_rejects_glob_in_path(self, kanban):
        """Security review (issue55-review-security.md, Attack class 4,
        BLOCKING): `_MOV_PREPASS_PATH_TOKEN` originally excluded only
        whitespace/quotes/`$;|&<>`` — not shell glob/brace/tilde/paren/hash
        metacharacters. An unquoted PATH token containing `*` is expanded
        by the shell BEFORE rg ever sees it; a file named `--pre=<cmd>` in
        the working directory then becomes rg's own `--pre` flag, achieving
        arbitrary command execution with zero shell metacharacters in the
        authored MoV string. Confirmed live in the security review via
        `.scratchpad/3621-probe-glob-pre.py` (mtime change on a planted
        file). This test pins that every character able to trigger a word
        expansion is excluded from the PATH token.

        DISCRIMINATES: yes, against the pre-fix-for-this-card character
        class. Before this card's fix, `_MOV_PREPASS_PATH_TOKEN =
        r"(?!-)[^\\s'\"$;|&<>`]+"` admits a bare `*` (and `?`, `[`, `]`,
        `{`, `}`, `~`, `(`, `)`, `#`) as ordinary path characters, so
        `test $(rg -c 'x' * || echo 0) -ge 1` matches
        `_MOV_PREPASS_COUNT_THRESHOLD_RE` and `_mov_prepass_command_is_safe`
        returns True. After this card's fix, the PATH token excludes all of
        those characters, so the same string no longer matches either new
        regex and falls through to the general metachar veto (which does
        not contain `*` etc. either, so it falls through further to
        `_mov_prepass_shape_is_exact`, which also rejects it — the overall
        verdict is False either way, but the fix changes WHICH gate FIRST
        refuses it, closing the specific glob-expansion admission path).
        """
        for cmd in [
            "test $(rg -c 'x' * || echo 0) -ge 1",
            "test $(rg -c 'x' fo?o || echo 0) -ge 1",
            "test $(rg -c 'x' fo[o]o || echo 0) -ge 1",
            "test $(rg -c 'x' fo{a,b}o || echo 0) -ge 1",
            "test $(rg -c 'x' ~/foo || echo 0) -ge 1",
            "test $(rg -c 'x' fo(o)o || echo 0) -ge 1",
            "test $(rg -c 'x' fo#o || echo 0) -ge 1",
        ]:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

    def test_sed_range_idiom_rejects_glob_in_path(self, kanban):
        """Same defect as test_count_threshold_idiom_rejects_glob_in_path,
        reached through `_MOV_PREPASS_SED_RANGE_PIPE_RG_RE`'s PATH token —
        the identical `_MOV_PREPASS_PATH_TOKEN` object, reused verbatim, so
        the security review's finding applies here too (flagged in the
        review as "not separately re-proven live... but flagging it as an
        equally live second instance of the same defect").

        DISCRIMINATES: yes, against the pre-fix-for-this-card character
        class, for the identical reason as the count-threshold sibling
        test above — `_MOV_PREPASS_PATH_TOKEN` is the shared object
        imported into both regexes, so the same fix (or the same
        pre-fix gap) applies to both call sites identically.
        """
        for cmd in [
            "sed -n '/A/,/B/p' * | rg -q 'x'",
            "sed -n '/A/,/B/p' fo?o | rg -q 'x'",
            "sed -n '/A/,/B/p' fo[o]o | rg -q 'x'",
            "sed -n '/A/,/B/p' fo{a,b}o | rg -q 'x'",
            "sed -n '/A/,/B/p' ~/foo | rg -q 'x'",
            "sed -n '/A/,/B/p' fo(o)o | rg -q 'x'",
            "sed -n '/A/,/B/p' fo#o | rg -q 'x'",
        ]:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

    def test_count_threshold_idiom_rejects_backslash_escaped_dash(self, kanban):
        """Re-verification (issue55-reverify-security.md § Q2, BLOCKING):
        excluding glob/brace/tilde/paren/hash characters (the prior fix,
        pinned above) closed pathname expansion but left backslash removal
        open. In an unquoted shell word, a backslash is the escape
        character: the shell strips it and takes the next character
        literally, including a `-`. `\\-\\-pre=touch` starts with `\\`, not
        `-`, so it passes the `(?!-)` lookahead; every character in it
        (`\\`, `-`, `p`, `r`, `e`, `=`, `t`, `o`, `u`, `c`, `h`) was outside
        the prior exclusion set, so the whole token matched. The shell then
        strips both backslashes and hands `rg` the literal argument
        `--pre=touch` — ripgrep's own preprocessor flag — achieving
        arbitrary command execution with no adversarial file needed
        anywhere (confirmed live via mtime change on a planted file,
        `.scratchpad/3624-probe-backslash-detail.py`). This test pins that
        the fix (a permitted-character allowlist, not another excluded
        character) rejects it structurally.

        Also asserts the single-backslash control (`\\-pre=touch`, which
        the shell reduces to `-pre=touch`, a short-flag cluster `rg`'s own
        arg parser rejects on its own) is rejected too, and that a
        representative legitimate path is still admitted — so an
        over-narrow allowlist would fail this test rather than silently
        rejecting real MoVs.

        DISCRIMINATES: yes, against the pre-this-card character class,
        `_MOV_PREPASS_PATH_TOKEN = r"(?!-)[^\\s'\"$;|&<>`*?\\[\\]{}~()#]+"`
        (the version this card's own predecessor shipped, closing only the
        glob-expansion vector). That negated class does not list `\\`
        among its excluded characters, so `\\-\\-pre=touch` matches it in
        full and `_MOV_PREPASS_COUNT_THRESHOLD_RE` — built from that same
        token — matches the whole cmd string, making
        `_mov_prepass_command_is_safe` return True. After this card's fix,
        `_MOV_PREPASS_PATH_TOKEN` is a positive allowlist of ASCII
        letters/digits/`/`/`.`/`-`/`_` only; `\\` is not a member, so the
        token fails to match at the very first character and the whole
        regex fails, correctly returning False.
        """
        bypass_cmds = [
            r"test $(rg -c 'x' \-\-pre=touch || echo 0) -ge 1",
            r"test $(rg -c 'x' \-pre=touch || echo 0) -ge 1",
        ]
        for cmd in bypass_cmds:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

        legitimate = (
            "test $(rg -c 'x' modules/kanban/tests/test_kanban_mov_prepass.py"
            " || echo 0) -ge 1"
        )
        assert kanban._mov_prepass_command_is_safe(legitimate) is True, legitimate

    def test_sed_range_idiom_rejects_backslash_escaped_dash(self, kanban):
        """Same defect as test_count_threshold_idiom_rejects_backslash_escaped_dash,
        reached through `_MOV_PREPASS_SED_RANGE_PIPE_RG_RE`'s PATH token —
        the identical `_MOV_PREPASS_PATH_TOKEN` object, reused verbatim, so
        the re-verification's finding applies here too.

        DISCRIMINATES: yes, against the pre-this-card character class, for
        the identical reason as the count-threshold sibling test above —
        `_MOV_PREPASS_PATH_TOKEN` is the shared object imported into both
        regexes, so the same fix (or the same pre-fix gap) applies to both
        call sites identically.
        """
        bypass_cmds = [
            "sed -n '/A/,/B/p' \\-\\-pre=touch | rg -q 'x'",
            "sed -n '/A/,/B/p' \\-pre=touch | rg -q 'x'",
        ]
        for cmd in bypass_cmds:
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd

        legitimate = (
            "sed -n '/A/,/B/p' modules/kanban/tests/test_kanban_mov_prepass.py"
            " | rg -q 'x'"
        )
        assert kanban._mov_prepass_command_is_safe(legitimate) is True, legitimate

    def test_quoted_spans_reject_embedded_newline(self, kanban):
        """Security review (issue55-review-security.md, Attack class 3,
        MEDIUM): a negated Python character class matches a literal
        newline unless `\\n` is explicitly excluded. Before this card's
        fix, neither the sed-address char class nor the rg-PATTERN char
        class excluded `\\n`/`\\r`, so a `cmd` carrying a raw embedded
        newline inside a quoted span could match at step 0 and return True
        BEFORE the general metachar veto (which does ban `"\\n"`,
        `_MOV_PREPASS_SHELL_METACHARS`) ever ran. The review confirmed this
        was inert today only by incidental downstream behavior (a newline
        is shell-literal inside single quotes; sed's own address parser
        happens to reject one) — not by the regex's own design. This test
        pins the fix so the guarantee holds by construction, not by
        accident.

        DISCRIMINATES: yes, against the pre-fix-for-this-card character
        classes. Before this card's fix, `[^']*` (rg PATTERN, both regexes)
        and `[^'/;$\\`|&<>]+` (sed address, both instances) each admit a
        literal embedded newline, so all three cmds below match their
        respective regex and `_mov_prepass_command_is_safe` returns True.
        After this card's fix, `\\n`/`\\r` are excluded from every one of
        those classes, so none of the three cmds match either new regex —
        each then falls through to the general metachar veto, which
        explicitly bans `"\\n"` and correctly returns False.
        """
        count_threshold_with_nl = "test $(rg -c 'x\ny' file.txt || echo 0) -ge 1"
        sed_address_with_nl = "sed -n '/A\n/,/B/p' file.txt | rg -q 'x'"
        sed_pattern_with_nl = "sed -n '/A/,/B/p' file.txt | rg -q 'x\ny'"
        for cmd in (count_threshold_with_nl, sed_address_with_nl, sed_pattern_with_nl):
            assert kanban._mov_prepass_command_is_safe(cmd) is False, cmd


# ---------------------------------------------------------------------------
# Unit tests: the 6 confirmed allowlist-scope bypasses from
# .scratchpad/review-movguard-security.md § Bypass analysis, all classified
# `safe=True` under the prior first-token-NAME allowlist despite executing
# code or overwriting a file. Each was confirmed live against
# _mov_prepass_command_is_safe (the pure classifier, nothing executed) by
# the review, and each is a single command, first-token allowlisted,
# containing ZERO banned shell metacharacters — the metachar scan alone
# could never catch these. This class is the review's HIGH finding closed:
# the prior 38-test suite gave 38/38 green while all 6 were live, because
# none of the 38 tests constructed any of these shapes.
# ---------------------------------------------------------------------------

class TestMovPrepassBypassRejection:
    def test_awk_system_call_is_rejected(self, kanban):
        """Bypass #1: awk's own system() builtin — arbitrary code execution.
        No banned metacharacter; the whole hazard is inside awk's own
        program-language argument, which the current design excludes awk
        for entirely (see module comment: script languages aren't guardable
        by a flag check).
        """
        assert kanban._mov_prepass_command_is_safe(
            'awk \'BEGIN{system("touch pwned")}\''
        ) is False

    def test_rg_pre_flag_is_rejected(self, kanban):
        """Bypass #2: ripgrep's own --pre=COMMAND preprocessor — arbitrary
        code execution. rg is admitted, but only for the -q/-i/-F flag
        combination; --pre is a long-form flag outside the admitted set and
        is rejected by _mov_prepass_rg_flag_token_is_safe / the exact-shape
        check in _mov_prepass_shape_is_exact.
        """
        assert kanban._mov_prepass_command_is_safe(
            "rg --pre /tmp/evil.sh -q x file.txt"
        ) is False

    def test_sed_e_command_is_rejected(self, kanban):
        """Bypass #3 (part of #6 in the review's numbering): sed's own `e`
        script command — arbitrary code execution, carrying no -i flag at
        all, defeating the prior design's dedicated in-place check. sed is
        now excluded outright.
        """
        assert kanban._mov_prepass_command_is_safe("sed 'e touch pwned' file.txt") is False

    def test_sed_w_command_is_rejected(self, kanban):
        """Bypass #4 (other half of review bypass #6): sed's own `w FILE`
        script command — arbitrary file write, also carrying no -i flag.
        sed is now excluded outright.
        """
        assert kanban._mov_prepass_command_is_safe("sed -n 'w pwned.txt' file.txt") is False

    def test_sort_output_flag_is_rejected(self, kanban):
        """Bypass #5: sort's own -o/--output=FILE flag — arbitrary file
        overwrite. sort is now excluded outright (zero corpus usage to
        justify a flag-level carve-out).
        """
        assert kanban._mov_prepass_command_is_safe("sort -o /etc/passwd /dev/null") is False
        assert kanban._mov_prepass_command_is_safe("sort --output=/etc/passwd /dev/null") is False

    def test_yq_inplace_flag_is_rejected(self, kanban):
        """Bypass #6a: yq's own -i/--inplace flag — arbitrary file write,
        the exact hazard class sed's in-place check existed for, but on a
        sibling tool with no equivalent guard. yq is now excluded outright.
        """
        assert kanban._mov_prepass_command_is_safe('yq -i ".foo=1" file.yml') is False
        assert kanban._mov_prepass_command_is_safe('yq --inplace ".foo=1" file.yml') is False

    def test_git_output_flag_is_rejected(self, kanban):
        """Bypass #6b: git diff/log/show's own --output=FILE flag —
        arbitrary file overwrite through a subcommand the prior design
        already trusted (subcommand-allowlisted, flags never checked). git
        is now excluded outright, for every subcommand.
        """
        assert kanban._mov_prepass_command_is_safe("git diff --output=/tmp/pwned") is False
        assert kanban._mov_prepass_command_is_safe("git log --output=/tmp/pwned") is False
        assert kanban._mov_prepass_command_is_safe("git show --output=/tmp/pwned") is False

    def test_all_six_bypass_shapes_are_never_actually_executed(self, kanban, tmp_path):
        """SAFETY-CRITICAL, live check: run each of the 6 confirmed bypass
        shapes through _mov_prepass_run_criterion (the function that
        actually calls subprocess.run) and assert a harmless observable
        proxy (a marker file) never comes into existence. Mirrors
        test_destructive_command_is_not_executed's marker-file technique —
        no destructive command is ever really run; the shapes below use
        `touch`/`w`/`-o`/`--output=` against a marker path exactly like the
        review's confirmed bypasses, but the assertion is that the guard
        refuses them (result is None) before subprocess.run ever sees them.
        """
        marker = tmp_path / "marker.txt"
        shapes = [
            f'awk \'BEGIN{{system("touch {marker}")}}\'',
            f"rg --pre {tmp_path}/evil.sh -q x {tmp_path}",
            f"sed 'e touch {marker}' {tmp_path}",
            f"sed -n 'w {marker}' {tmp_path}",
            f"sort -o {marker} /dev/null",
            f"git diff --output={marker}",
        ]
        for cmd in shapes:
            marker.unlink(missing_ok=True)
            criterion = make_criterion(cmd)
            result = kanban._mov_prepass_run_criterion(criterion, str(tmp_path))
            assert result is None, f"bypass shape should be refused (None), got {result!r}: {cmd!r}"
            assert not marker.exists(), f"confirmed bypass shape was actually executed: {cmd!r}"


# ---------------------------------------------------------------------------
# Unit tests: warn_nondiscriminating_movs
# ---------------------------------------------------------------------------

class TestWarnNondiscriminatingMovs:
    def test_already_passing_criterion_produces_warning(self, kanban, tmp_path, monkeypatch, capsys):
        """FIRE CASE: a criterion whose MoV already passes against the current
        tree produces the warning, naming the criterion's text.
        """
        monkeypatch.chdir(tmp_path)
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        card = make_card(criteria=[make_criterion("rg -q hello existing.txt", text="Fire case AC")])

        kanban.warn_nondiscriminating_movs(card)

        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "already pass" in captured.err
        assert "Fire case AC" in captured.err

    def test_not_yet_passing_criterion_produces_no_warning(self, kanban, tmp_path, monkeypatch, capsys):
        """SILENT CASE: a criterion whose MoV does NOT yet pass produces no
        warning at all — the normal, healthy case for a not-yet-done criterion.
        """
        monkeypatch.chdir(tmp_path)
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        card = make_card(criteria=[make_criterion("rg -q nonexistent_token existing.txt", text="Silent case AC")])

        kanban.warn_nondiscriminating_movs(card)

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_warn_only_never_raises_systemexit(self, kanban, tmp_path, monkeypatch):
        """warn_nondiscriminating_movs never blocks — no SystemExit, ever."""
        monkeypatch.chdir(tmp_path)
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        card = make_card(criteria=[make_criterion("rg -q hello existing.txt")])
        try:
            kanban.warn_nondiscriminating_movs(card)
        except SystemExit as e:
            pytest.fail(f"warn_nondiscriminating_movs raised SystemExit({e.code}) — must be warn-only")

    def test_internal_error_fails_open_no_warning(self, kanban, capsys):
        """An internal error while running the pre-pass (e.g. an unexpected
        exception inside the per-criterion runner) is swallowed — no warning
        is printed and no exception escapes. Mirrors
        warn_unmatched_card_identifiers' fail-open contract.
        """
        card = make_card(criteria=[make_criterion("true")])
        with patch.object(kanban, "_mov_prepass_run_criterion", side_effect=RuntimeError("boom")):
            try:
                kanban.warn_nondiscriminating_movs(card)
            except Exception as e:
                pytest.fail(f"warn_nondiscriminating_movs raised {e!r} — must fail open")

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_bulk_array_reports_correct_card_index(self, kanban, tmp_path, monkeypatch, capsys):
        """Bulk array input: a fire-case criterion in card[1] is reported with
        that index, while card[0] (silent case) produces nothing.
        """
        monkeypatch.chdir(tmp_path)
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        cards = [
            make_card(
                action="Card A: not yet done",
                criteria=[make_criterion("rg -q nonexistent_token existing.txt")],
            ),
            make_card(
                action="Card B: already passes",
                criteria=[make_criterion("rg -q hello existing.txt", text="Fire in card B")],
            ),
        ]

        kanban.warn_nondiscriminating_movs(cards)

        captured = capsys.readouterr()
        assert "card[1]" in captured.err
        assert "Fire in card B" in captured.err
        assert "card[0]" not in captured.err

    def test_non_card_input_is_noop(self, kanban, capsys):
        """Anything that isn't a dict or list of dicts is ignored silently."""
        kanban.warn_nondiscriminating_movs("not a card")
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_semantic_criterion_produces_no_warning(self, kanban, tmp_path, monkeypatch, capsys):
        """A semantic criterion (no mov_commands) can never be a "finding" —
        there's nothing to pre-run.
        """
        monkeypatch.chdir(tmp_path)
        card = make_card(criteria=[{"text": "Semantic check", "mov_type": "semantic", "met": False}])
        kanban.warn_nondiscriminating_movs(card)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_allowlisted_readonly_command_still_fires_warning(self, kanban, tmp_path, monkeypatch, capsys):
        """The execution safety guard must not be so tight that the pre-pass
        never fires for a genuinely allowlisted, already-passing command — a
        guard that refuses everything would silently delete this feature's
        value. Uses `test -f`, a different allowlisted command from the
        other fire-case tests (which use `rg`), to prove the guard's
        allowlist is not accidentally rg-only.
        """
        monkeypatch.chdir(tmp_path)
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        card = make_card(criteria=[make_criterion(f"test -f {fixture}", text="Allowlisted fire case")])

        kanban.warn_nondiscriminating_movs(card)

        captured = capsys.readouterr()
        assert "already pass" in captured.err
        assert "Allowlisted fire case" in captured.err

    def test_warn_nondiscriminating_movs_reports_every_passing_criterion(
        self, kanban, tmp_path, monkeypatch, capsys
    ):
        """Issue #55 regression: the warning must enumerate EVERY criterion
        whose full mov_commands chain already exits 0 — not a strict subset
        of them. Constructs three passing criteria using three different
        mov_commands shapes actually seen in this repo's own card corpus: a
        plain `rg -q`, the `test $(rg -c ... || echo 0) -ge N`
        count-threshold idiom, and the `sed -n '/A/,/B/p' | rg -q` range
        idiom. Under the pre-fix code, the metachar veto in
        _mov_prepass_command_is_safe rejected the last two outright
        (because they contain `$(` / `|`), so _mov_prepass_run_criterion
        returned None (inconclusive) for them regardless of the fact both
        actually exit 0 — they would silently never reach `already_passing`
        and never be named, even though this test's fixture makes all three
        genuinely already-passing. Asserting all three names are present
        (not just that the warning fired) is what makes this test capable
        of catching that under-report; a test that only checked "some
        warning happened" would pass identically before and after the fix.
        """
        monkeypatch.chdir(tmp_path)
        fixture = tmp_path / "existing.txt"
        fixture.write_text(
            "## Section A\n"
            "alpha\n"
            "alpha\n"
            "alpha\n"
            "alpha\n"
            "## Section B\n"
        )
        card = make_card(
            criteria=[
                make_criterion("rg -q alpha existing.txt", text="Plain rg AC"),
                make_criterion(
                    "test $(rg -c 'alpha' existing.txt || echo 0) -ge 4",
                    text="Count threshold AC",
                ),
                make_criterion(
                    "sed -n '/^## Section A/,/^## Section B/p' existing.txt | rg -q 'alpha'",
                    text="Sed range AC",
                ),
            ]
        )

        kanban.warn_nondiscriminating_movs(card)

        captured = capsys.readouterr()
        assert "3 acceptance criterion(s)" in captured.err
        assert "Plain rg AC" in captured.err
        assert "Count threshold AC" in captured.err
        assert "Sed range AC" in captured.err


# ---------------------------------------------------------------------------
# Integration tests: validate_and_build_card (card creation never blocks)
# ---------------------------------------------------------------------------

class TestValidateAndBuildCardIntegration:
    def test_card_creation_succeeds_when_mov_already_passes(self, kanban, tmp_path, monkeypatch, capsys):
        """Card creation succeeds (and the warning fires) when a criterion's
        MoV already passes with zero changes — warn, never block.
        """
        monkeypatch.chdir(tmp_path)
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        data = make_card(criteria=[make_criterion("rg -q hello existing.txt")])

        try:
            built_card = kanban.validate_and_build_card(data, session="test-session")
        except SystemExit as e:
            pytest.fail(
                f"Card with already-passing MoV raised SystemExit({e.code}) — "
                f"non-discriminating-MoV check must warn, not block"
            )

        assert built_card["action"] == data["action"]
        captured = capsys.readouterr()
        assert "already pass" in captured.err

    def test_card_creation_succeeds_when_mov_not_yet_passing(self, kanban, tmp_path, monkeypatch, capsys):
        """Card creation succeeds normally (no warning) for the healthy,
        not-yet-done case.
        """
        monkeypatch.chdir(tmp_path)
        fixture = tmp_path / "existing.txt"
        fixture.write_text("hello world\n")
        data = make_card(criteria=[make_criterion("rg -q nonexistent_token existing.txt")])

        try:
            built_card = kanban.validate_and_build_card(data, session="test-session")
        except SystemExit as e:
            pytest.fail(f"Card with not-yet-passing MoV raised SystemExit({e.code})")

        assert built_card["action"] == data["action"]
        captured = capsys.readouterr()
        assert "already pass" not in captured.err

    def test_card_creation_succeeds_when_prepass_errors_internally(self, kanban, tmp_path, monkeypatch, capsys):
        """Card creation succeeds even when the pre-pass itself hits an
        internal error — fail open, never fail the card.
        """
        monkeypatch.chdir(tmp_path)
        data = make_card(criteria=[make_criterion("true")])

        with patch.object(kanban, "_mov_prepass_run_criterion", side_effect=RuntimeError("boom")):
            try:
                built_card = kanban.validate_and_build_card(data, session="test-session")
            except SystemExit as e:
                pytest.fail(f"Card creation raised SystemExit({e.code}) on internal prepass error")

        assert built_card["action"] == data["action"]
        captured = capsys.readouterr()
        assert "already pass" not in captured.err
