"""
Tests for kanban list --output-style=xml terse schema.

The list XML output is intentionally terse: designed for coordinators to
answer coordination questions at a glance (which cards are in flight, what
files are they editing, what is each card roughly about).

Schema under test:
  <board session="...">
    <mine>
      <c n="NNN" s="status">
        <i>intent truncated to 200 chars...</i>
        <e>editFile1,editFile2</e>
      </c>
    </mine>
    <others>
      <c n="NNN" ses="session-name" s="status">
        ...
      </c>
    </others>
  </board>

EXCLUDED from list XML (use kanban show for these):
  - <a> action field (main culprit; 2000-3000 chars of instructions)
  - <r> readFiles — not coordination-critical; read access never conflicts.
    Excluded per user refinement to keep list maximally terse.
  - <criteria> / acceptance criteria
  - model, type, subagent_type, agent metadata
  - activity, comments

INCLUDED:
  - n (card number), s (status) attributes
  - ses attribute on <others> cards only
  - <i> intent (truncated at 200 chars with "..." ellipsis)
  - <e> editFiles (comma-separated, coordination-critical for conflict detection)

The constant _INTENT_MAX in kanban.py governs the truncation length (200).
"""

import importlib.util
import io
import json
import sys
import xml.etree.ElementTree as ET
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

    spec = importlib.util.spec_from_file_location("kanban_list_xml", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INTENT_MAX = 200  # must match _INTENT_MAX in kanban.py


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


def _make_card(
    action="Do the thing",
    intent="Because reasons",
    session="test-session",
    edit_files=None,
    read_files=None,
    criteria=None,
):
    """Build a minimal card dict."""
    card = {
        "action": action,
        "intent": intent,
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": edit_files or [],
        "readFiles": read_files or [],
        "criteria": criteria or [],
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }
    return card


def _make_args(root, session=None):
    """Build a minimal args namespace for cmd_list."""
    args = SimpleNamespace(
        root=str(root),
        session=session,
        output_style="xml",
        column=None,
        show_done=False,
        show_canceled=False,
        show_all=False,
        since=None,
        until=None,
        hide_mine=False,
        show_only_mine=False,
        _watch_state=None,
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
# Tests: action field excluded from list XML (terse schema)
# ---------------------------------------------------------------------------

class TestListXmlActionExcluded:
    """The full <a> action element must NOT appear in list XML output.

    Action text is excluded because it can be 2000-3000 chars of instructions,
    which defeats the purpose of a terse list view. Full content is available
    via `kanban show`.
    """

    def test_action_not_in_list_xml_output(self, kanban, tmp_path):
        """List XML output must not contain an <a> element (full action)."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(
            action="This is the full action text with lots of detail",
            intent="Short intent summary",
            session="test-session",
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        # Action element must not appear in list XML
        assert "<a>" not in output, (
            "List XML must not contain <a> action element. "
            "Full action belongs in `kanban show`."
        )
        assert "This is the full action text with lots of detail" not in output, (
            "Action text must not appear verbatim in list XML output."
        )

    def test_action_not_present_regardless_of_session_match(self, kanban, tmp_path):
        """Action excluded from both <mine> and <others> sections."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(
            action="My action text here",
            intent="My card intent",
            session="my-session",
        ))
        _write_card(board, "todo", "2", _make_card(
            action="Other action text here",
            intent="Other card intent",
            session="other-session",
        ))
        args = _make_args(board, session="my-session")
        output = _run_cmd_list(kanban, args, board)

        assert "<a>" not in output
        assert "My action text here" not in output
        assert "Other action text here" not in output


# ---------------------------------------------------------------------------
# Tests: intent truncated at 200 chars
# ---------------------------------------------------------------------------

class TestListXmlIntentTruncated:
    """Intent in list XML must be truncated to INTENT_MAX chars with ellipsis."""

    def test_short_intent_not_truncated(self, kanban, tmp_path):
        """Intent shorter than 200 chars is emitted as-is (no ellipsis)."""
        board = _setup_board(tmp_path)
        short_intent = "A brief intent that fits within the limit."
        _write_card(board, "doing", "1", _make_card(
            intent=short_intent,
            session="test-session",
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        assert len(c_elements) == 1
        i_el = c_elements[0].find("i")
        assert i_el is not None
        assert i_el.text == short_intent

    def test_long_intent_truncated_to_200_chars(self, kanban, tmp_path):
        """Intent longer than 200 chars is truncated to exactly 200 chars + '...'."""
        board = _setup_board(tmp_path)
        long_intent = "X" * 300  # 300 chars, well over limit
        _write_card(board, "doing", "1", _make_card(
            intent=long_intent,
            session="test-session",
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        i_el = c_elements[0].find("i")
        assert i_el is not None
        # Truncated text is exactly INTENT_MAX chars followed by "..."
        assert i_el.text is not None
        assert i_el.text.endswith("..."), (
            f"Truncated intent must end with '...', got: {i_el.text!r}"
        )
        # Content before "..." is 200 chars
        content_before_ellipsis = i_el.text[:-3]
        assert len(content_before_ellipsis) == INTENT_MAX, (
            f"Expected {INTENT_MAX} chars before '...', got {len(content_before_ellipsis)}"
        )

    def test_intent_exactly_200_chars_not_truncated(self, kanban, tmp_path):
        """Intent of exactly 200 chars is not truncated (boundary condition)."""
        board = _setup_board(tmp_path)
        exact_intent = "B" * INTENT_MAX  # exactly at limit
        _write_card(board, "doing", "1", _make_card(
            intent=exact_intent,
            session="test-session",
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        i_el = c_elements[0].find("i")
        assert i_el is not None
        assert i_el.text == exact_intent, (
            "Intent of exactly 200 chars should not be truncated or have '...' appended"
        )
        assert not i_el.text.endswith("...")

    def test_intent_201_chars_is_truncated(self, kanban, tmp_path):
        """Intent of 201 chars is truncated (one over the boundary)."""
        board = _setup_board(tmp_path)
        over_intent = "C" * (INTENT_MAX + 1)  # one over limit
        _write_card(board, "doing", "1", _make_card(
            intent=over_intent,
            session="test-session",
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        i_el = c_elements[0].find("i")
        assert i_el is not None
        assert i_el.text is not None
        assert i_el.text.endswith("...")

    def test_empty_intent_omits_i_element(self, kanban, tmp_path):
        """Card with empty intent emits no <i> element."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(
            intent="",
            session="test-session",
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        assert len(c_elements) == 1
        i_el = c_elements[0].find("i")
        assert i_el is None, "Empty intent must not produce an <i> element"


# ---------------------------------------------------------------------------
# Tests: editFiles present, readFiles excluded from list XML
# ---------------------------------------------------------------------------

class TestListXmlFilesSchema:
    """editFiles must appear in list XML; readFiles must NOT.

    editFiles are coordination-critical: coordinators use them to detect file
    conflicts before delegating parallel work. readFiles are not
    coordination-critical (read access never conflicts) and are excluded to
    keep the list maximally terse. Use `kanban show` for readFiles.
    """

    def test_edit_files_present_in_list_xml(self, kanban, tmp_path):
        """<e> element with editFiles appears when card has edit files."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(
            session="test-session",
            edit_files=["modules/foo/bar.py", "modules/foo/baz.py"],
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        assert len(c_elements) == 1
        e_el = c_elements[0].find("e")
        assert e_el is not None, "<e> editFiles element must be present"
        # All files must appear in the element text
        assert "modules/foo/bar.py" in e_el.text
        assert "modules/foo/baz.py" in e_el.text

    def test_read_files_excluded_from_list_xml(self, kanban, tmp_path):
        """<r> readFiles element must NOT appear in list XML output.

        readFiles are excluded from list XML because read access never creates
        file conflicts. Full readFiles are available via `kanban show`.
        """
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(
            session="test-session",
            read_files=["~/.claude/CLAUDE.md", "modules/claude/default.nix"],
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        # readFiles element must be absent from list XML
        assert "<r>" not in output, (
            "List XML must not contain <r> readFiles element. "
            "readFiles are not coordination-critical and belong in `kanban show`."
        )
        assert "~/.claude/CLAUDE.md" not in output, (
            "readFiles paths must not appear in list XML output."
        )
        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        r_el = c_elements[0].find("r")
        assert r_el is None, "<r> element must be absent from list XML"

    def test_read_files_excluded_even_when_edit_files_present(self, kanban, tmp_path):
        """readFiles excluded even on cards that also have editFiles."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(
            session="test-session",
            edit_files=["modules/foo/handler.py"],
            read_files=["~/.claude/CLAUDE.md"],
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        assert c_elements[0].find("e") is not None, "<e> editFiles must be present"
        assert c_elements[0].find("r") is None, "<r> readFiles must be absent"

    def test_no_edit_files_omits_e_element(self, kanban, tmp_path):
        """Card with no editFiles produces no <e> element (not an empty tag)."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(
            session="test-session",
            edit_files=[],
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        e_el = c_elements[0].find("e")
        assert e_el is None, "<e> element must be absent when editFiles is empty"

    def test_edit_files_all_entries_preserved(self, kanban, tmp_path):
        """All editFile entries are preserved even when many (coordination-critical)."""
        board = _setup_board(tmp_path)
        many_files = [f"modules/svc{i}/handler.py" for i in range(15)]
        _write_card(board, "doing", "1", _make_card(
            session="test-session",
            edit_files=many_files,
        ))
        args = _make_args(board, session="test-session")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        c_elements = list(root.iter("c"))
        e_el = c_elements[0].find("e")
        assert e_el is not None
        for f in many_files:
            assert f in e_el.text, f"Missing file {f} in <e> element"


# ---------------------------------------------------------------------------
# Tests: show command still has full action content
# ---------------------------------------------------------------------------

class TestShowCommandFullContentPreserved:
    """kanban show must still include full action/criteria (no regression)."""

    def test_show_xml_contains_action(self, kanban, tmp_path):
        """show --output-style=xml includes the full <action> element."""
        board = _setup_board(tmp_path)
        long_action = "Full detailed action: " + "A" * 500
        _write_card(board, "doing", "1", _make_card(
            action=long_action,
            intent="Short intent",
            session="test-session",
        ))

        card_path = board / "doing" / "1.json"
        args = SimpleNamespace(
            root=str(board),
            card="1",
            output_style="xml",
            session="test-session",
        )

        captured = io.StringIO()
        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch.object(kanban, "read_card",
                                   return_value=json.loads(card_path.read_text())):
                    with patch("sys.stdout", captured):
                        kanban.cmd_show(args)

        show_output = captured.getvalue()
        # Full action element must appear in show output
        assert "<action>" in show_output, (
            "show --output-style=xml must include <action> element"
        )
        assert long_action in show_output, (
            "show output must contain the full (untruncated) action text"
        )

    def test_list_xml_does_not_contain_full_action_when_show_does(
        self, kanban, tmp_path
    ):
        """Confirm the list/show divergence: list excludes action, show includes it."""
        board = _setup_board(tmp_path)
        unique_action = "UNIQUE_ACTION_MARKER_XYZ_DO_NOT_APPEAR_IN_LIST"
        _write_card(board, "doing", "1", _make_card(
            action=unique_action,
            intent="Some intent",
            session="test-session",
        ))

        # List output must NOT contain the action
        args = _make_args(board, session="test-session")
        list_output = _run_cmd_list(kanban, args, board)
        assert unique_action not in list_output, (
            "List XML must not contain action text that is only for show"
        )

        # Show output MUST contain the action
        card_path = board / "doing" / "1.json"
        show_args = SimpleNamespace(
            root=str(board),
            card="1",
            output_style="xml",
            session="test-session",
        )
        captured = io.StringIO()
        with patch.object(kanban, "get_root", return_value=board):
            with patch.object(kanban, "find_card", return_value=card_path):
                with patch.object(kanban, "read_card",
                                   return_value=json.loads(card_path.read_text())):
                    with patch("sys.stdout", captured):
                        kanban.cmd_show(show_args)

        assert unique_action in captured.getvalue(), (
            "Show XML must contain the full action text"
        )
