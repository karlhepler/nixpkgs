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

Card #3350 extends this same file with a SECOND, weaker anomaly class:
abandoned-card detection. An "abandoned" card sits in `doing` with NO
acceptance criterion met and no recorded activity for a long time. Unlike
stranding, this is genuinely ambiguous — it could be a dead card nobody is
working, or a live agent deep in a long investigation that has not yet
reached its first criterion check — so detection uses a much looser,
separately-named threshold (ABANDONED_CARD_THRESHOLD_MINUTES) and is
rendered in its own `<possibly-abandoned>` / "POSSIBLY ABANDONED CARDS" section,
never folded into `<stranded>`. Required coverage (per card #3350):
  - TestAbandonedDetectionFires::test_abandoned_card_with_stale_activity_and_no_ac_met_is_detected
    constructs a doing card with no criteria met and activity older than
    the threshold and asserts detection FIRES.
  - TestAbandonedDetectionStaysQuiet::test_recently_active_card_with_no_ac_met_is_not_flagged_abandoned
    constructs the same shape with RECENT activity and asserts detection
    does NOT fire.
  - TestAbandonedDoesNotOverlapWithStranded::test_stranded_card_never_also_reported_as_abandoned
    pins the design decision that a card already flagged stranded is never
    ALSO reported as abandoned: the two predicates are mutually exclusive
    by construction for any card with at least one criterion (every
    criterion met vs. no criterion met cannot both hold), so a stranded
    card can never satisfy is_card_abandoned's "no criterion met"
    requirement — no overlap-suppression logic is needed for correctness,
    only defensively present (see kanban.py's abandoned_cards computation
    in cmd_list) as a guard against that invariant weakening later.
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


# ---------------------------------------------------------------------------
# Unit tests: is_card_abandoned (pure function, no board I/O)
#
# Mirrors TestIsCardStrandedUnit above, but every "met" polarity is flipped:
# is_card_abandoned requires NO criterion met (vs. is_card_stranded's ALL
# criteria met), and uses the far looser ABANDONED_CARD_THRESHOLD_MINUTES.
# ---------------------------------------------------------------------------

class TestIsCardAbandonedUnit:
    """Direct unit tests of the is_card_abandoned predicate."""

    def test_no_criteria_met_and_stale_is_abandoned(self, kanban):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 5)
        card = _make_card(
            criteria=[{"text": "AC1", "met": False}, {"text": "AC2", "met": False}],
            updated=_iso(stale_updated),
        )
        assert kanban.is_card_abandoned(card, now=now) is True

    def test_no_criteria_met_but_recent_is_not_abandoned(self, kanban):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        recent_updated = now - timedelta(minutes=1)
        card = _make_card(
            criteria=[{"text": "AC1", "met": False}],
            updated=_iso(recent_updated),
        )
        assert kanban.is_card_abandoned(card, now=now) is False

    def test_some_criteria_met_is_never_abandoned_even_if_stale(self, kanban):
        """A card with a MIX of met/unmet criteria is neither fully worked
        nor fully untouched — it falls in the deliberate gap between the
        stranded and abandoned classes, so it must never be flagged
        abandoned regardless of staleness.
        """
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 60)
        card = _make_card(
            criteria=[{"text": "AC1", "met": True}, {"text": "AC2", "met": False}],
            updated=_iso(stale_updated),
        )
        assert kanban.is_card_abandoned(card, now=now) is False

    def test_all_criteria_met_is_never_abandoned_even_if_stale(self, kanban):
        """The mirror-image sanity check: a fully-met (stranded) card must
        never also satisfy is_card_abandoned's "no criterion met"
        requirement — the two predicates are mutually exclusive.
        """
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 60)
        card = _make_card(
            criteria=[{"text": "AC1", "met": True}, {"text": "AC2", "met": True}],
            updated=_iso(stale_updated),
        )
        assert kanban.is_card_abandoned(card, now=now) is False

    def test_no_criteria_is_never_abandoned(self, kanban):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 60)
        card = _make_card(criteria=[], updated=_iso(stale_updated))
        assert kanban.is_card_abandoned(card, now=now) is False

    def test_missing_updated_field_fails_closed(self, kanban):
        """No `updated` timestamp — cannot determine staleness, so not
        abandoned."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        card = _make_card(criteria=[{"text": "AC1", "met": False}])
        del card["updated"]
        assert kanban.is_card_abandoned(card, now=now) is False

    def test_malformed_updated_field_fails_closed(self, kanban):
        """Unparseable `updated` timestamp must not raise — fails closed to
        False."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        card = _make_card(
            criteria=[{"text": "AC1", "met": False}],
            updated="not-a-real-timestamp",
        )
        assert kanban.is_card_abandoned(card, now=now) is False

    def test_non_dict_criterion_entry_fails_closed(self, kanban):
        """A malformed (non-dict) criterion entry must not raise or
        false-positive."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_updated = now - timedelta(minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 60)
        card = _make_card(criteria=["not-a-dict"], updated=_iso(stale_updated))
        assert kanban.is_card_abandoned(card, now=now) is False

    def test_exactly_at_threshold_boundary_is_abandoned(self, kanban):
        """Age exactly equal to the threshold counts as abandoned (>=, not
        >) — same boundary convention as is_card_stranded."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        boundary_updated = now - timedelta(minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES)
        card = _make_card(
            criteria=[{"text": "AC1", "met": False}],
            updated=_iso(boundary_updated),
        )
        assert kanban.is_card_abandoned(card, now=now) is True

    def test_abandoned_threshold_is_much_looser_than_stranded_threshold(self, kanban):
        """Pins the card's core requirement: abandoned detection MUST use a
        deliberately looser threshold than stranded detection, because
        no-criteria-met + stale is weaker, more ambiguous evidence than
        all-criteria-met + stale. A warning that fires on healthy
        long-running work at the same cadence as the near-certain stranded
        signal would be noise.
        """
        assert kanban.ABANDONED_CARD_THRESHOLD_MINUTES > kanban.STRANDED_CARD_THRESHOLD_MINUTES


# ---------------------------------------------------------------------------
# Integration tests: abandoned-card detection fires in BOTH directions via
# cmd_list, and never overlaps with the stranded class.
# ---------------------------------------------------------------------------

class TestAbandonedDetectionFires:
    """Positive case: a deliberately abandoned fixture must be detected."""

    def test_abandoned_card_with_stale_activity_and_no_ac_met_is_detected(self, kanban, tmp_path):
        """A doing card with NO AC met and activity older than the
        (looser) abandoned threshold must appear in the <possibly-abandoned> section
        of `kanban list` XML output.
        """
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 30
        )
        _write_card(board, "doing", "60", _make_card(
            session="sweet-otter",
            criteria=[
                {"text": "AC1", "met": False},
                {"text": "AC2", "met": False},
            ],
            updated=_iso(stale_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        assert "<possibly-abandoned" in output, (
            f"Expected a <possibly-abandoned> section for card #60, got:\n{output}"
        )
        _abandoned_start = output.index("<possibly-abandoned")
        _abandoned_end = output.index("</possibly-abandoned>")
        assert 'n="60"' in output[_abandoned_start:_abandoned_end], (
            "Card #60 must be listed inside the <possibly-abandoned> section"
        )

    def test_non_xml_output_style_includes_abandoned_warning(self, kanban, tmp_path):
        """--output-style=simple must also surface the heuristic warning
        (plain text), phrased to hedge rather than assert certainty."""
        board = _setup_board(tmp_path)
        stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 30
        )
        _write_card(board, "doing", "61", _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": False}],
            updated=_iso(stale_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        args.output_style = "simple"
        output = _run_cmd_list(kanban, args, board)

        assert "ABANDONED CARDS" in output.upper()
        assert "#61" in output


class TestAbandonedDetectionStaysQuiet:
    """Negative case: recent activity must suppress the abandoned warning
    entirely — same rationale as the stranded class's quiet-case coverage.
    """

    def test_recently_active_card_with_no_ac_met_is_not_flagged_abandoned(self, kanban, tmp_path):
        """A doing card with no AC met but RECENT activity must NOT appear
        in the <possibly-abandoned> section — it may simply be a healthy agent still
        working toward its first criterion check.
        """
        board = _setup_board(tmp_path)
        recent_updated = datetime.now(timezone.utc) - timedelta(seconds=5)
        _write_card(board, "doing", "62", _make_card(
            session="sweet-otter",
            criteria=[
                {"text": "AC1", "met": False},
                {"text": "AC2", "met": False},
            ],
            updated=_iso(recent_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        assert "<possibly-abandoned" not in output, (
            f"A recently-active card with no AC met must not be flagged "
            f"abandoned, got:\n{output}"
        )

    def test_no_abandoned_cards_omits_section_entirely(self, kanban, tmp_path):
        """A clean board produces no <possibly-abandoned> section at all (XML) and
        no warning text (non-XML) — the feature is silent by default.

        Uses an explicit RECENT `updated` timestamp rather than
        `_make_card`'s fixed-past-date default — unlike the analogous
        stranded-class test, a card with an unmet criterion and the
        default 2026-01-01 timestamp WOULD satisfy is_card_abandoned's
        "no criterion met + stale" test against a real wall clock, since
        abandoned detection (unlike stranded detection) does not require
        every criterion met.
        """
        board = _setup_board(tmp_path)
        recent_updated = datetime.now(timezone.utc) - timedelta(seconds=5)
        _write_card(board, "doing", "63", _make_card(
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": False}],
            updated=_iso(recent_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        xml_output = _run_cmd_list(kanban, args, board)
        assert "<possibly-abandoned" not in xml_output

        args.output_style = "simple"
        simple_output = _run_cmd_list(kanban, args, board)
        assert "ABANDONED CARDS" not in simple_output.upper()


class TestAbandonedDoesNotOverlapWithStranded:
    """Design decision (card #3350): a card already flagged stranded must
    never ALSO be reported as abandoned. The two predicates are mutually
    exclusive by construction for any card with at least one criterion —
    is_card_stranded requires every criterion met, is_card_abandoned
    requires none met.

    test_stranded_card_never_also_reported_as_abandoned below is an
    end-to-end regression check with built-in redundancy, NOT a unit-level
    guard of the cmd_list exclusion filter's necessity in isolation. For its
    fixture, the filter's `continue` fires before is_card_abandoned is ever
    reached, and — independently — is_card_abandoned's own met-check would
    also return False for the same fixture. So the test is decisive against
    a JOINT failure of both mechanisms (and against a regression in
    is_card_stranded's own membership check), but it cannot isolate a solo
    failure of the filter from a solo failure of the predicate's met-check,
    because each one masks the other: removing just the filter leaves the
    predicate's met-check able to produce the identical correct result, and
    a regression that broke only the met-check would be silently masked by
    the filter's `continue`. This is not a tautology, though — a joint failure
    of both mechanisms together would still be caught.

    The met-check itself IS fully decisive on its own, independent of this
    joint-failure gap: see test_all_criteria_met_is_never_abandoned_even_if_stale
    above, which calls is_card_abandoned directly, bypassing cmd_list and
    the exclusion filter entirely.
    """

    def test_stranded_card_never_also_reported_as_abandoned(self, kanban, tmp_path):
        board = _setup_board(tmp_path)
        # Stale beyond BOTH thresholds, so if the mutual-exclusion invariant
        # were ever weakened, this test would still catch a double-report.
        very_stale_updated = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 30
        )
        _write_card(board, "doing", "64", _make_card(
            session="sweet-otter",
            criteria=[
                {"text": "AC1", "met": True},
                {"text": "AC2", "met": True},
            ],
            updated=_iso(very_stale_updated),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        assert "<stranded>" in output, (
            f"Card #64 is genuinely stranded and must be flagged, got:\n{output}"
        )
        assert 'n="64"' in output.split("<stranded>")[1].split("</stranded>")[0]
        assert "<possibly-abandoned" not in output, (
            f"A stranded card must never also be reported as abandoned, "
            f"got:\n{output}"
        )

    def test_mixed_board_flags_each_card_in_exactly_one_class(self, kanban, tmp_path):
        """A board with one stranded card, one abandoned card, and one
        healthy (recently-active) card partitions cleanly: each of the
        first two appears in exactly one section, and the healthy card
        appears in neither.
        """
        board = _setup_board(tmp_path)
        stale = datetime.now(timezone.utc) - timedelta(
            minutes=kanban.ABANDONED_CARD_THRESHOLD_MINUTES + 30
        )
        recent = datetime.now(timezone.utc) - timedelta(seconds=10)

        _write_card(board, "doing", "70", _make_card(  # stranded
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": True}],
            updated=_iso(stale),
        ))
        _write_card(board, "doing", "71", _make_card(  # abandoned
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": False}],
            updated=_iso(stale),
        ))
        _write_card(board, "doing", "72", _make_card(  # healthy
            session="sweet-otter",
            criteria=[{"text": "AC1", "met": False}],
            updated=_iso(recent),
        ))
        args = _make_args(board, session="sweet-otter")
        output = _run_cmd_list(kanban, args, board)

        stranded_section = output.split("<stranded>")[1].split("</stranded>")[0]
        _abandoned_start = output.index("<possibly-abandoned")
        _abandoned_end = output.index("</possibly-abandoned>")
        abandoned_section = output[_abandoned_start:_abandoned_end]

        assert 'n="70"' in stranded_section
        assert 'n="70"' not in abandoned_section

        assert 'n="71"' in abandoned_section
        assert 'n="71"' not in stranded_section

        assert 'n="72"' not in stranded_section
        assert 'n="72"' not in abandoned_section
