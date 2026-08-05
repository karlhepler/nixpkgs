#!/usr/bin/env python3
"""
hook-error-digest-hook: aggregates hook error logs into a short ranked digest.

PROBLEM SOLVED
==============
Four Claude Code hooks each write their own error log under ~/.claude/metrics/
via a `log_error()` helper, and nothing reads them back. One class alone
(a non-existent `transcript_path`, upstream-blocked at
anthropics/claude-code#7881) accounts for roughly a fifth of one log's lines
and is climbing over time. A digest that simply printed recent raw lines
would be dozens of near-identical entries after any session and would be
ignored within a day -- worse than no digest. This module instead groups
every line into a small number of classes and reports counts, so a latent
failure announces itself as a ranked summary instead of noise.

Card #3334 builds ONLY this module. It is deliberately NOT wired into any
hook event in modules/claude/default.nix -- that is a separate, later card,
so this module can be verified in isolation first. See run_digest() /
format_digest() for the pure aggregation logic; main() is a thin, unwired
SessionStart-shaped entry point provided for that future wiring card to call
directly, matching this repo's other *-hook.py SessionStart hooks (see
skill-autoload-hook.py OUTPUT FORMAT) without requiring changes to this file.

SOURCES
=======
All four hook error logs are modeled uniformly via one per-source config
table in build_sources() -- not a subset. Two of the four have never written
a line as of this writing. They are still included: excluding a source
because it happens to be empty today would mean this module needs a code
change the day it starts firing, which is exactly the blind spot this module
exists to close. A missing log file is "zero findings this run", never a
structural absence or an error -- see Source.fetch / _make_log_fetch, which
checks Path.exists() before every read with no special-case branch.

SOURCE ABSTRACTION
==================
Every source is modeled uniformly as a `Source` (name, kind, fetch, classify,
has_watermark), aggregated by ONE shared loop in run_digest() that does not
know or care whether a source is a log file or something else. The
`has_watermark` field is OPTIONAL per source (defaults to True) precisely so
a future source with no watermark at all -- e.g. a live "stranded kanban
card" board-state query, which has nothing to persist an {inode, offset}
pair against -- can be added later as pure config, with zero changes to the
watermark/rotation code path. That board-state source is intentionally not
built here (out of scope for this card).

CLASSIFICATION
==============
Class key = matched-classifier label, chosen from an ordered list of
hand-curated regexes per source, with a generic fallback so no non-blank
line is ever silently dropped -- every non-blank line lands in a class
bucket, and every source's raw line count is fully accounted for across
class_counts, blank_lines, and skipped_lines combined. Grouping by exact
line cannot work: every log_error() call site across all four hooks
interpolates a path, session id, exit code, or card number directly into
the message, so exact-line grouping would produce one "class" per
occurrence.

Blank and whitespace-only lines carry no classifiable content, so they are
never handed to a classifier; they are instead counted per source in
DigestResult.blank_lines rather than being forced into an arbitrary bucket.
In practice a blank line can only arise from a partial or interrupted
write -- every log_error() call site writes a non-empty, timestamp-prefixed
message -- so a nonzero blank_lines count is itself a useful signal: it
lines up with exactly the truncated-write condition _save_state()'s atomic
write (below) is designed to avoid on the state side. See run_digest() for
the accounting and format_digest() for how a nonzero count is surfaced.

Fallback labels may contain a raw message-content prefix, deliberately.
When a line matches no curated classifier and the fallback heuristic finds
no clean colon-delimited label boundary (see _fallback_classify()), the
label is "other: <first 60 chars>" of the raw message -- which can include
a path fragment, session id, or exit code. This is intentional, not an
oversight: the fallback label is the operator's only signal that an
uncurated class of error exists, so they can add a curated classifier for
it (see _HOT_LOG_CLASSIFIERS). Redacting it would remove the digest's only
discovery mechanism for new failure classes. On this single-operator
machine the paths/session ids are the operator's own -- nothing here
crosses a confidentiality boundary to a different party.

WATERMARK
=========
Per-log {inode, byte_offset} pairs persisted in
~/.claude/metrics/hook-log-consumer-state.json. On inode change (rotation
occurred -- see kanban-subagent-stop-hook.py _rotate_log_if_needed(), which
renames path -> path.1, keeping exactly one backup generation), this module
checks whether path.1's inode matches the *stored* inode; if so, it reads
that file's tail from the stored offset once, then resets to offset 0
against the new current file. This recovers exactly ONE rotation generation
-- if two rotations happen between two runs, the middle generation is
silently and permanently lost, because the rotation logic itself only keeps
one backup. Bounded and accepted, not solved here (see _make_log_fetch).

CAPS
====
Two independent caps, because a runaway class's *count* growing large is a
different risk from the *number of distinct classes* growing large:
  1. Per-run processing cap (PER_RUN_LINE_CAP): classify at most the most
     recent 5,000 lines per source per run; the watermark still advances to
     true end-of-file regardless, so skipped lines are never reprocessed.
  2. Report-shape cap (REPORT_CLASS_CAP): at most the top 10 classes by count
     across ALL sources combined, descending; the rest roll into one
     "N more classes, M more lines" line.

OUTPUT FORMAT (once wired as a SessionStart hook)
==================================================
  {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}
On no findings: no stdout, exit 0.
On error: no stdout, exit 0 (fail open -- never break SessionStart).
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATE_FILENAME = "hook-log-consumer-state.json"

# Per-run processing cap: classify at most this many of the newest lines per
# source per run. The watermark always advances to true EOF regardless of
# this cap -- skipped older lines are never reprocessed on a later run.
PER_RUN_LINE_CAP = 5000

# Report-shape cap: at most this many classes (by count, descending, across
# all sources combined) are shown individually; the rest are rolled into one
# "N more classes, M more lines" summary line.
REPORT_CLASS_CAP = 10

# The four hook error logs this module aggregates, uniformly, via one
# config table. Two have never written a line as of this writing -- included
# anyway; see module docstring § SOURCES.
_LOG_FILENAMES = (
    "kanban-subagent-stop-hook-errors.log",
    "kanban-pretool-hook-errors.log",
    "orphan-agent-tracker-hook-errors.log",
    "claude-kanban-transition-hook-errors.log",
)

# Hand-curated classifiers for the hottest log (kanban-subagent-stop-hook),
# matched in order against the message body after the "[timestamp] " prefix
# is stripped. First match wins; anything unmatched falls through to
# _fallback_classify(). Sourced from kanban-subagent-stop-hook.py's own
# log_error() call sites (see .scratchpad/log-consumer-design.md for the
# line-by-line citations this list was built from).
_HOT_LOG_CLASSIFIERS: list[tuple[str, "re.Pattern[str]"]] = [
    ("transcript-path-missing", re.compile(r"non-empty transcript_path that does not exist")),
    ("unhandled-exception", re.compile(r"^Unhandled exception:")),
    ("json-decode-error", re.compile(r"JSON decode error:")),
    ("kanban-done-nonzero-exit", re.compile(r"kanban done exit \d+:")),
    ("kanban-cli-not-found", re.compile(r"kanban CLI not found in PATH")),
    ("kanban-command-timeout", re.compile(r"kanban .+ timed out after \d+s")),
]

# Per-log-filename curated classifier lists. The other three logs have no
# curated classifiers today -- every line there resolves via the generic
# fallback. That is fine: the fallback guarantees no line is ever silently
# dropped, and curated entries can be added here later without touching
# anything else in this module.
_CURATED_CLASSIFIERS_BY_FILENAME: dict[str, list[tuple[str, "re.Pattern[str]"]]] = {
    "kanban-subagent-stop-hook-errors.log": _HOT_LOG_CLASSIFIERS,
    "kanban-pretool-hook-errors.log": [],
    "orphan-agent-tracker-hook-errors.log": [],
    "claude-kanban-transition-hook-errors.log": [],
}

_TIMESTAMP_PREFIX = re.compile(r'^\[[^\]]*\]\s*')


# ---------------------------------------------------------------------------
# Source abstraction
# ---------------------------------------------------------------------------


@dataclass
class Source:
    """One aggregatable source: a log file today, something else later.

    has_watermark is OPTIONAL (defaults True) so a future source with no
    persisted position at all -- e.g. a live board-state query -- can set it
    False and be aggregated by the exact same loop with zero changes to the
    watermark/rotation code path.
    """

    name: str
    kind: str
    fetch: Callable[[dict], "tuple[list[str], int]"]
    classify: Callable[[str], str]
    has_watermark: bool = True


@dataclass
class DigestResult:
    """Result of one aggregation run, ready for format_digest() to render."""

    class_counts: dict[str, int] = field(default_factory=dict)
    top_classes: list[tuple[str, int]] = field(default_factory=list)
    more_classes_count: int = 0
    more_lines_count: int = 0
    skipped_lines: dict[str, int] = field(default_factory=dict)
    # Per-source count of blank/whitespace-only raw lines seen this run.
    # These never reach classify() (see run_digest) -- a nonzero count is a
    # diagnostic signal of a partial/interrupted write, not an error.
    blank_lines: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _strip_timestamp(line: str) -> str:
    """Strip a leading '[timestamp] ' prefix, matching log_error()'s format."""
    return _TIMESTAMP_PREFIX.sub('', line, count=1)


def _fallback_classify(message: str) -> str:
    """Generic classifier used when no curated regex matches.

    Takes the substring up to and including the first ':' if one appears
    before the first digit, quote, or '/' character; truncates to 60 chars.
    Anything with no such colon buckets as "other: <first 60 chars>". This
    guarantees every non-blank line lands in exactly one bucket -- curated
    or fallback -- so no line is ever silently dropped.

    The "other: <raw prefix>" bucket deliberately surfaces raw message
    content (which can include a path, session id, or exit code) rather
    than a sanitized placeholder -- see module docstring § CLASSIFICATION
    for why: it is the operator's only way to notice an uncurated failure
    class and add a curated classifier for it.
    """
    colon_idx = message.find(':')
    stop_idx = -1
    for i, ch in enumerate(message):
        if ch.isdigit() or ch in ('"', "'", '/'):
            stop_idx = i
            break
    if colon_idx != -1 and (stop_idx == -1 or colon_idx < stop_idx):
        label = message[:colon_idx + 1]
    else:
        label = f"other: {message}"
    return label[:60]


def make_log_classifier(
    curated: list[tuple[str, "re.Pattern[str]"]],
) -> Callable[[str], str]:
    """Build a classify() function for a log source from its curated list."""

    def classify(line: str) -> str:
        message = _strip_timestamp(line)
        for label, pattern in curated:
            if pattern.search(message):
                return label
        return _fallback_classify(message)

    return classify


# ---------------------------------------------------------------------------
# Log fetch (watermark + rotation recovery)
# ---------------------------------------------------------------------------


def _make_log_fetch(path: Path, source_name: str) -> Callable[[dict], "tuple[list[str], int]"]:
    """Build a fetch() closure for one log-file source.

    fetch(state) reads only the bytes appended since the last run (per the
    persisted {inode, offset} watermark in `state[source_name]`), applies the
    per-run line cap, and mutates `state[source_name]` in place to record the
    new watermark. Returns (lines_to_classify, skipped_count).

    Missing file -> ([], 0), never an error. Path.exists() is checked before
    every read; there is no special-case branch for "log never existed" vs.
    "log existed and was truncated" -- both simply see no prior watermark
    that matches, and everything downstream falls out of the same logic.
    """

    def fetch(state: dict) -> "tuple[list[str], int]":
        if not path.exists():
            return [], 0

        try:
            current_stat = path.stat()
        except OSError:
            return [], 0

        entry = state.get(source_name, {})
        stored_inode = entry.get("inode")
        stored_offset = entry.get("offset", 0)
        current_inode = current_stat.st_ino

        lines: list[str] = []

        if stored_inode is not None and stored_inode != current_inode:
            # Rotation likely occurred. Rotation logic (see
            # kanban-subagent-stop-hook.py _rotate_log_if_needed) renames
            # path -> path.1 and keeps exactly ONE backup generation -- the
            # next rotation overwrites path.1 rather than chaining to path.2.
            # So this recovers exactly one rotation generation: if two
            # rotations happen between two consumer runs, the middle
            # generation's lines were already overwritten before we ever
            # got to read them, and are silently and permanently lost.
            # Bounded and accepted, not solved here.
            rotated_path = path.with_suffix(path.suffix + ".1")
            if rotated_path.exists():
                try:
                    rotated_stat = rotated_path.stat()
                    if rotated_stat.st_ino == stored_inode:
                        with open(rotated_path, "rb") as fh:
                            fh.seek(stored_offset)
                            tail = fh.read()
                        lines.extend(tail.decode("utf-8", errors="replace").splitlines())
                except OSError:
                    pass
            stored_offset = 0

        try:
            with open(path, "rb") as fh:
                fh.seek(stored_offset)
                new_bytes = fh.read()
            lines.extend(new_bytes.decode("utf-8", errors="replace").splitlines())
        except OSError:
            pass

        skipped = 0
        if len(lines) > PER_RUN_LINE_CAP:
            skipped = len(lines) - PER_RUN_LINE_CAP
            # Keep the most recent PER_RUN_LINE_CAP lines; the watermark
            # still advances to true EOF below regardless of this cap, so
            # the skipped older lines are never reprocessed on a later run.
            lines = lines[-PER_RUN_LINE_CAP:]

        state[source_name] = {"inode": current_inode, "offset": current_stat.st_size}
        return lines, skipped

    return fetch


# ---------------------------------------------------------------------------
# Source construction
# ---------------------------------------------------------------------------


def build_sources(metrics_dir: Path) -> list[Source]:
    """Build the uniform list of Sources for all four hook error logs.

    All four are configured identically via this one table -- including the
    two that have never written a line -- so no source needs a code change
    the day it starts firing.
    """
    sources: list[Source] = []
    for filename in _LOG_FILENAMES:
        path = metrics_dir / filename
        curated = _CURATED_CLASSIFIERS_BY_FILENAME.get(filename, [])
        sources.append(
            Source(
                name=filename,
                kind="log",
                fetch=_make_log_fetch(path, filename),
                classify=make_log_classifier(curated),
                has_watermark=True,
            )
        )
    return sources


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def _load_state(state_path: Path) -> dict:
    try:
        if state_path.exists():
            return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state_path: Path, state: dict) -> None:
    """Write state atomically: write to a sibling temp file, then os.replace()
    it onto state_path. os.replace() is atomic on POSIX, so a process kill
    (hook timeout) or a disk-full mid-write can only ever leave the OLD
    state file intact or the NEW one fully written -- never a truncated
    partial write. (If _load_state() ever does see a corrupt file -- e.g.
    from a filesystem that doesn't honor the atomicity guarantee -- its own
    broad except already treats that as empty state; this just removes the
    ordinary case that would produce one.)
    """
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp_path, state_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def run_digest(sources: Iterable[Source], state_path: Path) -> DigestResult:
    """Run one aggregation pass over all sources. Pure aside from I/O at the
    given state_path and whatever each source's own fetch() touches.

    Sources with has_watermark=False are handed an empty, throwaway state
    dict and nothing they do is persisted -- this is what makes the
    watermark field genuinely optional per source rather than a mandatory
    part of the Source contract.
    """
    persisted_state = _load_state(state_path)
    class_counts: dict[str, int] = {}
    skipped_lines: dict[str, int] = {}
    blank_lines: dict[str, int] = {}
    watermark_dirty = False

    for source in sources:
        if source.has_watermark:
            raw_lines, skipped = source.fetch(persisted_state)
            watermark_dirty = True
        else:
            raw_lines, skipped = source.fetch({})

        if skipped:
            skipped_lines[source.name] = skipped

        for line in raw_lines:
            if not line.strip():
                # Blank/whitespace-only lines carry no classifiable
                # content -- counted here rather than classified or
                # silently discarded. See module docstring §
                # CLASSIFICATION for why a nonzero count is a signal, not
                # noise.
                blank_lines[source.name] = blank_lines.get(source.name, 0) + 1
                continue
            label = source.classify(line)
            class_counts[label] = class_counts.get(label, 0) + 1

    if watermark_dirty:
        _save_state(state_path, persisted_state)

    sorted_classes = sorted(class_counts.items(), key=lambda kv: kv[1], reverse=True)
    top = sorted_classes[:REPORT_CLASS_CAP]
    rest = sorted_classes[REPORT_CLASS_CAP:]

    return DigestResult(
        class_counts=class_counts,
        top_classes=top,
        more_classes_count=len(rest),
        more_lines_count=sum(count for _, count in rest),
        skipped_lines=skipped_lines,
        blank_lines=blank_lines,
    )


def format_digest(result: DigestResult) -> str:
    """Render a DigestResult as a short, human-readable text block."""
    if not result.class_counts:
        return ""

    lines = ["Hook error digest:"]
    for label, count in result.top_classes:
        lines.append(f"  {count:>5}  {label}")
    if result.more_classes_count:
        lines.append(
            f"  {result.more_classes_count} more classes, {result.more_lines_count} more lines "
            "(see log files under ~/.claude/metrics/ directly)"
        )
    for source_name, skipped in sorted(result.skipped_lines.items()):
        lines.append(f"  [{source_name}] {skipped} older lines skipped this run (watermark advanced)")
    for source_name, blank in sorted(result.blank_lines.items()):
        lines.append(f"  [{source_name}] {blank} blank/whitespace-only lines this run (not classified)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point (unwired -- see module docstring)
# ---------------------------------------------------------------------------


def main() -> None:
    """Unwired SessionStart-shaped entry point.

    Not registered in any hooks.SessionStart list in default.nix as of this
    card -- a later card wires it in. Kept fail-open and silent-by-default so
    it is safe to invoke manually or wire in later without surprises.
    """
    try:
        sys.stdin.read()
    except Exception:
        pass

    try:
        metrics_dir = Path.home() / ".claude" / "metrics"
        state_path = metrics_dir / STATE_FILENAME
        sources = build_sources(metrics_dir)
        result = run_digest(sources, state_path)
        context = format_digest(result)
    except Exception:
        return

    if not context:
        return

    try:
        # stdout can fail mid-write (e.g. BrokenPipeError/SIGPIPE if the
        # hook runner closes or doesn't fully drain the child's stdout
        # pipe) -- a real, reachable failure mode for any subprocess-based
        # hook, not a hypothetical one. Swallowing it here means "no digest
        # this run", which is exactly what the module docstring's "On
        # error: no stdout, exit 0 (fail open)" guarantee prescribes.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))
    except Exception:
        pass


if __name__ == "__main__":
    main()
