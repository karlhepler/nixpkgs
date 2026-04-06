#!/usr/bin/env bash

show_help() {
  echo "claude-notification-hook - Internal Claude Code notification hook"
  echo
  echo "DESCRIPTION:"
  echo "  Internal hook script called automatically by Claude Code."
  echo "  Should not be invoked manually by users."
  echo
  echo "PURPOSE:"
  echo "  Sends macOS notifications and sets tmux window attention flags"
  echo "  when Claude Code requires user input (permission prompts, elicitation dialogs)."
  echo
  echo "TRIGGER:"
  echo "  Automatically invoked by Claude Code on Notification events."
  echo "  Only fires on: permission_prompt, elicitation_dialog"
  echo
  echo "BEHAVIOR:"
  echo "  - Parses JSON input from stdin (Claude Code hook format)"
  echo "  - Sends macOS notification via Alacritty (title: '❓ Question')"
  echo "  - Sets tmux @claude_attention window option"
  echo "  - Plays 'Ping' notification sound"
  echo
  echo "CONFIGURATION:"
  echo "  Configured in modules/claude/default.nix as notification hook."
}

# Parse arguments for help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

# @COMMON_FUNCTIONS@ - Will be replaced by Nix at build time

# Read JSON from stdin
json=$(cat)

# Get tmux context
tmux_context=$(get_tmux_context)
export TMUX_CONTEXT="$tmux_context"

# Extract data using official Claude Code hook fields
data=$(echo "$json" | python3 -c "
import sys, json, os
try:
    data = json.load(sys.stdin)
    notification_type = data.get('notification_type', '')
    tmux_context = os.environ.get('TMUX_CONTEXT', '')

    # Only notify for question/input events
    if notification_type not in ('permission_prompt', 'elicitation_dialog'):
        print('SKIP')
        sys.exit(0)

    message = data.get('message', 'Claude needs input')

    # Prepend tmux context to message if available
    if tmux_context:
        message = f'{tmux_context}\n{message}'

    print(f'❓ Question|{message}|Ping')
except Exception as e:
    print('SKIP')
")

# Skip notification if not a question event
if [[ "$data" == "SKIP" ]]; then
  exit 0
fi

# Split output on pipes: title|message|sound
IFS='|' read -r title message sound <<< "$data"

# Send notification with parsed sound
send_notification "$title" "$message" "$sound"

# Set tmux attention flags
set_tmux_attention
