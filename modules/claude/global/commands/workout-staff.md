---
name: workout-staff
description: Create git worktrees with TMUX windows and staff (Claude Code) instances for parallel development. Use when user wants to test features in isolation, work on multiple branches simultaneously, or needs dedicated staff Claude sessions per worktree.
version: 1.0
---

# Workout Staff - Batch Worktree Creation with TMUX and Staff

**Purpose:** Automate creation of multiple git worktrees with dedicated TMUX windows and staff (Claude Code) instances for parallel development workflows.

**Shared workflow:** All common procedures (prerequisites, branch inference, confirmation, JSON format, cross-repo support, error handling, single-worktree mode, branch naming, success criteria) are defined in `workout-shared`. Follow those patterns using `staff` as the subcommand.

## When to Use

Activate this skill when the user asks to:
- Create multiple worktrees at once
- Set up parallel development environments with Claude Code instances
- Test multiple features in isolation
- Work on multiple branches simultaneously with staff Claude agents
- Set up worktrees with Claude instances

**Example user requests:**
- "Create worktrees for feature-x, feature-y, and feature-z"
- "Set up parallel environments for branches A, B, and C"
- "I need to test these three features in isolation"
- "Create worktrees with Claude for bug-123, bug-456"

## How This Skill Works

This skill uses `workout-claude staff`, which processes JSON input to create multiple worktrees with staff (Claude Code) instances. Under the hood, `workout-claude` calls the standalone `workout` command for each worktree, then adds TMUX automation:

1. **Auto-prefixes branches** with `karlhepler/` (strips first if already present)
2. **Creates worktrees** for each branch using `workout` command (creates branch if doesn't exist)
3. **Creates TMUX windows** in detached mode (no focus switch)
4. **Launches `staff`** (Claude Code) in each window with custom prompts
5. **Reports summary** of created/failed worktrees

## Invocation

```bash
echo '[{"worktree": "branch", "prompt": "context"}]' | workout-claude staff
```

**When to use workout-claude staff:**
- Parent Claude has context (Linear tickets, user requests) to pass to child Claudes
- Each worktree needs different context/instructions
- You want to eliminate repeating context across Claude sessions
- You're coordinating parallel work with specific per-task details

## Confirmation Message Template

```
I'll create worktrees for these branches:
- karlhepler/<branch1>
- karlhepler/<branch2>

Each will have:
- Dedicated worktree in ~/worktrees/org/repo/branch/
- TMUX window named by branch suffix
- Claude Code instance (staff) running in each window

Ready to proceed? (yes/no)
```

## Example Usage

### Example 1: Multiple Worktrees Without Specific Context

**User request:**
"I need to work on three features: user authentication, payment processing, and email notifications. Set up worktrees with Claude for each."

**After user confirms "yes":**

```bash
echo '[
  {"worktree": "user-authentication", "prompt": ""},
  {"worktree": "payment-processing", "prompt": ""},
  {"worktree": "email-notifications", "prompt": ""}
]' | workout-claude staff
```

**Then explain:**

"Created 3 worktrees with TMUX windows and Claude instances:
- `user-authentication` - Ready to work on authentication feature
- `payment-processing` - Ready to work on payment feature
- `email-notifications` - Ready to work on notification feature

Switch to any window with:
- `tmux select-window -t user-authentication`
- `tmux select-window -t payment-processing`
- `tmux select-window -t email-notifications`

Or use `tmux list-windows` to see all windows."

### Example 2: Multiple Worktrees With Specific Context (Prompt Injection)

**User request:**
"I have three Linear tickets to work on. Create worktrees and pass the ticket context to each Claude instance:
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
]' | workout-claude staff
```

**Then explain:**

"Created 3 worktrees with TMUX windows and context-aware Claude instances:
- `fix-auth-123` - Claude knows to look up AUTH-123 and fix OAuth
- `bug-456-null-check` - Claude knows to fix null pointer per BUG-456
- `refactor-api-789` - Claude knows to refactor API errors per REF-789

Each Claude instance has the specific context and can start work immediately.

Switch to any window with `tmux select-window -t <name>` or use `tmux list-windows`."

## Notes

- **staff command** is the Claude Code interactive session
- See `workout-shared` for all common workflow patterns, error handling, and branch naming rules
