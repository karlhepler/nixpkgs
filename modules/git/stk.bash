#!/usr/bin/env bash
set -euo pipefail

# stk: Stacked PR workflow using Graphite CLI integrated with workout worktrees
# - No args / stk restack: gt restack
# - `stk work <branch>`: auto-inits graphite, creates branch, creates worktree inline
# - `stk work` (no args): delegates to workout for interactive picker
# - `stk log`: gt log
# - `stk sync`: git sync + gt restack
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
  echo "  stk                          Restack current stack onto parent (gt restack)"
  echo "  stk restack                  Restack current stack (explicit alias)"
  echo "  stk rebase <parent-branch>   Change parent branch: git rebase + gt move"
  echo "  stk work                     Open interactive worktree picker"
  echo "  stk work <branch>            Create graphite-tracked branch + dedicated worktree"
  echo "  stk log                      Show graphite stack log with PR statuses (gt log)"
  echo "  stk status                   Show stack position then git status"
  echo "  stk sync                     Sync trunk into current branch then restack stack"
  echo "  stk pr                       Create draft PR (no PR) or convert ready→draft"
  echo "  stk pr draft                 Same as stk pr"
  echo "  stk pr ready                 Create ready PR (no PR) or promote draft→ready"
  echo "  stk pr close [comment]       Close PR with optional comment"
  echo "  stk pr merge                 Merge PR (squash)"
  echo "  stk pr view [args]           View current branch PR (gh pr view passthrough)"
  echo "  stk -h, --help               Show this help"
  echo
  echo "DESCRIPTION:"
  echo "  Combines Graphite CLI stack management with the workout worktree system."
  echo "  Does NOT require Graphite auth token — all remote PR operations use gh CLI."
  echo
  echo "  WORKTREES:"
  echo "  'stk work <branch>' creates a Graphite-tracked branch stacked on the"
  echo "  current branch, then creates a dedicated worktree at:"
  echo "    ~/worktrees/<org>/<repo>/<branch>"
  echo "  Branch names are used as-is (include karlhepler/ prefix)."
  echo "  'stk work' with no args opens the interactive worktree picker (workout)."
  echo
  echo "  INNER LOOP (per branch):"
  echo "  Make changes → amend commit → stk → repeat"
  echo "  'stk' with no args restacks all downstream branches after amending."
  echo
  echo "  STACKED PR WORKFLOW:"
  echo "  1. stk sync                  Pull trunk changes + restack entire stack"
  echo "  2. stk work <branch>         Create next branch in the stack + worktree"
  echo "  3. <make changes>            Work in the new worktree"
  echo "  4. stk                       Restack after amending"
  echo "  5. stk pr                    Open draft PR for current branch"
  echo "  6. stk pr ready              Mark PR ready when done"
  echo
  echo "  PARENT MANAGEMENT:"
  echo "  'stk rebase <parent>' performs:"
  echo "    1. git rebase <parent>     Put parent in branch git history"
  echo "    2. gt move --onto <parent> Update graphite parent tracking"
  echo "  Required when a branch's graphite parent is wrong or unset."
  echo "  If the branch is untracked by graphite, 'stk' will error with a"
  echo "  message directing you to run 'stk rebase <parent>'."
  echo
  echo "  GRAPHITE INIT:"
  echo "  Auto-initializes graphite if .git/.graphite_repo_config does not exist."
  echo "  Defaults trunk to 'main'."
  echo
  echo "BRANCH NAMING:"
  echo "  All branches must use the 'karlhepler/' prefix."
  echo "  Example: karlhepler/my-feature, karlhepler/pla-728-sdk"
  echo
  echo "DEPENDENCIES:"
  echo "  gt (graphite-cli)  — for local stack tracking and restack"
  echo "  gh (GitHub CLI)    — for PR creation, status, and management"
  echo "  workout            — for interactive worktree picker (stk work)"
  echo "  jq                 — for PR state parsing"
  echo
  echo "EXAMPLES:"
  echo "  # Restack after amending the current branch"
  echo "  stk"
  echo
  echo "  # Create next stacked branch with dedicated worktree"
  echo "  stk work karlhepler/my-feature"
  echo
  echo "  # Fix a branch's parent (e.g., after bad state recovery)"
  echo "  stk rebase karlhepler/pla-728-sdk"
  echo
  echo "  # Pull trunk + restack entire stack"
  echo "  stk sync"
  echo
  echo "  # Show stack structure"
  echo "  stk log"
  echo
  echo "  # Open draft PR for current branch"
  echo "  stk pr"
  echo
  echo "  # Promote to ready for review"
  echo "  stk pr ready"
  echo
  echo "  # Close PR"
  echo "  stk pr close 'Superseded by #456'"
  echo
  echo "  # Squash merge PR"
  echo "  stk pr merge"
  echo
  echo "  # Open PR in browser"
  echo "  stk pr view --web"
}

# Get current PR state as JSON: {state, isDraft}
# Returns empty string and non-zero exit if no PR exists for the current branch.
get_pr_state() {
  gh pr view --json state,isDraft --jq '{state: .state, isDraft: .isDraft}' 2>/dev/null
}

# Get the graphite parent branch for the current branch (local, no auth required).
# Returns the parent branch name, or empty string if not determinable.
get_gt_parent() {
  gt branch info 2>/dev/null | head -1 | awk '{print $1}'
}

# Create a PR using gh, using the graphite parent as the base branch.
# Usage: create_gh_pr [--draft]
create_gh_pr() {
  local extra_flags=()
  if [[ "${1:-}" == "--draft" ]]; then
    extra_flags+=("--draft")
  fi

  local parent_branch
  parent_branch="$(get_gt_parent)"

  if [[ -n "$parent_branch" ]]; then
    gh pr create "${extra_flags[@]}" --fill --base "$parent_branch"
  else
    gh pr create "${extra_flags[@]}" --fill
  fi
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
    create_gh_pr --draft
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
    create_gh_pr
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
# Handles three recoverable failure modes before surfacing errors:
#   1. untracked branch  → gt track -p <parent>, then retry
#   2. not in history    → git rebase <parent> to fix git history, then retry
#   3. both at once      → track first, then rebase, then retry
# Any other failure surfaces the original error verbatim and returns 1.
# Usage: stk_rebase <parent-branch>
stk_rebase() {
  local parent_branch="$1"

  echo "Rebasing onto '$parent_branch'..." >&2

  # Per graphite docs: git rebase must run BEFORE gt track/gt move to ensure
  # the parent is in the branch's git history. This is a no-op if the branch
  # is already based on parent (exits 0 with "up to date").
  git rebase "$parent_branch" || return 1

  # Update the graphite parent. For already-tracked branches gt move --onto
  # updates the parent. For untracked branches (created outside gt workflow),
  # gt move fails so we fall back to gt track -p to register with graphite.
  if ! gt move --onto "$parent_branch" 2>/dev/null; then
    gt track -p "$parent_branch" || return 1
  fi
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
  local branch_info
  branch_info="$(gt branch info 2>&1 || true)"
  if ! echo "$branch_info" | rg -qi 'not tracked'; then
    return 0
  fi

  if [[ -n "$parent" ]]; then
    gt track --parent "$parent" >&2
  else
    echo "Error: branch is not tracked by Graphite. Run 'stk rebase <parent-branch>' to set its parent." >&2
    return 1
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

      # Save current branch before gt create. gt create checks out the new
      # branch in the current directory, which would cause git worktree list
      # to find the branch already checked out here — preventing a new
      # worktree from being created. We switch back immediately after.
      original_branch="$(git rev-parse --abbrev-ref HEAD)"

      # Create the graphite-tracked branch non-interactively
      run_gt create "$branch_name" >&2

      # Switch back to the original branch so the new branch is not checked
      # out in the current worktree. This allows git worktree add to create
      # a new dedicated worktree for it below.
      git checkout "$original_branch" >&2

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
  sync)
    git sync
    run_gt restack
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
    echo "  stk sync                   Sync with main + restack" >&2
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
