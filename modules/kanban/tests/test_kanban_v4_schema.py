"""
Tests for V4 schema migration and cmd_done exit code behavior.

Covers:
- V4 migration: agent_met -> met, reviewer_met dropped, review_cycles -> cycles
- cmd_done exits 0 when all criteria are met
- cmd_done exits 1 (retryable) when criteria are unchecked (first and second attempt)
- cmd_done exits 2 (max cycles) on the 3rd call with unchecked criteria
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

    spec = importlib.util.spec_from_file_location("kanban_v4_schema", _KANBAN_PATH)
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


def _make_v3_card(action="Do the thing", session="test-session", all_agent_met=True):
    """Build a V3 card dict with agent_met/reviewer_met schema."""
    return {
        "action": action,
        "intent": "Because reasons",
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": [],
        "readFiles": [],
        "criteria": [
            {
                "text": "First criterion",
                "agent_met": all_agent_met,
                "reviewer_met": "pass" if all_agent_met else None,
            },
            {
                "text": "Second criterion",
                "agent_met": all_agent_met,
                "reviewer_met": None,
            },
        ],
        "review_cycles": 2,
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


def _make_v4_card_with_unchecked(action="Do the thing", session="test-session", cycles=0):
    """Build a V4 card with unchecked criteria in doing column."""
    return {
        "action": action,
        "intent": "Because reasons",
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": [],
        "readFiles": [],
        "criteria": [
            {"text": "Unchecked criterion", "met": False},
        ],
        "cycles": cycles,
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


def _make_v4_card_all_met(action="Do the thing", session="test-session"):
    """Build a V4 card with all criteria met in doing column."""
    return {
        "action": action,
        "intent": "Because reasons",
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": [],
        "readFiles": [],
        "criteria": [
            {"text": "Met criterion", "met": True},
        ],
        "cycles": 0,
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


def _make_done_args(board_root, card_num="1", message=None):
    """Build a minimal args namespace for cmd_done."""
    return SimpleNamespace(
        root=str(board_root),
        card=str(card_num),
        message=message,
        session="test-session",
    )


# ---------------------------------------------------------------------------
# Tests: V4 migration
# ---------------------------------------------------------------------------

class TestV4Migration:
    """V4 migration correctly transforms V3 cards."""

    def test_v4_migration_renames_agent_met_to_met(self, kanban, tmp_path):
        """V3 agent_met field is renamed to met on migration."""
        board = _setup_board(tmp_path)
        v3_card = _make_v3_card(all_agent_met=True)
        card_path = _write_card(board, "doing", "1", v3_card)

        # Read triggers migration
        migrated = kanban.read_card(card_path)

        for criterion in migrated["criteria"]:
            assert "met" in criterion, "met field must be present after migration"
            assert "agent_met" not in criterion, "agent_met must be removed after migration"

    def test_v4_migration_removes_reviewer_met(self, kanban, tmp_path):
        """V3 reviewer_met field is removed on migration."""
        board = _setup_board(tmp_path)
        v3_card = _make_v3_card(all_agent_met=True)
        card_path = _write_card(board, "doing", "1", v3_card)

        migrated = kanban.read_card(card_path)

        for criterion in migrated["criteria"]:
            assert "reviewer_met" not in criterion, "reviewer_met must be removed after migration"

    def test_v4_migration_preserves_agent_met_value_as_met(self, kanban, tmp_path):
        """V3 agent_met=True becomes met=True; agent_met=False becomes met=False."""
        board = _setup_board(tmp_path)
        v3_card = {
            "action": "Do the thing",
            "intent": "Because reasons",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [
                {"text": "Checked", "agent_met": True, "reviewer_met": "pass"},
                {"text": "Unchecked", "agent_met": False, "reviewer_met": None},
            ],
            "activity": [],
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        }
        card_path = _write_card(board, "doing", "1", v3_card)

        migrated = kanban.read_card(card_path)

        assert migrated["criteria"][0]["met"] is True, "agent_met=True must become met=True"
        assert migrated["criteria"][1]["met"] is False, "agent_met=False must become met=False"

    def test_v4_migration_renames_review_cycles_to_cycles(self, kanban, tmp_path):
        """V3 review_cycles field is renamed to cycles on migration."""
        board = _setup_board(tmp_path)
        v3_card = _make_v3_card(all_agent_met=True)
        assert v3_card["review_cycles"] == 2
        card_path = _write_card(board, "doing", "1", v3_card)

        migrated = kanban.read_card(card_path)

        assert "cycles" in migrated, "cycles field must be present after migration"
        assert migrated["cycles"] == 2, "cycles must equal the old review_cycles value"
        assert "review_cycles" not in migrated, "review_cycles must be removed after migration"

    def test_v4_migration_persists_to_disk(self, kanban, tmp_path):
        """Migration is written back to disk so subsequent reads are idempotent."""
        board = _setup_board(tmp_path)
        v3_card = _make_v3_card(all_agent_met=True)
        card_path = _write_card(board, "doing", "1", v3_card)

        # First read triggers migration and write
        kanban.read_card(card_path)

        # Second read should see already-migrated card (no agent_met)
        raw = json.loads(card_path.read_text())
        assert "agent_met" not in raw["criteria"][0], (
            "Migrated card on disk must not contain agent_met"
        )
        assert "met" in raw["criteria"][0], (
            "Migrated card on disk must contain met"
        )


# ---------------------------------------------------------------------------
# Tests: cmd_done exit codes
# ---------------------------------------------------------------------------

class TestCmdDoneExitCodes:
    """cmd_done returns correct exit codes based on criteria state and cycle count."""

    def test_cmd_done_exits_0_when_all_criteria_met(self, kanban, tmp_path):
        """cmd_done exits 0 when all criteria have met=True."""
        board = _setup_board(tmp_path)
        card_data = _make_v4_card_all_met(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_done_args(board, card_num="1")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch.object(kanban, "write_kanban_event"):
                    with patch("sys.stdout", io.StringIO()):
                        # Should not raise SystemExit
                        try:
                            kanban.cmd_done(args)
                        except SystemExit as e:
                            pytest.fail(f"cmd_done raised SystemExit({e.code}) — expected 0 (no exception)")

        # Card should be moved to done
        done_path = board / "done" / "1.json"
        assert done_path.exists(), "Card must be moved to done/ on success"

    def test_cmd_done_exits_1_on_first_unchecked_attempt(self, kanban, tmp_path):
        """cmd_done exits 1 (retryable) when criteria unchecked and cycles < MAX_CYCLES."""
        board = _setup_board(tmp_path)
        card_data = _make_v4_card_with_unchecked(session="test-session", cycles=0)
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_done_args(board, card_num="1")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit) as exc_info:
                    kanban.cmd_done(args)

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 (retryable) on first attempt, got {exc_info.value.code}"
        )

    def test_cmd_done_exits_1_on_second_unchecked_attempt(self, kanban, tmp_path):
        """cmd_done exits 1 (retryable) on second attempt when cycles < MAX_CYCLES."""
        board = _setup_board(tmp_path)
        # Start with cycles=1 (one attempt already made)
        card_data = _make_v4_card_with_unchecked(session="test-session", cycles=1)
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_done_args(board, card_num="1")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit) as exc_info:
                    kanban.cmd_done(args)

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 (retryable) on second attempt, got {exc_info.value.code}"
        )

    def test_cmd_done_exits_2_when_max_cycles_reached(self, kanban, tmp_path):
        """cmd_done exits 2 when cycles reaches MAX_CYCLES."""
        board = _setup_board(tmp_path)
        # Start with cycles=MAX_CYCLES-1 so next attempt hits the limit
        max_cycles = kanban.MAX_CYCLES
        card_data = _make_v4_card_with_unchecked(session="test-session", cycles=max_cycles - 1)
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_done_args(board, card_num="1")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit) as exc_info:
                    kanban.cmd_done(args)

        assert exc_info.value.code == 2, (
            f"Expected exit code 2 (max cycles) when cycles={max_cycles}, got {exc_info.value.code}"
        )

    def test_cmd_done_3_attempts_with_unchecked_exits_2_on_third(self, kanban, tmp_path):
        """Calling cmd_done 3 times with unchecked criteria results in exit 2 on 3rd call.

        MAX_CYCLES=3: first call exits 1 (cycles=1), second exits 1 (cycles=2),
        third exits 2 (cycles=3 >= MAX_CYCLES).
        """
        board = _setup_board(tmp_path)
        card_data = _make_v4_card_with_unchecked(session="test-session", cycles=0)
        card_path = _write_card(board, "doing", "1", card_data)

        exit_codes = []
        for attempt in range(3):
            args = _make_done_args(board, card_num="1")
            with patch.object(kanban, "get_root", return_value=board):
                with patch.object(kanban, "find_card", return_value=card_path):
                    try:
                        kanban.cmd_done(args)
                        exit_codes.append(0)
                    except SystemExit as e:
                        exit_codes.append(e.code)

        assert exit_codes[0] == 1, f"Attempt 1: expected exit 1, got {exit_codes[0]}"
        assert exit_codes[1] == 1, f"Attempt 2: expected exit 1, got {exit_codes[1]}"
        assert exit_codes[2] == 2, f"Attempt 3: expected exit 2, got {exit_codes[2]}"

    def test_cmd_done_increments_cycles_on_blocked_attempt(self, kanban, tmp_path):
        """Each blocked cmd_done call increments the cycles counter on the card."""
        board = _setup_board(tmp_path)
        card_data = _make_v4_card_with_unchecked(session="test-session", cycles=0)
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_done_args(board, card_num="1")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit):
                    kanban.cmd_done(args)

        # Card on disk should have cycles=1
        updated_card = json.loads(card_path.read_text())
        assert updated_card.get("cycles") == 1, (
            f"cycles must be 1 after first blocked attempt, got {updated_card.get('cycles')}"
        )

    def test_max_cycles_constant_is_3(self, kanban):
        """MAX_CYCLES constant is defined and equals 3."""
        assert hasattr(kanban, "MAX_CYCLES"), "MAX_CYCLES constant must be defined"
        assert kanban.MAX_CYCLES == 3, f"MAX_CYCLES must be 3, got {kanban.MAX_CYCLES}"
