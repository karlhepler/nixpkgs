#!/usr/bin/env bash
set -euo pipefail

# Pick and restore a tmux-resurrect snapshot via fzf

RESURRECT_DIR="${HOME}/.tmux/resurrect"

# Collect snapshot files sorted newest-first
mapfile -t snapshots < <(ls -t "${RESURRECT_DIR}"/tmux_resurrect_*.txt 2>/dev/null || true)

if [[ ${#snapshots[@]} -eq 0 ]]; then
  echo "No tmux-resurrect snapshots found in ${RESURRECT_DIR}" >&2
  exit 1
fi

# Build display list: human-readable timestamp -> file path
# Format: tmux_resurrect_20260311T222421.txt -> 2026-03-11 22:24:21
format_timestamp() {
  local filename
  filename="$(basename "$1")"
  local ts="${filename#tmux_resurrect_}"
  ts="${ts%.txt}"
  # ts is like 20260311T222421
  local date_part="${ts%%T*}"
  local time_part="${ts##*T}"
  local year="${date_part:0:4}"
  local month="${date_part:4:2}"
  local day="${date_part:6:2}"
  local hour="${time_part:0:2}"
  local min="${time_part:2:2}"
  local sec="${time_part:4:2}"
  echo "${year}-${month}-${day} ${hour}:${min}:${sec}"
}

# Build the list for fzf (display -> path mapping via NUL-delimited entries)
declare -a fzf_input
for snapshot in "${snapshots[@]}"; do
  human_ts="$(format_timestamp "${snapshot}")"
  fzf_input+=("${human_ts}	${snapshot}")
done

# Preview command: parse selected snapshot file and show sessions/windows
# shellcheck disable=SC2016
preview_cmd='awk -F"\t" '"'"'($1=="window") { sessions[$2] = sessions[$2] (sessions[$2] ? "\n  " : "  ") $4 } END { for (s in sessions) print s ":\n" sessions[s] }'"'"' {2}'

# Pipe into fzf with preview showing sessions/windows
selected="$(printf '%s\n' "${fzf_input[@]}" | fzf \
  --no-sort \
  --delimiter=$'\t' \
  --with-nth=1 \
  --preview="${preview_cmd}" \
  || true)"

# Exit silently if user cancelled
if [[ -z "${selected}" ]]; then
  exit 0
fi

selected_file="${selected#*$'\t'}"
selected_ts="${selected%%$'\t'*}"

# Update the last symlink
ln -sf "${selected_file}" "${RESURRECT_DIR}/last"

echo "Restored snapshot: ${selected_ts}"
echo "Press Ctrl-g Ctrl-r in tmux to restore"
