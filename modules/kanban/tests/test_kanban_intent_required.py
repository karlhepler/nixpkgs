"""
Tests for kanban.py intent field validation at card creation time.

Covers:
- Card JSON without 'intent' field is rejected with exit 1 and error message about intent
- Card JSON without 'action' field is rejected with exit 1 (regression check)
- Card JSON with both 'intent' and 'action' is accepted (regression check)
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

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

    spec = importlib.util.spec_from_file_location("kanban_intent_required", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_full_card_data(action="Do the thing", intent="Because reasons"):
    """Build a minimal valid card JSON dict with a required criterion."""
    return {
        "action": action,
        "intent": intent,
        "type": "work",
        "agent": "swe-devex",
        "criteria": [{"text": "Some check", "mov_type": "programmatic", "mov_commands": [{"cmd": "true", "timeout": 5}], "met": False}],
    }


def make_card_data_without_intent():
    """Build a card JSON dict missing the 'intent' field."""
    return {
        "action": "Do the thing",
        "type": "work",
        "agent": "swe-devex",
    }


def make_card_data_without_action():
    """Build a card JSON dict missing the 'action' field."""
    return {
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-devex",
    }


# ---------------------------------------------------------------------------
# Tests: missing intent rejection
# ---------------------------------------------------------------------------

class TestMissingIntentRejection:
    """validate_and_build_card rejects cards that are missing the 'intent' field."""

    def test_missing_intent_exits_1(self, kanban):
        """Card without 'intent' field is rejected with exit code 1."""
        data = make_card_data_without_intent()
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test-session")
        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for missing intent, got {exc_info.value.code}"
        )

    def test_missing_intent_prints_error_message(self, kanban, capsys):
        """Card without 'intent' field prints error message about intent to stderr."""
        data = make_card_data_without_intent()
        with pytest.raises(SystemExit):
            kanban.validate_and_build_card(data, session="test-session")
        captured = capsys.readouterr()
        assert "intent" in captured.err.lower(), (
            f"Expected 'intent' in stderr error message, got: {captured.err!r}"
        )

    def test_missing_intent_error_uses_expected_message(self, kanban, capsys):
        """Card without 'intent' field prints the canonical error message format."""
        data = make_card_data_without_intent()
        with pytest.raises(SystemExit):
            kanban.validate_and_build_card(data, session="test-session")
        captured = capsys.readouterr()
        assert "JSON must include 'intent' field" in captured.err, (
            f"Expected canonical error message, got: {captured.err!r}"
        )


# ---------------------------------------------------------------------------
# Tests: missing action regression check
# ---------------------------------------------------------------------------

class TestMissingActionRegressionCheck:
    """validate_and_build_card still rejects cards missing 'action' (regression guard)."""

    def test_missing_action_exits_1(self, kanban):
        """Card without 'action' field is rejected with exit code 1."""
        data = make_card_data_without_action()
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test-session")
        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for missing action, got {exc_info.value.code}"
        )

    def test_missing_action_prints_error_message(self, kanban, capsys):
        """Card without 'action' field prints error message about action to stderr."""
        data = make_card_data_without_action()
        with pytest.raises(SystemExit):
            kanban.validate_and_build_card(data, session="test-session")
        captured = capsys.readouterr()
        assert "action" in captured.err.lower(), (
            f"Expected 'action' in stderr error message, got: {captured.err!r}"
        )


# ---------------------------------------------------------------------------
# Tests: empty-string intent rejection
# ---------------------------------------------------------------------------

class TestEmptyStringIntentRejection:
    """validate_and_build_card rejects cards where 'intent' is an empty string."""

    def test_empty_intent_exits_1(self, kanban):
        """Card with empty string 'intent' is rejected with exit code 1."""
        data = make_full_card_data(action="Do the thing", intent="")
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test-session")
        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for empty intent, got {exc_info.value.code}"
        )

    def test_empty_intent_prints_error_message(self, kanban, capsys):
        """Card with empty string 'intent' prints a non-empty string error to stderr."""
        data = make_full_card_data(action="Do the thing", intent="")
        with pytest.raises(SystemExit):
            kanban.validate_and_build_card(data, session="test-session")
        captured = capsys.readouterr()
        assert "non-empty string" in captured.err.lower(), (
            f"Expected 'non-empty string' in stderr error message, got: {captured.err!r}"
        )

    def test_whitespace_only_intent_is_rejected(self, kanban):
        """Card with whitespace-only 'intent' is also rejected with exit code 1."""
        data = make_full_card_data(action="Do the thing", intent="   ")
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_and_build_card(data, session="test-session")
        assert exc_info.value.code == 1, (
            f"Expected exit code 1 for whitespace-only intent, got {exc_info.value.code}"
        )


# ---------------------------------------------------------------------------
# Tests: both fields present — accepted
# ---------------------------------------------------------------------------

class TestBothFieldsPresentAccepted:
    """validate_and_build_card accepts cards that have both 'action' and 'intent'."""

    def test_card_with_action_and_intent_is_accepted(self, kanban):
        """Card with both 'action' and 'intent' fields passes validation without error."""
        data = make_full_card_data(action="Do the thing", intent="Because reasons")
        try:
            card = kanban.validate_and_build_card(data, session="test-session")
        except SystemExit as e:
            pytest.fail(
                f"Valid card with action and intent raised SystemExit({e.code}) — should be accepted"
            )
        assert card is not None, "validate_and_build_card must return a card dict on success"

    def test_card_action_and_intent_appear_in_built_card(self, kanban):
        """Both 'action' and 'intent' are preserved in the card returned by validate_and_build_card."""
        data = make_full_card_data(action="Deploy the service", intent="Reduce manual steps")
        card = kanban.validate_and_build_card(data, session="test-session")
        assert card["action"] == "Deploy the service", (
            "action must be preserved in the built card"
        )
        assert card["intent"] == "Reduce manual steps", (
            "intent must be preserved in the built card"
        )
