"""
Tests for modules/claude/kanban-pretool-hook.py.

Covered paths:
- Agent call missing run_in_background → self-healed to run_in_background=True (allowed)
- Agent call missing description → denied
- Agent call missing subagent_type → denied
- Agent call with invalid subagent_type (general-purpose) → denied
- Agent call with card number → card XML injected into prompt
- Agent call without card number → denied unless SKILL_AGENT_BYPASS marker
- Agent call with FOREGROUND_AUTHORIZED marker → allows run_in_background: false
- Agent call with SKILL_AGENT_BYPASS marker → bypasses all enforcement

All kanban CLI and subprocess calls are monkeypatched — no real kanban cards
are created or read during these tests.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from .conftest import KanbanMockResponses, make_pretool_payload

# ---------------------------------------------------------------------------
# Hook module loader
# ---------------------------------------------------------------------------

_HOOK_PATH = Path(__file__).parent.parent / "kanban-pretool-hook.py"


def load_hook():
    """Import kanban-pretool-hook.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("kanban_pretool_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    """Load the pretool hook module once per test module."""
    return load_hook()


# ---------------------------------------------------------------------------
# Helper: run main() with a JSON payload via monkeypatched stdin / stdout
# ---------------------------------------------------------------------------

def run_hook_main(hook_mod, payload: dict, env: dict | None = None) -> dict:
    """
    Call hook_mod.main() with the given payload dict as stdin JSON.
    Returns the parsed JSON written to stdout.
    """
    import io

    raw = json.dumps(payload)

    captured_output: list[str] = []

    def fake_print(val, **kwargs):
        captured_output.append(val)

    env_patch = env or {}

    with patch.object(sys, "stdin", io.StringIO(raw)):
        with patch("builtins.print", side_effect=fake_print):
            with patch.dict(os.environ, env_patch, clear=False):
                # Suppress log writes
                with patch.object(hook_mod, "log_error"):
                    with patch.object(hook_mod, "log_info"):
                        hook_mod.main()

    assert captured_output, "Hook produced no output"
    return json.loads(captured_output[-1])


# ---------------------------------------------------------------------------
# Helpers to assert decision outcomes
# ---------------------------------------------------------------------------

def assert_denied(result: dict, substring: str = ""):
    decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "deny", f"Expected deny, got {decision!r}. Full result: {result}"
    if substring:
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert substring.lower() in reason.lower(), (
            f"Expected {substring!r} in deny reason. Got: {reason!r}"
        )


def assert_allowed(result: dict):
    decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "allow", f"Expected allow, got {decision!r}. Full result: {result}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMissingRunInBackground:
    """Agent call missing run_in_background → self-healed to True, not denied.

    Per commit 15bd48c ("force background via updatedInput injection instead
    of denying"), a False/absent run_in_background (without FOREGROUND_AUTHORIZED)
    is no longer a deny path — the hook injects run_in_background=True into
    tool_input and falls through to the normal card-injection (allow) path.
    """

    @staticmethod
    def _fake_subprocess_run(cmd, **kwargs):
        card_xml = KanbanMockResponses.card_xml()
        if cmd[0] == "kanban" and cmd[1] == "show":
            return KanbanMockResponses.success(stdout=card_xml)
        if cmd[0] == "kanban" and cmd[1] == "agent":
            return KanbanMockResponses.success()
        return KanbanMockResponses.failure()

    def test_false_run_in_background_self_heals_to_true(self, hook):
        payload = make_pretool_payload(run_in_background=False)
        with patch("subprocess.run", side_effect=self._fake_subprocess_run):
            result = run_hook_main(hook, payload)
        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        assert updated_input.get("run_in_background") is True

    def test_missing_run_in_background_self_heals_to_true(self, hook):
        # Omit the key entirely from tool_input
        payload = make_pretool_payload(run_in_background=None)
        # Remove the key — make_pretool_payload omits it when None
        with patch("subprocess.run", side_effect=self._fake_subprocess_run):
            result = run_hook_main(hook, payload)
        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        assert updated_input.get("run_in_background") is True

    def test_self_heal_preserves_other_updated_input_fields(self, hook):
        payload = make_pretool_payload(run_in_background=False)
        with patch("subprocess.run", side_effect=self._fake_subprocess_run):
            result = run_hook_main(hook, payload)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        assert updated_input.get("run_in_background") is True
        assert updated_input.get("description") == "Test agent description"
        assert updated_input.get("subagent_type") == "swe-devex"


class TestAffirmativeRunInBackgroundStringForms:
    """String forms of 'true' (case-insensitive) must be treated as affirmative,
    matching boolean True — decision must be 'allow'.

    Ported from the deleted top-level duplicate
    modules/claude/test_kanban_pretool_hook.py, whose equivalent
    '*_is_permitted' tests still passed against current hook behavior (only
    that file's '*_is_denied' tests were stale, per commit 15bd48c's
    self-heal-instead-of-deny change). This preserves that still-valid
    coverage of the case-insensitive string comparison in the canonical
    suite.
    """

    @staticmethod
    def _fake_subprocess_run(cmd, **kwargs):
        card_xml = KanbanMockResponses.card_xml()
        if cmd[0] == "kanban" and cmd[1] == "show":
            return KanbanMockResponses.success(stdout=card_xml)
        if cmd[0] == "kanban" and cmd[1] == "agent":
            return KanbanMockResponses.success()
        return KanbanMockResponses.failure()

    @pytest.mark.parametrize("value", ["true", "True", "TRUE"])
    def test_string_true_variants_are_permitted(self, hook, value):
        """String 'true' (any case) must be permitted (decision='allow'),
        equivalent to boolean True.
        """
        payload = make_pretool_payload(run_in_background=value)
        with patch("subprocess.run", side_effect=self._fake_subprocess_run):
            result = run_hook_main(hook, payload)
        assert_allowed(result)


class TestMissingDescription:
    """Agent call missing or empty description → denied."""

    def test_empty_description_denied(self, hook):
        payload = make_pretool_payload(description="")
        result = run_hook_main(hook, payload)
        assert_denied(result, "description")

    def test_whitespace_only_description_denied(self, hook):
        payload = make_pretool_payload(description="   ")
        result = run_hook_main(hook, payload)
        assert_denied(result, "description")

    def test_deny_reason_mentions_description(self, hook):
        payload = make_pretool_payload(description="")
        result = run_hook_main(hook, payload)
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert "description" in reason.lower()


class TestMissingSubagentType:
    """Agent call missing or empty subagent_type → denied."""

    def test_empty_subagent_type_denied(self, hook):
        payload = make_pretool_payload(subagent_type="")
        result = run_hook_main(hook, payload)
        assert_denied(result, "subagent_type")

    def test_whitespace_only_subagent_type_denied(self, hook):
        payload = make_pretool_payload(subagent_type="  ")
        result = run_hook_main(hook, payload)
        assert_denied(result, "subagent_type")

    def test_deny_reason_mentions_subagent_type(self, hook):
        payload = make_pretool_payload(subagent_type="")
        result = run_hook_main(hook, payload)
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert "subagent_type" in reason.lower()


class TestInvalidSubagentType:
    """Agent call with 'general-purpose' subagent_type → denied."""

    def test_general_purpose_denied(self, hook):
        payload = make_pretool_payload(subagent_type="general-purpose")
        result = run_hook_main(hook, payload)
        assert_denied(result, "general-purpose")

    def test_general_purpose_case_insensitive(self, hook):
        payload = make_pretool_payload(subagent_type="General-Purpose")
        result = run_hook_main(hook, payload)
        assert_denied(result, "general-purpose")

    def test_specific_subagent_allowed(self, hook):
        """swe-backend is a valid subagent type — hook proceeds past the subagent_type check."""
        payload = make_pretool_payload(subagent_type="swe-backend")
        # The card reference check fires next; mock kanban show to succeed
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)
        # Must be allowed (card injected) — not denied for subagent_type
        assert_allowed(result)


class TestCardInjection:
    """Agent call with card number → card XML injected into prompt."""

    def test_card_xml_injected_into_prompt(self, hook):
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        new_prompt = updated_input.get("prompt", "")
        assert "Kanban card #42" in new_prompt
        assert "injected by PreToolUse hook" in new_prompt

    def test_card_injection_preserves_original_fields(self, hook):
        """updatedInput must contain ALL original tool_input fields."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
            description="Test description",
            run_in_background=True,
        )
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        assert updated_input.get("subagent_type") == "swe-devex"
        assert updated_input.get("description") == "Test description"
        assert updated_input.get("run_in_background") is True

    def test_kanban_show_failure_fails_open(self, hook):
        """If kanban show fails, hook should fail open (allow unchanged)."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.failure(returncode=1)
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        # No updatedInput — fails open means no injection
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput")
        assert updated_input is None

    def test_fetch_card_xml_failure_logs_error(self, hook):
        """fetch_card_xml logs an error when kanban show fails (diagnostic path)."""
        # Test fetch_card_xml directly to assert log_error is called on failure
        mock_result = KanbanMockResponses.failure(returncode=1, stderr="not found")
        with patch("subprocess.run", return_value=mock_result):
            with patch.object(hook, "log_error") as mock_log_error:
                result = hook.fetch_card_xml("42", "test-session")
        assert result is None
        mock_log_error.assert_called_once()

    def test_sqlite_backfill_called_on_successful_kanban_agent(self, hook):
        """After successful kanban agent call, sqlite3.connect is called to backfill DB."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("sqlite3.connect", return_value=mock_conn) as mock_sqlite:
                result = run_hook_main(hook, payload)

        assert_allowed(result)
        mock_sqlite.assert_called_once()
        # Verify the UPDATE was executed with expected parameters
        execute_calls = mock_conn.execute.call_args_list
        update_calls = [c for c in execute_calls if "UPDATE" in str(c) and "kanban_card_events" in str(c)]
        assert len(update_calls) >= 1, "Expected UPDATE kanban_card_events to be called"
        # Verify the normalized agent value and card number are passed
        update_args = update_calls[0][0]  # positional args of the first UPDATE call
        params = update_args[1] if len(update_args) > 1 else ()
        assert "swe-devex" in params, f"Expected swe-devex in UPDATE params: {params}"
        assert "42" in params, f"Expected card number 42 in UPDATE params: {params}"

    def test_sqlite_backfill_not_called_when_kanban_agent_fails(self, hook):
        """If kanban agent call fails, sqlite3.connect should NOT be called."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                # kanban agent fails
                return KanbanMockResponses.failure(returncode=1)
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("sqlite3.connect") as mock_sqlite:
                result = run_hook_main(hook, payload)

        assert_allowed(result)
        mock_sqlite.assert_not_called()

    def test_sqlite_exception_swallowed_does_not_propagate(self, hook):
        """If sqlite3.connect raises, the error is swallowed and hook still allows."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("sqlite3.connect", side_effect=Exception("DB not available")):
                # Must not raise — exception must be swallowed
                result = run_hook_main(hook, payload)

        # Hook should still allow despite DB failure
        assert_allowed(result)


def _card_xml_with_editfiles(
    card_number: str = "42",
    session: str = "test-session",
    edit_files: "list[str] | None" = None,
) -> str:
    """Build a minimal card XML string with an <edit-files> block.

    Local to this test module (not conftest.py — conftest.py is out of this
    card's editFiles scope). Mirrors the <edit-files><f>...</f></edit-files>
    structure the real kanban CLI emits; see KanbanMockResponses.card_xml in
    conftest.py for the sibling fixture that omits edit-files entirely.
    """
    if edit_files is None:
        edit_files = []
    ef_xml = "".join(f"<f>{f}</f>" for f in edit_files)
    return (
        f'<card num="{card_number}" session="{session}" status="doing" cycles="0">\n'
        f'  <intent>Test card intent</intent>\n'
        f'  <acceptance-criteria>\n'
        f'    <ac met="false">Some criterion</ac>\n'
        f'  </acceptance-criteria>\n'
        f'  <edit-files>{ef_xml}</edit-files>\n'
        f'</card>'
    )


class TestProgressProtocolInjection:
    """Automatic per-edit progress-protocol injection for multi-file work cards.

    Card #3428: when a card lists 2+ <edit-files><f> entries, the hook
    injects a PROGRESS PROTOCOL block into the agent prompt automatically —
    see build_progress_protocol_block() and _count_edit_files_in_card_xml()
    in kanban-pretool-hook.py.
    """

    def test_progress_protocol_injected_for_multi_file_card(self, hook):
        """A card with 2+ edit-files entries gets the PROGRESS PROTOCOL block injected."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = _card_xml_with_editfiles(
            card_number="42",
            session="test-session",
            edit_files=["src/a.py", "src/b.py"],
        )

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        new_prompt = updated_input.get("prompt", "")
        assert "PROGRESS PROTOCOL" in new_prompt
        assert ".scratchpad/42-progress.md" in new_prompt

    def test_progress_protocol_not_injected_for_single_file_card(self, hook):
        """A card with 0 or 1 edit-files entries does NOT get the block injected.

        Re-anchored at the function boundary (_resolve_progress_protocol_block)
        rather than only through main(): asserting via the full main() pipeline
        exercises this branch without being able to detect its absence,
        because a correctly-gated single-file card and a fully-disabled
        feature produce the same observable main()-level output. Driving the
        decision function directly and asserting its return value fails if
        the threshold check inside it is weakened or removed — see the
        perturbation demo in .scratchpad/progress-protocol-demo.md.
        """
        card_xml = _card_xml_with_editfiles(
            card_number="42",
            session="test-session",
            edit_files=["src/a.py"],
        )

        result = hook._resolve_progress_protocol_block(card_xml, "42")

        assert result is None

    def test_progress_protocol_counts_duplicate_edit_files_siblings(self, hook):
        """Non-empty <f> entries are summed across ALL sibling <edit-files> blocks.

        Card XML with two sibling <edit-files> elements (1 <f> + 2 <f>) must
        count 3 total, not just the first sibling's 1.
        """
        card_xml = (
            '<card num="42" session="test-session" status="doing" cycles="0">\n'
            '  <intent>Test card intent</intent>\n'
            '  <acceptance-criteria>\n'
            '    <ac met="false">Some criterion</ac>\n'
            '  </acceptance-criteria>\n'
            '  <edit-files><f>src/a.py</f></edit-files>\n'
            '  <edit-files><f>src/b.py</f><f>src/c.py</f></edit-files>\n'
            '</card>'
        )

        assert hook._count_edit_files_in_card_xml(card_xml) == 3

    def test_progress_protocol_skipped_when_already_present(self, hook):
        """No second copy is injected when the card action already contains
        the literal string "PROGRESS PROTOCOL" (coordinator hand-pasted it)."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        # Card XML whose <action> already carries the block — mirrors a
        # coordinator having hand-pasted it into the card action text.
        card_xml = (
            '<card num="42" session="test-session" status="doing" cycles="0">\n'
            '  <action>Do the work. PROGRESS PROTOCOL (mandatory): ...</action>\n'
            '  <intent>Test card intent</intent>\n'
            '  <acceptance-criteria>\n'
            '    <ac met="false">Some criterion</ac>\n'
            '  </acceptance-criteria>\n'
            '  <edit-files><f>src/a.py</f><f>src/b.py</f></edit-files>\n'
            '</card>'
        )

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        new_prompt = updated_input.get("prompt", "")
        # Exactly one copy — the hand-pasted one already inside the injected
        # card XML — not two.
        assert new_prompt.count("PROGRESS PROTOCOL") == 1

    def test_progress_protocol_block_matches_output_style_canonical_copy(self, hook):
        """The injected block is byte-identical to the canonical copy documented
        in staff-engineer.md § "Per-edit progress protocol block".

        Anchored on the heading text, never a line number, so the extraction
        survives unrelated edits to the surrounding output style file.
        """
        output_style_path = (
            Path(__file__).parent.parent
            / "global"
            / "output-styles"
            / "staff-engineer.md"
        )
        content = output_style_path.read_text(encoding="utf-8")

        heading = "Per-edit progress protocol block"
        heading_idx = content.index(heading)
        after_heading = content[heading_idx:]

        # First fenced code block after the heading.
        fence_start = after_heading.index("```", after_heading.index("\n"))
        fence_start = after_heading.index("\n", fence_start) + 1
        fence_end = after_heading.index("```", fence_start)
        canonical_block = after_heading[fence_start:fence_end]
        # Normalize a single trailing newline the fence markup introduces —
        # the source function returns no trailing newline.
        canonical_block = canonical_block.rstrip("\n")

        # The doc's canonical copy uses the literal placeholder "<card>"
        # (for manual substitution by a human); passing that same literal
        # string as card_number reproduces byte-identical output without
        # a second substitution step.
        injected_block = hook.build_progress_protocol_block("<card>")

        assert canonical_block == injected_block, (
            "Canonical block in staff-engineer.md has drifted from "
            "build_progress_protocol_block()'s output — do not edit "
            "staff-engineer.md to force agreement; report the difference."
        )

    def test_progress_protocol_injection_fails_open_on_malformed_editfiles(self, hook):
        """Missing/malformed edit-files must not raise and must not inject the block."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        # Card XML entirely lacking an <edit-files> element (the conftest
        # fixture's default shape) — this is the "missing" case.
        card_xml_no_editfiles = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml_no_editfiles)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            # Must not raise — fail-open is the whole point of this test.
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        new_prompt = updated_input.get("prompt", "")
        assert "PROGRESS PROTOCOL" not in new_prompt

        # Directly exercise the parser against malformed/absent input —
        # none of these may raise; all must resolve to a count of 0.
        assert hook._count_edit_files_in_card_xml("<not><valid xml") == 0
        assert hook._count_edit_files_in_card_xml("") == 0
        assert hook._count_edit_files_in_card_xml(None) == 0


class TestNoCardReference:
    """Agent call without card number → denied unless SKILL_AGENT_BYPASS."""

    def test_no_card_reference_denied(self, hook):
        payload = make_pretool_payload(prompt="Please do some work without any card reference.")
        result = run_hook_main(hook, payload)
        assert_denied(result, "kanban card")

    def test_deny_reason_explains_card_requirement(self, hook):
        payload = make_pretool_payload(prompt="Work without a card.")
        result = run_hook_main(hook, payload)
        reason = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert "kanban" in reason.lower() or "card" in reason.lower()


class TestForegroundAuthorized:
    """FOREGROUND_AUTHORIZED marker → allows run_in_background: false."""

    def test_foreground_authorized_bypasses_background_check(self, hook):
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="FOREGROUND_AUTHORIZED\nKANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        assert updated_input.get("run_in_background") is False

    def test_foreground_authorized_with_whitespace_padding_bypasses(self, hook):
        """FOREGROUND_AUTHORIZED with leading/trailing whitespace on its own line is allowed."""
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="  FOREGROUND_AUTHORIZED  \nKANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        assert updated_input.get("run_in_background") is False

    def test_foreground_authorized_still_enforces_description(self, hook):
        """FOREGROUND_AUTHORIZED does NOT bypass description check."""
        payload = make_pretool_payload(
            run_in_background=False,
            description="",
            prompt="FOREGROUND_AUTHORIZED\nKANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        result = run_hook_main(hook, payload)
        assert_denied(result, "description")

    def test_foreground_authorized_in_negation_prose_is_still_force_healed(self, hook):
        """FOREGROUND_AUTHORIZED embedded in prose (negation) must NOT bypass the
        self-heal-to-background injection.

        Bug fix: 'no FOREGROUND_AUTHORIZED marker' used to bypass the check via
        substring match. The line-anchored regex must reject prose that merely
        contains the marker text — the marker must occupy its own line.

        Per commit 15bd48c, the enforcement no longer denies on missing/false
        run_in_background — it self-heals to True. So the regression guard now
        asserts run_in_background is force-healed to True (not left as the
        user-provided False, which would indicate the negation prose was
        incorrectly treated as authorization).
        """
        payload = make_pretool_payload(
            run_in_background=False,
            prompt=(
                "This prompt says no FOREGROUND_AUTHORIZED marker is present.\n"
                "KANBAN CARD #42 | Session: test-session\nDo some work."
            ),
        )
        card_xml = KanbanMockResponses.card_xml()

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        assert updated_input.get("run_in_background") is True, (
            "Negation prose must not be treated as FOREGROUND_AUTHORIZED — "
            "run_in_background should be force-healed to True."
        )


class TestSkillAgentBypass:
    """SKILL_AGENT_BYPASS marker → bypasses all enforcement."""

    def test_bypass_skips_description_check(self, hook):
        payload = make_pretool_payload(
            run_in_background=None,
            description=None,
            subagent_type=None,
            prompt="SKILL_AGENT_BYPASS\nsome skill invocation",
        )
        result = run_hook_main(hook, payload)
        # Should be allow (no card found so fails open)
        assert_allowed(result)

    def test_bypass_skips_subagent_type_check(self, hook):
        payload = make_pretool_payload(
            subagent_type=None,
            prompt="SKILL_AGENT_BYPASS\nsome skill invocation",
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bypass_skips_run_in_background_check(self, hook):
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="SKILL_AGENT_BYPASS\nsome skill invocation",
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_skill_agent_bypass_with_whitespace_padding_bypasses(self, hook):
        """SKILL_AGENT_BYPASS with leading/trailing whitespace on its own line is allowed."""
        payload = make_pretool_payload(
            run_in_background=False,
            prompt="  SKILL_AGENT_BYPASS  \nsome skill invocation",
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_skill_agent_bypass_in_negation_prose_is_denied(self, hook):
        """SKILL_AGENT_BYPASS embedded in prose must NOT trigger bypass.

        Bug fix: 'no SKILL_AGENT_BYPASS marker' used to bypass enforcement
        via substring match. The line-anchored regex must reject prose that
        merely contains the marker text.
        """
        payload = make_pretool_payload(
            run_in_background=False,
            description="",
            subagent_type="",
            prompt="This prompt says no SKILL_AGENT_BYPASS marker should be here.",
        )
        result = run_hook_main(hook, payload)
        # Without bypass, empty description triggers deny
        assert_denied(result, "description")

    def test_bypass_with_card_reference_still_injects(self, hook):
        """With SKILL_AGENT_BYPASS and a card reference, injection still occurs."""
        payload = make_pretool_payload(
            run_in_background=None,
            description=None,
            subagent_type=None,
            prompt="SKILL_AGENT_BYPASS\nKANBAN CARD #99 | Session: bypass-session\nDo work.",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="99", session="bypass-session")

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)
        updated_input = result.get("hookSpecificOutput", {}).get("updatedInput", {})
        new_prompt = updated_input.get("prompt", "")
        # Both the card reference AND the injection marker must be present
        assert "Kanban card #99" in new_prompt, (
            f"Expected 'Kanban card #99' in injected prompt, got: {new_prompt[:200]!r}"
        )
        assert "injected by PreToolUse hook" in new_prompt, (
            f"Expected injection marker in prompt, got: {new_prompt[:200]!r}"
        )


class TestPersonalTrainerSession:
    """PERSONAL_TRAINER_SESSION=1 → hook skips all processing and allows unchanged."""

    def test_personal_trainer_session_allows_unchanged(self, hook):
        payload = make_pretool_payload(run_in_background=False, description="", subagent_type="")
        result = run_hook_main(hook, payload, env={"PERSONAL_TRAINER_SESSION": "1"})
        assert_allowed(result)
        # No updatedInput — completely unchanged
        assert "updatedInput" not in result.get("hookSpecificOutput", {})


class TestNonAgentTool:
    """Non-Agent tool_name → allow unchanged (hook is Agent-only)."""

    def test_non_agent_tool_allowed(self, hook):
        payload = make_pretool_payload()
        payload["tool_name"] = "Bash"
        result = run_hook_main(hook, payload)
        assert_allowed(result)


class TestResponseStructure:
    """Verify the hook always produces structurally valid JSON output."""

    def test_allow_response_has_required_fields(self, hook):
        payload = make_pretool_payload()
        card_xml = KanbanMockResponses.card_xml()
        with patch("subprocess.run", return_value=KanbanMockResponses.success(stdout=card_xml)):
            result = run_hook_main(hook, payload)
        assert "continue" in result
        assert "hookSpecificOutput" in result
        hook_out = result["hookSpecificOutput"]
        assert "hookEventName" in hook_out
        assert hook_out["hookEventName"] == "PreToolUse"
        assert "permissionDecision" in hook_out

    def test_deny_response_has_required_fields(self, hook):
        # Missing description is a deterministic deny path that requires no
        # subprocess/kanban-CLI mocking (checked before any card lookup) —
        # run_in_background=False no longer denies (see TestMissingRunInBackground).
        payload = make_pretool_payload(description="")
        result = run_hook_main(hook, payload)
        # No top-level "continue" field — a turn-halting deny would make the
        # agent's own same-turn recovery (retry or stop-and-report) structurally
        # impossible. See CLAUDE.md § Tool-Block Recovery and card #3487.
        assert "continue" not in result
        hook_out = result["hookSpecificOutput"]
        assert hook_out["permissionDecision"] == "deny"
        assert "permissionDecisionReason" in hook_out

        # Top-level stopReason must be absent — see card #3487.
        assert "stopReason" not in result, (
            f"Expected no top-level stopReason: {result}"
        )


class TestCardPatternExtraction:
    """Unit tests for extract_card_and_session directly."""

    def test_full_pattern(self, hook):
        prompt = "KANBAN CARD #123 | Session: my-session\nDo work."
        result = hook.extract_card_and_session(prompt)
        assert result == ("123", "my-session")

    def test_card_session_pattern(self, hook):
        prompt = "#456 --session another-session do something"
        result = hook.extract_card_and_session(prompt)
        assert result == ("456", "another-session")

    def test_bare_card_pattern(self, hook):
        prompt = "Work on card #789 please.\nSession: bare-session"
        result = hook.extract_card_and_session(prompt)
        assert result == ("789", "bare-session")

    def test_no_match_returns_none(self, hook):
        prompt = "No card reference here at all."
        result = hook.extract_card_and_session(prompt)
        assert result is None

    def test_card_session_pattern_requires_same_line(self, hook):
        """Pattern 2 (_CARD_SESSION_PATTERN) requires card # and --session on the same line.
        When they are on different lines, it falls through to Pattern 3 (bare card + bare session).
        """
        # Card number on one line, --session on a different line — Pattern 2 must NOT match.
        # Pattern 3 (bare card + bare session) should pick this up instead.
        prompt = "card #456\n--session cross-line-session\nDo work."
        result = hook.extract_card_and_session(prompt)
        # Pattern 3 (bare card + bare session) can still match here
        # The important thing is Pattern 2 didn't match (which would also give the right answer)
        # We verify the result is correct regardless of which pattern matched
        assert result is not None, "Expected some match via Pattern 3 fallthrough"
        assert result[0] == "456"
        assert result[1] == "cross-line-session"


# ---------------------------------------------------------------------------
# Helpers for destructive-git safeguard tests
# ---------------------------------------------------------------------------

def make_bash_payload(
    command: str,
    agent_id: str | None = "agent-abc123",
    session_id: str = "test-session",
    cwd: str = "/repo",
) -> dict:
    """Build a minimal PreToolUse Bash payload."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session_id,
        "cwd": cwd,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return payload


def make_kanban_list_xml(card_number: str = "42") -> str:
    """Build a minimal kanban list XML response containing one card."""
    return f'<cards><c n="{card_number}" status="doing"/></cards>'


def make_kanban_show_xml(card_number: str = "42", edit_files: list | None = None) -> str:
    """Build a minimal kanban show XML with optional edit-files entries."""
    if edit_files is None:
        edit_files = ["modules/claude/kanban-pretool-hook.py"]
    ef_entries = "".join(f"<f>{f}</f>" for f in edit_files)
    ef_block = f"<edit-files>{ef_entries}</edit-files>" if ef_entries else "<edit-files/>"
    return (
        f'<card num="{card_number}" session="test-session" status="doing">'
        f"<intent>Test card</intent>"
        f"{ef_block}"
        f"</card>"
    )


def patch_kanban_for_editfiles(edit_files: list | None = None, card_number: str = "42"):
    """Return a fake subprocess.run that simulates successful kanban list + show."""
    list_xml = make_kanban_list_xml(card_number)
    show_xml = make_kanban_show_xml(card_number, edit_files)

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "kanban":
            if cmd[1] == "list":
                return KanbanMockResponses.success(stdout=list_xml)
            if cmd[1] == "show":
                return KanbanMockResponses.success(stdout=show_xml)
        return KanbanMockResponses.failure()

    return fake_run


class TestDestructiveGitSafeguard:
    """Tests for the destructive git operation safeguard in _validate_bash_destructive_git.

    All kanban CLI calls are patched via subprocess.run — no real kanban state is read.
    """

    # 1. Sub-agent + git checkout -- <in-scope-file> → ALLOW
    def test_checkout_in_scope_file_allowed(self, hook):
        """git checkout -- on a file that IS in editFiles must be allowed."""
        payload = make_bash_payload("git checkout -- modules/claude/kanban-pretool-hook.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 2. Sub-agent + git checkout -- <out-of-scope-file> → DENY
    def test_checkout_out_of_scope_file_denied(self, hook):
        """git checkout -- on a file NOT in editFiles must be denied with card + file info."""
        payload = make_bash_payload("git checkout -- secret.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "secret.py" in reason
        assert "editFiles" in reason

    # 3. Sub-agent + git restore <out-of-scope-file> → DENY
    def test_restore_out_of_scope_file_denied(self, hook):
        """git restore on an out-of-scope file must be denied."""
        payload = make_bash_payload("git restore other_module.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 4. Sub-agent + git restore --staged <out-of-scope-file> → DENY
    def test_restore_staged_out_of_scope_denied(self, hook):
        """git restore --staged on an out-of-scope file must be denied."""
        payload = make_bash_payload("git restore --staged other_module.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 5. Sub-agent + git reset -- <out-of-scope-file> → DENY
    def test_reset_file_out_of_scope_denied(self, hook):
        """git reset -- <file> on an out-of-scope file must be denied."""
        payload = make_bash_payload("git reset -- secret.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 6. Sub-agent + git reset --hard HEAD → DENY unconditionally
    def test_reset_hard_denied_unconditionally(self, hook):
        """git reset --hard is blocked regardless of editFiles — reverts ALL tracked files."""
        payload = make_bash_payload("git reset --hard HEAD")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "reset --hard" in reason or "all tracked" in reason.lower()

    # 7. Sub-agent + git stash drop → DENY unconditionally
    def test_stash_drop_denied_unconditionally(self, hook):
        """git stash drop is always denied for sub-agents."""
        payload = make_bash_payload("git stash drop")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash drop" in reason

    # 8. Sub-agent + git clean -f → DENY (synthetic <all-untracked> target)
    def test_clean_denied_all_untracked(self, hook):
        """git clean -f is denied — no specific file, affects all untracked."""
        payload = make_bash_payload("git clean -f")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 9. Sub-agent + git checkout <branch> → ALLOW (non-destructive branch switch)
    def test_checkout_branch_allowed(self, hook):
        """git checkout <branch> is a non-destructive branch switch and must be allowed."""
        payload = make_bash_payload("git checkout main")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 10. Sub-agent + git checkout -b <branch> → ALLOW
    def test_checkout_new_branch_allowed(self, hook):
        """git checkout -b <branch> creates a new branch — non-destructive, must be allowed."""
        payload = make_bash_payload("git checkout -b feature/my-feature")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 11. Main thread (no agent_id) + git checkout -- <any-file> → ALLOW (staff bypass)
    def test_main_thread_bypasses_safeguard(self, hook):
        """Without agent_id, the safeguard does not apply — staff engineer is allowed."""
        payload = make_bash_payload(
            "git checkout -- secret.py",
            agent_id=None,  # No agent_id → main session
        )
        # Even with a mocked kanban that could respond, the guard should not be reached
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 12. Compound git status && git checkout -- <out-of-scope> → DENY
    def test_compound_and_operator_denied(self, hook):
        """Compound command with && must still catch the destructive git checkout."""
        payload = make_bash_payload("git status && git checkout -- secret.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 13. Compound git status; git checkout -- <out-of-scope> → DENY
    def test_compound_semicolon_operator_denied(self, hook):
        """Compound command with ; must still catch the destructive git checkout."""
        payload = make_bash_payload("git status; git checkout -- secret.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(
            edit_files=["modules/claude/kanban-pretool-hook.py"]
        )):
            result = run_hook_main(hook, payload)
        assert_denied(result)

    # 14. Kanban lookup failure → ALLOW (fails open — documents accepted trade-off)
    def test_kanban_lookup_failure_fails_open(self, hook):
        """When kanban CLI is unavailable, the safeguard fails open to avoid blocking work.

        This is an accepted trade-off: a kanban outage creates a bypass window,
        but blocking all git ops during infrastructure issues is worse.
        """
        payload = make_bash_payload("git checkout -- secret.py")
        with patch("subprocess.run", side_effect=subprocess.SubprocessError("kanban not found")):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_fetch_doing_card_anomalous_cli_failure_logs_error(self, hook):
        """kanban CLI non-zero exit is ANOMALOUS — must log_error naming the failure.

        Distinct from the benign 'no card in doing' case: an operator needs to
        know infrastructure failed, not just that a lookup came back empty.
        """
        mock_result = KanbanMockResponses.failure(returncode=1, stderr="kanban: connection refused")
        with patch("subprocess.run", return_value=mock_result):
            with patch.object(hook, "log_error") as mock_log_error:
                with patch.object(hook, "log_info") as mock_log_info:
                    result = hook._fetch_doing_card_for_session("test-session")
        assert result is None  # still fails open
        mock_log_error.assert_called_once()
        logged_message = mock_log_error.call_args[0][0]
        assert "kanban CLI failed" in logged_message
        assert "1" in logged_message  # exit code surfaced
        mock_log_info.assert_not_called()

    def test_fetch_doing_card_benign_no_card_does_not_log_error(self, hook):
        """kanban CLI success with empty stdout is BENIGN — no card in doing.

        Must NOT call log_error: this is a routine, expected state (a session
        with no card in 'doing') and error-log noise here would bury genuine
        CLI-failure signals.
        """
        mock_result = KanbanMockResponses.success(stdout="")
        with patch("subprocess.run", return_value=mock_result):
            with patch.object(hook, "log_error") as mock_log_error:
                result = hook._fetch_doing_card_for_session("test-session")
        assert result is None  # still fails open
        mock_log_error.assert_not_called()

    # 15. Card with empty editFiles → DENY all destructive ops
    def test_empty_edit_files_denies_all_destructive(self, hook):
        """A card with no editFiles must deny all destructive git ops."""
        payload = make_bash_payload("git checkout -- any_file.py")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles(edit_files=[])):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "none listed" in reason.lower() or "no editFiles" in reason.lower() or "editfiles" in reason.lower()

    # 16. git checkout -p with no file target → DENY with clear error (not confusing sentinel)
    def test_checkout_p_no_file_denied_with_clear_message(self, hook):
        """git checkout -p (no file) must produce a human-readable error, not a sentinel name."""
        payload = make_bash_payload("git checkout -p")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        # Must NOT expose the raw sentinel token as a filename
        assert "<interactive-hunk-revert>" not in reason
        # Must explain WHY it was blocked
        assert "interactive" in reason.lower() or "checkout -p" in reason.lower()

    # 17. fnmatch basename fallback: bare 'foo.py' editFile + target 'src/foo.py' → NO match
    def test_basename_fallback_not_over_permissive(self, hook):
        """A bare 'foo.py' editFiles entry must NOT match 'src/foo.py' after the M3 fix.

        The tightened basename fallback only applies when the pattern contains no path
        separator, but the pattern 'foo.py' should only match a file literally named
        'foo.py' at the root — NOT 'src/foo.py'.
        """
        # Use _file_in_editfiles directly to test the matching logic in isolation
        hook_mod = hook
        # 'foo.py' as a bare pattern should NOT match 'src/foo.py'
        result = hook_mod._file_in_editfiles("src/foo.py", ["foo.py"], "/repo")
        assert result is False, (
            "bare 'foo.py' in editFiles must not match 'src/foo.py' after M3 basename fix"
        )

    # 18. git stash push → DENY unconditionally for sub-agents
    def test_stash_push_blocked_for_sub_agent(self, hook):
        """git stash push is blocked unconditionally for sub-agents."""
        payload = make_bash_payload("git stash push")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash" in reason.lower()
        assert "cross-card" in reason.lower() or "parallel" in reason.lower() or "working-tree" in reason.lower() or "working tree" in reason.lower()
        assert "stop" in reason.lower() or "report" in reason.lower()

    # 19. git stash save → DENY unconditionally for sub-agents
    def test_stash_save_blocked_for_sub_agent(self, hook):
        """git stash save is blocked unconditionally for sub-agents."""
        payload = make_bash_payload("git stash save 'WIP changes'")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash" in reason.lower()

    # 20. git stash (bare, no subcommand) → DENY unconditionally for sub-agents
    def test_stash_bare_blocked_for_sub_agent(self, hook):
        """Bare 'git stash' (equivalent to git stash push) is blocked for sub-agents."""
        payload = make_bash_payload("git stash")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash" in reason.lower()

    # 21. git stash --keep-index → DENY unconditionally for sub-agents
    def test_stash_keep_index_blocked_for_sub_agent(self, hook):
        """git stash --keep-index is blocked unconditionally for sub-agents."""
        payload = make_bash_payload("git stash --keep-index")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash" in reason.lower()

    # 22. git stash pop → ALLOW (non-destructive restore, not blocked)
    def test_stash_pop_allowed(self, hook):
        """git stash pop restores working tree from stash — not a push operation, must be allowed."""
        payload = make_bash_payload("git stash pop")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 23. git stash apply → ALLOW (non-destructive restore, not blocked)
    def test_stash_apply_allowed(self, hook):
        """git stash apply restores working tree from stash — not a push operation, must be allowed."""
        payload = make_bash_payload("git stash apply stash@{0}")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 24. git stash list → ALLOW (read-only inspection)
    def test_stash_list_allowed(self, hook):
        """git stash list is a read-only inspection command — must be allowed."""
        payload = make_bash_payload("git stash list")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_allowed(result)

    # 25. git stash drop → still DENY (regression — pre-existing block must not break)
    def test_stash_drop_still_blocked(self, hook):
        """Regression: git stash drop was already blocked — verify it stays blocked."""
        payload = make_bash_payload("git stash drop stash@{0}")
        with patch("subprocess.run", side_effect=patch_kanban_for_editfiles()):
            result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "stash drop" in reason

    # 26. Main thread (no agent_id) + git stash push → ALLOW (staff engineer bypass)
    def test_main_thread_stash_push_allowed(self, hook):
        """Without agent_id, stash push is not blocked — staff engineer may use git stash."""
        payload = make_bash_payload(
            "git stash push",
            agent_id=None,  # No agent_id → main session (staff engineer)
        )
        result = run_hook_main(hook, payload)
        assert_allowed(result)


# ---------------------------------------------------------------------------
# Helpers for .kanban/ path guard tests
# ---------------------------------------------------------------------------

def make_edit_payload(file_path: str) -> dict:
    """Build a minimal PreToolUse Edit payload."""
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": "foo",
            "new_string": "bar",
        },
    }


def make_write_payload(file_path: str) -> dict:
    """Build a minimal PreToolUse Write payload."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": "{}",
        },
    }


def make_multiedit_payload(file_path: str) -> dict:
    """Build a minimal PreToolUse MultiEdit payload."""
    return {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": file_path,
            "edits": [],
        },
    }


def make_notebook_edit_payload(notebook_path: str) -> dict:
    """Build a minimal PreToolUse NotebookEdit payload."""
    return {
        "tool_name": "NotebookEdit",
        "tool_input": {
            "notebook_path": notebook_path,
            "cell_type": "code",
            "source": "",
        },
    }


class TestKanbanPathGuard:
    """Tests for the .kanban/ path guard in _check_kanban_path_guard.

    Verifies that direct file writes to .kanban/ are denied, reads are allowed,
    and kanban CLI commands are always allowed.
    """

    # --- Edit ---

    def test_edit_kanban_path_denied(self, hook):
        """Edit on .kanban/doing/123.json must be denied."""
        payload = make_edit_payload(".kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_edit_kanban_nested_denied(self, hook):
        """Edit on a nested .kanban/ path must be denied."""
        payload = make_edit_payload(".kanban/done/456.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_edit_normal_file_allowed(self, hook):
        """Edit on src/foo.py (outside .kanban/) must be allowed."""
        payload = make_edit_payload("src/foo.py")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- Write ---

    def test_write_kanban_path_denied(self, hook):
        """Write on .kanban/.perm-tracking.json must be denied."""
        payload = make_write_payload(".kanban/.perm-tracking.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_write_normal_file_allowed(self, hook):
        """Write on src/config.py (outside .kanban/) must be allowed."""
        payload = make_write_payload("src/config.py")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- MultiEdit ---

    def test_multiedit_kanban_path_denied(self, hook):
        """MultiEdit on .kanban/done/456.json must be denied."""
        payload = make_multiedit_payload(".kanban/done/456.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- NotebookEdit ---

    def test_notebook_edit_kanban_path_denied(self, hook):
        """NotebookEdit on .kanban/whatever.ipynb must be denied."""
        payload = make_notebook_edit_payload(".kanban/whatever.ipynb")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- Bash: mutation patterns → DENY ---

    def test_bash_python_mutation_denied(self, hook):
        """Bash with python3 -c '... .kanban/ ...' must be denied."""
        payload = make_bash_payload("python3 -c 'import json; open(\".kanban/doing/123.json\", \"w\")'")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_sed_inplace_kanban_denied(self, hook):
        """Bash with sed -i on .kanban/ path must be denied."""
        payload = make_bash_payload("sed -i 's/foo/bar/' .kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_redirect_kanban_denied(self, hook):
        """Bash with shell redirection writing to .kanban/ must be denied."""
        payload = make_bash_payload("echo {} > .kanban/file.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_rm_kanban_denied(self, hook):
        """Bash with rm .kanban/doing/123.json must be denied."""
        payload = make_bash_payload("rm .kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- Bash: reads → ALLOW ---

    def test_bash_cat_kanban_allowed(self, hook):
        """Bash with cat .kanban/doing/123.json (read) must be allowed."""
        payload = make_bash_payload("cat .kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- Bash: kanban CLI → ALLOW ---

    def test_bash_kanban_criteria_check_allowed(self, hook):
        """Bash with 'kanban criteria check 123 1' must be allowed."""
        payload = make_bash_payload("kanban criteria check 123 1")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_kanban_list_allowed(self, hook):
        """Bash with 'kanban list' must be allowed."""
        payload = make_bash_payload("kanban list")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_kanban_show_allowed(self, hook):
        """kanban show reads from .kanban/ internally — still allowed via CLI allowlist."""
        payload = make_bash_payload("kanban show 42 --session test-session")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- Denial message content ---

    def test_denial_message_includes_kanban_cli_guidance(self, hook):
        """Denial message must include kanban CLI guidance and prohibition text."""
        payload = make_edit_payload(".kanban/doing/123.json")
        result = run_hook_main(hook, payload)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "kanban CLI" in reason or "kanban criteria" in reason
        assert ".kanban/" in reason

    # --- Unit tests for helper functions ---

    def test_is_under_kanban_dir_relative(self, hook):
        """_is_under_kanban_dir: relative .kanban/ path → True."""
        assert hook._is_under_kanban_dir(".kanban/doing/123.json") is True

    def test_is_under_kanban_dir_nested(self, hook):
        """_is_under_kanban_dir: nested .kanban/ component → True."""
        assert hook._is_under_kanban_dir(".kanban/done/456.json") is True

    def test_is_under_kanban_dir_normal_path(self, hook):
        """_is_under_kanban_dir: normal path → False."""
        assert hook._is_under_kanban_dir("src/foo.py") is False

    def test_is_under_kanban_dir_empty(self, hook):
        """_is_under_kanban_dir: empty string → False."""
        assert hook._is_under_kanban_dir("") is False

    def test_is_kanban_cli_command_kanban(self, hook):
        """_is_kanban_cli_command: 'kanban list' → True."""
        assert hook._is_kanban_cli_command("kanban list") is True

    def test_is_kanban_cli_command_kanban_show(self, hook):
        """_is_kanban_cli_command: 'kanban show 42' → True."""
        assert hook._is_kanban_cli_command("kanban show 42") is True

    def test_is_kanban_cli_command_not_kanban(self, hook):
        """_is_kanban_cli_command: 'rm .kanban/foo' → False."""
        assert hook._is_kanban_cli_command("rm .kanban/foo") is False

    def test_is_kanban_cli_command_python_not_kanban(self, hook):
        """_is_kanban_cli_command: python mutation command → False."""
        assert hook._is_kanban_cli_command("python3 -c 'open(\".kanban/x\", \"w\")'") is False

    # --- Allowlist anchor: kanban-prefixed binary NOT allowlisted ---

    def test_is_kanban_cli_command_kanban_prefixed_binary_false(self, hook):
        """_is_kanban_cli_command: 'kanban-foo ...' → False (not the kanban CLI).

        kanban-foo is a different binary. The anchored regex must not match it
        as a kanban CLI command. (Whether the bash call is denied depends on
        whether a deny pattern also fires — e.g. if it redirects to .kanban/.)
        """
        assert hook._is_kanban_cli_command("kanban-foo write .kanban/file.json") is False

    def test_bash_kanban_prefixed_binary_with_redirect_denied(self, hook):
        """Bash with 'kanban-foo write > .kanban/file.json' must be DENIED.

        kanban-foo is not the kanban CLI (allowlist doesn't fire), and the
        shell redirect to .kanban/ matches the deny pattern.
        """
        payload = make_bash_payload("kanban-foo write > .kanban/file.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_nix_shell_p_kanban_denied(self, hook):
        """Bash with 'nix-shell -p kanban -c ...' writing to .kanban/ must be DENIED.

        'kanban' here is a flag argument to nix-shell — not an invocation of the
        kanban CLI. The anchored regex must not allowlist this.
        The command also writes to .kanban/ so it is caught by the redirect deny pattern.
        """
        payload = make_bash_payload("nix-shell -p kanban -c 'echo x > .kanban/foo.json'")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_is_kanban_cli_command_nix_shell_false(self, hook):
        """_is_kanban_cli_command: 'nix-shell -p kanban -c ...' → False."""
        assert hook._is_kanban_cli_command("nix-shell -p kanban -c 'kanban list'") is False

    def test_bash_echo_kanban_allowed(self, hook):
        """Bash with 'echo kanban' must be ALLOWED — no .kanban/ path involved."""
        payload = make_bash_payload("echo kanban")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    # --- Symlink bypass: ln / cp -s → DENY ---

    def test_bash_ln_kanban_denied(self, hook):
        """Bash with 'ln -s real .kanban/symlink' must be DENIED.

        ln creates a symlink (or hard link) that could allow mutation via the
        symlink target. This is a symlink-bypass vector — block it.
        """
        payload = make_bash_payload("ln -s real .kanban/symlink")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_link_kanban_denied(self, hook):
        """Bash with 'link src .kanban/dst' must be DENIED."""
        payload = make_bash_payload("link src .kanban/dst")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_cp_s_kanban_denied(self, hook):
        """Bash with 'cp -s src .kanban/foo' must be DENIED.

        cp -s creates a symbolic link — this is a symlink bypass vector.
        """
        payload = make_bash_payload("cp -s src .kanban/foo")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_cp_symbolic_kanban_denied(self, hook):
        """Bash with 'cp --symbolic src .kanban/foo' must be DENIED."""
        payload = make_bash_payload("cp --symbolic src .kanban/foo")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- jq --argfile is a read, not a write → ALLOW ---

    def test_bash_jq_argfile_kanban_allowed(self, hook):
        """Bash with 'jq --argfile X .kanban/x.json \".\"' must be ALLOWED.

        jq --argfile reads the file as input — it does not mutate it. The
        false-positive deny pattern for jq --argfile has been removed.
        """
        payload = make_bash_payload("jq --argfile X .kanban/x.json '\"$X\"' input.json")
        result = run_hook_main(hook, payload)
        assert_allowed(result)

    def test_bash_jq_i_kanban_denied(self, hook):
        """Bash with 'jq -i \".\" .kanban/x.json' must be DENIED.

        jq -i edits the file in place (in-place mutation) — block it.
        """
        payload = make_bash_payload("jq -i \".\" .kanban/x.json")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    # --- python3 word boundary: no trailing slash → DENY ---

    def test_bash_python3_no_trailing_slash_denied(self, hook):
        """Bash with python3 -c '...' referencing .kanban without trailing slash → DENIED.

        The updated pattern uses \\b instead of trailing / so it catches references
        like open(\".kanban\", \"w\") without a path separator after .kanban.
        """
        payload = make_bash_payload("python3 -c 'import os; os.chdir(\".kanban\")'")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")

    def test_bash_python3_open_no_trailing_slash_denied(self, hook):
        """Bash with python3 -c 'open(\".kanban/x\",\"w\")' must be DENIED (regression)."""
        payload = make_bash_payload("python3 -c 'open(\".kanban/x\",\"w\")'")
        result = run_hook_main(hook, payload)
        assert_denied(result, "Direct file modification of .kanban/")


# ---------------------------------------------------------------------------
# Tests: agent_launch_pending clear callback
# ---------------------------------------------------------------------------

class TestAgentLaunchPendingClear:
    """Pretool hook calls clear-agent-launch-pending on Agent launch with card reference."""

    def test_clear_agent_launch_pending_called_on_agent_launch(self, hook):
        """Hook calls 'kanban clear-agent-launch-pending <N> --session <s>' on Agent launch."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        called_commands = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list):
                called_commands.append(cmd)
                if cmd[0] == "kanban" and cmd[1] == "show":
                    return KanbanMockResponses.success(stdout=card_xml)
                if cmd[0] == "kanban" and cmd[1] == "clear-agent-launch-pending":
                    return KanbanMockResponses.success()
                if cmd[0] == "kanban" and cmd[1] == "agent":
                    return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        assert_allowed(result)

        # Verify clear-agent-launch-pending was called with correct args
        clear_calls = [
            c for c in called_commands
            if c[0] == "kanban" and c[1] == "clear-agent-launch-pending"
        ]
        assert len(clear_calls) == 1, (
            f"Expected exactly 1 clear-agent-launch-pending call, got {len(clear_calls)}: {clear_calls}"
        )
        clear_cmd = clear_calls[0]
        assert "42" in clear_cmd, f"Expected card number 42 in clear command: {clear_cmd}"
        assert "--session" in clear_cmd, f"Expected --session in clear command: {clear_cmd}"
        assert "test-session" in clear_cmd, f"Expected session in clear command: {clear_cmd}"

    def test_clear_agent_launch_pending_fails_open(self, hook):
        """If clear-agent-launch-pending fails, hook still allows the agent launch."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "show":
                return KanbanMockResponses.success(stdout=card_xml)
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "clear-agent-launch-pending":
                # Simulate failure
                return KanbanMockResponses.failure(returncode=1, stderr="card not found")
            if isinstance(cmd, list) and cmd[0] == "kanban" and cmd[1] == "agent":
                return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        # Hook must still allow even if clear-agent-launch-pending fails
        assert_allowed(result)

    def test_clear_agent_launch_pending_not_called_when_no_card_xml(self, hook):
        """If kanban show fails (no card XML), clear-agent-launch-pending is not called."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
        )

        called_commands = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list):
                called_commands.append(cmd)
                if cmd[0] == "kanban" and cmd[1] == "show":
                    return KanbanMockResponses.failure(returncode=1)
            return KanbanMockResponses.success()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            result = run_hook_main(hook, payload)

        # Hook allows (fails open) when show fails
        assert_allowed(result)

        # clear-agent-launch-pending must NOT be called when card XML is unavailable
        clear_calls = [
            c for c in called_commands
            if isinstance(c, list) and c[0] == "kanban" and c[1] == "clear-agent-launch-pending"
        ]
        assert len(clear_calls) == 0, (
            f"clear-agent-launch-pending must not be called when kanban show fails, got: {clear_calls}"
        )

    def test_clear_agent_launch_pending_called_before_agent_update(self, hook):
        """clear-agent-launch-pending is invoked as part of Agent launch processing."""
        payload = make_pretool_payload(
            prompt="KANBAN CARD #42 | Session: test-session\nDo some work.",
            subagent_type="swe-devex",
        )
        card_xml = KanbanMockResponses.card_xml(card_number="42", session="test-session")

        call_order = []

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list):
                if cmd[0] == "kanban" and cmd[1] == "show":
                    return KanbanMockResponses.success(stdout=card_xml)
                if cmd[0] == "kanban" and cmd[1] == "clear-agent-launch-pending":
                    call_order.append("clear-agent-launch-pending")
                    return KanbanMockResponses.success()
                if cmd[0] == "kanban" and cmd[1] == "agent":
                    call_order.append("agent")
                    return KanbanMockResponses.success()
            return KanbanMockResponses.failure()

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("sqlite3.connect", return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
                execute=MagicMock(),
                commit=MagicMock(),
                close=MagicMock(),
            )):
                result = run_hook_main(hook, payload)

        assert_allowed(result)
        assert "clear-agent-launch-pending" in call_order, (
            f"clear-agent-launch-pending must be called during agent launch processing; "
            f"call_order: {call_order}"
        )


class TestExceptionReprLogging:
    """Caught exceptions interpolated into log_error() messages must use !r.

    A bare str(e) can embed a raw newline (or other delimiter-confusing
    characters) verbatim, fragmenting one logged entry into two for
    hook-error-digest-hook.py's line-based classification. Every log_error()
    call site that interpolates a caught exception must render it via
    repr() (the !r conversion), matching the session_id!r treatment already
    applied on the same lines.
    """

    def test_fetch_doing_card_session_id_logged_in_quoted_repr_form(self, hook):
        """session_id must render as session='...' (quoted), not bare session=....

        Guards against a regression back to bare {session_id} interpolation,
        which would let a session_id containing a colon or newline corrupt
        the digest's line-based parsing.
        """
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            with patch.object(hook, "log_error") as mock_log_error:
                result = hook._fetch_doing_card_for_session("test-session")
        assert result is None  # still fails open
        mock_log_error.assert_called_once()
        logged_message = mock_log_error.call_args[0][0]
        assert "session='test-session'" in logged_message

    def test_fetch_doing_card_caught_exception_logged_via_repr(self, hook):
        """The caught exception itself must render via repr(), not bare str().

        repr() on an exception surfaces its type alongside its message
        (e.g. RuntimeError('boom with\\nnewline')), and critically escapes
        any raw newline in the message body to the two-character sequence
        \\n rather than reproducing it verbatim — which would otherwise
        split one logged line into two.
        """
        with patch("subprocess.run", side_effect=RuntimeError("boom with\nnewline")):
            with patch.object(hook, "log_error") as mock_log_error:
                result = hook._fetch_doing_card_for_session("test-session")
        assert result is None
        mock_log_error.assert_called_once()
        logged_message = mock_log_error.call_args[0][0]
        assert "RuntimeError('boom with\\nnewline')" in logged_message
        assert "\n" not in logged_message


class TestWriteLogLineCap:
    """_write_log() must cap a single oversized line before writing to disk.

    Without a per-line cap, hook-error-digest-hook.py's PER_RUN_LINE_CAP (a
    per-run line-count cap, not a byte cap) would re-read one pathologically
    long line whole on every digest run until the next 10 MB file rotation.
    """

    def test_write_log_caps_overlong_line(self, hook, tmp_path):
        """A message longer than _LOG_MAX_LINE_CHARS is truncated with a marker."""
        log_path = tmp_path / "test-pretool-errors.log"
        unique_tail_marker = "UNIQUE_TAIL_MARKER_ZZZ"
        long_message = ("A" * (hook._LOG_MAX_LINE_CHARS + 1000)) + unique_tail_marker
        hook._write_log(log_path, long_message)
        logged = log_path.read_text(encoding="utf-8")
        assert unique_tail_marker not in logged
        assert "truncated" in logged

    def test_write_log_leaves_short_line_untouched(self, hook, tmp_path):
        """A message at or under the cap is written verbatim, with no marker."""
        log_path = tmp_path / "test-pretool-errors.log"
        short_message = "short benign message"
        hook._write_log(log_path, short_message)
        logged = log_path.read_text(encoding="utf-8")
        assert short_message in logged
        assert "truncated" not in logged


# ---------------------------------------------------------------------------
# Tests: rm safety guard (card #3535 / GitHub issue #17)
# ---------------------------------------------------------------------------

class TestRmGuard:
    """Tests for _validate_bash_rm_guard.

    Scope (decided on card #3535, not re-litigated here):
      - DENY any rm targeting .scratchpad/ (any target under that directory).
      - DENY any recursive rm (-r, -R, -rf, --recursive, combined short flags)
        regardless of target.
      - ALLOW non-recursive rm of an ordinary named file (regression guard).
      - The coordinator (no agent_id) is never gated by this check.

    All tests below carry 'rmguard' in their name per card instructions.
    """

    # 1. Sub-agent + rm targeting .scratchpad/ → DENY
    def test_rmguard_scratchpad_target_denied(self, hook):
        """rm on a file under .scratchpad/ must be denied for a sub-agent."""
        payload = make_bash_payload("rm .scratchpad/3535-progress.md")
        result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "auto-pruned" in reason

    # 2. Sub-agent + rm -rf <ordinary target> → DENY (short recursive flag)
    def test_rmguard_recursive_short_flag_denied(self, hook):
        """rm -rf on an ordinary (non-.scratchpad) target must be denied."""
        payload = make_bash_payload("rm -rf build/")
        result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "recursive" in reason.lower()

    # 3. Sub-agent + rm --recursive <ordinary target> → DENY (long recursive flag)
    def test_rmguard_recursive_long_flag_denied(self, hook):
        """rm --recursive must be denied — exercises the long-flag branch."""
        payload = make_bash_payload("rm --recursive some_dir")
        result = run_hook_main(hook, payload)
        assert_denied(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "recursive" in reason.lower()

    # 4. Sub-agent + rm -fr <ordinary target> → DENY (combined short-flag cluster)
    def test_rmguard_combined_short_flags_denied(self, hook):
        """rm -fr (force+recursive combined, 'r' not first) must be denied —
        exercises the combined short-flag-cluster detection branch.
        """
        payload = make_bash_payload("rm -fr some_dir")
        result = run_hook_main(hook, payload)
        assert_denied(result)

    # 5. Sub-agent + non-recursive rm of an ordinary named file → ALLOW
    #    (regression guard for the scope decision). Called directly rather
    #    than through the full main() flow because the end-to-end decision
    #    is identical before and after this change (both allow) — see
    #    rmguard-demo.md DISCRIMINATES note for why the direct call still
    #    discriminates via AttributeError on the pre-change hook module.
    def test_rmguard_named_file_allowed(self, hook):
        """Non-recursive rm of a named file outside .scratchpad/ must be
        permitted — sub-agents legitimately delete deprecated files.
        """
        payload = make_bash_payload("rm deprecated_module.py")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, (
            "non-recursive rm of an ordinary named file must not be denied"
        )

    # 6. Coordinator (no agent_id) + rm targeting .scratchpad/ → ALLOW (bypass)
    def test_rmguard_coordinator_scratchpad_bypassed(self, hook):
        """The coordinator (no agent_id) is never gated — even for .scratchpad/."""
        payload = make_bash_payload("rm .scratchpad/foo.md", agent_id=None)
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "coordinator (no agent_id) must bypass rm-guard"

    # 7. Coordinator (no agent_id) + recursive rm → ALLOW (bypass)
    def test_rmguard_coordinator_recursive_bypassed(self, hook):
        """The coordinator (no agent_id) is never gated — even for recursive rm."""
        payload = make_bash_payload("rm -rf build/", agent_id=None)
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "coordinator (no agent_id) must bypass rm-guard"


# ---------------------------------------------------------------------------
# Tests: rm safety guard wrapper-stripping (card #3540)
# ---------------------------------------------------------------------------

class TestRmGuardWrapperStripping:
    """Tests for _strip_command_wrappers as applied inside _validate_bash_rm_guard.

    Card #3540 closed the gap where a wrapped `rm` (env rm, command rm,
    xargs rm, a for-loop's `do rm`, a subshell, a brace group) evaded
    detection because the guard only inspected seg[0] of each tokenized
    segment. Every test name below carries 'rmguard_wrapper' per card
    instructions.
    """

    # --- Deny-side: each wrapper form must still be caught ---

    def test_rmguard_wrapper_env_denied(self, hook):
        """`env rm .scratchpad/x` must be denied — env wrapper stripped."""
        payload = make_bash_payload("env rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_rmguard_wrapper_env_with_assignment_denied(self, hook):
        """`env FOO=bar rm .scratchpad/x` — env's own VAR=VAL token is also skipped."""
        payload = make_bash_payload("env FOO=bar rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_rmguard_wrapper_command_denied(self, hook):
        """`command rm .scratchpad/x` must be denied — command wrapper stripped."""
        payload = make_bash_payload("command rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_rmguard_wrapper_xargs_literal_target_denied(self, hook):
        """`xargs rm .scratchpad/x` with a literal target must be denied."""
        payload = make_bash_payload("xargs rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_rmguard_wrapper_xargs_leading_flag_denied(self, hook):
        """`xargs -n1 rm .scratchpad/x` — xargs's own leading flag is skipped too."""
        payload = make_bash_payload("xargs -n1 rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_rmguard_wrapper_for_loop_do_denied(self, hook):
        """A for-loop's `do rm <literal target>` segment must be denied."""
        payload = make_bash_payload("for f in x; do rm .scratchpad/foo.md; done")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_rmguard_wrapper_subshell_denied(self, hook):
        """`(rm .scratchpad/x)` — shlex-attached leading paren must be stripped."""
        payload = make_bash_payload("(rm .scratchpad/foo.md)")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_rmguard_wrapper_brace_group_denied(self, hook):
        """`{ rm .scratchpad/x; }` — standalone leading brace must be stripped."""
        payload = make_bash_payload("{ rm .scratchpad/foo.md; }")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_rmguard_wrapper_env_recursive_denied(self, hook):
        """A wrapped recursive rm (env rm -rf ...) must hit the recursive branch."""
        payload = make_bash_payload("env rm -rf .scratchpad")
        result = run_hook_main(hook, payload)
        assert_denied(result, "blast radius")

    # --- Allow-side: the false-positive guard and pre-existing allows survive ---

    def test_rmguard_wrapper_command_dash_v_allowed(self, hook):
        """`command -v rm` is a lookup, not a deletion — must remain allowed."""
        payload = make_bash_payload("command -v rm")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`command -v rm` must not be denied"

    def test_rmguard_wrapper_command_dash_V_allowed(self, hook):
        """`command -V rm` is also a lookup — must remain allowed."""
        payload = make_bash_payload("command -V rm")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`command -V rm` must not be denied"

    def test_rmguard_wrapper_git_rm_allowed(self, hook):
        """`git rm --cached foo.py` must remain allowed — not the coreutils rm."""
        payload = make_bash_payload("git rm --cached foo.py")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`git rm` must not be denied"

    def test_rmguard_wrapper_npm_rm_allowed(self, hook):
        """`npm rm some-package` must remain allowed — not the coreutils rm."""
        payload = make_bash_payload("npm rm some-package")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`npm rm` must not be denied"

    def test_rmguard_wrapper_rmdir_allowed(self, hook):
        """`rmdir .scratchpad/emptydir` must remain allowed — distinct token from `rm`."""
        payload = make_bash_payload("rmdir .scratchpad/emptydir")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`rmdir` must not be denied"


# ---------------------------------------------------------------------------
# Tests: wrapper's own flags no longer hide the real command (card #3550)
# ---------------------------------------------------------------------------

class TestRmGuardWrapperOwnFlags:
    """Tests for _strip_command_wrappers handling of `command`'s and `env`'s
    OWN flags, closing the gap GitHub issue #29 (and the security review at
    .scratchpad/3541-swe-security.md §2 F3) documented: `command -p rm ...`
    and `env -u VARNAME rm ...` previously evaded detection because only
    `command -v`/`-V` and env's VAR=VAL assignment tokens were special-cased.

    Every test name below carries 'wrapper_own_flags' per card instructions.
    """

    # --- Deny-side: flags that do NOT turn the wrapper into a lookup ---

    def test_wrapper_own_flags_command_dash_p_denied(self, hook):
        """`command -p rm .scratchpad/x` — command's own -p flag must be
        skipped, not mistaken for the real command."""
        payload = make_bash_payload("command -p rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_wrapper_own_flags_env_dash_u_denied(self, hook):
        """`env -u VARNAME rm .scratchpad/x` — env's own -u flag AND its
        separate-token argument (VARNAME) must both be skipped."""
        payload = make_bash_payload("env -u VARNAME rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_wrapper_own_flags_env_dash_C_denied(self, hook):
        """`env -C /tmp rm .scratchpad/x` — env's -C flag takes a
        separate-token DIR argument that must also be skipped."""
        payload = make_bash_payload("env -C /tmp rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_wrapper_own_flags_env_dash_i_denied(self, hook):
        """`env -i rm .scratchpad/x` — env's no-arg -i flag must be skipped."""
        payload = make_bash_payload("env -i rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_wrapper_own_flags_env_attached_value_denied(self, hook):
        """`env -uVARNAME rm .scratchpad/x` — an attached-value short flag
        (no space before the value) must be skipped as a single token."""
        payload = make_bash_payload("env -uVARNAME rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_wrapper_own_flags_env_long_flag_denied(self, hook):
        """`env --ignore-environment rm .scratchpad/x` — env's long-form
        flags must be skipped too, not just the short forms."""
        payload = make_bash_payload("env --ignore-environment rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_wrapper_own_flags_env_bare_dash_denied(self, hook):
        """`env - rm .scratchpad/x` — env's bare `-` (implies -i) must be
        skipped as a single token."""
        payload = make_bash_payload("env - rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_wrapper_own_flags_env_recursive_via_dash_u_denied(self, hook):
        """A recursive rm hidden behind env's -u flag must still hit the
        recursive branch, not just the scratchpad branch."""
        payload = make_bash_payload("env -u VARNAME rm -rf .scratchpad")
        result = run_hook_main(hook, payload)
        assert_denied(result, "blast radius")

    # --- Allow-side: the existing lookup guard and unrelated wrappers survive ---

    def test_wrapper_own_flags_command_dash_p_dash_v_lookup_allowed(self, hook):
        """`command -p -v rm` combines command's own -p with -v — still a
        lookup, must remain allowed."""
        payload = make_bash_payload("command -p -v rm")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`command -p -v rm` (lookup) must not be denied"

    def test_wrapper_own_flags_command_dash_v_dash_p_lookup_allowed(self, hook):
        """`command -v -p rm` — -v ordered before -p — is still a lookup."""
        payload = make_bash_payload("command -v -p rm")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`command -v -p rm` (lookup) must not be denied"


# ---------------------------------------------------------------------------
# Tests: `command`'s p-only bundled flags no longer hide the real command
# (GitHub issue #29, card #3556)
# ---------------------------------------------------------------------------

class TestRmGuardCommandPOnlyBundle:
    """`command -pp rm ...` / `command -ppp rm ...` — a bundle whose
    characters are ALL `p` — must be stripped the same way repeated exact
    `-p` tokens already were. Confirmed live against real bash:
    `command -pp echo hi` performs a REAL invocation (prints `hi`, rc=0),
    unlike a `v`/`V`-containing bundle, which stays lookup-only.
    """

    # --- Deny-side: a p-only bundle must not hide the real `rm` ---

    def test_command_p_only_bundle_double_p_scratchpad_denied(self, hook):
        """`command -pp rm .scratchpad/x` — bundled `-pp` must be skipped,
        landing the guard on the real `rm` target."""
        payload = make_bash_payload("command -pp rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_command_p_only_bundle_triple_p_scratchpad_denied(self, hook):
        """`command -ppp rm .scratchpad/x` — same as above with a
        three-`p` bundle."""
        payload = make_bash_payload("command -ppp rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_command_p_only_bundle_recursive_denied(self, hook):
        """`command -pp rm -rf .scratchpad` — the p-only bundle must not
        hide a recursive whole-directory delete either."""
        payload = make_bash_payload("command -pp rm -rf .scratchpad")
        result = run_hook_main(hook, payload)
        assert_denied(result, "blast radius")

    # --- Allow-side: lookups and unrelated commands survive ---

    def test_command_p_only_bundle_ls_allowed(self, hook):
        """`command -pp ls -la` — a p-only bundle in front of a non-`rm`
        command remains allowed."""
        payload = make_bash_payload("command -pp ls -la")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`command -pp ls -la` must not be denied"

    def test_command_p_only_bundle_with_v_lookup_allowed(self, hook):
        """`command -ppv rm` — a bundle that ALSO contains `v` is
        inherently a lookup and must remain allowed, even though it packs
        multiple `p` characters with the `v`."""
        payload = make_bash_payload("command -ppv rm")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`command -ppv rm` (lookup) must not be denied"

    def test_command_dash_v_lookup_still_allowed(self, hook):
        """`command -v rm` — the pre-existing unbundled lookup case must
        survive the p-only bundle fix unchanged."""
        payload = make_bash_payload("command -v rm")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`command -v rm` (lookup) must not be denied"

    def test_command_dash_V_lookup_still_allowed(self, hook):
        """`command -V rm` — same as above for the uppercase `-V` form."""
        payload = make_bash_payload("command -V rm")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`command -V rm` (lookup) must not be denied"


# ---------------------------------------------------------------------------
# Tests: `env`'s bundled short-flag clusters no longer hide the real command
# (GitHub issue #44, card #3560; original fix landed in commit 7b7f61d)
# ---------------------------------------------------------------------------

class TestRmGuardEnvBundledCluster:
    """`env -ui rm ...` / `env -ia FOO rm ...` / `env -i0u FOO rm -rf ...` —
    a bundled short-flag cluster on `env` must not hide the real command
    behind it. GNU env genuinely parses these as bundles (confirmed against
    the real binary: `env -iu FOO echo x` and `env -iuFOO echo x` both ran
    `echo x`, GNU coreutils 9.8). Pre-fix, `_strip_command_wrappers` removed
    only the leading `env` token and any `VAR=VAL` assignment tokens after
    it — a flag cluster like `-ui` or `-i0u` was left as `seg[0]`, which is
    never `rm`, so the guard fell through to ALLOW regardless of what the
    cluster was hiding.
    """

    # --- Deny-side: a bundled cluster must not hide the real `rm` ---

    def test_env_bundle_ui_scratchpad_denied(self, hook):
        """`env -ui rm .scratchpad/foo.md` — `u` is visited first, at index 0
        of the cluster; `u` takes an arg, so the remaining char `i` is
        consumed as `u`'s attached argument value rather than being
        processed as its own no-arg flag; the whole cluster token is
        discarded and the guard lands on the real `rm`."""
        payload = make_bash_payload("env -ui rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_env_bundle_ia_scratchpad_denied(self, hook):
        """`env -ia FOO rm .scratchpad/foo.md` — arg-taking `-a` is last in
        the cluster with nothing attached, so it consumes the separate next
        token (`FOO`) as its argument, and the guard lands on the real
        `rm` two tokens later."""
        payload = make_bash_payload("env -ia FOO rm .scratchpad/foo.md")
        result = run_hook_main(hook, payload)
        assert_denied(result, "auto-pruned")

    def test_env_bundle_i0u_recursive_denied(self, hook):
        """`env -i0u FOO rm -rf .scratchpad` — a three-character cluster
        (`i`, `0`, then arg-taking `u` last) must not hide a recursive
        whole-directory delete."""
        payload = make_bash_payload("env -i0u FOO rm -rf .scratchpad")
        result = run_hook_main(hook, payload)
        assert_denied(result, "blast radius")

    def test_env_bundle_iu_attached_value_recursive_denied(self, hook):
        """`env -iuFOO rm -rf .scratchpad` — `-u`'s argument (`FOO`) is
        ATTACHED to the same token, not a separate token; the whole
        `-iuFOO` token is discarded and the guard still lands on the real
        `rm -rf .scratchpad`."""
        payload = make_bash_payload("env -iuFOO rm -rf .scratchpad")
        result = run_hook_main(hook, payload)
        assert_denied(result, "blast radius")

    # --- Allow-side: unrelated commands and coincidental "rm" values survive ---

    def test_env_bundle_iu_npm_test_allowed(self, hook):
        """`env -iu FOO npm test` — a bundled cluster in front of a
        non-`rm` command remains allowed."""
        payload = make_bash_payload("env -iu FOO npm test")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`env -iu FOO npm test` must not be denied"

    def test_env_dash_a_value_literally_rm_allowed(self, hook):
        """`env -a rm /usr/bin/true` — `-a`'s argument VALUE is literally
        the word `rm`, but it is `-a`'s argument, not the invoked command
        (`/usr/bin/true` is); must not be denied."""
        payload = make_bash_payload("env -a rm /usr/bin/true")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`env -a rm /usr/bin/true` must not be denied"

    def test_env_dash_u_name_literally_rm_allowed(self, hook):
        """`env -u rm ls` — `-u`'s argument NAME is literally the word
        `rm`, but it is the variable being unset, not the invoked command
        (`ls` is); must not be denied."""
        payload = make_bash_payload("env -u rm ls")
        result = hook._validate_bash_rm_guard(payload)
        assert result is None, "`env -u rm ls` must not be denied"

