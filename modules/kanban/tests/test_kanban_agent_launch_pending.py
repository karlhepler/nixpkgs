"""
CLI-side tests for agent_launch_pending field set/clear paths.

Covers gaps identified in ai-expert F6 and swe-devex review:
- cmd_do single-card: sets flag = True
- cmd_do bulk array: sets flag = True on all
- cmd_do conflict path → todo: flag NOT set
- cmd_start: sets flag = True after rename (atomicity: flag written to doing/, not todo/)
- cmd_start with non-todo card: error path (exits 1)
- cmd_clear_agent_launch_pending: clears flag
- cmd_clear_agent_launch_pending on non-doing card: rejected (column guard)
- cmd_clear_agent_launch_pending on missing card: graceful error
- backward compat: read_card sets flag to False via setdefault on legacy cards
- cmd_defer clears agent_launch_pending before moving to todo
"""

import importlib.util
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

    spec = importlib.util.spec_from_file_location("kanban_alp", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
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


def _make_valid_card_json(edit_files=None):
    """Build a minimal valid single-card JSON string for cmd_do."""
    card = {
        "action": "Do the thing",
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-devex",
        "criteria": [
            {
                "text": "Some check",
                "mov_type": "programmatic",
                "mov_commands": [{"cmd": "true", "timeout": 5}],
                "met": False,
            }
        ],
    }
    if edit_files is not None:
        card["editFiles"] = edit_files
    return json.dumps(card)


def _make_valid_bulk_card_json(n=2):
    """Build a minimal valid bulk-array JSON string for cmd_do."""
    cards = [
        {
            "action": f"Do the thing {i}",
            "intent": "Because reasons",
            "type": "work",
            "agent": "swe-devex",
            "criteria": [
                {
                    "text": "Some check",
                    "mov_type": "programmatic",
                    "mov_commands": [{"cmd": "true", "timeout": 5}],
                    "met": False,
                }
            ],
        }
        for i in range(n)
    ]
    return json.dumps(cards)


def _make_do_args(board_root, json_data, session="test-session"):
    return SimpleNamespace(
        root=str(board_root),
        json_data=json_data,
        json_file=None,
        session=session,
    )


def _make_start_args(board_root, card_num, session="test-session"):
    return SimpleNamespace(
        root=str(board_root),
        card=[card_num],
        session=session,
    )


def _make_clear_alp_args(board_root, card_num, session="test-session"):
    return SimpleNamespace(
        root=str(board_root),
        card=card_num,
        session=session,
    )


def _make_defer_args(board_root, card_num, session="test-session"):
    return SimpleNamespace(
        root=str(board_root),
        card=[card_num],
        session=session,
    )


def _minimal_doing_card(num_str, agent_launch_pending=True, session="test-session"):
    return {
        "action": "Work in progress",
        "intent": "Agent was launched",
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "session": session,
        "editFiles": [],
        "readFiles": [],
        "criteria": [{"text": "check", "met": False}],
        "cycles": 0,
        "agent_launch_pending": agent_launch_pending,
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "activity": [],
    }


def _minimal_todo_card(num_str, agent_launch_pending=False, session="test-session"):
    return {
        "action": "Queued work",
        "intent": "Waiting to start",
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "session": session,
        "editFiles": [],
        "readFiles": [],
        "criteria": [{"text": "check", "met": False}],
        "cycles": 0,
        "agent_launch_pending": agent_launch_pending,
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "activity": [],
    }


# ---------------------------------------------------------------------------
# cmd_do: single-card sets flag = True
# ---------------------------------------------------------------------------

class TestCmdDoSetsFlag:
    def test_cmd_do_single_card_sets_agent_launch_pending_true(self, kanban, tmp_path):
        """cmd_do single-card path sets agent_launch_pending=True on doing card."""
        board = _setup_board(tmp_path)
        args = _make_do_args(board, _make_valid_card_json())

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 1
        card_data = json.loads(doing_cards[0].read_text())
        assert card_data.get("agent_launch_pending") is True, (
            f"cmd_do must set agent_launch_pending=True, got {card_data.get('agent_launch_pending')!r}"
        )

    def test_cmd_do_bulk_array_sets_agent_launch_pending_true_on_all(self, kanban, tmp_path):
        """cmd_do bulk-array path sets agent_launch_pending=True on all doing cards."""
        board = _setup_board(tmp_path)
        args = _make_do_args(board, _make_valid_bulk_card_json(n=3))

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 3, f"Expected 3 doing cards, got {len(doing_cards)}"
        for card_path in doing_cards:
            card_data = json.loads(card_path.read_text())
            assert card_data.get("agent_launch_pending") is True, (
                f"Bulk cmd_do must set agent_launch_pending=True on all doing cards, "
                f"got {card_data.get('agent_launch_pending')!r} for {card_path.name}"
            )

    def test_cmd_do_conflict_path_does_not_set_flag_true(self, kanban, tmp_path):
        """cmd_do conflict path defers card to todo and does NOT set agent_launch_pending=True."""
        board = _setup_board(tmp_path)

        # Pre-existing in-flight card owning the conflicting file
        inflight = _minimal_doing_card("99", agent_launch_pending=False)
        inflight["editFiles"] = ["modules/kanban/kanban.py"]
        _write_card(board, "doing", "99", inflight)

        args = _make_do_args(
            board,
            _make_valid_card_json(edit_files=["modules/kanban/kanban.py"]),
        )

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1

        todo_cards = list((board / "todo").glob("*.json"))
        assert len(todo_cards) == 1, f"Expected 1 todo card, got {len(todo_cards)}"
        card_data = json.loads(todo_cards[0].read_text())
        assert card_data.get("agent_launch_pending") is not True, (
            "Conflict-deferred card in todo must NOT have agent_launch_pending=True"
        )


# ---------------------------------------------------------------------------
# cmd_start: sets flag after rename (atomicity)
# ---------------------------------------------------------------------------

class TestCmdStartSetsFlag:
    def test_cmd_start_sets_agent_launch_pending_true_in_doing(self, kanban, tmp_path):
        """cmd_start moves card and writes agent_launch_pending=True only to doing path."""
        board = _setup_board(tmp_path)
        card_path = _write_card(board, "todo", "10", _minimal_todo_card("10"))
        args = _make_start_args(board, card_num="10")

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        # Card must be in doing, not todo
        assert not (board / "todo" / "10.json").exists(), "Card must not remain in todo after cmd_start"
        doing_path = board / "doing" / "10.json"
        assert doing_path.exists(), "Card must be in doing after cmd_start"
        card_data = json.loads(doing_path.read_text())
        assert card_data.get("agent_launch_pending") is True, (
            f"cmd_start must set agent_launch_pending=True in doing card, "
            f"got {card_data.get('agent_launch_pending')!r}"
        )

    def test_cmd_start_with_non_todo_card_exits_error(self, kanban, tmp_path):
        """cmd_start rejects cards not in todo with exit code 1."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "20", _minimal_doing_card("20"))
        args = _make_start_args(board, card_num="20")

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_start(args)

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# cmd_clear_agent_launch_pending: clears flag, column guard, missing card
# ---------------------------------------------------------------------------

class TestCmdClearAgentLaunchPending:
    def test_clears_flag_on_doing_card(self, kanban, tmp_path):
        """cmd_clear_agent_launch_pending sets agent_launch_pending=False on doing card."""
        board = _setup_board(tmp_path)
        card_path = _write_card(board, "doing", "30", _minimal_doing_card("30", agent_launch_pending=True))
        args = _make_clear_alp_args(board, card_num="30")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                kanban.cmd_clear_agent_launch_pending(args)

        card_data = json.loads(card_path.read_text())
        assert card_data.get("agent_launch_pending") is False, (
            f"cmd_clear_agent_launch_pending must set flag to False, "
            f"got {card_data.get('agent_launch_pending')!r}"
        )

    def test_column_guard_rejects_todo_card(self, kanban, tmp_path):
        """cmd_clear_agent_launch_pending exits 1 when card is not in doing (todo)."""
        board = _setup_board(tmp_path)
        card_path = _write_card(board, "todo", "40", _minimal_todo_card("40"))
        args = _make_clear_alp_args(board, card_num="40")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit) as exc_info:
                    kanban.cmd_clear_agent_launch_pending(args)

        assert exc_info.value.code == 1

    def test_column_guard_rejects_done_card(self, kanban, tmp_path):
        """cmd_clear_agent_launch_pending exits 1 when card is in done."""
        board = _setup_board(tmp_path)
        done_card = _minimal_doing_card("41", agent_launch_pending=False)
        card_path = _write_card(board, "done", "41", done_card)
        args = _make_clear_alp_args(board, card_num="41")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit) as exc_info:
                    kanban.cmd_clear_agent_launch_pending(args)

        assert exc_info.value.code == 1

    def test_missing_card_exits_gracefully(self, kanban, tmp_path):
        """cmd_clear_agent_launch_pending exits non-zero when card not found."""
        board = _setup_board(tmp_path)
        args = _make_clear_alp_args(board, card_num="9999")

        # find_card calls sys.exit(1) when card not found — confirm that behavior
        with pytest.raises(SystemExit) as exc_info:
            kanban.cmd_clear_agent_launch_pending(args)

        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# backward compat: read_card setdefault
# ---------------------------------------------------------------------------

class TestReadCardBackwardCompat:
    def test_read_card_sets_default_false_on_legacy_card(self, kanban, tmp_path):
        """read_card adds agent_launch_pending=False on cards that lack the field."""
        board = _setup_board(tmp_path)
        legacy_card = {
            "action": "Old card",
            "intent": "No agent_launch_pending field",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "session": "test-session",
            "editFiles": [],
            "readFiles": [],
            "criteria": [{"text": "check", "met": False}],
            "cycles": 0,
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "activity": [],
        }
        card_path = _write_card(board, "doing", "50", legacy_card)

        card_data = kanban.read_card(card_path)

        assert "agent_launch_pending" in card_data, (
            "read_card must inject agent_launch_pending key on legacy cards"
        )
        assert card_data["agent_launch_pending"] is False, (
            f"read_card must default agent_launch_pending=False, "
            f"got {card_data['agent_launch_pending']!r}"
        )


# ---------------------------------------------------------------------------
# cmd_defer: clears agent_launch_pending before moving to todo
# ---------------------------------------------------------------------------

class TestCmdDeferClearsFlag:
    def test_defer_clears_agent_launch_pending(self, kanban, tmp_path):
        """cmd_defer sets agent_launch_pending=False before moving card to todo."""
        board = _setup_board(tmp_path)
        # Card in doing with pending flag still set (coordinator deferred before hook fired)
        card_path = _write_card(board, "doing", "60", _minimal_doing_card("60", agent_launch_pending=True))
        args = _make_defer_args(board, card_num="60")

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_defer(args)

        # Card must be in todo with flag cleared
        todo_path = board / "todo" / "60.json"
        assert todo_path.exists(), "Deferred card must be in todo"
        card_data = json.loads(todo_path.read_text())
        assert card_data.get("agent_launch_pending") is False, (
            f"cmd_defer must clear agent_launch_pending before moving to todo, "
            f"got {card_data.get('agent_launch_pending')!r}"
        )
