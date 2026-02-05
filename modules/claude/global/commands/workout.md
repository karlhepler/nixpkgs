---
description: Create git worktrees with TMUX windows and Claude Code instances for parallel development. Use when user wants to test features in isolation, work on multiple branches simultaneously, or needs dedicated Claude sessions per worktree.
---

# Workout - Batch Worktree Creation with TMUX

**Purpose:** Automate creation of multiple git worktrees with dedicated TMUX windows and Claude Code instances for parallel development workflows.

## When to Use

Activate this skill when the user asks to:
- Create multiple worktrees at once
- Set up parallel development environments
- Test multiple features in isolation
- Work on multiple branches simultaneously
- Set up worktrees with Claude instances

**Example user requests:**
- "Create worktrees for feature-x, feature-y, and feature-z"
- "Set up parallel environments for branches A, B, and C"
- "I need to test these three features in isolation"
- "Create worktrees with Claude for bug-123, bug-456"

## How Workout Works

The `workout` command creates git worktrees organized in `~/worktrees/org/repo/branch/` structure. When given multiple branch names:

1. **Auto-prefixes branches** with `karlhepler/` (strips first if already present)
2. **Creates worktrees** for each branch (creates branch if doesn't exist)
3. **Creates TMUX windows** in detached mode (no focus switch)
4. **Launches `staff`** (Claude Code) in each window
5. **Reports summary** of created/failed worktrees

**Key features:**
- Idempotent: Safe to run multiple times (reuses existing worktrees)
- Error resilient: Skips failures, continues with others
- Detached mode: Windows created in background (no focus switching)
- TMUX window naming: Uses branch suffix only (no `karlhepler/` prefix)

## Branch Name Inference

When the user describes features or tasks without explicit branch names:

**1. Listen for task descriptions:**
- "I need to work on authentication, payment, and notifications"
- "Let's test the API refactor, UI updates, and database migration"
- "Set up environments for bug fixes 123, 456, and 789"

**2. Infer logical branch names:**
- Task-based: `authentication`, `payment`, `notifications`
- Feature-based: `api-refactor`, `ui-updates`, `db-migration`
- Bug-based: `bug-123`, `bug-456`, `bug-789`

**3. Use kebab-case conventions:**
- Lowercase with hyphens
- Descriptive and concise
- Follows project conventions (check existing branches if unsure)

## Confirmation Workflow

**CRITICAL: Always confirm branch names before creating worktrees.**

1. **Present the inferred branch names** to the user
2. **Show what will be created** (full branch names with `karlhepler/` prefix)
3. **Wait for explicit approval** before running the command

**Example confirmation:**

```
I'll create worktrees for these branches:
- karlhepler/authentication
- karlhepler/payment
- karlhepler/notifications

Each will have:
- Dedicated worktree in ~/worktrees/org/repo/branch/
- TMUX window named by branch suffix (authentication, payment, notifications)
- Claude Code instance (staff) running in each window

Ready to proceed? (yes/no)
```

**Only proceed if user confirms with "yes" or equivalent affirmative response.**

## Invocation

workout-claude now supports **two modes**:

### Mode 1: Simple Branch Names (No Context)

Use when Claude instances don't need specific prompts:

```bash
workout-claude feature-1 feature-2 feature-3
```

**Example:**
```bash
# User confirms: "yes, create those worktrees"
workout-claude authentication payment notifications
```

### Mode 2: JSON Input with Prompts (Context Injection)

Use when each Claude instance needs specific context (Linear tickets, task details, etc.):

```bash
echo '[{"worktree": "branch", "prompt": "context"}]' | workout-claude
```

**Example:**
```bash
echo '[
  {"worktree": "fix-auth", "prompt": "Look up Linear AUTH-123 and fix OAuth flow"},
  {"worktree": "bug-456", "prompt": "Fix null pointer in user profile - Linear BUG-456"}
]' | workout-claude
```

**JSON format requirements:**
- Array of objects
- Each object MUST have `worktree` (branch name) and `prompt` (context string)
- `prompt` can be empty string (just launches staff interactively)
- Branch names auto-prefixed with `karlhepler/` (strips first if present)

**The command will:**
- Auto-prefix each branch with `karlhepler/`
- Create worktrees if they don't exist
- Create TMUX windows in detached mode
- Launch staff with `-p "prompt"` in each window (passes context to Claude)
- Report summary of created/failed worktrees

**When to use JSON mode:**
- Parent Claude has context (Linear tickets, user requests) to pass to child Claudes
- Each worktree needs different context/instructions
- You want to eliminate repeating context across Claude sessions
- You're coordinating parallel work with specific per-task details

## What the User Gets

After successful execution:

1. **Worktrees created** at:
   - `~/worktrees/org/repo/karlhepler/authentication/`
   - `~/worktrees/org/repo/karlhepler/payment/`
   - `~/worktrees/org/repo/karlhepler/notifications/`

2. **TMUX windows** (detached, running in background):
   - Window: `authentication` (with staff running)
   - Window: `payment` (with staff running)
   - Window: `notifications` (with staff running)

3. **How to access:**
   - `tmux list-windows` - See all windows
   - `tmux select-window -t authentication` - Switch to window
   - Or use TMUX prefix + window number

## Error Handling

The workout command is error-resilient:

- **Existing worktrees:** Reuses them (idempotent)
- **Invalid branch names:** Skips and continues with others
- **TMUX failures:** Reports warning but continues
- **Missing staff command:** Warning only, windows still created

**Summary report shows:**
- ✓ Successfully created worktrees
- ✗ Failed worktrees (with reasons)

## Example Usage

### Example 1: Simple Mode (No Context)

**User request:**
"I need to work on three features: user authentication, payment processing, and email notifications. Set up worktrees with Claude for each."

**Your response:**

"I'll create worktrees for these branches:
- karlhepler/user-authentication
- karlhepler/payment-processing
- karlhepler/email-notifications

Each will have a dedicated worktree, TMUX window, and Claude Code instance.

Ready to proceed?"

**After user confirms "yes":**

```bash
workout-claude user-authentication payment-processing email-notifications
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

### Example 2: JSON Mode with Context (Prompt Injection)

**User request:**
"I have three Linear tickets to work on. Create worktrees and pass the ticket context to each Claude instance:
- AUTH-123: Fix OAuth flow
- BUG-456: Null pointer in user profile
- REF-789: Refactor API error handling"

**Your response:**

"I'll create worktrees with custom prompts for each ticket:
- karlhepler/fix-auth-123 - OAuth flow fix (Linear AUTH-123)
- karlhepler/bug-456-null-check - Null pointer fix (Linear BUG-456)
- karlhepler/refactor-api-789 - API error handling refactor (Linear REF-789)

Each Claude instance will receive the ticket context automatically.

Ready to proceed?"

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
]' | workout-claude
```

**Then explain:**

"Created 3 worktrees with TMUX windows and context-aware Claude instances:
- `fix-auth-123` - Claude knows to look up AUTH-123 and fix OAuth
- `bug-456-null-check` - Claude knows to fix null pointer per BUG-456
- `refactor-api-789` - Claude knows to refactor API errors per REF-789

Each Claude instance has the specific context and can start work immediately without you repeating the requirements.

Switch to any window with:
- `tmux select-window -t fix-auth-123`
- `tmux select-window -t bug-456-null-check`
- `tmux select-window -t refactor-api-789`

Or use `tmux list-windows` to see all windows."

## Single Worktree Mode

For single worktree creation (no TMUX batch mode):

```bash
# Current branch
workout .

# Specific branch
workout feature-name

# Interactive browser
workout  # (no args)

# Toggle to previous
workout -
```

**Use single mode when:**
- User asks for one worktree only
- User wants to navigate immediately (not parallel work)
- User mentions "switch to" or "navigate to"

## Branch Naming Conventions

**CRITICAL: ALL branches MUST use `karlhepler/` prefix.**

The workout command handles this automatically:
- Input: `feature-x` → Creates: `karlhepler/feature-x`
- Input: `karlhepler/feature-x` → Creates: `karlhepler/feature-x` (no double-prefix)

**When inferring names:**
- Use kebab-case: `user-auth` not `user_auth` or `UserAuth`
- Be descriptive: `fix-login-bug` not `fix-bug`
- Keep it short: `api-refactor` not `refactor-entire-api-layer-for-performance`

## Success Criteria

- [ ] User request interpreted correctly (single vs batch mode)
- [ ] Branch names inferred logically from task descriptions
- [ ] User confirmed branch names before creation
- [ ] Workout command invoked with all branch names
- [ ] Summary provided showing created TMUX windows
- [ ] Instructions given on how to access windows

## Notes

- **Detached mode** means windows are created in background (no focus switch)
- **Window names** use branch suffix only (no `karlhepler/` prefix)
- **Staff command** is the Claude Code interactive session
- **Worktree structure** is `~/worktrees/org/repo/branch/`
- **Idempotent** means safe to run multiple times with same branches
- **Error resilient** means skips failures and continues with others
