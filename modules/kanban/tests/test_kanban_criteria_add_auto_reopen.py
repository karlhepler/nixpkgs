"""
Tests for cmd_criteria_add auto-reopen behavior (Option B).

When kanban criteria add is invoked on a card in 'done' status, the card must
be automatically transitioned back to 'doing' before the criterion is appended.
A warning is emitted to stderr explaining the auto-reopen.

Covers:
- criteria add on a todo card: appends criterion, status unchanged (regression)
- criteria add on a doing card: appends criterion, status unchanged (regression)
- criteria add on a done card: appends AND transitions to doing AND warning emitted
- Pre-existing criteria state is preserved through the auto-reopen transition
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

    spec = importlib.util.spec_from_file_location("kanban_criteria_add_auto_reopen", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_board(tmp_path):
    """Create minimal kanban board directory structure."""
    for col in ("todo", "doing", "done", "canceled"):
        (tmp_path / col).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_card(board_root, col, num, card_data):
    """Write a card JSON file into a column directory."""
    card_path = board_root / col / f"{num}.json"
    card_path.write_text(json.dumps(card_data))
    return card_path


def _make_card(col, session="test-session", criteria=None):
    """Build a minimal V4 card dict for the given column."""
    if criteria is None:
        criteria = [
            {"text": "Existing criterion", "mov_commands": [{"cmd": "true", "timeout": 5}], "met": True},
        ]
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
        "cycles": 0,
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


def _make_add_args(board_root, card_num="1", text="New criterion", mov_cmd=None, mov_timeout=None, session="test-session"):
    """Build a minimal args namespace for cmd_criteria_add."""
    return SimpleNamespace(
        root=str(board_root),
        card=str(card_num),
        text=text,
        mov_cmd=mov_cmd,
        mov_timeout=mov_timeout,
        session=session,
    )


# ---------------------------------------------------------------------------
# Regression tests: todo and doing cards are unaffected
# ---------------------------------------------------------------------------

class TestCriteriaAddRegressionNonDoneCards:
    """criteria add on todo/doing cards: appends criterion, status unchanged."""

    def test_criteria_add_on_todo_card_appends_criterion(self, kanban, tmp_path):
        """Appending to a todo card leaves the card in todo."""
        board = _setup_board(tmp_path)
        card_data = _make_card("todo")
        card_path = _write_card(board, "todo", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    kanban.cmd_criteria_add(args)

        # Card file must remain in todo (not moved)
        assert card_path.exists(), "Card file must remain in todo/ after criteria add"
        assert not (board / "doing" / "1.json").exists(), "Card must NOT be moved to doing/ for a todo card"

        on_disk = json.loads(card_path.read_text())
        texts = [c["text"] for c in on_disk["criteria"]]
        assert "New AC" in texts, "New criterion must be appended"

    def test_criteria_add_on_todo_card_status_unchanged(self, kanban, tmp_path):
        """criteria add on a todo card does not emit an auto-reopen warning."""
        board = _setup_board(tmp_path)
        card_data = _make_card("todo")
        card_path = _write_card(board, "todo", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    stderr_capture = io.StringIO()
                    with patch("sys.stderr", stderr_capture):
                        kanban.cmd_criteria_add(args)

        assert "auto-reopened" not in stderr_capture.getvalue(), (
            "No auto-reopen warning must be emitted for a todo card"
        )

    def test_criteria_add_on_doing_card_appends_criterion(self, kanban, tmp_path):
        """Appending to a doing card leaves the card in doing."""
        board = _setup_board(tmp_path)
        card_data = _make_card("doing")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    kanban.cmd_criteria_add(args)

        assert card_path.exists(), "Card file must remain in doing/ after criteria add"
        assert not (board / "done" / "1.json").exists(), "Card must NOT be moved to done/ for a doing card"

        on_disk = json.loads(card_path.read_text())
        texts = [c["text"] for c in on_disk["criteria"]]
        assert "New AC" in texts, "New criterion must be appended"

    def test_criteria_add_on_doing_card_status_unchanged(self, kanban, tmp_path):
        """criteria add on a doing card does not emit an auto-reopen warning."""
        board = _setup_board(tmp_path)
        card_data = _make_card("doing")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    stderr_capture = io.StringIO()
                    with patch("sys.stderr", stderr_capture):
                        kanban.cmd_criteria_add(args)

        assert "auto-reopened" not in stderr_capture.getvalue(), (
            "No auto-reopen warning must be emitted for a doing card"
        )


# ---------------------------------------------------------------------------
# New behavior: done card is auto-reopened
# ---------------------------------------------------------------------------

class TestCriteriaAddAutoReopenDoneCard:
    """criteria add on a done card: auto-reopens to doing, appends criterion, warns."""

    def test_criteria_add_on_done_card_moves_to_doing(self, kanban, tmp_path):
        """criteria add on a done card transitions the card file to doing/."""
        board = _setup_board(tmp_path)
        card_data = _make_card("done")
        card_path = _write_card(board, "done", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        kanban.cmd_criteria_add(args)

        doing_path = board / "doing" / "1.json"
        done_path = board / "done" / "1.json"

        assert doing_path.exists(), "Card must be present in doing/ after auto-reopen"
        assert not done_path.exists(), "Card must be removed from done/ after auto-reopen"

    def test_criteria_add_on_done_card_appends_new_criterion(self, kanban, tmp_path):
        """The new criterion is appended to the card after auto-reopen."""
        board = _setup_board(tmp_path)
        card_data = _make_card("done")
        card_path = _write_card(board, "done", "1", card_data)
        args = _make_add_args(board, card_num="1", text="Brand new AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        kanban.cmd_criteria_add(args)

        doing_path = board / "doing" / "1.json"
        on_disk = json.loads(doing_path.read_text())
        texts = [c["text"] for c in on_disk["criteria"]]
        assert "Brand new AC" in texts, "New criterion must appear in the reopened card"

    def test_criteria_add_on_done_card_new_criterion_has_met_false(self, kanban, tmp_path):
        """The new criterion added during auto-reopen has met=False."""
        board = _setup_board(tmp_path)
        card_data = _make_card("done")
        card_path = _write_card(board, "done", "1", card_data)
        args = _make_add_args(board, card_num="1", text="Unverified AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        kanban.cmd_criteria_add(args)

        doing_path = board / "doing" / "1.json"
        on_disk = json.loads(doing_path.read_text())
        new_criterion = next(c for c in on_disk["criteria"] if c["text"] == "Unverified AC")
        assert new_criterion["met"] is False, "Newly added criterion must have met=False"

    def test_criteria_add_on_done_card_emits_warning_to_stderr(self, kanban, tmp_path):
        """criteria add on a done card emits an auto-reopen warning to stderr."""
        board = _setup_board(tmp_path)
        card_data = _make_card("done")
        card_path = _write_card(board, "done", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        stderr_capture = io.StringIO()
        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", stderr_capture):
                        kanban.cmd_criteria_add(args)

        captured_err = stderr_capture.getvalue()
        assert "auto-reopened" in captured_err, (
            f"Expected 'auto-reopened' in stderr warning, got: {captured_err!r}"
        )
        assert "new acceptance criterion was added after the card was already marked done" in captured_err, (
            f"Expected plain-language description in stderr warning, got: {captured_err!r}"
        )

    def test_criteria_add_on_done_card_preserves_existing_criteria(self, kanban, tmp_path):
        """Pre-existing criteria state (met=True) is preserved through auto-reopen."""
        board = _setup_board(tmp_path)
        # Card with one already-met criterion and one unmet criterion
        existing_criteria = [
            {"text": "Already met", "mov_commands": [{"cmd": "true", "timeout": 5}], "met": True},
            {"text": "Not met yet", "mov_commands": [{"cmd": "false", "timeout": 5}], "met": False},
        ]
        card_data = _make_card("done", criteria=existing_criteria)
        card_path = _write_card(board, "done", "1", card_data)
        args = _make_add_args(board, card_num="1", text="Brand new AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        kanban.cmd_criteria_add(args)

        doing_path = board / "doing" / "1.json"
        on_disk = json.loads(doing_path.read_text())
        criteria_by_text = {c["text"]: c for c in on_disk["criteria"]}

        assert criteria_by_text["Already met"]["met"] is True, (
            "Pre-existing met=True criterion must remain True after auto-reopen"
        )
        assert criteria_by_text["Not met yet"]["met"] is False, (
            "Pre-existing met=False criterion must remain False after auto-reopen"
        )
        assert "Brand new AC" in criteria_by_text, (
            "New criterion must be appended during auto-reopen"
        )
        assert criteria_by_text["Brand new AC"]["met"] is False, (
            "New criterion must start with met=False"
        )

    def test_criteria_add_on_done_card_total_criterion_count(self, kanban, tmp_path):
        """After auto-reopen, the card has exactly one more criterion than before."""
        board = _setup_board(tmp_path)
        existing_criteria = [
            {"text": "AC 1", "mov_commands": [{"cmd": "true", "timeout": 5}], "met": True},
            {"text": "AC 2", "mov_commands": [{"cmd": "true", "timeout": 5}], "met": True},
        ]
        card_data = _make_card("done", criteria=existing_criteria)
        card_path = _write_card(board, "done", "1", card_data)
        args = _make_add_args(board, card_num="1", text="AC 3", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        kanban.cmd_criteria_add(args)

        doing_path = board / "doing" / "1.json"
        on_disk = json.loads(doing_path.read_text())
        assert len(on_disk["criteria"]) == 3, (
            f"Expected 3 criteria after adding 1 to a done card with 2, got {len(on_disk['criteria'])}"
        )


# ---------------------------------------------------------------------------
# Canceled card guard: criteria add on a canceled card must error out
# ---------------------------------------------------------------------------

class TestCriteriaAddCanceledCard:
    """criteria add on a canceled card must exit 1 with a clear error message."""

    def test_criteria_add_on_canceled_card_exits_with_error(self, kanban, tmp_path):
        """criteria add on a canceled card must exit 1."""
        board = _setup_board(tmp_path)
        card_data = _make_card("canceled")
        card_path = _write_card(board, "canceled", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        with pytest.raises(SystemExit) as exc_info:
                            kanban.cmd_criteria_add(args)

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for canceled card, got {exc_info.value.code}"
        )

    def test_criteria_add_on_canceled_card_emits_error_to_stderr(self, kanban, tmp_path):
        """criteria add on a canceled card must emit an error message mentioning canceled."""
        board = _setup_board(tmp_path)
        card_data = _make_card("canceled")
        card_path = _write_card(board, "canceled", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        stderr_capture = io.StringIO()
        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", stderr_capture):
                        with pytest.raises(SystemExit):
                            kanban.cmd_criteria_add(args)

        captured_err = stderr_capture.getvalue()
        assert "canceled" in captured_err.lower(), (
            f"Expected error message mentioning 'canceled', got: {captured_err!r}"
        )
        assert "intentionally closed" in captured_err.lower(), (
            f"Expected error message mentioning 'intentionally closed', got: {captured_err!r}"
        )

    def test_criteria_add_on_canceled_card_does_not_append_criterion(self, kanban, tmp_path):
        """criteria add on a canceled card must NOT append the criterion."""
        board = _setup_board(tmp_path)
        card_data = _make_card("canceled")
        original_criteria_count = len(card_data["criteria"])
        card_path = _write_card(board, "canceled", "1", card_data)
        args = _make_add_args(board, card_num="1", text="Should not appear", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        with pytest.raises(SystemExit):
                            kanban.cmd_criteria_add(args)

        on_disk = json.loads(card_path.read_text())
        assert len(on_disk["criteria"]) == original_criteria_count, (
            "Criterion must NOT be appended to a canceled card"
        )
        texts = [c["text"] for c in on_disk["criteria"]]
        assert "Should not appear" not in texts, (
            "New criterion text must not appear in a canceled card's criteria"
        )

    def test_criteria_add_on_canceled_card_does_not_move_card(self, kanban, tmp_path):
        """criteria add on a canceled card must NOT move the card to any other column."""
        board = _setup_board(tmp_path)
        card_data = _make_card("canceled")
        card_path = _write_card(board, "canceled", "1", card_data)
        args = _make_add_args(board, card_num="1", text="New AC", mov_cmd=["true"], mov_timeout=[5])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        with pytest.raises(SystemExit):
                            kanban.cmd_criteria_add(args)

        assert card_path.exists(), "Card must remain in canceled/ after failed criteria add"
        assert not (board / "doing" / "1.json").exists(), "Card must NOT be moved to doing/"
        assert not (board / "done" / "1.json").exists(), "Card must NOT be moved to done/"
        assert not (board / "todo" / "1.json").exists(), "Card must NOT be moved to todo/"
