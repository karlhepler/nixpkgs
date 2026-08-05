"""
Tests for stranded-card detection (kanban list § Stranded-card warning).

A "stranded" card sits in `doing` with every acceptance criterion already
marked met, but was never advanced to `done` — the symptom of
kanban-subagent-stop-hook.py silently returning early on a non-existent
agent_transcript_path (see anthropics/claude-code#7881). Detection is
SURFACE ONLY: it must never mutate a card or call `kanban done` — a card can
legitimately sit with every AC met for a few seconds between the agent's
last `criteria check` and the SubagentStop hook actually firing, so an
un-gated check would fire constantly on healthy in-flight work.

This file owns exactly this concern — kept separate from
test_kanban_mov_validation.py, which owns MoV banned-pattern validation, a
different concern entirely.

Core deliverable (per card #3348): prove the detector can fire in BOTH
directions —
  - TestStrandedDetectionFires::test_stranded_card_with_stale_activity_is_detected
    constructs a deliberately stranded fixture (doing, every AC met,
    activity older than the threshold) and asserts detection FIRES.
  - TestStrandedDetectionStaysQuiet::test_recently_active_card_with_all_ac_met_is_not_flagged
    constructs a card with every AC met but RECENT activity and asserts
    detection does NOT fire — this is what prevents the warning from
    spamming every healthy parallel card completing its last criterion.

Fixtures are built under tmp_path — never against the real .kanban/
directory, which holds live cards from concurrently-running sessions.
"""

import importlib.util
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module loader (mirrors test_kanban_list_xml_schema.py)
# ---------------------------------------------------------------------------

_KANBAN_PATH = Path(__file__).parent.parent / "kanban.py"


def load_kanban():
    """Import kanban.py as a module with watchdog stubbed out."""
    watchdog_stub = MagicMock()
    sys.modules.setdefault("watchdog", watchdog_stub)
    sys.modules.setdefault("watchdog.observers", watchdog_stub)
    sys.modules.setdefault("watchdog.events", watchdog_stub)
    watchdog_stub.events.FileSystemEventHandler = object

    spec = importlib.util.spec_from_file_location("kanban_stranded_cards", _KANBAN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kanban():
    return load_kanban()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    criteria=None,
    updated="2026-01-01T00:00:00Z",
):
    """Build a minimal card dict."""
    return {
        "action": action,
        "intent": intent,
        "session": session,
        "type": "work",
        "agent": "swe-devex",
        "model": "sonnet",
        "editFiles": edit_files or [],
        "readFiles": [],
        "criteria": criteria if criteria is not None else [],
        "activity": [],
        "created": "2026-01-01T00:00:00Z",
        "updated": updated,
    }


def _make_args(root, session=None):
    """Build a minimal args namespace for cmd_list."""
    return SimpleNamespace(
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
# Unit tests: is_card_stranded (pure function, no board I/O)
# ---------------------------------------------------------------------------

class TestIsCardStrandedUnit:
    """Direct unit tests of the is_card_stranded predicate."""

    def test_all_met_and_stale_is_stranded(self, kanban):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 5)
        card = _make_card(
            criteria=[{"text": "AC1", "met": True}, {"text": "AC2", "met": True}],
            updated=_iso(stale_updated),
        )
        assert kanban.is_card_stranded(card, now=now) is True

    def test_all_met_but_recent_is_not_stranded(self, kanban):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        recent_updated = now - timedelta(minutes=1)
        card = _make_card(
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(recent_updated),
        )
        assert kanban.is_card_stranded(card, now=now) is False

    def test_unmet_criterion_is_never_stranded_even_if_stale(self, kanban):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 60)
        card = _make_card(
            criteria=[{"text": "AC1", "met": True}, {"text": "AC2", "met": False}],
            updated=_iso(stale_updated),
        )
        assert kanban.is_card_stranded(card, now=now) is False

    def test_no_criteria_is_never_stranded(self, kanban):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 60)
        card = _make_card(criteria=[], updated=_iso(stale_updated))
        assert kanban.is_card_stranded(card, now=now) is False

    def test_missing_updated_field_fails_closed(self, kanban):
        """No `updated` timestamp — cannot determine staleness, so not stranded."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        card = _make_card(criteria=[{"text": "AC1", "met": True}])
        del card["updated"]
        assert kanban.is_card_stranded(card, now=now) is False

    def test_malformed_updated_field_fails_closed(self, kanban):
        """Unparseable `updated` timestamp must not raise — fails closed to False."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        card = _make_card(
            criteria=[{"text": "AC1", "met": True}],
            updated="not-a-real-timestamp",
        )
        assert kanban.is_card_stranded(card, now=now) is False

    def test_non_dict_criterion_entry_fails_closed(self, kanban):
        """A malformed (non-dict) criterion entry must not raise or false-positive."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 60)
        card = _make_card(criteria=["not-a-dict"], updated=_iso(stale_updated))
        assert kanban.is_card_stranded(card, now=now) is False

    def test_exactly_at_threshold_boundary_is_stranded(self, kanban):
        """Age exactly equal to the threshold counts as stranded (>=, not >)."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        boundary_updated = now - timedelta(minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES)
        card = _make_card(
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(boundary_updated),
        )
        assert kanban.is_card_stranded(card, now=now) is True


# ---------------------------------------------------------------------------
# Integration tests: detection fires in BOTH directions via cmd_list
# ---------------------------------------------------------------------------

class TestStrandedDetectionFires:
    """Positive case: a deliberately stranded fixture must be detected."""

    def test_stranded_card_with_stale_activity_is_detected(self, kanban, tmp_path):
        """A doing card with every AC met and activity older than the threshold
        must appear in the <stranded> section of `kanban list` XML output.
        """
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 30
        )
        _write_card(board, "doing", "42", _make_card(
            session="sweet-otter",
            criteria=[
                {"text": "AC1", "met": True},
                {"text": "AC2", "met": True},
            ],
            updated=_iso(stale_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        assert "<stranded>" in output, (
            f"Expected a <stranded> section for card #42, got:\n{output}"
        )
        assert 'n="42"' in output.split("<stranded>")[1].split("</stranded>")[0], (
            "Card #42 must be listed inside the <stranded> section"
        )


class TestStrandedDetectionStaysQuiet:
    """Negative case: recent activity must suppress the warning entirely.

    This matters at least as much as the positive case — an un-gated
    detector would fire on every healthy card that just finished checking
    its last criterion, training coordinators to ignore the warning.
    """

    def test_recently_active_card_with_all_ac_met_is_not_flagged(self, kanban, tmp_path):
        """A doing card with every AC met but RECENT activity must NOT appear
        in the <stranded> section — it may simply be seconds away from a
        legitimate SubagentStop transition.
        """
        board = _setup_board(tmp_path)
        recent_updated = datetime.now(timezone.utc) - timedelta(seconds=5)
        _write_card(board, "doing", "43", _make_card(
            session="sweet-otter",
            criteria=[
                {"text": "AC1", "met": True},
                {"text": "AC2", "met": True},
            ],
            updated=_iso(recent_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        assert "<stranded>" not in output, (
            f"A recently-active fully-met card must not be flagged stranded, got:\n{output}"
        )


class TestStrandedDetectionNeverLeaksIntoColumnFilteredConsumers:
    """Pins card #3362's reviewed invariant: stranded output can never reach
    a consumer that filters `kanban list` to `--column todo`.

    This mirrors the real invocation in
    modules/claude/kanban-subagent-stop-hook.py:get_deferred_cards --
        run_kanban(["list", "--column", "todo", "--output-style=xml",
                    "--session", session])
    i.e. a call shaped like `kanban list --column todo --output-style=xml
    --session <session>`. Stranded detection only ever considers cards
    already gathered into `all_cards_by_column["doing"]`
    (modules/kanban/kanban.py:3765) -- when the caller's column filter
    excludes "doing", that key is never populated, so `stranded_cards` stays
    empty regardless of how stale or fully-met the card is. This test
    fixes a genuinely stranded card in `doing` and asserts a `--column
    todo` filtered listing never surfaces it, so a future change that
    widens the filter or moves detection off the `doing` gate fails this
    test instead of silently leaking a stranded warning into a consumer
    that never expects one.
    """

    def test_stranded_card_absent_from_column_todo_filtered_list(self, kanban, tmp_path):
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 30
        )
        _write_card(board, "doing", "42", _make_card(
            session="sweet-otter",
            criteria=[
                {"text": "AC1", "met": True},
                {"text": "AC2", "met": True},
            ],
            updated=_iso(stale_updated),
        ))

        # Same invocation shape as get_deferred_cards: --column todo,
        # --output-style=xml, --session <session>.
        args = _make_args(board, session="sweet-otter")
        args.column = ["todo"]
        output = _run_cmd_list(kanban, args, board)

        assert "<stranded>" not in output, (
            "A --column todo filtered `kanban list` must never surface a "
            f"<stranded> section, even with a genuinely stranded doing "
            f"card on the board, got:\n{output}"
        )
        assert 'n="42"' not in output, (
            "The stranded card must not appear at all in a --column todo "
            f"filtered listing, got:\n{output}"
        )


class TestStrandedDetectionAdditionalIntegrationCases:
    """Further integration coverage: mixed boards, non-XML output, isolation
    from unrelated columns/cards.
    """

    def test_todo_column_card_is_never_flagged_regardless_of_criteria(self, kanban, tmp_path):
        """Only `doing` cards are eligible — a stale, all-met card sitting in
        `todo` (not yet started) must never be flagged.
        """
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 30
        )
        _write_card(board, "todo", "7", _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(stale_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        assert "<stranded>" not in output

    def test_mixed_board_only_flags_the_stranded_card(self, kanban, tmp_path):
        """A board with one healthy doing card and one stranded doing card
        flags only the stranded one.
        """
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 30
        )
        recent_updated = datetime.now(timezone.utc) - timedelta(seconds=10)

        _write_card(board, "doing", "10", _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(stale_updated),
        ))
        _write_card(board, "doing", "11", _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": False}],
            updated=_iso(recent_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        stranded_section = output.split("<stranded>")[1].split("</stranded>")[0]
        assert 'n="10"' in stranded_section
        assert 'n="11"' not in stranded_section

    def test_stranded_warning_uses_card_tag_not_c_tag(self, kanban, tmp_path):
        """The stranded section must use a distinct <card> tag rather than
        <c>, so ElementTree consumers that scan for `<c>` elements
        (kanban-pretool-hook.py, find-orphaned-cards.py in default.nix) never
        mistake a stranded-card entry for a normal board card.
        """
        import xml.etree.ElementTree as ET

        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 30
        )
        _write_card(board, "doing", "99", _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(stale_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        root = ET.fromstring(output)
        # Exactly one <c> element (the normal board card) — the stranded
        # entry must not add a second one.
        c_elements = list(root.iter("c"))
        assert len(c_elements) == 1, (
            f"Expected exactly one <c> element (stranded entries use <card>), "
            f"got {len(c_elements)}"
        )
        stranded_els = list(root.iter("stranded"))
        assert len(stranded_els) == 1
        card_els = list(stranded_els[0].iter("card"))
        assert len(card_els) == 1
        assert card_els[0].get("n") == "99"

    def test_non_xml_output_style_includes_stranded_warning(self, kanban, tmp_path):
        """--output-style=simple must also surface the warning (plain text)."""
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 30
        )
        _write_card(board, "doing", "55", _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(stale_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        args.output_style = "simple"
        output = _run_cmd_list(kanban, args, board)

        # NOTE: assert on the specific warning heading, not a bare "STRANDED"
        # substring — this test's own tmp_path directory name also contains
        # "stranded" (from the test function name) and would make a bare
        # substring check pass even if the feature were broken.
        assert "STRANDED CARDS" in output.upper()
        assert "#55" in output

    def test_no_stranded_cards_omits_section_entirely(self, kanban, tmp_path):
        """A clean board produces no <stranded> section at all (XML) and no
        warning text (non-XML) — the feature is silent by default.
        """
        board = _setup_board(tmp_path)
        _write_card(board, "doing", "1", _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": False}],
        ))
        args = _make_args(board, session="sweet-otter")
        xml_output = _run_cmd_list(kanban, args, board)
        assert "<stranded>" not in xml_output

        args.output_style = "simple"
        simple_output = _run_cmd_list(kanban, args, board)
        # NOTE: can't assert "STRANDED" not in output.upper() — the tmp_path
        # fixture directory embeds this test's own name (which contains the
        # word "stranded"), and `KANBAN BOARD: {root}` prints that path
        # verbatim. Assert on the specific warning heading text instead.
        assert "STRANDED CARDS" not in simple_output.upper()

    def test_malformed_card_does_not_break_list_command(self, kanban, tmp_path):
        """A corrupt card (unparseable `updated`) must not raise — `kanban
        list` must still print the rest of the board normally (Fail open).
        """
        board = _setup_board(tmp_path)
        corrupt_card = _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": True}],
        )
        corrupt_card["updated"] = "definitely-not-a-timestamp"
        _write_card(board, "doing", "1", corrupt_card)
        _write_card(board, "doing", "2", _make_card(
            session="sweet-otter",
            intent="A perfectly healthy card",
        ))
        args = _make_args(board, session="sweet-otter")

        # Must not raise.
        output = _run_cmd_list(kanban, args, board)
        assert "<stranded>" not in output
        assert 'n="2"' in output


class TestStrandedDetectionNonStringSessionFailsOpen:
    """Pins the Tier 2 review finding (card #3364): a card that IS correctly
    flagged stranded but carries a non-string `session` value (e.g. an int
    or a list) must not crash `kanban list`, in either output style, and the
    rest of the listing must still print.

    Before the fix, `_ses_attr()` called `html.escape(card_session)`
    unconditionally on any truthy `session` value. `html.escape` requires a
    `str` and raises `AttributeError` on anything else — a real risk because
    `is_card_stranded()` validates `criteria`/`updated` but never touches
    `session` at all, so a card can sail through detection with an
    untouched, arbitrary `session` value straight from a hand-edited or
    historically-drifted card file, then crash purely in rendering.
    `_ses_attr()` now rejects a non-string `session` the same way it already
    rejected a falsy one, and the stranded-card emission blocks are
    additionally guarded end-to-end so the class of bug — not just this one
    input — cannot break the command.

    No `--session` filter is passed here deliberately: bucketing a card
    with a non-matching, non-string session into the "other sessions"
    section would additionally exercise `format_card_line`'s own, separate,
    out-of-scope session-slicing code (`session[:8]`) — not part of this
    card's fix. Omitting `--session` keeps the exercised surface limited to
    the stranded-card code path this card is about.
    """

    def test_non_string_int_session_on_stranded_card_does_not_crash_xml_output(self, kanban, tmp_path):
        """A stranded card with an int `session` must not crash the default
        XML output, and a healthy sibling card must still appear.
        """
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 30
        )
        malformed_card = _make_card(
            session=12345,  # non-string — plausible hand-edited drift
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(stale_updated),
        )
        _write_card(board, "doing", "1", malformed_card)
        _write_card(board, "doing", "2", _make_card(
            session="sweet-otter",
            intent="A perfectly healthy card",
        ))
        args = _make_args(board, session=None)

        # Must not raise.
        output = _run_cmd_list(kanban, args, board)

        assert "<stranded>" in output, (
            f"Card #1 is genuinely stranded and must still be flagged "
            f"despite its non-string session, got:\n{output}"
        )
        assert 'n="1"' in output.split("<stranded>")[1].split("</stranded>")[0], (
            f"Card #1 must appear in the <stranded> section, got:\n{output}"
        )
        # "Did not crash" alone is satisfied by a command that prints
        # nothing at all — assert the rest of the listing is still present.
        assert 'n="2"' in output, (
            f"Healthy card #2 must still render even though card #1 has a "
            f"non-string session, got:\n{output}"
        )

    def test_non_string_list_session_on_stranded_card_does_not_crash_simple_output(self, kanban, tmp_path):
        """Same scenario with a list `session`, on `--output-style=simple`.

        This path is not vulnerable to today's known crash (an f-string
        never calls `html.escape`), but it is guarded and tested anyway so a
        future edit that adds escaping there fails this test instead of
        shipping a silent regression with zero coverage.
        """
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.STRANDED_CARD_THRESHOLD_MINUTES + 30
        )
        malformed_card = _make_card(
            session=["not", "a", "string"],  # non-string
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(stale_updated),
        )
        _write_card(board, "doing", "1", malformed_card)
        _write_card(board, "doing", "2", _make_card(
            session="sweet-otter",
            intent="A perfectly healthy card",
        ))
        args = _make_args(board, session=None)
        args.output_style = "simple"

        # Must not raise.
        output = _run_cmd_list(kanban, args, board)

        assert "STRANDED CARDS" in output.upper(), (
            f"Card #1 is genuinely stranded and must still be flagged "
            f"despite its non-string session, got:\n{output}"
        )
        assert "#1" in output
        # "Did not crash" alone is satisfied by a command that prints
        # nothing at all — assert the rest of the listing is still present.
        assert "#2" in output, (
            f"Healthy card #2 must still render even though card #1 has a "
            f"non-string session, got:\n{output}"
        )
