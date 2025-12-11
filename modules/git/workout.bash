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
  echo "  -         Toggle between current and previous worktree (like cd -)"
  echo "  /         Interactive browser - view, navigate, and delete worktrees"
  echo "            (Enter=select, D=delete, ESC=cancel)"
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
}

# List all worktrees in format for fzf
list_worktrees() {
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
    if [ -z "$branch" ]; then
      printf "%-40s  %s  %s\n" "(main)" "$head" "$path"
    else
      printf "%-40s  %s  %s\n" "$branch" "$head" "$path"
    fi
  done
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

  # Get current branch
  local current_branch
  current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "detached")"

  echo "═══════════════════════════════════════════════════════════════"
  echo "  📍 WORKTREE: $worktree_path"
  echo "  🌿 BRANCH: $current_branch"
  echo "═══════════════════════════════════════════════════════════════"
  echo

  # Section 1: Git Status
  echo "━━━ GIT STATUS ━━━"
  git status --short 2>&1 || echo "Error: Could not get git status"
  echo

  # Section 2: Recent Commits
  echo "━━━ RECENT COMMITS ━━━"
  git log --oneline --color=always -5 2>&1 || echo "Error: Could not get git log"
  echo

  # Section 3: Diff stats vs main/master
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

    # Combine name-status and numstat for comprehensive view
    git diff --name-status "$trunk_branch"...HEAD | while IFS=$'\t' read -r change_type file oldfile; do
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
          printf "M  %s ${GREEN}+%s${NC}/${RED}-%s${NC}\n" \
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
    done

    # Show summary
    local summary
    summary=$(git diff --shortstat "$trunk_branch"...HEAD 2>/dev/null)
    if [ -n "$summary" ]; then
      echo
      echo "$summary"
    fi
  fi
}

# Delete a worktree with confirmation
delete_worktree() {
  local worktree_path="$1"

  if [ ! -d "$worktree_path" ]; then
    echo "Error: Worktree not found: $worktree_path" >&2
    return 1
  fi

  # Show preview
  echo "═══════════════════════════════════════════════════════════════"
  echo "  ⚠️  DELETE WORKTREE"
  echo "═══════════════════════════════════════════════════════════════"
  echo
  preview_worktree "$worktree_path"
  echo
  echo "═══════════════════════════════════════════════════════════════"
  echo "  This will delete: $worktree_path"
  echo "═══════════════════════════════════════════════════════════════"
  echo
  read -r -p "Delete this worktree? [y/N] " response
  case "$response" in
    [yY][eE][sS]|[yY])
      echo "Deleting worktree..."
      git worktree remove "$worktree_path" 2>&1
      echo "Worktree deleted successfully"
      ;;
    *)
      echo "Cancelled"
      return 1
      ;;
  esac
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

  # Get list of worktrees
  local worktrees
  worktrees="$(list_worktrees)"

  if [ -z "$worktrees" ]; then
    echo "No worktrees found" >&2
    return 1
  fi

  # Run fzf with preview
  local selected
  # shellcheck disable=SC2016
  selected="$(echo "$worktrees" | fzf \
    --ansi \
    --with-nth=1,2 \
    --header 'Enter=select  D=delete  ESC=cancel' \
    --preview "$(declare -f preview_worktree); preview_worktree {3}" \
    --preview-window 'right:60%:wrap' \
    --bind 'd:execute($(declare -f preview_worktree delete_worktree); delete_worktree {3})+reload($(declare -f list_worktrees); list_worktrees)')"

  if [ -z "$selected" ]; then
    # User cancelled
    return 1
  fi

  # Extract path (third field - hidden but still in data)
  local selected_path
  selected_path="$(echo "$selected" | awk '{print $3}')"

  # Output cd command
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

# Build worktree path
worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
worktree_path="$worktree_root/$org_repo/$branch_name"

# Check if worktree already exists
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
