---
name: stk-burns
description: Create Graphite-tracked stacked git worktrees with TMUX windows and burns (Ralph Orchestrator) instances. Use when user wants to work on multiple stacked branches simultaneously with dedicated burns sessions, each branch parented in the graphite stack.
version: 1.0
---

# Stk Burns - Batch Stacked Worktree Creation with TMUX and Burns

**Purpose:** Automate creation of multiple Graphite-tracked stacked worktrees with dedicated TMUX windows and burns (Ralph Orchestrator) instances for parallel stacked PR development.

**Shared workflow:** All common procedures (prerequisites, branch inference, confirmation, JSON format, cross-repo support, error handling, single-worktree mode, branch naming, success criteria) are defined in `workout-shared`. Follow those patterns using `stk-claude` as the command and `burns` as the subcommand.

## Key Difference from workout-burns

Unlike `/workout-burns` which creates plain git branches, this skill uses `stk-claude burns` which calls `stk work` for each branch. Every worktree gets a **Graphite-tracked branch stacked on the current branch** of the target repo. Use this when you want stacked PRs, not just parallel branches.

## When to Use

Activate this skill when the user asks to:
- Create multiple stacked worktrees with burns (Ralph Orchestrator) instances
- Set up parallel stacked PR environments with Ralph
- Work on multiple stacked branches simultaneously with autonomous Ralph agents

**Example user requests:**
- "Create stacked worktrees for feature-x, feature-y, and feature-z with burns"
- "Set up parallel stacked environments with Ralph for branches A, B, and C"
- "stk-burns these three features"

## How This Skill Works

Uses `stk-claude burns`, which calls `stk work <branch>` for each entry:

1. **Auto-prefixes branches** with `karlhepler/` (strips first if already present)
2. **Creates Graphite-tracked branches** stacked on the current branch via `stk work`
3. **Creates worktrees** at `~/worktrees/<org>/<repo>/<branch>`
4. **Creates TMUX windows** in detached mode
5. **Launches `burns`** (Ralph Orchestrator) in each window with custom prompts
6. **Reports summary** of created/failed worktrees

## Invocation

```bash
echo '[{"worktree": "branch", "prompt": "context"}]' | stk-claude burns
```

## Prerequisites

Check that `Bash(stk-claude *)`, `Bash(stk *)`, and `Bash(tmux *)` are in the project's `permissions.allow` before proceeding. See `workout-shared` for the full prerequisite check procedure.

## Confirmation Message Template

```
I'll create stacked worktrees for these branches (stacked on current branch):
- karlhepler/<branch1>
- karlhepler/<branch2>

Each will have:
- Graphite-tracked branch stacked on current branch
- Dedicated worktree in ~/worktrees/org/repo/branch/
- TMUX window named by branch suffix
- Burns (Ralph Orchestrator) instance running in each window

Ready to proceed? (yes/no)
```

## Notes

- **stk-claude burns** vs **workout-claude burns**: Use stk when you want stacked PRs. Use workout for independent parallel branches.
- See `workout-shared` for all common workflow patterns, error handling, and branch naming rules.
