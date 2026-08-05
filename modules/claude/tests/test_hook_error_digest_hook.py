"""
Tests for modules/claude/hook-error-digest-hook.py.

Covered paths:
- Aggregation correctness against a synthetic fixture with a KNOWN mix of
  classes (curated + fallback) -- asserts exact counts and exact class keys,
  not just "it ran without raising".
- A missing source log file yields zero findings, never an error.
- The report-shape cap (REPORT_CLASS_CAP) actually truncates when given more
  than 10 classes, rolling the rest into one summary line.
- The per-run line-processing cap (PER_RUN_LINE_CAP) skips older lines and
  still advances the watermark to true EOF.
- The watermark advances after a run and is not reprocessed on the next run.
- Log rotation recovery reads the one preserved backup generation.
- has_watermark=False sources are aggregated without persisting any state
  (proves the watermark field is genuinely optional per source).

All log/state files used here live under tmp_path -- the real
~/.claude/metrics/ files and the real state file are never read or written.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

_HOOK_PATH = Path(__file__).parent.parent / "hook-error-digest-hook.py"


def load_hook():
    """Import hook-error-digest-hook.py as a module (hyphenated filename)."""
    spec = importlib.util.spec_from_file_location("hook_error_digest_hook", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    return load_hook()


def _write_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(f"[2026-08-05T00:00:00Z] {line}\n")


# ---------------------------------------------------------------------------
# Aggregation correctness (the test that matters)
# ---------------------------------------------------------------------------


class TestAggregationCorrectness:
    def test_known_mix_of_classes_produces_exact_counts(self, hook, tmp_path):
        """5 transcript-path-missing + 3 unhandled-exception + 2 fallback-only
        lines must classify into exactly those three keys with exact counts.
        """
        metrics_dir = tmp_path / "metrics"
        log_path = metrics_dir / "kanban-subagent-stop-hook-errors.log"

        lines = (
            ["Anti-gaming check skipped: non-empty transcript_path that does not exist on disk"] * 5
            + ["Unhandled exception: boom"] * 3
            + ["totally unclassifiable line with no colon before a digit 123"] * 2
        )
        _write_log(log_path, lines)

        sources = hook.build_sources(metrics_dir)
        # Isolate to just the one populated source for this assertion.
        target = [s for s in sources if s.name == "kanban-subagent-stop-hook-errors.log"]

        state_path = tmp_path / "state.json"
        result = hook.run_digest(target, state_path)

        expected_fallback_label = ("other: " + "totally unclassifiable line with no colon before a digit 123")[:60]
        assert result.class_counts == {
            "transcript-path-missing": 5,
            "unhandled-exception": 3,
            expected_fallback_label: 2,
        }

    def test_fallback_classifier_takes_prefix_up_to_first_colon(self, hook):
        message = "detect_criteria_gaming: failed to read transcript"
        assert hook._fallback_classify(message) == "detect_criteria_gaming:"

    def test_fallback_classifier_other_bucket_when_no_qualifying_colon(self, hook):
        # No ':' character appears anywhere in the message -> no qualifying
        # colon -> "other: ..." bucket. (This fixture has no colon at all;
        # see the next test for the distinct "colon exists but appears
        # after a digit" branch.)
        message = "exit 137 with no colon before that number"
        label = hook._fallback_classify(message)
        assert label.startswith("other: ")
        assert len(label) <= 60

    def test_fallback_classifier_other_bucket_when_colon_appears_after_digit(self, hook):
        # A ':' exists in the message, but a digit ('1' in '#123') appears
        # before it -> the colon does not qualify as a clean label boundary
        # -> "other: <first 60 chars>" rather than truncating at the colon.
        # Mirrors a real log_error() call-site shape (card number ahead of
        # the first colon), e.g. kanban-subagent-stop-hook.py's
        # f"kanban show #{card_number} failed (exit {rc}): {stderr}".
        message = "kanban show #123: failed (exit 1): stderr text"
        label = hook._fallback_classify(message)
        assert label == ("other: " + message)[:60]

    def test_curated_classifier_takes_priority_over_fallback(self, hook):
        classify = hook.make_log_classifier(hook._HOT_LOG_CLASSIFIERS)
        line = "[2026-08-05T00:00:00Z] kanban done exit 1: card not found"
        assert classify(line) == "kanban-done-nonzero-exit"


# ---------------------------------------------------------------------------
# Blank/whitespace-only lines are counted, not silently dropped
# ---------------------------------------------------------------------------


class TestBlankLinesAreCounted:
    def test_blank_and_whitespace_only_lines_are_counted_per_source(self, hook, tmp_path):
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        log_path = metrics_dir / "kanban-subagent-stop-hook-errors.log"

        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("[2026-08-05T00:00:00Z] real-class: one\n")
            fh.write("\n")
            fh.write("   \n")
            fh.write("[2026-08-05T00:00:00Z] real-class: two\n")

        sources = hook.build_sources(metrics_dir)
        target = [s for s in sources if s.name == "kanban-subagent-stop-hook-errors.log"]
        state_path = tmp_path / "state.json"

        result = hook.run_digest(target, state_path)

        # The two real lines classify normally; the blank and whitespace-only
        # lines are neither classified nor skipped -- they land in
        # blank_lines instead, so every raw line is accounted for somewhere.
        assert result.class_counts == {"real-class:": 2}
        assert result.blank_lines == {"kanban-subagent-stop-hook-errors.log": 2}
        assert result.skipped_lines == {}

        digest_text = hook.format_digest(result)
        assert "2 blank/whitespace-only lines this run" in digest_text


# ---------------------------------------------------------------------------
# Missing source file
# ---------------------------------------------------------------------------


class TestMissingSourceFile:
    def test_missing_log_file_yields_zero_findings_not_an_error(self, hook, tmp_path):
        metrics_dir = tmp_path / "metrics"  # never created
        sources = hook.build_sources(metrics_dir)
        state_path = tmp_path / "state.json"

        result = hook.run_digest(sources, state_path)

        assert result.class_counts == {}
        assert result.skipped_lines == {}

    def test_all_four_sources_configured_even_when_absent(self, hook, tmp_path):
        metrics_dir = tmp_path / "metrics"
        sources = hook.build_sources(metrics_dir)
        names = {s.name for s in sources}
        assert names == {
            "kanban-subagent-stop-hook-errors.log",
            "kanban-pretool-hook-errors.log",
            "orphan-agent-tracker-hook-errors.log",
            "claude-kanban-transition-hook-errors.log",
        }


# ---------------------------------------------------------------------------
# Report-shape cap
# ---------------------------------------------------------------------------


class TestReportShapeCap:
    def test_more_than_ten_classes_are_truncated_to_top_ten(self, hook, tmp_path):
        metrics_dir = tmp_path / "metrics"
        log_path = metrics_dir / "kanban-pretool-hook-errors.log"

        # 13 distinct fallback classes, each with a distinct, descending count
        # so ranking is unambiguous. Use distinct first-words so the fallback
        # classifier produces 13 distinct class keys.
        lines = []
        for i in range(13):
            count = 13 - i  # 13, 12, 11, ..., 1
            label_word = f"class{i:02d}"
            lines.extend([f"{label_word}: some message body"] * count)
        _write_log(log_path, lines)

        sources = hook.build_sources(metrics_dir)
        target = [s for s in sources if s.name == "kanban-pretool-hook-errors.log"]
        state_path = tmp_path / "state.json"

        result = hook.run_digest(target, state_path)

        assert len(result.class_counts) == 13
        assert len(result.top_classes) == 10
        assert result.more_classes_count == 3
        # Rolled-up remainder is the three smallest counts: 3 + 2 + 1 = 6
        assert result.more_lines_count == 6

        digest_text = hook.format_digest(result)
        assert "3 more classes, 6 more lines" in digest_text


# ---------------------------------------------------------------------------
# Per-run line cap + watermark advancement
# ---------------------------------------------------------------------------


class TestPerRunLineCapAndWatermark:
    def test_line_cap_skips_oldest_lines_and_advances_watermark_to_eof(self, hook, tmp_path, monkeypatch):
        monkeypatch.setattr(hook, "PER_RUN_LINE_CAP", 10)

        metrics_dir = tmp_path / "metrics"
        log_path = metrics_dir / "kanban-subagent-stop-hook-errors.log"
        # 15 lines: first 5 are "old-class", last 10 are "new-class". With a
        # cap of 10, only the most recent 10 ("new-class") should classify.
        lines = ["old-class: stale"] * 5 + ["new-class: fresh"] * 10
        _write_log(log_path, lines)

        sources = hook.build_sources(metrics_dir)
        target = [s for s in sources if s.name == "kanban-subagent-stop-hook-errors.log"]
        state_path = tmp_path / "state.json"

        result = hook.run_digest(target, state_path)

        assert result.class_counts == {"new-class:": 10}
        assert result.skipped_lines == {"kanban-subagent-stop-hook-errors.log": 5}

        # Watermark must have advanced to true EOF regardless of the cap --
        # a second run against the same unchanged file finds nothing new.
        second_result = hook.run_digest(target, state_path)
        assert second_result.class_counts == {}
        assert second_result.skipped_lines == {}

    def test_watermark_persists_inode_and_offset_to_state_file(self, hook, tmp_path):
        metrics_dir = tmp_path / "metrics"
        log_path = metrics_dir / "kanban-subagent-stop-hook-errors.log"
        _write_log(log_path, ["some-class: message"])

        sources = hook.build_sources(metrics_dir)
        target = [s for s in sources if s.name == "kanban-subagent-stop-hook-errors.log"]
        state_path = tmp_path / "state.json"

        hook.run_digest(target, state_path)

        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        entry = state["kanban-subagent-stop-hook-errors.log"]
        assert entry["inode"] == os.stat(log_path).st_ino
        assert entry["offset"] == os.stat(log_path).st_size

    def test_new_lines_appended_since_last_run_are_picked_up(self, hook, tmp_path):
        metrics_dir = tmp_path / "metrics"
        log_path = metrics_dir / "kanban-subagent-stop-hook-errors.log"
        _write_log(log_path, ["first-class: one"])

        sources = hook.build_sources(metrics_dir)
        target = [s for s in sources if s.name == "kanban-subagent-stop-hook-errors.log"]
        state_path = tmp_path / "state.json"

        first = hook.run_digest(target, state_path)
        assert first.class_counts == {"first-class:": 1}

        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write("[2026-08-05T00:01:00Z] second-class: two\n")

        second = hook.run_digest(target, state_path)
        assert second.class_counts == {"second-class:": 1}


# ---------------------------------------------------------------------------
# Rotation recovery
# ---------------------------------------------------------------------------


class TestRotationRecovery:
    def test_rotation_reads_backup_tail_once_then_resets_against_new_file(self, hook, tmp_path):
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        log_path = metrics_dir / "kanban-subagent-stop-hook-errors.log"

        _write_log(log_path, ["before-rotation: one", "before-rotation: two"])

        sources = hook.build_sources(metrics_dir)
        target = [s for s in sources if s.name == "kanban-subagent-stop-hook-errors.log"]
        state_path = tmp_path / "state.json"

        first = hook.run_digest(target, state_path)
        assert first.class_counts == {"before-rotation:": 2}

        # Simulate rotation: old file (with the recorded inode) becomes
        # path.1; a brand-new, empty-then-appended file takes the old name.
        rotated_path = log_path.with_suffix(log_path.suffix + ".1")
        # Append one more line to the (soon-to-be-rotated) file before moving
        # it, to prove the tail-from-stored-offset read picks up entries
        # written between the last run and the rotation.
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write("[2026-08-05T00:02:00Z] before-rotation: three\n")
        log_path.rename(rotated_path)
        _write_log(log_path, ["after-rotation: four"])

        second = hook.run_digest(target, state_path)

        assert second.class_counts == {
            "before-rotation:": 1,  # the "three" line written pre-rotation
            "after-rotation:": 1,
        }


# ---------------------------------------------------------------------------
# has_watermark optionality
# ---------------------------------------------------------------------------


class TestWatermarkIsOptionalPerSource:
    def test_source_without_watermark_persists_nothing(self, hook, tmp_path):
        calls: list[dict] = []

        def fetch(state: dict) -> "tuple[list[str], int]":
            calls.append(state)
            return ["[2026-08-05T00:00:00Z] board-class: stranded card #1"], 0

        watermark_free_source = hook.Source(
            name="synthetic-board-source",
            kind="board",
            fetch=fetch,
            classify=lambda line: "stranded-card",
            has_watermark=False,
        )

        state_path = tmp_path / "state.json"
        result = hook.run_digest([watermark_free_source], state_path)

        assert result.class_counts == {"stranded-card": 1}
        # fetch() was handed an empty, throwaway dict -- not the persisted
        # state -- and no state file was ever written for this run.
        assert calls == [{}]
        assert not state_path.exists()
