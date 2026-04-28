"""
Tests for kanban output-style default and --watch override behavior.

Covers:
- kanban list (no --output-style) defaults to XML output
- kanban list --output-style=simple produces human-readable output
- kanban list --watch always forces simple style (via WatchState)
- kanban list --watch --output-style=xml still forces simple (watch wins)
- test_watch_overrides_output_style: named test required by AC
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

    spec = importlib.util.spec_from_file_location("kanban_output_style", _KANBAN_PATH)
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
    for col in ("todo", "doing", "review", "done", "canceled"):
        (tmp_path / col).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_card(board_root, col, num, card_data):
    """Write a card JSON file into a column directory."""
    card_path = board_root / col / f"{num}.json"
    card_path.write_text(json.dumps(card_data))
    return card_path


def _make_card(action="Do the thing", intent="Because reasons", session="test-session"):
    """Build a minimal card dict."""
    return {
        "action": action,
        "intent": intent,
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": [],
        "readFiles": [],
        "criteria": [],
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


def _make_args(root, output_style=None, session="test-session", watch_state=None):
    """Build a minimal args namespace for cmd_list.

    output_style=None simulates argparse providing the default (xml).
    The default kwarg is not passed through here — callers must set it
    explicitly when testing the 'no flag given' case.
    """
    args = SimpleNamespace(
        root=str(root),
        session=session,
        output_style=output_style if output_style is not None else "xml",  # argparse default
        column=None,
        show_done=False,
        show_canceled=False,
        show_all=False,
        since=None,
        until=None,
        hide_mine=False,
        show_only_mine=False,
        _watch_state=watch_state,
    )
    return args


def _run_cmd_list(kanban_mod, args, board_root):
    """Run cmd_list and return captured stdout as a string."""
    captured = io.StringIO()
    with patch.object(kanban_mod, "get_root", return_value=board_root):
        with patch.object(kanban_mod, "get_current_session_id",
                          return_value=args.session or ""):
            with patch.object(kanban_mod, "resolve_session_filters",
                               return_value=(args.session or "", False, False)):
                with patch("sys.stdout", captured):
                    kanban_mod.cmd_list(args)
    return captured.getvalue()


# ---------------------------------------------------------------------------
# Tests: XML is the new default output style
# ---------------------------------------------------------------------------

class TestXmlIsDefaultOutputStyle:
    """kanban list without --output-style flag defaults to XML."""

    def test_default_output_style_is_xml(self, kanban, tmp_path):
        """cmd_list with no explicit output_style (argparse default=xml) produces XML."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(session="test-session"))

        # Simulate argparse providing the new default "xml"
        args = _make_args(board, output_style="xml", session="test-session")
        output = _run_cmd_list(kanban, args, board)

        assert output.startswith("<board"), (
            f"Default output_style=xml must produce XML starting with <board, got: {output[:80]!r}"
        )

    def test_xml_default_produces_valid_board_element(self, kanban, tmp_path):
        """Default XML output starts with <board and ends with </board>."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(session="test-session"))

        args = _make_args(board, output_style="xml", session="test-session")
        output = _run_cmd_list(kanban, args, board)

        assert "<board" in output
        assert "</board>" in output

    def test_xml_default_does_not_contain_kanban_board_header(self, kanban, tmp_path):
        """Default XML output does not contain the simple/human 'KANBAN BOARD' header."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(session="test-session"))

        args = _make_args(board, output_style="xml", session="test-session")
        output = _run_cmd_list(kanban, args, board)

        assert "KANBAN BOARD" not in output, (
            "XML output must not contain the human-readable 'KANBAN BOARD' header"
        )


# ---------------------------------------------------------------------------
# Tests: explicit --output-style=simple still works
# ---------------------------------------------------------------------------

class TestSimpleStyleStillWorks:
    """Explicit --output-style=simple still produces human-readable output."""

    def test_explicit_simple_produces_non_xml_output(self, kanban, tmp_path):
        """--output-style=simple output does not start with <board."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(session="test-session"))

        args = _make_args(board, output_style="simple", session="test-session")
        output = _run_cmd_list(kanban, args, board)

        assert not output.startswith("<board"), (
            "simple style must not produce XML output"
        )

    def test_explicit_simple_does_not_contain_board_tag(self, kanban, tmp_path):
        """--output-style=simple output contains no <board> XML tag."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(session="test-session"))

        args = _make_args(board, output_style="simple", session="test-session")
        output = _run_cmd_list(kanban, args, board)

        assert "<board" not in output, (
            "simple style must not produce a <board> XML element"
        )


# ---------------------------------------------------------------------------
# Tests: --watch forces simple regardless of --output-style
# ---------------------------------------------------------------------------

class TestWatchForcesSimpleOutputStyle:
    """--watch mode always uses simple output style via WatchState.

    Watch mode creates a WatchState with output_style="simple" which takes
    precedence over any --output-style flag. This test calls cmd_list directly
    with a WatchState injected to verify the behavior without spawning the
    actual blocking watch loop.
    """

    def test_watch_overrides_output_style(self, kanban, tmp_path):
        """--watch forces simple style even when --output-style=xml is set.

        This test is named test_watch_overrides_output_style per AC requirement.
        It injects a WatchState(output_style="simple") directly into cmd_list
        to simulate what watch_and_run does, verifying that watch mode produces
        simple (non-XML) output regardless of the --output-style argument.
        """
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(session="test-session"))

        # Simulate watch_and_run: it creates WatchState(output_style="simple")
        # and injects it as args._watch_state. The --output-style=xml on args
        # is irrelevant because cmd_list checks _watch_state first.
        watch_state = kanban.WatchState(output_style="simple")
        args = _make_args(board, output_style="xml", session="test-session",
                          watch_state=watch_state)

        output = _run_cmd_list(kanban, args, board)

        assert "<board" not in output, (
            "Watch mode (WatchState injected) must produce simple output, not XML, "
            "even when args.output_style='xml'"
        )

    def test_watch_simple_flag_also_uses_simple(self, kanban, tmp_path):
        """Watch mode with --output-style=simple also uses simple output."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(session="test-session"))

        watch_state = kanban.WatchState(output_style="simple")
        args = _make_args(board, output_style="simple", session="test-session",
                          watch_state=watch_state)

        output = _run_cmd_list(kanban, args, board)

        assert "<board" not in output

    def test_watch_state_default_output_style_is_simple(self, kanban):
        """WatchState default output_style is 'simple' (watch starts human-readable)."""
        state = kanban.WatchState()
        assert state.output_style == "simple", (
            f"WatchState must default to 'simple', got '{state.output_style}'"
        )

    def test_watch_state_explicit_simple_is_simple(self, kanban):
        """WatchState(output_style='simple') is indeed simple."""
        state = kanban.WatchState(output_style="simple")
        assert state.output_style == "simple"
