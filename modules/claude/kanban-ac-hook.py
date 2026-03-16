#!/usr/bin/env python3
"""
kanban-ac-hook: Claude Code SubagentStop hook that reads agent transcripts for
kanban markers and processes them via the kanban CLI.

Marker processing:
  - KANBAN CRITERIA CHECK <N>  → kanban criteria check <card> <N> --session <s>
  - KANBAN REVIEW              → kanban review <card> --session <s>
  - KANBAN CRITERIA PASS <N>   → kanban criteria pass <card> <N> --session <s>
  - KANBAN CRITERIA FAIL <N>   → kanban criteria fail <card> <N> --session <s>
  - KANBAN DONE                → (no-op; done is called by AC reviewer, not agent)

If KANBAN REVIEW marker is absent after agent stop, the hook checks the card
state and notifies staff engineer via a blocking response.

When KANBAN REVIEW is present, the hook launches an AC review loop:
  1. Spawns `claude -p --model haiku` with AC reviewer prompt and card context
  2. Parses stdout for KANBAN CRITERIA PASS/FAIL/DONE markers
  3. Calls kanban CLI to record each pass/fail
  4. Loops until: all criteria pass + DONE emitted, any failure, or max iterations
  5. On all pass: calls kanban done; on failure: notifies staff; on max: notifies staff
  6. Context file (.scratchpad/ac-loop-<card>.md) deleted after completion

Never exits non-zero — all errors are swallowed silently to avoid disrupting
Claude Code's hook pipeline.
"""

import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Transcript marker parser
# ---------------------------------------------------------------------------

# Supported marker patterns. Each is matched case-insensitively.
_MARKER_PATTERNS = [
    # KANBAN CRITERIA CHECK <N>
    (re.compile(r"KANBAN\s+CRITERIA\s+CHECK\s+(\d+)", re.IGNORECASE), "CRITERIA_CHECK"),
    # KANBAN CRITERIA PASS <N>
    (re.compile(r"KANBAN\s+CRITERIA\s+PASS\s+(\d+)", re.IGNORECASE), "CRITERIA_PASS"),
    # KANBAN CRITERIA FAIL <N>
    (re.compile(r"KANBAN\s+CRITERIA\s+FAIL\s+(\d+)", re.IGNORECASE), "CRITERIA_FAIL"),
    # KANBAN REVIEW (no arguments)
    (re.compile(r"KANBAN\s+REVIEW\b", re.IGNORECASE), "REVIEW"),
    # KANBAN DONE (no arguments)
    (re.compile(r"KANBAN\s+DONE\b", re.IGNORECASE), "DONE"),
]


def _strip_code_fences(text):
    """
    Remove content inside markdown code fences (``` ... ```) from text.

    Handles both plain fences (```) and language-tagged fences (```python).
    Returns text with code fence blocks replaced by empty strings.
    """
    return re.sub(r"```[\s\S]*?```", "", text)


def _extract_text_from_content_block(block):
    """
    Extract plain text from a single content block dict.

    Returns the text string if this is an assistant text block, or None if it
    should be skipped (tool_use, tool_result, thinking, or non-text blocks).
    """
    if not isinstance(block, dict):
        return None
    block_type = block.get("type", "")
    # Only process text blocks — skip tool_use, tool_result, thinking, etc.
    if block_type != "text":
        return None
    return block.get("text", "")


def _extract_assistant_text_blocks(transcript_path):
    """
    Read a JSONL transcript file and yield plain text strings from all
    assistant text blocks.

    Skips: tool_use blocks, tool_result blocks, thinking blocks, human turns.
    Only yields content from: message.role == "assistant", content[].type == "text"
    """
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                msg = entry.get("message", {})
                role = msg.get("role", "")
                if role != "assistant":
                    continue

                content = msg.get("content", "")
                if isinstance(content, str):
                    # Bare string content — treat as text
                    yield content
                elif isinstance(content, list):
                    for block in content:
                        text = _extract_text_from_content_block(block)
                        if text is not None:
                            yield text
    except Exception:
        return


def parse_markers(transcript_path):
    """
    Parse a Claude Code JSONL transcript for kanban markers.

    Extracts markers ONLY from assistant text blocks. Ignores markers inside
    markdown code fences (``` ... ```), tool_use blocks, tool_result blocks,
    and thinking blocks.

    Returns a list of dicts with keys:
      - marker_type: str  ("CRITERIA_CHECK", "CRITERIA_PASS", "CRITERIA_FAIL",
                           "REVIEW", "DONE")
      - args: list[str]   (e.g. ["3"] for CRITERIA_CHECK 3, [] for REVIEW)
      - line_index: int   (0-based index within the text block, for diagnostics)

    Unit-testable: accepts a file path, returns structured list.
    """
    found = []

    for text_block in _extract_assistant_text_blocks(transcript_path):
        # Strip code fences first so markers inside ``` ... ``` are excluded
        clean_text = _strip_code_fences(text_block)

        for line_idx, line in enumerate(clean_text.splitlines()):
            for pattern, marker_type in _MARKER_PATTERNS:
                m = pattern.search(line)
                if m:
                    args = list(m.groups())  # may be empty for REVIEW/DONE
                    found.append({
                        "marker_type": marker_type,
                        "args": args,
                        "line_index": line_idx,
                    })
                    # A line can contain at most one marker — stop after first match
                    break

    return found


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


def read_first_human_message(transcript_path):
    """
    Return the text of the first human turn in the transcript JSONL.

    The initial prompt is delivered as a human message with type == "human".
    Returns an empty string if the file cannot be read or no human turn found.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "human":
                    continue
                msg = entry.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict):
                            text = block.get("text", "")
                            if text:
                                parts.append(text)
                        elif isinstance(block, str):
                            parts.append(block)
                    return "\n".join(parts)
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Kanban helpers
# ---------------------------------------------------------------------------


def parse_card_and_session(prompt_text):
    """
    Extract card number and session id from the KANBAN CARD # pattern.

    Looks for: KANBAN CARD #<N> | Session: <session-id>
    Returns (card_number_str, session_id_str) or (None, None) if not found.
    """
    match = re.search(
        r"KANBAN CARD #(\d+)\s*\|\s*Session:\s*(\S+)",
        prompt_text,
    )
    if not match:
        return None, None
    return match.group(1), match.group(2)


def run_kanban_cli(args, timeout=25):
    """
    Run the kanban CLI with the given argument list.

    Returns (returncode, stdout, stderr). Never raises — errors are captured.
    """
    try:
        result = subprocess.run(
            ["kanban"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as exc:
        return -1, "", str(exc)


def run_kanban_status(card_number, session_id):
    """
    Run `kanban status <card> --session <session>`.

    Returns the column name string (e.g. "doing", "review", "done") or None.
    """
    rc, stdout, _ = run_kanban_cli(["status", card_number, "--session", session_id])
    if rc != 0:
        return None
    return stdout.strip() or None


# ---------------------------------------------------------------------------
# Marker processing
# ---------------------------------------------------------------------------


def process_markers(markers, card_number, session_id):
    """
    Execute kanban CLI calls for each marker in the list.

    - CRITERIA_CHECK <N>: kanban criteria check <card> <N> --session <s>
    - CRITERIA_PASS <N>:  kanban criteria pass  <card> <N> --session <s>
    - CRITERIA_FAIL <N>:  kanban criteria fail  <card> <N> --session <s>
    - REVIEW:             kanban review <card> --session <s>
    - DONE:               no-op (done is called by AC reviewer)

    NOTE: CRITERIA_PASS and CRITERIA_FAIL markers are processed from ANY agent,
    including the main agent (not just sub-agents). This allows the hook to process
    marker output from all agent types during the SubagentStop hook's initial
    transcript scan.

    Returns a list of error strings for any non-zero CLI exits.
    """
    errors = []

    for marker in markers:
        mt = marker["marker_type"]
        args = marker["args"]

        if mt == "CRITERIA_CHECK" and args:
            rc, _, stderr = run_kanban_cli(
                ["criteria", "check", card_number, args[0], "--session", session_id]
            )
            if rc != 0:
                errors.append(f"criteria check {args[0]} failed (exit {rc}): {stderr.strip()}")

        elif mt == "CRITERIA_PASS" and args:
            rc, _, stderr = run_kanban_cli(
                ["criteria", "pass", card_number, args[0], "--session", session_id]
            )
            if rc != 0:
                errors.append(f"criteria pass {args[0]} failed (exit {rc}): {stderr.strip()}")

        elif mt == "CRITERIA_FAIL" and args:
            rc, _, stderr = run_kanban_cli(
                ["criteria", "fail", card_number, args[0], "--session", session_id]
            )
            if rc != 0:
                errors.append(f"criteria fail {args[0]} failed (exit {rc}): {stderr.strip()}")

        elif mt == "REVIEW":
            rc, _, stderr = run_kanban_cli(
                ["review", card_number, "--session", session_id]
            )
            if rc != 0:
                errors.append(f"review failed (exit {rc}): {stderr.strip()}")

        elif mt == "DONE":
            # no-op: During SubagentStop hook processing (initial transcript scan),
            # KANBAN DONE markers are silently ignored. The hook only invokes kanban done
            # during the AC review loop (when KANBAN REVIEW was present), where the AC
            # reviewer's DONE marker signals successful verification. Non-AC-reviewer
            # agents emitting KANBAN DONE during normal execution have no effect — the
            # hook does not call kanban done for them, since done is the responsibility
            # of the AC review process or the staff engineer.
            pass

    return errors


def has_review_marker(markers):
    """Return True if the marker list contains a REVIEW marker."""
    return any(m["marker_type"] == "REVIEW" for m in markers)


# ---------------------------------------------------------------------------
# Block response construction
# ---------------------------------------------------------------------------

BLOCK_SENTINEL = "STOP — incomplete kanban workflow on card #"


def build_missing_review_block(card_number, session_id, column, cli_errors):
    """
    Build a blocking response when KANBAN REVIEW marker was absent.

    Includes CLI errors (if any) and the command the agent needs to run.
    """
    lines = [
        f"{BLOCK_SENTINEL}{card_number}.",
        "",
        "KANBAN REVIEW marker was not found in your transcript.",
    ]

    if cli_errors:
        lines.append("")
        lines.append("CLI errors encountered during marker processing:")
        for err in cli_errors:
            lines.append(f"  - {err}")

    if column and column not in ("review", "done"):
        lines.append("")
        lines.append("You must move the card to review before finishing:")
        lines.append(f"  kanban review {card_number} --session {session_id}")
        lines.append("")
        lines.append("Run the command above, then you may finish.")
    elif cli_errors:
        lines.append("")
        lines.append("Fix the CLI errors above and retry.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AC review loop
# ---------------------------------------------------------------------------

# Default maximum number of AC review loop iterations before giving up.
_AC_LOOP_MAX_ITERATIONS = int(os.environ.get("KANBAN_AC_LOOP_MAX_ITER", "5"))

# Scratchpad directory relative to current working directory.
_SCRATCHPAD_DIR = ".scratchpad"

# AC reviewer prompt template. Intentionally lightweight — no CLI instructions,
# no permission guards. The reviewer's sole job is to verify criteria and emit
# structured markers.
_AC_REVIEWER_PROMPT_TEMPLATE = """\
You are an acceptance criteria reviewer for kanban card #{card_number}.

Your job: read the card content below, verify each listed criterion, and emit
structured markers for each result. Do NOT run any commands, access any tools,
or take any actions outside of emitting markers.

## Card Content

{card_content}

## Pending Criteria to Verify

{pending_criteria_list}

## Previous Iteration Output (if any)

{prev_iteration_output}

## Marker Format

For each criterion, emit exactly one of:
  KANBAN CRITERIA PASS <N>   — criterion N is fully satisfied
  KANBAN CRITERIA FAIL <N>   — criterion N is NOT satisfied; briefly note why

After evaluating all criteria, emit either:
  KANBAN DONE                — all criteria passed
  (nothing more)             — if any criteria failed

Rules:
- Emit markers one per line, no surrounding text required on that line.
- Only evaluate the pending criteria listed above.
- KANBAN DONE must only appear if every pending criterion passed.
- Be concise. One sentence of reasoning per criterion is sufficient.
"""


def _scratchpad_path(card_number):
    """Return the path to the AC loop context file for the given card number."""
    return os.path.join(_SCRATCHPAD_DIR, f"ac-loop-{card_number}.md")


def _fetch_card_content(card_number, session_id):
    """
    Fetch card content via `kanban show <card> --output-style=xml`.

    Returns the full stdout string, or an empty string on failure.
    """
    rc, stdout, _ = run_kanban_cli(
        ["show", card_number, "--output-style=xml", "--session", session_id],
        timeout=25,
    )
    if rc != 0:
        return ""
    return stdout.strip()


def _fetch_criteria_list(card_number, session_id):
    """
    Return a list of (index, text) tuples for all acceptance criteria on the card.

    Parses XML output from `kanban show --output-style=xml`.
    Returns empty list on parse failure.
    """
    xml = _fetch_card_content(card_number, session_id)
    if not xml:
        return []

    criteria = []
    # Match <ac agent-met="..." reviewer-met="...">text</ac>
    for idx, m in enumerate(
        re.finditer(r"<ac\b[^>]*>(.*?)</ac>", xml, re.DOTALL), start=1
    ):
        criteria.append((idx, m.group(1).strip()))
    return criteria


def _format_pending_criteria(criteria_indices, all_criteria):
    """
    Format a numbered list of pending criteria for the AC reviewer prompt.

    criteria_indices: set of 1-based criterion numbers still pending.
    all_criteria: list of (index, text) tuples from _fetch_criteria_list.
    """
    lines = []
    for idx, text in all_criteria:
        if idx in criteria_indices:
            lines.append(f"{idx}. {text}")
    return "\n".join(lines) if lines else "(none)"


def _write_context_file(card_number, card_content, pending_criteria_text, prev_output):
    """
    Write the AC loop context file.

    Content = card content + most recent iteration output only (not cumulative).
    Creates .scratchpad/ directory if it does not exist.
    """
    os.makedirs(_SCRATCHPAD_DIR, exist_ok=True)
    path = _scratchpad_path(card_number)
    content_lines = [
        f"# AC Review Loop — Card #{card_number}",
        "",
        "## Card Content",
        "",
        card_content,
        "",
        "## Pending Criteria",
        "",
        pending_criteria_text,
    ]
    if prev_output:
        content_lines += [
            "",
            "## Previous Iteration Output",
            "",
            prev_output,
        ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(content_lines))
    return path


def _delete_context_file(card_number):
    """Remove the AC loop context file if it exists."""
    path = _scratchpad_path(card_number)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _spawn_ac_reviewer(prompt):
    """
    Spawn `claude -p --model haiku` with the given prompt text.

    Returns (returncode, stdout_text). Never raises.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode, result.stdout
    except Exception as exc:
        return -1, f"[spawn error: {exc}]"


def _parse_ac_reviewer_output(stdout):
    """
    Parse claude -p stdout for AC reviewer markers.

    Returns:
      passed: set of criterion numbers (int) that PASSED
      failed: list of (criterion_number, line) for FAILed criteria
      done: bool — True if KANBAN DONE was emitted
    """
    passed = set()
    failed = []
    done = False

    pass_re = re.compile(r"KANBAN\s+CRITERIA\s+PASS\s+(\d+)", re.IGNORECASE)
    fail_re = re.compile(r"KANBAN\s+CRITERIA\s+FAIL\s+(\d+)", re.IGNORECASE)
    done_re = re.compile(r"KANBAN\s+DONE\b", re.IGNORECASE)

    for line in stdout.splitlines():
        m = pass_re.search(line)
        if m:
            passed.add(int(m.group(1)))
            continue
        m = fail_re.search(line)
        if m:
            failed.append((int(m.group(1)), line.strip()))
            continue
        if done_re.search(line):
            done = True

    return passed, failed, done


def _build_staff_notification(card_number, session_id, outcome, details):
    """
    Build a blocking response to notify the staff engineer of AC review outcome.

    outcome: "passed" | "failed" | "max_iterations"
    details: string with additional context.
    """
    if outcome == "passed":
        header = f"AC review complete — card #{card_number} PASSED."
    elif outcome == "failed":
        header = f"AC review complete — card #{card_number} FAILED."
    else:
        header = (
            f"AC review loop reached maximum iterations for card #{card_number}."
        )

    lines = [header, ""]
    if details:
        lines.append(details)
    return "\n".join(lines)


def run_ac_review_loop(card_number, session_id, max_iterations=None):
    """
    Run the AC review loop for the given card.

    Fetches card criteria, spawns claude -p --model haiku iteratively, and
    processes PASS/FAIL/DONE markers. Calls kanban done on success.

    Returns (outcome, notification_text) where:
      outcome: "passed" | "failed" | "max_iterations" | "error"
      notification_text: human-readable summary for the staff engineer
    """
    if max_iterations is None:
        max_iterations = _AC_LOOP_MAX_ITERATIONS

    # Fetch card content and criteria once at the start.
    card_content = _fetch_card_content(card_number, session_id)
    all_criteria = _fetch_criteria_list(card_number, session_id)

    if not all_criteria:
        return "error", f"Could not fetch criteria for card #{card_number}."

    # Track which criteria are still pending (1-based indices).
    pending = set(idx for idx, _ in all_criteria)
    prev_output = ""

    try:
        for iteration in range(1, max_iterations + 1):
            pending_text = _format_pending_criteria(pending, all_criteria)
            _write_context_file(
                card_number, card_content, pending_text, prev_output
            )

            # The prompt is the structured template — lightweight, no tooling.
            prompt = _AC_REVIEWER_PROMPT_TEMPLATE.format(
                card_number=card_number,
                card_content=card_content,
                pending_criteria_list=pending_text,
                prev_iteration_output=prev_output,
            )

            rc, stdout = _spawn_ac_reviewer(prompt)

            # Save output for the next iteration's context (not cumulative —
            # prev_output is replaced each iteration, not appended).
            prev_output = stdout.strip()

            # Parse markers from AC reviewer output.
            passed, failed_list, done = _parse_ac_reviewer_output(stdout)

            # Apply passes via kanban CLI.
            for n in passed:
                run_kanban_cli(
                    ["criteria", "pass", card_number, str(n), "--session", session_id]
                )
                pending.discard(n)

            # Apply failures via kanban CLI.
            for n, _ in failed_list:
                run_kanban_cli(
                    ["criteria", "fail", card_number, str(n), "--session", session_id]
                )

            if failed_list:
                # Any failure terminates the loop immediately.
                fail_details = "\n".join(
                    f"  Criterion {n}: {line}" for n, line in failed_list
                )
                notification = _build_staff_notification(
                    card_number, session_id, "failed",
                    f"Failed criteria:\n{fail_details}"
                )
                return "failed", notification

            if not pending and done:
                # All criteria passed and reviewer emitted KANBAN DONE.
                run_kanban_cli(
                    ["done", card_number, "All acceptance criteria verified by AC reviewer.",
                     "--session", session_id]
                )
                notification = _build_staff_notification(
                    card_number, session_id, "passed",
                    f"All {len(all_criteria)} criteria verified after {iteration} iteration(s)."
                )
                return "passed", notification

            if not pending:
                # All criteria resolved but no DONE marker — treat as passed.
                run_kanban_cli(
                    ["done", card_number, "All acceptance criteria verified by AC reviewer.",
                     "--session", session_id]
                )
                notification = _build_staff_notification(
                    card_number, session_id, "passed",
                    f"All {len(all_criteria)} criteria verified after {iteration} iteration(s) (no DONE marker emitted)."
                )
                return "passed", notification

            # Some criteria still pending — loop continues with re-prompt.

        # Exhausted iterations.
        remaining = sorted(pending)
        notification = _build_staff_notification(
            card_number, session_id, "max_iterations",
            f"Reached limit of {max_iterations} iterations. "
            f"Still pending: criteria {remaining}.\n"
            f"Last reviewer output:\n{prev_output[:500]}"
        )
        return "max_iterations", notification

    finally:
        _delete_context_file(card_number)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    payload = json.load(sys.stdin)

    # EMERGENCY BRAKE: KANBAN_MARKERS environment variable controls marker processing.
    # If KANBAN_MARKERS=0, skip all marker processing and fall back to legacy (no-op)
    # behavior. This allows immediate rollback if the marker architecture causes issues.
    kanban_markers_enabled = os.environ.get("KANBAN_MARKERS", "1") != "0"
    if not kanban_markers_enabled:
        # Fall back to legacy behavior: return immediately without blocking decision
        return

    # Support both subagent transcripts (agent_transcript_path) and main agent
    # transcripts (transcript_path) for forward compatibility.
    transcript_path = payload.get("agent_transcript_path") or payload.get("transcript_path", "")
    if not transcript_path:
        return

    # Read the first human message to detect KANBAN CARD # pattern and extract
    # card number + session ID.
    first_human = read_first_human_message(transcript_path)
    if not first_human:
        return

    # Not a kanban-aware agent — exit quietly.
    if "KANBAN CARD #" not in first_human:
        return

    card_number, session_id = parse_card_and_session(first_human)
    if card_number is None or session_id is None:
        return

    # Parse the full transcript for kanban markers.
    markers = parse_markers(transcript_path)

    # Process all markers via kanban CLI. Collect any errors.
    cli_errors = process_markers(markers, card_number, session_id)

    # If KANBAN REVIEW was present, launch the AC review loop.
    # The loop handles kanban done (on pass) or staff notification (on fail/limit).
    if has_review_marker(markers):
        outcome, notification = run_ac_review_loop(card_number, session_id)
        if outcome == "passed":
            # Inform staff that AC review succeeded.
            sys.stdout.write(json.dumps({"decision": "block", "reason": notification}))
            sys.stdout.flush()
        elif outcome in ("failed", "max_iterations", "error"):
            # Notify staff of failure or partial results.
            sys.stdout.write(json.dumps({"decision": "block", "reason": notification}))
            sys.stdout.flush()
        return

    # KANBAN REVIEW marker absent — check card state and notify.
    column = run_kanban_status(card_number, session_id)

    # If the card already reached review or done (agent ran kanban review directly
    # without emitting the marker, or a previous attempt succeeded), let through.
    if column in ("review", "done"):
        return

    # Block with explanation.
    reason = build_missing_review_block(card_number, session_id, column, cli_errors)
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never exit non-zero — hook must not disrupt Claude Code
        pass


# ---------------------------------------------------------------------------
# Unit tests (run with: python3 kanban-ac-hook.py --test)
# ---------------------------------------------------------------------------


def _run_tests():
    """Run unit tests for the transcript marker parser."""
    import tempfile
    import os

    passed = 0
    failed = 0

    def assert_eq(label, actual, expected):
        nonlocal passed, failed
        if actual == expected:
            print(f"  PASS: {label}")
            passed += 1
        else:
            print(f"  FAIL: {label}")
            print(f"    expected: {expected!r}")
            print(f"    actual:   {actual!r}")
            failed += 1

    def make_transcript(entries):
        """Write a list of (role, content) or raw entry dicts to a temp JSONL file."""
        lines = []
        for entry in entries:
            if isinstance(entry, dict):
                lines.append(json.dumps(entry))
            else:
                role, content = entry
                if isinstance(content, str):
                    msg = {"role": role, "content": content}
                else:
                    msg = {"role": role, "content": content}
                lines.append(json.dumps({"type": role, "message": msg}))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(lines))
            return f.name

    # --- Test 1: Normal extraction from assistant text block ---
    print("Test 1: Normal marker extraction")
    path = make_transcript([
        ("human", "KANBAN CARD #42 | Session: test-session"),
        ("assistant", "I checked criterion 1.\nKANBAN CRITERIA CHECK 1\nNow reviewing.\nKANBAN REVIEW"),
    ])
    markers = parse_markers(path)
    os.unlink(path)
    types = [m["marker_type"] for m in markers]
    assert_eq("finds CRITERIA_CHECK", "CRITERIA_CHECK" in types, True)
    assert_eq("finds REVIEW", "REVIEW" in types, True)
    assert_eq("CRITERIA_CHECK arg is 1", markers[0]["args"], ["1"])

    # --- Test 2: Code fence exclusion ---
    print("Test 2: Code fence exclusion")
    path = make_transcript([
        ("human", "KANBAN CARD #42 | Session: test-session"),
        ("assistant", "Here is example:\n```\nKANBAN REVIEW\nKANBAN CRITERIA CHECK 2\n```\nActual: KANBAN CRITERIA CHECK 3"),
    ])
    markers = parse_markers(path)
    os.unlink(path)
    types = [m["marker_type"] for m in markers]
    args_list = [m["args"] for m in markers]
    assert_eq("no REVIEW in code fence", "REVIEW" not in types, True)
    assert_eq("no CHECK 2 from code fence", ["2"] not in args_list, True)
    assert_eq("CHECK 3 outside fence found", ["3"] in args_list, True)

    # --- Test 3: Thinking block exclusion ---
    print("Test 3: Thinking block exclusion")
    thinking_content = [
        {"type": "thinking", "thinking": "I should KANBAN REVIEW here"},
        {"type": "text", "text": "KANBAN CRITERIA CHECK 5"},
    ]
    path = make_transcript([
        ("human", "KANBAN CARD #42 | Session: test-session"),
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": thinking_content},
        },
    ])
    markers = parse_markers(path)
    os.unlink(path)
    types = [m["marker_type"] for m in markers]
    assert_eq("thinking block REVIEW excluded", "REVIEW" not in types, True)
    assert_eq("text block CHECK 5 found", "CRITERIA_CHECK" in types, True)

    # --- Test 4: Tool output exclusion ---
    print("Test 4: Tool output exclusion")
    tool_content = [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "kanban review 42"}},
        {"type": "text", "text": "KANBAN REVIEW"},
    ]
    path = make_transcript([
        ("human", "KANBAN CARD #42 | Session: test-session"),
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": tool_content},
        },
    ])
    markers = parse_markers(path)
    os.unlink(path)
    # tool_use block has no "text" key so it yields None and is skipped
    assert_eq("tool_use block skipped", sum(1 for m in markers if m["marker_type"] == "REVIEW"), 1)

    # --- Test 5: tool_result blocks excluded ---
    print("Test 5: Tool result exclusion")
    # tool_result appears as a human turn with content list including tool_result blocks
    tool_result_content = [
        {"type": "tool_result", "tool_use_id": "t1", "content": "KANBAN REVIEW"},
    ]
    path = make_transcript([
        ("human", "KANBAN CARD #42 | Session: test-session"),
        {
            "type": "human",
            "message": {"role": "human", "content": tool_result_content},
        },
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": "KANBAN REVIEW"},
        },
    ])
    markers = parse_markers(path)
    os.unlink(path)
    # Only the assistant message should contribute a REVIEW marker
    assert_eq("only 1 REVIEW from assistant text", sum(1 for m in markers if m["marker_type"] == "REVIEW"), 1)

    # --- Test 6: Partial transcript (no markers) ---
    print("Test 6: Partial/empty transcript")
    path = make_transcript([
        ("human", "KANBAN CARD #42 | Session: test-session"),
        ("assistant", "I am working on this task."),
    ])
    markers = parse_markers(path)
    os.unlink(path)
    assert_eq("no markers in partial transcript", markers, [])

    # --- Test 7: has_review_marker ---
    print("Test 7: has_review_marker helper")
    assert_eq("detects REVIEW", has_review_marker([{"marker_type": "REVIEW", "args": [], "line_index": 0}]), True)
    assert_eq("no REVIEW in empty list", has_review_marker([]), False)
    assert_eq("CRITERIA_CHECK not REVIEW", has_review_marker([{"marker_type": "CRITERIA_CHECK", "args": ["1"], "line_index": 0}]), False)

    # --- Test 8: KANBAN CRITERIA PASS and FAIL markers ---
    print("Test 8: CRITERIA_PASS and CRITERIA_FAIL markers")
    path = make_transcript([
        ("human", "KANBAN CARD #42 | Session: test-session"),
        ("assistant", "KANBAN CRITERIA PASS 2\nKANBAN CRITERIA FAIL 3\nKANBAN REVIEW"),
    ])
    markers = parse_markers(path)
    os.unlink(path)
    types = [m["marker_type"] for m in markers]
    assert_eq("CRITERIA_PASS found", "CRITERIA_PASS" in types, True)
    assert_eq("CRITERIA_FAIL found", "CRITERIA_FAIL" in types, True)
    pass_markers = [m for m in markers if m["marker_type"] == "CRITERIA_PASS"]
    assert_eq("CRITERIA_PASS arg is 2", pass_markers[0]["args"], ["2"])

    # --- Test 9: _parse_ac_reviewer_output ---
    print("Test 9: _parse_ac_reviewer_output — all pass with DONE")
    stdout = "Criterion 1 looks good.\nKANBAN CRITERIA PASS 1\nCriterion 2 also good.\nKANBAN CRITERIA PASS 2\nKANBAN DONE"
    p, f, d = _parse_ac_reviewer_output(stdout)
    assert_eq("passed set = {1, 2}", p, {1, 2})
    assert_eq("no failures", f, [])
    assert_eq("DONE emitted", d, True)

    # --- Test 10: _parse_ac_reviewer_output — mixed pass/fail, no DONE ---
    print("Test 10: _parse_ac_reviewer_output — mixed pass/fail")
    stdout = "KANBAN CRITERIA PASS 1\nKANBAN CRITERIA FAIL 2 — not satisfied"
    p, f, d = _parse_ac_reviewer_output(stdout)
    assert_eq("passed = {1}", p, {1})
    assert_eq("failed has criterion 2", [n for n, _ in f], [2])
    assert_eq("no DONE", d, False)

    # --- Test 11: _parse_ac_reviewer_output — empty output ---
    print("Test 11: _parse_ac_reviewer_output — empty output")
    p, f, d = _parse_ac_reviewer_output("")
    assert_eq("empty: no passed", p, set())
    assert_eq("empty: no failed", f, [])
    assert_eq("empty: no DONE", d, False)

    # --- Test 12: _parse_ac_reviewer_output — case insensitive ---
    print("Test 12: _parse_ac_reviewer_output — case insensitive")
    stdout = "kanban criteria pass 3\nkanban done"
    p, f, d = _parse_ac_reviewer_output(stdout)
    assert_eq("case insensitive pass", p, {3})
    assert_eq("case insensitive DONE", d, True)

    # --- Test 13: _write_context_file / _delete_context_file ---
    print("Test 13: context file write and delete")
    orig_dir = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        try:
            _write_context_file("99", "card content here", "1. criterion one", "prev output")
            ctx_path = _scratchpad_path("99")
            assert_eq("context file exists after write", os.path.exists(ctx_path), True)
            with open(ctx_path) as fh:
                content = fh.read()
            assert_eq("context contains card content", "card content here" in content, True)
            assert_eq("context contains prev output", "prev output" in content, True)
            # Overwrite resets content (non-cumulative)
            _write_context_file("99", "card content here", "1. criterion one", "NEW output only")
            with open(ctx_path) as fh:
                content2 = fh.read()
            assert_eq("context shows new output, not cumulative", "NEW output only" in content2, True)
            assert_eq("old prev output not in new context", content2.count("prev output") == 0, True)
            _delete_context_file("99")
            assert_eq("context file gone after delete", os.path.exists(ctx_path), False)
        finally:
            os.chdir(orig_dir)

    # --- Test 14: _fetch_criteria_list XML parsing ---
    print("Test 14: _fetch_criteria_list XML parsing")
    sample_xml = """<card num="42">
  <acceptance-criteria>
    <ac agent-met="false" reviewer-met="false">First criterion text</ac>
    <ac agent-met="true" reviewer-met="false">Second criterion text</ac>
  </acceptance-criteria>
</card>"""
    # Monkey-patch run_kanban_cli for this test
    original_run_kanban_cli = run_kanban_cli

    def mock_run_kanban_cli(args, timeout=25):
        if "show" in args:
            return 0, sample_xml, ""
        return 0, "", ""
    # Patch via globals
    globals()["run_kanban_cli"] = mock_run_kanban_cli
    try:
        criteria = _fetch_criteria_list("42", "test-session")
        assert_eq("fetches 2 criteria", len(criteria), 2)
        assert_eq("first criterion idx=1", criteria[0][0], 1)
        assert_eq("first criterion text", criteria[0][1], "First criterion text")
        assert_eq("second criterion idx=2", criteria[1][0], 2)
    finally:
        globals()["run_kanban_cli"] = original_run_kanban_cli

    # --- Test 15: _build_staff_notification ---
    print("Test 15: _build_staff_notification")
    msg = _build_staff_notification("42", "s1", "passed", "3 criteria in 1 iteration.")
    assert_eq("passed notification contains PASSED", "PASSED" in msg, True)
    msg = _build_staff_notification("42", "s1", "failed", "Criterion 2: bad.")
    assert_eq("failed notification contains FAILED", "FAILED" in msg, True)
    msg = _build_staff_notification("42", "s1", "max_iterations", "Pending: [1, 2].")
    assert_eq("max_iter notification contains 'maximum iterations'", "maximum iterations" in msg, True)

    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--test":
    success = _run_tests()
    sys.exit(0 if success else 1)
