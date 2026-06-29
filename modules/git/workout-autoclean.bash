#!/usr/bin/env bash
set -euo pipefail
# workout-autoclean: Automatically trash worktrees >=90 days old.
#
# Skips:
#   - The primary repo (main checkout, not under the worktree root)
#   - The current working directory (never delete the worktree we're in)
#   - Any worktree with uncommitted changes (hard safety requirement — a dirty
#     worktree must NEVER be trashed)
#
# Age is computed from macOS directory BIRTH TIME (stat -f %B), NOT mtime.
# mtime is unreliable — build artifacts and file edits reset it constantly.
#
# Deletion uses the same mechanism as `workout clean` / workout-delete:
#   trash "$path" (macOS-native Trash, visible in Finder)
#   git worktree prune (clean up leftover git metadata)

# 90 days in seconds
readonly max_age_seconds=$((90 * 86400))

worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
now_epoch=$(date +%s)

# Parse git worktree list --porcelain into path/bare/main fields.
# Each worktree stanza is separated by a blank line.
# Fields we care about: "worktree <path>" and "bare"
current_dir="$(pwd)"

while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    "worktree "*)
      current_path="${line#worktree }"
      is_bare=false
      ;;
    "bare")
      is_bare=true
      ;;
    "")
      # End of stanza — evaluate this worktree
      if [[ -z "${current_path:-}" ]]; then
        continue
      fi

      # Skip bare worktrees (git internals)
      if [[ "$is_bare" == "true" ]]; then
        current_path=""
        is_bare=false
        continue
      fi

      # Skip: worktree not under the worktree root (i.e., the primary repo)
      if [[ "$current_path" != "$worktree_root"/* ]]; then
        echo "Skipping primary repo: $current_path" >&2
        current_path=""
        is_bare=false
        continue
      fi

      # Skip: this is our current working directory (the just-created or active worktree)
      if [[ "$current_path" == "$current_dir" || "$current_dir" == "$current_path"/* ]]; then
        echo "Skipping current worktree: $current_path" >&2
        current_path=""
        is_bare=false
        continue
      fi

      # Skip: directory no longer exists
      if [[ ! -d "$current_path" ]]; then
        current_path=""
        is_bare=false
        continue
      fi

      # Skip: worktree has uncommitted changes — dirty worktrees must NEVER be trashed
      dirty_check=$(git -C "$current_path" status --porcelain 2>/dev/null || true)
      if [[ -n "$dirty_check" ]]; then
        echo "Skipping dirty worktree (uncommitted changes): $current_path" >&2
        current_path=""
        is_bare=false
        continue
      fi

      # Compute age using macOS birth time (creation time), not mtime
      birth_epoch=$(stat -f %B "$current_path" 2>/dev/null || echo "9999999999")
      age_seconds=$(( now_epoch - birth_epoch ))

      if (( age_seconds >= max_age_seconds )); then
        echo "Trashing stale worktree (age: $((age_seconds / 86400)) days): $current_path" >&2
        trash "$current_path" >&2
        git worktree prune >&2
        echo "Trashed: $current_path" >&2
      fi

      current_path=""
      is_bare=false
      ;;
  esac
done < <(git worktree list --porcelain; echo "")
