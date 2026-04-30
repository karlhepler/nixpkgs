"""
Tests for kanban.py v5 schema changes.

Covers:
- P1.1: v5 schema validation (mov_commands array); rejection of v4 schema
- P1.2: cmd_criteria_check array iteration + short-circuit
- P1.4: __CARD_ID__ substitution in create_card_in_column and cmd_criteria_add
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

_KANBAN_PATH = Path(__file__).parent.parent.parent / "kanban" / "kanban.py"


def load_kanban():
    """Import kanban.py as a module.

    kanban.py imports watchdog which is only available when running via Nix.
    Inject a stub so tests can run without the full Nix environment.
    """
    # Stub watchdog modules before kanban.py is exec'd
    watchdog_stub = MagicMock()
    sys.modules.setdefault("watchdog", watchdog_stub)
    sys.modules.setdefault("watchdog.observers", watchdog_stub)
    sys.modules.setdefault("watchdog.events", watchdog_stub)
    # Provide concrete base class so class inheritance in kanban.py works
    watchdog_stub.events.FileSystemEventHandler = object

    spec = importlib.util.spec_from_file_location("kanban", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_v5_criterion(
    text: str = "Some criterion",
    mov_type: str = "programmatic",
    cmds: list | None = None,
) -> dict:
    """Build a minimal v5 criterion dict."""
    c: dict = {"text": text, "mov_type": mov_type}
    if mov_type == "programmatic":
        if cmds is None:
            cmds = [{"cmd": "true", "timeout": 5}]
        c["mov_commands"] = cmds
    return c


def make_v4_criterion(
    text: str = "Old criterion",
    mov_type: str = "programmatic",
    mov_command: str = "true",
    mov_timeout: int = 5,
) -> dict:
    """Build a v4 criterion dict (legacy schema — should be rejected)."""
    return {
        "text": text,
        "mov_type": mov_type,
        "mov_command": mov_command,
        "mov_timeout": mov_timeout,
    }


def make_minimal_card(criteria: list | None = None, card_id: str = "999") -> dict:
    """Build a minimal card dict for testing."""
    if criteria is None:
        criteria = [make_v5_criterion()]
    return {
        "action": "Do something",
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-backend",
        "session": "test-session",
        "criteria": criteria,
        "editFiles": [],
        "readFiles": [],
    }


# ---------------------------------------------------------------------------
# P1.1: v5 schema validation
# ---------------------------------------------------------------------------

class TestV5SchemaValidation:
    """validate_criteria_schema() enforces v5 schema; rejects v4."""

    def test_valid_programmatic_criterion_passes(self, kanban):
        """Single valid v5 programmatic criterion passes validation."""
        criteria = [make_v5_criterion()]
        # Should not raise/exit
        try:
            kanban.validate_criteria_schema(criteria)
        except SystemExit as e:
            pytest.fail(f"validate_criteria_schema raised SystemExit({e.code}) for valid v5 criterion")

    def test_valid_semantic_criterion_passes(self, kanban):
        """Semantic criterion with no mov_commands passes."""
        criteria = [{"text": "Semantic check", "mov_type": "semantic"}]
        try:
            kanban.validate_criteria_schema(criteria)
        except SystemExit as e:
            pytest.fail(f"Unexpected SystemExit({e.code}) for valid semantic criterion")

    def test_semantic_with_empty_mov_commands_passes(self, kanban):
        """Semantic criterion with empty mov_commands array passes."""
        criteria = [{"text": "Semantic check", "mov_type": "semantic", "mov_commands": []}]
        try:
            kanban.validate_criteria_schema(criteria)
        except SystemExit as e:
            pytest.fail(f"Unexpected SystemExit({e.code}) for semantic with empty mov_commands")

    def test_multiple_commands_in_array_passes(self, kanban):
        """Programmatic criterion with multiple commands in mov_commands passes."""
        criteria = [make_v5_criterion(cmds=[
            {"cmd": "true", "timeout": 5},
            {"cmd": "echo hello", "timeout": 10},
        ])]
        try:
            kanban.validate_criteria_schema(criteria)
        except SystemExit as e:
            pytest.fail(f"Unexpected SystemExit({e.code}) for multi-command criterion")

    def test_v4_mov_command_field_rejected(self, kanban, capsys):
        """v4 schema: mov_command field is rejected with a clear error."""
        criteria = [make_v4_criterion()]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "v4" in captured.err.lower() or "mov_command" in captured.err
        assert "mov_commands" in captured.err  # tells user the v5 field name

    def test_v4_mov_timeout_field_rejected(self, kanban, capsys):
        """v4 schema: mov_timeout field is rejected with a clear error."""
        criteria = [{
            "text": "Old style",
            "mov_type": "programmatic",
            "mov_timeout": 10,
            "mov_commands": [{"cmd": "true", "timeout": 10}],
        }]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "v4" in captured.err.lower() or "mov_timeout" in captured.err

    def test_programmatic_requires_non_empty_mov_commands(self, kanban, capsys):
        """Programmatic criterion with empty mov_commands is rejected."""
        criteria = [{"text": "Check", "mov_type": "programmatic", "mov_commands": []}]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1

    def test_programmatic_requires_mov_commands_present(self, kanban, capsys):
        """Programmatic criterion missing mov_commands is rejected."""
        criteria = [{"text": "Check", "mov_type": "programmatic"}]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1

    def test_cmd_entry_requires_cmd_field(self, kanban, capsys):
        """mov_commands entry missing 'cmd' is rejected."""
        criteria = [make_v5_criterion(cmds=[{"timeout": 5}])]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1

    def test_cmd_entry_requires_timeout_field(self, kanban, capsys):
        """mov_commands entry missing 'timeout' is rejected."""
        criteria = [make_v5_criterion(cmds=[{"cmd": "true"}])]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1

    def test_timeout_out_of_range_rejected(self, kanban, capsys):
        """timeout=0, timeout=1801, and timeout=-1 are rejected (range is 1-1800)."""
        for bad_timeout in (0, 1801, -1):
            criteria = [make_v5_criterion(cmds=[{"cmd": "true", "timeout": bad_timeout}])]
            with pytest.raises(SystemExit):
                kanban.validate_criteria_schema(criteria)

    def test_timeout_must_be_integer(self, kanban, capsys):
        """timeout as string is rejected."""
        criteria = [make_v5_criterion(cmds=[{"cmd": "true", "timeout": "30"}])]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1

    def test_semantic_with_non_empty_mov_commands_rejected(self, kanban, capsys):
        """Semantic criterion with non-empty mov_commands is rejected."""
        criteria = [{
            "text": "Semantic",
            "mov_type": "semantic",
            "mov_commands": [{"cmd": "true", "timeout": 5}],
        }]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# P1.2: cmd_criteria_check array iteration + short-circuit
# ---------------------------------------------------------------------------

class TestCriteriaCheckArrayIteration:
    """cmd_criteria_check iterates mov_commands in order, short-circuits on failure."""

    def _build_card_file(self, tmp_path: Path, criteria: list) -> Path:
        """Write a minimal doing-column card to tmp_path and return its path."""
        doing_dir = tmp_path / "doing"
        doing_dir.mkdir(parents=True, exist_ok=True)
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "type": "work",
            "agent": "swe-backend",
            "session": "test-session",
            "criteria": criteria,
            "editFiles": [],
            "readFiles": [],
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        }
        card_path = doing_dir / "42.json"
        card_path.write_text(json.dumps(card))
        return card_path

    def _make_args(self, root: str, card: str, n: list) -> MagicMock:
        args = MagicMock()
        args.root = root
        args.card = card
        args.n = n
        return args

    def test_all_commands_pass_sets_met(self, kanban, tmp_path):
        """When all commands in mov_commands exit 0, met is set to True."""
        criteria = [make_v5_criterion(cmds=[
            {"cmd": "true", "timeout": 5},
            {"cmd": "true", "timeout": 5},
        ])]
        card_path = self._build_card_file(tmp_path, criteria)
        args = self._make_args(str(tmp_path), "42", ["1"])

        # Patch subprocess.run to simulate all commands passing
        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            kanban.cmd_criteria_check(args)

        # Re-read card and verify met
        import json as _json
        updated = _json.loads(card_path.read_text())
        assert updated["criteria"][0]["met"] is True

    def test_first_command_fails_short_circuits(self, kanban, tmp_path, capsys):
        """When first command fails, second command is NOT executed."""
        criteria = [make_v5_criterion(cmds=[
            {"cmd": "false", "timeout": 5},
            {"cmd": "true", "timeout": 5},  # should NOT be reached
        ])]
        card_path = self._build_card_file(tmp_path, criteria)
        args = self._make_args(str(tmp_path), "42", ["1"])

        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            if call_count[0] == 1:
                m.returncode = 1  # first command fails
            return m

        with pytest.raises(SystemExit) as exc_info:
            with patch("subprocess.run", side_effect=fake_run):
                kanban.cmd_criteria_check(args)

        assert exc_info.value.code == 1, "Expected exit 1 on work failure"
        assert call_count[0] == 1, (
            f"Expected short-circuit after first failure; got {call_count[0]} calls"
        )

    def test_first_passes_second_fails_exits_one(self, kanban, tmp_path, capsys):
        """First command passes, second fails → exits 1 with failed_index=1."""
        criteria = [make_v5_criterion(cmds=[
            {"cmd": "true", "timeout": 5},
            {"cmd": "false", "timeout": 5},
        ])]
        card_path = self._build_card_file(tmp_path, criteria)
        args = self._make_args(str(tmp_path), "42", ["1"])

        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            m.stdout = ""
            m.stderr = ""
            m.returncode = 0 if call_count[0] == 1 else 1
            return m

        with pytest.raises(SystemExit) as exc_info:
            with patch("subprocess.run", side_effect=fake_run):
                kanban.cmd_criteria_check(args)

        assert exc_info.value.code == 1
        assert call_count[0] == 2, "Expected both commands to be attempted"
        captured = capsys.readouterr()
        assert "failed_index: 1" in captured.err

    def test_exit_127_emits_error_diagnostic(self, kanban, tmp_path, capsys):
        """Exit 127 (command not found) → exits 10 with diagnostic."""
        criteria = [make_v5_criterion(cmds=[{"cmd": "nonexistent_xyz", "timeout": 5}])]
        card_path = self._build_card_file(tmp_path, criteria)
        args = self._make_args(str(tmp_path), "42", ["1"])

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 127
            m.stdout = ""
            m.stderr = "command not found"
            return m

        with pytest.raises(SystemExit) as exc_info:
            with patch("subprocess.run", side_effect=fake_run):
                kanban.cmd_criteria_check(args)

        assert exc_info.value.code == 10

    def test_exit_2_emits_error_diagnostic(self, kanban, tmp_path, capsys):
        """Exit 2 (bash syntax error) → exits 10 with diagnostic, not exit 1."""
        criteria = [make_v5_criterion(cmds=[{"cmd": "echo test", "timeout": 5}])]
        card_path = self._build_card_file(tmp_path, criteria)
        args = self._make_args(str(tmp_path), "42", ["1"])

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 2
            m.stdout = ""
            m.stderr = "syntax error near unexpected token"
            return m

        with pytest.raises(SystemExit) as exc_info:
            with patch("subprocess.run", side_effect=fake_run):
                kanban.cmd_criteria_check(args)

        assert exc_info.value.code == 10, (
            f"Expected exit 10 (command error) for rc==2, got exit {exc_info.value.code}"
        )

    def test_timeout_exits_11(self, kanban, tmp_path, capsys):
        """TimeoutExpired → exits 11 with clear message."""
        criteria = [make_v5_criterion(cmds=[{"cmd": "sleep 100", "timeout": 1}])]
        card_path = self._build_card_file(tmp_path, criteria)
        args = self._make_args(str(tmp_path), "42", ["1"])

        import subprocess as _subprocess

        def fake_run(cmd, **kwargs):
            raise _subprocess.TimeoutExpired(cmd=cmd, timeout=1)

        with pytest.raises(SystemExit) as exc_info:
            with patch("subprocess.run", side_effect=fake_run):
                kanban.cmd_criteria_check(args)

        assert exc_info.value.code == 11

    def test_semantic_criterion_rejected_by_check(self, kanban, tmp_path, capsys):
        """Criterion with no mov_commands is rejected by criteria check (exit 1).

        Prior behavior: semantic criteria (empty/absent mov_commands) were unconditionally
        marked met. This was a quality-gate bypass bug. The new behavior rejects them
        with a clear error — they must be created with programmatic mov_commands.
        """
        criteria = [{"text": "Semantic check", "mov_type": "semantic", "met": False}]
        card_path = self._build_card_file(tmp_path, criteria)
        args = self._make_args(str(tmp_path), "42", ["1"])

        with pytest.raises(SystemExit) as exc_info:
            kanban.cmd_criteria_check(args)

        assert exc_info.value.code == 1, (
            f"Expected exit 1 for criterion without mov_commands, got {exc_info.value.code}"
        )
        captured = capsys.readouterr()
        assert "no programmatic verification provided" in captured.err, (
            f"Expected 'no programmatic verification provided' in stderr, got: {captured.err!r}"
        )

        import json as _json
        updated = _json.loads(card_path.read_text())
        assert updated["criteria"][0]["met"] is False, (
            "Card state must not be mutated when criterion has no mov_commands"
        )


# ---------------------------------------------------------------------------
# P1.4: __CARD_ID__ substitution
# ---------------------------------------------------------------------------

class TestCardIdSubstitution:
    """substitute_card_id_placeholders() and create_card_in_column() replace __CARD_ID__."""

    def test_substitute_replaces_in_criterion_text(self, kanban):
        """__CARD_ID__ in criterion text is replaced with the card number."""
        card = make_minimal_card(criteria=[{
            "text": "Check card __CARD_ID__ exists",
            "mov_type": "semantic",
            "met": False,
        }])
        kanban.substitute_card_id_placeholders(card, 42)
        assert card["criteria"][0]["text"] == "Check card 42 exists"

    def test_substitute_replaces_in_mov_commands_cmd(self, kanban):
        """__CARD_ID__ in mov_commands[].cmd is replaced with the card number."""
        card = make_minimal_card(criteria=[{
            "text": "Programmatic check",
            "mov_type": "programmatic",
            "mov_commands": [
                {"cmd": "kanban criteria check __CARD_ID__ 1 --session s", "timeout": 10},
            ],
            "met": False,
        }])
        kanban.substitute_card_id_placeholders(card, 99)
        assert card["criteria"][0]["mov_commands"][0]["cmd"] == "kanban criteria check 99 1 --session s"

    def test_substitute_multiple_occurrences_in_cmd(self, kanban):
        """Multiple __CARD_ID__ tokens in a single cmd are all replaced."""
        card = make_minimal_card(criteria=[{
            "text": "Multi check",
            "mov_type": "programmatic",
            "mov_commands": [
                {"cmd": "echo __CARD_ID__ && kanban show __CARD_ID__", "timeout": 5},
            ],
            "met": False,
        }])
        kanban.substitute_card_id_placeholders(card, 7)
        assert card["criteria"][0]["mov_commands"][0]["cmd"] == "echo 7 && kanban show 7"

    def test_substitute_multiple_criteria(self, kanban):
        """__CARD_ID__ replaced in all criteria, not just first."""
        card = make_minimal_card(criteria=[
            {
                "text": "Check __CARD_ID__ alpha",
                "mov_type": "programmatic",
                "mov_commands": [{"cmd": "rg __CARD_ID__ file.txt", "timeout": 5}],
                "met": False,
            },
            {
                "text": "Check __CARD_ID__ beta",
                "mov_type": "semantic",
                "met": False,
            },
        ])
        kanban.substitute_card_id_placeholders(card, 123)
        assert card["criteria"][0]["text"] == "Check 123 alpha"
        assert card["criteria"][0]["mov_commands"][0]["cmd"] == "rg 123 file.txt"
        assert card["criteria"][1]["text"] == "Check 123 beta"

    def test_substitute_does_not_touch_action(self, kanban):
        """__CARD_ID__ in action field is NOT replaced (out of scope)."""
        card = make_minimal_card()
        card["action"] = "Work on card __CARD_ID__"
        kanban.substitute_card_id_placeholders(card, 42)
        assert card["action"] == "Work on card __CARD_ID__"

    def test_substitute_does_not_touch_intent(self, kanban):
        """__CARD_ID__ in intent field is NOT replaced (out of scope)."""
        card = make_minimal_card()
        card["intent"] = "Because card __CARD_ID__ needs it"
        kanban.substitute_card_id_placeholders(card, 42)
        assert card["intent"] == "Because card __CARD_ID__ needs it"

    def test_substitute_no_token_is_noop(self, kanban):
        """When no __CARD_ID__ tokens exist, card is unchanged."""
        card = make_minimal_card(criteria=[{
            "text": "Plain criterion",
            "mov_type": "programmatic",
            "mov_commands": [{"cmd": "true", "timeout": 5}],
            "met": False,
        }])
        original_text = card["criteria"][0]["text"]
        original_cmd = card["criteria"][0]["mov_commands"][0]["cmd"]
        kanban.substitute_card_id_placeholders(card, 55)
        assert card["criteria"][0]["text"] == original_text
        assert card["criteria"][0]["mov_commands"][0]["cmd"] == original_cmd

    def test_create_card_applies_substitution(self, kanban, tmp_path):
        """create_card_in_column() applies __CARD_ID__ substitution before writing."""
        card = make_minimal_card(criteria=[{
            "text": "Check card __CARD_ID__",
            "mov_type": "programmatic",
            "mov_commands": [
                {"cmd": "kanban show __CARD_ID__", "timeout": 10},
            ],
            "met": False,
        }])

        # Ensure the column directory exists
        doing_dir = tmp_path / "doing"
        doing_dir.mkdir(parents=True, exist_ok=True)
        # Also create other columns so next_number works
        for col in ("todo", "review", "done", "canceled"):
            (tmp_path / col).mkdir(exist_ok=True)

        num = kanban.create_card_in_column(tmp_path, "doing", card)

        import json as _json
        card_path = doing_dir / f"{num}.json"
        written = _json.loads(card_path.read_text())
        assert str(num) in written["criteria"][0]["text"]
        assert str(num) in written["criteria"][0]["mov_commands"][0]["cmd"]
        # Verify placeholder is gone
        assert "__CARD_ID__" not in written["criteria"][0]["text"]
        assert "__CARD_ID__" not in written["criteria"][0]["mov_commands"][0]["cmd"]


# ---------------------------------------------------------------------------
# Enforcement: criteria add defaults to semantic; programmatic requires
# mov_commands; every mutating path validates before write.
# ---------------------------------------------------------------------------

class TestCriteriaAddDefaultsSemantic:
    """criteria add without --mov-cmd creates criterion with empty mov_commands."""

    def _build_card_file(self, tmp_path: Path, criteria: list | None = None) -> Path:
        """Write a minimal doing-column card and return its path."""
        doing_dir = tmp_path / "doing"
        doing_dir.mkdir(parents=True, exist_ok=True)
        if criteria is None:
            criteria = [{"text": "Existing AC", "mov_commands": [{"cmd": "true", "timeout": 5}], "met": False}]
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "type": "work",
            "agent": "swe-backend",
            "session": "test-session",
            "criteria": criteria,
            "editFiles": [],
            "readFiles": [],
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        }
        card_path = doing_dir / "99.json"
        card_path.write_text(json.dumps(card))
        return card_path

    def test_criteria_add_without_mov_cmd_has_empty_mov_commands(self, kanban, tmp_path):
        """kanban criteria add without --mov-cmd creates criterion with empty mov_commands.

        The criterion will be rejected by 'kanban criteria check' (exit 1).
        This tests the add path only — the check-time rejection is tested elsewhere.
        """
        card_path = self._build_card_file(tmp_path)

        args = SimpleNamespace(
            root=str(tmp_path),
            card="99",
            text="New criterion added via CLI",
            mov_cmd=None,
            mov_timeout=None,
        )

        kanban.cmd_criteria_add(args)

        updated = json.loads(card_path.read_text())
        new_criterion = updated["criteria"][-1]
        assert new_criterion.get("mov_commands") == [], (
            f"Expected empty mov_commands when --mov-cmd not provided, "
            f"got {new_criterion.get('mov_commands')!r}"
        )
        assert "mov_type" not in new_criterion, (
            "mov_type must not be set by criteria add — it is legacy and unused"
        )

    def test_criteria_add_without_mov_cmd_passes_validation(self, kanban, tmp_path):
        """Criterion added via criteria add (no --mov-cmd) passes validate_criteria_schema.

        Schema validation allows empty mov_commands — rejection happens at check-time,
        not at add-time. This test ensures add succeeds (no SystemExit).
        """
        card_path = self._build_card_file(tmp_path)

        args = SimpleNamespace(
            root=str(tmp_path),
            card="99",
            text="Another criterion",
            mov_cmd=None,
            mov_timeout=None,
        )

        # Should not raise SystemExit
        try:
            kanban.cmd_criteria_add(args)
        except SystemExit as e:
            pytest.fail(f"cmd_criteria_add raised SystemExit({e.code}) for a valid add without --mov-cmd")


class TestProgrammaticRequiresMoveCommands:
    """validate_criteria_schema rejects programmatic criterion without mov_commands."""

    def test_programmatic_without_mov_commands_raises(self, kanban, capsys):
        """Direct validation of programmatic criterion missing mov_commands raises SystemExit."""
        criteria = [{"text": "Check something", "mov_type": "programmatic"}]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        # Message should name the criterion and explain what's missing
        assert "programmatic" in captured.err.lower() or "mov_commands" in captured.err

    def test_programmatic_with_empty_mov_commands_raises(self, kanban, capsys):
        """Programmatic criterion with empty mov_commands array raises SystemExit."""
        criteria = [{"text": "Check something", "mov_type": "programmatic", "mov_commands": []}]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_criteria_schema(criteria)
        assert exc_info.value.code == 1

    def test_programmatic_with_valid_mov_commands_passes(self, kanban):
        """Programmatic criterion with valid mov_commands passes without error."""
        criteria = [make_v5_criterion(text="Valid check", mov_type="programmatic")]
        try:
            kanban.validate_criteria_schema(criteria)
        except SystemExit as e:
            pytest.fail(f"Unexpected SystemExit({e.code}) for valid programmatic criterion")


class TestCriteriaMutationValidation:
    """Every criteria-mutating command (check, uncheck, remove) calls
    validate_criteria_schema before writing the card.

    We inject a broken-state card (programmatic criterion missing mov_commands) and
    verify that each mutation command rejects the write rather than silently
    persisting bad state.
    """

    def _build_broken_card_file(self, tmp_path: Path, column: str = "doing") -> Path:
        """Write a card with a programmatic criterion that has no mov_commands."""
        col_dir = tmp_path / column
        col_dir.mkdir(parents=True, exist_ok=True)
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "type": "work",
            "agent": "swe-backend",
            "session": "test-session",
            "criteria": [
                {
                    "text": "Broken programmatic criterion",
                    "mov_type": "programmatic",
                    # Intentionally omits mov_commands — invalid v5 state
                    "met": False,
                }
            ],
            "editFiles": [],
            "readFiles": [],
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        }
        card_path = col_dir / "77.json"
        card_path.write_text(json.dumps(card))
        return card_path

    def _build_valid_card_file(self, tmp_path: Path, column: str = "doing") -> Path:
        """Write a card with valid programmatic criteria (non-empty mov_commands)."""
        col_dir = tmp_path / column
        col_dir.mkdir(parents=True, exist_ok=True)
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "type": "work",
            "agent": "swe-backend",
            "session": "test-session",
            "criteria": [
                {
                    "text": "Valid programmatic criterion",
                    "mov_commands": [{"cmd": "true", "timeout": 5}],
                    "met": False,
                },
                {
                    "text": "Second valid programmatic criterion",
                    "mov_commands": [{"cmd": "true", "timeout": 5}],
                    "met": False,
                },
            ],
            "editFiles": [],
            "readFiles": [],
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        }
        card_path = col_dir / "77.json"
        card_path.write_text(json.dumps(card))
        return card_path

    def _make_args(self, root: str, card: str = "77", **kwargs) -> MagicMock:
        args = MagicMock()
        args.root = root
        args.card = card
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    @pytest.mark.parametrize("subcommand", ["check", "uncheck"])
    def test_check_and_uncheck_reject_broken_state(self, kanban, tmp_path, subcommand):
        """cmd_criteria_check and cmd_criteria_uncheck reject a broken-state card."""
        self._build_broken_card_file(tmp_path, column="doing")
        args = self._make_args(str(tmp_path), n=["1"])

        cmd_fn = kanban.cmd_criteria_check if subcommand == "check" else kanban.cmd_criteria_uncheck

        if subcommand == "check":
            def fake_run(cmd, **kwargs):
                m = MagicMock()
                m.returncode = 0
                m.stdout = ""
                m.stderr = ""
                return m
            with pytest.raises(SystemExit) as exc_info:
                with patch("subprocess.run", side_effect=fake_run):
                    cmd_fn(args)
        else:
            with pytest.raises(SystemExit) as exc_info:
                cmd_fn(args)

        assert exc_info.value.code == 1

    def test_remove_rejects_broken_state(self, kanban, tmp_path):
        """cmd_criteria_remove rejects a broken-state card (programmatic without mov_commands)."""
        # Build a card with TWO criteria so remove doesn't fail on "last criterion" guard.
        col_dir = tmp_path / "doing"
        col_dir.mkdir(parents=True, exist_ok=True)
        card = {
            "action": "Test action",
            "intent": "Test intent",
            "type": "work",
            "agent": "swe-backend",
            "session": "test-session",
            "criteria": [
                {
                    "text": "Broken programmatic criterion",
                    "mov_type": "programmatic",
                    # Intentionally omits mov_commands
                    "met": False,
                },
                {
                    "text": "Second criterion",
                    "mov_type": "semantic",
                    "met": False,
                },
            ],
            "editFiles": [],
            "readFiles": [],
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        }
        card_path = col_dir / "77.json"
        card_path.write_text(json.dumps(card))

        args = self._make_args(str(tmp_path), n=2, reason="cleanup")

        with pytest.raises(SystemExit) as exc_info:
            kanban.cmd_criteria_remove(args)

        assert exc_info.value.code == 1

    def test_valid_card_check_succeeds(self, kanban, tmp_path):
        """Sanity check: valid programmatic card passes check when mov_commands exit 0."""
        self._build_valid_card_file(tmp_path, column="doing")
        args = self._make_args(str(tmp_path), n=["1"])

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run):
            # Should not raise SystemExit — valid programmatic criterion passes
            try:
                kanban.cmd_criteria_check(args)
            except SystemExit as e:
                pytest.fail(f"Valid programmatic card raised SystemExit({e.code})")


# ---------------------------------------------------------------------------
# Bug fix: kanban cancel <card> <reason> — reason was being passed to
# card-lookup, producing a spurious "No card found matching '<reason>'" error
# and exiting with code 1 even though the cancel succeeded.
# ---------------------------------------------------------------------------

class TestCancelWithReason:
    """cmd_cancel correctly handles positional reason argument."""

    def _build_board(self, tmp_path: Path, card_num: int = 42, column: str = "doing") -> Path:
        """Create a minimal kanban board with one card; return the card path."""
        for col in ("todo", "doing", "review", "done", "canceled"):
            (tmp_path / col).mkdir(parents=True, exist_ok=True)
        (tmp_path / "archive").mkdir(exist_ok=True)
        (tmp_path / "scratchpad").mkdir(exist_ok=True)
        card = {
            "action": "Do something",
            "intent": "Because reasons",
            "type": "work",
            "agent": "swe-backend",
            "session": "test-session",
            "criteria": [{"text": "AC", "mov_type": "semantic", "met": False}],
            "editFiles": [],
            "readFiles": [],
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        }
        card_path = tmp_path / column / f"{card_num}.json"
        card_path.write_text(json.dumps(card))
        return card_path

    def _make_cancel_args(self, root: str, cards: list[str], reason: str | None = None):
        args = MagicMock()
        args.root = root
        args.card = cards
        args.reason = reason
        return args

    def test_cancel_with_positional_reason_exits_zero(self, kanban, tmp_path, capsys):
        """cancel <card> <reason> exits 0 and prints one 'Canceled: #N' line."""
        self._build_board(tmp_path, card_num=42)

        # Simulate argparse nargs="+" absorbing reason as last card element
        args = self._make_cancel_args(str(tmp_path), ["42", "Pre-v5 card. Abandoned."])

        # cmd_cancel must not raise SystemExit
        kanban.cmd_cancel(args)

        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 1, f"Expected exactly 1 output line, got: {lines!r}"
        assert "Canceled: #42" in lines[0], f"Expected 'Canceled: #42' in output, got: {lines[0]!r}"
        assert "Error" not in out, f"Unexpected error in output: {out!r}"

    def test_cancel_with_positional_reason_persists_reason(self, kanban, tmp_path):
        """cancel <card> <reason> writes cancelReason to the card's JSON."""
        self._build_board(tmp_path, card_num=42)
        args = self._make_cancel_args(str(tmp_path), ["42", "Pre-v5 card. Abandoned."])

        kanban.cmd_cancel(args)

        card_path = tmp_path / "canceled" / "42.json"
        assert card_path.exists(), "Card was not moved to canceled column"
        card = json.loads(card_path.read_text())
        assert card.get("cancelReason") == "Pre-v5 card. Abandoned.", (
            f"cancelReason not persisted; card={card!r}"
        )

    def test_cancel_no_reason_still_works(self, kanban, tmp_path, capsys):
        """cancel <card> with no reason still cancels correctly."""
        self._build_board(tmp_path, card_num=7)
        args = self._make_cancel_args(str(tmp_path), ["7"])

        kanban.cmd_cancel(args)

        out = capsys.readouterr().out
        assert "Canceled: #7" in out
        assert "Error" not in out
