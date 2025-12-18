#!/usr/bin/env bash
set -eou pipefail

# Merge trunk branch (main/master) into current branch
# - Fetches latest trunk from remote
# - Merges trunk changes into current working branch
# - Keeps you on your current branch after sync

show_help() {
  echo "git-sync - Merge trunk into current branch"
  echo
  echo "USAGE:"
  echo "  git-sync    Fetch and merge trunk into current branch"
  echo
  echo "DESCRIPTION:"
  echo "  Fetches the latest trunk branch (main or master) from the remote"
  echo "  and merges it into your current working branch. Automatically"
  echo "  detects whether the trunk is 'main' or 'master'."
  echo "  Keeps you on your current branch after sync."
  echo
  echo "EXAMPLES:"
  echo "  # Sync current branch with latest trunk"
  echo "  git-sync"
  echo
  echo "NOTES:"
  echo "  - Automatically detects trunk branch (main or master)"
  echo "  - Stays on current branch after merge"
  echo "  - Use git-trunk to switch to trunk branch instead"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

# Determine trunk branch (main or master)
git remote set-head origin -a
trunk="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"

# Fetch latest trunk from remote and merge into current branch
git fetch origin "$trunk"
git merge "origin/$trunk"
