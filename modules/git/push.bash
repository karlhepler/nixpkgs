#!/usr/bin/env bash
set -eou pipefail

# Smart git push with automatic upstream tracking
# - Pushes changes to remote branch
# - Automatically sets upstream tracking on first push
# - Passes through additional arguments to git push

show_help() {
  echo "push - Smart git push with automatic upstream tracking"
  echo
  echo "USAGE:"
  echo "  push [options]    Push changes to remote"
  echo
  echo "DESCRIPTION:"
  echo "  Pushes changes to the remote branch. Automatically sets upstream"
  echo "  tracking on the first push if not already configured."
  echo "  Passes through all arguments to git push."
  echo
  echo "EXAMPLES:"
  echo "  # Push current branch"
  echo "  push"
  echo
  echo "  # Force push (careful!)"
  echo "  push --force-with-lease"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

git_push='git push'
if ! git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  git_push="$git_push --set-upstream"
fi
$git_push "$@"
