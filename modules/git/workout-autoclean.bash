#!/usr/bin/env bash
set -euo pipefail
# workout-autoclean: Daily global reaper for stale git worktrees.
#
# Scheduled via launchd (modules/git/default.nix, StartCalendarInterval
# Hour=17) to run once a day at 5:00pm, completely independent of any
# `workout` command or shell session. Unconditionally trashes every git
# worktree found under $WORKTREE_ROOT (default ~/worktrees) whose directory
# BIRTH TIME is >= 30 days old — no merge check, age is the only signal.
#
# ~/worktrees is a HETEROGENEOUS tree: some top-level directories ARE
# worktrees, others are plain org/repo path containers holding worktrees one
# level down (or deeper). Worktrees CANNOT be identified by depth, so this
# script walks the tree recursively and detects a worktree by the presence of
# a `.git` FILE (not directory) — a worktree's `.git` is a text file
# containing `gitdir: <main-repo>/.git/worktrees/<name>`, whereas a
# primary/main repo checkout has a `.git` DIRECTORY. Recursion is pruned the
# instant either marker is found, since repos/worktrees never nest inside
# each other in this layout — this also protects against picking up a
# submodule's `.git` file nested inside a worktree.
#
# Skips (hard safety requirements):
#   - Primary/main repo checkouts — excluded structurally: a directory with a
#     `.git` DIRECTORY is never even considered a worktree candidate.
#   - Any worktree with uncommitted changes — a dirty worktree must NEVER be
#     trashed.
#   (No current-directory skip: this runs from launchd, which has no cwd/repo
#   context. A just-created worktree is protected by the age threshold alone.)
#
# Age is computed from macOS directory BIRTH TIME, NOT mtime — mtime is
# unreliable (build artifacts and file edits reset it constantly). Birth time
# is queried via the absolute path /usr/bin/stat (macOS's native BSD stat),
# NOT the bare `stat` command: this shellapp's wrapper prepends Nix's GNU
# coreutils onto PATH ahead of /usr/bin, and GNU stat's `-f` flag means
# something entirely different (filesystem status) than BSD stat's
# `-f FORMAT` (custom format string). Calling the bare `stat -f %B` under
# this PATH silently fails and would make every worktree look infinitely
# young (birth epoch would fall back to the "never reap" sentinel below).
# Since this repo is locked to aarch64-darwin, hardcoding the macOS system
# stat path is safe and correct.
#
# Deletion uses the SAME mechanism as `workout clean` / workout-delete:
#   1. Resolve the worktree's owner repo via `git rev-parse --git-common-dir`
#      BEFORE trashing — the `.git` file (and the ability to resolve it) is
#      gone once the directory has been trashed.
#   2. trash "$path" (macOS-native Trash, visible in Finder — pkgs.darwin.trash)
#   3. git worktree prune (once per owner repo, after all trashing is done)
# The `git worktree` "remove" subcommand is never invoked anywhere in this script.
#
# Flags:
#   --dry-run   Print what WOULD be reaped (path + age) without trashing,
#               pruning, or writing to the log.
#
# Logging: every reap is appended (ISO-8601 UTC timestamp, worktree path,
# owner repo) to "${XDG_STATE_HOME:-$HOME/.local/state}/workout-autoclean.log".
# Dry runs never write to this log.

# 30 days in seconds
readonly max_age_days=30
readonly max_age_seconds=$((max_age_days * 86400))

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true
fi

worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
now_epoch=$(date +%s)
log_file="${XDG_STATE_HOME:-$HOME/.local/state}/workout-autoclean.log"

shopt -s nullglob dotglob

# Recursively discover worktree directories under $1, appending to the
# global `discovered_worktrees` array. See header comment for the detection
# rule (a `.git` FILE marks a worktree; a `.git` DIRECTORY marks a primary
# repo and is never recursed into).
declare -a discovered_worktrees=()

discover_worktrees() {
  local dir="$1"

  if [[ -f "$dir/.git" ]]; then
    discovered_worktrees+=("$dir")
    return 0
  fi

  if [[ -d "$dir/.git" ]]; then
    # Primary/main repo checkout — never a reap candidate, never recursed into.
    return 0
  fi

  local entry
  for entry in "$dir"/*/; do
    entry="${entry%/}"
    # Skip symlinks to avoid cycles when walking the tree.
    [[ -L "$entry" ]] && continue
    [[ -d "$entry" ]] || continue
    discover_worktrees "$entry"
  done
}

if [[ -d "$worktree_root" ]]; then
  discover_worktrees "$worktree_root"
fi

# Owner repos that need `git worktree prune` after the trash loop, deduped so
# each repo is pruned exactly once regardless of how many of its worktrees
# were reaped in this run.
declare -a owner_repos_to_prune=()

add_owner_repo() {
  local repo="$1"
  local existing
  for existing in "${owner_repos_to_prune[@]}"; do
    [[ "$existing" == "$repo" ]] && return 0
  done
  owner_repos_to_prune+=("$repo")
}

for current_path in "${discovered_worktrees[@]}"; do
  # Skip: worktree has uncommitted changes — dirty worktrees must NEVER be trashed.
  # Fail CLOSED: if `git status` itself errors (corrupted index, filesystem
  # hiccup, etc.), we cannot verify the worktree is clean, so skip it rather
  # than assume clean. Only an empty (successful, no-output) result is treated
  # as verified-clean.
  if ! dirty_check=$(git -C "$current_path" status --porcelain 2>/dev/null); then
    echo "Skipping $current_path (cannot verify clean state)" >&2
    continue
  fi
  if [[ -n "$dirty_check" ]]; then
    echo "Skipping dirty worktree (uncommitted changes): $current_path" >&2
    continue
  fi

  # Compute age using macOS birth time (creation time), not mtime. See header
  # comment for why this hardcodes /usr/bin/stat instead of relying on PATH.
  birth_epoch=$(/usr/bin/stat -f %B "$current_path" 2>/dev/null || echo "9999999999")
  age_seconds=$(( now_epoch - birth_epoch ))
  age_days=$((age_seconds / 86400))

  if (( age_seconds < max_age_seconds )); then
    continue
  fi

  if [[ "$dry_run" == true ]]; then
    echo "[dry-run] Would reap (age: ${age_days} days): $current_path" >&2
    continue
  fi

  # Resolve the owner repo BEFORE trashing — the `.git` file (and therefore
  # the ability to resolve it) is gone once the directory is trashed.
  git_common_dir="$(git -C "$current_path" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -z "$git_common_dir" ]]; then
    echo "Skipping (could not resolve owner repo): $current_path" >&2
    continue
  fi
  owner_repo="$(dirname "$git_common_dir")"

  echo "Trashing stale worktree (age: ${age_days} days): $current_path" >&2
  if trash "$current_path" >&2; then
    echo "Trashed: $current_path" >&2
  else
    echo "Failed to trash: $current_path" >&2
    continue
  fi

  add_owner_repo "$owner_repo"

  mkdir -p "$(dirname "$log_file")"
  printf '%s\treaped\t%s\towner=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current_path" "$owner_repo" >> "$log_file"
done

# Prune each owner repo once, after all trashing is done. A single repo's
# prune failure must not abort the rest of the sweep.
for owner_repo in "${owner_repos_to_prune[@]}"; do
  git -C "$owner_repo" worktree prune >&2 || echo "Prune failed for $owner_repo" >&2
done
