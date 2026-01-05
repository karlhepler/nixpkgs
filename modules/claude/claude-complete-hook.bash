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
  echo
  echo "TRIGGER:"
  echo "  Automatically invoked by Claude Code on completion events:"
  echo "  - Stop (main task completion)"
  echo "  - SubagentStop (subagent task completion)"
  echo
  echo "BEHAVIOR:"
  echo "  - Parses JSON input from stdin (Claude Code hook format)"
  echo "  - Sends macOS notification via Alacritty"
  echo "  - Sets tmux @claude_attention window option"
  echo "  - Plays 'Glass' notification sound"
  echo "  - Extracts directory context from transcript path"
  echo
  echo "CONFIGURATION:"
  echo "  Configured in modules/claude/default.nix as completion hook."
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

# Extract data using official Claude Code Stop hook fields
data=$(echo "$json" | python3 -c "
import sys, json, os
try:
    data = json.load(sys.stdin)
    hook_event_name = data.get('hook_event_name', 'Stop')
    tmux_context = os.environ.get('TMUX_CONTEXT', '')

    # Determine title and message
    if hook_event_name == 'SubagentStop':
        title = 'Claude Subagent Complete'
        message = 'Subagent task finished'
    else:
        title = 'Claude Code Complete'
        message = 'Task finished'

    # Prepend tmux context to message if available
    if tmux_context:
        message = f'{tmux_context}\n{message}'

    print(f'{title}|{message}')
except Exception as e:
    print('Claude Code Complete|Task finished')
")

# Split output on first pipe, preserving newlines in message
title="${data%%|*}"
message="${data#*|}"

# Send notification with 'Glass' sound
send_notification "$title" "$message" "Glass"

# Set tmux attention flags
set_tmux_attention
