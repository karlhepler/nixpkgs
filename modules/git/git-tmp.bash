#!/usr/bin/env bash
set -eou pipefail

# Create/recreate temporary branch for experiments
# - Deletes existing $BRANCH_PREFIX/tmp branch if it exists
# - Creates fresh $BRANCH_PREFIX/tmp branch from current HEAD
# - BRANCH_PREFIX is your username, exported by the Nix wrapper (modules/git/default.nix)
# - Useful for throwaway work and experiments

show_help() {
  echo "git-tmp - Create/recreate temporary branch"
  echo
  echo "USAGE:"
  echo "  git-tmp    Create fresh $BRANCH_PREFIX/tmp branch"
  echo
  echo "DESCRIPTION:"
  echo "  Creates a fresh temporary branch named $BRANCH_PREFIX/tmp from current HEAD."
  echo "  Deletes any existing $BRANCH_PREFIX/tmp branch first. Useful for throwaway"
  echo "  experiments and temporary work."
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

git branch -D "$BRANCH_PREFIX/tmp" || true
git checkout -b "$BRANCH_PREFIX/tmp"
