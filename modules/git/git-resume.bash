#!/usr/bin/env bash
set -eou pipefail

# Resume work on most recently used branch
# - Checks out your most recently committed <username>/* branch
# - Uses git-branches (default filter: your username prefix) to find it

show_help() {
  echo "git-resume - Resume work on most recently used branch"
  echo
  echo "USAGE:"
  echo "  git-resume    Checkout your most recently committed branch"
  echo
  echo "DESCRIPTION:"
  echo "  Checks out the most recently committed of your <username>/* local"
  echo "  branches (the ones git-branches lists by default)."
  echo
  echo "EXAMPLES:"
  echo "  # Resume work on most recent branch"
  echo "  git-resume"
  echo
  echo "NOTES:"
  echo "  - Depends on git-branches command"
  echo "  - Only considers branches under your username prefix"
  echo "  - Useful for switching back to active work"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

branch="$(git branches | head -1)"
if [ -z "$branch" ]; then
  echo "git-resume: no branches under your username prefix" >&2
  exit 1
fi
git checkout "$branch"
