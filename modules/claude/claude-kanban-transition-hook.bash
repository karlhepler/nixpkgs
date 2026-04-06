#!/usr/bin/env bash

show_help() {
  echo "claude-kanban-transition-hook - PostToolUse hook for kanban state transitions"
  echo
  echo "DESCRIPTION:"
  echo "  Internal hook script called automatically by Claude Code."
  echo "  Should not be invoked manually by users."
  echo
  echo "PURPOSE:"
  echo "  Sends macOS notifications when a kanban card changes state via"
  echo "  staff engineer or agent Bash commands (kanban start, defer, cancel, done, review)."
  echo
  echo "TRIGGER:"
  echo "  PostToolUse(Bash) — fires after every Bash tool call."
  echo "  Only sends notification when the command is a kanban state-changing"
  echo "  command: start, defer, cancel, done, or review."
  echo "  Does NOT fire on: kanban criteria check/uncheck."
  echo
  echo "STATE MAPPING:"
  echo "  kanban start  N → 🚂 Work Started  (todo→doing)"
  echo "  kanban defer  N → ⏸️ Deferred      (doing→todo)"
  echo "  kanban cancel N → ❌ Canceled      (any→canceled)"
  echo "  kanban done   N → ✅ Done          (review→done)"
  echo "  kanban review N → 🔍 In Review     (doing→review)"
  echo
  echo "NOTIFICATION FORMAT:"
  echo "  Title: <emoji> <State Name>"
  echo "  Body line 1: <tmux_session> → <tmux_window>"
  echo "  Body line 2: #N — <card intent, truncated>"
  echo
  echo "CONFIGURATION:"
  echo "  Configured in modules/claude/default.nix as PostToolUse(Bash) hook."
}

# Parse arguments for help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

# Read JSON from stdin
json=$(cat)

# Extract command, detect kanban state transitions, send macOS notification
python3 -c "
import html
import sys, json, os, re, subprocess

KANBAN_TIMEOUT = 10  # seconds

# Pattern: kanban <subcommand> <card_number> [options]
# Matches: start, defer, cancel, done, review
# Does NOT match: criteria (which covers check/uncheck)
_TRANSITION_PATTERN = re.compile(
    r'^\s*kanban\s+(start|defer|cancel|done|review)\s+(\d+)',
    re.IGNORECASE | re.MULTILINE,
)

# State mapping: command → (emoji, title, new_state, sound)
_COMMAND_STATES = {
    'start':  ('🚂', 'Work Started', 'doing', 'Purr'),
    'defer':  ('⏸️', 'Deferred',     'todo', 'Pop'),
    'cancel': ('❌', 'Canceled',     'canceled', 'Bottle'),
    'done':   ('✅', 'Done',         'done', 'Hero'),
    'review': ('🔍', 'In Review',    'review', 'Blow'),
}


def truncate_intent(intent, max_len=60):
    intent = intent.replace('\n', ' ').strip()
    if len(intent) <= max_len:
        return intent
    return intent[:max_len - 1].rstrip() + '\u2026'


def get_card_intent(card_number, session):
    try:
        result = subprocess.run(
            ['kanban', 'show', card_number, '--output-style=xml', '--session', session],
            capture_output=True, text=True, timeout=KANBAN_TIMEOUT,
        )
        if result.returncode == 0:
            m = re.search(r'<intent>(.*?)</intent>', result.stdout, re.DOTALL)
            if m:
                encoded_intent = m.group(1).strip()
                # Decode XML/HTML entities: &amp;#x27; → ', &amp; → &, &lt; → <, etc.
                return html.unescape(encoded_intent)
    except Exception:
        pass
    return ''


def get_card_intent_no_session(card_number):
    '''Try to get intent without requiring a session (for cancel case).
    Decodes XML/HTML entities from the intent text.
    '''
    try:
        result = subprocess.run(
            ['kanban', 'show', card_number, '--output-style=xml'],
            capture_output=True, text=True, timeout=KANBAN_TIMEOUT,
        )
        if result.returncode == 0:
            m = re.search(r'<intent>(.*?)</intent>', result.stdout, re.DOTALL)
            if m:
                encoded_intent = m.group(1).strip()
                # Decode XML/HTML entities: &amp;#x27; → ', &amp; → &, &lt; → <, etc.
                return html.unescape(encoded_intent)
    except Exception:
        pass
    return ''


def get_tmux_context():
    '''Get tmux session → window context string, or empty string if not in tmux.'''
    tmux = os.environ.get('TMUX', '')
    tmux_pane = os.environ.get('TMUX_PANE', '')
    if not tmux or not tmux_pane:
        return ''
    try:
        session = subprocess.run(
            ['tmux', 'display-message', '-t', tmux_pane, '-p', '#S'],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        window = subprocess.run(
            ['tmux', 'display-message', '-t', tmux_pane, '-p', '#W'],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if session and window:
            return f'{session} \u2192 {window}'
    except Exception:
        pass
    return ''


def send_notification(title, body, sound='Glass'):
    safe_title = title.replace('\\\\', '\\\\\\\\').replace('\"', '\\\\\"')
    safe_body = body.replace('\\\\', '\\\\\\\\').replace('\"', '\\\\\"')
    try:
        subprocess.run(
            [
                'osascript', '-e',
                f'tell application id \"org.alacritty\" to display notification '
                f'\"{safe_body}\" with title \"{safe_title}\" sound name \"{sound}\"',
            ],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


try:
    data = json.loads(sys.stdin.read())
    tool_input = data.get('tool_input', {})
    command = tool_input.get('command', '') if isinstance(tool_input, dict) else ''

    if not command:
        sys.exit(0)

    m = _TRANSITION_PATTERN.search(command)
    if not m:
        sys.exit(0)

    subcommand = m.group(1).lower()
    card_number = m.group(2)

    emoji, state_name, new_state, sound = _COMMAND_STATES[subcommand]
    title = f'{emoji} {state_name}'

    # Extract --session flag from command if present
    session_m = re.search(r'--session\s+([a-z0-9][a-z0-9-]*)', command, re.IGNORECASE)
    session = session_m.group(1) if session_m else ''

    # Fetch card intent
    if session:
        intent = get_card_intent(card_number, session)
    else:
        intent = get_card_intent_no_session(card_number)

    snippet = truncate_intent(intent) if intent else f'card #{card_number}'
    tmux_ctx = get_tmux_context()
    card_line = f'#{card_number} \u2014 {snippet}'
    body = f'{tmux_ctx}\n{card_line}' if tmux_ctx else card_line

    send_notification(title, body, sound)

except Exception:
    pass
" <<< "$json"

exit 0
