#!/usr/bin/env bash
set -euo pipefail

# stk: Stacked PR workflow using Graphite CLI integrated with workout worktrees
# - No args / stk restack: gt restack
# - `stk work <branch>`: auto-inits graphite, creates branch, creates worktree inline
# - `stk work` (no args): delegates to workout for interactive picker
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
  echo "  stk                          Rebase the current stack (gt restack)"
  echo "  stk restack                  Rebase the current stack (explicit alias)"
  echo "  stk rebase <parent-branch>   Change parent branch and restack"
  echo "  stk work                     Open interactive worktree picker"
  echo "  stk work <branch>            Create graphite branch + worktree"
  echo "  stk log                      Show graphite stack log (gt log)"
  echo "  stk pull                     Sync with remote (gt sync)"
  echo "  stk status                   Show stack position then working tree state"
  echo "  stk pr [draft]               Create draft PR or convert ready→draft"
  echo "  stk pr ready                 Create ready PR or promote draft→ready"
  echo "  stk pr close [comment]       Close PR with optional comment"
  echo "  stk pr merge                 Merge PR (squash)"
  echo "  stk pr view [args]           View current branch PR (gh pr view passthrough)"
  echo "  stk -h, --help               Show this help"
  echo
  echo "DESCRIPTION:"
  echo "  Combines Graphite CLI stacked PRs with the workout worktree system."
  echo "  'stk work <branch>' creates a Graphite-tracked branch and opens a worktree."
  echo "  'stk work' with no arguments opens the interactive worktree picker."
  echo
  echo "  Auto-initializes Graphite if the repo has not been initialized"
  echo "  (.git/.graphite_repo_config does not exist). Defaults trunk to main."
  echo
  echo "EXAMPLES:"
  echo "  # Rebase the whole stack after amending a parent branch"
  echo "  stk"
  echo "  stk restack"
  echo
  echo "  # Change this branch's parent and restack onto it"
  echo "  stk rebase main"
  echo "  stk rebase karlhepler/other-feature"
  echo
  echo "  # Open the interactive worktree picker"
  echo "  stk work"
  echo
  echo "  # Create a new stacked branch with worktree"
  echo "  stk work karlhepler/my-feature"
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
    run_gt submit --draft
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
    run_gt submit
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

# Change the current branch's Graphite parent and restack onto it.
# Usage: stk_rebase <parent-branch>
stk_rebase() {
  local parent_branch="$1"

  ensure_tracked "$parent_branch"  # Track current branch under the new parent before moving

  echo "Updating Graphite parent to '$parent_branch'..." >&2
  gt move --onto "$parent_branch"

  echo >&2
  run_gt log
}

# If there are uncommitted changes, present a fzf picker offering:
#   1. Commit first, then stack
#   2. Stack anyway
#   3. Quit
# Returns 0 to proceed with branch creation, 1 to abort.
# If stdin is not a TTY (non-interactive context), exits with error instead of fzf.
guard_uncommitted_changes() {
  local dirty
  dirty="$(git status --porcelain)"
  if [[ -z "$dirty" ]]; then
    return 0
  fi

  # Check if stdin is a TTY (interactive context)
  if [[ ! -t 0 ]]; then
    echo "error: uncommitted changes detected in this worktree. Commit or stash before stacking." >&2
    echo "Uncommitted files:" >&2
    echo "$dirty" >&2
    return 1
  fi

  local choice
  choice="$(printf 'Commit first, then stack\nStack anyway\nQuit' \
    | fzf --prompt="Uncommitted changes detected. Choose: " \
          --height=~10 \
          --no-info \
          --no-sort)"

  case "$choice" in
    "Commit first, then stack")
      local commit_msg
      read -r -p "Commit message [WIP]: " commit_msg
      commit_msg="${commit_msg:-WIP}"
      git add -A
      git commit -m "$commit_msg"
      return 0
      ;;
    "Stack anyway")
      return 0
      ;;
    "Quit"|"")
      echo "Aborted." >&2
      return 1
      ;;
  esac
}

# Ensure the current branch is tracked by Graphite before running gt operations.
# If the branch is already tracked, this is a no-op.
# Accepts an optional parent argument: if provided, passes --parent <arg> to gt track.
#
# Usage: ensure_tracked [parent-branch]
ensure_tracked() {
  local parent="${1:-}"

  # Check whether the branch is already tracked by graphite
  if ! gt branch info 2>&1 | rg -qi 'not tracked'; then
    return 0
  fi

  if [[ -n "$parent" ]]; then
    gt track --parent "$parent" >&2
  else
    gt track >&2
  fi
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

# Run a gt command with automatic branch tracking on untracked-branch errors.
# If the command fails with an "untracked" error, auto-runs:
#   gt track --parent <trunk>
# using the same trunk detection already in this script, then retries once.
# All other failures propagate normally.
#
# Usage: run_gt <gt-subcommand> [args...]
run_gt() {
  local stderr_file
  stderr_file="$(mktemp)"

  if gt "$@" 2>"$stderr_file"; then
    rm -f "$stderr_file"
    return 0
  fi
  local gt_exit=$?

  if rg -qi 'not tracked|untracked' "$stderr_file"; then
    cat "$stderr_file" >&2
    rm -f "$stderr_file"

    local trunk
    trunk="$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')"
    echo "Branch not tracked by Graphite. Running: gt track --parent $trunk" >&2
    gt track --parent "$trunk"
    gt "$@"
    return
  fi

  cat "$stderr_file" >&2
  rm -f "$stderr_file"
  return $gt_exit
}

# No args: restack (auto-track if needed, then restack)
if [[ $# -eq 0 ]]; then
  ensure_tracked
  run_gt restack
  exit $?
fi

case "$1" in
  -h|--help)
    show_help
    exit 0
    ;;
  restack)
    run_gt restack
    ;;
  rebase)
    if [[ $# -lt 2 ]]; then
      echo "Error: 'stk rebase' requires a parent branch name." >&2
      echo "Usage: stk rebase <parent-branch>" >&2
      exit 1
    fi
    stk_rebase "$2"
    ;;
  work)
    shift
    if [[ $# -eq 0 ]]; then
      # No branch arg: delegate to workout for the interactive picker.
      # workout outputs a cd command that the shell wrapper in zsh.nix evals.
      workout
    else
      branch_name="$1"

      # Guard: if there are uncommitted changes, ask the user what to do
      guard_uncommitted_changes || exit 0

      # Ensure graphite is initialized for this repo
      ensure_gt_init

      # Create the graphite-tracked branch non-interactively
      run_gt create "$branch_name" >&2

      # Inline worktree creation (mirrors workout <branch> logic).
      # Get remote URL and extract org/repo
      remote_url="$(git remote get-url origin)"

      # Extract org/repo from URL (handles both SSH and HTTPS)
      # git@github.com:org/repo.git -> org/repo
      # https://github.com/org/repo.git -> org/repo
      org_repo="$(echo "$remote_url" | sed -E 's#.*[:/]([^/]+/[^/]+)\.git$#\1#')"

      if [[ -z "$org_repo" ]]; then
        echo "Error: Could not extract org/repo from remote URL: $remote_url" >&2
        exit 1
      fi

      # Security: Reject path traversal attempts in org/repo
      if [[ "$org_repo" == *".."* ]]; then
        echo "Error: Invalid org/repo path detected (contains '..'): $org_repo" >&2
        exit 1
      fi

      worktree_root="${WORKTREE_ROOT:-$HOME/worktrees}"
      worktree_path="$worktree_root/$org_repo/$branch_name"

      # Check if branch is already checked out in any worktree
      existing_worktree=$(git worktree list --porcelain | awk -v branch="refs/heads/$branch_name" '
        /^worktree / { path = substr($0, 10) }
        /^branch / && $0 ~ branch { print path; exit }
      ')

      if [[ -n "$existing_worktree" ]]; then
        # Branch is checked out somewhere
        if [[ "$existing_worktree" =~ ^$worktree_root/ ]]; then
          # Already in a managed worktree — just navigate there
          echo "cd '$existing_worktree'"
        else
          # Branch is in primary repo — check if trunk (trunk stays in primary repo)
          git remote set-head origin -a >/dev/null 2>&1 || true
          trunk_branch="$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')"

          if [[ "$branch_name" == "$trunk_branch" ]]; then
            echo "cd '$existing_worktree'"
          else
            # Non-trunk branch in primary repo — move it to a worktree
            echo "Branch '$branch_name' is checked out in primary repo. Moving to worktree..." >&2

            worktree_path="$worktree_root/$org_repo/$branch_name"
            mkdir -p "$(dirname "$worktree_path")"

            (
              cd "$existing_worktree" || exit 1

              has_changes=false
              if [[ -n "$(git status --porcelain)" ]]; then
                echo "Stashing uncommitted changes..." >&2
                git stash push -u -m "stk work: moving to worktree" >&2
                has_changes=true
              fi

              echo "Switching primary repo to trunk..." >&2
              git trunk --no-pull >&2

              echo "Creating worktree at $worktree_path..." >&2
              git worktree add "$worktree_path" "$branch_name" >&2

              if [[ "$has_changes" == "true" ]]; then
                echo "Restoring uncommitted changes in worktree..." >&2
                (cd "$worktree_path" && git stash pop) >&2
              fi
            ) || exit 1

            echo "cd '$worktree_path'"

            # Run post-switch hook if present
            git_dir="$(git rev-parse --git-dir 2>/dev/null)"
            if [[ -f "$git_dir" ]]; then
              real_git_dir="$(grep '^gitdir:' "$git_dir" | cut -d' ' -f2)"
              git_dir="${real_git_dir%/worktrees/*}"
            fi
            hook_path="$git_dir/workout-hooks/post-switch"
            if [[ -f "$hook_path" && -x "$hook_path" ]]; then
              hook_path="$(cd "$(dirname "$hook_path")" && pwd)/$(basename "$hook_path")"
              echo "'$hook_path'"
            fi
          fi
        fi
      elif [[ -d "$worktree_path" ]]; then
        # Worktree directory already exists at expected path — just navigate
        echo "cd '$worktree_path'"
      else
        # New worktree: graphite already created the branch via run_gt create above.
        # The branch now exists, so use git worktree add without -b.
        mkdir -p "$(dirname "$worktree_path")"
        git worktree add "$worktree_path" "$branch_name" >&2

        echo "cd '$worktree_path'"

        # Run post-switch hook if present
        git_dir="$(git rev-parse --git-dir 2>/dev/null)"
        if [[ -f "$git_dir" ]]; then
          real_git_dir="$(grep '^gitdir:' "$git_dir" | cut -d' ' -f2)"
          git_dir="${real_git_dir%/worktrees/*}"
        fi
        hook_path="$git_dir/workout-hooks/post-switch"
        if [[ -f "$hook_path" && -x "$hook_path" ]]; then
          hook_path="$(cd "$(dirname "$hook_path")" && pwd)/$(basename "$hook_path")"
          echo "'$hook_path'"
        fi
      fi
    fi
    ;;
  log)
    run_gt log
    ;;
  status)
    run_gt log
    git status
    ;;
  pull)
    run_gt sync
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
  *)
    echo "Error: Unknown subcommand: $1" >&2
    echo
    echo "This is not a valid stk subcommand... yet. Want to add it?" >&2
    echo "Open a staff session to extend stk with new capabilities." >&2
    echo
    echo "Available stk subcommands:" >&2
    echo "  stk                        Restack downstream branches" >&2
    echo "  stk restack                Restack downstream branches (explicit alias)" >&2
    echo "  stk rebase <parent-branch> Change parent branch and restack" >&2
    echo "  stk work                   Open interactive worktree picker" >&2
    echo "  stk work <branch>          Create stacked worktree (auto-inits graphite)" >&2
    echo "  stk pull                   Sync with main + restack" >&2
    echo "  stk log                    Stack status with PR states" >&2
    echo "  stk status                 Stack position + working tree" >&2
    echo "  stk pr                     Create/convert to draft PR" >&2
    echo "  stk pr draft               Create draft or convert ready to draft" >&2
    echo "  stk pr ready               Create ready or promote draft to ready" >&2
    echo "  stk pr close               Close PR (optional comment)" >&2
    echo "  stk pr merge               Merge PR" >&2
    echo "  stk pr view                View PR (passthrough to gh pr view)" >&2
    exit 1
    ;;
esac
