"""
Tests for the per-entry "column" field in kanban.py's `kanban do` / `kanban
todo` JSON array (and single-object) inputs.

Card #3349: each entry in a `kanban do --file` / `kanban todo --file` JSON
array may declare its own target column ("doing" or "todo"), overriding the
column the invoking verb would otherwise imply. Absent means "use whatever
the verb implies" — today's behavior, unchanged. An unrecognized value is
rejected outright rather than silently defaulted.

Covered (the three scenarios the card requires, one per class below):
- TestArrayMixedColumnTargets: a mixed array where one entry targets "doing"
  and another targets "todo" — each lands in the column it asked for.
- TestArrayColumnAbsentRegression: an array with the field absent on every
  entry — behavior is identical to today's (regression, for both verbs).
- TestUnrecognizedColumnValueRejected: an unrecognized "column" value is
  rejected with a useful error, both at the validation-function level and
  through the full `kanban do` bulk-array code path.
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

    spec = importlib.util.spec_from_file_location("kanban_array_column", _KANBAN_PATH)
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


def make_valid_card_data(action="Do the thing", criteria=None, column=None):
    """Build a minimal valid card JSON dict, optionally carrying a 'column' field."""
    if criteria is None:
        criteria = [make_valid_criterion()]
    data = {
        "action": action,
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-devex",
        "criteria": criteria,
    }
    if column is not None:
        data["column"] = column
    return data


def make_args_with_json(json_data: str, root: str, session: str = "test-session", force: bool = False):
    """Build a mock args object for cmd_do / cmd_todo with inline JSON.

    force is set explicitly (rather than left to MagicMock's attribute
    auto-vivification) because cmd_do/cmd_todo read it via
    `getattr(args, "force", False)` — on a bare MagicMock that would return a
    truthy auto-created Mock instead of the real CLI default of False.
    """
    args = MagicMock()
    args.root = root
    args.session = session
    args.json_data = json_data
    args.json_file = None
    args.force = force
    return args


def setup_kanban_root(tmp_path):
    """Create minimal kanban board directory structure."""
    for col in ("todo", "doing", "done", "canceled"):
        (tmp_path / col).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _run_with_mocked_subprocess(fn, args):
    """Run cmd_do/cmd_todo with subprocess.run mocked out.

    warn_nondiscriminating_movs and friends execute mov_commands against the
    real tree to sanity-check them at creation time — mocking subprocess.run
    keeps these tests hermetic and fast, matching the pattern already used in
    test_kanban_unknown_field_validation.py.
    """
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        fn(args)


# ---------------------------------------------------------------------------
# 1. Mixed array: one entry targets "doing", another targets "todo"
# ---------------------------------------------------------------------------

class TestArrayMixedColumnTargets:
    """A single array where entries declare different target columns."""

    def test_kanban_do_bulk_mixed_column_targets_land_correctly(self, kanban, tmp_path):
        """kanban do: one entry column='doing', another column='todo' — each lands where it asked."""
        setup_kanban_root(tmp_path)
        bulk_array = [
            make_valid_card_data(action="Explicitly doing", column="doing"),
            make_valid_card_data(action="Explicitly todo", column="todo"),
        ]
        args = make_args_with_json(json.dumps(bulk_array), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            try:
                _run_with_mocked_subprocess(kanban.cmd_do, args)
            except SystemExit as e:
                pytest.fail(f"Mixed-column array raised SystemExit({e.code})")

        doing_cards = list((tmp_path / "doing").glob("*.json"))
        todo_cards = list((tmp_path / "todo").glob("*.json"))
        assert len(doing_cards) == 1, f"Expected 1 card in doing, found {len(doing_cards)}"
        assert len(todo_cards) == 1, f"Expected 1 card in todo, found {len(todo_cards)}"

        doing_card = json.loads(doing_cards[0].read_text())
        todo_card = json.loads(todo_cards[0].read_text())
        assert doing_card["action"] == "Explicitly doing"
        assert todo_card["action"] == "Explicitly todo"
        # Cards placed in doing get agent_launch_pending=True; todo-routed
        # entries never do, regardless of which verb created them.
        assert doing_card["agent_launch_pending"] is True
        assert todo_card["agent_launch_pending"] is False

    def test_kanban_todo_bulk_mixed_column_targets_land_correctly(self, kanban, tmp_path):
        """kanban todo: one entry column='todo', another column='doing' — each lands where it asked."""
        setup_kanban_root(tmp_path)
        bulk_array = [
            make_valid_card_data(action="Explicitly todo via todo verb", column="todo"),
            make_valid_card_data(action="Explicitly doing via todo verb", column="doing"),
        ]
        args = make_args_with_json(json.dumps(bulk_array), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            try:
                _run_with_mocked_subprocess(kanban.cmd_todo, args)
            except SystemExit as e:
                pytest.fail(f"Mixed-column array raised SystemExit({e.code})")

        doing_cards = list((tmp_path / "doing").glob("*.json"))
        todo_cards = list((tmp_path / "todo").glob("*.json"))
        assert len(doing_cards) == 1, f"Expected 1 card in doing, found {len(doing_cards)}"
        assert len(todo_cards) == 1, f"Expected 1 card in todo, found {len(todo_cards)}"

        doing_card = json.loads(doing_cards[0].read_text())
        todo_card = json.loads(todo_cards[0].read_text())
        assert doing_card["action"] == "Explicitly doing via todo verb"
        assert todo_card["action"] == "Explicitly todo via todo verb"


# ---------------------------------------------------------------------------
# 2. Array with the field absent on every entry — regression
# ---------------------------------------------------------------------------

class TestArrayColumnAbsentRegression:
    """An array where no entry carries 'column' behaves exactly as today."""

    def test_kanban_do_bulk_column_absent_all_land_in_doing(self, kanban, tmp_path):
        """kanban do with no 'column' field anywhere: every card lands in doing (today's behavior)."""
        setup_kanban_root(tmp_path)
        bulk_array = [
            make_valid_card_data(action="First card"),
            make_valid_card_data(action="Second card"),
        ]
        args = make_args_with_json(json.dumps(bulk_array), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            try:
                _run_with_mocked_subprocess(kanban.cmd_do, args)
            except SystemExit as e:
                pytest.fail(f"Column-absent array raised SystemExit({e.code})")

        doing_cards = list((tmp_path / "doing").glob("*.json"))
        todo_cards = list((tmp_path / "todo").glob("*.json"))
        assert len(doing_cards) == 2, f"Expected both cards in doing, found {len(doing_cards)}"
        assert len(todo_cards) == 0, f"Expected no cards in todo, found {len(todo_cards)}"
        for card_path in doing_cards:
            card = json.loads(card_path.read_text())
            assert card["agent_launch_pending"] is True

    def test_kanban_todo_bulk_column_absent_all_land_in_todo(self, kanban, tmp_path):
        """kanban todo with no 'column' field anywhere: every card lands in todo (today's behavior)."""
        setup_kanban_root(tmp_path)
        bulk_array = [
            make_valid_card_data(action="First card"),
            make_valid_card_data(action="Second card"),
        ]
        args = make_args_with_json(json.dumps(bulk_array), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            try:
                _run_with_mocked_subprocess(kanban.cmd_todo, args)
            except SystemExit as e:
                pytest.fail(f"Column-absent array raised SystemExit({e.code})")

        todo_cards = list((tmp_path / "todo").glob("*.json"))
        doing_cards = list((tmp_path / "doing").glob("*.json"))
        assert len(todo_cards) == 2, f"Expected both cards in todo, found {len(todo_cards)}"
        assert len(doing_cards) == 0, f"Expected no cards in doing, found {len(doing_cards)}"

    def test_single_object_column_absent_regression_for_do_and_todo(self, kanban, tmp_path):
        """Single-object (non-array) input with no 'column' field is unaffected in either verb."""
        setup_kanban_root(tmp_path / "do-case")
        setup_kanban_root(tmp_path / "todo-case")

        do_args = make_args_with_json(
            json.dumps(make_valid_card_data(action="Single do card")),
            root=str(tmp_path / "do-case"),
        )
        todo_args = make_args_with_json(
            json.dumps(make_valid_card_data(action="Single todo card")),
            root=str(tmp_path / "todo-case"),
        )

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            _run_with_mocked_subprocess(kanban.cmd_do, do_args)
            _run_with_mocked_subprocess(kanban.cmd_todo, todo_args)

        assert len(list((tmp_path / "do-case" / "doing").glob("*.json"))) == 1
        assert len(list((tmp_path / "do-case" / "todo").glob("*.json"))) == 0
        assert len(list((tmp_path / "todo-case" / "todo").glob("*.json"))) == 1
        assert len(list((tmp_path / "todo-case" / "doing").glob("*.json"))) == 0


# ---------------------------------------------------------------------------
# 3. Unrecognized "column" value is rejected
# ---------------------------------------------------------------------------

class TestUnrecognizedColumnValueRejected:
    """An unrecognized 'column' value is rejected, not silently defaulted."""

    def test_validate_card_column_rejects_unrecognized_value(self, kanban, capsys):
        """validate_card_column exits 1 with a useful message on an unrecognized value."""
        data = make_valid_card_data(column="parking-lot")
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_card_column(data)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "parking-lot" in captured.err
        assert "doing" in captured.err
        assert "todo" in captured.err

    def test_validate_card_column_accepts_doing_and_todo(self, kanban):
        """validate_card_column accepts both recognized values and absence without raising."""
        for column in ("doing", "todo", None):
            data = make_valid_card_data(column=column)
            try:
                kanban.validate_card_column(data)
            except SystemExit as e:
                pytest.fail(f"column={column!r} raised SystemExit({e.code})")

    def test_cmd_do_bulk_array_rejects_unrecognized_column_value(self, kanban, tmp_path, capsys):
        """kanban do exits 1 when a bulk array entry has an unrecognized 'column' value.

        No card is created anywhere on the board — the whole batch fails
        fast, matching how other structural validation errors behave.
        """
        setup_kanban_root(tmp_path)
        bulk_array = [
            make_valid_card_data(action="Bad column card", column="parking-lot"),
        ]
        args = make_args_with_json(json.dumps(bulk_array), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "parking-lot" in captured.err

        assert not list((tmp_path / "doing").glob("*.json"))
        assert not list((tmp_path / "todo").glob("*.json"))

    def test_cmd_todo_single_object_rejects_unrecognized_column_value(self, kanban, tmp_path, capsys):
        """kanban todo exits 1 for a single-object input with an unrecognized 'column' value."""
        setup_kanban_root(tmp_path)
        data = make_valid_card_data(action="Bad column card", column="backlog")
        args = make_args_with_json(json.dumps(data), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_todo(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "backlog" in captured.err

        assert not list((tmp_path / "doing").glob("*.json"))
        assert not list((tmp_path / "todo").glob("*.json"))


# ---------------------------------------------------------------------------
# 4. Single-object cmd_todo + column="doing" + conflict, and force + column
# ---------------------------------------------------------------------------

def _write_conflicting_doing_card(tmp_path, edit_files, session="other-session", num="99"):
    """Write an in-flight doing card directly to disk, bypassing validation.

    Mirrors the routing card's own editFiles so a conflict check against it
    is guaranteed to find an overlap.
    """
    card = {
        "action": "In-flight work",
        "intent": "Active agent",
        "type": "work",
        "agent": "swe-devex",
        "session": session,
        "editFiles": edit_files,
        "criteria": [{"text": "check", "met": False}],
        "agent_launch_pending": True,
    }
    (tmp_path / "doing" / f"{num}.json").write_text(json.dumps(card))


class TestSingleObjectColumnOverrideConflictAndForce:
    """Single-object cmd_todo routed to doing, and force overriding a conflict.

    Card #3349 unified cmd_do/cmd_todo routing through _route_card_to_column
    (see its docstring). These cover the two combinations Q7's Tier 2 review
    flagged as untested: a single-object `kanban todo --file` entry that
    explicitly requests "column": "doing" under an editFiles conflict, and
    --force interacting with an explicit "column" override.
    """

    def test_cmd_todo_single_object_column_doing_defers_on_editfiles_conflict(self, kanban, tmp_path):
        """Single-object kanban todo with column='doing' defers to todo on editFiles conflict."""
        setup_kanban_root(tmp_path)
        _write_conflicting_doing_card(tmp_path, ["src/conflict.ts"])

        data = make_valid_card_data(action="Single todo card wants doing", column="doing")
        data["editFiles"] = ["src/conflict.ts"]
        args = make_args_with_json(json.dumps(data), root=str(tmp_path))

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            with pytest.raises(SystemExit) as exc_info:
                _run_with_mocked_subprocess(kanban.cmd_todo, args)

        assert exc_info.value.code == 1

        todo_cards = list((tmp_path / "todo").glob("*.json"))
        new_doing_cards = [p for p in (tmp_path / "doing").glob("*.json") if p.name != "99.json"]
        assert len(todo_cards) == 1, "Card should be deferred to todo on conflict"
        assert len(new_doing_cards) == 0, "Card should NOT land in doing due to the conflict"

        deferred_card = json.loads(todo_cards[0].read_text())
        assert deferred_card["action"] == "Single todo card wants doing"

    def test_force_with_explicit_column_override_proceeds_to_doing(self, kanban, tmp_path):
        """force=True with an explicit column='doing' override proceeds to doing despite conflict."""
        setup_kanban_root(tmp_path)
        _write_conflicting_doing_card(tmp_path, ["src/conflict.ts"])

        data = make_valid_card_data(action="Forced doing override", column="doing")
        data["editFiles"] = ["src/conflict.ts"]
        args = make_args_with_json(json.dumps(data), root=str(tmp_path), force=True)

        with patch.object(kanban, "get_current_session_id", return_value="test-session"):
            try:
                _run_with_mocked_subprocess(kanban.cmd_todo, args)
            except SystemExit as e:
                pytest.fail(f"force=True should bypass the conflict, but raised SystemExit({e.code})")

        new_doing_cards = [p for p in (tmp_path / "doing").glob("*.json") if p.name != "99.json"]
        assert len(new_doing_cards) == 1, "Card should land in doing when force=True overrides the conflict"

        forced_card = json.loads(new_doing_cards[0].read_text())
        assert forced_card["action"] == "Forced doing override"
        assert forced_card["forced"] is True
