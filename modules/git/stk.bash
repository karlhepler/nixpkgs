#!/usr/bin/env bash
set -euo pipefail

# stk: Stacked PR workflow using Graphite CLI integrated with workout worktrees
# - No args: gt restack
# - `stk <branch>`: auto-inits graphite if needed, creates graphite branch, creates worktree
# - `stk log`: gt log
# - `stk pull`: gt sync
#
# NOTE: Requires shell wrapper function to change directory in parent shell.
# A `stk()` wrapper is defined in modules/zsh.nix (mirrors the workout wrapper):
#
#   stk() {
#     local result
#     result="$(~/.nix-profile/bin/stk "$@")"
#     local exit_code=$?
#     if [ $exit_code -eq 0 ]; then
#       if [[ "$result" == cd\ * ]]; then
#         local worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
#         mkdir -p "$worktree_root"
#         echo "$PWD" > "$worktree_root/.workout_prev"
#         eval "$result"
#       else
#         echo "$result"
#       fi
#     fi
#     return $exit_code
#   }

show_help() {
  echo "stk - Stacked PR workflow with Graphite CLI and git worktrees"
  echo
  echo "USAGE:"
  echo "  stk                    Rebase the current stack (gt restack)"
  echo "  stk <branch>           Create graphite branch + worktree"
  echo "  stk log                Show graphite stack log (gt log)"
  echo "  stk pull               Sync with remote (gt sync)"
  echo "  stk -h, --help         Show this help"
  echo
  echo "DESCRIPTION:"
  echo "  Combines Graphite CLI stacked PRs with the workout worktree system."
  echo "  'stk <branch>' is identical muscle memory to 'workout <branch>',"
  echo "  but automatically registers the branch in Graphite."
  echo
  echo "  Auto-initializes Graphite if the repo has not been initialized"
  echo "  (.git/.graphite_repo_config does not exist). Defaults trunk to main."
  echo
  echo "EXAMPLES:"
  echo "  # Rebase the whole stack after amending a parent branch"
  echo "  stk"
  echo
  echo "  # Create a new stacked branch with worktree"
  echo "  stk karlhepler/my-feature"
  echo
  echo "  # Show graphite stack structure"
  echo "  stk log"
  echo
  echo "  # Sync with remote and clean up merged branches"
  echo "  stk pull"
}

# Ensure the repo is initialized with Graphite
ensure_gt_init() {
  local graphite_config
  graphite_config="$(git rev-parse --git-common-dir 2>/dev/null)/.graphite_repo_config"

  if [[ ! -f "$graphite_config" ]]; then
    echo "Initializing Graphite for this repository..." >&2
    gt init --trunk main >&2
  fi
}

# No args: restack
if [[ $# -eq 0 ]]; then
  exec gt restack
fi

case "$1" in
  -h|--help)
    show_help
    exit 0
    ;;
  log)
    exec gt log
    ;;
  pull)
    exec gt sync
    ;;
  -*)
    # Unrecognized flag
    echo "Error: Unknown option: $1" >&2
    show_help >&2
    exit 1
    ;;
  *)
    branch_name="$1"

    # Ensure graphite is initialized for this repo
    ensure_gt_init

    # Create the graphite-tracked branch non-interactively
    gt create "$branch_name" >&2

    # Create the worktree (workout binary outputs cd command to stdout)
    workout "$branch_name"
    ;;
esac
