#!/usr/bin/env bash
set -euo pipefail

# perm - Claude Code permission manager
#
# Manages Claude Code permissions in .claude/settings.local.json
# Tracks temporary vs permanent patterns for lifecycle cleanup.
#
# SUBCOMMANDS:
#   perm [--session <id>] allow <pattern>    Add pattern as temporary permission (session-scoped)
#   perm always <pattern>                    Add pattern as permanent permission
#   perm [--session <id>] cleanup            Remove temporary permissions owned by given session
#   perm list                                Show tracked permissions with labels
#
# FILES:
#   .claude/settings.local.json  - Claude Code local settings
#   .claude/.perm-tracking.json  - Tracks temporary/permanent patterns
#
# TRACKING FORMAT:
#   {
#     "temporary": {
#       "Bash(npm run lint)": ["fair-drift", "cool-vale"]
#     },
#     "permanent": ["Bash(npm run test)"]
#   }

show_help() {
  cat <<'EOF'
perm - Claude Code permission manager

USAGE:
  perm --session <id> allow <pattern>    Add pattern as temporary permission (cleaned up on perm cleanup)
  perm always <pattern>                  Add pattern as permanent permission (never cleaned up)
  perm --session <id> cleanup            Remove temporary permissions owned by the given session
  perm list                              Show tracked permissions with labels
  perm --help                            Show this help message

OPTIONS:
  --session <id>    Session identifier (required for allow and cleanup subcommands).
                    Can be a kanban friendly name, a Claude session UUID, or any
                    arbitrary string. Not session-scoped; any identifier works.

DESCRIPTION:
  Manages Claude Code permissions in .claude/settings.local.json.
  All paths are relative to the git repository root.

  Tracking is stored in .claude/.perm-tracking.json to distinguish
  temporary permissions (granted for a session) from permanent ones.

  Temporary permissions are session-scoped. Multiple sessions can hold
  the same temporary permission; cleanup only removes the given session's
  claim. The permission is removed from settings only when no sessions hold it.

EXAMPLES:
  perm --session abc123 allow "Bash(npm run lint)"
  perm always "Bash(npm run test)"
  perm --session abc123 cleanup
  perm list

EOF
}

# Find git repo root — Nix guarantees git is available
repo_root="$(git rev-parse --show-toplevel)"
settings_file="${repo_root}/.claude/settings.local.json"
tracking_file="${repo_root}/.claude/.perm-tracking.json"

# Ensure .claude directory exists
mkdir -p "${repo_root}/.claude"

# Initialize settings.local.json if absent or missing required keys
init_settings() {
  if [[ ! -f "${settings_file}" ]]; then
    echo '{"permissions":{"allow":[]}}' | jq . > "${settings_file}"
    return
  fi

  # Ensure permissions key exists
  local has_permissions
  has_permissions="$(jq 'has("permissions")' "${settings_file}")"
  if [[ "${has_permissions}" == "false" ]]; then
    jq '.permissions = {"allow":[]}' "${settings_file}" > "${settings_file}.tmp"
    mv "${settings_file}.tmp" "${settings_file}"
    return
  fi

  # Ensure permissions.allow key exists
  local has_allow
  has_allow="$(jq '.permissions | has("allow")' "${settings_file}")"
  if [[ "${has_allow}" == "false" ]]; then
    jq '.permissions.allow = []' "${settings_file}" > "${settings_file}.tmp"
    mv "${settings_file}.tmp" "${settings_file}"
  fi
}

# Initialize .perm-tracking.json if absent.
# Migrates old array-based temporary format to the new object format.
init_tracking() {
  if [[ ! -f "${tracking_file}" ]]; then
    echo '{"temporary":{},"permanent":[]}' | jq . > "${tracking_file}"
    return
  fi

  # Migrate old format: temporary was an array, now it is an object
  local temp_is_array
  temp_is_array="$(jq '.temporary | type == "array"' "${tracking_file}")"
  if [[ "${temp_is_array}" == "true" ]]; then
    jq '.temporary = {}' "${tracking_file}" > "${tracking_file}.tmp"
    mv "${tracking_file}.tmp" "${tracking_file}"
  fi
}

# Check if a pattern is already in settings.local.json permissions.allow
pattern_in_settings() {
  local pattern="$1"
  jq --arg p "${pattern}" '.permissions.allow | index($p) != null' "${settings_file}"
}

# Check if a pattern is already tracked under permanent
pattern_in_permanent() {
  local pattern="$1"
  jq --arg p "${pattern}" '.permanent | index($p) != null' "${tracking_file}"
}

# Add a pattern to settings.local.json permissions.allow (idempotent)
add_to_settings() {
  local pattern="$1"
  local already_in_settings
  already_in_settings="$(pattern_in_settings "${pattern}")"

  if [[ "${already_in_settings}" == "true" ]]; then
    return
  fi

  jq --arg p "${pattern}" '.permissions.allow += [$p]' "${settings_file}" > "${settings_file}.tmp"
  mv "${settings_file}.tmp" "${settings_file}"
}

# Add session to the temporary pattern's session array (idempotent)
add_to_temporary() {
  local pattern="$1"
  local session="$2"

  # If pattern doesn't exist in temporary, create it with [session].
  # If it exists, append session only if not already present.
  jq --arg p "${pattern}" --arg s "${session}" '
    if .temporary | has($p) then
      if (.temporary[$p] | index($s)) != null then
        .
      else
        .temporary[$p] += [$s]
      end
    else
      .temporary[$p] = [$s]
    end
  ' "${tracking_file}" > "${tracking_file}.tmp"
  mv "${tracking_file}.tmp" "${tracking_file}"
}

# Add a pattern to permanent tracking (idempotent)
add_to_permanent() {
  local pattern="$1"
  local already_tracked
  already_tracked="$(pattern_in_permanent "${pattern}")"

  if [[ "${already_tracked}" == "true" ]]; then
    return
  fi

  jq --arg p "${pattern}" '.permanent += [$p]' "${tracking_file}" > "${tracking_file}.tmp"
  mv "${tracking_file}.tmp" "${tracking_file}"
}

# Remove a pattern from settings.local.json permissions.allow
remove_from_settings() {
  local pattern="$1"
  jq --arg p "${pattern}" '.permissions.allow = [.permissions.allow[] | select(. != $p)]' \
    "${settings_file}" > "${settings_file}.tmp"
  mv "${settings_file}.tmp" "${settings_file}"
}

cmd_allow() {
  local session="$1"
  local pattern="$2"

  if [[ -z "${session}" ]]; then
    echo "Error: --session <id> is required for 'allow'" >&2
    echo "Usage: perm --session <id> allow <pattern>" >&2
    exit 1
  fi

  if [[ -z "${pattern}" ]]; then
    echo "Error: pattern required" >&2
    echo "Usage: perm --session <id> allow <pattern>" >&2
    exit 1
  fi

  init_settings
  init_tracking
  add_to_settings "${pattern}"
  add_to_temporary "${pattern}" "${session}"
  echo "Allowed (temporary): ${pattern}"
}

cmd_always() {
  local pattern="${1:-}"
  if [[ -z "${pattern}" ]]; then
    echo "Error: pattern required" >&2
    echo "Usage: perm always <pattern>" >&2
    exit 1
  fi

  init_settings
  init_tracking
  add_to_settings "${pattern}"
  add_to_permanent "${pattern}"
  echo "Allowed (permanent): ${pattern}"
}

cmd_cleanup() {
  local session="$1"

  if [[ -z "${session}" ]]; then
    echo "Error: --session <id> is required for 'cleanup'" >&2
    echo "Usage: perm --session <id> cleanup" >&2
    exit 1
  fi

  init_settings
  init_tracking

  # Get all temporary patterns
  local temp_count
  temp_count="$(jq '.temporary | length' "${tracking_file}")"

  if [[ "${temp_count}" -eq 0 ]]; then
    echo "No temporary permissions to clean up."
    return
  fi

  # Find patterns owned by this session
  local owned_patterns
  owned_patterns="$(jq -r --arg s "${session}" \
    '.temporary | to_entries[] | select(.value | index($s) != null) | .key' \
    "${tracking_file}")"

  if [[ -z "${owned_patterns}" ]]; then
    echo "No temporary permissions owned by session '${session}'."
    return
  fi

  local removed_count=0

  while IFS= read -r pattern; do
    # Remove this session from the pattern's session array
    jq --arg p "${pattern}" --arg s "${session}" \
      '.temporary[$p] = [.temporary[$p][] | select(. != $s)]' \
      "${tracking_file}" > "${tracking_file}.tmp"
    mv "${tracking_file}.tmp" "${tracking_file}"

    # If session array is now empty, remove from both files
    local remaining
    remaining="$(jq --arg p "${pattern}" '.temporary[$p] | length' "${tracking_file}")"

    if [[ "${remaining}" -eq 0 ]]; then
      remove_from_settings "${pattern}"
      jq --arg p "${pattern}" 'del(.temporary[$p])' \
        "${tracking_file}" > "${tracking_file}.tmp"
      mv "${tracking_file}.tmp" "${tracking_file}"
      removed_count=$((removed_count + 1))
    fi
  done <<< "${owned_patterns}"

  local total_owned
  total_owned="$(echo "${owned_patterns}" | wc -l | tr -d ' ')"

  if [[ "${removed_count}" -eq "${total_owned}" ]]; then
    echo "Cleaned up ${removed_count} temporary permission(s) (session: ${session})."
  else
    local kept=$((total_owned - removed_count))
    echo "Released session '${session}' from ${total_owned} permission(s)."
    echo "  Removed: ${removed_count} (no other sessions held them)"
    echo "  Kept:    ${kept} (still held by other sessions)"
  fi
}

cmd_list() {
  init_tracking

  local temp_count
  local perm_count
  temp_count="$(jq '.temporary | length' "${tracking_file}")"
  perm_count="$(jq '.permanent | length' "${tracking_file}")"

  if [[ "${temp_count}" -eq 0 && "${perm_count}" -eq 0 ]]; then
    echo "No tracked permissions."
    return
  fi

  if [[ "${temp_count}" -gt 0 ]]; then
    echo "Temporary:"
    jq -r '.temporary | to_entries[] | "\(.key)\t\(.value | join(", "))"' "${tracking_file}" \
      | while IFS=$'\t' read -r pattern sessions; do
          echo "  [temporary] ${pattern} (sessions: ${sessions})"
        done
  fi

  if [[ "${perm_count}" -gt 0 ]]; then
    echo "Permanent:"
    jq -r '.permanent[]' "${tracking_file}" | while IFS= read -r pattern; do
      echo "  [permanent] ${pattern}"
    done
  fi
}

# Parse global --session flag and subcommand.
# Accepted forms:
#   perm --session <id> <subcommand> [args...]
#   perm <subcommand> [args...]   (session not required for always/list)
session_id=""
subcommand=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      if [[ $# -lt 2 ]]; then
        echo "Error: --session requires an argument" >&2
        exit 1
      fi
      session_id="$2"
      shift 2
      ;;
    -h|--help|help)
      show_help
      exit 0
      ;;
    allow|always|cleanup|list)
      subcommand="$1"
      shift
      break
      ;;
    *)
      echo "Error: unknown option or subcommand '$1'" >&2
      echo "Run 'perm --help' for usage." >&2
      exit 1
      ;;
  esac
done

if [[ -z "${subcommand}" ]]; then
  echo "Error: subcommand required" >&2
  echo "Run 'perm --help' for usage." >&2
  exit 1
fi

case "${subcommand}" in
  allow)
    cmd_allow "${session_id}" "${1:-}"
    ;;
  always)
    cmd_always "${1:-}"
    ;;
  cleanup)
    cmd_cleanup "${session_id}"
    ;;
  list)
    cmd_list
    ;;
esac
