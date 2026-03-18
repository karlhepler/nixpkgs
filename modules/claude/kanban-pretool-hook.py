#!/usr/bin/env python3
"""
kanban-pretool-hook: PreToolUse(Agent) hook that injects kanban card content
into sub-agent prompts.

Triggered by Claude Code's PreToolUse event when tool_name == 'Agent'.
Reads the agent prompt, extracts the card number and session ID, fetches the
card content via `kanban show`, and injects it at the beginning of the prompt.

Output format (PreToolUse hook):
    {"hookSpecificOutput": {"permissionDecision": "allow", "updatedInput": {"prompt": "..."}}}

Fails open: any error (no card found, kanban show fails, JSON parse error)
results in allowing the tool call unchanged.

Skip condition: BURNS_SESSION=1 env var means Ralph is running — skip injection
to avoid confusing the model with kanban context.

Known Issues:
    - Claude Code displays 'PreToolUse:Agent hook error' in the UI even when
      this hook succeeds (exits 0, valid JSON, no stderr). This is a cosmetic
      UI bug in Claude Code, not a hook failure. The hook's info log at
      ~/.claude/metrics/kanban-pretool-hook.log confirms successful injection.
      See: https://github.com/anthropics/claude-code/issues/17088
    - updatedInput may be silently dropped if multiple PreToolUse hooks match
      the same tool (we only register one for Agent, so this should not apply).
      See: https://github.com/anthropics/claude-code/issues/15897
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

ERROR_LOG_PATH = Path.home() / ".claude" / "metrics" / "kanban-pretool-hook-errors.log"
INFO_LOG_PATH = Path.home() / ".claude" / "metrics" / "kanban-pretool-hook.log"

# Patterns for extracting card number and session from agent prompts.
# Priority order: most specific first.
#
# Pattern 1: "KANBAN CARD #N | Session: session-name"  (current delegation template)
_CARD_FULL_PATTERN = re.compile(
    r'KANBAN\s+CARD\s+#(\d+)\s*\|\s*Session:\s*([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)

# Pattern 2: "card #N" or "#N" with "--session session-name" nearby
_CARD_SESSION_PATTERN = re.compile(
    r'(?:card\s+)?#(\d+)[^\n]*--session\s+([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)

# Pattern 3: Standalone card number with session on same or adjacent line
# e.g. "card #123" anywhere + "session noble-maple" anywhere
_CARD_BARE_PATTERN = re.compile(r'card\s+#(\d+)', re.IGNORECASE)
_SESSION_BARE_PATTERN = re.compile(r'[Ss]ession[:\s]+([a-z0-9][a-z0-9-]+)')


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

def _write_log(path: Path, message: str) -> None:
    """Append a timestamped message to a log file. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def log_error(message: str) -> None:
    """Append an error to the hook error log. Never raises."""
    _write_log(ERROR_LOG_PATH, message)


def log_info(message: str) -> None:
    """Append an info message to the hook info log. Never raises."""
    _write_log(INFO_LOG_PATH, message)


# ---------------------------------------------------------------------------
# Card/session extraction
# ---------------------------------------------------------------------------

def extract_card_and_session(prompt: str) -> tuple[str, str] | None:
    """
    Parse card number and session ID from the agent prompt.

    Returns (card_number_str, session_id) or None if not found.
    Tries patterns from most to least specific.
    """
    # Pattern 1: "KANBAN CARD #N | Session: session-name"
    m = _CARD_FULL_PATTERN.search(prompt)
    if m:
        return (m.group(1), m.group(2))

    # Pattern 2: "#N ... --session session-name" on same line
    m = _CARD_SESSION_PATTERN.search(prompt)
    if m:
        return (m.group(1), m.group(2))

    # Pattern 3: Combine bare card + bare session from anywhere in prompt
    card_m = _CARD_BARE_PATTERN.search(prompt)
    session_m = _SESSION_BARE_PATTERN.search(prompt)
    if card_m and session_m:
        return (card_m.group(1), session_m.group(1))

    return None


# ---------------------------------------------------------------------------
# Kanban card fetch
# ---------------------------------------------------------------------------

def fetch_card_xml(card_number: str, session: str) -> str | None:
    """
    Run `kanban show <card_number> --output-style=xml --session <session>`.
    Returns the XML string on success, None on any failure.
    """
    try:
        result = subprocess.run(
            ["kanban", "show", card_number, "--output-style=xml", "--session", session],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            log_error(
                f"kanban show #{card_number} failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
            return None
        output = result.stdout.strip()
        if not output:
            log_error(f"kanban show #{card_number} returned empty output")
            return None
        return output
    except subprocess.TimeoutExpired:
        log_error(f"kanban show #{card_number} timed out")
        return None
    except FileNotFoundError:
        log_error("kanban CLI not found in PATH")
        return None
    except Exception as exc:
        log_error(f"kanban show #{card_number} unexpected error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

def inject_card_into_prompt(prompt: str, card_xml: str, card_number: str, session: str) -> str:
    """
    Prepend the card XML to the agent prompt, separated by a clear boundary.

    The injected block is placed BEFORE the original prompt so the agent
    sees the card details immediately without having to call kanban show.
    """
    header = (
        f"<!-- Kanban card #{card_number} (session: {session}) "
        f"injected by PreToolUse hook -->\n"
        f"{card_xml}\n"
        f"<!-- End of injected card content -->\n\n"
    )
    return header + prompt


# ---------------------------------------------------------------------------
# Allow response helpers
# ---------------------------------------------------------------------------

def allow_unchanged() -> dict:
    """Return a permissionDecision=allow response with no prompt modification."""
    return {
        "continue": True,
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "",
        }
    }


def allow_with_updated_prompt(original_input: dict, new_prompt: str) -> dict:
    """Return a permissionDecision=allow response with updated prompt.

    CRITICAL: updatedInput must contain ALL original tool_input fields, not just
    prompt. Claude Code replaces (not merges) tool_input with updatedInput, so
    omitting fields like run_in_background, subagent_type, model, and description
    causes them to be silently stripped — resulting in agents running in the
    foreground despite the caller setting run_in_background: true.
    """
    updated = dict(original_input)
    updated["prompt"] = new_prompt
    return {
        "continue": True,
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "",
            "updatedInput": updated,
        }
    }


def deny_with_reason(reason: str) -> dict:
    """Return a permissionDecision=deny response with a reason message."""
    return {
        "continue": False,
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Skip if running inside a Burns/Ralph session to avoid confusing Ralph
    # with kanban context injection.
    if os.environ.get("BURNS_SESSION") == "1":
        print(json.dumps(allow_unchanged()))
        return

    # Read the hook payload from stdin
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps(allow_unchanged()))
        return

    try:
        payload = json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        log_error(f"JSON decode error: {exc}")
        print(json.dumps(allow_unchanged()))
        return

    # Verify this is an Agent tool call (matcher should guarantee this, but be safe)
    tool_name = payload.get("tool_name", "")
    if tool_name != "Agent":
        print(json.dumps(allow_unchanged()))
        return

    # Extract prompt from tool_input
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        print(json.dumps(allow_unchanged()))
        return

    prompt = tool_input.get("prompt", "")

    # SKILL_AGENT_BYPASS: Skills (e.g. /commit) may spawn Agent calls without
    # kanban cards, background mode, or subagent_type. If the prompt contains
    # the bypass marker, skip all enforcement deny rules but still attempt card
    # injection if a card reference is present.
    skill_bypass = bool(prompt and "SKILL_AGENT_BYPASS" in prompt)
    if skill_bypass:
        log_info("SKILL_AGENT_BYPASS detected — skipping enforcement rules")

    if not skill_bypass:
        # Check for missing or empty description field — deny launch if absent
        description = tool_input.get("description", "")
        if not description or not str(description).strip():
            reason = (
                "Agent tool call denied: missing or empty 'description' field. "
                "Include a meaningful description on all Agent/Task tool calls "
                "so the completion notification identifies the agent (instead of 'undefined')."
            )
            log_info("Agent denied — missing description field")
            print(json.dumps(deny_with_reason(reason)))
            return

        # Check for missing or invalid subagent_type — deny launch if absent
        subagent_type_check = tool_input.get("subagent_type", "")
        if not subagent_type_check or not str(subagent_type_check).strip():
            reason = (
                "Agent tool call denied: missing or empty 'subagent_type' field. "
                "Always specify a subagent_type (e.g. swe-backend, swe-frontend, "
                "researcher). The general-purpose agent is prohibited — there is "
                "always a more appropriate specialist."
            )
            log_info("Agent denied — missing subagent_type field")
            print(json.dumps(deny_with_reason(reason)))
            return

        # Deny the literal "general-purpose" subagent_type (case-insensitive).
        # Defense-in-depth: the staff engineer prompt already prohibits it, but
        # concrete examples in docs were overriding the prose instruction.
        if str(subagent_type_check).strip().lower() == "general-purpose":
            reason = (
                "Agent tool call denied: subagent_type 'general-purpose' is "
                "prohibited. There is always a more appropriate specialist. "
                "Use a specific subagent_type instead (e.g. swe-backend, "
                "swe-frontend, swe-fullstack, swe-devex, swe-infra, swe-sre, "
                "swe-security, researcher, scribe, debugger)."
            )
            log_info(f"Agent denied — general-purpose subagent_type: {subagent_type_check!r}")
            print(json.dumps(deny_with_reason(reason)))
            return

    if not prompt:
        print(json.dumps(allow_unchanged()))
        return

    if not skill_bypass:
        # Check for missing run_in_background: true — deny foreground launches unless
        # Option C is explicitly authorized via FOREGROUND_AUTHORIZED marker in prompt.
        run_in_background = tool_input.get("run_in_background")
        if run_in_background is not True:
            if "FOREGROUND_AUTHORIZED" not in prompt:
                reason = (
                    "Agent tool call denied: missing `run_in_background: true`. "
                    "All Agent tool calls MUST run in the background to keep the "
                    "coordination loop available. Add `run_in_background: true` to "
                    "your Agent tool call. Exception: Permission Gate Recovery "
                    "Option C — include 'FOREGROUND_AUTHORIZED' in the delegation "
                    "prompt to allow a foreground launch."
                )
                log_info("Agent denied — missing run_in_background: true")
                print(json.dumps(deny_with_reason(reason)))
                return

        # Extract card number and session from prompt — deny if missing
        extracted = extract_card_and_session(prompt)
        if extracted is None:
            reason = (
                "Agent tool call denied: no kanban card reference found in prompt. "
                "Every Agent delegation must reference a card created with `kanban do`. "
                "Include 'KANBAN CARD #<N> | Session: <session-id>' at the top of "
                "the delegation prompt. Create the card first, then launch the agent."
            )
            log_info("Agent denied — no card reference in prompt")
            print(json.dumps(deny_with_reason(reason)))
            return
    else:
        # Bypass mode: still attempt card injection if a card reference exists
        extracted = extract_card_and_session(prompt)

    # If no card reference found (only possible in bypass mode), allow unchanged
    if extracted is None:
        print(json.dumps(allow_unchanged()))
        return

    card_number, session = extracted
    log_info(f"card found: #{card_number} session={session}")

    # Fetch card XML via kanban CLI
    card_xml = fetch_card_xml(card_number, session)
    if card_xml is None:
        # kanban show failed — fail open
        print(json.dumps(allow_unchanged()))
        return
    log_info(f"card XML fetched successfully for #{card_number}")

    # Inject card content into the prompt
    new_prompt = inject_card_into_prompt(prompt, card_xml, card_number, session)

    # Update card's agent field with the actual sub-agent type (fire-and-forget)
    subagent_type = tool_input.get("subagent_type", "")
    if subagent_type:
        try:
            subprocess.Popen(
                ["kanban", "agent", card_number, subagent_type, "--session", session],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            log_error(f"kanban agent update failed for #{card_number}: {exc}")

    log_info(f"prompt updated successfully for #{card_number} session={session}")
    print(json.dumps(allow_with_updated_prompt(tool_input, new_prompt)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_error(f"hook error: {exc}\n{traceback.format_exc()}")
    # Always exit 0 — hook must never block agent launch
    sys.exit(0)
