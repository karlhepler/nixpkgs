#!/usr/bin/env bash
set -eou pipefail

# Create/recreate temporary branch for experiments
# - Creates $BRANCH_PREFIX/tmp from current HEAD, or resets it there if it exists
# - BRANCH_PREFIX is your username, exported by the Nix wrapper (modules/git/default.nix)
# - Useful for throwaway work and experiments

show_help() {
  echo "git-tmp - Create/recreate temporary branch"
  echo
  echo "USAGE:"
  echo "  git-tmp    Create fresh $BRANCH_PREFIX/tmp branch"
  echo
  echo "DESCRIPTION:"
  echo "  Checks out a temporary branch named $BRANCH_PREFIX/tmp at current HEAD,"
  echo "  creating it or resetting it there if it already exists. Works when you are"
  echo "  already on it. Useful for throwaway experiments and temporary work."
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

git checkout -B "$BRANCH_PREFIX/tmp"
