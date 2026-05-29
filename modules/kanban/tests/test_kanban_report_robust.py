"""
Regression tests for kanban report robust timestamp resolution.

The bug: cards in done/ lacking the explicit `updated` field were silently
skipped, producing empty output even when cards exist.

The fix (FIX A + FIX B):
- Timestamp resolution falls back to activity[-1]['timestamp'], then 'created'.
- Only when ALL three sources fail is a card skipped.
- Skipped cards produce a loud stderr warning ('kanban report: skipping').

Tests:
1. Card with 'updated' field surfaces in unfiltered report (existing behavior).
2. Card lacking 'updated' but with activity[] surfaces in unfiltered report.
3. Card lacking both 'updated' and activity[] but with 'created' surfaces.
4. Card lacking ALL three is skipped AND produces a stderr warning.
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
# Module loader (matches pattern from test_kanban_list_xml_schema.py)
# ---------------------------------------------------------------------------

_KANBAN_PATH = Path(__file__).parent.parent / "kanban.py"


def load_kanban():
    """Import kanban.py as a module with watchdog stubbed out."""
    watchdog_stub = MagicMock()
    sys.modules.setdefault("watchdog", watchdog_stub)
    sys.modules.setdefault("watchdog.observers", watchdog_stub)
    sys.modules.setdefault("watchdog.events", watchdog_stub)
    watchdog_stub.events.FileSystemEventHandler = object

    spec = importlib.util.spec_from_file_location("kanban_report_robust", _KANBAN_PATH)
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


def _make_report_args(root, from_date=None, to_date=None, output_style="human"):
    """Build a minimal args namespace for cmd_report."""
    return SimpleNamespace(
        root=str(root),
        from_date=from_date,
        to_date=to_date,
        output_style=output_style,
    )


def _run_cmd_report(kanban_mod, args, board_root):
    """Run cmd_report and return (stdout, stderr) as strings."""
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    with patch.object(kanban_mod, "get_root", return_value=board_root):
        with patch("sys.stdout", captured_out):
            with patch("sys.stderr", captured_err):
                kanban_mod.cmd_report(args)
    return captured_out.getvalue(), captured_err.getvalue()


# ---------------------------------------------------------------------------
# Test 1: card with 'updated' field — existing behavior preserved
# ---------------------------------------------------------------------------


class TestReportWithUpdatedField:
    """Card with explicit 'updated' field surfaces in report (existing behavior)."""

    def test_card_with_updated_appears_in_report(self, kanban, tmp_path):
        board = _setup_board(tmp_path)
        card = {
            "action": "Do the thing",
            "intent": "Because it matters",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            "activity": [
                {"timestamp": "2026-01-01T10:00:00Z", "message": "Created"},
                {"timestamp": "2026-01-02T12:00:00Z", "message": "Completed"},
            ],
            "created": "2026-01-01T10:00:00Z",
            "updated": "2026-01-02T12:00:00Z",
        }
        _write_card(board, "done", "101", card)
        args = _make_report_args(board)
        stdout, stderr = _run_cmd_report(kanban, args, board)

        # Card must appear in output; stderr must be clean
        assert "101" in stdout, "Card number must appear in human-readable report"
        assert "kanban report: skipping" not in stderr, (
            "No skip warnings expected when 'updated' field is present"
        )


# ---------------------------------------------------------------------------
# Test 2: card lacking 'updated' but with activity[] — fall-back path
# ---------------------------------------------------------------------------


class TestReportFallbackToActivity:
    """Card lacking 'updated' but with activity[] surfaces via activity fallback."""

    def test_card_without_updated_but_with_activity_surfaces(self, kanban, tmp_path):
        board = _setup_board(tmp_path)
        card = {
            "action": "Do the thing without updated",
            "intent": "Activity-only timestamp card",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            "activity": [
                {"timestamp": "2026-01-05T08:00:00Z", "message": "Created"},
                {"timestamp": "2026-01-05T16:00:00Z", "message": "Completed successfully"},
            ],
            "created": "2026-01-05T08:00:00Z",
            # NOTE: 'updated' field intentionally absent
        }
        _write_card(board, "done", "202", card)
        args = _make_report_args(board)
        stdout, stderr = _run_cmd_report(kanban, args, board)

        assert "202" in stdout, (
            "Card lacking 'updated' but with activity[] must surface in report "
            "via the activity fallback path"
        )
        assert "kanban report: skipping" not in stderr, (
            "No skip warning expected when activity[] provides a timestamp"
        )

    def test_card_without_updated_single_activity_entry_surfaces(self, kanban, tmp_path):
        """Single-entry activity[] (just 'Created') still provides a fallback timestamp."""
        board = _setup_board(tmp_path)
        card = {
            "action": "Minimal activity card",
            "intent": "One activity entry only",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            "activity": [
                {"timestamp": "2026-02-10T09:00:00Z", "message": "Created"},
            ],
            "created": "2026-02-10T09:00:00Z",
            # NOTE: 'updated' field intentionally absent
        }
        _write_card(board, "done", "203", card)
        args = _make_report_args(board)
        stdout, stderr = _run_cmd_report(kanban, args, board)

        assert "203" in stdout, (
            "Card with single activity entry must surface via activity fallback"
        )
        assert "kanban report: skipping" not in stderr


# ---------------------------------------------------------------------------
# Test 3: card lacking 'updated' AND activity[] but with 'created'
# ---------------------------------------------------------------------------


class TestReportFallbackToCreated:
    """Card lacking 'updated' and activity[] but with 'created' surfaces via created."""

    def test_card_without_updated_or_activity_but_with_created_surfaces(
        self, kanban, tmp_path
    ):
        board = _setup_board(tmp_path)
        card = {
            "action": "Bare minimum card",
            "intent": "Only has created field for timestamp",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            # activity intentionally absent (or empty)
            "activity": [],
            "created": "2026-03-15T14:30:00Z",
            # NOTE: 'updated' field intentionally absent
        }
        _write_card(board, "done", "303", card)
        args = _make_report_args(board)
        stdout, stderr = _run_cmd_report(kanban, args, board)

        assert "303" in stdout, (
            "Card lacking 'updated' and activity[] must surface via 'created' fallback"
        )
        assert "kanban report: skipping" not in stderr, (
            "No skip warning expected when 'created' provides a timestamp"
        )

    def test_card_with_empty_activity_and_no_updated_falls_back_to_created(
        self, kanban, tmp_path
    ):
        """Explicitly empty activity list triggers fall-through to 'created'."""
        board = _setup_board(tmp_path)
        card = {
            "action": "Empty activity list card",
            "intent": "Should use created as fallback",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            "activity": [],  # explicitly empty
            "created": "2026-04-01T00:00:00Z",
            # NOTE: 'updated' intentionally absent
        }
        _write_card(board, "done", "304", card)
        args = _make_report_args(board)
        stdout, stderr = _run_cmd_report(kanban, args, board)

        assert "304" in stdout, (
            "Card with empty activity[] must fall back to 'created' field"
        )
        assert "kanban report: skipping" not in stderr


# ---------------------------------------------------------------------------
# Test 4: card lacking ALL three — skipped with loud stderr warning
# ---------------------------------------------------------------------------


class TestReportSkipWithWarning:
    """Card lacking all timestamp sources is skipped with a loud stderr warning."""

    def test_card_without_any_timestamp_is_skipped_with_warning(
        self, kanban, tmp_path
    ):
        board = _setup_board(tmp_path)
        card = {
            "action": "Timestamp-free card",
            "intent": "No timestamps at all",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            # No 'updated', no 'activity', no 'created'
        }
        _write_card(board, "done", "404", card)
        args = _make_report_args(board)
        stdout, stderr = _run_cmd_report(kanban, args, board)

        # Card must NOT appear in output
        assert "404" not in stdout, (
            "Card with no timestamp sources must not appear in report output"
        )
        # Stderr must contain the searchable warning phrase
        assert "kanban report: skipping" in stderr, (
            "Skipped card must produce a 'kanban report: skipping' warning on stderr"
        )
        # Warning must reference the card path or file so it's actionable
        assert "404.json" in stderr, (
            "Skip warning must identify the card file path for actionable diagnostics"
        )

    def test_card_with_only_bad_timestamps_is_skipped_with_warning(
        self, kanban, tmp_path
    ):
        """Card with invalid/unparseable timestamps in all fields is skipped with warning."""
        board = _setup_board(tmp_path)
        card = {
            "action": "Bad timestamp card",
            "intent": "Timestamps are all invalid strings",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            "updated": "not-a-date",
            "activity": [
                {"timestamp": "also-not-a-date", "message": "Created"},
            ],
            "created": "still-not-a-date",
        }
        _write_card(board, "done", "405", card)
        args = _make_report_args(board)
        stdout, stderr = _run_cmd_report(kanban, args, board)

        assert "405" not in stdout, (
            "Card with all invalid timestamps must not appear in report output"
        )
        assert "kanban report: skipping" in stderr, (
            "Card with all invalid timestamps must produce a skip warning"
        )

    def test_date_filter_with_fallback(self, kanban, tmp_path):
        """Date filter correctly includes/excludes cards whose timestamp comes from fallback."""
        board = _setup_board(tmp_path)

        # Card A: fallback timestamp INSIDE the --from/--to range (no 'updated' field)
        card_inside = {
            "action": "Card inside range via fallback",
            "intent": "Activity timestamp falls within the filter window",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            "activity": [
                {"timestamp": "2026-03-15T12:00:00Z", "message": "Created"},
                {"timestamp": "2026-03-20T12:00:00Z", "message": "Completed"},
            ],
            "created": "2026-03-15T12:00:00Z",
            # NOTE: 'updated' intentionally absent — fallback to activity[-1].timestamp
        }

        # Card B: fallback timestamp OUTSIDE the --from/--to range (no 'updated' field)
        card_outside = {
            "action": "Card outside range via fallback",
            "intent": "Activity timestamp falls before the filter window",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            "activity": [
                {"timestamp": "2026-01-01T12:00:00Z", "message": "Created"},
                {"timestamp": "2026-01-10T12:00:00Z", "message": "Completed"},
            ],
            "created": "2026-01-01T12:00:00Z",
            # NOTE: 'updated' intentionally absent — fallback to activity[-1].timestamp
        }

        _write_card(board, "done", "601", card_inside)
        _write_card(board, "done", "602", card_outside)

        args = _make_report_args(
            board,
            from_date="2026-03-01",
            to_date="2026-03-31",
        )
        stdout, stderr = _run_cmd_report(kanban, args, board)

        # Card inside range must appear
        assert "601" in stdout, (
            "Card whose fallback timestamp (activity[-1]) is inside the filter "
            "range must appear in the report"
        )
        # Card outside range must not appear
        assert "602" not in stdout, (
            "Card whose fallback timestamp (activity[-1]) is outside the filter "
            "range must be excluded from the report"
        )
        assert "kanban report: skipping" not in stderr, (
            "No skip warning expected — both cards have valid fallback timestamps"
        )

    def test_exit_code_still_zero_when_cards_skipped(self, kanban, tmp_path):
        """Skipped cards do not change the exit code (partial reads return 0)."""
        board = _setup_board(tmp_path)
        # One good card and one bad card
        good_card = {
            "action": "Good card",
            "intent": "Has proper timestamps",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
            "activity": [],
            "created": "2026-05-01T12:00:00Z",
            "updated": "2026-05-02T12:00:00Z",
        }
        bad_card = {
            "action": "Bad card",
            "intent": "Missing all timestamps",
            "session": "test-session",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "editFiles": [],
            "readFiles": [],
            "criteria": [],
        }
        _write_card(board, "done", "501", good_card)
        _write_card(board, "done", "502", bad_card)
        args = _make_report_args(board)

        # cmd_report must complete without raising SystemExit
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        with patch.object(kanban, "get_root", return_value=board):
            with patch("sys.stdout", captured_out):
                with patch("sys.stderr", captured_err):
                    # Should not raise
                    kanban.cmd_report(args)

        stdout = captured_out.getvalue()
        stderr = captured_err.getvalue()

        # Good card must appear; bad card must not
        assert "501" in stdout
        assert "502" not in stdout
        # Skip warning for the bad card
        assert "kanban report: skipping" in stderr
