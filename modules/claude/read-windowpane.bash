#!/usr/bin/env bash

show_help() {
  echo "read-windowpane - Capture recent output from one or more tmux window panes"
  echo
  echo "USAGE:"
  echo "  read-windowpane <window.pane>[,<window.pane>...] [lines]"
  echo
  echo "ARGUMENTS:"
  echo "  window.pane   tmux target in window.pane format (e.g. 'pricing.0')"
  echo "                Multiple targets may be comma-separated (e.g. 'pricing.0,auth.0')"
  echo "  lines         Number of lines to capture per target (default: 50)"
  echo
  echo "DESCRIPTION:"
  echo "  Captures the last N lines of output from each named tmux pane and"
  echo "  writes them to stdout."
  echo
  echo "  Window names are resolved across all sessions in the current tmux server."
  echo "  Each target MUST be in window.pane format — the bare window name is"
  echo "  rejected to prevent silent misrouting to the wrong pane."
  echo
  echo "  When multiple targets are given, output is headered per target."
  echo
  echo "EXAMPLES:"
  echo "  read-windowpane pricing.0"
  echo "  read-windowpane pricing.0 200"
  echo "  read-windowpane pricing.0,auth.0,docs.0 100"
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

if [[ $# -lt 1 ]]; then
  echo "Error: window.pane target(s) are required" >&2
  echo "Usage: read-windowpane <window.pane>[,<window.pane>...] [lines]" >&2
  exit 1
fi

targets_arg="$1"
lines="${2:-50}"

if ! [[ "$lines" =~ ^[0-9]+$ ]]; then
  echo "Error: lines must be numeric, got '${lines}'" >&2
  exit 1
fi

# Build lookup of window name → session:window_index (first-match semantics)
declare -A window_lookup=()
while IFS= read -r line; do
  session_window="${line%%:*}"
  rest="${line#*:}"
  index="${rest%%:*}"
  name_part="${rest#*: }"
  name="${name_part%% *}"
  if [[ -z "${window_lookup[$name]:-}" ]]; then
    window_lookup["$name"]="${session_window}:${index}"
  fi
done < <(tmux list-windows -a -F "#{session_name}:#{window_index}: #{window_name}" 2>/dev/null || true)

# Validate all targets upfront
resolved_targets=()
raw_target_names=()
IFS=',' read -ra raw_targets <<< "$targets_arg"

for raw in "${raw_targets[@]}"; do
  raw="${raw#"${raw%%[![:space:]]*}"}"
  raw="${raw%"${raw##*[![:space:]]}"}"

  if [[ -z "$raw" ]]; then
    continue
  fi

  if [[ "$raw" != *.* ]]; then
    echo "Error: read-windowpane requires window.pane format (e.g. 'pa-service.0'), got '${raw}'" >&2
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
  raw_target_names+=("$raw")
done

if [[ ${#resolved_targets[@]} -eq 0 ]]; then
  echo "Error: no valid targets specified" >&2
  exit 1
fi

# Capture output. Header per target only when multiple targets given.
multi=0
if [[ ${#resolved_targets[@]} -gt 1 ]]; then
  multi=1
fi

for i in "${!resolved_targets[@]}"; do
  target="${resolved_targets[$i]}"
  raw_name="${raw_target_names[$i]}"
  if [[ $multi -eq 1 ]]; then
    echo "--- ${raw_name} ---"
  fi
  tmux capture-pane -t "$target" -p -S "-${lines}"
  if [[ $multi -eq 1 ]]; then
    echo ""
  fi
done
