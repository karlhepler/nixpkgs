"""
Tests for the mov_type schema simplification.

Since card #1527: mov_type is no longer required on card creation, no longer
emitted in XML output, but tolerated on existing cards for backward compatibility.
Programmatic mode is implicit: a criterion with non-empty mov_commands is
programmatic; without mov_commands it is treated as semantic (no MoV commands run).

Covers:
- Card creation accepts criterion without mov_type field
- Empty mov_commands is rejected on creation
- kanban show --output-style=xml does NOT emit mov-type attribute on <ac> elements
"""

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
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

    spec = importlib.util.spec_from_file_location("kanban_mov_type_schema", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_card_data_no_mov_type(action="Do the thing", cmd="rg -q X", timeout=10):
    """Build a card JSON dict with a criterion that has NO mov_type field."""
    return {
        "action": action,
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-devex",
        "criteria": [
            {
                "text": "Check something",
                "mov_commands": [{"cmd": cmd, "timeout": timeout}],
                "agent_met": False,
                "reviewer_met": None,
            }
        ],
    }


def make_card_data_empty_mov_commands(action="Do the thing"):
    """Build a card JSON dict with a criterion that has an empty mov_commands array."""
    return {
        "action": action,
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-devex",
        "criteria": [
            {
                "text": "Check something",
                "mov_commands": [],
                "agent_met": False,
                "reviewer_met": None,
            }
        ],
    }


def _setup_board(tmp_path):
    """Create minimal kanban board directory structure."""
    for col in ("todo", "doing", "review", "done", "canceled"):
        (tmp_path / col).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_card(board_root, col, num, card_data):
    """Write a card JSON file into a column directory."""
    card_path = board_root / col / f"{num}.json"
    card_path.write_text(json.dumps(card_data))
    return card_path


def _make_card_with_criteria(criteria, session="test-session"):
    """Build a minimal card dict with given criteria."""
    return {
        "action": "Do the thing",
        "intent": "Because reasons",
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": [],
        "readFiles": [],
        "criteria": criteria,
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# AC #1: Card creation accepts criterion without mov_type field
# ---------------------------------------------------------------------------

class TestMovTypeOptionalOnCreation:
    """Criterion without mov_type field is accepted on card creation."""

    def test_criterion_without_mov_type_field_is_accepted(self, kanban):
        """Card with {text, mov_commands} only (no mov_type) passes validation."""
        data = make_card_data_no_mov_type()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            try:
                card = kanban.validate_and_build_card(data, session="test")
            except SystemExit as e:
                pytest.fail(
                    f"Criterion without mov_type raised SystemExit({e.code}) — "
                    f"mov_type must be optional"
                )
        assert card is not None

    def test_criterion_without_mov_type_or_mov_commands_is_accepted(self, kanban):
        """Card with {text} only (no mov_type, no mov_commands) passes validation."""
        data = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "type": "work",
            "agent": "swe-devex",
            "criteria": [
                {
                    "text": "Human-verified check",
                    "agent_met": False,
                    "reviewer_met": None,
                }
            ],
        }
        try:
            card = kanban.validate_and_build_card(data, session="test")
        except SystemExit as e:
            pytest.fail(
                f"Criterion with only text raised SystemExit({e.code}) — "
                f"criteria without mov_commands must be accepted"
            )
        assert card is not None

    def test_criterion_with_mov_type_still_accepted_backward_compat(self, kanban):
        """Criterion WITH mov_type='programmatic' is still accepted (backward compat)."""
        data = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "type": "work",
            "agent": "swe-devex",
            "criteria": [
                {
                    "text": "Check something",
                    "mov_type": "programmatic",
                    "mov_commands": [{"cmd": "rg -q X", "timeout": 10}],
                    "agent_met": False,
                    "reviewer_met": None,
                }
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            try:
                card = kanban.validate_and_build_card(data, session="test")
            except SystemExit as e:
                pytest.fail(
                    f"Criterion with mov_type='programmatic' raised SystemExit({e.code}) "
                    f"— existing cards with mov_type must still be accepted"
                )
        assert card is not None


# ---------------------------------------------------------------------------
# AC #2: Empty mov_commands is rejected
# ---------------------------------------------------------------------------

class TestEmptyMovCommandsRejected:
    """Criterion with empty mov_commands array is rejected on creation."""

    def test_empty_mov_commands_rejected(self, kanban, capsys):
        """Criterion with mov_commands=[] is rejected with exit 1."""
        data = make_card_data_empty_mov_commands()
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "mov_commands" in captured.err

    def test_empty_mov_commands_error_message_is_actionable(self, kanban, capsys):
        """Error for empty mov_commands names the field and guides the fix."""
        data = make_card_data_empty_mov_commands()
        with pytest.raises(SystemExit):
            kanban.validate_and_build_card(data, session="test")
        captured = capsys.readouterr()
        # Error must name the field so the user knows what to fix
        assert "mov_commands" in captured.err

    def test_null_mov_commands_is_accepted(self, kanban):
        """Criterion with mov_commands=null (None) is accepted (same as absent)."""
        data = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "type": "work",
            "agent": "swe-devex",
            "criteria": [
                {
                    "text": "Check something",
                    "mov_commands": None,
                    "agent_met": False,
                    "reviewer_met": None,
                }
            ],
        }
        try:
            card = kanban.validate_and_build_card(data, session="test")
        except SystemExit as e:
            pytest.fail(
                f"Criterion with mov_commands=null raised SystemExit({e.code}) — "
                f"null mov_commands must be treated same as absent"
            )
        assert card is not None


# ---------------------------------------------------------------------------
# AC #3: XML output omits mov-type attribute on <ac> elements
# ---------------------------------------------------------------------------

class TestXmlOutputOmitsMovType:
    """kanban show --output-style=xml must NOT emit mov-type attribute on <ac> elements."""

    def _run_cmd_show(self, kanban_mod, board_root, card_path, card_data):
        """Run cmd_show and return captured stdout."""
        args = SimpleNamespace(
            root=str(board_root),
            card="1",
            output_style="xml",
            session="test-session",
        )
        captured = io.StringIO()
        with patch.object(kanban_mod, "get_root", return_value=board_root):
            with patch.object(kanban_mod, "find_card", return_value=card_path):
                with patch.object(kanban_mod, "read_card", return_value=card_data):
                    with patch("sys.stdout", captured):
                        kanban_mod.cmd_show(args)
        return captured.getvalue()

    def test_xml_output_omits_mov_type_attr_on_programmatic_criterion(self, kanban, tmp_path):
        """<ac> element must not have mov-type attribute even for criteria with mov_commands."""
        board = _setup_board(tmp_path)
        criteria = [
            {
                "text": "Check something",
                "mov_type": "programmatic",  # present on disk (backward compat card)
                "mov_commands": [{"cmd": "rg -q X", "timeout": 10}],
                "agent_met": False,
                "reviewer_met": None,
            }
        ]
        card_data = _make_card_with_criteria(criteria)
        card_path = _write_card(board, "doing", "1", card_data)
        card_data_loaded = json.loads(card_path.read_text())

        output = self._run_cmd_show(kanban, board, card_path, card_data_loaded)

        assert "mov-type" not in output, (
            f"XML output must not emit mov-type attribute on <ac> elements. "
            f"Got output containing 'mov-type': {output!r}"
        )

    def test_xml_output_omits_mov_type_attr_on_semantic_criterion(self, kanban, tmp_path):
        """<ac> element must not have mov-type attribute for criteria without mov_commands."""
        board = _setup_board(tmp_path)
        criteria = [
            {
                "text": "Human-verified check",
                "mov_type": "semantic",  # present on disk (backward compat card)
                "agent_met": False,
                "reviewer_met": None,
            }
        ]
        card_data = _make_card_with_criteria(criteria)
        card_path = _write_card(board, "doing", "1", card_data)
        card_data_loaded = json.loads(card_path.read_text())

        output = self._run_cmd_show(kanban, board, card_path, card_data_loaded)

        assert "mov-type" not in output, (
            f"XML output must not emit mov-type attribute on <ac> elements. "
            f"Got output containing 'mov-type': {output!r}"
        )

    def test_xml_output_omits_mov_type_attr_on_new_schema_criterion(self, kanban, tmp_path):
        """<ac> element must not have mov-type when criterion was created without mov_type."""
        board = _setup_board(tmp_path)
        # New-style criterion: no mov_type field at all
        criteria = [
            {
                "text": "Check something",
                "mov_commands": [{"cmd": "rg -q X", "timeout": 10}],
                "agent_met": False,
                "reviewer_met": None,
            }
        ]
        card_data = _make_card_with_criteria(criteria)
        card_path = _write_card(board, "doing", "1", card_data)
        card_data_loaded = json.loads(card_path.read_text())

        output = self._run_cmd_show(kanban, board, card_path, card_data_loaded)

        assert "mov-type" not in output, (
            f"XML output must not emit mov-type attribute on <ac> elements. "
            f"Got: {output!r}"
        )

    def test_xml_output_still_emits_mov_commands_child_elements(self, kanban, tmp_path):
        """<ac> elements with mov_commands still emit <movCommands> children."""
        board = _setup_board(tmp_path)
        criteria = [
            {
                "text": "Check something",
                "mov_commands": [{"cmd": "rg -q X", "timeout": 10}],
                "agent_met": False,
                "reviewer_met": None,
            }
        ]
        card_data = _make_card_with_criteria(criteria)
        card_path = _write_card(board, "doing", "1", card_data)
        card_data_loaded = json.loads(card_path.read_text())

        output = self._run_cmd_show(kanban, board, card_path, card_data_loaded)

        # mov-type must be absent but movCommands must still be present
        assert "mov-type" not in output
        assert "<movCommands>" in output, (
            "movCommands child elements must still appear in XML output"
        )
        assert 'cmd="rg -q X"' in output
