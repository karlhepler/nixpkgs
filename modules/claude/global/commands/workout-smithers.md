---
name: workout-smithers
description: Launch smithers (autonomous PR watcher) across multiple PRs in parallel TMUX windows, each with a dedicated git worktree on the correct branch. Use when the user wants to monitor and auto-fix CI failures across several PRs simultaneously.
version: 1.0
---

# Workout Smithers - Parallel PR Watching with Dedicated Worktrees

**Purpose:** Automate launching `smithers` (autonomous PR watcher) across multiple PRs simultaneously. Each PR gets its own git worktree checked out to the correct branch, and its own TMUX window running `smithers <pr>`.

## When to Use

Activate this skill when the user asks to:
- Watch multiple PRs with smithers at once
- Set up parallel smithers sessions for several open PRs
- Monitor CI failures across multiple PRs simultaneously
- Auto-fix CI issues on several branches in parallel
- Launch smithers for a batch of PRs

**Example user requests:**
- "Watch PRs 123, 456, and 789 with smithers"
- "Set up smithers for all my open PRs in ops"
- "Launch smithers in parallel for PR 101 in ops and PR 202 in api"
- "I need smithers running on three PRs at once"

## Requirements

**GITHUB_REPOS_ROOT must be set.** This environment variable tells workout-smithers where repos live locally.

Set it in `overconfig.nix`:
```nix
home.sessionVariables.GITHUB_REPOS_ROOT = "/Users/karlhepler/github.com";
```

Then run `hms` to apply. The value should be the root directory that contains your org folders (e.g. `mazedesignhq/`).

If not set, `workout-smithers` will fail immediately with a clear error message explaining exactly what to do.

## Hard Prerequisites

**Before anything else: verify required permissions are in the project's `permissions.allow`.**

Due to a known Claude Code bug ([GitHub #5140](https://github.com/anthropics/claude-code/issues/5140)), global `~/.claude/settings.json` permissions are **not** inherited by projects with their own `permissions.allow` — project settings replace globals entirely. To verify: read `.claude/settings.json` or `.claude/settings.local.json` in the project root and confirm each required permission appears in the `permissions.allow` array.

**Required:**
- `Bash(workout *)` — needed to create git worktrees
- `Bash(tmux *)` — needed to create TMUX windows for each PR

**If any are missing:** Stop immediately. Do not start work. Surface to the user with the specific permissions that are missing.

## JSON Input Format

```json
[
  {"pr": 123, "repo": "mazedesignhq/ops"},
  {"pr": 456, "repo": "mazedesignhq/api", "name": "api-fix"}
]
```

**Required fields:**
- `pr` — PR number (integer, e.g. `123`)
- `repo` — GitHub `org/repo` identifier (e.g. `"mazedesignhq/ops"`)

**Optional fields:**
- `name` — TMUX window name. Defaults to `<repo-name>-<pr>` (e.g. `"ops-123"`)

## How This Skill Works

`workout-smithers` reads JSON from stdin and for each entry:

1. Resolves repo path: `$GITHUB_REPOS_ROOT/<org/repo>`
2. Clones repo if it does not exist locally (via `git clone git@github.com:...`)
3. Fetches PR head branch: `gh pr view <pr> -R <org/repo> --json headRefName -q .headRefName`
4. Creates worktree: runs `workout <branch>` with CWD set to the repo path
5. Opens TMUX window in detached mode at the worktree directory
6. Sends `smithers <pr>` to the window

All windows are created in detached mode (no focus switch). Failed entries are skipped and reported in the summary.

## Confirmation Message Template

Before invoking the command, show a confirmation:

```
I'll launch smithers for these PRs:

  PR #123  mazedesignhq/ops   -> window: ops-123
  PR #456  mazedesignhq/api   -> window: api-fix
  PR #789  mazedesignhq/web   -> window: web-789

Each will have:
  - Repo cloned to $GITHUB_REPOS_ROOT/<org/repo> if not already present
  - Dedicated worktree on the PR's head branch
  - TMUX window in detached mode
  - smithers <pr> running in each window

Ready to proceed? (yes/no)
```

## Invocation

```bash
echo '[{"pr": 123, "repo": "mazedesignhq/ops"}]' | workout-smithers
```

Or from a heredoc:

```bash
cat << 'EOF' | workout-smithers
[
  {"pr": 101, "repo": "mazedesignhq/ops", "name": "ops-deploy"},
  {"pr": 202, "repo": "mazedesignhq/api"},
  {"pr": 303, "repo": "mazedesignhq/web"}
]
EOF
```

## Example Usage

### Example 1: Single PR

**User request:**
"Watch PR 123 in ops with smithers."

**After user confirms "yes":**

```bash
echo '[{"pr": 123, "repo": "mazedesignhq/ops"}]' | workout-smithers
```

**Then explain:**

"Launched smithers for PR #123 in `mazedesignhq/ops`:
- Worktree created on the PR branch
- TMUX window `ops-123` opened in detached mode
- `smithers 123` running in the window

Switch to it with: `tmux select-window -t ops-123`"

### Example 2: Multiple PRs Across Repos

**User request:**
"I have three PRs to watch: 101 in ops, 202 in api, and 303 in web."

**After user confirms "yes":**

```bash
cat << 'EOF' | workout-smithers
[
  {"pr": 101, "repo": "mazedesignhq/ops"},
  {"pr": 202, "repo": "mazedesignhq/api"},
  {"pr": 303, "repo": "mazedesignhq/web"}
]
EOF
```

**Then explain:**

"Launched smithers for 3 PRs in parallel:
- `ops-101` — watching PR #101 in ops
- `api-202` — watching PR #202 in api
- `web-303` — watching PR #303 in web

Switch to any window with `tmux select-window -t <name>` or use `tmux list-windows`."

## Notes

- **Worktrees** are created under `~/worktrees/<org>/<repo>/karlhepler/<branch-suffix>/`
- **TMUX windows** are always created in detached mode (no focus switch)
- **Window naming** defaults to `<repo-name>-<pr>` (e.g. `ops-123`); override with the `name` field
- **Repo cloning** happens automatically if `$GITHUB_REPOS_ROOT/<org/repo>` does not exist
- **Error resilience**: failed entries are skipped and reported; other entries continue processing
- **smithers** is the autonomous PR watcher that polls CI, invokes Ralph to fix failures, and auto-merges on green
