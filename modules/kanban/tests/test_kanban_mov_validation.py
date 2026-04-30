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
