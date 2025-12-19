#!/usr/bin/env bash
set -eou pipefail

# Select and set random emoji for tmux session icon

show_help() {
  echo "random-session-icon - Set random emoji for tmux session icon"
  echo
  echo "USAGE:"
  echo "  random-session-icon    Set random emoji icon for current tmux session"
  echo
  echo "DESCRIPTION:"
  echo "  Selects a random emoji from a predefined list and sets it as the"
  echo "  tmux session icon that appears in the status bar next to the session name."
  echo "  Each session gets its own unique icon that persists until the session ends."
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

# EMOJIS array is injected by Nix from emojis.bash

# Select random emoji from array
RANDOM_EMOJI="${EMOJIS[$RANDOM % ${#EMOJIS[@]}]}"

# Get current session name
SESSION_NAME=$(tmux display-message -p '#S')

# Set session-scoped tmux option (NOT global -g flag)
# This ensures each session has its own icon
tmux set-option -t "$SESSION_NAME" @session_icon "$RANDOM_EMOJI"
