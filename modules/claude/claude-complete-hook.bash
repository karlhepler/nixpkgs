#!/usr/bin/env bash

show_help() {
  echo "claude-complete-hook - Internal Claude Code completion hook"
  echo
  echo "DESCRIPTION:"
  echo "  Internal hook script called automatically by Claude Code."
  echo "  Should not be invoked manually by users."
  echo
  echo "PURPOSE:"
  echo "  Sends macOS notifications and sets tmux window attention flags"
  echo "  when Claude Code completes a task or subagent finishes."
  echo "  Notifications include kanban card context when available."
  echo
  echo "TRIGGER:"
  echo "  Automatically invoked by Claude Code on completion events:"
  echo "  - Stop (main task completion)"
  echo "  - SubagentStop (subagent task completion)"
  echo
  echo "BEHAVIOR:"
  echo "  - Parses JSON input from stdin (Claude Code hook format)"
  echo "  - SubagentStop: extracts card number from transcript, queries kanban"
  echo "    for card status and intent, formats card-centric notification"
  echo "  - Stop: queries kanban board summary for session, formats session summary"
  echo "  - Falls back to generic notification if kanban context unavailable"
  echo "  - Sends macOS notification via Alacritty"
  echo "  - Sets tmux @claude_attention window option"
  echo "  - Plays 'Glass' notification sound"
  echo
  echo "CONFIGURATION:"
  echo "  Configured in modules/claude/default.nix as completion hook."
}

# Parse arguments for help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

# @COMMON_FUNCTIONS@ - Will be replaced by Nix at build time

# Get tmux context
tmux_context=$(get_tmux_context)
export TMUX_CONTEXT="$tmux_context"

# Extract data using official Claude Code Stop hook fields
# Pipe stdin directly to python (no intermediate buffering)
data=$(python3 -c "
import sys, json, os, re, subprocess

KANBAN_TIMEOUT = 10  # seconds (stop hook uses 30s; write contention may occur)

# Patterns for extracting card number and session from transcript text
# Matches: <!-- Kanban card #N (session: SESSION) injected by PreToolUse hook -->
_CARD_COMMENT_PATTERN = re.compile(
    r'Kanban\s+card\s+#(\d+)\s*\(session:\s*([a-z0-9][a-z0-9-]*)\)',
    re.IGNORECASE,
)
# Matches: KANBAN CARD #N | Session: SESSION
_CARD_HEADER_PATTERN = re.compile(
    r'KANBAN\s+CARD\s+#(\d+)\s*\|\s*Session:\s*([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)
# Matches: <card num=\"N\" ... session=\"SESSION\"
_CARD_XML_PATTERN = re.compile(
    r'<card\s+[^>]*num=\"(\d+)\"[^>]*session=\"([a-z0-9][a-z0-9-]*)\"',
    re.IGNORECASE,
)
# Matches: kanban criteria check N ... --session SESSION
_KANBAN_CMD_PATTERN = re.compile(
    r'kanban\s+(?:criteria\s+check|review|show|status|done)\s+(\d+).*?--session\s+([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE | re.DOTALL,
)


def extract_strings(obj, depth=0):
    '''Recursively extract string values from a JSON structure.'''
    if depth > 5:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        results = []
        for v in obj.values():
            results.extend(extract_strings(v, depth + 1))
        return results
    if isinstance(obj, list):
        results = []
        for item in obj:
            results.extend(extract_strings(item, depth + 1))
        return results
    return []


def extract_card_from_transcript(transcript_path):
    '''Parse JSONL transcript to find card number and session ID.
    Returns (card_number, session) or None.'''
    try:
        with open(transcript_path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line, strict=False)
                except json.JSONDecodeError:
                    continue
                for text in extract_strings(entry):
                    for pat in [_CARD_XML_PATTERN, _CARD_COMMENT_PATTERN, _CARD_HEADER_PATTERN, _KANBAN_CMD_PATTERN]:
                        m = pat.search(text)
                        if m:
                            return (m.group(1), m.group(2))
    except (OSError, IOError):
        pass
    return None


def run_kanban(args):
    '''Run kanban CLI with a short timeout. Returns stdout string or None.'''
    try:
        result = subprocess.run(
            ['kanban'] + args,
            capture_output=True, text=True,
            timeout=KANBAN_TIMEOUT,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def get_card_info(card_number, session):
    '''Query kanban show for card status and intent. Returns (status, intent) or None.'''
    xml = run_kanban(['show', card_number, '--output-style=xml', '--session', session])
    if not xml:
        return None
    status_m = re.search(r'status=\"([^\"]+)\"', xml)
    intent_m = re.search(r'<intent>(.*?)</intent>', xml, re.DOTALL)
    if not status_m:
        return None
    status = status_m.group(1)
    intent = intent_m.group(1).strip() if intent_m else ''
    return (status, intent)


def truncate_intent(intent, max_len=60):
    '''Truncate intent to a short snippet for notifications.'''
    intent = intent.replace('\n', ' ').strip()
    if len(intent) <= max_len:
        return intent
    return intent[:max_len - 1].rstrip() + '\u2026'


def get_board_summary(session):
    '''Query kanban list for board summary. Returns summary string or None.'''
    xml = run_kanban(['list', '--output-style=xml', '--session', session, '--show-all'])
    if not xml:
        return None
    # Count cards by status attribute: s=\"done\", s=\"redo\", s=\"review\", s=\"doing\"
    counts = {}
    for m in re.finditer(r'<c\s+[^>]*\bs=\"([^\"]+)\"', xml):
        col = m.group(1)
        counts[col] = counts.get(col, 0) + 1
    if not counts:
        return None
    # Build summary string: '2 done, 1 review, 3 doing'
    order = ['done', 'review', 'redo', 'doing', 'todo']
    parts = []
    for col in order:
        if col in counts:
            parts.append(f'{counts[col]} {col}')
    # Any columns not in our ordered list
    for col, n in counts.items():
        if col not in order:
            parts.append(f'{n} {col}')
    return ', '.join(parts)


try:
    data = json.load(sys.stdin)
    hook_event_name = data.get('hook_event_name', 'Stop')
    tmux_context = os.environ.get('TMUX_CONTEXT', '')

    if hook_event_name == 'SubagentStop':
        transcript_path = data.get('transcript_path', '')
        title = 'Claude: Complete'
        message = 'Subagent task finished'

        if transcript_path:
            card_info = extract_card_from_transcript(transcript_path)
            if card_info:
                card_number, session = card_info
                info = get_card_info(card_number, session)
                if info:
                    status, intent = info
                    snippet = truncate_intent(intent) if intent else f'Card #{card_number}'
                    if status == 'done':
                        title = 'Kanban: Done'
                        message = f'Card #{card_number} \u2705 \u2014 {snippet} ({session})'
                    elif status == 'redo':
                        title = 'Kanban: Redo'
                        message = f'Card #{card_number} \U0001f501 redo \u2014 {snippet} ({session})'
                    else:
                        # review, doing, or any other in-progress state
                        title = 'Kanban: Complete'
                        message = f'Card #{card_number} \u23f3 \u2014 {snippet} ({session})'

    else:
        # Stop event (main session)
        title = 'Session Complete'
        message = 'Task finished'
        kanban_session = os.environ.get('KANBAN_SESSION', '')
        if kanban_session:
            summary = get_board_summary(kanban_session)
            if summary:
                message = f'Session complete \u2014 {summary} ({kanban_session})'

    # Prepend tmux context to message if available
    if tmux_context:
        message = f'{tmux_context}\n{message}'

    print(title)
    print(message)
except Exception:
    print('Claude Code Complete')
    print('Task finished')
")

# Two-line protocol: first line = title, remaining lines = message
title="${data%%$'\n'*}"
message="${data#*$'\n'}"

# Send notification with 'Glass' sound
send_notification "$title" "$message" "Glass"

# Set tmux attention flags
set_tmux_attention
