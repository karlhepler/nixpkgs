#!/usr/bin/env python3
"""
claude-kanban-transition-hook: PostToolUse(Bash) hook for kanban state transitions.

Sends macOS notifications when a kanban card changes state via staff engineer
or agent Bash commands (kanban start, defer, cancel, done, review).

Trigger: PostToolUse(Bash) — fires after every Bash tool call.
Input:   JSON from stdin (Claude Code hook format with tool_input.command).
Output:  None (PostToolUse notification hook has no JSON output contract).
"""

import html
import json
import re
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

_HELP = """\
claude-kanban-transition-hook - PostToolUse hook for kanban state transitions

DESCRIPTION:
  Internal hook script called automatically by Claude Code.
  Should not be invoked manually by users.

PURPOSE:
  Sends macOS notifications when a kanban card changes state via
  staff engineer or agent Bash commands (kanban start, defer, cancel, done, review).

TRIGGER:
  PostToolUse(Bash) — fires after every Bash tool call.
  Only sends notification when the command is a kanban state-changing
  command: start, defer, cancel, done, or review.
  Does NOT fire on: kanban criteria check/uncheck.

STATE MAPPING:
  kanban start  N → 🚂 Work Started  (todo→doing)
  kanban defer  N → ⏸️ Deferred      (doing→todo)
  kanban cancel N → ❌ Canceled      (any→canceled)
  kanban done   N → ✅ Done          (review→done)
  kanban review N → 🔍 In Review     (doing→review)

NOTIFICATION FORMAT:
  Title: <emoji> <State Name>
  Body line 1: <tmux_session> → <tmux_window>
  Body line 2: #N — <card intent, truncated>

CONFIGURATION:
  Configured in modules/claude/default.nix as PostToolUse(Bash) hook.
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KANBAN_TIMEOUT = 10  # seconds
_ERROR_LOG_PATH = Path.home() / ".claude" / "metrics" / "claude-kanban-transition-hook-errors.log"


def _log_error(message: str) -> None:
    """Append a timestamped error to the hook error log. Never raises."""
    try:
        _ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(_ERROR_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


# Pattern: kanban <subcommand> <card_number> [options]
# Matches: start, defer, cancel, done, review
# Does NOT match: criteria (which covers check/uncheck)
_TRANSITION_PATTERN = re.compile(
    r"^\s*kanban\s+(start|defer|cancel|done|review)\s+(\d+)",
    re.IGNORECASE | re.MULTILINE,
)

# State mapping: command → (emoji, title, new_state, sound)
_COMMAND_STATES = {
    "start": ("🚂", "Work Started", "doing", "Purr"),
    "defer": ("⏸️", "Deferred", "todo", "Pop"),
    "cancel": ("❌", "Canceled", "canceled", "Bottle"),
    "done": ("✅", "Done", "done", "Hero"),
    "review": ("🔍", "In Review", "review", "Blow"),
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_common():
    """Import claude_hook_common from the same directory as this script."""
    sys.path.insert(0, str(Path(__file__).parent))
    import claude_hook_common  # noqa: PLC0415
    return claude_hook_common


# ---------------------------------------------------------------------------
# Card intent helpers
# ---------------------------------------------------------------------------

def truncate_intent(intent: str, max_len: int = 60) -> str:
    """Truncate intent to max_len characters, adding ellipsis if needed."""
    intent = intent.replace("\n", " ").strip()
    if len(intent) <= max_len:
        return intent
    return intent[: max_len - 1].rstrip() + "…"


def get_card_intent(card_number: str, session: str = "") -> str:
    """Fetch card intent from kanban CLI, decoding XML/HTML entities.

    Returns empty string on any failure. Logs the exception so that
    notifications showing "card #N" (instead of the intent snippet) can
    be diagnosed via the error log.
    """
    cmd = ["kanban", "show", card_number, "--output-style=xml"]
    if session:
        cmd += ["--session", session]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=KANBAN_TIMEOUT,
        )
        if result.returncode == 0:
            m = re.search(r"<intent>(.*?)</intent>", result.stdout, re.DOTALL)
            if m:
                encoded_intent = m.group(1).strip()
                # Decode XML/HTML entities: &amp;#x27; → ', &amp; → &, &lt; → <, etc.
                return html.unescape(encoded_intent)
    except Exception as exc:
        _log_error(
            f"get_card_intent failed for card #{card_number} (session={session!r}): "
            f"{exc}\n{traceback.format_exc()}"
        )
    return ""


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> None:
    common = _load_common()

    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

    if not command:
        return

    m = _TRANSITION_PATTERN.search(command)
    if not m:
        return

    subcommand = m.group(1).lower()
    card_number = m.group(2)

    emoji, state_name, _new_state, sound = _COMMAND_STATES[subcommand]
    title = f"{emoji} {state_name}"

    # Extract --session flag from command if present
    session_m = re.search(r"--session\s+([a-z0-9][a-z0-9-]*)", command, re.IGNORECASE)
    session = session_m.group(1) if session_m else ""

    # Fetch card intent
    intent = get_card_intent(card_number, session)
    snippet = truncate_intent(intent) if intent else f"card #{card_number}"

    tmux_ctx = common.get_tmux_context()
    card_line = f"#{card_number} — {snippet}"
    body = f"{tmux_ctx}\n{card_line}" if tmux_ctx else card_line

    common.send_notification(title, body, sound)
    common.set_tmux_attention()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(_HELP, end="")
        sys.exit(0)

    try:
        main()
    except Exception:
        pass  # Hooks must never crash Claude Code
