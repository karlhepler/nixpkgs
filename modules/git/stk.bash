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
  echo "  stk status             Show stack position then working tree state"
  echo "  stk pr [draft]         Create draft PR or convert ready→draft"
  echo "  stk pr ready           Create ready PR or promote draft→ready"
  echo "  stk pr close [comment] Close PR with optional comment"
  echo "  stk pr merge           Merge PR (squash)"
  echo "  stk pr view [args]     View current branch PR (gh pr view passthrough)"
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
  echo "  # Show full stack position and working tree state"
  echo "  stk status"
  echo
  echo "  # Sync with remote and clean up merged branches"
  echo "  stk pull"
  echo
  echo "  # Create a draft PR (or convert existing ready PR to draft)"
  echo "  stk pr"
  echo
  echo "  # Promote draft PR to ready for review"
  echo "  stk pr ready"
  echo
  echo "  # Close PR with an optional comment"
  echo "  stk pr close 'Superseded by #456'"
  echo
  echo "  # Merge PR as squash commit"
  echo "  stk pr merge"
  echo
  echo "  # View PR details (e.g., --web, --json)"
  echo "  stk pr view --web"
}

# Get current PR state as JSON: {state, isDraft}
# Returns empty string and non-zero exit if no PR exists for the current branch.
get_pr_state() {
  gh pr view --json state,isDraft --jq '{state: .state, isDraft: .isDraft}' 2>/dev/null
}

# Convert a ready PR to draft. Tries --undo flag first (newer gh), falls back to
# convert-to-draft (older gh).
convert_to_draft() {
  if gh pr ready --help 2>&1 | rg -q -- '--undo'; then
    gh pr ready --undo
  else
    gh pr convert-to-draft
  fi
}

stk_pr_draft() {
  local pr_json
  if ! pr_json="$(get_pr_state)"; then
    echo "No PR found for current branch. Creating draft PR..." >&2
    gt submit --draft
    return
  fi

  local state is_draft
  state="$(echo "$pr_json" | jq -r '.state')"
  is_draft="$(echo "$pr_json" | jq -r '.isDraft')"

  case "$state" in
    MERGED)
      echo "PR is already merged. Nothing to do." >&2
      return 0
      ;;
    CLOSED)
      echo "PR is closed. Nothing to do." >&2
      return 0
      ;;
  esac

  if [[ "$is_draft" == "true" ]]; then
    echo "PR is already a draft." >&2
    return 0
  fi

  echo "Converting PR to draft..." >&2
  convert_to_draft
}

stk_pr_ready() {
  local pr_json
  if ! pr_json="$(get_pr_state)"; then
    echo "No PR found for current branch. Creating ready PR..." >&2
    gt submit
    return
  fi

  local state is_draft
  state="$(echo "$pr_json" | jq -r '.state')"
  is_draft="$(echo "$pr_json" | jq -r '.isDraft')"

  case "$state" in
    MERGED)
      echo "PR is already merged. Nothing to do." >&2
      return 0
      ;;
    CLOSED)
      echo "PR is closed. Nothing to do." >&2
      return 0
      ;;
  esac

  if [[ "$is_draft" == "false" ]]; then
    echo "PR is already ready for review." >&2
    return 0
  fi

  echo "Marking PR as ready for review..." >&2
  gh pr ready
}

stk_pr_close() {
  local comment="${1:-}"

  local pr_json
  if ! pr_json="$(get_pr_state)"; then
    echo "No PR found for current branch. Nothing to close." >&2
    return 0
  fi

  local state
  state="$(echo "$pr_json" | jq -r '.state')"

  case "$state" in
    MERGED)
      echo "PR is already merged. Nothing to close." >&2
      return 0
      ;;
    CLOSED)
      echo "PR is already closed." >&2
      return 0
      ;;
  esac

  if [[ -n "$comment" ]]; then
    gh pr close --comment "$comment"
  else
    gh pr close
  fi
}

stk_pr_merge() {
  local pr_json
  if ! pr_json="$(get_pr_state)"; then
    echo "No PR found for current branch. Nothing to merge." >&2
    return 0
  fi

  local state
  state="$(echo "$pr_json" | jq -r '.state')"

  case "$state" in
    MERGED)
      echo "PR is already merged." >&2
      return 0
      ;;
    CLOSED)
      echo "PR is closed and cannot be merged." >&2
      return 0
      ;;
  esac

  gh pr merge --squash
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
  status)
    gt log
    git status
    ;;
  pull)
    exec gt sync
    ;;
  pr)
    shift
    subcommand="${1:-draft}"
    shift || true

    case "$subcommand" in
      draft)
        stk_pr_draft
        ;;
      ready)
        stk_pr_ready
        ;;
      close)
        stk_pr_close "${1:-}"
        ;;
      merge)
        stk_pr_merge
        ;;
      view)
        gh pr view "$@"
        ;;
      *)
        echo "Error: Unknown pr subcommand: $subcommand" >&2
        echo
        echo "This is not a valid stk pr subcommand... yet. Want to add it?" >&2
        echo "Open a staff session to extend stk pr with new capabilities." >&2
        echo
        echo "Available stk pr subcommands:" >&2
        echo "  stk pr            Create draft PR (or convert ready → draft)" >&2
        echo "  stk pr draft      Create draft PR or convert ready → draft" >&2
        echo "  stk pr ready      Create ready PR or promote draft → ready" >&2
        echo "  stk pr close      Close PR (optional comment)" >&2
        echo "  stk pr merge      Merge PR" >&2
        echo "  stk pr view       View PR (passthrough to gh pr view)" >&2
        exit 1
        ;;
    esac
    ;;
  -*)
    # Unrecognized flag
    echo "Error: Unknown option: $1" >&2
    echo
    echo "This is not a valid stk command... yet. Want to add it?" >&2
    echo "Open a staff session to extend stk with new capabilities." >&2
    echo
    echo "Available stk commands:" >&2
    echo "  stk <branch>      Create stacked worktree (auto-inits graphite)" >&2
    echo "  stk               Restack downstream branches" >&2
    echo "  stk pull          Sync with main + restack" >&2
    echo "  stk log           Stack status with PR states" >&2
    echo "  stk status        Stack position + working tree" >&2
    echo "  stk pr            Create/convert to draft PR" >&2
    echo "  stk pr draft      Create draft or convert ready to draft" >&2
    echo "  stk pr ready      Create ready or promote draft to ready" >&2
    echo "  stk pr close      Close PR (optional comment)" >&2
    echo "  stk pr merge      Merge PR" >&2
    echo "  stk pr view       View PR (passthrough to gh pr view)" >&2
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
