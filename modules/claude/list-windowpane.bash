#!/usr/bin/env bash

show_help() {
  echo "list-windowpane - Overview of all tmux windows, panes, and recent output"
  echo
  echo "USAGE:"
  echo "  list-windowpane [lines]"
  echo
  echo "ARGUMENTS:"
  echo "  lines   Snippet lines per pane (default: 3)"
  echo
  echo "DESCRIPTION:"
  echo "  Prints a structured overview of every window and pane across all tmux"
  echo "  sessions, along with each pane's running command and a short snippet"
  echo "  of its most recent output."
  echo
  echo "  Intended as a 'lay of the land' command for Senior Staff to survey"
  echo "  active work and reconcile its roster against tmux reality. For deep"
  echo "  reads of specific panes, use read-windowpane."
  echo
  echo "EXAMPLES:"
  echo "  list-windowpane         # 3-line snippets per pane"
  echo "  list-windowpane 10      # 10-line snippets per pane"
  echo
  echo "OUTPUT FORMAT:"
  echo "  === <window> (session: <session>) ==="
  echo "    [<pane-index>] <current-command>"
  echo "        <recent-output-line-1>"
  echo "        <recent-output-line-2>"
  echo "        ..."
  echo
  echo "  Empty panes are shown as '[no recent output]' rather than omitted —"
  echo "  the presence of the pane is information, even when silent."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

lines="${1:-3}"

if ! [[ "$lines" =~ ^[0-9]+$ ]]; then
  echo "Error: lines must be numeric, got '${lines}'" >&2
  exit 1
fi

# Gather all panes across all sessions
# Format: session|window_index|window_name|pane_index|pane_current_command
panes_raw="$(tmux list-panes -a -F '#{session_name}|#{window_index}|#{window_name}|#{pane_index}|#{pane_current_command}' 2>/dev/null || true)"

if [[ -z "$panes_raw" ]]; then
  echo "(no tmux sessions running)"
  exit 0
fi

prev_window_key=""
first_block=1

while IFS='|' read -r session window_index window_name pane_index pane_cmd; do
  window_key="${session}:${window_index}"

  if [[ "$window_key" != "$prev_window_key" ]]; then
    # New window block
    if [[ $first_block -eq 0 ]]; then
      echo ""
    fi
    echo "=== ${window_name} (session: ${session}) ==="
    prev_window_key="$window_key"
    first_block=0
  fi

  echo "  [${pane_index}] ${pane_cmd}"

  target="${session}:${window_index}.${pane_index}"
  snippet="$(tmux capture-pane -t "$target" -p -S "-${lines}" 2>/dev/null || true)"

  if [[ -z "$snippet" ]]; then
    echo "      [no recent output]"
  else
    while IFS= read -r snippet_line; do
      echo "      ${snippet_line}"
    done <<< "$snippet"
  fi
done <<< "$panes_raw"

exit 0
