#!/usr/bin/env bash

show_help() {
  echo "senior-staff-staleness-hook - PreToolUse hook that polls Senior Staff session windows"
  echo
  echo "DESCRIPTION:"
  echo "  Internal hook script called automatically by Claude Code before Bash tool use."
  echo "  Should not be invoked manually by users."
  echo
  echo "PURPOSE:"
  echo "  Automatically refreshes Senior Staff session awareness by polling recent"
  echo "  output from each registered session window when the last poll is >60s stale."
  echo
  echo "TRIGGER:"
  echo "  PreToolUse(Bash) — fires before every Bash tool call."
  echo "  Only actually polls when .scratchpad/senior-staff-roster.json exists AND"
  echo "  .scratchpad/senior-staff-last-poll is missing or >60 seconds old."
  echo
  echo "ROSTER FORMAT:"
  echo "  .scratchpad/senior-staff-roster.json:"
  echo '  {"sessions":[{"window":"pricing","workstream":"Stripe pricing model"}]}'
  echo
  echo "STALENESS GATE:"
  echo "  Reads unix epoch from .scratchpad/senior-staff-last-poll."
  echo "  If missing or >60s old: polls all sessions, prints summary, updates timestamp."
  echo "  If <60s old: no-op (silent)."
  echo
  echo "CONFIGURATION:"
  echo "  Configured in modules/claude/default.nix as PreToolUse(Bash) hook."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

roster_file=".scratchpad/senior-staff-roster.json"
timestamp_file=".scratchpad/senior-staff-last-poll"
staleness_seconds=60

# Feature detection: no-op if roster doesn't exist
if [[ ! -f "$roster_file" ]]; then
  exit 0
fi

# Staleness check: read last poll timestamp
now="$(date +%s)"
last_poll=0

if [[ -f "$timestamp_file" ]]; then
  last_poll="$(cat "$timestamp_file" 2>/dev/null || echo 0)"
fi

age=$(( now - last_poll ))

if [[ $age -lt $staleness_seconds ]]; then
  # Not stale yet — no-op
  exit 0
fi

# Poll is stale (or first run) — gather session output
# Read the sessions array from roster JSON
sessions_json="$(jq -c '.sessions[]' "$roster_file" 2>/dev/null || true)"

if [[ -z "$sessions_json" ]]; then
  # Empty or malformed roster — update timestamp and exit
  echo "$now" > "$timestamp_file"
  exit 0
fi

# Print header for model visibility
echo "--- Senior Staff Session Update (${age}s since last poll) ---"

while IFS= read -r session_entry; do
  window="$(echo "$session_entry" | jq -r '.window // empty')"
  workstream="$(echo "$session_entry" | jq -r '.workstream // empty')"

  if [[ -z "$window" ]]; then
    continue
  fi

  echo ""
  echo "Session: ${window}${workstream:+ (${workstream})}"

  # Capture recent output from the window; report if window is missing
  window_output="$(read-window "$window" 30 2>&1)" || {
    echo "  [window '${window}' not found or could not be read]"
    continue
  }

  if [[ -z "$window_output" ]]; then
    echo "  [no recent output]"
  else
    # Indent output for readability
    while IFS= read -r output_line; do
      echo "  ${output_line}"
    done <<< "$window_output"
  fi
done <<< "$sessions_json"

echo ""
echo "--- End Senior Staff Session Update ---"

# Update the timestamp
echo "$now" > "$timestamp_file"

exit 0
