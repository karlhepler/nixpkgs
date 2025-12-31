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
  echo "  when Claude Code requires user input or interaction."
  echo
  echo "TRIGGER:"
  echo "  Automatically invoked by Claude Code on Notification events:"
  echo "  - Permission prompts"
  echo "  - Idle prompts (waiting for user)"
  echo "  - Authentication success"
  echo "  - Input requests"
  echo "  - Errors"
  echo
  echo "BEHAVIOR:"
  echo "  - Parses JSON input from stdin (Claude Code hook format)"
  echo "  - Sends macOS notification via Alacritty"
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

set -eou pipefail

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
    message = data.get('message', 'Claude needs input')
    notification_type = data.get('notification_type', '')
    tmux_context = os.environ.get('TMUX_CONTEXT', '')

    # Use notification_type for better title categorization
    if notification_type == 'permission_prompt':
        title = 'Claude Permission Request'
    elif notification_type == 'idle_prompt':
        title = 'Claude Waiting'
    elif notification_type == 'auth_success':
        title = 'Claude Authenticated'
    elif notification_type == 'elicitation_dialog':
        title = 'Claude Needs Input'
    elif 'error' in message.lower():
        title = 'Claude Error'
    else:
        title = 'Claude Notification'

    # Prepend tmux context to message if available
    if tmux_context:
        message = f'{tmux_context}\n{message}'

    print(f'{title}|{message}')
except Exception as e:
    print('Claude Notification|Claude needs input')
")

# Split output on first pipe, preserving newlines in message
title="${data%%|*}"
message="${data#*|}"

# Send notification with 'Ping' sound
send_notification "$title" "$message" "Ping"

# Set tmux attention flags
set_tmux_attention
