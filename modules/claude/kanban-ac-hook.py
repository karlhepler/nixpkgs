#!/usr/bin/env python3
"""
kanban-ac-hook: Claude Code SubagentStop hook that enforces AC self-checking.

When a kanban-aware sub-agent finishes, this hook checks whether all acceptance
criteria on the card were self-checked (agent_met="true"). If any remain
unchecked, it blocks the agent with instructions to run the missing
`kanban criteria check` commands.

Retry protection: the SubagentStop payload includes a 'stop_hook_active'
boolean that is True when the agent is already continuing from a prior Stop
hook block. When detected, the agent is let through with a warning comment
on the card instead of looping infinitely.

Never exits non-zero — all errors are swallowed silently to avoid disrupting
Claude Code's hook pipeline.
"""

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BLOCK_SENTINEL = "STOP — incomplete kanban workflow on card #"


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
                # Extract text from message content (may be a list of blocks)
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


def run_kanban_show(card_number, session_id):
    """
    Run `kanban show <N> --output-style=xml --session <session-id>`.
    Returns the XML string output or None on failure.
    """
    try:
        result = subprocess.run(
            ["kanban", "show", card_number, "--output-style=xml", "--session", session_id],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


def parse_unchecked_criteria(xml_text):
    """
    Parse kanban XML output and return a list of unchecked ACs.

    Each entry is a dict with keys:
      - "n": 1-based index of the criterion (int)
      - "text": criterion text (str)

    Returns an empty list if all criteria are checked or XML is unparseable.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    unchecked = []
    ac_elements = root.findall(".//ac")
    for idx, ac_el in enumerate(ac_elements, start=1):
        agent_met = ac_el.get("agent-met", "false").lower()
        if agent_met not in ("true", "yes"):
            text = (ac_el.text or "").strip()
            unchecked.append({"n": idx, "text": text})
    return unchecked


def parse_card_column(xml_text):
    """Parse the card's status (column) from kanban XML output."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    card_el = root if root.tag == "card" else root.find(".//card")
    if card_el is not None:
        return card_el.get("status")
    return None


def has_agent_comments(xml_text):
    """Check if the card has any comments (agent findings)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    comments = root.findall(".//comment")
    return len(comments) > 0


def post_warning_comment(card_number, session_id, last_message=""):
    """
    Post a warning comment to the card when the agent is let through on retry.

    Includes a truncated excerpt of last_assistant_message when available so
    reviewers have context about what the agent was doing.  Failures are
    silently swallowed.
    """
    base = (
        "WARNING: Agent completed without finishing all kanban workflow steps"
        " (comment/criteria check/review). AC review will need to catch gaps."
    )
    if last_message:
        excerpt = last_message[:200]
        if len(last_message) > 200:
            excerpt += "..."
        comment_text = f"{base} Last message: {excerpt}"
    else:
        comment_text = base

    try:
        subprocess.run(
            [
                "kanban",
                "comment",
                card_number,
                comment_text,
                "--session",
                session_id,
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except Exception:
        pass


def build_block_reason(card_number, session_id, unchecked, comments_present, column):
    """
    Build the human-readable blocking reason string listing all incomplete
    workflow steps: findings comment, AC self-checks, and review transition.
    """
    lines = [
        f"{BLOCK_SENTINEL}{card_number}. Before finishing, you MUST complete these steps:",
        "",
    ]

    # Step 1: Post findings (if no comments yet)
    if not comments_present:
        lines.append(
            f'kanban comment {card_number} "your detailed findings here" --session {session_id}'
        )
        lines.append("  # Post your findings/summary as a card comment")
        lines.append("")

    # Step 2: Check unchecked AC criteria
    for ac in unchecked:
        lines.append(
            f"kanban criteria check {card_number} {ac['n']} --session {session_id}"
        )
        if ac["text"]:
            lines.append(f"  # Criterion: {ac['text'][:120]}")
    if unchecked:
        lines.append("")

    # Step 3: Move to review (if not already there)
    if column and column not in ("review", "done"):
        lines.append(
            f"kanban review {card_number} --session {session_id}"
        )
        lines.append("  # Move card to review column (must be last step)")
        lines.append("")

    lines.append("Run ALL commands above in order. Then you may finish.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    payload = json.load(sys.stdin)

    transcript_path = payload.get("agent_transcript_path", "")
    if not transcript_path:
        return

    # Read the first human message to detect the KANBAN CARD # pattern
    first_human = read_first_human_message(transcript_path)
    if not first_human:
        return

    # Not a kanban-aware agent — exit quietly
    if "KANBAN CARD #" not in first_human:
        return

    # AC reviewer agents use 'criteria verify' — do not block them.
    #
    # COUPLING POINT: This string match detects AC reviewer agents vs
    # work/research agents.  The phrase 'criteria verify' comes directly from
    # the AC reviewer delegation template in staff-engineer.md
    # (§ 'Delegation template for AC reviewers').  If that template ever
    # changes its wording (e.g. renames the command), this detection must be
    # updated to match, otherwise AC reviewers will be incorrectly subjected
    # to enforcement.
    if "criteria verify" in first_human:
        return

    # Work/research agents use 'criteria check' — proceed with enforcement
    # (Guard: if neither phrase present, treat as work agent and check anyway)

    card_number, session_id = parse_card_and_session(first_human)
    if card_number is None or session_id is None:
        return

    # Retry protection — the SubagentStop payload sets stop_hook_active=True
    # when the agent is already continuing from a prior Stop hook block.
    # Let it through with a warning comment rather than looping infinitely.
    last_message = payload.get("last_assistant_message", "")
    if payload.get("stop_hook_active", False):
        post_warning_comment(card_number, session_id, last_message)
        return

    xml_text = run_kanban_show(card_number, session_id)
    if not xml_text:
        return

    # Check ALL completion requirements in one pass.
    # Combined check matters because retry protection (stop_hook_active) only
    # allows one retry — all missing steps must be communicated at once.
    unchecked = parse_unchecked_criteria(xml_text)
    comments_present = has_agent_comments(xml_text)
    column = parse_card_column(xml_text)

    needs_block = (
        bool(unchecked)
        or not comments_present
        or (column is not None and column not in ("review", "done"))
    )

    if not needs_block:
        return

    reason = build_block_reason(
        card_number, session_id, unchecked, comments_present, column
    )
    block_response = json.dumps({"decision": "block", "reason": reason})
    sys.stdout.write(block_response)
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never exit non-zero — hook must not disrupt Claude Code
        pass
