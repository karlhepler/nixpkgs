"""
Tests for validate_mov_commands_content in kanban.py.

Covers the banned-pattern validation that runs at card-creation time on BOTH
the inline-JSON path and the --file path for `kanban do` and `kanban todo`.

Covered patterns:
- backslash-pipe (\\|) in rg/grep cmd → rejected
- rg -E flag (capital E = encoding, not extended regex) → rejected
- test $(rg -c ...) -le 0 absence-via-count idiom → rejected
- git commit -n hook-skip short flag → rejected
- --no-verify hook-skip flag → rejected
- HUSKY=0 hook-skip env var → rejected
- clean card (no banned patterns) → accepted
- Multiple violations across multiple ACs → all reported
- inline-JSON code path: subprocess-based integration via `kanban do` / `kanban todo`
- --file code path: subprocess-based integration via `kanban do --file`

Also covers warn_unmatched_card_identifiers (identifier-existence warning):
- real nonexistent identifier from the historical incident → flagged
- real existing identifier (_validate_bash_destructive_git) → NOT flagged
- unmatched identifier still allows card creation to succeed (warn, not block)
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
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

    spec = importlib.util.spec_from_file_location("kanban_mov_validation", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_criterion(cmd="rg -q X", timeout=10):
    """Build a minimal programmatic criterion dict."""
    return {
        "text": "Check something",
        "mov_type": "programmatic",
        "mov_commands": [{"cmd": cmd, "timeout": timeout}],
        "met": False,
    }


def make_card(action="Do the thing", criteria=None):
    """Build a minimal card dict (as passed to validate_mov_commands_content)."""
    if criteria is None:
        criteria = [make_criterion()]
    return {
        "action": action,
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-devex",
        "criteria": criteria,
    }


def make_kanban_root(tmp_path):
    """Create minimal kanban board directory structure."""
    for col in ("todo", "doing", "done", "canceled"):
        (tmp_path / col).mkdir(parents=True, exist_ok=True)
    return tmp_path


def make_args(kanban_mod, json_data: str, root: str, session: str = "test-session"):
    """Build a mock args object for cmd_do / cmd_todo with inline JSON."""
    args = MagicMock()
    args.root = root
    args.session = session
    args.json_data = json_data
    args.json_file = None
    return args


def _find_kanban_python() -> str:
    """
    Return the Python interpreter that has watchdog bundled (needed to run kanban.py
    as a subprocess).

    Strategy: read the shebang of the deployed kanban binary (via ~/.nix-profile/bin/kanban
    or the wrapped binary it points to). Falls back to sys.executable if not found.
    """
    import re as _re

    # ~/.nix-profile/bin/kanban is a bash wrapper that exec's the real binary.
    # Parse it to find the .kanban-wrapped path, then read that file's shebang.
    nix_profile_kanban = Path.home() / ".nix-profile" / "bin" / "kanban"
    try:
        wrapper_text = nix_profile_kanban.read_text(encoding="utf-8")
        # The bash wrapper contains: exec -a "$0" "/nix/store/.../bin/.kanban-wrapped"
        m = _re.search(r'exec -a "\$0" "([^"]+)"', wrapper_text)
        if m:
            wrapped = Path(m.group(1))
            shebang_line = wrapped.read_text(encoding="utf-8").splitlines()[0]
            if shebang_line.startswith("#!"):
                python = shebang_line[2:].strip().split()[0]
                if Path(python).exists():
                    return python
    except OSError:
        pass

    # Fallback: read shebang from any kanban binary in the nix store that this
    # test's source file is part of.
    try:
        for candidate in sorted(Path("/nix/store").glob("*/bin/kanban")):
            try:
                first_line = candidate.read_text(encoding="utf-8").splitlines()[0]
            except OSError:
                continue
            if first_line.startswith("#!") and "python" in first_line:
                python = first_line[2:].strip().split()[0]
                if Path(python).exists():
                    return python
    except OSError:
        pass

    return sys.executable


_KANBAN_PYTHON = _find_kanban_python()


def run_kanban_subprocess(args_list: list, input_data: str | None = None, cwd: str | None = None):
    """Run kanban CLI as a subprocess using the Python that has watchdog bundled."""
    cmd = [_KANBAN_PYTHON, str(_KANBAN_PATH)] + args_list
    result = subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Unit tests: validate_mov_commands_content (function-level)
# ---------------------------------------------------------------------------

class TestValidateMovCommandsContentUnit:
    """Direct unit tests for validate_mov_commands_content."""

    def test_clean_card_passes(self, kanban):
        """Card with no banned patterns in mov_commands passes without error."""
        card = make_card(criteria=[make_criterion(cmd="rg -q X")])
        # Should return normally (no SystemExit)
        try:
            kanban.validate_mov_commands_content(card)
        except SystemExit as e:
            pytest.fail(f"Clean card raised SystemExit({e.code})")

    def test_backslash_pipe_in_rg_cmd_rejected(self, kanban, capsys):
        """rg cmd with \\| (backslash-pipe) is rejected with exit 1."""
        card = make_card(criteria=[make_criterion(cmd=r"rg -q 'foo\|bar' file")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "backslash-pipe" in captured.err.lower()

    def test_rg_encoding_flag_rejected(self, kanban, capsys):
        """rg -E flag (capital E = encoding) is rejected with exit 1."""
        card = make_card(criteria=[make_criterion(cmd="rg -qiE 'pattern' file")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "rg -E" in captured.err or "-E" in captured.err

    def test_rg_count_absence_idiom_rejected(self, kanban, capsys):
        """test $(rg -c ...) -le 0 absence idiom is rejected with exit 1."""
        card = make_card(criteria=[make_criterion(cmd="test $(rg -c 'pattern' file) -le 0")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "absence" in captured.err.lower() or "rg -c" in captured.err

    def test_no_verify_hook_skip_rejected(self, kanban, capsys):
        """--no-verify hook-skip flag is rejected with exit 1."""
        card = make_card(criteria=[make_criterion(cmd="git commit --no-verify -m 'msg'")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "no-verify" in captured.err.lower() or "--no-verify" in captured.err

    def test_multiple_violations_all_reported(self, kanban, capsys):
        """Multiple violations across multiple ACs are all reported before exit."""
        card = make_card(criteria=[
            make_criterion(cmd=r"rg -q 'foo\|bar' file"),      # backslash-pipe
            make_criterion(cmd="rg -qiE 'pattern' file"),       # rg -E
            make_criterion(cmd="test $(rg -c 'x' f) -le 0"),   # absence idiom
        ])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        # Error output should reference at least two of the three criteria
        criteria_refs = sum(1 for i in range(3) if f"criteria[{i}]" in captured.err)
        assert criteria_refs >= 2, (
            f"Expected references to multiple criteria in error output, got:\n{captured.err}"
        )

    def test_array_of_cards_all_violations_reported(self, kanban, capsys):
        """Array input (bulk create): violations across all cards are reported."""
        cards = [
            make_card(action="Card A", criteria=[
                make_criterion(cmd=r"rg -q 'foo\|bar' file"),  # violation
            ]),
            make_card(action="Card B", criteria=[
                make_criterion(cmd="rg -q X"),  # clean
            ]),
            make_card(action="Card C", criteria=[
                make_criterion(cmd="rg -qiE 'pat' file"),  # violation
            ]),
        ]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(cards)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "card[0]" in captured.err
        assert "card[2]" in captured.err

    def test_semantic_criterion_skipped(self, kanban):
        """Semantic criteria (no mov_commands) are not checked for banned patterns."""
        card = make_card(criteria=[
            {
                "text": "Semantic check",
                "mov_type": "semantic",
                "met": False,
            }
        ])
        try:
            kanban.validate_mov_commands_content(card)
        except SystemExit as e:
            pytest.fail(f"Semantic criterion raised SystemExit({e.code})")

    def test_git_commit_n_hook_skip_rejected(self, kanban, capsys):
        """git commit -n (short form of --no-verify) is rejected."""
        card = make_card(criteria=[make_criterion(cmd="git commit -n -m 'msg'")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "hook-skip" in captured.err.lower() or "no-verify" in captured.err.lower()

    def test_no_gpg_sign_pattern_detected(self, kanban, capsys):
        """--no-gpg-sign hook-skip flag is rejected with exit 1."""
        card = make_card(criteria=[make_criterion(cmd="git commit --no-gpg-sign -m 'msg'")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "no-gpg-sign" in captured.err.lower() or "hook-skip" in captured.err.lower()

    def test_husky_skip_hooks_pattern_detected(self, kanban, capsys):
        """HUSKY_SKIP_HOOKS=1 hook-skip env var is rejected with exit 1."""
        card = make_card(criteria=[make_criterion(cmd="HUSKY_SKIP_HOOKS=1 git commit -m 'msg'")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "husky_skip_hooks" in captured.err.lower() or "hook-skip" in captured.err.lower()

    def test_dash_leading_pattern_detected(self, kanban, capsys):
        """rg with a dash-leading pattern (without -- or -e guard) is rejected."""
        card = make_card(criteria=[make_criterion(cmd="rg -qF '--watch' file")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "dash-leading" in captured.err.lower() or "separator" in captured.err.lower()

    def test_rg_E_in_quoted_arg_is_not_flagged(self, kanban):
        """rg -qi 'rg -E text' file: rg -E is inside the regex pattern, not a flag."""
        card = make_card(criteria=[make_criterion(cmd="rg -qi 'rg -E text' file")])
        try:
            kanban.validate_mov_commands_content(card)
        except SystemExit as e:
            pytest.fail(
                f"rg -E inside quoted pattern arg raised SystemExit({e.code}) — "
                f"token-based detection should not flag this"
            )

    def test_rg_E_as_flag_is_still_flagged(self, kanban, capsys):
        """rg -qiE 'pattern' file: -E is an actual flag to rg and must be rejected."""
        card = make_card(criteria=[make_criterion(cmd="rg -qiE 'pattern' file")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "rg -E" in captured.err or "-E" in captured.err or "encoding" in captured.err.lower()

    def test_rg_E_in_grep_command_text_search(self, kanban):
        """grep 'rg -E' file: grep is searching FOR the text 'rg -E', not using -E as its own flag."""
        card = make_card(criteria=[make_criterion(cmd="grep 'rg -E' file")])
        try:
            kanban.validate_mov_commands_content(card)
        except SystemExit as e:
            pytest.fail(
                f"grep searching for literal 'rg -E' text raised SystemExit({e.code}) — "
                f"token-based detection should not flag grep's pattern content"
            )

    def test_rg_E_piped_multi_rg_pipeline_detected(self, kanban, capsys):
        """rg -qi 'pattern' file | rg -E 'other': second rg -E in pipeline must be rejected."""
        card = make_card(criteria=[make_criterion(cmd="rg -qi 'pattern' file | rg -E 'other'")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "rg -E" in captured.err or "-E" in captured.err or "encoding" in captured.err.lower()

    def test_rg_E_value_consuming_short_flag_f_detected(self, kanban, capsys):
        """rg -f encodingfile -E 'pattern' file: -f consumes value, -E must still be detected."""
        card = make_card(criteria=[make_criterion(cmd="rg -f encodingfile -E 'pattern' file")])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "rg -E" in captured.err or "-E" in captured.err or "encoding" in captured.err.lower()

    def test_rg_E_shlex_fallback_with_unclosed_quotes(self):
        """rg -qiE 'unclosed: shlex.split raises ValueError, fallback to regex detection returns True."""
        mod = load_kanban()
        result = mod._mov_is_rg_E_flag_token("rg -qiE 'unclosed")
        assert result is True, (
            "shlex fallback should return True for rg -qiE with unclosed quote "
            "(regex detection catches it)"
        )


# ---------------------------------------------------------------------------
# Integration tests: inline-JSON path (subprocess-based)
# ---------------------------------------------------------------------------

class TestInlineJsonPathSubprocess:
    """
    End-to-end tests using subprocess to invoke the kanban CLI directly.

    These tests cover the inline-JSON code path (positional JSON argument),
    verifying that validate_mov_commands_content is called when using
    `kanban do '{...}'` or `kanban todo '{...}'` (no --file flag).
    """

    def test_inline_backslash_pipe_kanban_do_rejected(self, tmp_path):
        """kanban do with inline JSON containing backslash-pipe exits 1."""
        make_kanban_root(tmp_path)
        card = make_card(criteria=[make_criterion(cmd=r"rg -q 'foo\|bar' file")])
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", json.dumps(card)],
            cwd=str(tmp_path),
        )
        assert returncode == 1, f"Expected exit 1, got {returncode}. stderr: {stderr}"
        assert "backslash-pipe" in stderr.lower() or "banned" in stderr.lower(), (
            f"Expected banned-pattern error in stderr, got: {stderr}"
        )

    def test_inline_rg_encoding_flag_kanban_do_rejected(self, tmp_path):
        """kanban do with inline JSON containing rg -E exits 1."""
        make_kanban_root(tmp_path)
        card = make_card(criteria=[make_criterion(cmd="rg -qiE 'pattern' file")])
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", json.dumps(card)],
            cwd=str(tmp_path),
        )
        assert returncode == 1, f"Expected exit 1, got {returncode}. stderr: {stderr}"
        assert "-E" in stderr or "encoding" in stderr.lower() or "banned" in stderr.lower(), (
            f"Expected rg -E error in stderr, got: {stderr}"
        )

    def test_inline_backslash_pipe_kanban_todo_rejected(self, tmp_path):
        """kanban todo with inline JSON containing backslash-pipe exits 1."""
        make_kanban_root(tmp_path)
        card = make_card(criteria=[make_criterion(cmd=r"rg -q 'foo\|bar' file")])
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "todo", json.dumps(card)],
            cwd=str(tmp_path),
        )
        assert returncode == 1, f"Expected exit 1, got {returncode}. stderr: {stderr}"

    def test_inline_clean_card_kanban_do_accepted(self, tmp_path):
        """kanban do with clean inline JSON creates the card (exit 0)."""
        make_kanban_root(tmp_path)
        card = make_card(criteria=[make_criterion(cmd="rg -q X")])
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", json.dumps(card)],
            cwd=str(tmp_path),
        )
        assert returncode == 0, f"Expected exit 0, got {returncode}. stderr: {stderr}"
        created = list((tmp_path / "doing").glob("*.json"))
        assert len(created) == 1, f"Expected 1 card created, found {len(created)}"


# ---------------------------------------------------------------------------
# Integration tests: --file path (subprocess-based)
# ---------------------------------------------------------------------------

class TestFilePathSubprocess:
    """
    End-to-end tests using subprocess to invoke the kanban CLI with --file.

    These tests cover the --file code path, verifying that
    validate_mov_commands_content is called when using `kanban do --file <path>`.
    """

    def test_file_backslash_pipe_kanban_do_rejected(self, tmp_path):
        """kanban do --file with backslash-pipe in cmd exits 1."""
        make_kanban_root(tmp_path)
        card = make_card(criteria=[make_criterion(cmd=r"rg -q 'foo\|bar' file")])
        card_file = tmp_path / "card.json"
        card_file.write_text(json.dumps(card), encoding="utf-8")
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", "--file", str(card_file)],
            cwd=str(tmp_path),
        )
        assert returncode == 1, f"Expected exit 1, got {returncode}. stderr: {stderr}"
        assert "backslash-pipe" in stderr.lower() or "banned" in stderr.lower(), (
            f"Expected banned-pattern error in stderr, got: {stderr}"
        )

    def test_file_rg_encoding_flag_kanban_do_rejected(self, tmp_path):
        """kanban do --file with rg -E in cmd exits 1."""
        make_kanban_root(tmp_path)
        card = make_card(criteria=[make_criterion(cmd="rg -E 'pattern' file")])
        card_file = tmp_path / "card.json"
        card_file.write_text(json.dumps(card), encoding="utf-8")
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", "--file", str(card_file)],
            cwd=str(tmp_path),
        )
        assert returncode == 1, f"Expected exit 1, got {returncode}. stderr: {stderr}"

    def test_file_absence_idiom_kanban_do_rejected(self, tmp_path):
        """kanban do --file with absence-via-count idiom exits 1."""
        make_kanban_root(tmp_path)
        card = make_card(criteria=[make_criterion(cmd="test $(rg -c 'X' f) -le 0")])
        card_file = tmp_path / "card.json"
        card_file.write_text(json.dumps(card), encoding="utf-8")
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", "--file", str(card_file)],
            cwd=str(tmp_path),
        )
        assert returncode == 1, f"Expected exit 1, got {returncode}. stderr: {stderr}"
        assert "absence" in stderr.lower() or "rg -c" in stderr or "banned" in stderr.lower(), (
            f"Expected absence-idiom error in stderr, got: {stderr}"
        )

    def test_file_clean_card_accepted(self, tmp_path):
        """kanban do --file with clean card JSON exits 0 and creates card."""
        make_kanban_root(tmp_path)
        card = make_card(criteria=[make_criterion(cmd="rg -q X")])
        card_file = tmp_path / "card.json"
        card_file.write_text(json.dumps(card), encoding="utf-8")
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", "--file", str(card_file)],
            cwd=str(tmp_path),
        )
        assert returncode == 0, f"Expected exit 0, got {returncode}. stderr: {stderr}"

    def test_malformed_json_with_hook_skip_blocked(self, tmp_path):
        """Malformed JSON containing --no-verify triggers hook-skip block (fail-closed)."""
        make_kanban_root(tmp_path)
        # Intentionally malformed JSON that still contains a hook-skip literal.
        malformed_json = '{"action": "test", "criteria": [{"cmd": "git commit --no-verify"'
        card_file = tmp_path / "malformed.json"
        card_file.write_text(malformed_json, encoding="utf-8")
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", "--file", str(card_file)],
            cwd=str(tmp_path),
        )
        assert returncode == 1, f"Expected exit 1 for malformed JSON with hook-skip, got {returncode}"
        # Should emit hook-skip specific message, not just generic JSON parse error.
        assert (
            "no-verify" in stderr.lower()
            or "hook-skip" in stderr.lower()
            or "banned" in stderr.lower()
        ), f"Expected hook-skip block message in stderr, got: {stderr}"


# ---------------------------------------------------------------------------
# Tests for review and research card types
# ---------------------------------------------------------------------------

class TestCardTypeValidation:
    """Tests that validate_mov_commands_content handles all card types equally."""

    def test_review_card_with_banned_pattern_rejected(self, kanban, capsys):
        """type: review card with banned mov_commands pattern is rejected."""
        review_card = {
            "action": "Review the thing",
            "intent": "Because reasons",
            "type": "review",
            "agent": "swe-devex",
            "criteria": [make_criterion(cmd=r"rg -q 'foo\|bar' file")],
        }
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(review_card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "backslash-pipe" in captured.err.lower() or "banned" in captured.err.lower()

    def test_research_card_with_banned_pattern_rejected(self, kanban, capsys):
        """type: research card with banned mov_commands pattern is rejected."""
        research_card = {
            "action": "Research the thing",
            "intent": "Because reasons",
            "type": "research",
            "agent": "researcher",
            "criteria": [make_criterion(cmd="rg -qiE 'pattern' file")],
        }
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_commands_content(research_card)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "-E" in captured.err or "encoding" in captured.err.lower() or "banned" in captured.err.lower()

    def test_review_card_clean_passes(self, kanban):
        """type: review card with clean mov_commands passes without error."""
        review_card = {
            "action": "Review the thing",
            "intent": "Because reasons",
            "type": "review",
            "agent": "swe-devex",
            "criteria": [make_criterion(cmd="rg -q X")],
        }
        try:
            kanban.validate_mov_commands_content(review_card)
        except SystemExit as e:
            pytest.fail(f"Clean review card raised SystemExit({e.code})")


# ---------------------------------------------------------------------------
# Tests for the identifier-existence warning (non-blocking)
#
# `_check_destructive_git_ops` is the real, invented function name from the
# historical incident (an audit hallucinated it; it was then propagated,
# unverified, into a fix card and two review cards). It genuinely does not
# exist anywhere in this repo as actual source — outside `.kanban/` and
# outside this test module's own fixtures.
#
# Both this file's directory (modules/kanban/tests/) and `.kanban/` are
# excluded from `_identifier_exists_in_repo`'s search (see kanban.py). This
# fixture literal has to live somewhere in this file's text to drive the
# true-positive assertion below — without that exclusion, the mere presence
# of this literal in the test suite would make the production check treat
# the identifier as "found," self-defeating the very test proving it is
# correctly flagged as unmatched when genuinely absent from real source.
#
# `_validate_bash_destructive_git` is the real function that DOES exist
# (modules/claude/kanban-pretool-hook.py) — used as the true-negative.
# ---------------------------------------------------------------------------

_REAL_NONEXISTENT_IDENTIFIER = "_check_destructive_git_ops"
_REAL_EXISTING_IDENTIFIER = "_validate_bash_destructive_git"


class TestIdentifierExistenceWarningUnit:
    """Direct unit tests for extract_identifier_candidates / warn_unmatched_card_identifiers."""

    def test_true_positive_nonexistent_identifier_is_flagged(self, kanban, capsys):
        """The real invented identifier from the incident is flagged as unmatched.

        Relies on `_identifier_exists_in_repo` excluding this file's own
        directory (modules/kanban/tests/) from its search — see module
        comment above and kanban.py's _MOV_IDENTIFIER_SEARCH_EXCLUDE_GLOBS.
        Without that exclusion, this fixture's own literal presence in this
        file would make the identifier appear to "exist," self-defeating
        this assertion.
        """
        card = make_card(action=f"Fix the caller `{_REAL_NONEXISTENT_IDENTIFIER}`")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert _REAL_NONEXISTENT_IDENTIFIER in captured.err

    def test_true_negative_existing_identifier_is_not_flagged(self, kanban, capsys):
        """A real, existing identifier is NOT flagged — no warning at all."""
        card = make_card(action=f"Fix the caller `{_REAL_EXISTING_IDENTIFIER}`")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert captured.err == ""
        assert _REAL_EXISTING_IDENTIFIER not in captured.err

    def test_warn_only_never_raises_systemexit(self, kanban):
        """warn_unmatched_card_identifiers never blocks — no SystemExit, ever."""
        card = make_card(action=f"Fix the caller `{_REAL_NONEXISTENT_IDENTIFIER}`")
        try:
            kanban.warn_unmatched_card_identifiers(card)
        except SystemExit as e:
            pytest.fail(f"warn_unmatched_card_identifiers raised SystemExit({e.code}) — must be warn-only")

    def test_card_with_unmatched_identifier_still_validates_successfully(self, kanban, capsys):
        """A card whose action references an unmatched identifier still builds/validates
        successfully via validate_and_build_card — warn, never block.

        This is the behavioural decision most likely to be silently inverted by a
        later edit, so it gets its own explicit assertion.
        """
        data = make_card(action=f"Fix the caller `{_REAL_NONEXISTENT_IDENTIFIER}`")
        try:
            built_card = kanban.validate_and_build_card(data, session="test-session")
        except SystemExit as e:
            pytest.fail(
                f"Card with unmatched identifier raised SystemExit({e.code}) — "
                f"identifier-existence check must warn, not block"
            )
        assert built_card["action"] == data["action"]
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert _REAL_NONEXISTENT_IDENTIFIER in captured.err

    def test_extract_identifier_candidates_excludes_file_paths(self, kanban):
        """A backtick-quoted file path is not identifier-shaped (contains '/' and '.')."""
        candidates = kanban.extract_identifier_candidates(
            "Edit `modules/kanban/kanban.py` to fix the bug"
        )
        assert candidates == []

    def test_extract_identifier_candidates_excludes_shell_commands(self, kanban):
        """A backtick-quoted shell command/flag (contains spaces or a leading dash)
        is not identifier-shaped."""
        candidates = kanban.extract_identifier_candidates(
            "Run `git commit -n` and check for `--no-verify`"
        )
        assert candidates == []

    def test_extract_identifier_candidates_excludes_bare_english_words(self, kanban):
        """A bare, non-compound lowercase word (no underscore, no case mixing) is
        excluded even though it is technically a valid identifier — it is far more
        likely to be prose than a real code reference."""
        candidates = kanban.extract_identifier_candidates(
            "Update the `criteria` and re-run `pytest`"
        )
        assert candidates == []

    def test_extract_identifier_candidates_includes_snake_case(self, kanban):
        """A snake_case backtick-quoted token (contains an underscore) is identifier-shaped."""
        candidates = kanban.extract_identifier_candidates(
            f"The caller `{_REAL_NONEXISTENT_IDENTIFIER}` is invoked here"
        )
        assert candidates == [_REAL_NONEXISTENT_IDENTIFIER]

    def test_extract_identifier_candidates_includes_camel_case(self, kanban):
        """A camelCase backtick-quoted token (mixed case, no underscore) is identifier-shaped."""
        candidates = kanban.extract_identifier_candidates(
            "The field `movCommands` is a typo of mov_commands"
        )
        assert candidates == ["movCommands"]

    def test_extract_identifier_candidates_includes_json_field_name_that_exists(self, kanban, capsys):
        """A compound JSON field name that genuinely exists in the repo (mov_commands)
        is identifier-shaped but is NOT flagged, since it exists in kanban.py's own source."""
        card = make_card(action="Add a `mov_commands` entry to the criterion")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_multiple_cards_bulk_array_reports_correct_card_index(self, kanban, capsys):
        """Bulk array input: an unmatched identifier in card[1] is reported with that index."""
        cards = [
            make_card(action="Card A: nothing special here"),
            make_card(action=f"Card B: fix `{_REAL_NONEXISTENT_IDENTIFIER}`"),
        ]
        kanban.warn_unmatched_card_identifiers(cards)
        captured = capsys.readouterr()
        assert "card[1]" in captured.err
        assert _REAL_NONEXISTENT_IDENTIFIER in captured.err


# ---------------------------------------------------------------------------
# Tests for the noise-reduction fixes from the Tier 2 review (card #3344):
# MCP tool name exclusion, camelCase/snake_case cross-matching, and the
# narrowed modules/kanban/tests/** exclusion. See review at
# .scratchpad/review-identgate.md.
# ---------------------------------------------------------------------------

class TestIdentifierExistenceMcpToolExclusion:
    """MCP tool identifiers (mcp__server__tool) are never real repo source and are
    excluded from candidates entirely — review finding Q2."""

    def test_extract_identifier_candidates_excludes_mcp_tool_names(self, kanban):
        """A backtick-quoted MCP tool name is not identifier-shaped for this check's
        purposes — it is filtered out before shape-checking, not merely unmatched."""
        candidates = kanban.extract_identifier_candidates(
            "Call `mcp__notes__delete_note` and also `mcp__claude_ai_Slack__authenticate`"
        )
        assert candidates == []

    def test_mcp_tool_name_reference_is_not_flagged(self, kanban, capsys):
        """A card legitimately referencing a real MCP tool never warns, since MCP tool
        names can never appear as literal strings in this repo's own source."""
        card = make_card(action="Use `mcp__notes__delete_note` to remove the stale note")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_extract_identifier_candidates_mcp_exclusion_does_not_hide_other_tokens(self, kanban):
        """The MCP exclusion only removes the mcp__ prefixed token — other identifier-shaped
        tokens on the same line are still extracted normally."""
        candidates = kanban.extract_identifier_candidates(
            f"Call `mcp__notes__delete_note` then fix `{_REAL_NONEXISTENT_IDENTIFIER}`"
        )
        assert candidates == [_REAL_NONEXISTENT_IDENTIFIER]


class TestIdentifierExistenceCaseVariantMatching:
    """A candidate written in one naming convention (camelCase/snake_case) still
    matches a real repo identifier written in the other convention — review finding Q2.
    """

    def test_case_variants_helper_generates_snake_from_camel(self, kanban):
        assert kanban._mov_identifier_case_variants("outputStyle") == [
            "outputStyle",
            "output_style",
        ]

    def test_case_variants_helper_generates_camel_from_snake(self, kanban):
        assert kanban._mov_identifier_case_variants("output_style") == [
            "output_style",
            "outputStyle",
        ]

    def test_case_variants_helper_handles_screaming_snake_case(self, kanban):
        """SCREAMING_SNAKE_CASE constants still take the underscore branch and get a
        lowercase-first-word camelCase variant, same as any other snake_case token."""
        assert kanban._mov_identifier_case_variants("MAX_RETRIES") == [
            "MAX_RETRIES",
            "maxRetries",
        ]

    def test_camel_case_candidate_matches_existing_snake_case_identifier(self, kanban, capsys):
        """`outputStyle` (camelCase, not itself present in the repo) is NOT flagged,
        because its snake_case counterpart `output_style` is a real, existing identifier
        (kanban.py's own CLI option)."""
        card = make_card(action="Check the `outputStyle` flag behavior")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_case_variant_matching_does_not_reintroduce_the_motivating_false_negative(self, kanban, capsys):
        """Case/underscore normalization must not make the real historical incident's
        hallucinated identifier collide with the real identifier that does exist —
        confirms the two do not accidentally match after normalization."""
        assert (
            kanban._mov_identifier_case_variants(_REAL_NONEXISTENT_IDENTIFIER)
            != kanban._mov_identifier_case_variants(_REAL_EXISTING_IDENTIFIER)
        )
        card = make_card(action=f"Fix the caller `{_REAL_NONEXISTENT_IDENTIFIER}`")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert _REAL_NONEXISTENT_IDENTIFIER in captured.err


class TestIdentifierExistenceNarrowedTestDirExclusion:
    """The modules/kanban/tests/** exclusion applies only to the known fixture
    literal(s), not the whole directory — review finding Q3. Real identifiers that
    happen to be defined only in that directory must still be found."""

    def test_helper_defined_only_in_tests_dir_is_not_flagged(self, kanban, capsys):
        """`make_kanban_root` is a real, existing helper defined only in
        modules/kanban/tests/test_kanban_mov_validation.py (this file) and nowhere
        else in the repo. Before the Q3 fix, the blanket directory exclusion made it
        appear unmatched; after the fix, it is found because only the known fixture
        literal(s) are excluded from that directory, not the whole tree."""
        card = make_card(action="Extend `make_kanban_root` to support a new fixture shape")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_another_helper_defined_only_in_tests_dir_is_not_flagged(self, kanban, capsys):
        """`run_kanban_subprocess` is likewise real, existing, and defined only in this
        test file — must not be flagged."""
        card = make_card(action="Add a fixture using `run_kanban_subprocess`")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_fixture_literal_is_still_shielded_from_self_match(self, kanban, capsys):
        """The known fixture literal is still excluded from modules/kanban/tests/** —
        without this, its own presence in this test file's text would make the check
        treat it as 'existing,' self-defeating the true-positive test that proves this
        check works. This test is a duplicate-intent guard on top of
        test_true_positive_nonexistent_identifier_is_flagged above, specific to the
        narrowed (allowlist-based) exclusion mechanism."""
        assert _REAL_NONEXISTENT_IDENTIFIER in kanban._MOV_IDENTIFIER_TEST_FIXTURE_LITERALS
        card = make_card(action=f"Fix the caller `{_REAL_NONEXISTENT_IDENTIFIER}`")
        kanban.warn_unmatched_card_identifiers(card)
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert _REAL_NONEXISTENT_IDENTIFIER in captured.err


# ---------------------------------------------------------------------------
# Integration test: identifier-existence warning via subprocess (kanban do)
# ---------------------------------------------------------------------------

class TestIdentifierExistenceWarningSubprocess:
    """End-to-end test that `kanban do` warns but still creates the card."""

    def test_kanban_do_with_unmatched_identifier_warns_but_succeeds(self, tmp_path):
        """kanban do with an action referencing an unmatched identifier exits 0,
        creates the card, and prints a warning to stderr."""
        make_kanban_root(tmp_path)
        card = make_card(
            action=f"Fix the caller `{_REAL_NONEXISTENT_IDENTIFIER}`",
            criteria=[make_criterion(cmd="rg -q X")],
        )
        returncode, stdout, stderr = run_kanban_subprocess(
            ["--root", str(tmp_path), "do", json.dumps(card)],
            cwd=str(_KANBAN_PATH.parent.parent.parent),  # repo root, so rg search covers real source
        )
        assert returncode == 0, f"Expected exit 0 (warn, not block), got {returncode}. stderr: {stderr}"
        assert "Warning" in stderr
        assert _REAL_NONEXISTENT_IDENTIFIER in stderr
        created = list((tmp_path / "doing").glob("*.json"))
        assert len(created) == 1, f"Expected 1 card created despite the warning, found {len(created)}"
