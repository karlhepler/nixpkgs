"""
Structural guard: hook tests must live in modules/claude/tests/, never at the
shallower modules/claude/ top level.

Why this exists: modules/claude/test_kanban_pretool_hook.py was a stale
duplicate of modules/claude/tests/test_kanban_pretool_hook.py, discoverable
at a SHALLOWER path than the canonical directory. A `--max-depth 1` lookup
would find the wrong copy first — and it did, once, when a coordinator cited
the fossil to an agent as "the conventions to follow," causing a second
top-level test file to be created. This guard fails loudly if any hook test
file ever reappears at the top level, instead of relying on a human to notice.

Covered paths:
- No file matching test_*_hook*.py OR test_hook*.py exists directly under
  modules/claude/ (top level only — the tests/ subdirectory is exempt and
  intentionally holds many such files). Two patterns are unioned because a
  single glob cannot express "hook as a whole word" on its own: test_*_hook*.py
  requires an underscore immediately before "hook" (catching forms like
  test_kanban_pretool_hook.py), but that same requirement means it does NOT
  match the test_hook_* prefix form (e.g. test_hook_foo.py) — there, the
  literal "test_" prefix consumes the leading underscore, leaving "hook_foo.py"
  with no "_hook" substring left to match. test_hook*.py closes that gap by
  catching "hook" at the very start of the post-"test_" portion. Together the
  two patterns match "hook" as a whole word in either position it can occur,
  while a filename that merely contains the substring "hook" — e.g. a
  hypothetical future test_webhook_client.py, which is unrelated to the Claude
  Code hook family this guard protects — is correctly ignored by both.

What this guard does NOT cover: it is purely structural — it only detects a
hook test file REAPPEARING at the top level. It cannot detect the failure
mode of CONTENT imitation: a hook test file that is correctly located inside
tests/ but contains stale or wrong assertions, later cited by a coordinator
or agent as "the conventions to follow." A correctly-placed file with wrong
content passes this guard trivially. Only location is enforced here — do not
mistake "this guard exists and passes" for "the imitation risk is solved."
"""

from pathlib import Path

_CLAUDE_MODULE_DIR = Path(__file__).parent.parent
_CANONICAL_TESTS_DIR = "modules/claude/tests/"


def _find_top_level_hook_tests(directory: Path) -> list[str]:
    """Return sorted names of hook test files directly under `directory`.

    Matches the UNION of two glob patterns so that "hook" is matched as a
    whole word:
      - test_*_hook*.py — an underscore-delimited "hook" segment anywhere
        after the "test_" prefix (e.g. test_kanban_pretool_hook.py).
      - test_hook*.py — "hook" immediately following the "test_" prefix
        (e.g. test_hook_foo.py, test_hooks_x.py). test_*_hook*.py alone
        cannot catch this form: the literal "test_" prefix consumes the
        leading underscore, leaving no "_hook" substring behind.
    Neither pattern matches a filename where "hook" is merely a substring
    of a larger word, e.g. test_webhook_client.py or test_unhook_thing.py
    — those are correctly ignored.

    Non-recursive by design (uses Path.glob, not a recursive variant) —
    recursing into a tests/ subdirectory would flag the many legitimate hook
    test suites that belong there.
    """
    matches = set(directory.glob("test_*_hook*.py")) | set(
        directory.glob("test_hook*.py")
    )
    return sorted(p.name for p in matches if p.is_file())


def test_no_hook_test_file_at_claude_top_level():
    """No test_*_hook*.py file may exist directly under modules/claude/.

    Hook tests belong exclusively in modules/claude/tests/ — this check only
    looks at direct children of modules/claude/, not the tests/ subdirectory
    itself (which legitimately contains many such files).
    """
    offenders = _find_top_level_hook_tests(_CLAUDE_MODULE_DIR)
    assert not offenders, (
        f"Found hook test file(s) at the modules/claude/ top level: {offenders}. "
        f"Hook tests belong exclusively in {_CANONICAL_TESTS_DIR} — move the "
        f"offending file(s) there instead of leaving them at the shallower path."
    )


def test_helper_flags_genuine_hook_test_file(tmp_path):
    """A genuine hook test filename is detected by the helper."""
    (tmp_path / "test_something_hook.py").touch()

    assert _find_top_level_hook_tests(tmp_path) == ["test_something_hook.py"]


def test_helper_ignores_unrelated_webhook_filename(tmp_path):
    """A filename merely containing the substring "hook" (e.g. "webhook")
    must NOT be flagged — this is the boundary Finding 1 fixes. This test
    would fail against the old, untightened test_*hook*.py pattern and
    passes against the tightened test_*_hook*.py pattern.
    """
    (tmp_path / "test_webhook_client.py").touch()

    assert _find_top_level_hook_tests(tmp_path) == []


def test_helper_flags_kanban_pretool_hook_form(tmp_path):
    """test_kanban_pretool_hook.py — the underscore-delimited "_hook" form —
    is detected by test_*_hook*.py.
    """
    (tmp_path / "test_kanban_pretool_hook.py").touch()

    assert _find_top_level_hook_tests(tmp_path) == ["test_kanban_pretool_hook.py"]


def test_helper_flags_hook_prefix_form(tmp_path):
    """test_hook_foo.py — "hook" immediately following the "test_" prefix —
    is detected by test_hook*.py. This is the case this card's fix closes:
    the literal "test_" prefix consumes the leading underscore, so what
    remains ("hook_foo.py") contains no "_hook" substring and the single
    tightened test_*_hook*.py pattern alone does NOT match here. Confirmed
    empirically: this assertion fails against test_*_hook*.py in isolation
    and passes once test_hook*.py is unioned in.
    """
    (tmp_path / "test_hook_foo.py").touch()

    assert _find_top_level_hook_tests(tmp_path) == ["test_hook_foo.py"]


def test_helper_flags_hooks_plural_prefix_form(tmp_path):
    """test_hooks_x.py — another "hook"-immediately-after-"test_" form —
    is detected by test_hook*.py for the same reason as test_hook_foo.py.
    """
    (tmp_path / "test_hooks_x.py").touch()

    assert _find_top_level_hook_tests(tmp_path) == ["test_hooks_x.py"]


def test_helper_ignores_unhook_filename(tmp_path):
    """test_unhook_thing.py contains "hook" only as part of the larger word
    "unhook" — no underscore precedes "hook" and "hook" is not immediately
    after the "test_" prefix, so neither unioned pattern matches.
    """
    (tmp_path / "test_unhook_thing.py").touch()

    assert _find_top_level_hook_tests(tmp_path) == []
