#!/usr/bin/env bash
# Workout Claude - Batch worktree creation with TMUX automation
#
# This is a WRAPPER around the existing workout command that adds:
# - Batch creation: Process multiple branches at once
# - TMUX automation: Create detached windows for each worktree
# - Claude integration: Launch staff in each window
#
# CRITICAL: This script CALLS the existing workout command.
# It does NOT duplicate workout's logic.

show_help() {
  echo "workout-claude - Batch worktree creation with TMUX windows"
  echo
  echo "USAGE:"
  echo "  workout-claude <branch1> <branch2> <branch3> ..."
  echo "  workout-claude -h, --help"
  echo
  echo "DESCRIPTION:"
  echo "  Creates multiple git worktrees with dedicated TMUX windows and"
  echo "  Claude Code instances for parallel development workflows."
  echo
  echo "  This is a wrapper around the existing 'workout' command that adds:"
  echo "  - Batch processing of multiple branches"
  echo "  - Detached TMUX window creation per worktree"
  echo "  - Automatic 'staff' (Claude Code) launch in each window"
  echo
  echo "FEATURES:"
  echo "  - Auto-prefixes branches with karlhepler/ (strips first if present)"
  echo "  - Idempotent: safe to run multiple times with same branches"
  echo "  - Error resilient: skips failures, continues with others"
  echo "  - Detached mode: windows created in background (no focus switch)"
  echo "  - Window naming: uses branch suffix only (no karlhepler/ prefix)"
  echo
  echo "EXAMPLES:"
  echo "  # Create worktrees for three features"
  echo "  workout-claude feature-x feature-y feature-z"
  echo
  echo "  # With karlhepler/ prefix (automatically handled)"
  echo "  workout-claude karlhepler/feature-x feature-y"
  echo
  echo "  # Bug fixes"
  echo "  workout-claude bug-123 bug-456 bug-789"
  echo
  echo "WHAT HAPPENS:"
  echo "  For each branch:"
  echo "  1. Calls existing 'workout' command to create worktree"
  echo "  2. Creates TMUX window in detached mode"
  echo "  3. Launches 'staff' (Claude Code) in the window"
  echo "  4. Reports success/failure"
  echo
  echo "REQUIREMENTS:"
  echo "  - git: Repository management"
  echo "  - tmux: Window management"
  echo "  - workout: Base worktree command (automatically available)"
  echo "  - staff: Claude Code command (optional, warning if missing)"
  echo
  echo "NOTES:"
  echo "  - For single worktree creation, use 'workout' command directly"
  echo "  - TMUX windows are created in background (detached)"
  echo "  - Window names use branch suffix only (no karlhepler/ prefix)"
  echo "  - Worktrees organized in ~/worktrees/org/repo/branch/"
  echo
  echo "SEE ALSO:"
  echo "  workout --help    Original worktree command"
  echo "  tmux list-windows View all TMUX windows"
}

# Check for help flag
if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  show_help
  exit 0
fi

# Check if we're in a git repo
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Error: Not in a git repository" >&2
  exit 1
fi

# Check if tmux is available
if ! command -v tmux >/dev/null 2>&1; then
  echo "Error: tmux is required for batch worktree creation" >&2
  echo "Install tmux or use 'workout' command for single worktrees" >&2
  exit 1
fi

# Check if workout command is available
if ! command -v workout >/dev/null 2>&1; then
  echo "Error: 'workout' command not found" >&2
  echo "This wrapper requires the base workout command" >&2
  exit 1
fi

# Check if staff command is available (warning only)
if ! command -v staff >/dev/null 2>&1; then
  echo "Warning: 'staff' command not found - TMUX windows will be created but staff won't launch" >&2
fi

# Arrays to track results
declare -a created=()
declare -a failed=()

# Verify we can get git remote (validates we're in a proper git repo)
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Error: Could not get git remote URL" >&2
  exit 1
fi

# Process each branch
for branch_input in "$@"; do
  # Skip help flags in batch mode
  if [[ "$branch_input" == "-h" || "$branch_input" == "--help" ]]; then
    echo "Warning: Skipping help flag in batch mode" >&2
    continue
  fi

  # Strip karlhepler/ prefix if present, then re-add it
  branch_suffix="${branch_input#karlhepler/}"
  branch_name="karlhepler/${branch_suffix}"

  echo "Processing: $branch_suffix..." >&2

  # Call existing workout command to create/navigate to worktree
  # workout outputs "cd 'path'" which we need to parse
  workout_output=$(workout "$branch_name" 2>&1)
  workout_exit=$?

  if [ $workout_exit -eq 0 ]; then
    # Parse worktree path from workout output
    # workout outputs: cd '/path/to/worktree'
    worktree_path=$(echo "$workout_output" | grep "^cd " | sed "s/^cd '\(.*\)'$/\1/")

    if [ -z "$worktree_path" ]; then
      echo "  ⚠ Could not determine worktree path from workout output" >&2
      failed+=("$branch_suffix")
      continue
    fi

    echo "  ✓ Created worktree: $worktree_path" >&2

    # Create detached TMUX window
    if tmux new-window -d -c "$worktree_path" -n "$branch_suffix" 2>/dev/null; then
      echo "  ✓ Created TMUX window: $branch_suffix" >&2

      # Launch staff in the window if available
      if command -v staff >/dev/null 2>&1; then
        tmux send-keys -t "$branch_suffix" "staff" Enter
        echo "  ✓ Launched staff in window" >&2
      fi

      created+=("$branch_suffix")
    else
      echo "  ⚠ Failed to create TMUX window (worktree created successfully)" >&2
      created+=("$branch_suffix")
    fi
  else
    # Failed
    echo "  ✗ Failed to create worktree" >&2
    echo "$workout_output" | grep -v "^cd " >&2  # Show error messages
    failed+=("$branch_suffix")
  fi
  echo >&2
done

# Print summary
echo "═══════════════════════════════════════════════════════════════" >&2
echo "BATCH WORKTREE CREATION SUMMARY" >&2
echo "═══════════════════════════════════════════════════════════════" >&2
echo >&2

if [ ${#created[@]} -gt 0 ]; then
  echo "✓ Successfully created (${#created[@]}):" >&2
  for branch in "${created[@]}"; do
    echo "  - $branch" >&2
  done
  echo >&2
fi

if [ ${#failed[@]} -gt 0 ]; then
  echo "✗ Failed (${#failed[@]}):" >&2
  for branch in "${failed[@]}"; do
    echo "  - $branch" >&2
  done
  echo >&2
fi

echo "Use 'tmux list-windows' to see all windows" >&2
echo "Use 'tmux select-window -t <name>' to switch to a window" >&2

# Exit with error if any failed
if [ ${#failed[@]} -gt 0 ]; then
  exit 1
fi

exit 0
