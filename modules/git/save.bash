#!/usr/bin/env bash
set -eou pipefail

# Quick save: commit and push in one command
# - Combines 'commit' and 'push' operations
# - Stages all changes, commits with message, and pushes to remote

show_help() {
  echo "save - Quick save: commit and push in one command"
  echo
  echo "USAGE:"
  echo "  save <message>    Commit all changes and push to remote"
  echo
  echo "DESCRIPTION:"
  echo "  Composite command that stages all changes, commits with the"
  echo "  provided message, and pushes to the remote branch."
  echo "  Equivalent to: commit <message> && push"
  echo
  echo "EXAMPLES:"
  echo "  # Save all changes with a message"
  echo "  save 'Add new feature'"
  echo
  echo "NOTES:"
  echo "  - Uses the 'commit' command (stages all changes)"
  echo "  - Uses the 'push' command (auto-tracks upstream)"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

commit "$*"
push
