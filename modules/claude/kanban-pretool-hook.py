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
        "hookSpecificOutput": {
            "permissionDecision": "allow",
        }
    }


def allow_with_updated_prompt(new_prompt: str) -> dict:
    """Return a permissionDecision=allow response with updated prompt."""
    return {
        "hookSpecificOutput": {
            "permissionDecision": "allow",
            "updatedInput": {
                "prompt": new_prompt,
            },
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
    if not prompt:
        print(json.dumps(allow_unchanged()))
        return

    # Extract card number and session from prompt
    extracted = extract_card_and_session(prompt)
    if extracted is None:
        # No card reference found — pass through unchanged
        print(json.dumps(allow_unchanged()))
        return

    card_number, session = extracted

    # Fetch card XML via kanban CLI
    card_xml = fetch_card_xml(card_number, session)
    if card_xml is None:
        # kanban show failed — fail open
        print(json.dumps(allow_unchanged()))
        return

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

    print(json.dumps(allow_with_updated_prompt(new_prompt)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_error(f"hook error: {exc}\n{traceback.format_exc()}")
    # Always exit 0 — hook must never block agent launch
    sys.exit(0)
