"""
Tests for V4 schema migration, cmd_done exit code behavior, and
agent_launch_pending field lifecycle.

Covers:
- V4 migration: agent_met -> met, reviewer_met dropped, review_cycles -> cycles
- cmd_done exits 0 when all criteria are met
- cmd_done exits 1 (retryable) when criteria are unchecked (first and second attempt)
- cmd_done exits 2 (max cycles) on the 3rd call with unchecked criteria
- agent_launch_pending set to True by cmd_do (doing path)
- agent_launch_pending set to True by cmd_start (todo -> doing)
- clear_agent_launch_pending sets the flag to False
- flag persists in card JSON across invocations
- backward compat: cards without the field default to False on read
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


# ---------------------------------------------------------------------------
# Tests: criteria check strict rejection of empty mov_commands
# ---------------------------------------------------------------------------

def _make_card_with_empty_mov_commands(session="test-session"):
    """Build a card dict with a criterion that has no mov_commands."""
    return {
        "action": "Do the thing",
        "intent": "Because reasons",
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": [],
        "readFiles": [],
        "criteria": [
            {"text": "Criterion with no mov_commands", "mov_commands": [], "met": False},
        ],
        "cycles": 0,
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


def _make_card_with_valid_mov_commands(session="test-session"):
    """Build a card dict with a criterion that has a passing mov_commands entry."""
    return {
        "action": "Do the thing",
        "intent": "Because reasons",
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": [],
        "readFiles": [],
        "criteria": [
            {
                "text": "Criterion with passing mov_command",
                "mov_commands": [{"cmd": "true", "timeout": 5}],
                "met": False,
            },
        ],
        "cycles": 0,
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


def _make_check_args(board_root, card_num="1", criterion_nums=None, session="test-session"):
    """Build a minimal args namespace for cmd_criteria_check."""
    return SimpleNamespace(
        root=str(board_root),
        card=str(card_num),
        n=[str(n) for n in (criterion_nums or [1])],
        session=session,
    )


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


class TestCriteriaCheckStrictness:
    """criteria check rejects criteria with empty mov_commands."""

    def test_criteria_check_rejects_empty_mov_commands(self, kanban, tmp_path):
        """criteria check exits 1 when criterion has empty mov_commands."""
        board = _setup_board(tmp_path)
        card_data = _make_card_with_empty_mov_commands(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_check_args(board, card_num="1", criterion_nums=[1])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit) as exc_info:
                    kanban.cmd_criteria_check(args)

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for empty mov_commands, got {exc_info.value.code}"
        )

    def test_criteria_check_empty_mov_commands_prints_error(self, kanban, tmp_path, capsys):
        """criteria check prints 'no programmatic verification provided' to stderr for empty mov_commands."""
        board = _setup_board(tmp_path)
        card_data = _make_card_with_empty_mov_commands(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_check_args(board, card_num="1", criterion_nums=[1])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit):
                    kanban.cmd_criteria_check(args)

        captured = capsys.readouterr()
        assert "no programmatic verification provided" in captured.err, (
            f"Expected 'no programmatic verification provided' in stderr, got: {captured.err!r}"
        )

    def test_criteria_check_empty_mov_commands_does_not_mutate_card(self, kanban, tmp_path):
        """criteria check does NOT set met=true when mov_commands is empty."""
        board = _setup_board(tmp_path)
        card_data = _make_card_with_empty_mov_commands(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_check_args(board, card_num="1", criterion_nums=[1])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit):
                    kanban.cmd_criteria_check(args)

        on_disk = json.loads(card_path.read_text())
        assert on_disk["criteria"][0]["met"] is False, (
            "Card state must not be mutated when empty mov_commands check fails"
        )

    def test_criteria_check_with_passing_mov_commands_sets_met(self, kanban, tmp_path):
        """criteria check sets met=True when all mov_commands exit 0 (regression check)."""
        board = _setup_board(tmp_path)
        card_data = _make_card_with_valid_mov_commands(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_check_args(board, card_num="1", criterion_nums=[1])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    kanban.cmd_criteria_check(args)

        on_disk = json.loads(card_path.read_text())
        assert on_disk["criteria"][0]["met"] is True, (
            "met must be True after passing criteria check with valid mov_commands"
        )


# ---------------------------------------------------------------------------
# Tests: criteria add --mov-cmd / --mov-timeout flags
# ---------------------------------------------------------------------------

class TestCriteriaAddMovCmd:
    """criteria add --mov-cmd populates mov_commands on the criterion."""

    def test_criteria_add_with_mov_cmd_populates_mov_commands(self, kanban, tmp_path):
        """--mov-cmd flag creates criterion with mov_commands populated."""
        board = _setup_board(tmp_path)
        card_data = _make_v4_card_all_met(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_add_args(
            board,
            card_num="1",
            text="Pattern present",
            mov_cmd=["true"],
            mov_timeout=[5],
        )

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    kanban.cmd_criteria_add(args)

        on_disk = json.loads(card_path.read_text())
        new_criterion = on_disk["criteria"][-1]
        assert new_criterion["mov_commands"], "mov_commands must be non-empty when --mov-cmd provided"
        assert new_criterion["mov_commands"][0]["cmd"] == "true"
        assert new_criterion["mov_commands"][0]["timeout"] == 5

    def test_criteria_add_multiple_mov_cmd_appends_all(self, kanban, tmp_path):
        """Multiple --mov-cmd occurrences correctly append separate entries."""
        board = _setup_board(tmp_path)
        card_data = _make_v4_card_all_met(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_add_args(
            board,
            card_num="1",
            text="Multi-command criterion",
            mov_cmd=["true", "test -d /tmp"],
            mov_timeout=[5, 10],
        )

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    kanban.cmd_criteria_add(args)

        on_disk = json.loads(card_path.read_text())
        new_criterion = on_disk["criteria"][-1]
        assert len(new_criterion["mov_commands"]) == 2, (
            f"Expected 2 mov_commands entries, got {len(new_criterion['mov_commands'])}"
        )
        assert new_criterion["mov_commands"][0]["cmd"] == "true"
        assert new_criterion["mov_commands"][0]["timeout"] == 5
        assert new_criterion["mov_commands"][1]["cmd"] == "test -d /tmp"
        assert new_criterion["mov_commands"][1]["timeout"] == 10

    def test_criteria_add_without_mov_cmd_creates_empty_mov_commands(self, kanban, tmp_path):
        """Without --mov-cmd, criterion has empty mov_commands (criteria check will reject it)."""
        board = _setup_board(tmp_path)
        card_data = _make_v4_card_all_met(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_add_args(
            board,
            card_num="1",
            text="Unverifiable criterion",
            mov_cmd=None,
            mov_timeout=None,
        )

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    kanban.cmd_criteria_add(args)

        on_disk = json.loads(card_path.read_text())
        new_criterion = on_disk["criteria"][-1]
        assert new_criterion["mov_commands"] == [], (
            "Without --mov-cmd, mov_commands must be empty list"
        )

    def test_criteria_add_mov_cmd_then_check_succeeds(self, kanban, tmp_path):
        """criterion added with --mov-cmd passes criteria check when command exits 0."""
        board = _setup_board(tmp_path)
        # Start with a card that has one already-met criterion
        card_data = _make_v4_card_all_met(session="test-session")
        card_path = _write_card(board, "doing", "1", card_data)

        add_args = _make_add_args(
            board,
            card_num="1",
            text="Always-passing check",
            mov_cmd=["true"],
            mov_timeout=[5],
        )

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    kanban.cmd_criteria_add(add_args)

        on_disk = json.loads(card_path.read_text())
        new_criterion_idx = len(on_disk["criteria"])  # 1-based index

        check_args = _make_check_args(board, card_num="1", criterion_nums=[new_criterion_idx])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    # Should not raise SystemExit
                    try:
                        kanban.cmd_criteria_check(check_args)
                    except SystemExit as e:
                        pytest.fail(f"criteria check raised SystemExit({e.code}) — expected success")

        on_disk = json.loads(card_path.read_text())
        assert on_disk["criteria"][-1]["met"] is True, (
            "Newly added criterion with valid mov_command must be checkable and set met=True"
        )


# ---------------------------------------------------------------------------
# Tests: timeout boundary validation (cap at 1800 seconds)
# ---------------------------------------------------------------------------

def _make_card_with_timeout(timeout_value, session="test-session"):
    """Build a minimal V4 card with a single criterion using the given timeout."""
    return {
        "action": "Do the thing",
        "intent": "Because reasons",
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": [],
        "readFiles": [],
        "criteria": [
            {
                "text": "Criterion with custom timeout",
                "mov_commands": [{"cmd": "true", "timeout": timeout_value}],
                "met": False,
            },
        ],
        "cycles": 0,
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


class TestTimeoutBoundary:
    """criteria check enforces 1-1800 second timeout range."""

    def test_timeout_1800_is_accepted(self, kanban, tmp_path, capsys):
        """timeout=1800 is within range and criteria check proceeds past validation."""
        board = _setup_board(tmp_path)
        card_data = _make_card_with_timeout(1800)
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_check_args(board, card_num="1", criterion_nums=[1])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    try:
                        kanban.cmd_criteria_check(args)
                    except SystemExit:
                        pass  # Other failures (e.g., met=False) are acceptable

        captured = capsys.readouterr()
        assert "Must be 1-1800 seconds" not in captured.err, (
            f"timeout=1800 must not trigger the out-of-range error message, got: {captured.err!r}"
        )

    def test_timeout_1800_does_not_print_range_error(self, kanban, tmp_path, capsys):
        """timeout=1800 does NOT trigger the out-of-range error message."""
        board = _setup_board(tmp_path)
        card_data = _make_card_with_timeout(1800)
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_check_args(board, card_num="1", criterion_nums=[1])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch("sys.stdout", io.StringIO()):
                    try:
                        kanban.cmd_criteria_check(args)
                    except SystemExit:
                        pass

        captured = capsys.readouterr()
        assert "Must be 1-1800 seconds" not in captured.err, (
            "timeout=1800 must not trigger the out-of-range error message"
        )

    def test_timeout_1801_is_rejected(self, kanban, tmp_path):
        """timeout=1801 exceeds cap and criteria check exits 1."""
        board = _setup_board(tmp_path)
        card_data = _make_card_with_timeout(1801)
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_check_args(board, card_num="1", criterion_nums=[1])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit) as exc_info:
                    kanban.cmd_criteria_check(args)

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for timeout=1801 (out of range), got {exc_info.value.code}"
        )

    def test_timeout_1801_prints_range_error(self, kanban, tmp_path, capsys):
        """timeout=1801 prints the out-of-range error message referencing 1-1800 seconds."""
        board = _setup_board(tmp_path)
        card_data = _make_card_with_timeout(1801)
        card_path = _write_card(board, "doing", "1", card_data)
        args = _make_check_args(board, card_num="1", criterion_nums=[1])

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with pytest.raises(SystemExit):
                    kanban.cmd_criteria_check(args)

        captured = capsys.readouterr()
        assert "Must be 1-1800 seconds" in captured.err, (
            f"Expected 'Must be 1-1800 seconds' in stderr for timeout=1801, got: {captured.err!r}"
        )

    def test_timeout_1_is_accepted(self, kanban, tmp_path, capsys):
        """timeout=1 is the lower bound and should be accepted — no range error in stderr."""
        criteria = _make_card_with_timeout(1)["criteria"]
        # validate_criteria_schema should not raise for timeout=1
        try:
            kanban.validate_criteria_schema(criteria)
        except SystemExit:
            pass  # Other failures are not expected; capture stderr to check

        captured = capsys.readouterr()
        assert "Must be 1-1800 seconds" not in captured.err, (
            f"timeout=1 must not trigger the out-of-range error message, got: {captured.err!r}"
        )

    def test_timeout_0_is_rejected(self, kanban, tmp_path, capsys):
        """timeout=0 is below the lower bound and schema validation should print the range error and exit 1."""
        criteria = _make_card_with_timeout(0)["criteria"]

        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for timeout=0 (out of range), got {exc_info.value.code}"
        )
        captured = capsys.readouterr()
        assert "Must be 1-1800 seconds" in captured.err, (
            f"Expected 'Must be 1-1800 seconds' in stderr for timeout=0, got: {captured.err!r}"
        )

    def test_timeout_minus1_is_rejected(self, kanban, tmp_path, capsys):
        """timeout=-1 is negative and schema validation should print the range error and exit 1."""
        criteria = _make_card_with_timeout(-1)["criteria"]

        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for timeout=-1 (out of range), got {exc_info.value.code}"
        )
        captured = capsys.readouterr()
        assert "Must be 1-1800 seconds" in captured.err, (
            f"Expected 'Must be 1-1800 seconds' in stderr for timeout=-1, got: {captured.err!r}"
        )


# ---------------------------------------------------------------------------
# Helpers: agent_launch_pending tests
# ---------------------------------------------------------------------------

def _make_valid_card_json() -> str:
    """Build a minimal valid card JSON string for cmd_do tests."""
    return json.dumps({
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
    })


def _make_do_args(board_root, json_data: str, session: str = "test-session"):
    """Build a minimal args namespace for cmd_do."""
    return SimpleNamespace(
        root=str(board_root),
        json_data=json_data,
        json_file=None,
        session=session,
    )


def _make_start_args(board_root, card_num: str, session: str = "test-session"):
    """Build a minimal args namespace for cmd_start."""
    return SimpleNamespace(
        root=str(board_root),
        card=[card_num],
        session=session,
    )


def _make_clear_alp_args(board_root, card_num: str, session: str = "test-session"):
    """Build a minimal args namespace for cmd_clear_agent_launch_pending."""
    return SimpleNamespace(
        root=str(board_root),
        card=card_num,
        session=session,
    )


# ---------------------------------------------------------------------------
# Tests: agent_launch_pending field lifecycle
# ---------------------------------------------------------------------------

class TestAgentLaunchPending:
    """agent_launch_pending field is set and cleared correctly across card lifecycle."""

    def test_cmd_do_sets_agent_launch_pending_true(self, kanban, tmp_path):
        """cmd_do sets agent_launch_pending=True on newly created doing card."""
        board = _setup_board(tmp_path)
        args = _make_do_args(board, _make_valid_card_json())

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        # Find the created card in doing/
        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 1, f"Expected 1 card in doing, got {len(doing_cards)}"
        card_data = json.loads(doing_cards[0].read_text())
        assert card_data.get("agent_launch_pending") is True, (
            f"cmd_do must set agent_launch_pending=True on doing card, got {card_data.get('agent_launch_pending')!r}"
        )

    def test_cmd_do_conflict_does_not_set_agent_launch_pending(self, kanban, tmp_path):
        """cmd_do sets agent_launch_pending=False when card is deferred to todo due to conflict."""
        board = _setup_board(tmp_path)

        # Create an in-flight card with the same editFile to trigger conflict
        inflight_card = {
            "action": "Inflight work",
            "intent": "Already doing",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "session": "other-session",
            "editFiles": ["modules/kanban/kanban.py"],
            "readFiles": [],
            "criteria": [{"text": "check", "met": False}],
            "cycles": 0,
            "agent_launch_pending": False,
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "activity": [],
        }
        _write_card(board, "doing", "99", inflight_card)

        conflict_card_json = json.dumps({
            "action": "Conflicting work",
            "intent": "Same file",
            "type": "work",
            "agent": "swe-devex",
            "editFiles": ["modules/kanban/kanban.py"],
            "criteria": [{"text": "check", "mov_type": "programmatic", "mov_commands": [{"cmd": "true", "timeout": 5}], "met": False}],
        })
        args = _make_do_args(board, conflict_card_json)

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1

        # Card should be in todo, not doing
        todo_cards = list((board / "todo").glob("*.json"))
        assert len(todo_cards) == 1, f"Expected 1 card in todo, got {len(todo_cards)}"
        card_data = json.loads(todo_cards[0].read_text())
        # Not set to True — card is in todo, not doing
        assert card_data.get("agent_launch_pending") is not True, (
            "Conflicted card deferred to todo must NOT have agent_launch_pending=True"
        )

    def test_cmd_start_sets_agent_launch_pending_true(self, kanban, tmp_path):
        """cmd_start sets agent_launch_pending=True when moving card from todo to doing."""
        board = _setup_board(tmp_path)

        # Place a card in todo
        todo_card = {
            "action": "Queued work",
            "intent": "Will do it later",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "session": "test-session",
            "editFiles": [],
            "readFiles": [],
            "criteria": [{"text": "check", "met": False}],
            "cycles": 0,
            "agent_launch_pending": False,
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "activity": [],
        }
        card_path = _write_card(board, "todo", "7", todo_card)
        args = _make_start_args(board, card_num="7")

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        # Card should be moved to doing with agent_launch_pending=True
        doing_path = board / "doing" / "7.json"
        assert doing_path.exists(), "Card must be moved to doing/ after cmd_start"
        card_data = json.loads(doing_path.read_text())
        assert card_data.get("agent_launch_pending") is True, (
            f"cmd_start must set agent_launch_pending=True, got {card_data.get('agent_launch_pending')!r}"
        )

    def test_cmd_start_deferred_then_restart_resets_flag(self, kanban, tmp_path):
        """cmd_start re-sets agent_launch_pending=True even if it was previously cleared."""
        board = _setup_board(tmp_path)

        # Card was previously launched (flag cleared), then deferred back to todo
        todo_card = {
            "action": "Restarted work",
            "intent": "Coming back to this",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "session": "test-session",
            "editFiles": [],
            "readFiles": [],
            "criteria": [{"text": "check", "met": False}],
            "cycles": 0,
            "agent_launch_pending": False,  # was cleared by previous launch
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "activity": [],
        }
        _write_card(board, "todo", "8", todo_card)
        args = _make_start_args(board, card_num="8")

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_start(args)

        doing_path = board / "doing" / "8.json"
        card_data = json.loads(doing_path.read_text())
        assert card_data.get("agent_launch_pending") is True, (
            "cmd_start must re-set agent_launch_pending=True on restart"
        )

    def test_clear_agent_launch_pending_sets_flag_false(self, kanban, tmp_path):
        """cmd_clear_agent_launch_pending sets agent_launch_pending=False."""
        board = _setup_board(tmp_path)

        # Card in doing with flag set
        doing_card = {
            "action": "Work in progress",
            "intent": "Agent was launched",
            "type": "work",
            "agent": "swe-devex",
            "model": "sonnet",
            "session": "test-session",
            "editFiles": [],
            "readFiles": [],
            "criteria": [{"text": "check", "met": False}],
            "cycles": 0,
            "agent_launch_pending": True,
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "activity": [],
        }
        card_path = _write_card(board, "doing", "5", doing_card)
        args = _make_clear_alp_args(board, card_num="5")

        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                kanban.cmd_clear_agent_launch_pending(args)

        card_data = json.loads(card_path.read_text())
        assert card_data.get("agent_launch_pending") is False, (
            f"cmd_clear_agent_launch_pending must set flag to False, got {card_data.get('agent_launch_pending')!r}"
        )

    def test_agent_launch_pending_persists_in_json(self, kanban, tmp_path):
        """agent_launch_pending field survives a write/read cycle (persists in JSON)."""
        board = _setup_board(tmp_path)
        args = _make_do_args(board, _make_valid_card_json())

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        doing_cards = list((board / "doing").glob("*.json"))
        assert len(doing_cards) == 1
        card_path = doing_cards[0]

        # Re-read via read_card (not raw JSON) to confirm round-trip
        card_data = kanban.read_card(card_path)
        assert card_data.get("agent_launch_pending") is True, (
            "agent_launch_pending=True must persist in card JSON across read_card calls"
        )

    def test_card_without_field_defaults_to_false(self, kanban, tmp_path):
        """Cards without agent_launch_pending field read back as False (backward compat)."""
        board = _setup_board(tmp_path)

        # Write a card without the field (simulating a pre-Phase1 card)
        old_card = {
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
        card_path = _write_card(board, "doing", "3", old_card)

        card_data = kanban.read_card(card_path)
        # Field is absent — .get() returns None/False; either way it must not be True
        assert card_data.get("agent_launch_pending", False) is not True, (
            "Old cards without agent_launch_pending must not read as True"
        )

    def test_make_card_includes_agent_launch_pending_false(self, kanban):
        """make_card includes agent_launch_pending=False in the returned dict."""
        card = kanban.make_card(
            action="Test action",
            intent="Test intent",
        )
        assert "agent_launch_pending" in card, (
            "make_card must include agent_launch_pending field"
        )
        assert card["agent_launch_pending"] is False, (
            f"make_card must set agent_launch_pending=False by default, got {card['agent_launch_pending']!r}"
        )
