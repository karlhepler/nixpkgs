#!/usr/bin/env python3
"""
kanban-subagent-stop-hook: SubagentStop hook that implements the dual-loop AC
review system.

Triggered when any sub-agent finishes execution. Parses the agent's transcript
to find the associated kanban card, then runs an inner AC review loop using
claude -p --model haiku. If all criteria pass, the card is marked done and the
agent is allowed to stop. If criteria fail and review_cycles < 3, the agent is
blocked with failure details so it can fix and retry (outer loop). After 3
cycles, the agent is allowed to stop with a failure summary for staff.

Output format (SubagentStop hook):
    {"decision": "allow"}  — let the agent stop
    {"decision": "block", "reason": "..."}  — send agent back with feedback

Fails open: any error results in allowing the agent to stop unchanged.

Skip condition: BURNS_SESSION=1 env var means Ralph is running — skip AC review.
"""

import json
import os
import re
import subprocess
import sys
import traceback
import warnings
from pathlib import Path

# Suppress Python deprecation warnings to prevent stderr output,
# which Claude Code interprets as hook errors.
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ERROR_LOG_PATH = Path.home() / ".claude" / "metrics" / "kanban-subagent-stop-hook-errors.log"
MAX_INNER_ITERATIONS = 2
MAX_OUTER_CYCLES = 3
CLAUDE_MAX_TURNS = 50
AC_REVIEWER_AGENT_PATH = Path.home() / ".claude" / "agents" / "ac-reviewer.md"

# Patterns for extracting card number and session from transcript lines
_KANBAN_CMD_PATTERN = re.compile(
    r'kanban\s+(?:criteria\s+check|review|show|status|done)\s+(\d+).*--session\s+([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)

# Pattern for "KANBAN CARD #N | Session: session-name" (injected by pretool hook)
_CARD_HEADER_PATTERN = re.compile(
    r'KANBAN\s+CARD\s+#(\d+)\s*\|\s*Session:\s*([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)

# Pattern for card reference in injected XML: card num="N" ... session="session-name"
_CARD_XML_PATTERN = re.compile(
    r'<card\s+[^>]*num="(\d+)"[^>]*session="([a-z0-9][a-z0-9-]*)"',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

def log_error(message: str) -> None:
    """Append an error to the hook error log. Never raises."""
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


INFO_LOG_PATH = Path.home() / ".claude" / "metrics" / "kanban-subagent-stop-hook.log"


def log_info(message: str) -> None:
    """Log informational message to file. Never raises.

    Previously wrote to stderr, but Claude Code interprets any stderr output
    from hooks as errors — causing false 'hook error' labels in the UI.
    """
    try:
        INFO_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(INFO_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Allow/block response helpers
# ---------------------------------------------------------------------------

def allow(message: str = "") -> dict:
    """Return a decision=allow response."""
    result = {"decision": "allow"}
    if message:
        result["reason"] = message
    return result


def block(reason: str, system_message: str = "") -> dict:
    """Return a decision=block response to send the agent back."""
    result = {"decision": "block", "reason": reason}
    if system_message:
        result["systemMessage"] = system_message
    return result


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def extract_agent_output(transcript_path: str) -> str:
    """
    Extract the agent's final substantive output from the JSONL transcript.

    Reads the transcript and returns the content of the last assistant message
    before the agent stopped. This is the agent's findings/deliverable summary.

    For review/research cards, this output IS the primary deliverable.
    For work cards, file inspection remains primary but this provides supplementary context.

    Returns the extracted output string, or empty string if not found.
    """
    last_assistant_content = ""
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line, strict=False)
                except json.JSONDecodeError:
                    continue

                # Look for assistant-role messages
                if not isinstance(entry, dict):
                    continue

                role = entry.get("role", "")
                if role != "assistant":
                    continue

                content = entry.get("content", "")
                if isinstance(content, str) and content.strip():
                    last_assistant_content = content.strip()
                elif isinstance(content, list):
                    # Content may be a list of blocks; extract text blocks
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text.strip():
                                text_parts.append(text.strip())
                        elif isinstance(block, str) and block.strip():
                            text_parts.append(block.strip())
                    if text_parts:
                        last_assistant_content = "\n".join(text_parts)
    except (OSError, IOError) as exc:
        log_error(f"Failed to read transcript for agent output at {transcript_path}: {exc}")

    return last_assistant_content


def extract_card_from_transcript(transcript_path: str) -> tuple[str, str] | None:
    """
    Parse the agent's transcript (JSONL) line by line to find the card number
    and session ID.

    Looks for:
    1. Injected card XML header from PreToolUse hook
    2. KANBAN CARD #N | Session: session-name header
    3. kanban CLI calls with card number and --session flag

    Returns (card_number_str, session_id) or None if not found.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line, strict=False)
                except json.JSONDecodeError:
                    continue

                # Search through all string values in the entry for patterns
                text_to_search = _extract_text_from_entry(entry)
                for text in text_to_search:
                    # Try XML card pattern first (most specific from pretool hook)
                    m = _CARD_XML_PATTERN.search(text)
                    if m:
                        return (m.group(1), m.group(2))

                    # Try KANBAN CARD header pattern
                    m = _CARD_HEADER_PATTERN.search(text)
                    if m:
                        return (m.group(1), m.group(2))

                    # Try kanban CLI command pattern
                    m = _KANBAN_CMD_PATTERN.search(text)
                    if m:
                        return (m.group(1), m.group(2))
    except (OSError, IOError) as exc:
        log_error(f"Failed to read transcript at {transcript_path}: {exc}")
        return None

    return None


def _extract_text_from_entry(entry: dict | list | str, depth: int = 0) -> list[str]:
    """Recursively extract string values from a JSON entry, with depth limit."""
    if depth > 5:
        return []
    texts = []
    if isinstance(entry, str):
        texts.append(entry)
    elif isinstance(entry, dict):
        for v in entry.values():
            texts.extend(_extract_text_from_entry(v, depth + 1))
    elif isinstance(entry, list):
        for item in entry:
            texts.extend(_extract_text_from_entry(item, depth + 1))
    return texts


# ---------------------------------------------------------------------------
# Kanban CLI helpers
# ---------------------------------------------------------------------------

def run_kanban(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a kanban CLI command, capturing output."""
    cmd = ["kanban"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            log_info(f"kanban {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}")
        return result
    except subprocess.TimeoutExpired:
        log_error(f"kanban {' '.join(args)} timed out after {timeout}s")
        raise
    except FileNotFoundError:
        log_error("kanban CLI not found in PATH")
        raise


def get_card_status(card_number: str, session: str) -> str | None:
    """Get the current column of a card. Returns column name or None on error."""
    try:
        result = run_kanban(["status", card_number, "--session", session])
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_review_cycles(card_number: str, session: str) -> int:
    """Read the review_cycles count from the card XML."""
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode == 0:
            m = re.search(r'review-cycles="(\d+)"', result.stdout)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 0


def _extract_criteria_failures(card_number: str, session: str) -> str:
    """Read card XML and extract criteria that failed with their reasons.

    Returns a formatted string listing each failed criterion, or a fallback
    message if the card cannot be read.
    """
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode != 0:
            return "Could not read card details to determine failure reasons."

        xml_output = result.stdout
        # Parse ALL <ac> elements to track their 1-based position, then report
        # only those with reviewer-met="fail" using their actual AC index.
        ac_pattern = re.compile(
            r'<ac\b([^>]*?)>(.*?)</ac>',
            re.DOTALL,
        )
        fail_pattern = re.compile(r'reviewer-met="fail"')
        reason_pattern = re.compile(r'reviewer-fail-reason="([^"]*)"')

        failures = []
        for ac_index, match in enumerate(ac_pattern.finditer(xml_output), 1):
            attrs = match.group(1)
            if not fail_pattern.search(attrs):
                continue
            criterion_text = match.group(2).strip()
            reason_match = reason_pattern.search(attrs)
            reason = reason_match.group(1) if reason_match else "no reason provided"
            failures.append(f"{ac_index}. [{criterion_text}]: {reason}")

        if failures:
            return "\n".join(failures)

        return "AC review did not pass, but no specific failure reasons were found on the card."

    except Exception as exc:
        log_error(f"Failed to extract criteria failures for card #{card_number}: {exc}")
        return "Could not determine failure reasons due to an error."


def get_deferred_cards(session: str) -> list[str]:
    """Get list of card numbers in the todo column for this session."""
    try:
        result = run_kanban(["list", "--column", "todo", "--output-style=xml", "--session", session])
        if result.returncode == 0 and result.stdout.strip():
            # Extract card numbers from XML output
            return re.findall(r'num="(\d+)"', result.stdout)
    except Exception:
        pass
    return []


def format_deferred_notification(session: str) -> str:
    """Build deferred card notification string, or empty if none."""
    card_nums = get_deferred_cards(session)
    if card_nums:
        card_refs = ", ".join(f"#{n}" for n in card_nums)
        return f"\nDeferred cards awaiting action: {card_refs}"
    return ""


# ---------------------------------------------------------------------------
# Inner loop: Haiku AC review
# ---------------------------------------------------------------------------

def build_haiku_prompt(card_number: str, session: str, previous_context: str, agent_output: str = "") -> str:
    """Build the prompt for the haiku AC reviewer."""
    previous_section = ""
    if previous_context:
        previous_section = f"""
Previous review context (accumulated from earlier passes — use this to avoid
re-checking criteria you already reviewed):
{previous_context}
"""

    agent_output_section = ""
    if agent_output:
        agent_output_section = f"""
Agent output (the sub-agent's final response — use this as evidence context):
---
{agent_output}
---

For review/research cards, the agent output above IS the primary deliverable to verify against.
For work cards, file inspection is primary but use agent output as supplementary context.
"""

    return f"""You are an AC reviewer for kanban card #{card_number} (session {session}).

Your job: Verify each acceptance criterion, then complete the card.

Step 1: Run this command to read the card:
  kanban show {card_number} --output-style=xml --session {session}

Step 2: For each acceptance criterion, verify it by inspecting files, running
the Method of Verification (MoV) specified in the criterion text, or checking
whatever evidence is appropriate.

Step 3: For each criterion you verify:
  - If it PASSES: kanban criteria pass {card_number} <n> --session {session}
  - If it FAILS: kanban criteria fail {card_number} <n> --reason '<why it failed>' --session {session}

Step 4: After all criteria have a pass or fail verdict, run:
  kanban done {card_number} '<one-sentence summary>' --session {session}

If kanban done fails (some criteria are unchecked or failed), that is expected.
Just ensure every criterion has been evaluated with pass or fail.
{agent_output_section}{previous_section}
IMPORTANT:
- Verify EVERY criterion. Do not skip any.
- Be thorough but efficient — max 2 file reads per criterion.
- Use the MoV in each criterion to guide your verification approach.
- Run kanban criteria pass/fail as you verify each criterion, not all at the end.
"""


def read_ac_reviewer_agent_definition() -> str:
    """Read the ac-reviewer agent definition for use as system prompt.

    Same pattern as staff.bash: read agent definition, pass via --system-prompt.
    The file is deployed by Nix Home Manager (hms) and is guaranteed to exist.
    If missing, that is a deployment failure and should crash loudly.
    """
    return AC_REVIEWER_AGENT_PATH.read_text(encoding="utf-8")


def run_inner_loop(card_number: str, session: str, transcript_path: str = "") -> bool:
    """
    Run the inner AC review loop (max MAX_INNER_ITERATIONS iterations).

    Each iteration launches claude -p --model haiku to review criteria.
    After each iteration, checks if the card reached the done column.

    Returns True if the card reached done, False otherwise.
    """
    accumulated_context = ""
    agent_output = extract_agent_output(transcript_path) if transcript_path else ""
    if agent_output:
        log_info(f"Extracted agent output for card #{card_number} ({len(agent_output)} chars)")

    # Read ac-reviewer agent definition for use as system prompt
    # (same pattern as staff.bash: read agent definition, pass via --system-prompt)
    ac_reviewer_system_prompt = read_ac_reviewer_agent_definition()
    log_info("Loaded ac-reviewer agent definition as system prompt")

    for i in range(1, MAX_INNER_ITERATIONS + 1):
        log_info(f"Inner loop iteration {i}/{MAX_INNER_ITERATIONS} for card #{card_number}")

        prompt = build_haiku_prompt(card_number, session, accumulated_context, agent_output)

        try:
            # Set agent identity env vars so metrics identify this as ac-reviewer
            # (same pattern as staff.bash: KANBAN_AGENT + CLAUDIT2_ROLE)
            ac_env = {**os.environ, "KANBAN_AGENT": "ac-reviewer", "CLAUDIT2_ROLE": "ac-reviewer"}

            # Build claude command: load ac-reviewer agent definition as system prompt
            # (same mechanism as staff.bash loads staff-engineer via --system-prompt)
            claude_cmd = [
                "claude", "-p", "--model", "haiku", "--max-turns", str(CLAUDE_MAX_TURNS),
                "--system-prompt", ac_reviewer_system_prompt,
            ]

            result = subprocess.run(
                claude_cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes per iteration
                env=ac_env,
            )
            iteration_output = result.stdout.strip()
            iteration_stderr = result.stderr.strip()

            if iteration_stderr:
                log_info(f"claude -p stderr (iter {i}): {iteration_stderr}")

            accumulated_context += f"\n--- Pass {i} ---\n{iteration_output}\n"

        except subprocess.TimeoutExpired:
            log_error(f"claude -p timed out on iteration {i}")
            accumulated_context += f"\n--- Pass {i} ---\n[TIMED OUT]\n"
            continue
        except FileNotFoundError:
            log_error("claude CLI not found in PATH")
            return False
        except Exception as exc:
            log_error(f"claude -p failed on iteration {i}: {exc}")
            accumulated_context += f"\n--- Pass {i} ---\n[ERROR: {exc}]\n"
            continue

        # Check if card reached done column
        status = get_card_status(card_number, session)
        if status == "done":
            log_info(f"Card #{card_number} reached done after {i} inner iteration(s)")
            return True

        # If card is not in review or done, something unexpected happened
        if status and status not in ("review", "doing", "done"):
            log_info(f"Card #{card_number} in unexpected status '{status}' — breaking inner loop")
            break

    return False


# ---------------------------------------------------------------------------
# Main hook logic
# ---------------------------------------------------------------------------

def process_subagent_stop(payload: dict) -> dict:
    """
    Process a SubagentStop event.

    Steps:
    1. Identify card from transcript
    2. Check if agent called kanban review
    3. Run inner AC review loop (haiku)
    4. Process result (allow/block)
    5. Append deferred card notification
    """
    transcript_path = payload.get("agent_transcript_path", "")

    if not transcript_path or not os.path.exists(transcript_path):
        log_info("No transcript path or file not found — allowing stop")
        return allow()

    # Step 1: Identify the card
    extracted = extract_card_from_transcript(transcript_path)
    if extracted is None:
        log_info("No kanban card found in transcript — allowing stop (not kanban-managed)")
        return allow()

    card_number, session = extracted
    log_info(f"Found card #{card_number} (session: {session})")

    # Step 2: Check if agent completed work (called kanban review)
    # Check card status — if it's in "review", the agent successfully called kanban review
    status = get_card_status(card_number, session)
    if status is None:
        log_info(f"Could not get status for card #{card_number} — allowing stop")
        return allow()

    if status == "done":
        # Card already done (maybe by a previous hook run or manual intervention)
        message = f"Card #{card_number} is already done."
        message += format_deferred_notification(session)
        return allow(message)

    if status != "review":
        # Agent didn't call kanban review successfully — incomplete work
        log_info(f"Card #{card_number} is in '{status}', not 'review' — agent did not complete review step")
        message = (
            f"Card #{card_number} work incomplete — agent stopped without calling kanban review. "
            f"Card remains in '{status}' column."
        )
        message += format_deferred_notification(session)
        return allow(message)

    # Step 3: Inner loop — Haiku AC verification
    log_info(f"Starting AC review inner loop for card #{card_number}")
    card_done = run_inner_loop(card_number, session, transcript_path)

    # Step 4: Process result
    if card_done:
        message = f"Card #{card_number} AC review passed — card completed."
        message += format_deferred_notification(session)
        return allow(message)

    # Re-check status — inner loop may have succeeded but returned False
    # (e.g. transient status check failure while haiku actually called kanban done)
    status = get_card_status(card_number, session)
    if status == "done":
        log_info(f"Card #{card_number} reached done (detected on re-check after inner loop)")
        message = f"Card #{card_number} AC review passed — card completed."
        message += format_deferred_notification(session)
        return allow(message)

    # Card not done after inner loop — check review cycles
    review_cycles = get_review_cycles(card_number, session)
    log_info(f"Card #{card_number} AC review failed — review_cycles={review_cycles}")

    if review_cycles >= MAX_OUTER_CYCLES:
        # Max cycles reached — allow stop, staff handles manually
        message = (
            f"Card #{card_number} AC review failed after {review_cycles} review cycle(s). "
            f"Max cycles ({MAX_OUTER_CYCLES}) reached — requires manual intervention by staff engineer."
        )
        message += format_deferred_notification(session)
        return allow(message)

    # Under max cycles — redo the card and block the agent
    # Read the card to get actual criteria failure reasons from the AC reviewer
    failure_details = _extract_criteria_failures(card_number, session)

    # Check card status before attempting redo — if it's already in a terminal state, skip redo
    status_before_redo = get_card_status(card_number, session)
    if status_before_redo in ("done", "canceled"):
        message = f"Card #{card_number} is already {status_before_redo}."
        message += format_deferred_notification(session)
        return allow(message)

    # Run kanban redo to send card back to doing (increments review_cycles)
    redo_result = run_kanban(["redo", card_number, "--session", session])
    if redo_result.returncode != 0:
        log_error(f"kanban redo #{card_number} failed: {redo_result.stderr.strip()}")
        # If redo fails, allow stop — don't block agent in a broken state
        message = f"Card #{card_number} AC review failed but kanban redo also failed. Needs manual intervention."
        message += format_deferred_notification(session)
        return allow(message)

    # Block the agent with failure details
    reason = (
        f"AC review failed for card #{card_number} "
        f"(cycle {review_cycles + 1}/{MAX_OUTER_CYCLES}). "
        f"The following criteria failed:\n\n{failure_details}"
    )
    system_message = (
        f"The AC reviewer found issues with your work. "
        f"Fix the issues described below, then call "
        f"kanban review {card_number} --session {session} again."
    )
    return block(reason, system_message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Skip if running inside a Burns/Ralph session
    if os.environ.get("BURNS_SESSION") == "1":
        print(json.dumps(allow()))
        return

    # Read the hook payload from stdin
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps(allow()))
        return

    try:
        payload = json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        log_error(f"JSON decode error: {exc}")
        print(json.dumps(allow()))
        return

    result = process_subagent_stop(payload)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Fail open — never block agent stop due to hook failure
        log_error(f"Unhandled exception: {exc}\n{traceback.format_exc()}")
        print(json.dumps({"decision": "allow"}))
    sys.exit(0)
