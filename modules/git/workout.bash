# Create and navigate to git worktrees in ~/worktrees/ (or $WORKTREE_ROOT)
# - Creates worktree organized by org/repo/branch structure
# - Reuses existing worktree if already created (idempotent)
# - With no args: shows help
# - With `.`: creates worktree for current branch
# - With `-`: toggles to previous worktree location (persists across sessions)
# - With `/`: opens interactive fzf browser to view and manage worktrees
# - With `-h` or `--help`: shows help
# - With branch name: creates/uses worktree for that branch (creates branch if needed)
#
# NOTE: Requires shell wrapper function to change directory in parent shell.
# The wrapper function is defined in modules/zsh.nix (lines 134-151):
#
#   workout() {
#     local result
#     result="$(${homeDirectory}/.nix-profile/bin/workout "$@")"
#     local exit_code=$?
#     if [ $exit_code -eq 0 ]; then
#       # Save current location to global state file if we're in a worktree
#       local worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
#       if [[ "$PWD" =~ ^$worktree_root/ ]]; then
#         mkdir -p "$worktree_root"
#         echo "$PWD" > "$worktree_root/.workout_prev"
#       fi
#       eval "$result"
#     fi
#     return $exit_code
#   }
#
# This script outputs a cd command to stdout, which the wrapper evals to change directories.
# The wrapper also saves the current location to a state file for the toggle feature (-).

show_help() {
  echo "workout - Create and navigate git worktrees"
  echo
  echo "USAGE:"
  echo "  workout                    Show this help"
  echo "  workout .                  Create worktree for current branch"
  echo "  workout -                  Toggle to previous worktree"
  echo "  workout /                  Browse and manage worktrees (interactive)"
  echo "  workout <branch>           Create worktree for branch"
  echo "  workout -h, --help         Show this help"
  echo
  echo "DESCRIPTION:"
  echo "  Manages git worktrees organized in ~/worktrees/org/repo/branch/."
  echo "  Creates worktrees automatically if they don't exist (idempotent)."
  echo "  Enables working on multiple branches simultaneously without stashing."
  echo
  echo "COMMANDS:"
  echo "  .         Create/navigate to worktree for current branch"
  echo "            If in primary repo: migrates branch to worktree,"
  echo "            preserves uncommitted changes, restores primary to trunk"
  echo "  -         Toggle between current and previous worktree (like cd -)"
  echo "  /         Interactive browser - view and navigate worktrees"
  echo "            (Enter=select, ESC=cancel)"
  echo "  <branch>  Create/navigate to worktree for specified branch"
  echo "            If branch doesn't exist, creates it from current HEAD"
  echo
  echo "EXAMPLES:"
  echo "  # Create worktree for current branch"
  echo "  workout ."
  echo
  echo "  # Create worktree for feature branch"
  echo "  workout feature/new-thing"
  echo
  echo "  # Create worktree for non-existent branch (creates branch too)"
  echo "  workout experimental-idea"
  echo
  echo "  # Toggle back to previous worktree"
  echo "  workout -"
  echo
  echo "  # Browse all worktrees interactively"
  echo "  workout /"
  echo
  echo "  # Typical workflow: work on feature, switch to main, switch back"
  echo "  workout feature/xyz        # Work on feature"
  echo "  workout main               # Quick check of main"
  echo "  workout -                  # Back to feature/xyz"
  echo
  echo "PRIMARY REPO MIGRATION:"
  echo "  When running 'workout .' from a branch checked out in the primary"
  echo "  repository (not a worktree), workout will:"
  echo "  1. Stash any uncommitted changes (including untracked files)"
  echo "  2. Switch primary repo back to trunk branch"
  echo "  3. Create worktree for the branch"
  echo "  4. Restore uncommitted changes in the new worktree"
  echo "  5. Navigate you into the worktree"
  echo
  echo "  This keeps your primary repo clean on trunk while doing all"
  echo "  branch work in worktrees."
  echo
  echo "WORKTREE ORGANIZATION:"
  echo "  All worktrees stored in: ~/worktrees/<org>/<repo>/<branch>/"
  echo "  (or \$WORKTREE_ROOT/<org>/<repo>/<branch>/ if WORKTREE_ROOT is set)"
  echo
  echo "  Example:"
  echo "    ~/worktrees/karlhepler/nixpkgs/main/"
  echo "    ~/worktrees/karlhepler/nixpkgs/feature/workout-enhancements/"
  echo
  echo "CUSTOMIZATION:"
  echo "  Set WORKTREE_ROOT to customize worktree location (default: ~/worktrees)"
  echo
  echo "  Example:"
  echo "    export WORKTREE_ROOT=~/dev/worktrees"
  echo "    workout feature-x  # Creates ~/dev/worktrees/org/repo/feature-x"
  echo
  echo "NOTES:"
  echo "  - Worktrees share .git directory (shared refs, tags, remotes)"
  echo "  - Each worktree has independent working directory and index"
  echo "  - Useful for reviewing PRs, testing changes, or parallel development"
  echo "  - Uncommitted changes are preserved when migrating from primary repo"
}

# List all worktrees in format for fzf
# Accepts optional git_root parameter to mark the primary repo with [brackets]
# Accepts optional current_dir parameter to mark the current worktree with → prefix
list_worktrees() {
  local git_root="${1:-}"
  local current_dir="${2:-}"

  git worktree list --porcelain | awk '
    /^worktree / {
      path = substr($0, 10)
    }
    /^branch / {
      branch = substr($0, 8)
      sub(/^refs\/heads\//, "", branch)
    }
    /^HEAD / {
      head = substr($0, 6)
    }
    /^$/ {
      if (path != "")  {
        printf "%s|%s|%s\n", path, branch, substr(head, 1, 8)
        path = ""
        branch = ""
        head = ""
      }
    }
    END {
      if (path != "") {
        printf "%s|%s|%s\n", path, branch, substr(head, 1, 8)
      }
    }
  ' | while IFS='|' read -r path branch head; do
    # Format: branch  commit  path
    # Path is last so we can hide it but still extract it

    # Mark the current worktree with a right arrow
    local prefix=""
    if [ -n "$current_dir" ] && [ "$path" = "$current_dir" ]; then
      prefix="→ "
    fi

    # Mark the primary repo (git root) with square brackets
    local is_root=false
    if [ -n "$git_root" ] && [ "$path" = "$git_root" ]; then
      is_root=true
    fi

    if [ -z "$branch" ]; then
      if [ "$is_root" = true ]; then
        printf "%-40s  %s  %s\n" "${prefix}[(main)]" "$head" "$path"
      else
        printf "%-40s  %s  %s\n" "${prefix}(main)" "$head" "$path"
      fi
    else
      if [ "$is_root" = true ]; then
        printf "%-40s  %s  %s\n" "${prefix}[${branch}]" "$head" "$path"
      else
        printf "%-40s  %s  %s\n" "${prefix}${branch}" "$head" "$path"
      fi
    fi
  done
}

# Check if git index is locked
is_git_locked() {
  local git_dir
  git_dir="$(git rev-parse --git-dir 2>/dev/null)" || return 1

  # Check for common lock files
  [ -f "$git_dir/index.lock" ] || \
  [ -f "$git_dir/HEAD.lock" ] || \
  [ -f "$git_dir/refs/heads/*.lock" ] 2>/dev/null
}

# Generate preview for a worktree
preview_worktree() {
  local worktree_path="$1"

  if [ ! -d "$worktree_path" ]; then
    echo "Error: Worktree not found: $worktree_path"
    return 1
  fi

  # Change to worktree directory
  cd "$worktree_path" || return 1

  # Check for lock files and wait briefly if found
  if is_git_locked; then
    echo "⏳ Git operation in progress, waiting..."
    sleep 0.5
    # If still locked after wait, skip preview
    if is_git_locked; then
      echo "⚠️  Git index is locked - preview unavailable"
      echo "Try again in a moment"
      return 0
    fi
  fi

  # Get current branch
  local current_branch
  current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "detached")"

  echo "═══════════════════════════════════════════════════════════════"
  echo "  📍 WORKTREE: $worktree_path"
  echo "  🌿 BRANCH: $current_branch"
  echo "═══════════════════════════════════════════════════════════════"
  echo

  # Section 1: Git Status (with timeout and error handling)
  echo "━━━ GIT STATUS ━━━"
  if ! timeout 2 git status --short 2>&1; then
    echo "(Status unavailable - git operation may be in progress)"
  fi
  echo

  # Section 2: Recent Commits (with timeout)
  echo "━━━ RECENT COMMITS ━━━"
  if ! timeout 2 git log --oneline --color=always -5 2>&1; then
    echo "(Log unavailable)"
  fi
  echo

  # Section 3: Diff stats vs main/master (with timeout)
  echo "━━━ CHANGES VS TRUNK ━━━"
  # Try to find the main branch
  local trunk_branch
  if git rev-parse --verify main >/dev/null 2>&1; then
    trunk_branch="main"
  elif git rev-parse --verify master >/dev/null 2>&1; then
    trunk_branch="master"
  else
    echo "Note: Could not find main/master branch"
    return 0
  fi

  # Check if we're on the trunk branch
  if [ "$current_branch" = "$trunk_branch" ]; then
    echo "This is the $trunk_branch branch (no diff)"
  else
    # Get file changes with status and line counts
    local RED='\033[0;31m'
    local GREEN='\033[0;32m'
    local YELLOW='\033[0;33m'
    local NC='\033[0m' # No Color

    # Combine name-status and numstat for comprehensive view (with timeout)
    if timeout 3 git diff --name-status "$trunk_branch"...HEAD 2>/dev/null | while IFS=$'\t' read -r change_type file oldfile; do
      case "$change_type" in
        A)
          # Added file - get line count without showing debug output
          printf "${GREEN}+${NC}  %s ${GREEN}(+%s)${NC}\n" \
            "$file" \
            "$(git diff --numstat "$trunk_branch"...HEAD -- "$file" 2>/dev/null | awk '{print $1}')"
          ;;
        D)
          # Deleted file
          printf "${RED}-${NC}  %s\n" "$file"
          ;;
        M)
          # Modified file - show M indicator and line counts
          printf "${YELLOW}M${NC}  %s ${GREEN}+%s${NC}/${RED}-%s${NC}\n" \
            "$file" \
            "$(git diff --numstat "$trunk_branch"...HEAD -- "$file" 2>/dev/null | awk '{print $1}')" \
            "$(git diff --numstat "$trunk_branch"...HEAD -- "$file" 2>/dev/null | awk '{print $2}')"
          ;;
        R*)
          # Renamed file
          printf "${YELLOW}→${NC}  %s → %s\n" "$oldfile" "$file"
          ;;
        *)
          printf "   %s (%s)\n" "$file" "$change_type"
          ;;
      esac
    done; then
      # Show summary if diff succeeded
      local summary
      summary=$(timeout 2 git diff --shortstat "$trunk_branch"...HEAD 2>/dev/null || echo "")
      if [ -n "$summary" ]; then
        echo
        echo "$summary"
      fi
    else
      echo "(Diff unavailable - this may be a large changeset)"
    fi
  fi
}

# Run fzf selector for worktrees
run_fzf_selector() {
  # Create worktree root directory if it doesn't exist
  local worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
  mkdir -p "$worktree_root"

  # Check if we're in a git repo
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "Error: Not in a git repository" >&2
    return 1
  fi

  # Get git root directory (primary repo location) before launching fzf
  # This is needed in case we delete the current worktree
  # Use git worktree list to find primary repo (first entry), not git rev-parse which returns current worktree
  local git_root
  git_root="$(git worktree list --porcelain | awk '/^worktree / {print substr($0, 10); exit}')"

  # Get current directory to mark with arrow
  local current_dir="$PWD"

  # Get list of worktrees
  local worktrees
  worktrees="$(list_worktrees "$git_root" "$current_dir")"

  if [ -z "$worktrees" ]; then
    echo "No worktrees found" >&2
    return 1
  fi

  # Run fzf with preview
  local selected
  # shellcheck disable=SC2016
  selected="$(echo "$worktrees" | fzf \
    --ansi \
    --with-nth=1..-2 \
    --header 'Enter=select  Ctrl-D=delete  ESC=cancel' \
    --preview "$(declare -f is_git_locked; declare -f preview_worktree); preview_worktree {-1}" \
    --preview-window 'right:60%:wrap' \
    --bind "ctrl-d:execute(workout-delete {-1} {1..2} < /dev/tty > /dev/tty 2>&1)+reload(cd '$git_root' 2>/dev/null && { $(declare -f list_worktrees); if [ -d '$current_dir' ]; then list_worktrees '$git_root' '$current_dir'; else list_worktrees '$git_root' '$git_root'; fi; })")" || true

  # Check if user cancelled (empty selection)
  if [ -z "$selected" ]; then
    # Check if current directory still exists
    # If not, navigate to git root (happens when current worktree was deleted)
    if [ ! -d "$current_dir" ]; then
      # User cancelled and directory was deleted - go to git root
      echo "cd '$git_root'"
      return 0
    fi
    # User cancelled and directory still exists - don't change directory
    return 1
  fi

  # User selected something
  # Check if current directory was deleted (need to cd somewhere)
  if [ ! -d "$current_dir" ]; then
    # Current dir was deleted but user selected something - cd to selection
    local selected_path
    selected_path="$(echo "$selected" | awk '{print $NF}')"
    echo "cd '$selected_path'"
    return 0
  fi

  # Normal case: user selected something and current dir still exists
  local selected_path
  selected_path="$(echo "$selected" | awk '{print $NF}')"
  echo "cd '$selected_path'"
}

# Parse arguments
branch_name=""
create_new=false

# No args: show help
if [ $# -eq 0 ]; then
  show_help
  exit 0
fi

# One arg: check special cases
if [ $# -eq 1 ]; then
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    -)
      # Toggle to previous worktree (read from global state file)
      worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
      prev_file="$worktree_root/.workout_prev"

      if [ ! -f "$prev_file" ]; then
        echo "Error: No previous worktree location" >&2
        exit 1
      fi

      prev_location="$(cat "$prev_file")"
      if [ -z "$prev_location" ]; then
        echo "Error: No previous worktree location" >&2
        exit 1
      fi

      echo "cd '$prev_location'"
      exit 0
      ;;
    .)
      # Use current branch (old default behavior)
      branch_name="$(git rev-parse --abbrev-ref HEAD)"
      if [ "$branch_name" = "HEAD" ]; then
        echo "Error: Not on a branch (detached HEAD state)" >&2
        exit 1
      fi
      ;;
    /)
      # Interactive fzf browser
      run_fzf_selector
      exit $?
      ;;
    *)
      # Regular branch name
      branch_name="$1"
      if ! git show-ref --verify --quiet "refs/heads/$branch_name"; then
        create_new=true
      fi
      ;;
  esac
else
  # Too many args
  echo "Error: Too many arguments" >&2
  show_help >&2
  exit 1
fi

# Get remote URL and extract org/repo
remote_url="$(git remote get-url origin)"

# Extract org/repo from URL (handles both SSH and HTTPS)
# git@github.com:org/repo.git -> org/repo
# https://github.com/org/repo.git -> org/repo
org_repo="$(echo "$remote_url" | sed -E 's#.*[:/]([^/]+/[^/]+)\.git$#\1#')"

if [ -z "$org_repo" ]; then
  echo "Error: Could not extract org/repo from remote URL: $remote_url" >&2
  exit 1
fi

# Check if branch is already checked out in any worktree
existing_worktree=$(git worktree list --porcelain | awk -v branch="refs/heads/$branch_name" '
  /^worktree / { path = substr($0, 10) }
  /^branch / && $0 ~ branch { print path; exit }
')

if [ -n "$existing_worktree" ]; then
  # Branch is checked out somewhere
  worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"

  # Check if it's already in a managed worktree location
  if [[ "$existing_worktree" =~ ^$worktree_root/ ]]; then
    # Already in a worktree, just navigate there
    echo "cd '$existing_worktree'"
    exit 0
  fi

  # Branch is checked out in primary repo
  # Check if this is the trunk branch - trunk should never be migrated to a worktree
  git remote set-head origin -a >/dev/null 2>&1 || true
  trunk_branch="$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')"

  if [ "$branch_name" = "$trunk_branch" ]; then
    # Trunk branch stays in the primary repo - just navigate there
    echo "cd '$existing_worktree'"
    exit 0
  fi

  # Non-trunk branch in primary repo - need to move it to a worktree
  echo "Branch '$branch_name' is checked out in primary repo. Moving to worktree..." >&2

  # Build worktree path
  worktree_path="$worktree_root/$org_repo/$branch_name"

  # Create parent directory if needed
  mkdir -p "$(dirname "$worktree_path")"

  # Perform all git operations in the primary repo (where the branch is checked out)
  # This is critical - we need to stash/switch in the PRIMARY repo, not current worktree
  (
    cd "$existing_worktree" || exit 1

    # Check if there are uncommitted changes
    has_changes=false
    if [ -n "$(git status --porcelain)" ]; then
      echo "Stashing uncommitted changes..." >&2
      git stash push -u -m "workout: moving to worktree" >&2
      has_changes=true
    fi

    # Switch primary repo to trunk (without pulling - just free up the branch)
    echo "Switching primary repo to trunk..." >&2
    git trunk --no-pull >&2

    # Create the worktree
    echo "Creating worktree at $worktree_path..." >&2
    git worktree add "$worktree_path" "$branch_name" >&2

    # Pop stash in worktree if we stashed
    if [ "$has_changes" = true ]; then
      echo "Restoring uncommitted changes in worktree..." >&2
      (cd "$worktree_path" && git stash pop) >&2
    fi
  ) || exit 1

  # Output the cd command
  echo "cd '$worktree_path'"
  exit 0
fi

# Build worktree path
worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
worktree_path="$worktree_root/$org_repo/$branch_name"

# Check if worktree already exists at expected path
if [ -d "$worktree_path" ]; then
  # Worktree exists, just cd into it
  echo "cd '$worktree_path'"
  exit 0
fi

# Create parent directory if needed
mkdir -p "$(dirname "$worktree_path")"

# Create the worktree (redirect output to stderr so it displays but doesn't interfere with eval)
if [ "$create_new" = true ]; then
  git worktree add -b "$branch_name" "$worktree_path" >&2
else
  git worktree add "$worktree_path" "$branch_name" >&2
fi

# Output the cd command to stdout for the wrapper function to eval
echo "cd '$worktree_path'"
