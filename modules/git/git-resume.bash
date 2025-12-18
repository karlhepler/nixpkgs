#!/usr/bin/env bash
set -eou pipefail

# Resume work on most recently used branch
# - Checks out the most recently committed branch
# - Uses git-branches command to find most recent branch

show_help() {
  echo "git-resume - Resume work on most recently used branch"
  echo
  echo "USAGE:"
  echo "  git-resume    Checkout most recently committed branch"
  echo
  echo "DESCRIPTION:"
  echo "  Checks out the branch with the most recent commit."
  echo "  Uses git-branches to find and sort branches by commit date."
  echo
  echo "EXAMPLES:"
  echo "  # Resume work on most recent branch"
  echo "  git-resume"
  echo
  echo "NOTES:"
  echo "  - Depends on git-branches command"
  echo "  - Selects branch with most recent commit"
  echo "  - Useful for switching back to active work"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

git checkout "$(git branches | head -1)"
