"""
Tests for unknown/misspelled field validation in kanban.py.

Covers:
- Criterion with movCommands (camelCase typo) → rejected with 'did you mean mov_commands?'
- Top-level card with unknown field (e.g. criterias typo) → rejected
- Card with all-correct snake_case fields → accepted (regression)
- Top-level unknown field with a close match → suggestion present in error
- Top-level unknown field with no close match → rejected without suggestion
- mov_commands entry with unknown field → rejected
- Bulk array: one card with unknown field → rejected
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

    spec = importlib.util.spec_from_file_location("kanban_unknown_field", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_valid_criterion(text="Check something", cmd="rg -q X", timeout=10):
    """Build a valid programmatic criterion dict."""
    return {
        "text": text,
        "mov_type": "programmatic",
        "mov_commands": [{"cmd": cmd, "timeout": timeout}],
        "met": False,
    }


def make_valid_card_data(action="Do the thing", criteria=None, card_type="work"):
    """Build a minimal valid card JSON dict."""
    if criteria is None:
        criteria = [make_valid_criterion()]
    return {
        "action": action,
        "intent": "Because reasons",
        "type": card_type,
        "agent": "swe-devex",
        "criteria": criteria,
    }


def make_args_with_json(json_data: str, root: str, session: str = "test-session"):
    """Build a mock args object for cmd_do / cmd_todo with inline JSON."""
    args = MagicMock()
    args.root = root
    args.session = session
    args.json_data = json_data
    args.json_file = None
    return args


def setup_kanban_root(tmp_path):
    """Create minimal kanban board directory structure."""
    for col in ("todo", "doing", "done", "canceled"):
        (tmp_path / col).mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests: validate_no_unknown_fields
# ---------------------------------------------------------------------------

class TestValidateNoUnknownFields:
    """validate_no_unknown_fields rejects cards with unknown/misspelled fields."""

    def test_movCommands_camelCase_rejected(self, kanban, capsys):
        """Criterion with movCommands (camelCase typo) → exit 1 with helpful error."""
        data = make_valid_card_data(criteria=[
            {
                "text": "Check something",
                "movCommands": [{"cmd": "rg -q X", "timeout": 10}],
                "met": False,
            }
        ])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_no_unknown_fields(data)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "movCommands" in captured.err

    def test_movCommands_suggests_mov_commands(self, kanban, capsys):
        """Error for movCommands includes 'did you mean mov_commands?' suggestion."""
        data = make_valid_card_data(criteria=[
            {
                "text": "Check something",
                "movCommands": [{"cmd": "rg -q X", "timeout": 10}],
                "met": False,
            }
        ])
        with pytest.raises(SystemExit):
            kanban.validate_no_unknown_fields(data)
        captured = capsys.readouterr()
        assert "mov_commands" in captured.err

    def test_criterias_typo_rejected(self, kanban, capsys):
        """Card with 'criterias' instead of 'criteria' → exit 1."""
        data = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "type": "work",
            "criterias": [{"text": "Check something", "met": False}],
        }
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_no_unknown_fields(data)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "criterias" in captured.err

    def test_criterias_suggests_criteria(self, kanban, capsys):
        """Error for 'criterias' includes suggestion for 'criteria'."""
        data = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "type": "work",
            "criterias": [{"text": "Check something", "met": False}],
        }
        with pytest.raises(SystemExit):
            kanban.validate_no_unknown_fields(data)
        captured = capsys.readouterr()
        assert "criteria" in captured.err

    def test_unknown_top_level_field_no_close_match_rejected(self, kanban, capsys):
        """Card with totally unknown top-level field → exit 1, no suggestion required."""
        data = make_valid_card_data()
        data["xyzzy_nonexistent"] = "some value"
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_no_unknown_fields(data)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "xyzzy_nonexistent" in captured.err

    def test_unknown_mov_entry_field_rejected(self, kanban, capsys):
        """mov_commands entry with unknown field (e.g. 'timeoutt') → exit 1."""
        data = make_valid_card_data(criteria=[
            {
                "text": "Check something",
                "mov_commands": [{"cmd": "rg -q X", "timeoutt": 10}],
                "met": False,
            }
        ])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_no_unknown_fields(data)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "timeoutt" in captured.err

    def test_valid_card_all_correct_fields_passes(self, kanban):
        """Card with all correct snake_case fields passes without error (regression)."""
        data = make_valid_card_data()
        try:
            kanban.validate_no_unknown_fields(data)
        except SystemExit as e:
            pytest.fail(f"Valid card raised SystemExit({e.code})")

    def test_valid_card_with_optional_fields_passes(self, kanban):
        """Card with all optional fields populated passes without error."""
        data = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": ["src/foo.py"],
            "readFiles": ["src/bar.py"],
            "criteria": [make_valid_criterion()],
        }
        try:
            kanban.validate_no_unknown_fields(data)
        except SystemExit as e:
            pytest.fail(f"Card with all optional fields raised SystemExit({e.code})")

    def test_valid_card_with_ac_shorthand_passes(self, kanban):
        """Card using 'ac' shorthand instead of 'criteria' passes without error."""
        data = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "type": "work",
            "ac": [make_valid_criterion()],
        }
        try:
            kanban.validate_no_unknown_fields(data)
        except SystemExit as e:
            pytest.fail(f"Card with 'ac' shorthand raised SystemExit({e.code})")


# ---------------------------------------------------------------------------
# Integration tests: validate_and_build_card rejects unknown fields
# ---------------------------------------------------------------------------

class TestValidateAndBuildCardUnknownFields:
    """validate_and_build_card exits 1 when card JSON contains unknown fields."""

    def test_movCommands_criterion_rejected_by_validate_and_build_card(self, kanban, capsys):
        """validate_and_build_card rejects criterion with movCommands (camelCase)."""
        data = make_valid_card_data(criteria=[
            {
                "text": "Check something",
                "movCommands": [{"cmd": "rg -q X", "timeout": 10}],
                "met": False,
            }
        ])
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "movCommands" in captured.err
        assert "mov_commands" in captured.err

    def test_unknown_top_level_field_rejected_by_validate_and_build_card(self, kanban, capsys):
        """validate_and_build_card rejects card with unknown top-level field."""
        data = make_valid_card_data()
        data["criterias"] = data.pop("criteria")
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "criterias" in captured.err

    def test_valid_card_passes_validate_and_build_card(self, kanban):
        """Valid card with correct fields passes validate_and_build_card."""
        data = make_valid_card_data()
        try:
            card = kanban.validate_and_build_card(data, session="test")
        except SystemExit as e:
            pytest.fail(f"Valid card raised SystemExit({e.code})")
        assert card is not None
        assert card["action"] == "Do the thing"


# ---------------------------------------------------------------------------
# Integration tests: cmd_do and cmd_todo reject unknown fields
# ---------------------------------------------------------------------------

class TestCmdDoUnknownFieldValidation:
    """cmd_do exits 1 when card JSON contains unknown fields."""

    def test_cmd_do_rejects_movCommands_criterion(self, kanban, tmp_path, capsys):
        """kanban do rejects card with movCommands typo in criterion."""
        setup_kanban_root(tmp_path)
        data = make_valid_card_data(criteria=[
            {
                "text": "Check something",
                "movCommands": [{"cmd": "rg -q X", "timeout": 10}],
                "met": False,
            }
        ])
        args = make_args_with_json(json.dumps(data), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "movCommands" in captured.err
        assert "mov_commands" in captured.err

    def test_cmd_do_rejects_unknown_top_level_field(self, kanban, tmp_path, capsys):
        """kanban do rejects card with unknown top-level field (criterias typo)."""
        setup_kanban_root(tmp_path)
        data = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "type": "work",
            "criterias": [make_valid_criterion()],
        }
        args = make_args_with_json(json.dumps(data), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "criterias" in captured.err

    def test_cmd_do_accepts_valid_card(self, kanban, tmp_path, capsys):
        """kanban do accepts a card with all correct fields (regression test)."""
        setup_kanban_root(tmp_path)
        data = make_valid_card_data()
        args = make_args_with_json(json.dumps(data), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                try:
                    kanban.cmd_do(args)
                except SystemExit as e:
                    pytest.fail(f"Valid card raised SystemExit({e.code})")

        doing_dir = tmp_path / "doing"
        created = list(doing_dir.glob("*.json"))
        assert len(created) == 1, f"Expected 1 card created, found {len(created)}"

    def test_cmd_do_bulk_array_rejects_one_card_with_movCommands(self, kanban, tmp_path, capsys):
        """Bulk array: one card with movCommands typo → exit 1, stderr mentions movCommands."""
        setup_kanban_root(tmp_path)
        card_bad = make_valid_card_data(
            action="Bad card with movCommands typo",
            criteria=[
                {
                    "text": "Check something",
                    "movCommands": [{"cmd": "rg -q X", "timeout": 10}],
                    "met": False,
                }
            ],
        )
        bulk_array = [
            make_valid_card_data(action="First valid card"),
            card_bad,
            make_valid_card_data(action="Third valid card"),
        ]
        args = make_args_with_json(json.dumps(bulk_array), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "movCommands" in captured.err


class TestCmdTodoUnknownFieldValidation:
    """cmd_todo exits 1 when card JSON contains unknown fields."""

    def test_cmd_todo_rejects_movCommands_criterion(self, kanban, tmp_path, capsys):
        """kanban todo rejects card with movCommands typo in criterion."""
        setup_kanban_root(tmp_path)
        data = make_valid_card_data(criteria=[
            {
                "text": "Check something",
                "movCommands": [{"cmd": "rg -q X", "timeout": 10}],
                "met": False,
            }
        ])
        args = make_args_with_json(json.dumps(data), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_todo(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "movCommands" in captured.err

    def test_cmd_todo_accepts_valid_card(self, kanban, tmp_path):
        """kanban todo accepts a card with all correct fields (regression test)."""
        setup_kanban_root(tmp_path)
        data = make_valid_card_data()
        args = make_args_with_json(json.dumps(data), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                try:
                    kanban.cmd_todo(args)
                except SystemExit as e:
                    pytest.fail(f"Valid card raised SystemExit({e.code})")

        todo_dir = tmp_path / "todo"
        created = list(todo_dir.glob("*.json"))
        assert len(created) == 1, f"Expected 1 card created, found {len(created)}"
