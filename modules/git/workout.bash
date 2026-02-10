# Create and navigate to git worktrees in ~/worktrees/ (or $WORKTREE_ROOT)
# - Creates worktree organized by org/repo/branch structure
# - Reuses existing worktree if already created (idempotent)
# - With no args: opens interactive browser
# - With `.`: creates worktree for current branch
# - With `-`: toggles to previous worktree location (persists across sessions)
# - With `/`: opens interactive fzf browser to view and manage worktrees
# - With `clean`: deletes worktrees older than 30 days (with confirmation)
# - With `clean --expunge`: deletes ALL worktrees (with confirmation)
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
  echo "  workout                    Browse and manage worktrees (interactive)"
  echo "  workout .                  Create worktree for current branch"
  echo "  workout -                  Toggle to previous worktree"
  echo "  workout <branch>           Create worktree for branch"
  echo "  workout clean              Delete worktrees with merged branches"
  echo "  workout clean --expunge    Delete ALL worktrees (dangerous!)"
  echo "  workout -h, --help         Show this help"
  echo
  echo "DESCRIPTION:"
  echo "  Manages git worktrees organized in ~/worktrees/org/repo/branch/."
  echo "  Creates worktrees automatically if they don't exist (idempotent)."
  echo "  Enables working on multiple branches simultaneously without stashing."
  echo
  echo "  Requires a shell wrapper function (automatically configured in this setup)"
  echo "  that handles directory changes and state management."
  echo
  echo "COMMANDS:"
  echo "  .         Create/navigate to worktree for current branch"
  echo "            If in primary repo: migrates branch to worktree,"
  echo "            preserves uncommitted changes, restores primary to trunk"
  echo
  echo "  -         Toggle between current and previous worktree (like cd -)"
  echo "            State persists across shell sessions in:"
  echo "            \$WORKTREE_ROOT/.workout_prev"
  echo "            Only tracks worktree locations (not primary repo)"
  echo
  echo "  <branch>  Create/navigate to worktree for specified branch"
  echo "            If branch doesn't exist, creates it from current HEAD"
  echo "            Reuses existing worktree if already created (idempotent)"
  echo
  echo "  clean     Delete worktrees older than 30 days (with confirmation)"
  echo "            Lists all matching worktrees and prompts before deletion"
  echo "            Uses trash command for safe deletion + git worktree prune"
  echo
  echo "  clean --expunge  Delete ALL worktrees (dangerous!)"
  echo "            Removes all worktrees regardless of age"
  echo "            Primary repo and current worktree are preserved"
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
  echo "  workout"
  echo
  echo "  # Typical workflow: work on feature, switch to main, switch back"
  echo "  workout feature/xyz        # Work on feature"
  echo "  workout main               # Quick check of main"
  echo "  workout -                  # Back to feature/xyz"
  echo
  echo "  # Cleanup: delete merged worktrees"
  echo "  workout clean              # Delete worktrees with merged branches"
  echo "  workout clean --expunge    # Delete ALL worktrees (careful!)"
  echo
  echo "CLEANUP COMMANDS:"
  echo "  workout clean"
  echo "    Deletes worktrees with branches merged into the default branch"
  echo "    - Detects default branch automatically (main/master/develop)"
  echo "    - Checks if each worktree's branch is merged"
  echo "    - Lists all merged branches with merge status"
  echo "    - Prompts for confirmation before deletion"
  echo "    - Excludes primary repo and current worktree (safe)"
  echo "    - Uses trash command for safe deletion"
  echo "    - Runs 'git worktree prune' to clean up metadata"
  echo
  echo "  workout clean --expunge"
  echo "    Deletes ALL worktrees regardless of merge status (DANGEROUS!)"
  echo "    - Lists all worktrees that will be deleted"
  echo "    - Requires 'yes' confirmation (not just 'y')"
  echo "    - Excludes primary repo and current worktree (safe)"
  echo "    - Use this for major cleanup or when switching projects"
  echo
  echo "INTERACTIVE BROWSER:"
  echo "  Running 'workout' with no arguments launches an interactive browser using fzf:"
  echo
  echo "  List View:"
  echo "    - Current worktree marked with → prefix"
  echo "    - Primary repo marked with [brackets] around branch name"
  echo "    - Shows: branch name, commit SHA, path"
  echo
  echo "  Preview Pane (right side):"
  echo "    - Git status (modified, staged, untracked files)"
  echo "    - Recent commits (last 5)"
  echo "    - Changes vs trunk (file-level diff with line counts)"
  echo
  echo "  Keybindings:"
  echo "    - Enter: Navigate to selected worktree"
  echo "    - Ctrl-D: Delete selected worktree (with confirmation)"
  echo "    - ESC: Cancel and stay in current location"
  echo
  echo "  Delete Behavior:"
  echo "    - If you delete your current worktree, workout navigates to:"
  echo "      → Selected worktree (if you select one after deleting)"
  echo "      → Git root / primary repo (if you ESC after deleting)"
  echo "    - List refreshes automatically after deletion"
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
  echo "TRUNK BRANCH BEHAVIOR:"
  echo "  The trunk branch (main/master) is treated specially:"
  echo "  - Always stays checked out in the primary repository"
  echo "  - Never migrated to a worktree location"
  echo "  - Detected automatically via 'git symbolic-ref refs/remotes/origin/HEAD'"
  echo "  - When navigating to trunk, workout goes to primary repo, not a worktree"
  echo
  echo "  This design ensures the primary clone remains stable and on trunk."
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
  echo "TECHNICAL DETAILS:"
  echo "  Shell Wrapper:"
  echo "    - Workout requires a shell wrapper function to change directories"
  echo "    - The wrapper evaluates the 'cd' command output by this script"
  echo "    - Wrapper saves current location to state file for toggle feature"
  echo "    - Automatically configured in this Nix Home Manager setup"
  echo
  echo "  Worktree Organization:"
  echo "    - All worktrees stored under \$WORKTREE_ROOT/<org>/<repo>/<branch>/"
  echo "    - Org/repo extracted from git remote URL (origin)"
  echo "    - Works with both SSH and HTTPS remote URLs"
  echo
  echo "  Shared Git Data:"
  echo "    - Worktrees share .git directory (refs, tags, remotes, config)"
  echo "    - Each worktree has independent working directory and index"
  echo "    - Enables parallel work without repo duplication"
  echo
  echo "  State Management:"
  echo "    - Toggle history: \$WORKTREE_ROOT/.workout_prev"
  echo "    - Only worktree paths saved (primary repo excluded from toggle)"
  echo "    - State persists across shell sessions"
  echo
  echo "NOTES:"
  echo "  - Idempotent: safe to run multiple times with same branch"
  echo "  - Creates branches from current HEAD if they don't exist"
  echo "  - Uncommitted changes preserved when migrating from primary repo"
  echo "  - Useful for reviewing PRs, testing changes, or parallel development"
  echo "  - Delete worktrees via interactive browser (/) with Ctrl-D"
  echo
  echo "HOOKS:"
  echo "  Workout supports a post-switch hook that runs automatically when a"
  echo "  worktree is FIRST CREATED. The hook only runs once per worktree:"
  echo "  - When creating new worktrees (first time)"
  echo "  - When migrating from primary repo to worktree (first time)"
  echo "  - NOT when navigating to existing worktrees (subsequent times)"
  echo
  echo "  This is designed for one-time setup tasks like initial dependency"
  echo "  installation, direnv allow, or environment configuration."
  echo
  echo "  Hook Location:"
  echo "    .git/workout-hooks/post-switch"
  echo "    (Stored in main .git directory, shared across all worktrees)"
  echo
  echo "  Format Requirements:"
  echo "    - Must be an executable file (chmod +x)"
  echo "    - Can be any executable (bash script, Python, compiled binary, etc.)"
  echo "    - Must have proper shebang if it's a script (#!/usr/bin/env bash)"
  echo "    - If not executable, silently ignored (no error)"
  echo
  echo "  Execution Context:"
  echo "    - Working directory: The worktree directory (CWD set automatically)"
  echo "    - Arguments: \$1 = absolute worktree path, \$2 = branch name"
  echo "    - Environment: Inherits from parent shell"
  echo "    - Runs in subshell (cannot affect parent workout process)"
  echo
  echo "  Exit Code Handling:"
  echo "    - Exit 0: Success, no output"
  echo "    - Non-zero: Warning logged to stderr, navigation continues"
  echo "    - Hook failures never prevent navigation"
  echo
  echo "  Example Setup (Bash):"
  echo "    mkdir -p .git/workout-hooks"
  echo "    cat > .git/workout-hooks/post-switch << 'EOF'"
  echo "    #!/usr/bin/env bash"
  echo "    # Auto-allow direnv if .envrc exists"
  echo "    [[ -f .envrc ]] && direnv allow"
  echo "    EOF"
  echo "    chmod +x .git/workout-hooks/post-switch"
  echo
  echo "  Example Setup (Python):"
  echo "    cat > .git/workout-hooks/post-switch << 'EOF'"
  echo "    #!/usr/bin/env python3"
  echo "    import sys, os"
  echo "    worktree_path = sys.argv[1]"
  echo "    branch_name = sys.argv[2]"
  echo "    # Custom logic here"
  echo "    print(f\"Switched to {branch_name}\")"
  echo "    EOF"
  echo "    chmod +x .git/workout-hooks/post-switch"
  echo
  echo "  Common Use Cases (one-time setup):"
  echo "    - Auto-allow direnv (.envrc)"
  echo "    - Initial dependency installation (npm install, bundle install)"
  echo "    - Database setup or migrations"
  echo "    - Generate environment-specific config files"
  echo "    - Send 'new worktree created' notifications"
  echo "    - Initialize IDE workspace settings"
  echo "    - Copy template files or configurations"
}

# Execute post-switch hook if it exists
# Arguments: worktree_path branch_name
run_post_switch_hook() {
  local worktree_path="$1"
  local branch_name="$2"

  # Get shared .git directory (handle .git file in worktrees)
  local git_dir
  git_dir="$(git rev-parse --git-dir 2>/dev/null)" || return 0

  if [[ -f "$git_dir" ]]; then
    # .git is a file (worktree) - extract main git directory
    local real_git_dir
    real_git_dir="$(grep '^gitdir:' "$git_dir" | cut -d' ' -f2)"
    git_dir="${real_git_dir%/worktrees/*}"
  fi

  local hook_path="$git_dir/workout-hooks/post-switch"

  # Silent return if hook doesn't exist, isn't a regular file, or isn't executable
  [[ ! -f "$hook_path" ]] && return 0
  [[ ! -x "$hook_path" ]] && return 0

  # Resolve to absolute path before cd (in case hook_path is relative)
  hook_path="$(cd "$(dirname "$hook_path")" && pwd)/$(basename "$hook_path")"

  # Execute in subshell with worktree as CWD
  (
    cd "$worktree_path" || exit 1
    "$hook_path" "$worktree_path" "$branch_name"
  ) || {
    local exit_code=$?
    echo "Warning: post-switch hook failed (exit code: $exit_code)" >&2
    echo "Hook location: $hook_path" >&2
    return 0
  }
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

# Detect the default branch (main/master/develop)
detect_default_branch() {
  # Try to get from origin/HEAD first
  local default_branch
  default_branch="$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')"

  if [ -n "$default_branch" ]; then
    echo "$default_branch"
    return 0
  fi

  # Fallback: check for common branch names
  if git rev-parse --verify main >/dev/null 2>&1; then
    echo "main"
    return 0
  elif git rev-parse --verify master >/dev/null 2>&1; then
    echo "master"
    return 0
  elif git rev-parse --verify develop >/dev/null 2>&1; then
    echo "develop"
    return 0
  fi

  # Could not detect default branch
  return 1
}

# Check if a branch is merged into the default branch
# Arguments: worktree_path default_branch
is_branch_merged() {
  local worktree_path="$1"
  local default_branch="$2"

  # Get the branch name for this worktree
  local branch
  branch="$(git -C "$worktree_path" branch --show-current 2>/dev/null)"

  # Skip if detached HEAD or can't determine branch
  if [ -z "$branch" ]; then
    return 1
  fi

  # Check if this branch is merged into default branch
  if git branch --merged "$default_branch" 2>/dev/null | grep -q "^[*+ ] $branch\$"; then
    return 0
  fi

  return 1
}

# Clean worktrees (delete merged or all worktrees)
# Arguments: [--expunge]
clean_worktrees() {
  local expunge=false
  if [ "${1:-}" = "--expunge" ]; then
    expunge=true
  fi

  # Check if we're in a git repo
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "Error: Not in a git repository" >&2
    return 1
  fi

  # Get git root directory (primary repo) to exclude from deletion
  local git_root
  git_root="$(git worktree list --porcelain | awk '/^worktree / {print substr($0, 10); exit}')"

  # Get current directory to exclude from deletion
  local current_dir="$PWD"

  # Detect default branch (only needed for non-expunge mode)
  local default_branch=""
  if [ "$expunge" = false ]; then
    if ! default_branch="$(detect_default_branch)"; then
      echo "Error: Could not detect default branch" >&2
      echo "Try running: git remote set-head origin --auto" >&2
      return 1
    fi
  fi

  # Collect worktrees to delete
  local -a worktrees_to_delete=()
  local -a worktree_info=()

  # Parse worktree list and filter based on mode
  while IFS='|' read -r path branch head; do
    # Skip primary repo (git root)
    [ "$path" = "$git_root" ] && continue

    # Skip current worktree for safety
    [ "$path" = "$current_dir" ] && continue

    # Check directory exists
    [ ! -d "$path" ] && continue

    # Skip if no branch (detached HEAD)
    if [ -z "$branch" ]; then
      continue
    fi

    if [ "$expunge" = true ]; then
      # Expunge mode: target ALL worktrees (no progress output)
      worktrees_to_delete+=("$path")
      worktree_info+=("$branch|$head|$path")
    else
      # Regular mode: target worktrees with merged branches
      if is_branch_merged "$path" "$default_branch"; then
        worktrees_to_delete+=("$path")
        worktree_info+=("$branch|$head|$path")
      fi
    fi
  done < <(git worktree list --porcelain | awk '
    /^worktree / { path = substr($0, 10) }
    /^branch / {
      branch = substr($0, 8)
      sub(/^refs\/heads\//, "", branch)
    }
    /^HEAD / { head = substr($0, 6) }
    /^$/ {
      if (path != "") {
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
  ')

  # Check if we found any worktrees to delete
  local count="${#worktrees_to_delete[@]}"

  if [ "$count" -eq 0 ]; then
    if [ "$expunge" = true ]; then
      echo "No worktrees found to delete (primary repo and current worktree excluded)" >&2
    else
      echo "No merged branches found to clean up" >&2
    fi
    return 0
  fi

  # Display what will be deleted
  echo "═══════════════════════════════════════════════════════════════" >&2
  if [ "$expunge" = true ]; then
    echo "  WORKOUT CLEAN --expunge: Delete ALL worktrees" >&2
  else
    echo "  WORKOUT CLEAN: Delete worktrees with merged branches" >&2
  fi
  echo "═══════════════════════════════════════════════════════════════" >&2
  echo >&2
  echo "Found $count worktree(s) to delete:" >&2
  echo >&2

  # Show each worktree
  for info in "${worktree_info[@]}"; do
    IFS='|' read -r branch head path <<< "$info"

    echo "  • $branch" >&2
  done

  echo >&2

  # Prompt for confirmation
  local prompt
  if [ "$expunge" = true ]; then
    prompt="Delete ALL $count worktree(s)? This cannot be undone! (yes/no): "
  else
    prompt="Delete $count worktree(s) with merged branches? (yes/no): "
  fi

  echo -n "$prompt" >&2
  read -r response < /dev/tty

  # Only proceed if user types exactly "yes"
  if [ "$response" != "yes" ]; then
    echo "Cancelled - no worktrees deleted" >&2
    return 1
  fi

  echo >&2

  # Delete each worktree (silently - trash is fast)
  local deleted_count=0
  local failed_count=0

  for path in "${worktrees_to_delete[@]}"; do
    if trash "$path" 2>/dev/null; then
      deleted_count=$((deleted_count + 1))
    else
      failed_count=$((failed_count + 1))
    fi
  done

  # Prune git's internal worktree tracking
  git worktree prune >&2 2>&1

  echo >&2
  echo "✓ Deleted: $deleted_count worktree(s)" >&2

  if [ "$failed_count" -gt 0 ]; then
    echo "✗ Failed: $failed_count worktree(s)" >&2
  fi

  return 0
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

# No args: open interactive browser
if [ $# -eq 0 ]; then
  run_fzf_selector
  exit $?
fi

# One arg: check special cases
if [ $# -eq 1 ]; then
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    clean)
      # Clean old worktrees
      clean_worktrees
      exit $?
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
elif [ $# -eq 2 ]; then
  # Two args: check for clean --expunge
  if [ "$1" = "clean" ] && [ "$2" = "--expunge" ]; then
    clean_worktrees --expunge
    exit $?
  else
    # Invalid two-arg combination
    echo "Error: Invalid arguments" >&2
    show_help >&2
    exit 1
  fi
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

# Security: Reject path traversal attempts in org/repo
if [[ "$org_repo" == *".."* ]]; then
  echo "Error: Invalid org/repo path detected (contains '..'): $org_repo" >&2
  echo "This could indicate a malicious git remote URL." >&2
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

  # Output hook path if it exists (new worktree, so run hook)
  git_dir="$(git rev-parse --git-dir 2>/dev/null)"
  if [[ -f "$git_dir" ]]; then
    real_git_dir="$(grep '^gitdir:' "$git_dir" | cut -d' ' -f2)"
    git_dir="${real_git_dir%/worktrees/*}"
  fi
  hook_path="$git_dir/workout-hooks/post-switch"
  if [[ -f "$hook_path" && -x "$hook_path" ]]; then
    # Resolve to absolute path
    hook_path="$(cd "$(dirname "$hook_path")" && pwd)/$(basename "$hook_path")"
    echo "'$hook_path'"
  fi

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

# Output hook path if it exists (new worktree, so run hook)
git_dir="$(git rev-parse --git-dir 2>/dev/null)"
if [[ -f "$git_dir" ]]; then
  real_git_dir="$(grep '^gitdir:' "$git_dir" | cut -d' ' -f2)"
  git_dir="${real_git_dir%/worktrees/*}"
fi
hook_path="$git_dir/workout-hooks/post-switch"
if [[ -f "$hook_path" && -x "$hook_path" ]]; then
  # Resolve to absolute path
  hook_path="$(cd "$(dirname "$hook_path")" && pwd)/$(basename "$hook_path")"
  echo "'$hook_path'"
fi
