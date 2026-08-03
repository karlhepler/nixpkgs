"""
Tests for claudit-hook.py Opus model-tier cost normalization.

Covers the defect where `normalize_model()` mapped an 'opus'-containing model
string against an allowlist of known-cheap version substrings ("4.5", "4.6",
"4.7", and their dash forms) and fell through to the expensive legacy
$15/$75 tier for anything not on that list — silently mis-pricing newer
releases like Opus 4.8 and Opus 5 (which actually bill at the same $5/$25
tier as Opus 4.5-4.7) at roughly 3x their real cost.

The fix inverts the check to a denylist of known LEGACY versions
(_LEGACY_OPUS_MARKERS: Opus 3, Opus 4, Opus 4.1), so an unrecognized future
Opus release defaults to the cheaper current tier instead of the expensive
legacy tier.

Covers:
- claude-opus-4-8 resolves to the current $5/$25 tier, not legacy $15/$75
- claude-opus-5 resolves to the current $5/$25 tier, not legacy $15/$75
- previously-working versions (4.5/4.6/4.7, dash and dot forms) still
  resolve to the current $5/$25 tier (regression guard)
- genuine legacy Opus releases (Opus 3, bare Opus 4, Opus 4.1) still
  resolve to the legacy $15/$75 tier (regression guard for the direction
  the inversion could break)
- a hypothetical two-digit-minor release (Opus 4.10) does not collide with
  the "opus-4-1" legacy marker, now that marker matching is anchored to a
  version boundary instead of a bare substring check (regression guard
  against recreating the original defect one version away)
"""

import importlib.util
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

_CLAUDIT_HOOK_PATH = Path(__file__).parent / "claudit-hook.py"


def load_claudit_hook():
    """Import claudit-hook.py as a module (hyphenated filename needs importlib)."""
    spec = importlib.util.spec_from_file_location("claudit_hook", _CLAUDIT_HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["claudit_hook"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def claudit_hook():
    return load_claudit_hook()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ONE_MILLION_INPUT_TOKENS = {
    "input": 1_000_000,
    "output": 0,
    "cache_read": 0,
    "cache_write": 0,
}


def cost_for_input_tokens(claudit_hook, model: str) -> float:
    """Normalize `model` and compute the cost of 1M input tokens."""
    normalized = claudit_hook.normalize_model(model)
    return claudit_hook.calculate_cost(normalized, _ONE_MILLION_INPUT_TOKENS)


# ---------------------------------------------------------------------------
# Tests: previously-mis-bucketed models now bill at the current tier
# ---------------------------------------------------------------------------

class TestNewOpusReleasesBillAtCurrentTier:
    """Opus 4.8 and Opus 5 resolve to the current $5/$25 tier, not legacy."""

    def test_opus_4_8_normalizes_to_current_tier(self, claudit_hook):
        """claude-opus-4-8 normalizes to 'opus-4', the current-tier bucket."""
        normalized = claudit_hook.normalize_model("claude-opus-4-8-20261101")
        assert normalized == "opus-4", (
            f"Expected 'opus-4' (current tier) for Opus 4.8, got {normalized!r}"
        )

    def test_opus_4_8_bills_at_current_tier_price_not_legacy(self, claudit_hook):
        """claude-opus-4-8 input-token cost matches the $5/MTok current tier."""
        cost = cost_for_input_tokens(claudit_hook, "claude-opus-4-8-20261101")
        current_tier_cost = claudit_hook.PRICING["opus-4"]["input"]
        legacy_tier_cost = claudit_hook.PRICING["opus"]["input"]
        assert cost == pytest.approx(current_tier_cost), (
            f"Expected Opus 4.8 to bill at current-tier rate {current_tier_cost}, got {cost}"
        )
        assert cost != pytest.approx(legacy_tier_cost), (
            "Opus 4.8 must not bill at the legacy $15/$75 tier rate"
        )

    def test_opus_5_normalizes_to_current_tier(self, claudit_hook):
        """claude-opus-5 normalizes to 'opus-4', the current-tier bucket."""
        normalized = claudit_hook.normalize_model("claude-opus-5-20260301")
        assert normalized == "opus-4", (
            f"Expected 'opus-4' (current tier) for Opus 5, got {normalized!r}"
        )

    def test_opus_5_bare_alias_normalizes_to_current_tier(self, claudit_hook):
        """The bare alias 'claude-opus-5' (no date suffix) also resolves to current tier."""
        normalized = claudit_hook.normalize_model("claude-opus-5")
        assert normalized == "opus-4", (
            f"Expected 'opus-4' (current tier) for bare Opus 5 alias, got {normalized!r}"
        )

    def test_opus_5_bills_at_current_tier_price_not_legacy(self, claudit_hook):
        """claude-opus-5 input-token cost matches the $5/MTok current tier."""
        cost = cost_for_input_tokens(claudit_hook, "claude-opus-5-20260301")
        current_tier_cost = claudit_hook.PRICING["opus-4"]["input"]
        legacy_tier_cost = claudit_hook.PRICING["opus"]["input"]
        assert cost == pytest.approx(current_tier_cost), (
            f"Expected Opus 5 to bill at current-tier rate {current_tier_cost}, got {cost}"
        )
        assert cost != pytest.approx(legacy_tier_cost), (
            "Opus 5 must not bill at the legacy $15/$75 tier rate"
        )


# ---------------------------------------------------------------------------
# Tests: previously-working versions still resolve correctly (no regression)
# ---------------------------------------------------------------------------

class TestPreviouslyWorkingVersionsStillCurrentTier:
    """Opus 4.5 / 4.6 / 4.7 (dash and dot forms) still resolve to the current tier."""

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-4-5-20260101",
            "claude-opus-4-6-20260201",
            "claude-opus-4-7-20260215",
            "Claude Opus 4.5",
            "Claude Opus 4.6",
            "Claude Opus 4.7",
        ],
    )
    def test_dash_and_dot_forms_normalize_to_current_tier(self, claudit_hook, model):
        normalized = claudit_hook.normalize_model(model)
        assert normalized == "opus-4", (
            f"Expected 'opus-4' (current tier) for {model!r}, got {normalized!r}"
        )


# ---------------------------------------------------------------------------
# Tests: version-boundary anchoring closes the two-digit-minor collision
# ---------------------------------------------------------------------------

class TestTwoDigitMinorDoesNotCollideWithLegacyMarker:
    """A hypothetical Opus 4.10 does not collide with the Opus 4.1 legacy marker.

    `_LEGACY_OPUS_MARKERS` matches "opus-4-1" as a substring. Without a
    version-boundary anchor, that substring is also present inside
    "claude-opus-4-10-..." (Opus 4.10) — "opus-4-1" followed by "0" —
    which would misclassify a CURRENT-tier model as legacy Opus 4.1,
    recreating the exact defect this module was fixed for, one version
    away. These tests pin the anchored-boundary fix and FAIL under the
    unanchored `marker in lower` substring check.
    """

    def test_opus_4_10_bare_normalizes_to_current_tier(self, claudit_hook):
        """Bare 'claude-opus-4-10' must not collide with the 'opus-4-1' marker."""
        normalized = claudit_hook.normalize_model("claude-opus-4-10")
        assert normalized == "opus-4", (
            f"Expected 'opus-4' (current tier) for hypothetical Opus 4.10, "
            f"got {normalized!r} — the 'opus-4-1' legacy marker must not match "
            "as an unanchored substring of 'opus-4-10'"
        )

    def test_opus_4_10_snapshot_suffixed_normalizes_to_current_tier(self, claudit_hook):
        """Snapshot-suffixed 'claude-opus-4-10-...' must not collide either."""
        normalized = claudit_hook.normalize_model("claude-opus-4-10-20270101")
        assert normalized == "opus-4", (
            f"Expected 'opus-4' (current tier) for hypothetical Opus 4.10, "
            f"got {normalized!r} — the 'opus-4-1' legacy marker must not match "
            "as an unanchored substring of 'opus-4-10-20270101'"
        )

    def test_opus_4_10_bills_at_current_tier_price_not_legacy(self, claudit_hook):
        """claude-opus-4-10 input-token cost matches the $5/MTok current tier."""
        cost = cost_for_input_tokens(claudit_hook, "claude-opus-4-10-20270101")
        current_tier_cost = claudit_hook.PRICING["opus-4"]["input"]
        legacy_tier_cost = claudit_hook.PRICING["opus"]["input"]
        assert cost == pytest.approx(current_tier_cost), (
            f"Expected Opus 4.10 to bill at current-tier rate {current_tier_cost}, got {cost}"
        )
        assert cost != pytest.approx(legacy_tier_cost), (
            "Opus 4.10 must not bill at the legacy $15/$75 tier rate"
        )


# ---------------------------------------------------------------------------
# Tests: genuine legacy Opus releases still resolve to the legacy tier
# ---------------------------------------------------------------------------

class TestGenuineLegacyOpusStillLegacyTier:
    """Opus 3 / bare Opus 4 / Opus 4.1 still resolve to the legacy $15/$75 tier.

    This is the direction the allowlist->denylist inversion could break, so
    it is pinned explicitly per model. Also covers the bare (no date suffix)
    Opus 4.1 alias, since the boundary-anchoring fix must accept both the
    bare and snapshot-suffixed forms.
    """

    def test_bare_opus_4_1_normalizes_to_legacy_tier(self, claudit_hook):
        """Bare 'claude-opus-4-1' (no date suffix) still resolves to legacy tier."""
        normalized = claudit_hook.normalize_model("claude-opus-4-1")
        assert normalized == "opus", (
            f"Expected 'opus' (legacy tier) for bare Opus 4.1, got {normalized!r}"
        )

    def test_opus_3_normalizes_to_legacy_tier(self, claudit_hook):
        normalized = claudit_hook.normalize_model("claude-3-opus-20240229")
        assert normalized == "opus", (
            f"Expected 'opus' (legacy tier) for Opus 3, got {normalized!r}"
        )

    def test_bare_opus_4_normalizes_to_legacy_tier(self, claudit_hook):
        normalized = claudit_hook.normalize_model("claude-opus-4-20250514")
        assert normalized == "opus", (
            f"Expected 'opus' (legacy tier) for bare Opus 4, got {normalized!r}"
        )

    def test_opus_4_1_normalizes_to_legacy_tier(self, claudit_hook):
        normalized = claudit_hook.normalize_model("claude-opus-4-1-20250805")
        assert normalized == "opus", (
            f"Expected 'opus' (legacy tier) for Opus 4.1, got {normalized!r}"
        )

    def test_genuine_legacy_model_bills_at_legacy_price_not_current(self, claudit_hook):
        """A genuine legacy Opus release bills at the $15/MTok legacy rate."""
        cost = cost_for_input_tokens(claudit_hook, "claude-opus-4-1-20250805")
        legacy_tier_cost = claudit_hook.PRICING["opus"]["input"]
        current_tier_cost = claudit_hook.PRICING["opus-4"]["input"]
        assert cost == pytest.approx(legacy_tier_cost), (
            f"Expected legacy Opus 4.1 to bill at legacy-tier rate {legacy_tier_cost}, got {cost}"
        )
        assert cost != pytest.approx(current_tier_cost), (
            "Legacy Opus 4.1 must not bill at the current $5/$25 tier rate"
        )


# ---------------------------------------------------------------------------
# Tests: unrelated model families are unaffected
# ---------------------------------------------------------------------------

class TestUnrelatedModelFamiliesUnaffected:
    """sonnet/haiku normalization is untouched by the Opus denylist change."""

    def test_sonnet_still_normalizes_to_sonnet(self, claudit_hook):
        assert claudit_hook.normalize_model("claude-sonnet-4-5-20260101") == "sonnet"

    def test_haiku_still_normalizes_to_haiku(self, claudit_hook):
        assert claudit_hook.normalize_model("claude-haiku-4-5-20260101") == "haiku"
