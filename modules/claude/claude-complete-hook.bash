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

# Read JSON from stdin
json=$(cat)

# Get tmux context if in tmux
tmux_context=""
if [[ -n "${TMUX:-}" ]]; then
  # Get session name and window name
  session_name=$(tmux display-message -p '#S' 2>/dev/null || echo "")
  window_name=$(tmux display-message -p '#W' 2>/dev/null || echo "")

  tmux_context="$session_name → $window_name"
fi

# Export for Python
export TMUX_CONTEXT="$tmux_context"

# Extract data using official Claude Code Stop hook fields
data=$(echo "$json" | python3 -c "
import sys, json, os
try:
    data = json.load(sys.stdin)
    hook_event_name = data.get('hook_event_name', 'Stop')
    transcript_path = data.get('transcript_path', '')
    tmux_context = os.environ.get('TMUX_CONTEXT', '')

    # Extract directory from transcript_path (Stop hook doesn't provide cwd!)
    dir_name = ''
    if transcript_path:
        # transcript_path format: ~/.claude/projects/{project_name}/{session_id}.jsonl
        parts = transcript_path.split('/')
        if 'projects' in parts:
            idx = parts.index('projects')
            if idx + 1 < len(parts):
                dir_name = parts[idx + 1]

    # Determine title and message
    if hook_event_name == 'SubagentStop':
        title = 'Claude Subagent Complete'
        message = f'Subagent task finished{\" in \" + dir_name if dir_name else \"\"}'
    else:
        title = 'Claude Code Complete'
        message = f'Task finished{\" in \" + dir_name if dir_name else \"\"}'

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

# Send notification from Alacritty (using bundle ID to avoid path issues)
osascript -e "tell application id \"org.alacritty\" to display notification \"$message\" with title \"$title\" sound name \"Glass\""

# Set tmux window option for attention flag
# Can't ring bell directly because Claude Code is a TUI that would receive the keys
if [[ -n "${TMUX:-}" && -n "${TMUX_PANE:-}" ]]; then
  # Set custom window option to flag this window needs attention
  tmux set-window-option -t "$TMUX_PANE" @claude_attention 1

  # Also set session-level flag so it shows in session chooser
  session_name=$(tmux display-message -p '#S')
  tmux set-option -t "$session_name" @session_needs_attention 1
fi
