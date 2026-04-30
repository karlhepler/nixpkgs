"""
Tests for editFiles overlap detection in cmd_do and cmd_start.

Covers:
- _globs_overlap: exact match, glob match, no match
- check_editfiles_overlap: returns list of conflicts, skips self, empty editFiles
- cmd_do with empty editFiles → no check, succeeds
- cmd_do with editFiles overlapping an existing doing card (same session) → exit 1
- cmd_do with editFiles overlapping an existing doing card (different session) → exit 1
- cmd_do with --force flag and overlap → succeeds, card metadata records forced=true
- cmd_start same conditions as above
- Glob overlap: card with src/foo.ts conflicts with card with src/*.ts
- Glob overlap: card with **/*.ts conflicts with card with src/foo.ts
- todo cards do NOT block (only doing cards count)
- canceled cards do NOT block
- done cards do NOT block
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

    spec = importlib.util.spec_from_file_location("kanban_overlap", _KANBAN_PATH)
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


def _make_card_json(edit_files=None, action="Do the thing"):
    """Build a minimal valid single-card JSON string for cmd_do."""
    card = {
        "action": action,
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


def _make_do_args(board_root, json_data, session="test-session", force=False):
    return SimpleNamespace(
        root=str(board_root),
        json_data=json_data,
        json_file=None,
        session=session,
        force=force,
    )


def _make_start_args(board_root, card_num, session="test-session", force=False):
    return SimpleNamespace(
        root=str(board_root),
        card=[card_num],
        session=session,
        force=force,
    )


def _minimal_doing_card(edit_files=None, session="test-session"):
    return {
        "action": "In-flight work",
        "intent": "Active agent",
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "session": session,
        "editFiles": edit_files or [],
        "readFiles": [],
        "criteria": [{"text": "check", "met": False}],
        "cycles": 0,
        "agent_launch_pending": True,
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "activity": [],
    }


def _minimal_todo_card(edit_files=None, session="test-session"):
    return {
        "action": "Queued work",
        "intent": "Waiting to start",
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "session": session,
        "editFiles": edit_files or [],
        "readFiles": [],
        "criteria": [{"text": "check", "met": False}],
        "cycles": 0,
        "agent_launch_pending": False,
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "activity": [],
    }


# ---------------------------------------------------------------------------
# Tests: _globs_overlap helper
# ---------------------------------------------------------------------------

class TestGlobsOverlap:
    def test_exact_match_returns_overlap(self, kanban):
        """Two identical paths overlap."""
        result = kanban._globs_overlap(["src/foo.ts"], ["src/foo.ts"])
        assert result == ["src/foo.ts"]

    def test_glob_a_matches_b_returns_overlap(self, kanban):
        """A glob in list_a matches a concrete path in list_b."""
        result = kanban._globs_overlap(["src/*.ts"], ["src/foo.ts"])
        assert result == ["src/*.ts"]

    def test_glob_b_matches_a_returns_overlap(self, kanban):
        """A glob in list_b matches a concrete path in list_a."""
        result = kanban._globs_overlap(["src/foo.ts"], ["src/*.ts"])
        assert result == ["src/foo.ts"]

    def test_double_star_glob_matches_nested_path(self, kanban):
        """**/*.ts glob in list_a matches src/foo.ts in list_b."""
        result = kanban._globs_overlap(["**/*.ts"], ["src/foo.ts"])
        assert result == ["**/*.ts"]

    def test_no_match_returns_empty(self, kanban):
        """Paths that don't overlap return empty list."""
        result = kanban._globs_overlap(["src/foo.ts"], ["src/bar.py"])
        assert result == []

    def test_empty_inputs_return_empty(self, kanban):
        """Empty input lists return empty result."""
        assert kanban._globs_overlap([], ["src/foo.ts"]) == []
        assert kanban._globs_overlap(["src/foo.ts"], []) == []
        assert kanban._globs_overlap([], []) == []

    def test_multiple_overlapping_entries(self, kanban):
        """Multiple overlapping entries each appear in the result."""
        result = kanban._globs_overlap(
            ["src/foo.ts", "src/bar.ts"],
            ["src/*.ts"],
        )
        assert "src/foo.ts" in result
        assert "src/bar.ts" in result

    def test_partial_overlap_only_matching_returned(self, kanban):
        """Only the overlapping entries from list_a are returned."""
        result = kanban._globs_overlap(
            ["src/foo.ts", "README.md"],
            ["src/*.ts"],
        )
        assert "src/foo.ts" in result
        assert "README.md" not in result


# ---------------------------------------------------------------------------
# Tests: check_editfiles_overlap
# ---------------------------------------------------------------------------

class TestCheckEditfilesOverlap:
    def test_empty_edit_files_returns_no_conflicts(self, kanban):
        """Card with no editFiles never conflicts."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["src/foo.ts"]},
        ]
        result = kanban.check_editfiles_overlap("200", [], doing_cards)
        assert result == []

    def test_conflict_same_session_detected(self, kanban):
        """Overlapping editFiles from same session are detected."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["src/foo.ts"]},
        ]
        result = kanban.check_editfiles_overlap("200", ["src/foo.ts"], doing_cards)
        assert len(result) == 1
        card_id, session, files = result[0]
        assert card_id == "100"
        assert session == "sess-a"
        assert "src/foo.ts" in files

    def test_conflict_different_session_detected(self, kanban):
        """Overlapping editFiles from different session are detected."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["src/foo.ts"]},
        ]
        result = kanban.check_editfiles_overlap("200", ["src/foo.ts"], doing_cards)
        assert len(result) == 1
        _, session, _ = result[0]
        assert session == "sess-a"

    def test_self_excluded_from_scan(self, kanban):
        """Card does not conflict with itself."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["src/foo.ts"]},
        ]
        result = kanban.check_editfiles_overlap("100", ["src/foo.ts"], doing_cards)
        assert result == []

    def test_no_overlap_returns_empty(self, kanban):
        """No conflict when editFiles don't overlap."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["src/bar.py"]},
        ]
        result = kanban.check_editfiles_overlap("200", ["src/foo.ts"], doing_cards)
        assert result == []

    def test_glob_overlap_detected(self, kanban):
        """Glob patterns in either card trigger conflict detection."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["src/*.ts"]},
        ]
        result = kanban.check_editfiles_overlap("200", ["src/foo.ts"], doing_cards)
        assert len(result) == 1

    def test_double_star_glob_detected(self, kanban):
        """**/*.ts glob pattern matches nested concrete paths."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["src/foo.ts"]},
        ]
        result = kanban.check_editfiles_overlap("200", ["**/*.ts"], doing_cards)
        assert len(result) == 1

    def test_doing_cards_with_empty_edit_files_no_conflict(self, kanban):
        """Doing cards with no editFiles don't conflict."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": []},
        ]
        result = kanban.check_editfiles_overlap("200", ["src/foo.ts"], doing_cards)
        assert result == []

    def test_multiple_conflicts_all_returned(self, kanban):
        """All conflicting doing cards are returned, not just the first."""
        doing_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["src/foo.ts"]},
            {"id": "101", "session": "sess-b", "editFiles": ["src/foo.ts"]},
        ]
        result = kanban.check_editfiles_overlap("200", ["src/foo.ts"], doing_cards)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests: cmd_do with empty editFiles
# ---------------------------------------------------------------------------

class TestCmdDoEmptyEditFiles:
    def test_cmd_do_empty_edit_files_succeeds(self, kanban, tmp_path):
        """cmd_do with no editFiles places card in doing without conflict check."""
        board = _setup_board(tmp_path)
        # Existing doing card with editFiles (should not matter)
        _write_card(board, "doing", "99", _minimal_doing_card(["src/foo.ts"]))

        args = _make_do_args(board, _make_card_json(edit_files=[]))

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 2, f"Expected 2 doing cards, got {len(doing_cards)}"


# ---------------------------------------------------------------------------
# Tests: cmd_do overlap detection
# ---------------------------------------------------------------------------

class TestCmdDoOverlapDetection:
    def test_cmd_do_overlap_same_session_exits_1(self, kanban, tmp_path):
        """cmd_do exits 1 when editFiles conflict with a doing card in the same session."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(
            ["src/api/auth.ts"], session="test-session"
        ))
        args = _make_do_args(
            board,
            _make_card_json(edit_files=["src/api/auth.ts"]),
            session="test-session",
        )

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        # Card deferred to todo
        todo_cards = list((board / "todo").glob("*.json"))
        assert len(todo_cards) == 1

    def test_cmd_do_overlap_different_session_exits_1(self, kanban, tmp_path):
        """cmd_do exits 1 when editFiles conflict with a doing card in a different session."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(
            ["src/api/auth.ts"], session="sess-a"
        ))
        args = _make_do_args(
            board,
            _make_card_json(edit_files=["src/api/auth.ts"]),
            session="sess-b",
        )

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1

    def test_cmd_do_force_flag_bypasses_overlap_check(self, kanban, tmp_path):
        """cmd_do with --force succeeds even when editFiles overlap exists."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(["src/api/auth.ts"]))
        args = _make_do_args(
            board,
            _make_card_json(edit_files=["src/api/auth.ts"]),
            force=True,
        )

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        new_cards = [c for c in doing_cards if c.name != "99.json"]
        assert len(new_cards) == 1, "New card must be placed in doing when --force is set"

    def test_cmd_do_force_sets_forced_true_on_card(self, kanban, tmp_path):
        """cmd_do with --force records forced=true on the card for audit trail."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(["src/api/auth.ts"]))
        args = _make_do_args(
            board,
            _make_card_json(edit_files=["src/api/auth.ts"]),
            force=True,
        )

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        new_cards = [c for c in doing_cards if c.name != "99.json"]
        assert len(new_cards) == 1
        card_data = json.loads(new_cards[0].read_text())
        assert card_data.get("forced") is True, (
            f"cmd_do with --force must set forced=true on card, "
            f"got {card_data.get('forced')!r}"
        )

    def test_cmd_do_no_overlap_no_forced_key(self, kanban, tmp_path):
        """cmd_do without conflicts does not set forced on card."""
        board = _setup_board(tmp_path)
        args = _make_do_args(board, _make_card_json(edit_files=["src/unique.ts"]))

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 1
        card_data = json.loads(doing_cards[0].read_text())
        assert card_data.get("forced") is not True, (
            "Card without conflict must not have forced=true"
        )


# ---------------------------------------------------------------------------
# Tests: cmd_start overlap detection
# ---------------------------------------------------------------------------

class TestCmdStartOverlapDetection:
    def test_cmd_start_overlap_same_session_exits_1(self, kanban, tmp_path):
        """cmd_start exits 1 when editFiles conflict with a doing card (same session)."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(
            ["src/api/auth.ts"], session="test-session"
        ))
        _write_card(board, "todo", "10", _minimal_todo_card(
            ["src/api/auth.ts"], session="test-session"
        ))
        args = _make_start_args(board, "10", session="test-session")

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_start(args)

        assert exc_info.value.code == 1
        # Card must remain in todo
        assert (board / "todo" / "10.json").exists(), "Card must stay in todo on conflict"

    def test_cmd_start_overlap_different_session_exits_1(self, kanban, tmp_path):
        """cmd_start exits 1 when editFiles conflict with a doing card (different session)."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(
            ["src/api/auth.ts"], session="sess-a"
        ))
        _write_card(board, "todo", "10", _minimal_todo_card(
            ["src/api/auth.ts"], session="sess-b"
        ))
        args = _make_start_args(board, "10", session="sess-b", force=False)

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_start(args)

        assert exc_info.value.code == 1

    def test_cmd_start_force_flag_bypasses_overlap_check(self, kanban, tmp_path):
        """cmd_start with --force succeeds even when editFiles overlap exists."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(["src/api/auth.ts"]))
        _write_card(board, "todo", "10", _minimal_todo_card(["src/api/auth.ts"]))
        args = _make_start_args(board, "10", force=True)

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        doing_path = board / "doing" / "10.json"
        assert doing_path.exists(), "Card must be in doing when --force bypasses conflict"

    def test_cmd_start_force_sets_forced_true_on_card(self, kanban, tmp_path):
        """cmd_start with --force records forced=true on the card for audit trail."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(["src/api/auth.ts"]))
        _write_card(board, "todo", "10", _minimal_todo_card(["src/api/auth.ts"]))
        args = _make_start_args(board, "10", force=True)

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        doing_path = board / "doing" / "10.json"
        assert doing_path.exists()
        card_data = json.loads(doing_path.read_text())
        assert card_data.get("forced") is True, (
            f"cmd_start with --force must set forced=true on card, "
            f"got {card_data.get('forced')!r}"
        )

    def test_cmd_start_empty_edit_files_succeeds(self, kanban, tmp_path):
        """cmd_start with no editFiles places card in doing without conflict check."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_doing_card(["src/foo.ts"]))
        _write_card(board, "todo", "10", _minimal_todo_card(edit_files=[]))
        args = _make_start_args(board, "10")

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        doing_path = board / "doing" / "10.json"
        assert doing_path.exists(), "Card with empty editFiles must proceed to doing"


# ---------------------------------------------------------------------------
# Tests: non-doing cards do NOT block
# ---------------------------------------------------------------------------

class TestNonDoingCardsDoNotBlock:
    def test_todo_cards_do_not_block_cmd_do(self, kanban, tmp_path):
        """Cards in todo column do not trigger overlap detection in cmd_do."""
        board = _setup_board(tmp_path)
        _write_card(board, "todo", "99", _minimal_todo_card(["src/api/auth.ts"]))
        args = _make_do_args(board, _make_card_json(edit_files=["src/api/auth.ts"]))

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 1, "cmd_do must succeed when conflict only in todo"

    def test_done_cards_do_not_block_cmd_do(self, kanban, tmp_path):
        """Cards in done column do not trigger overlap detection in cmd_do."""
        board = _setup_board(tmp_path)
        _write_card(board, "done", "99", _minimal_doing_card(["src/api/auth.ts"]))
        args = _make_do_args(board, _make_card_json(edit_files=["src/api/auth.ts"]))

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 1, "cmd_do must succeed when conflict only in done"

    def test_canceled_cards_do_not_block_cmd_do(self, kanban, tmp_path):
        """Cards in canceled column do not trigger overlap detection in cmd_do."""
        board = _setup_board(tmp_path)
        _write_card(board, "canceled", "99", _minimal_doing_card(["src/api/auth.ts"]))
        args = _make_do_args(board, _make_card_json(edit_files=["src/api/auth.ts"]))

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 1, "cmd_do must succeed when conflict only in canceled"

    def test_todo_cards_do_not_block_cmd_start(self, kanban, tmp_path):
        """Cards in todo column do not block cmd_start."""
        board = _setup_board(tmp_path)
        _write_card(board, "todo", "99", _minimal_todo_card(["src/api/auth.ts"]))
        _write_card(board, "todo", "10", _minimal_todo_card(["src/api/auth.ts"]))
        args = _make_start_args(board, "10")

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        doing_path = board / "doing" / "10.json"
        assert doing_path.exists(), "cmd_start must succeed when conflict only in todo"

    def test_done_cards_do_not_block_cmd_start(self, kanban, tmp_path):
        """Cards in done column do not block cmd_start."""
        board = _setup_board(tmp_path)
        _write_card(board, "done", "99", _minimal_doing_card(["src/api/auth.ts"]))
        _write_card(board, "todo", "10", _minimal_todo_card(["src/api/auth.ts"]))
        args = _make_start_args(board, "10")

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        doing_path = board / "doing" / "10.json"
        assert doing_path.exists(), "cmd_start must succeed when conflict only in done"

    def test_canceled_cards_do_not_block_cmd_start(self, kanban, tmp_path):
        """Cards in canceled column do not block cmd_start."""
        board = _setup_board(tmp_path)
        _write_card(board, "canceled", "99", _minimal_doing_card(["src/api/auth.ts"]))
        _write_card(board, "todo", "10", _minimal_todo_card(["src/api/auth.ts"]))
        args = _make_start_args(board, "10")

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        doing_path = board / "doing" / "10.json"
        assert doing_path.exists(), "cmd_start must succeed when conflict only in canceled"
