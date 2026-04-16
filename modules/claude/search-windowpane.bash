#!/usr/bin/env bash

show_help() {
  echo "search-windowpane - Search tmux scrollback across all windowpanes"
  echo
  echo "USAGE:"
  echo "  search-windowpane <pattern> [lines]"
  echo
  echo "ARGUMENTS:"
  echo "  pattern   Text or regex to search for (passed to rg)"
  echo "  lines     Search only the most recent N lines per pane (default: full scrollback)"
  echo
  echo "DESCRIPTION:"
  echo "  Searches the scrollback buffer of every pane across all tmux sessions"
  echo "  for the given pattern. Results are grouped by window.pane with matching"
  echo "  lines indented beneath each header."
  echo
  echo "  Panes with no matches are omitted from output."
  echo
  echo "EXAMPLES:"
  echo "  search-windowpane 'review'              # full scrollback, all panes"
  echo "  search-windowpane 'Tier 1' 500          # last 500 lines per pane"
  echo "  search-windowpane 'kanban done'"
  echo
  echo "EXIT STATUS:"
  echo "  0  At least one match found"
  echo "  1  No matches found (or no tmux sessions)"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Error: pattern is required" >&2
  echo "Usage: search-windowpane <pattern> [lines]" >&2
  exit 1
fi

pattern="$1"
lines="${2:-}"

if [[ -n "$lines" ]] && ! [[ "$lines" =~ ^[0-9]+$ ]]; then
  echo "Error: lines must be numeric, got '${lines}'" >&2
  exit 1
fi

# Gather all panes across all sessions
panes_raw="$(tmux list-panes -a -F '#{session_name}|#{window_index}|#{window_name}|#{pane_index}' 2>/dev/null || true)"

if [[ -z "$panes_raw" ]]; then
  echo "(no tmux sessions running)" >&2
  exit 1
fi

found_any=0

while IFS='|' read -r session window_index window_name pane_index; do
  target="${session}:${window_index}.${pane_index}"
  label="${window_name}.${pane_index}"

  # Capture scrollback: full history (-S -) or last N lines (-S -N)
  if [[ -n "$lines" ]]; then
    buffer="$(tmux capture-pane -t "$target" -p -S "-${lines}" 2>/dev/null || true)"
  else
    buffer="$(tmux capture-pane -t "$target" -p -S - 2>/dev/null || true)"
  fi

  if [[ -z "$buffer" ]]; then
    continue
  fi

  # Search for pattern in this pane's buffer
  matches="$(printf '%s\n' "$buffer" | rg "$pattern" 2>/dev/null || true)"

  if [[ -n "$matches" ]]; then
    if [[ $found_any -eq 1 ]]; then
      echo ""
    fi
    echo "=== ${label} ==="
    while IFS= read -r line; do
      echo "  ${line}"
    done <<< "$matches"
    found_any=1
  fi
done <<< "$panes_raw"

if [[ $found_any -eq 0 ]]; then
  exit 1
fi

exit 0
