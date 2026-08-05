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
