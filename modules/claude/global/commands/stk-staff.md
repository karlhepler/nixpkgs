---
name: stk-staff
description: Create Graphite-tracked stacked git worktrees with TMUX windows and staff (Claude Code) instances. Use when user wants to work on multiple stacked branches simultaneously with dedicated Claude sessions, each branch parented in the graphite stack.
version: 1.0
---

# Stk Staff - Batch Stacked Worktree Creation with TMUX and Staff

**Purpose:** Automate creation of multiple Graphite-tracked stacked worktrees with dedicated TMUX windows and staff (Claude Code) instances for parallel stacked PR development.

**Shared workflow:** All common procedures (prerequisites, branch inference, confirmation, JSON format, cross-repo support, error handling, single-worktree mode, branch naming, success criteria) are defined in `workout-shared`. Follow those patterns using `stk-claude` as the command and `staff` as the subcommand.

> **Note:** Wherever `workout-claude` appears in `workout-shared` examples, substitute `stk-claude`.

## Key Difference from workout-staff

Unlike `/workout-staff` which creates plain git branches, this skill uses `stk-claude staff` which calls `stk work` for each branch. Every worktree gets a **Graphite-tracked branch stacked on the current branch** of the target repo. Use this when you want stacked PRs, not just parallel branches.

## When to Use

Activate this skill when the user asks to:
- Create multiple stacked worktrees with Claude Code instances
- Set up parallel stacked PR environments
- Work on multiple branches simultaneously in a graphite stack with staff Claude agents

**Example user requests:**
- "Create stacked worktrees for feature-x, feature-y, and feature-z with staff"
- "Set up parallel stacked environments with Claude for branches A, B, and C"
- "stk-staff these three features"

## How This Skill Works

Uses `stk-claude staff`, which calls `stk work <branch>` for each entry:

1. **Auto-prefixes branches** with `karlhepler/` (strips first if already present)
2. **Creates Graphite-tracked branches** stacked on the current branch via `stk work`
3. **Creates worktrees** at `~/worktrees/<org>/<repo>/<branch>`
4. **Creates TMUX windows** in detached mode
5. **Launches `staff`** (Claude Code) in each window with custom prompts
6. **Reports summary** of created/failed worktrees

## Invocation

```bash
echo '[{"worktree": "branch", "prompt": "context"}]' | stk-claude staff
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
- Claude Code instance (staff) running in each window

Ready to proceed? (yes/no)
```

## Example Usage

### Example 1: Multiple Stacked Worktrees Without Specific Context

**User request:**
"I need to work on three features: user authentication, payment processing, and email notifications. Set up stacked worktrees with Claude for each."

**After user confirms "yes":**

```bash
echo '[
  {"worktree": "user-authentication", "prompt": ""},
  {"worktree": "payment-processing", "prompt": ""},
  {"worktree": "email-notifications", "prompt": ""}
]' | stk-claude staff
```

**Then explain:**

"Created 3 stacked worktrees with TMUX windows and Claude instances:
- `user-authentication` - Graphite-tracked branch, ready to work
- `payment-processing` - Graphite-tracked branch, ready to work
- `email-notifications` - Graphite-tracked branch, ready to work

Switch to any window with:
- `tmux select-window -t user-authentication`
- `tmux select-window -t payment-processing`
- `tmux select-window -t email-notifications`

Or use `tmux list-windows` to see all windows."

### Example 2: Multiple Stacked Worktrees With Specific Context (Prompt Injection)

**User request:**
"I have three Linear tickets to work on. Create stacked worktrees and pass the ticket context to each Claude instance:
- AUTH-123: Fix OAuth flow
- BUG-456: Null pointer in user profile
- REF-789: Refactor API error handling"

**After user confirms "yes":**

```bash
echo '[
  {
    "worktree": "fix-auth-123",
    "prompt": "Look up Linear ticket AUTH-123 and implement the OAuth flow fix. Check existing authentication patterns in the codebase first."
  },
  {
    "worktree": "bug-456-null-check",
    "prompt": "Fix null pointer exception in user profile handler. See Linear BUG-456 for details. Add defensive null checks and update tests."
  },
  {
    "worktree": "refactor-api-789",
    "prompt": "Refactor the API module to use consistent error handling patterns. Review tech debt ticket REF-789. Focus on maintainability."
  }
]' | stk-claude staff
```

**Then explain:**

"Created 3 stacked worktrees with TMUX windows and context-aware Claude instances:
- `fix-auth-123` - Claude knows to look up AUTH-123 and fix OAuth
- `bug-456-null-check` - Claude knows to fix null pointer per BUG-456
- `refactor-api-789` - Claude knows to refactor API errors per REF-789

Each Claude instance has the specific context and can start work immediately.

Switch to any window with `tmux select-window -t <name>` or use `tmux list-windows`."

## Notes

- **stk-claude staff** vs **workout-claude staff**: Use stk when you want stacked PRs. Use workout for independent parallel branches.
- See `workout-shared` for all common workflow patterns, error handling, and branch naming rules.
