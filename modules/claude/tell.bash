#!/usr/bin/env bash

show_help() {
  echo "tell - Send a message to a named tmux window"
  echo
  echo "USAGE:"
  echo "  tell <window-name> <message>"
  echo
  echo "ARGUMENTS:"
  echo "  window-name   Name of the tmux window to send the message to"
  echo "  message       Message to send (remaining arguments joined with spaces)"
  echo
  echo "DESCRIPTION:"
  echo "  Sends a message string followed by Enter to the named tmux window."
  echo "  Enter is sent as a separate tmux send-keys call to ensure the message"
  echo "  is submitted rather than sitting in the input buffer."
  echo
  echo "  The target window is resolved by name across all sessions in the"
  echo "  current tmux server."
  echo
  echo "EXAMPLES:"
  echo "  tell pricing 'What is the current status?'"
  echo "  tell auth check the OAuth2 flow"
  echo
  echo "ERROR CONDITIONS:"
  echo "  Exits with error if the window name is not found in any tmux session."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Error: window-name and message are required" >&2
  echo "Usage: tell <window-name> <message>" >&2
  exit 1
fi

window_name="$1"
shift
message="$*"

# Verify the window exists by searching all sessions
window_target=""
while IFS= read -r line; do
  # tmux list-windows -a format: session:index: name (flags) [...]
  # We extract "session:index" and "name" from each line
  session_window="${line%%:*}"
  rest="${line#*:}"
  index="${rest%%:*}"
  name_part="${rest#*: }"
  name="${name_part%% *}"
  if [[ "$name" == "$window_name" ]]; then
    window_target="${session_window}:${index}"
    break
  fi
done < <(tmux list-windows -a -F "#{session_name}:#{window_index}: #{window_name}" 2>/dev/null || true)

if [[ -z "$window_target" ]]; then
  echo "Error: tmux window '${window_name}' not found" >&2
  echo "Available windows:" >&2
  tmux list-windows -a -F "  #{session_name}:#{window_name}" 2>/dev/null >&2 || echo "  (no tmux sessions running)" >&2
  exit 1
fi

# Send the message to the window — message and Enter must be separate send-keys calls.
# Without the separate Enter, the message sits in the input buffer and is never submitted.
tmux send-keys -t "$window_target" "$message"
tmux send-keys -t "$window_target" Enter
