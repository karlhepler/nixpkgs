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

# Read JSON from stdin
json=$(cat)

# Extract data using official Claude Code hook fields
data=$(echo "$json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    message = data.get('message', 'Claude needs input')
    notification_type = data.get('notification_type', '')
    hook_event_name = data.get('hook_event_name', 'Notification')
    cwd = data.get('cwd', '')

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

    # Add context if available
    if cwd:
        dir_name = cwd.split('/')[-1] if '/' in cwd else cwd
        message = f'{message} [in {dir_name}]'

    print(f'{title}|{message}')
except Exception as e:
    print('Claude Notification|Claude needs input')
")

# Split output
IFS='|' read -r title message <<< "$data"

# Send notification from Alacritty (using bundle ID to avoid path issues)
osascript -e "tell application id \"org.alacritty\" to display notification \"$message\" with title \"$title\" sound name \"Ping\""

# Set tmux window option for attention flag
# Can't ring bell directly because Claude Code is a TUI that would receive the keys
if [[ -n "${TMUX:-}" && -n "${TMUX_PANE:-}" ]]; then
  # Set custom window option to flag this window needs attention
  tmux set-window-option -t "$TMUX_PANE" @claude_attention 1
fi
