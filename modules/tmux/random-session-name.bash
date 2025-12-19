#!/usr/bin/env bash
set -eou pipefail

# Rename tmux session to a random Simpsons-themed word if the session has a default numeric name

show_help() {
  echo "random-session-name - Rename tmux session to random Simpsons word"
  echo
  echo "USAGE:"
  echo "  random-session-name    Rename current tmux session to random Simpsons word"
  echo
  echo "DESCRIPTION:"
  echo "  If the current tmux session has a default numeric name (0, 1, 2, etc.),"
  echo "  this script renames it to a random Simpsons-themed word. It checks for"
  echo "  name collisions with existing sessions and will try up to 10 times to"
  echo "  find a unique name. If all attempts fail, the session keeps its default name."
  echo
  echo "  Sessions with custom names are not renamed."
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

# SIMPSONS_WORDS array is injected by Nix from simpsons-words.bash

# Get current session name
CURRENT_NAME=$(tmux display-message -p '#S')

# Check if current name is a default numeric name (0, 1, 2, etc.)
# If not, exit without renaming (user already gave it a custom name)
if ! [[ "$CURRENT_NAME" =~ ^[0-9]+$ ]]; then
  exit 0
fi

# Get list of existing session names (excluding the current session)
EXISTING_SESSIONS=$(tmux list-sessions -F '#S' | grep -v "^${CURRENT_NAME}$" || true)

# Try up to 10 times to find a unique random name
MAX_ATTEMPTS=10
for ((i=0; i<MAX_ATTEMPTS; i++)); do
  # Select random word from array
  RANDOM_INDEX=$((RANDOM % ${#SIMPSONS_WORDS[@]}))
  NEW_NAME="${SIMPSONS_WORDS[$RANDOM_INDEX]}"

  # Check if this name already exists in the session list
  if ! echo "$EXISTING_SESSIONS" | grep -qxF "$NEW_NAME"; then
    # Name is unique, rename the session and exit
    tmux rename-session "$NEW_NAME"
    exit 0
  fi
done

# If we get here, all 10 attempts found collisions
# Gracefully exit and keep the default numeric name
exit 0
