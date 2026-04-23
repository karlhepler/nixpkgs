"""
Tests for kanban.py && validation in mov_commands[].cmd.

Covers:
- Single cmd with && is rejected
- Multiple criteria with && are all reported
- Array card input with one violating card is rejected
- Valid card (no &&) is accepted
- Semantic criteria with no mov_commands are unaffected
- && in criterion text field is NOT rejected (validation scope is mov_commands[].cmd only)
"""

import importlib.util
import json
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

    spec = importlib.util.spec_from_file_location("kanban_ampersand", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_programmatic_criterion(text="Check something", cmd="rg -q X", timeout=10):
    """Build a programmatic criterion dict."""
    return {
        "text": text,
        "mov_type": "programmatic",
        "mov_commands": [{"cmd": cmd, "timeout": timeout}],
        "agent_met": False,
        "reviewer_met": None,
    }


def make_semantic_criterion(text="Semantic check"):
    """Build a semantic criterion dict."""
    return {
        "text": text,
        "mov_type": "semantic",
        "agent_met": False,
        "reviewer_met": None,
    }


def make_card_data(action="Do the thing", criteria=None, card_type="work"):
    """Build a minimal card JSON dict (as passed to validate_and_build_card)."""
    if criteria is None:
        criteria = [make_programmatic_criterion()]
    return {
        "action": action,
        "intent": "Because reasons",
        "type": card_type,
        "agent": "swe-devex",
        "criteria": criteria,
    }


def make_args_with_json(json_data: str, session: str = "test-session"):
    """Build an args mock for cmd_do / cmd_todo with inline JSON."""
    args = MagicMock()
    args.root = None
    args.session = session
    args.json_data = json_data
    args.json_file = None
    return args


# ---------------------------------------------------------------------------
# Unit tests: _collect_ampersand_errors
# ---------------------------------------------------------------------------

class TestCollectAmpersandErrors:
    """_collect_ampersand_errors returns correct violation tuples."""

    def test_returns_empty_for_no_ampersand(self, kanban):
        """No && in any cmd -> empty list returned."""
        criteria = [make_programmatic_criterion(cmd="rg -q X")]
        result = kanban._collect_ampersand_errors(criteria)
        assert result == []

    def test_detects_ampersand_in_cmd(self, kanban):
        """Single && violation returns one tuple."""
        criteria = [make_programmatic_criterion(cmd="rg -q X && rg -q Y")]
        result = kanban._collect_ampersand_errors(criteria)
        assert len(result) == 1
        criterion_num, cmd = result[0]
        assert criterion_num == 1
        assert "&&" in cmd

    def test_criterion_number_is_one_indexed(self, kanban):
        """Criterion number in returned tuple is 1-indexed."""
        criteria = [
            make_semantic_criterion("First"),
            make_programmatic_criterion(cmd="rg -q A && rg -q B"),
        ]
        result = kanban._collect_ampersand_errors(criteria)
        assert len(result) == 1
        assert result[0][0] == 2, "Criterion number should be 2 (1-indexed)"

    def test_multiple_violations_all_collected(self, kanban):
        """Multiple criteria with && are all returned."""
        criteria = [
            make_programmatic_criterion(text="AC 1", cmd="rg -q A && rg -q B"),
            make_programmatic_criterion(text="AC 2", cmd="rg -q C"),
            make_programmatic_criterion(text="AC 3", cmd="test -f x && echo ok"),
        ]
        result = kanban._collect_ampersand_errors(criteria)
        assert len(result) == 2
        criterion_nums = [r[0] for r in result]
        assert 1 in criterion_nums
        assert 3 in criterion_nums

    def test_semantic_criteria_ignored(self, kanban):
        """Semantic criteria are not checked for && (no mov_commands)."""
        criteria = [
            make_semantic_criterion("No && check here"),
            make_programmatic_criterion(cmd="rg -q X"),
        ]
        result = kanban._collect_ampersand_errors(criteria)
        assert result == []

    def test_ampersand_in_text_field_not_detected(self, kanban):
        """&& in criterion text field is NOT flagged -- only mov_commands[].cmd is checked."""
        criteria = [
            {
                "text": "Run rg -q X && rg -q Y",  # && in text, not in cmd
                "mov_type": "programmatic",
                "mov_commands": [{"cmd": "rg -q X", "timeout": 10}],
                "agent_met": False,
                "reviewer_met": None,
            }
        ]
        result = kanban._collect_ampersand_errors(criteria)
        assert result == [], "&& in text field must not trigger the check"


# ---------------------------------------------------------------------------
# Integration tests: validate_and_build_card rejects && on single card
# ---------------------------------------------------------------------------

class TestValidateAndBuildCardAmpersand:
    """validate_and_build_card exits 1 when mov_commands[].cmd contains &&."""

    def test_single_criterion_with_ampersand_rejected(self, kanban, capsys):
        """Card with && in single criterion is rejected with exit 1."""
        data = make_card_data(criteria=[
            make_programmatic_criterion(cmd="rg -q X && rg -q Y"),
        ])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "&&" in captured.err
        assert "forbidden" in captured.err.lower()

    def test_error_message_contains_criterion_number(self, kanban, capsys):
        """Error message names the criterion number."""
        data = make_card_data(criteria=[
            make_semantic_criterion("AC 1"),
            make_programmatic_criterion(text="AC 2", cmd="rg -q A && rg -q B"),
        ])
        with pytest.raises(SystemExit):
            kanban.validate_and_build_card(data, session="test")
        captured = capsys.readouterr()
        assert "Criterion 2" in captured.err

    def test_error_message_contains_fix_pointer(self, kanban, capsys):
        """Error message includes the fix suggestion (separate array items)."""
        data = make_card_data(criteria=[
            make_programmatic_criterion(cmd="rg -q X && rg -q Y"),
        ])
        with pytest.raises(SystemExit):
            kanban.validate_and_build_card(data, session="test")
        captured = capsys.readouterr()
        assert "mov_commands" in captured.err
        assert "separate" in captured.err.lower() or "split" in captured.err.lower()

    def test_multiple_criteria_with_ampersand_all_reported(self, kanban, capsys):
        """When multiple criteria contain &&, all are reported in one error message."""
        data = make_card_data(criteria=[
            make_programmatic_criterion(text="AC 1", cmd="rg -q A && rg -q B"),
            make_programmatic_criterion(text="AC 2", cmd="rg -q C"),
            make_programmatic_criterion(text="AC 3", cmd="test -f x && echo ok"),
        ])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Criterion 1" in captured.err
        assert "Criterion 3" in captured.err

    def test_valid_card_no_ampersand_passes(self, kanban):
        """Card with no && in mov_commands[].cmd passes validation without error."""
        data = make_card_data(criteria=[
            make_programmatic_criterion(cmd="rg -q X"),
        ])
        try:
            card = kanban.validate_and_build_card(data, session="test")
        except SystemExit as e:
            pytest.fail(f"Valid card raised SystemExit({e.code}) -- no && should be fine")
        assert card is not None

    def test_semantic_criterion_only_passes(self, kanban):
        """Card with only semantic criteria (no mov_commands) passes validation."""
        data = make_card_data(criteria=[
            make_semantic_criterion("Just a semantic check"),
        ])
        try:
            card = kanban.validate_and_build_card(data, session="test")
        except SystemExit as e:
            pytest.fail(f"Semantic-only card raised SystemExit({e.code})")
        assert card is not None

    def test_ampersand_in_text_field_not_rejected(self, kanban):
        """&& in criterion text field does NOT trigger the validation."""
        data = make_card_data(criteria=[
            {
                "text": "Run rg -q X && rg -q Y to check",  # && in text only
                "mov_type": "programmatic",
                "mov_commands": [{"cmd": "rg -q X", "timeout": 10}],
                "agent_met": False,
                "reviewer_met": None,
            }
        ])
        try:
            card = kanban.validate_and_build_card(data, session="test")
        except SystemExit as e:
            pytest.fail(f"&& in text field incorrectly triggered exit({e.code})")
        assert card is not None


# ---------------------------------------------------------------------------
# Integration tests: cmd_do batch -- all violations reported
# ---------------------------------------------------------------------------

class TestCmdDoBatchAmpersandValidation:
    """cmd_do with array input reports ALL && violations across all cards."""

    def _setup_kanban_root(self, tmp_path):
        """Create minimal kanban board structure."""
        for col in ("todo", "doing", "review", "done", "canceled"):
            (tmp_path / col).mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_batch_single_violating_card_rejected(self, kanban, tmp_path, capsys):
        """Batch with one violating card is rejected with exit 1."""
        self._setup_kanban_root(tmp_path)
        cards = [
            make_card_data(action="Good card", criteria=[
                make_programmatic_criterion(cmd="rg -q X"),
            ]),
            make_card_data(action="Bad card", criteria=[
                make_programmatic_criterion(cmd="rg -q A && rg -q B"),
            ]),
        ]
        args = make_args_with_json(json.dumps(cards))
        args.root = str(tmp_path)

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "&&" in captured.err
        assert "forbidden" in captured.err.lower()

    def test_batch_multiple_violating_cards_all_reported(self, kanban, tmp_path, capsys):
        """Batch with multiple violating cards reports all violations."""
        self._setup_kanban_root(tmp_path)
        cards = [
            make_card_data(action="Card 0 bad", criteria=[
                make_programmatic_criterion(cmd="rg -q A && rg -q B"),
            ]),
            make_card_data(action="Card 1 good", criteria=[
                make_programmatic_criterion(cmd="rg -q C"),
            ]),
            make_card_data(action="Card 2 bad", criteria=[
                make_programmatic_criterion(cmd="test -f x && echo ok"),
            ]),
        ]
        args = make_args_with_json(json.dumps(cards))
        args.root = str(tmp_path)

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        # Both violating cards should appear in the error output
        assert "card[0]" in captured.err
        assert "card[2]" in captured.err

    def test_batch_all_valid_cards_accepted(self, kanban, tmp_path, capsys):
        """Batch with no && violations passes and creates cards."""
        self._setup_kanban_root(tmp_path)
        cards = [
            make_card_data(action="Card A", criteria=[
                make_programmatic_criterion(cmd="rg -q X"),
            ]),
            make_card_data(action="Card B", criteria=[
                make_semantic_criterion("Semantic only"),
            ]),
        ]
        args = make_args_with_json(json.dumps(cards))
        args.root = str(tmp_path)

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                try:
                    kanban.cmd_do(args)
                except SystemExit as e:
                    pytest.fail(f"Valid batch raised SystemExit({e.code})")

        # Verify cards were created in doing column
        doing_dir = tmp_path / "doing"
        created = list(doing_dir.glob("*.json"))
        assert len(created) == 2, f"Expected 2 cards created, found {len(created)}"


# ---------------------------------------------------------------------------
# Integration tests: cmd_todo batch -- all violations reported
# ---------------------------------------------------------------------------

class TestCmdTodoBatchAmpersandValidation:
    """cmd_todo with array input reports ALL && violations across all cards."""

    def _setup_kanban_root(self, tmp_path):
        """Create minimal kanban board structure."""
        for col in ("todo", "doing", "review", "done", "canceled"):
            (tmp_path / col).mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_todo_batch_violating_card_rejected(self, kanban, tmp_path, capsys):
        """kanban todo batch with && violation is rejected with exit 1."""
        self._setup_kanban_root(tmp_path)
        cards = [
            make_card_data(action="Bad card", criteria=[
                make_programmatic_criterion(cmd="rg -q A && rg -q B"),
            ]),
        ]
        args = make_args_with_json(json.dumps(cards))
        args.root = str(tmp_path)

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_todo(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "&&" in captured.err

    def test_todo_batch_all_valid_cards_accepted(self, kanban, tmp_path):
        """kanban todo batch with no && violations creates cards successfully."""
        self._setup_kanban_root(tmp_path)
        cards = [
            make_card_data(action="Good card", criteria=[
                make_programmatic_criterion(cmd="rg -q X"),
            ]),
        ]
        args = make_args_with_json(json.dumps(cards))
        args.root = str(tmp_path)

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                try:
                    kanban.cmd_todo(args)
                except SystemExit as e:
                    pytest.fail(f"Valid todo batch raised SystemExit({e.code})")

        todo_dir = tmp_path / "todo"
        created = list(todo_dir.glob("*.json"))
        assert len(created) == 1, f"Expected 1 card created, found {len(created)}"
