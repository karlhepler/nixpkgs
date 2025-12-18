#!/usr/bin/env bash
set -eou pipefail

# Change to git repository root
# - Gets repository root using git rev-parse
# - Outputs cd command for parent shell to evaluate
# - Requires zsh wrapper function to actually change directory

show_help() {
  echo "groot - Change to git repository root"
  echo
  echo "USAGE:"
  echo "  groot    Change to repository root directory"
  echo
  echo "DESCRIPTION:"
  echo "  Changes directory to the git repository root."
  echo "  Gets the root path using 'git rev-parse --show-toplevel'."
  echo "  Outputs a cd command for the parent shell to evaluate."
  echo
  echo "EXAMPLES:"
  echo "  # Change to repo root"
  echo "  groot"
  echo
  echo "NOTES:"
  echo "  - Requires zsh wrapper function (defined in modules/zsh.nix)"
  echo "  - The wrapper evaluates the output to change directory"
  echo "  - Only works inside a git repository"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

# Check if in git repository
if ! git rev-parse --show-toplevel > /dev/null 2>&1; then
  echo "Error: Not in a git repository" >&2
  exit 1
fi

# Get root path and output cd command
root_path="$(git rev-parse --show-toplevel)"
echo "cd '$root_path'"
