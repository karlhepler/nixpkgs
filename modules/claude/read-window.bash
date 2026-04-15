#!/usr/bin/env bash

show_help() {
  echo "read-window - Capture recent output from a tmux window"
  echo
  echo "USAGE:"
  echo "  read-window <window-name> [lines]"
  echo
  echo "ARGUMENTS:"
  echo "  window-name   Name of the tmux window to capture output from"
  echo "  lines         Number of lines to capture (default: 50)"
  echo
  echo "DESCRIPTION:"
  echo "  Captures the last N lines of output from the named tmux window"
  echo "  and writes them to stdout."
  echo
  echo "  The target window is resolved by name across all sessions in the"
  echo "  current tmux server."
  echo
  echo "EXAMPLES:"
  echo "  read-window pricing"
  echo "  read-window auth 30"
  echo
  echo "ERROR CONDITIONS:"
  echo "  Exits with error if the window name is not found in any tmux session."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Error: window-name is required" >&2
  echo "Usage: read-window <window-name> [lines]" >&2
  exit 1
fi

window_name="$1"
lines="${2:-50}"

# Verify the window exists by searching all sessions
window_target=""
while IFS= read -r line; do
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

# Capture the last N lines from the window's pane
tmux capture-pane -t "$window_target" -p -S "-${lines}"
