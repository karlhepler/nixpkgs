#!/usr/bin/env bash

# Smart git pull with automatic upstream tracking
# - Pulls changes from remote branch
# - Automatically sets upstream tracking if not configured
# - Handles missing tracking information gracefully

show_help() {
  echo "pull - Smart git pull with automatic upstream tracking"
  echo
  echo "USAGE:"
  echo "  pull    Pull changes from remote"
  echo
  echo "DESCRIPTION:"
  echo "  Pulls changes from the remote branch. Automatically sets upstream"
  echo "  tracking if not configured. Handles missing tracking information"
  echo "  gracefully by detecting the error and configuring the upstream."
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

set +e # keep going
git pull 2> >(
  must_set_upstream=
  while IFS= read -r line; do
    if [[ $line == 'There is no tracking information for the current branch.' ]]; then
      must_set_upstream=true
      break
    fi
    echo "$line" >&2
  done

  git_pull_exit_code=$?
  if [[ $must_set_upstream != true ]]; then
    exit $git_pull_exit_code
  fi

  set -e # reset error handling
  branch="$(git symbolic-ref --short HEAD)"
  git branch --set-upstream-to="origin/$branch" "$branch"
  git pull
)
