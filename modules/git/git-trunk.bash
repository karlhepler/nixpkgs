#!/usr/bin/env bash
set -eou pipefail

# Switch to trunk branch (main/master) and pull latest changes
# - Automatically detects whether trunk is 'main' or 'master'
# - Updates local trunk branch with remote changes

show_help() {
  echo "git-trunk - Switch to trunk branch and pull latest"
  echo
  echo "USAGE:"
  echo "  git-trunk    Checkout trunk and pull latest changes"
  echo
  echo "DESCRIPTION:"
  echo "  Switches to the trunk branch (main or master) and pulls the"
  echo "  latest changes from the remote. Automatically detects whether"
  echo "  the trunk branch is 'main' or 'master'."
  echo
  echo "EXAMPLES:"
  echo "  # Switch to trunk and update"
  echo "  git-trunk"
  echo
  echo "NOTES:"
  echo "  - Automatically detects trunk branch (main or master)"
  echo "  - Pulls latest changes after checkout"
  echo "  - Use git-sync to merge trunk into current branch instead"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

git remote set-head origin -a # make sure there is an origin/HEAD
trunk="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"
git checkout "$trunk"
git pull
