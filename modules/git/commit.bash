#!/usr/bin/env bash
set -eou pipefail

# Git commit with automatic staging
# - Stages all changes in repository root before committing
# - Special case: 'noop' message creates empty commit

show_help() {
  echo "commit - Git commit with automatic staging"
  echo
  echo "USAGE:"
  echo "  commit <message>    Stage all changes and commit with message"
  echo "  commit noop         Create empty commit (no changes)"
  echo
  echo "DESCRIPTION:"
  echo "  Automatically stages all changes in the repository root and creates"
  echo "  a commit with the provided message. Special case: 'noop' creates an"
  echo "  empty commit without staging any changes (useful for triggering CI)."
  echo
  echo "EXAMPLES:"
  echo "  # Commit all changes with a message"
  echo "  commit 'Add new feature'"
  echo
  echo "  # Create empty commit"
  echo "  commit noop"
  echo
  echo "NOTES:"
  echo "  - Stages ALL changes in repository root (git add <repo-root>)"
  echo "  - Part of the save workflow: save = commit + push"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

msg="$*"
if [ "$msg" == 'noop' ]; then
  git commit --allow-empty -m "$msg"
else
  git add "$(git rev-parse --show-toplevel)"
  git commit -m "$msg"
fi
