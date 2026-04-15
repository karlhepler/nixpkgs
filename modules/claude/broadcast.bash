#!/usr/bin/env bash

show_help() {
  echo "broadcast - Send the same message to multiple tmux windows"
  echo
  echo "USAGE:"
  echo "  broadcast <window1,window2,...> <message>"
  echo
  echo "ARGUMENTS:"
  echo "  window1,window2,...   Comma-separated list of tmux window names"
  echo "  message               Message to send (remaining arguments joined with spaces)"
  echo
  echo "DESCRIPTION:"
  echo "  Sends the same message to each named tmux window by invoking 'tell'"
  echo "  for each window in the list."
  echo
  echo "  Windows that don't exist are reported but do not stop delivery to"
  echo "  the remaining windows."
  echo
  echo "EXAMPLES:"
  echo "  broadcast pricing,auth 'New deployment is live'"
  echo "  broadcast frontend,backend,infra check your queues"
  echo
  echo "ERROR CONDITIONS:"
  echo "  Reports any windows that could not be found, but exits 0 if at"
  echo "  least one window received the message."
  echo "  Exits with error if the window list or message is missing."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Error: window list and message are required" >&2
  echo "Usage: broadcast <window1,window2,...> <message>" >&2
  exit 1
fi

windows_arg="$1"
shift
message="$*"

# Split comma-separated window names into an array
IFS=',' read -ra windows <<< "$windows_arg"

failed_windows=()
success_count=0

for window in "${windows[@]}"; do
  # Trim whitespace
  window="${window#"${window%%[![:space:]]*}"}"
  window="${window%"${window##*[![:space:]]}"}"

  if [[ -z "$window" ]]; then
    continue
  fi

  if tell "$window" "$message" 2>/dev/null; then
    success_count=$((success_count + 1))
  else
    failed_windows+=("$window")
    echo "Warning: window '${window}' not found — skipping" >&2
  fi
done

if [[ ${#failed_windows[@]} -gt 0 ]]; then
  echo "broadcast: ${success_count} window(s) received the message, ${#failed_windows[@]} not found: ${failed_windows[*]}" >&2
fi

if [[ $success_count -eq 0 && ${#failed_windows[@]} -gt 0 ]]; then
  echo "Error: no windows received the message" >&2
  exit 1
fi

exit 0
