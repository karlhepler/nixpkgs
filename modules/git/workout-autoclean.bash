#!/usr/bin/env bash
set -euo pipefail
# workout-autoclean: Daily global reaper for stale, merged or empty git worktrees.
#
# Scheduled via launchd (modules/git/default.nix, StartCalendarInterval
# Hour=17) to run once a day at 5:00pm, completely independent of any
# `workout` command or shell session. Trashes every CLEAN git worktree found
# under $WORKTREE_ROOT (default ~/worktrees) that matches ANY reap rule (checked in this order):
#
#   age         The directory BIRTH TIME is >= 30 days old. Catches worktrees
#               that never got a PR. No merge check.
#   no-commits  Birth time >= 7 days AND HEAD is already contained in the
#               origin default branch (`git merge-base --is-ancestor HEAD
#               refs/remotes/origin/HEAD`) — nothing in the worktree exists
#               only locally. Purely local, so it works when `gh` is down.
#               Skipped if origin/HEAD is unset (fail closed).
#   merged-pr   The branch's pull request has MERGED (see "Merged-PR rule").
#               Catches the common case: worktrees are created far faster
#               than 30 days allows for, and a merged PR means the work is
#               done.
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
#     trashed, under any rule.
#   - Any worktree a running process has as its working directory (or inside
#     it) — found with one `lsof -d cwd` at startup. Trashing a folder out
#     from under a live tmux pane or Claude session breaks that session even
#     though no work is lost. If lsof returns nothing at all, the script
#     aborts without reaping (fail closed).
#   (No script-cwd skip: this runs from launchd, which has no cwd/repo
#   context.)
#
# Merged-PR rule — ALL of these must hold, and every error fails CLOSED:
#   1. Clean (the dirty check above).
#   2. No OPEN PR for the branch name, by anyone. Branch names get reused: the
#      same name can have an old merged PR and a new open one.
#   3. At least one MERGED PR of mine (`--author @me`) for the branch name.
#   4. Nothing extra: the worktree's HEAD equals a merged PR's headRefOid or is
#      an ancestor of it (`git merge-base --is-ancestor`). Commits past what
#      was merged may exist nowhere else, so the worktree is kept. This does
#      NOT use `git log HEAD --not --remotes`: the repos squash-merge and
#      delete the remote branch, so that check would wrongly flag nearly every
#      merged worktree.
#   A detached HEAD has no branch, so it never matches. GitHub is queried
#   lazily, TWICE per owner repo (open PRs, then my merged PRs), not once per
#   worktree. If `gh` is unauthenticated, rate-limited or errors, the
#   merged-PR rule is skipped (for the whole run, or for that repo) and
#   behavior falls back to age-only — "couldn't ask GitHub" is never treated
#   as "merged". Closed-but-unmerged PRs are deliberately NOT reaped early.
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
# Test hook: WORKOUT_AUTOCLEAN_NOW=<epoch> overrides "now" so tests can make
# worktrees look old (birth time itself cannot be faked).
#
# Flags:
#   --dry-run   Print what WOULD be reaped (path, reason, age) without
#               trashing, pruning, or writing to the log. It still calls
#               GitHub (read-only) so the merged-PR rule can be previewed.
#
# Logging: every reap is appended (ISO-8601 UTC timestamp, worktree path,
# owner repo, reason=age|no-commits|merged-pr, and pr=#N for merged-pr) to
# "${XDG_STATE_HOME:-$HOME/.local/state}/workout-autoclean.log".
# Dry runs never write to this log.

# 30 days in seconds
readonly max_age_days=30
readonly max_age_seconds=$((max_age_days * 86400))
# no-commits rule: a short buffer so a worktree just created (and not yet
# committed to) isn't reaped.
readonly no_commits_min_age_days=7
readonly no_commits_min_age_seconds=$((no_commits_min_age_days * 86400))

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true
fi

worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
now_epoch="${WORKOUT_AUTOCLEAN_NOW:-$(date +%s)}"
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

# --- Merged-PR rule -------------------------------------------------------

# gh's stderr lands here so fallback messages can say WHY gh failed (a launchd
# keychain problem looks very different from a rate limit).
gh_err_file="$(mktemp)"
trap 'rm -f "$gh_err_file"' EXIT

# "gh: <first stderr line>" for the failure that just happened.
gh_why() {
  local line
  line="$(head -n 1 "$gh_err_file" 2>/dev/null || true)"
  echo "gh: ${line:-no error output}"
}

# Whether the merged-PR rule is usable at all this run. `--active` so a stale
# secondary account doesn't make the check fail; only github.com is queried.
merged_rule_enabled=true
if ! gh auth status --hostname github.com --active >/dev/null 2>"$gh_err_file"; then
  merged_rule_enabled=false
  echo "Merged-PR rule disabled for this run ($(gh_why)); age-only" >&2
fi

# Per-owner-repo PR index, filled lazily by load_pr_index. Keys are the owner
# repo path, or "<owner repo>|<branch>" for the per-branch maps.
declare -A pr_index_ok=()      # repo -> 1 if loaded, 0 if the rule is skipped for it
declare -A open_pr=()          # repo|branch -> 1 if ANY open PR has that head branch
declare -A merged_prs=()       # repo|branch -> space-separated "<headRefOid>:<number>"

# Print the GitHub "owner/name" of $1's origin remote; non-zero if it isn't GitHub.
github_slug() {
  local url
  url="$(git -C "$1" remote get-url origin 2>/dev/null)" || return 1
  if [[ "$url" =~ github\.com[:/]([^/]+/[^/]+)$ ]]; then
    local slug="${BASH_REMATCH[1]}"
    echo "${slug%.git}"
    return 0
  fi
  return 1
}

# Fill the PR index for owner repo $1 (once). Any failure marks the repo
# skipped: pr_index_ok[$1]=0.
load_pr_index() {
  local repo="$1"
  [[ -n "${pr_index_ok[$repo]:-}" ]] && return 0
  pr_index_ok[$repo]=0

  local slug open_out merged_out
  if ! slug="$(github_slug "$repo")"; then
    echo "Merged-PR rule skipped for $repo (origin is not a GitHub remote); age-only" >&2
    return 0
  fi

  # Everyone's open PRs: any open PR on a branch name blocks the reap.
  if ! open_out="$(gh pr list -R "$slug" --state open --limit 1000 \
      --json headRefName --jq '.[].headRefName' 2>"$gh_err_file")"; then
    echo "Merged-PR rule skipped for $slug (listing open PRs: $(gh_why)); age-only" >&2
    return 0
  fi
  # A full page may be truncated — an open PR could be missing from it.
  if (( $(grep -c . <<<"$open_out" || true) >= 1000 )); then
    echo "Merged-PR rule skipped for $slug (>=1000 open PRs, list may be truncated); age-only" >&2
    return 0
  fi
  # Only my merged PRs. A truncated list can only make us reap LESS.
  if ! merged_out="$(gh pr list -R "$slug" --author @me --state merged --limit 1000 \
      --json headRefName,headRefOid,number \
      --jq '.[] | [.headRefName, .headRefOid, (.number | tostring)] | @tsv' 2>"$gh_err_file")"; then
    echo "Merged-PR rule skipped for $slug (listing merged PRs: $(gh_why)); age-only" >&2
    return 0
  fi

  local branch oid num
  while IFS= read -r branch; do
    [[ -n "$branch" ]] && open_pr["$repo|$branch"]=1
  done <<<"$open_out"
  while IFS=$'\t' read -r branch oid num; do
    [[ -n "$branch" ]] && merged_prs["$repo|$branch"]+="$oid:$num "
  done <<<"$merged_out"

  pr_index_ok[$repo]=1
}

# Does worktree $1 (owner repo $2) satisfy the merged-PR rule? On success sets
# `matched_pr` to the merged PR number; on failure prints why to stderr.
matched_pr=""
merged_pr_check() {
  local path="$1" repo="$2" branch head entry oid rc saw_extra=false
  matched_pr=""

  [[ "$merged_rule_enabled" == true ]] || return 1

  # A detached HEAD has no branch name to look up.
  branch="$(git -C "$path" symbolic-ref --short -q HEAD 2>/dev/null)" || return 1
  head="$(git -C "$path" rev-parse HEAD 2>/dev/null)" || return 1

  load_pr_index "$repo"
  [[ "${pr_index_ok[$repo]}" == 1 ]] || return 1

  if [[ -n "${open_pr["$repo|$branch"]:-}" ]]; then
    echo "Skipping (open PR on branch $branch): $path" >&2
    return 1
  fi

  [[ -n "${merged_prs["$repo|$branch"]:-}" ]] || return 1

  for entry in ${merged_prs["$repo|$branch"]}; do
    oid="${entry%%:*}"
    if [[ "$head" == "$oid" ]]; then
      matched_pr="${entry#*:}"
      return 0
    fi
    # Exit 0 = HEAD is inside the merged PR; 1 = HEAD has commits beyond it;
    # anything else (128) = the merged commit isn't in this clone at all.
    rc=0
    git -C "$path" merge-base --is-ancestor "$head" "$oid" 2>/dev/null || rc=$?
    case "$rc" in
      0) matched_pr="${entry#*:}"; return 0 ;;
      1) saw_extra=true ;;
    esac
  done

  if [[ "$saw_extra" == true ]]; then
    echo "Skipping (commits not in the merged PR on branch $branch): $path" >&2
  else
    echo "Skipping (merged PR commit not present locally on branch $branch): $path" >&2
  fi
  return 1
}

# --- no-commits rule ---------------------------------------------------------

# Is everything in worktree $1 already in the origin default branch? Needs
# origin/HEAD set; a stale local origin/main can only make this match LESS.
no_commits_check() {
  local path="$1" default_ref
  default_ref="$(git -C "$path" symbolic-ref -q refs/remotes/origin/HEAD 2>/dev/null)" || return 1
  git -C "$path" merge-base --is-ancestor HEAD "$default_ref" 2>/dev/null
}

# --- In-use guard -----------------------------------------------------------

# Working directories of every running process, absolute lsof path for the
# same PATH-shadowing reason as /usr/bin/stat. Always non-empty on a healthy
# system (this very shell, tmux, ...); empty means lsof is broken, so abort
# rather than reap blind.
in_use_cwds="$(/usr/sbin/lsof -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
if [[ -z "$in_use_cwds" ]]; then
  echo "lsof returned no working directories; refusing to reap without the in-use check" >&2
  exit 1
fi

# Is any process's cwd the worktree $1 or somewhere inside it?
path_in_use() {
  local p="$1" cwd
  while IFS= read -r cwd; do
    [[ "$cwd" == "$p" || "$cwd" == "$p"/* ]] && return 0
  done <<<"$in_use_cwds"
  return 1
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

  if path_in_use "$current_path"; then
    echo "Skipping (in use by a running process): $current_path" >&2
    continue
  fi

  # Resolve the owner repo BEFORE anything else — the PR lookup needs it, and
  # the `.git` file (and therefore the ability to resolve it) is gone once the
  # directory is trashed.
  git_common_dir="$(git -C "$current_path" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -z "$git_common_dir" ]]; then
    echo "Skipping (could not resolve owner repo): $current_path" >&2
    continue
  fi
  owner_repo="$(dirname "$git_common_dir")"

  # Compute age using macOS birth time (creation time), not mtime. See header
  # comment for why this hardcodes /usr/bin/stat instead of relying on PATH.
  birth_epoch=$(/usr/bin/stat -f %B "$current_path" 2>/dev/null || echo "9999999999")
  age_seconds=$(( now_epoch - birth_epoch ))
  age_days=$((age_seconds / 86400))

  # Decide WHY this worktree is reapable, or skip it.
  reason=""
  if (( age_seconds >= max_age_seconds )); then
    reason="age"
  elif (( age_seconds >= no_commits_min_age_seconds )) && no_commits_check "$current_path"; then
    reason="no-commits"
  elif merged_pr_check "$current_path" "$owner_repo"; then
    reason="merged-pr"
  fi
  [[ -n "$reason" ]] || continue

  reason_label="reason: ${reason}, age: ${age_days} days"
  log_extra=""
  if [[ "$reason" == "merged-pr" ]]; then
    reason_label="reason: merged-pr, PR #${matched_pr}, age: ${age_days} days"
    log_extra=$'\t'"pr=#${matched_pr}"
  fi

  if [[ "$dry_run" == true ]]; then
    echo "[dry-run] Would reap ($reason_label): $current_path" >&2
    continue
  fi

  echo "Trashing worktree ($reason_label): $current_path" >&2
  if trash "$current_path" >&2; then
    echo "Trashed: $current_path" >&2
  else
    echo "Failed to trash: $current_path" >&2
    continue
  fi

  add_owner_repo "$owner_repo"

  mkdir -p "$(dirname "$log_file")"
  printf '%s\treaped\t%s\towner=%s\treason=%s%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current_path" "$owner_repo" "$reason" "$log_extra" >> "$log_file"
done

# Prune each owner repo once, after all trashing is done. A single repo's
# prune failure must not abort the rest of the sweep.
for owner_repo in "${owner_repos_to_prune[@]}"; do
  git -C "$owner_repo" worktree prune >&2 || echo "Prune failed for $owner_repo" >&2
done
