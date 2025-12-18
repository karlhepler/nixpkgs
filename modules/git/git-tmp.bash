#!/usr/bin/env bash
set -eou pipefail

# Create/recreate temporary branch for experiments
# - Deletes existing karlhepler/tmp branch if it exists
# - Creates fresh karlhepler/tmp branch from current HEAD
# - Useful for throwaway work and experiments

show_help() {
  echo "git-tmp - Create/recreate temporary branch"
  echo
  echo "USAGE:"
  echo "  git-tmp    Create fresh karlhepler/tmp branch"
  echo
  echo "DESCRIPTION:"
  echo "  Creates a fresh temporary branch named karlhepler/tmp from current HEAD."
  echo "  Deletes any existing karlhepler/tmp branch first. Useful for throwaway"
  echo "  experiments and temporary work."
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

git branch -D karlhepler/tmp || true
git checkout -b karlhepler/tmp
