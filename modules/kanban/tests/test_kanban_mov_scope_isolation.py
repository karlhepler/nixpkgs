"""
Tests for cross-card MoV scope-isolation validation in kanban.py.

Covers the check that rejects a MoV path-emptiness assertion (e.g.
`test -z "$(git diff --name-only HEAD -- <path>)"`) when the asserted <path>
overlaps another card's declared editFiles — an assertion that can never pass
because the other card's work will modify that path.

Checked against TWO populations (this is the whole point of the card):
  1. Board cards currently in todo/doing, ACROSS ALL SESSIONS.
  2. SIBLING cards in the same creation batch (`kanban do --file` array) — these
     do not exist on the board yet, so a board-only check would catch NONE of
     the real-world failures this validator exists to prevent.

Covered:
- _mov_extract_emptiness_assertion_paths: dash-z shape, wc-l==0 shape, directory
  path, content-based cmd (no extraction)
- _path_is_prefix_of: directory-containment in both directions, no false match
  on partial-segment names (e.g. 'modules' vs 'modules-extra')
- _mov_path_overlaps_editfile: glob overlap (reused from _globs_overlap),
  directory-containment overlap (both directions), no-overlap case
- check_mov_scope_isolation: board conflict (different session), SAME-BATCH
  SIBLING conflict, directory-contains-editFile shape, no-overlap (no false
  positive), content-based MoV untouched
- _load_scope_isolation_board_cards: loads BOTH todo and doing (unlike
  _load_all_doing_cards, which is doing-only)
- validate_mov_scope_isolation: exits 1 with actionable message naming the
  card/sibling and the overlapping path; clean card returns normally
- cmd_do integration: single-card board conflict rejected; bulk-array SAME-BATCH
  SIBLING conflict rejected; content-based MoV and non-overlapping MoV succeed
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

    spec = importlib.util.spec_from_file_location("kanban_mov_scope_isolation", _KANBAN_PATH)
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


def _dash_z_cmd(path: str) -> str:
    """A `test -z "$(git diff ... -- <path>)"` MoV command asserting path unmodified."""
    return f'test -z "$(git diff --name-only HEAD -- {path})"'


def _wc_zero_cmd(path: str) -> str:
    """A `... | wc -l` MoV command asserting path unmodified, compared via -eq 0."""
    return f'[ "$(git diff --name-only HEAD -- {path} | wc -l)" -eq 0 ]'


def _make_emptiness_criterion(path: str, cmd_builder=_dash_z_cmd):
    return {
        "text": f"{path} is unmodified",
        "mov_type": "programmatic",
        "mov_commands": [{"cmd": cmd_builder(path), "timeout": 10}],
        "met": False,
    }


def _make_content_criterion(cmd="rg -qF 'expected text' file"):
    return {
        "text": "Content check",
        "mov_type": "programmatic",
        "mov_commands": [{"cmd": cmd, "timeout": 10}],
        "met": False,
    }


def _make_card(action="Do the thing", criteria=None, edit_files=None):
    """Build a minimal card dict (as passed to validate_mov_scope_isolation / cmd_do)."""
    card = {
        "action": action,
        "intent": "Because reasons",
        "type": "work",
        "agent": "swe-devex",
        "criteria": criteria if criteria is not None else [_make_content_criterion()],
    }
    if edit_files is not None:
        card["editFiles"] = edit_files
    return card


def _make_do_args(board_root, json_data, session="test-session", force=False):
    return SimpleNamespace(
        root=str(board_root),
        json_data=json_data,
        json_file=None,
        session=session,
        force=force,
    )


def _minimal_board_card(edit_files=None, session="test-session"):
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


# ---------------------------------------------------------------------------
# Unit tests: _mov_extract_emptiness_assertion_paths
# ---------------------------------------------------------------------------

class TestExtractEmptinessAssertionPaths:
    def test_dash_z_shape_extracts_concrete_file(self, kanban):
        """test -z "$(git diff --name-only HEAD -- <file>)" extracts the file path."""
        cmd = _dash_z_cmd("modules/kanban/kanban.py")
        assert kanban._mov_extract_emptiness_assertion_paths(cmd) == ["modules/kanban/kanban.py"]

    def test_dash_z_shape_extracts_directory(self, kanban):
        """A directory pathspec (trailing slash) is extracted just like a file."""
        cmd = _dash_z_cmd("modules/")
        assert kanban._mov_extract_emptiness_assertion_paths(cmd) == ["modules/"]

    def test_double_bracket_dash_z_shape_extracts_path(self, kanban):
        """[[ -z "$(...)" ]] is recognized, not just test -z / [ -z ]."""
        cmd = '[[ -z "$(git diff --name-only HEAD -- modules/foo.py)" ]]'
        assert kanban._mov_extract_emptiness_assertion_paths(cmd) == ["modules/foo.py"]

    def test_wc_zero_shape_extracts_path(self, kanban):
        """"$(git diff ... -- <path> | wc -l)" -eq 0 extracts the path before the pipe."""
        cmd = _wc_zero_cmd("modules/kanban/")
        assert kanban._mov_extract_emptiness_assertion_paths(cmd) == ["modules/kanban/"]

    def test_content_based_rg_cmd_extracts_nothing(self, kanban):
        """A content-based MoV (rg -qF) has no modification-state assertion — untouched."""
        assert kanban._mov_extract_emptiness_assertion_paths("rg -qF 'expected text' file") == []

    def test_content_based_test_f_cmd_extracts_nothing(self, kanban):
        """test -f (existence check) is unrelated to git-diff emptiness — untouched."""
        assert kanban._mov_extract_emptiness_assertion_paths("test -f modules/foo.py") == []

    def test_bare_git_diff_without_comparison_extracts_nothing(self, kanban):
        """A bare `git diff` with no -z/wc-l==0 comparison is not an emptiness assertion."""
        assert kanban._mov_extract_emptiness_assertion_paths(
            "git diff --stat HEAD -- modules/foo.py"
        ) == []

    def test_rg_count_absence_idiom_extracts_nothing(self, kanban):
        """A non-git-diff count-absence idiom (rg -c) is a different idiom, not path-emptiness."""
        assert kanban._mov_extract_emptiness_assertion_paths(
            "test $(rg -c 'X' modules/foo.py) -le 0"
        ) == []


# ---------------------------------------------------------------------------
# Unit tests: _path_is_prefix_of
# ---------------------------------------------------------------------------

class TestPathIsPrefixOf:
    def test_directory_is_prefix_of_nested_file(self, kanban):
        assert kanban._path_is_prefix_of("modules/", "modules/claude/foo.py") is True

    def test_nested_file_is_not_prefix_of_directory(self, kanban):
        assert kanban._path_is_prefix_of("modules/claude/foo.py", "modules/") is False

    def test_no_false_match_on_partial_segment_name(self, kanban):
        """'modules' must not falsely prefix-match 'modules-extra/foo.py' (segment-based)."""
        assert kanban._path_is_prefix_of("modules/", "modules-extra/foo.py") is False
        assert kanban._path_is_prefix_of("modules-extra/", "modules/foo.py") is False

    def test_identical_paths_are_prefixes_of_each_other(self, kanban):
        assert kanban._path_is_prefix_of("modules/foo.py", "modules/foo.py") is True

    def test_unrelated_paths_not_prefixes(self, kanban):
        assert kanban._path_is_prefix_of("modules/foo.py", "src/bar.py") is False


# ---------------------------------------------------------------------------
# Unit tests: _mov_path_overlaps_editfile
# ---------------------------------------------------------------------------

class TestMovPathOverlapsEditfile:
    def test_directory_asserted_path_overlaps_nested_editfile(self, kanban):
        """The dominant real-world shape: 'modules/' asserted unmodified while a
        sibling/board card's editFiles entry is 'modules/claude/foo.py' nested under it.
        """
        assert kanban._mov_path_overlaps_editfile("modules/", "modules/claude/foo.py") is True

    def test_editfile_directory_contains_asserted_path(self, kanban):
        """Reverse direction: editFiles entry is a directory containing the asserted path."""
        assert kanban._mov_path_overlaps_editfile("modules/claude/foo.py", "modules/") is True

    def test_exact_match_overlaps(self, kanban):
        assert kanban._mov_path_overlaps_editfile("modules/foo.py", "modules/foo.py") is True

    def test_glob_editfile_overlaps_concrete_asserted_path(self, kanban):
        """Glob editFiles entries overlap via the reused _globs_overlap machinery."""
        assert kanban._mov_path_overlaps_editfile("src/foo.ts", "src/*.ts") is True

    def test_no_overlap_returns_false(self, kanban):
        assert kanban._mov_path_overlaps_editfile("modules/foo.py", "modules/bar.py") is False


# ---------------------------------------------------------------------------
# Unit tests: check_mov_scope_isolation
# ---------------------------------------------------------------------------

class TestCheckMovScopeIsolation:
    def test_board_conflict_different_session_detected(self, kanban):
        """A MoV asserting a path overlapping a card in `doing` in ANOTHER session
        is rejected, naming that card and the overlapping path.
        """
        cards = [_make_card(criteria=[_make_emptiness_criterion("modules/kanban/kanban.py")])]
        board_cards = [
            {"id": "100", "session": "other-session", "editFiles": ["modules/kanban/kanban.py"]},
        ]
        violations = kanban.check_mov_scope_isolation(cards, board_cards)
        assert len(violations) == 1
        card_idx, ac_idx, cmd_idx, conflict_label, asserted_path, overlapping_file = violations[0]
        assert card_idx == 0
        assert conflict_label == "card #100"
        assert asserted_path == "modules/kanban/kanban.py"
        assert overlapping_file == "modules/kanban/kanban.py"

    def test_same_batch_sibling_conflict_detected(self, kanban):
        """SAME-BATCH SIBLING case: a MoV asserting a path overlapping a sibling
        card in the same `--file` array is rejected — this sibling does not exist
        on the board yet, so this is the case a board-only check would miss.
        """
        cards = [
            _make_card(
                action="Card A asserts B's path untouched",
                criteria=[_make_emptiness_criterion("modules/claude/smithers.py")],
            ),
            _make_card(
                action="Card B edits the asserted path",
                edit_files=["modules/claude/smithers.py"],
            ),
        ]
        violations = kanban.check_mov_scope_isolation(cards, board_cards=[])
        assert len(violations) == 1
        card_idx, ac_idx, cmd_idx, conflict_label, asserted_path, overlapping_file = violations[0]
        assert card_idx == 0
        assert conflict_label == "batch sibling [1]"
        assert asserted_path == "modules/claude/smithers.py"

    def test_directory_contains_editfile_shape_detected(self, kanban):
        """A directory asserted-empty ('modules/') while a sibling edits a file
        nested under it ('modules/claude/smithers.py') is rejected.
        """
        cards = [
            _make_card(criteria=[_make_emptiness_criterion("modules/")]),
            _make_card(edit_files=["modules/claude/smithers.py"]),
        ]
        violations = kanban.check_mov_scope_isolation(cards, board_cards=[])
        assert len(violations) == 1
        assert violations[0][3] == "batch sibling [1]"

    def test_no_overlap_no_false_positive(self, kanban):
        """A MoV asserting a path with NO overlap anywhere is accepted (no violations)."""
        cards = [_make_card(criteria=[_make_emptiness_criterion("modules/unrelated.py")])]
        board_cards = [
            {"id": "100", "session": "other-session", "editFiles": ["modules/kanban/kanban.py"]},
        ]
        violations = kanban.check_mov_scope_isolation(cards, board_cards)
        assert violations == []

    def test_content_based_mov_untouched_even_with_overlap(self, kanban):
        """A content-based MoV (rg -qF) is NOT a modification-emptiness assertion,
        so it produces no violations even when a board/sibling card edits the
        exact same path referenced in the command text.
        """
        cards = [
            _make_card(criteria=[_make_content_criterion(
                cmd="rg -qF 'expected text' modules/kanban/kanban.py"
            )]),
        ]
        board_cards = [
            {"id": "100", "session": "other-session", "editFiles": ["modules/kanban/kanban.py"]},
        ]
        violations = kanban.check_mov_scope_isolation(cards, board_cards)
        assert violations == [], (
            "Content-based MoVs must never be treated as scope-isolation violations — "
            "they are the recommended safe pattern"
        )

    def test_no_emptiness_assertions_no_violations(self, kanban):
        """A card with no path-emptiness assertions at all produces no violations,
        regardless of board/sibling editFiles overlap.
        """
        cards = [_make_card(criteria=[{"text": "Semantic check", "mov_type": "semantic", "met": False}])]
        board_cards = [{"id": "100", "session": "s", "editFiles": ["modules/anything.py"]}]
        assert kanban.check_mov_scope_isolation(cards, board_cards) == []

    def test_multiple_board_conflicts_all_returned(self, kanban):
        """All conflicting board cards are returned, not just the first."""
        cards = [_make_card(criteria=[_make_emptiness_criterion("modules/foo.py")])]
        board_cards = [
            {"id": "100", "session": "sess-a", "editFiles": ["modules/foo.py"]},
            {"id": "101", "session": "sess-b", "editFiles": ["modules/foo.py"]},
        ]
        violations = kanban.check_mov_scope_isolation(cards, board_cards)
        assert len(violations) == 2


# ---------------------------------------------------------------------------
# Unit tests: _load_scope_isolation_board_cards
# ---------------------------------------------------------------------------

class TestLoadScopeIsolationBoardCards:
    def test_loads_both_todo_and_doing(self, kanban, tmp_path):
        """Unlike _load_all_doing_cards (doing-only), this loads BOTH todo and doing —
        a card queued in todo will eventually move to doing and modify its editFiles
        just as surely as one already doing.
        """
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "10", _minimal_board_card(["src/a.py"]))
        _write_card(board, "todo", "20", _minimal_board_card(["src/b.py"]))
        _write_card(board, "done", "30", _minimal_board_card(["src/c.py"]))
        _write_card(board, "canceled", "40", _minimal_board_card(["src/d.py"]))

        loaded = kanban._load_scope_isolation_board_cards(board)
        loaded_ids = {c["id"] for c in loaded}

        assert loaded_ids == {"10", "20"}, (
            f"Expected only todo+doing card IDs, got {loaded_ids}"
        )

    def test_empty_board_returns_empty_list(self, kanban, tmp_path):
        board = _setup_board(tmp_path)
        assert kanban._load_scope_isolation_board_cards(board) == []


# ---------------------------------------------------------------------------
# Unit tests: validate_mov_scope_isolation
# ---------------------------------------------------------------------------

class TestValidateMovScopeIsolation:
    def test_clean_card_passes(self, kanban, tmp_path):
        """Card with no scope-isolation violations passes without error."""
        board = _setup_board(tmp_path)
        card = _make_card(criteria=[_make_content_criterion()])
        try:
            kanban.validate_mov_scope_isolation(card, board)
        except SystemExit as e:
            pytest.fail(f"Clean card raised SystemExit({e.code})")

    def test_board_conflict_rejected_with_actionable_message(self, kanban, tmp_path, capsys):
        """A board conflict (different session) is rejected with card number and path."""
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "42", _minimal_board_card(
            ["modules/kanban/kanban.py"], session="other-session"
        ))
        card = _make_card(criteria=[_make_emptiness_criterion("modules/kanban/kanban.py")])

        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_scope_isolation(card, board)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "#42" in captured.err
        assert "modules/kanban/kanban.py" in captured.err

    def test_same_batch_sibling_conflict_rejected(self, kanban, tmp_path, capsys):
        """SAME-BATCH SIBLING conflict (array input) is rejected — no board cards involved."""
        board = _setup_board(tmp_path)
        cards = [
            _make_card(
                action="Card asserting sibling's path untouched",
                criteria=[_make_emptiness_criterion("modules/claude/smithers.py")],
            ),
            _make_card(
                action="Sibling editing the asserted path",
                edit_files=["modules/claude/smithers.py"],
            ),
        ]
        with pytest.raises(SystemExit) as exc_info:
            kanban.validate_mov_scope_isolation(cards, board)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "sibling" in captured.err.lower()
        assert "modules/claude/smithers.py" in captured.err


# ---------------------------------------------------------------------------
# Integration tests: cmd_do
# ---------------------------------------------------------------------------

class TestCmdDoScopeIsolationIntegration:
    def test_cmd_do_board_conflict_exits_1(self, kanban, tmp_path):
        """cmd_do rejects a single card whose MoV asserts a path overlapping a
        `doing` card in ANOTHER session, before any card is created.
        """
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_board_card(
            ["modules/kanban/kanban.py"], session="other-session"
        ))
        card = _make_card(criteria=[_make_emptiness_criterion("modules/kanban/kanban.py")])
        args = _make_do_args(board, json.dumps(card), session="test-session")

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        # No card created anywhere — rejected before card creation.
        assert list((board / "doing").glob("*.json")) == [board / "doing" / "99.json"]
        assert list((board / "todo").glob("*.json")) == []

    def test_cmd_do_bulk_same_batch_sibling_conflict_exits_1(self, kanban, tmp_path):
        """cmd_do rejects a bulk array where one card's MoV asserts a path that
        overlaps a SIBLING's editFiles in the same array — neither card exists
        on the board yet, so this can only be caught by inspecting the batch itself.
        """
        board = _setup_board(tmp_path)
        cards = [
            _make_card(
                action="Card asserting sibling's path untouched",
                criteria=[_make_emptiness_criterion("modules/claude/smithers.py")],
            ),
            _make_card(
                action="Sibling editing the asserted path",
                edit_files=["modules/claude/smithers.py"],
            ),
        ]
        args = _make_do_args(board, json.dumps(cards))

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        assert list((board / "doing").glob("*.json")) == []
        assert list((board / "todo").glob("*.json")) == []

    def test_cmd_do_content_based_mov_succeeds(self, kanban, tmp_path):
        """A content-based MoV (rg -qF) is unaffected by scope-isolation checks
        and the card is created normally.
        """
        board = _setup_board(tmp_path)
        card = _make_card(criteria=[_make_content_criterion()])
        args = _make_do_args(board, json.dumps(card))

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        assert len(list((board / "doing").glob("*.json"))) == 1

    def test_cmd_do_non_overlapping_emptiness_assertion_succeeds(self, kanban, tmp_path):
        """A path-emptiness MoV that does NOT overlap any board/sibling editFiles
        is accepted — no false positive.
        """
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_board_card(["modules/other.py"]))
        card = _make_card(criteria=[_make_emptiness_criterion("modules/unrelated.py")])
        args = _make_do_args(board, json.dumps(card))

        with patch.object(kanban, "write_kanban_event"):
            kanban.cmd_do(args)

        new_cards = [c for c in (board / "doing").glob("*.json") if c.name != "99.json"]
        assert len(new_cards) == 1

    def test_glob_editfile_board_conflict_detected_via_cmd_do(self, kanban, tmp_path):
        """A GLOB-shaped editFiles entry on a board card (e.g. 'modules/claude/*.py')
        must be recognized through the real cmd_do integration path — not merely by
        the direct _globs_overlap/_mov_path_overlaps_editfile helper calls already
        covered elsewhere in this file. This proves the glob actually reaches the
        wired-up check_mov_scope_isolation call inside cmd_do.
        """
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "99", _minimal_board_card(
            ["modules/claude/*.py"], session="other-session"
        ))
        card = _make_card(criteria=[_make_emptiness_criterion("modules/claude/smithers.py")])
        args = _make_do_args(board, json.dumps(card), session="test-session")

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        # No card created anywhere — rejected before card creation.
        assert list((board / "doing").glob("*.json")) == [board / "doing" / "99.json"]
        assert list((board / "todo").glob("*.json")) == []

    def test_glob_editfile_sibling_conflict_detected_via_cmd_do(self, kanban, tmp_path):
        """A GLOB-shaped editFiles entry on a SAME-BATCH SIBLING (no board cards
        present at all) must be recognized through the real cmd_do integration
        path. With the board empty, this can only pass via the sibling code path
        inside check_mov_scope_isolation — mirroring the decisiveness property of
        test_cmd_do_bulk_same_batch_sibling_conflict_exits_1, but for a glob
        pattern instead of a concrete sibling editFiles path.
        """
        board = _setup_board(tmp_path)
        cards = [
            _make_card(
                action="Card asserting sibling's glob-matched path untouched",
                criteria=[_make_emptiness_criterion("modules/claude/smithers.py")],
            ),
            _make_card(
                action="Sibling editing files matched by a glob pattern",
                edit_files=["modules/claude/*.py"],
            ),
        ]
        args = _make_do_args(board, json.dumps(cards))

        with patch.object(kanban, "write_kanban_event"):
            with pytest.raises(SystemExit) as exc_info:
                kanban.cmd_do(args)

        assert exc_info.value.code == 1
        assert list((board / "doing").glob("*.json")) == []
        assert list((board / "todo").glob("*.json")) == []
