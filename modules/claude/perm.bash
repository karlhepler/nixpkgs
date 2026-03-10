#!/usr/bin/env bash
set -euo pipefail

# perm - Claude Code permission manager
#
# Manages Claude Code permissions in .claude/settings.local.json
# Tracks temporary vs permanent patterns for lifecycle cleanup.
#
# SUBCOMMANDS:
#   perm [--session <id>] allow <pattern> [<pattern> ...]    Add pattern(s) as temporary permission (session-scoped, timestamped)
#   perm always <pattern> [<pattern> ...]                    Add pattern(s) as permanent permission
#   perm [--session <id>] cleanup                            Remove temporary permissions owned by given session
#   perm cleanup-stale [--max-age <hours>]                   Remove temporary permissions older than max-age (default: 4h)
#   perm list                                                Show tracked permissions with labels and timestamps
#   perm check <pattern>                                     Check if pattern is approved across all settings files
#   perm nuke                                                Nuke ALL entries from permissions.allow (interactive, user-only)
#   perm session-hook                                        SessionStart hook: read JSON from stdin, print session UUID
#
# FILES:
#   .claude/settings.local.json  - Claude Code local settings
#   .claude/.perm-tracking.json  - Tracks temporary/permanent patterns
#
# TRACKING FORMAT:
#   {
#     "temporary": {
#       "Bash(npm run lint)": {"session-uuid-a": 1709000000, "session-uuid-b": 1709000100}
#     },
#     "permanent": ["Bash(npm run test)"]
#   }

show_help() {
  cat <<'EOF'
perm - Claude Code permission manager

USAGE:
  perm --session <id> allow <pattern> [<pattern> ...]      Add temporary permission(s) (session-scoped, timestamped)
  perm always <pattern> [<pattern> ...]                    Add permanent permission(s) (never cleaned up)
  perm --session <id> cleanup                              Remove temporary permissions owned by the given session
  perm cleanup-stale [--max-age <hours>]                   Remove temporary permissions older than max-age (default: 4h)
  perm list                                                Show tracked permissions with labels and timestamps
  perm check <pattern>                                     Check if pattern is approved across all settings files
  perm nuke                                                Nuke ALL entries from permissions.allow (interactive, user-only)
  perm session-hook                                        SessionStart hook: read JSON stdin, print session UUID
  perm --help                                              Show this help message

OPTIONS:
  --session <id>      Session identifier (required for allow and cleanup).
                      Use the perm session UUID printed at session start.
                      Controls ownership in .claude/.perm-tracking.json only — NOT written to settings.local.json.
  --max-age <hours>   Maximum age in hours for cleanup-stale (default: 4).

DESCRIPTION:
  Manages Claude Code permissions in .claude/settings.local.json.
  All paths are relative to the git repository root.

  Tracking is stored in .claude/.perm-tracking.json to distinguish
  temporary permissions (granted for a session) from permanent ones.
  The --session flag identifies the owner of a temporary claim in the
  tracking file and is never written to settings.local.json.

  Temporary permissions are session-scoped and timestamped. Multiple
  sessions can hold the same temporary permission; cleanup only removes
  the given session's claim. The permission is removed from settings
  only when no sessions hold it.

  cleanup-stale removes any temporary claims older than the specified
  max-age (default: 4 hours), regardless of session. Designed to run
  automatically at session start as a safety net for crashed or
  forgotten sessions.

  session-hook reads Claude Code SessionStart JSON from stdin and
  prints the session UUID for use with --session flags.

EXAMPLES:
  perm --session a1b2c3d4 allow "Bash(npm run lint)"
  perm --session a1b2c3d4 allow "Bash(npm run lint)" "Bash(npm run test *)" "Read(src/auth/**)"
  perm always "Bash(npm run test)"
  perm always "Bash(npm run test)" "Bash(npm run build)"
  perm --session a1b2c3d4 cleanup
  perm cleanup-stale
  perm cleanup-stale --max-age 2
  perm list
  perm check "Bash(kanban *)"
  perm check "Write(.scratchpad/**)"

EOF
}

# --- Lazy repo root resolution ---
# Not all subcommands need file access (e.g., session-hook).
# Functions that need files call ensure_repo first.
_repo_root=""
_settings_file=""
_tracking_file=""

ensure_repo() {
  if [[ -z "${_repo_root}" ]]; then
    _repo_root="$(git rev-parse --show-toplevel)"
    _settings_file="${_repo_root}/.claude/settings.local.json"
    _tracking_file="${_repo_root}/.claude/.perm-tracking.json"
    mkdir -p "${_repo_root}/.claude"
  fi
}

# Initialize settings.local.json if absent or missing required keys
init_settings() {
  ensure_repo

  if [[ ! -f "${_settings_file}" ]]; then
    echo '{"permissions":{"allow":[]}}' | jq . > "${_settings_file}"
    return
  fi

  # Ensure permissions key exists
  local has_permissions
  has_permissions="$(jq 'has("permissions")' "${_settings_file}")"
  if [[ "${has_permissions}" == "false" ]]; then
    jq '.permissions = {"allow":[]}' "${_settings_file}" > "${_settings_file}.tmp"
    mv "${_settings_file}.tmp" "${_settings_file}"
    return
  fi

  # Ensure permissions.allow key exists
  local has_allow
  has_allow="$(jq '.permissions | has("allow")' "${_settings_file}")"
  if [[ "${has_allow}" == "false" ]]; then
    jq '.permissions.allow = []' "${_settings_file}" > "${_settings_file}.tmp"
    mv "${_settings_file}.tmp" "${_settings_file}"
  fi
}

# Initialize .perm-tracking.json if absent.
# Migrates old formats to current session→timestamp object format.
init_tracking() {
  ensure_repo

  if [[ ! -f "${_tracking_file}" ]]; then
    echo '{"temporary":{},"permanent":[]}' | jq . > "${_tracking_file}"
    return
  fi

  # Migration 1: temporary was a flat array → now an object (keyed by pattern)
  local temp_is_array
  temp_is_array="$(jq '.temporary | type == "array"' "${_tracking_file}")"
  if [[ "${temp_is_array}" == "true" ]]; then
    jq '.temporary = {}' "${_tracking_file}" > "${_tracking_file}.tmp"
    mv "${_tracking_file}.tmp" "${_tracking_file}"
  fi

  # Migration 2: temporary values were session arrays → now session→timestamp objects
  # Detect: if any value in .temporary is an array, migrate all to objects with current timestamp
  local has_array_values
  has_array_values="$(jq '[.temporary | to_entries[] | .value | type] | any(. == "array")' "${_tracking_file}")"
  if [[ "${has_array_values}" == "true" ]]; then
    local now
    now="$(date +%s)"
    jq --argjson now "${now}" '
      .temporary |= with_entries(
        if (.value | type) == "array" then
          .value = (.value | map({(.): $now}) | add // {})
        else . end
      )
    ' "${_tracking_file}" > "${_tracking_file}.tmp"
    mv "${_tracking_file}.tmp" "${_tracking_file}"
  fi
}

# Check if a pattern is already in settings.local.json permissions.allow
pattern_in_settings() {
  local pattern="$1"
  jq --arg p "${pattern}" '.permissions.allow | index($p) != null' "${_settings_file}"
}

# Check if a pattern is already tracked under permanent
pattern_in_permanent() {
  local pattern="$1"
  jq --arg p "${pattern}" '.permanent | index($p) != null' "${_tracking_file}"
}

# Add a pattern to settings.local.json permissions.allow (idempotent).
add_to_settings() {
  local pattern="$1"
  local already_in_settings
  already_in_settings="$(pattern_in_settings "${pattern}")"
  if [[ "${already_in_settings}" == "true" ]]; then
    return
  fi
  jq --arg p "${pattern}" '.permissions.allow += [$p]' "${_settings_file}" > "${_settings_file}.tmp"
  mv "${_settings_file}.tmp" "${_settings_file}"
}

# Add session claim with timestamp to the temporary pattern (idempotent, updates timestamp)
add_to_temporary() {
  local pattern="$1"
  local session="$2"
  local now
  now="$(date +%s)"

  jq --arg p "${pattern}" --arg s "${session}" --argjson now "${now}" '
    if .temporary | has($p) then
      .temporary[$p][$s] = $now
    else
      .temporary[$p] = {($s): $now}
    end
  ' "${_tracking_file}" > "${_tracking_file}.tmp"
  mv "${_tracking_file}.tmp" "${_tracking_file}"
}

# Add a pattern to permanent tracking (idempotent)
add_to_permanent() {
  local pattern="$1"
  local already_tracked
  already_tracked="$(pattern_in_permanent "${pattern}")"

  if [[ "${already_tracked}" == "true" ]]; then
    return
  fi

  jq --arg p "${pattern}" '.permanent += [$p]' "${_tracking_file}" > "${_tracking_file}.tmp"
  mv "${_tracking_file}.tmp" "${_tracking_file}"
}

# Remove a pattern from settings.local.json permissions.allow.
remove_from_settings() {
  local pattern="$1"
  jq --arg p "${pattern}" '.permissions.allow = [.permissions.allow[] | select(. != $p)]' \
    "${_settings_file}" > "${_settings_file}.tmp"
  mv "${_settings_file}.tmp" "${_settings_file}"
}

cmd_allow() {
  local session="$1"
  shift  # Remove session_id from args, remaining args are patterns
  local patterns=("$@")

  if [[ -z "${session}" ]]; then
    echo "Error: --session <id> is required for 'allow'" >&2
    echo "Usage: perm --session <id> allow <pattern> [<pattern> ...]" >&2
    exit 1
  fi

  if [[ ${#patterns[@]} -eq 0 ]]; then
    echo "Error: at least one pattern required" >&2
    echo "Usage: perm --session <id> allow <pattern> [<pattern> ...]" >&2
    exit 1
  fi

  init_settings
  init_tracking

  for pattern in "${patterns[@]}"; do
    add_to_settings "${pattern}"
    add_to_temporary "${pattern}" "${session}"
    echo "Allowed (temporary): ${pattern}"
  done
}

cmd_always() {
  local patterns=("$@")

  if [[ ${#patterns[@]} -eq 0 ]]; then
    echo "Error: at least one pattern required" >&2
    echo "Usage: perm always <pattern> [<pattern> ...]" >&2
    exit 1
  fi

  init_settings
  init_tracking

  for pattern in "${patterns[@]}"; do
    add_to_settings "${pattern}"
    add_to_permanent "${pattern}"
    echo "Allowed (permanent): ${pattern}"
  done
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
  temp_count="$(jq '.temporary | length' "${_tracking_file}")"

  if [[ "${temp_count}" -eq 0 ]]; then
    echo "No temporary permissions to clean up."
    return
  fi

  # Find patterns that have a claim from this session
  local owned_patterns
  owned_patterns="$(jq -r --arg s "${session}" \
    '.temporary | to_entries[] | select(.value | has($s)) | .key' \
    "${_tracking_file}")"

  if [[ -z "${owned_patterns}" ]]; then
    echo "No temporary permissions owned by session '${session}'."
    return
  fi

  local removed_count=0

  while IFS= read -r pattern; do
    # Remove this session's claim from the pattern
    jq --arg p "${pattern}" --arg s "${session}" \
      'del(.temporary[$p][$s])' \
      "${_tracking_file}" > "${_tracking_file}.tmp"
    mv "${_tracking_file}.tmp" "${_tracking_file}"

    # If no claims remain, remove from both files
    local remaining
    remaining="$(jq --arg p "${pattern}" '.temporary[$p] | length' "${_tracking_file}")"

    if [[ "${remaining}" -eq 0 ]]; then
      remove_from_settings "${pattern}"
      jq --arg p "${pattern}" 'del(.temporary[$p])' \
        "${_tracking_file}" > "${_tracking_file}.tmp"
      mv "${_tracking_file}.tmp" "${_tracking_file}"
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

cmd_cleanup_stale() {
  local max_age_hours="${1:-4}"

  # Gracefully exit if not in a git repo (safety net — may run outside repos)
  ensure_repo 2>/dev/null || return 0

  # Gracefully exit if tracking file doesn't exist yet
  if [[ ! -f "${_tracking_file}" ]]; then
    return
  fi

  init_settings
  init_tracking

  local temp_count
  temp_count="$(jq '.temporary | length' "${_tracking_file}")"

  if [[ "${temp_count}" -eq 0 ]]; then
    return  # Silent — this is a background safety net
  fi

  local now max_age_seconds cutoff
  now="$(date +%s)"
  max_age_seconds=$((max_age_hours * 3600))
  cutoff=$((now - max_age_seconds))

  # Find patterns that have at least one stale claim
  local stale_patterns
  stale_patterns="$(jq -r --argjson cutoff "${cutoff}" '
    .temporary | to_entries[]
    | select(.value | to_entries | any(.value < $cutoff))
    | .key
  ' "${_tracking_file}")" || true

  if [[ -z "${stale_patterns}" ]]; then
    return  # Silent
  fi

  local stale_count=0

  while IFS= read -r pattern; do
    # Remove stale claims from this pattern
    jq --arg p "${pattern}" --argjson cutoff "${cutoff}" '
      .temporary[$p] |= with_entries(select(.value >= $cutoff))
    ' "${_tracking_file}" > "${_tracking_file}.tmp"
    mv "${_tracking_file}.tmp" "${_tracking_file}"

    # If no claims remain, remove from both files
    local remaining
    remaining="$(jq --arg p "${pattern}" '.temporary[$p] | length' "${_tracking_file}")"

    if [[ "${remaining}" -eq 0 ]]; then
      remove_from_settings "${pattern}"
      jq --arg p "${pattern}" 'del(.temporary[$p])' \
        "${_tracking_file}" > "${_tracking_file}.tmp"
      mv "${_tracking_file}.tmp" "${_tracking_file}"
      stale_count=$((stale_count + 1))
    fi
  done <<< "${stale_patterns}"

  if [[ "${stale_count}" -gt 0 ]]; then
    echo "Cleaned up ${stale_count} stale temporary permission(s) (older than ${max_age_hours}h)."
  fi
}

cmd_session_hook() {
  # Read JSON from stdin (Claude Code SessionStart hook format)
  local json
  json="$(cat)"

  local session_id
  session_id="$(echo "${json}" | jq -r '.session_id // empty')"

  if [[ -z "${session_id}" ]]; then
    return
  fi

  # Suppress for sub-agents (they have agent_type in the JSON)
  local agent_type
  agent_type="$(echo "${json}" | jq -r '.agent_type // empty')"
  if [[ -n "${agent_type}" ]]; then
    return
  fi

  # Suppress for burns sessions
  if [[ -n "${BURNS_SESSION:-}" ]]; then
    return
  fi

  echo "🔑 Your perm session is: ${session_id}"
}

cmd_nuke() {
  init_settings

  local current_count
  current_count="$(jq '.permissions.allow | length' "${_settings_file}")"

  if [[ "${current_count}" -eq 0 ]]; then
    echo "permissions.allow is already empty. Nothing to nuke."
    return
  fi

  echo "This will remove ALL ${current_count} entries from permissions.allow in:"
  echo "  ${_settings_file}"
  echo
  printf "Are you sure? [y/N]: "

  local response
  read -r response < /dev/tty

  if [[ "${response}" != "y" && "${response}" != "Y" ]]; then
    echo "Aborted. No changes made."
    return
  fi

  jq '.permissions.allow = []' "${_settings_file}" > "${_settings_file}.tmp"
  mv "${_settings_file}.tmp" "${_settings_file}"
  echo "Nuked: removed ${current_count} permission(s) from permissions.allow."
}

cmd_list() {
  init_tracking

  local temp_count
  local perm_count
  temp_count="$(jq '.temporary | length' "${_tracking_file}")"
  perm_count="$(jq '.permanent | length' "${_tracking_file}")"

  if [[ "${temp_count}" -eq 0 && "${perm_count}" -eq 0 ]]; then
    echo "No tracked permissions."
    return
  fi

  if [[ "${temp_count}" -gt 0 ]]; then
    echo "Temporary:"
    jq -r '
      .temporary | to_entries[] |
      .key as $pattern |
      .value | to_entries[] |
      "\($pattern)\t\(.key)\t\(.value)"
    ' "${_tracking_file}" \
      | while IFS=$'\t' read -r pattern session timestamp; do
          local age_hours
          age_hours=$(( ($(date +%s) - timestamp) / 3600 ))
          echo "  [temporary] ${pattern} (session: ${session}, age: ${age_hours}h)"
        done
  fi

  if [[ "${perm_count}" -gt 0 ]]; then
    echo "Permanent:"
    jq -r '.permanent[]' "${_tracking_file}" | while IFS= read -r pattern; do
      echo "  [permanent] ${pattern}"
    done
  fi
}

cmd_check() {
  local pattern="${1:-}"

  if [[ -z "${pattern}" ]]; then
    echo "Error: pattern required" >&2
    echo "Usage: perm check <pattern>" >&2
    exit 1
  fi

  echo "Checking: ${pattern}"
  echo ""

  local found_allow=false
  local found_deny=false

  # Determine git repo root (gracefully handle non-repo context)
  local repo_root=""
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || true

  # 1. Project-local: .claude/settings.local.json
  if [[ -n "${repo_root}" ]]; then
    local local_file="${repo_root}/.claude/settings.local.json"
    if [[ -f "${local_file}" ]]; then
      local in_local_allow
      in_local_allow="$(jq --arg p "${pattern}" '.permissions.allow // [] | index($p) != null' "${local_file}")"
      if [[ "${in_local_allow}" == "true" ]]; then
        printf "  ✓ local   .claude/settings.local.json\n"
        found_allow=true
      else
        printf "  ✗ local   .claude/settings.local.json\n"
      fi
      local in_local_deny
      in_local_deny="$(jq --arg p "${pattern}" '(.permissions.deny // []) + (.permissions.block // []) | index($p) != null' "${local_file}")"
      if [[ "${in_local_deny}" == "true" ]]; then
        printf "  ⚠ deny/block  local   .claude/settings.local.json\n"
        found_deny=true
      fi
    else
      printf "  - local   .claude/settings.local.json [not found]\n"
    fi

    # 2. Project: .claude/settings.json
    local project_file="${repo_root}/.claude/settings.json"
    if [[ -f "${project_file}" ]]; then
      local in_project_allow
      in_project_allow="$(jq --arg p "${pattern}" '.permissions.allow // [] | index($p) != null' "${project_file}")"
      if [[ "${in_project_allow}" == "true" ]]; then
        printf "  ✓ project .claude/settings.json\n"
        found_allow=true
      else
        printf "  ✗ project .claude/settings.json\n"
      fi
      local in_project_deny
      in_project_deny="$(jq --arg p "${pattern}" '(.permissions.deny // []) + (.permissions.block // []) | index($p) != null' "${project_file}")"
      if [[ "${in_project_deny}" == "true" ]]; then
        printf "  ⚠ deny/block  project .claude/settings.json\n"
        found_deny=true
      fi
    else
      printf "  - project .claude/settings.json [not found]\n"
    fi
  else
    printf "  - local   .claude/settings.local.json [not in a git repo]\n"
    printf "  - project .claude/settings.json [not in a git repo]\n"
  fi

  # 3. Global: ~/.claude/settings.json
  local global_file="${HOME}/.claude/settings.json"
  if [[ -f "${global_file}" ]]; then
    local in_global_allow
    in_global_allow="$(jq --arg p "${pattern}" '.permissions.allow // [] | index($p) != null' "${global_file}")"
    if [[ "${in_global_allow}" == "true" ]]; then
      printf "  ✓ global  ~/.claude/settings.json\n"
      found_allow=true
    else
      printf "  ✗ global  ~/.claude/settings.json\n"
    fi
    local in_global_deny
    in_global_deny="$(jq --arg p "${pattern}" '(.permissions.deny // []) + (.permissions.block // []) | index($p) != null' "${global_file}")"
    if [[ "${in_global_deny}" == "true" ]]; then
      printf "  ⚠ deny/block  global  ~/.claude/settings.json\n"
      found_deny=true
    fi
  else
    printf "  - global  ~/.claude/settings.json [not found]\n"
  fi

  echo ""
  if [[ "${found_deny}" == "true" ]]; then
    echo "→ DENIED  (deny/block found — overrides all allows globally)"
  elif [[ "${found_allow}" == "true" ]]; then
    echo "→ ALLOWED"
  else
    echo "→ NOT ALLOWED"
  fi
}

# Parse global --session flag and subcommand.
# Accepted forms:
#   perm --session <id> <subcommand> [args...]
#   perm <subcommand> [args...]   (session not required for always/list/cleanup-stale/session-hook)
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
    allow|always|cleanup|cleanup-stale|list|check|nuke|session-hook)
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

# Parse subcommand-specific flags
sub_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    --max-age)
      if [[ $# -lt 2 ]]; then
        echo "Error: --max-age requires an argument" >&2
        exit 1
      fi
      sub_args+=("$2")
      shift 2
      ;;
    *)
      sub_args+=("$1")
      shift
      ;;
  esac
done

case "${subcommand}" in
  allow)
    cmd_allow "${session_id}" "${sub_args[@]}"
    ;;
  always)
    cmd_always "${sub_args[@]}"
    ;;
  cleanup)
    cmd_cleanup "${session_id}"
    ;;
  cleanup-stale)
    cmd_cleanup_stale "${sub_args[0]:-4}"
    ;;
  list)
    cmd_list
    ;;
  check)
    cmd_check "${sub_args[0]:-}"
    ;;
  nuke)
    cmd_nuke
    ;;
  session-hook)
    cmd_session_hook
    ;;
esac
