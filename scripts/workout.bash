# Create and navigate to git worktree in ~/worktrees/
# - Creates worktree organized by org/repo/branch structure
# - Reuses existing worktree if already created
# - With no args: moves current branch to worktree
# - With branch name: creates/uses worktree for that branch (creates branch if needed)
#
# NOTE: Requires shell wrapper function to change directory in parent shell.
# The wrapper function is defined in home.nix zsh initContent (lines 467-475):
#
#   workout() {
#     local result
#     result="$(${homeDirectory}/.nix-profile/bin/workout "$@")"
#     local exit_code=$?
#     if [ $exit_code -eq 0 ]; then
#       eval "$result"
#     fi
#     return $exit_code
#   }
#
# This script outputs a cd command to stdout, which the wrapper evals to change directories.

# Parse arguments
branch_name=""
create_new=false

if [ $# -eq 0 ]; then
  # No args - use current branch
  branch_name="$(git rev-parse --abbrev-ref HEAD)"

  if [ "$branch_name" = "HEAD" ]; then
    echo "Error: Not on a branch (detached HEAD state)" >&2
    exit 1
  fi
elif [ $# -eq 1 ]; then
  # One arg - smart mode: use existing branch or create if doesn't exist
  branch_name="$1"

  # Check if branch exists
  if ! git show-ref --verify --quiet "refs/heads/$branch_name"; then
    # Branch doesn't exist, we'll create it
    create_new=true
  fi
else
  echo "Usage: workout [branch-name]" >&2
  echo "  workout              Move current branch to worktree" >&2
  echo "  workout <branch>     Create worktree for branch (creates branch if needed)" >&2
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
worktree_path="$HOME/worktrees/$org_repo/$branch_name"

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
