#!/usr/bin/env bash

show_help() {
  echo "tell-windowpane - Send a message to one or more tmux window panes"
  echo
  echo "USAGE:"
  echo "  tell-windowpane <window.pane>[,<window.pane>...] <message>"
  echo
  echo "ARGUMENTS:"
  echo "  window.pane   tmux target in window.pane format (e.g. 'pricing.0')"
  echo "                Multiple targets may be comma-separated (e.g. 'pricing.0,auth.0')"
  echo "  message       Message to send (remaining arguments joined with spaces)"
  echo
  echo "DESCRIPTION:"
  echo "  Sends a message string followed by Enter to one or more named tmux panes."
  echo "  For each target, message and Enter are sent as two separate send-keys"
  echo "  calls with a short sleep between them — this gives the target pane's"
  echo "  input handler time to process the message into its buffer before the"
  echo "  Enter keystroke submits it. Senior Staff never needs to send Enter"
  echo "  manually; this primitive handles it automatically."
  echo
  echo "  Window names are resolved across all sessions in the current tmux server."
  echo "  Each target MUST be in window.pane format — the bare window name is"
  echo "  rejected to prevent silent misrouting to the wrong pane (e.g. a shell"
  echo "  pane instead of the Claude pane)."
  echo
  echo "  Targets are validated upfront; no send occurs until every target is"
  echo "  resolved. Individual target send failures (e.g. tmux rejects a missing"
  echo "  pane index) surface as tmux errors and abort the run."
  echo
  echo "EXAMPLES:"
  echo "  tell-windowpane pricing.0 'Pause the Stripe work.'"
  echo "  tell-windowpane pricing.0,auth.0,docs.0 'Rename secrets from PA_* to PLATFORM_AUTOPILOT_*.'"
  echo
  echo "ERROR CONDITIONS:"
  echo "  Exits 1 if any target is missing a .pane suffix."
  echo "  Exits 1 if any target's pane index is non-numeric."
  echo "  Exits 1 if any target's window name cannot be resolved in tmux."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Error: window.pane target(s) and message are required" >&2
  echo "Usage: tell-windowpane <window.pane>[,<window.pane>...] <message>" >&2
  exit 1
fi

targets_arg="$1"
shift
message="$*"

# Build lookup of window name → session:window_index (first-match semantics)
declare -A window_lookup=()
while IFS= read -r line; do
  # tmux format: session:index: name (flags)
  session_window="${line%%:*}"
  rest="${line#*:}"
  index="${rest%%:*}"
  name_part="${rest#*: }"
  name="${name_part%% *}"
  if [[ -z "${window_lookup[$name]:-}" ]]; then
    window_lookup["$name"]="${session_window}:${index}"
  fi
done < <(tmux list-windows -a -F "#{session_name}:#{window_index}: #{window_name}" 2>/dev/null || true)

# Validate all targets upfront — loud failure for missing .pane, bad index, unresolved window
resolved_targets=()
IFS=',' read -ra raw_targets <<< "$targets_arg"

for raw in "${raw_targets[@]}"; do
  # Trim whitespace
  raw="${raw#"${raw%%[![:space:]]*}"}"
  raw="${raw%"${raw##*[![:space:]]}"}"

  if [[ -z "$raw" ]]; then
    continue
  fi

  # Require window.pane format
  if [[ "$raw" != *.* ]]; then
    echo "Error: tell-windowpane requires window.pane format (e.g. 'pa-service.0'), got '${raw}'" >&2
    exit 1
  fi

  window_name="${raw%.*}"
  pane_index="${raw##*.}"

  if ! [[ "$pane_index" =~ ^[0-9]+$ ]]; then
    echo "Error: pane index must be numeric, got '${pane_index}' in target '${raw}'" >&2
    exit 1
  fi

  target="${window_lookup[$window_name]:-}"
  if [[ -z "$target" ]]; then
    echo "Error: tmux window '${window_name}' not found (target '${raw}')" >&2
    echo "Available windows:" >&2
    tmux list-windows -a -F "  #{session_name}:#{window_name}" 2>/dev/null >&2 || echo "  (no tmux sessions running)" >&2
    exit 1
  fi

  resolved_targets+=("${target}.${pane_index}")
done

if [[ ${#resolved_targets[@]} -eq 0 ]]; then
  echo "Error: no valid targets specified" >&2
  exit 1
fi

# Send to each target. Message and Enter are two separate send-keys calls
# with a short sleep in between to let the target pane's input handler process
# the message before the Enter submits it.
for target in "${resolved_targets[@]}"; do
  tmux send-keys -t "$target" "$message"
  sleep 0.15
  tmux send-keys -t "$target" Enter
done
