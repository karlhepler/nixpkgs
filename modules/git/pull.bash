#!/usr/bin/env bash
set -eou pipefail

# Smart git pull with automatic upstream tracking
# - Pulls changes from the remote branch
# - If the current branch has no upstream yet, sets it to origin/<branch> first
# - Passes any arguments straight through to `git pull`

show_help() {
  echo "pull - Smart git pull with automatic upstream tracking"
  echo
  echo "USAGE:"
  echo "  pull [git pull args]    Pull changes from remote"
  echo
  echo "DESCRIPTION:"
  echo "  Pulls changes from the remote branch. If the current branch has no"
  echo "  upstream configured, sets it to origin/<branch> before pulling."
  echo
  echo "EXAMPLES:"
  echo "  # Pull latest changes"
  echo "  pull"
  echo
  echo "  # Pull with rebase"
  echo "  pull --rebase"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

if ! git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
  branch="$(git symbolic-ref --short HEAD)"
  # The remote branch has to exist locally as origin/<branch> before it can be tracked
  if ! git fetch origin "$branch"; then
    echo "pull: '$branch' has no upstream and origin has no branch with that name" >&2
    exit 1
  fi
  git branch --set-upstream-to="origin/$branch" "$branch"
fi

git pull "$@"
