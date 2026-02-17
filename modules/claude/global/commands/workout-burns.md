---
name: workout-burns
description: Create git worktrees with TMUX windows and burns (Ralph Orchestrator) instances for parallel development. Use when user wants to test features in isolation, work on multiple branches simultaneously, or needs dedicated burns Ralph sessions per worktree.
version: 1.0
keep-coding-instructions: true
---

# Workout Burns - Batch Worktree Creation with TMUX and Burns

**Purpose:** Automate creation of multiple git worktrees with dedicated TMUX windows and burns (Ralph Orchestrator) instances for parallel development workflows.

## When to Use

Activate this skill when the user asks to:
- Create multiple worktrees at once
- Set up parallel development environments with burns
- Test multiple features in isolation with Ralph Orchestrator
- Work on multiple branches simultaneously with autonomous agents
- Set up worktrees with burns instances

**Example user requests:**
- "Create worktrees for feature-x, feature-y, and feature-z with burns"
- "Set up parallel environments with Ralph Orchestrator for branches A, B, and C"
- "I need to test these three features in isolation with burns"
- "Create worktrees with burns for bug-123, bug-456"

## How This Skill Works

This skill uses `workout-claude burns`, which processes JSON input to create multiple worktrees with burns (Ralph Orchestrator) instances. Under the hood, `workout-claude` calls the standalone `workout` command for each worktree, then adds TMUX automation:

1. **Auto-prefixes branches** with `karlhepler/` (strips first if already present)
2. **Creates worktrees** for each branch using `workout` command (creates branch if doesn't exist)
3. **Creates TMUX windows** in detached mode (no focus switch)
4. **Launches `burns`** (Ralph Orchestrator) in each window with custom prompts
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
- Burns (Ralph Orchestrator) instance running in each window

Ready to proceed? (yes/no)
```

**Only proceed if user confirms with "yes" or equivalent affirmative response.**

## Invocation

**CRITICAL: workout-claude ONLY accepts JSON input via stdin.**

Use `workout-claude burns` to create worktrees with burns (Ralph Orchestrator) instances.

### JSON Input Format (Required)

```bash
echo '[{"worktree": "branch", "prompt": "context"}]' | workout-claude burns
```

**Example:**
```bash
echo '[
  {"worktree": "fix-auth", "prompt": "Look up Linear AUTH-123 and fix OAuth flow"},
  {"worktree": "bug-456", "prompt": "Fix null pointer in user profile - Linear BUG-456"}
]' | workout-claude burns
```

**JSON format requirements:**
- Array of objects (MUST be valid JSON array)
- Each object MUST have `worktree` (branch name) and `prompt` (context string)
- `prompt` can be empty string `""` to launch burns interactively without initial prompt
- Branch names auto-prefixed with `karlhepler/` (strips first if present)

**The command will:**
- Parse JSON input from stdin (fails immediately if invalid JSON or missing fields)
- Auto-prefix each branch with `karlhepler/`
- Create worktrees if they don't exist
- Create TMUX windows in detached mode
- Launch `burns "prompt"` in each window (passes prompt as positional argument to Ralph Orchestrator)
- Prepend worktree context to prompt (orients Ralph to correct directory)
- Report summary of created/failed worktrees

**When to use workout-claude burns:**
- Parent Claude has context (Linear tickets, user requests) to pass to burns instances
- Each worktree needs different context/instructions
- You want to eliminate repeating context across Ralph sessions
- You're coordinating parallel work with specific per-task details

**If user wants simple worktree creation without prompts:**
- For multiple worktrees without context, build JSON with empty prompts: `[{"worktree": "branch1", "prompt": ""}, {"worktree": "branch2", "prompt": ""}]`
- For single worktree, use `workout` command directly (not `workout-claude`)

## What the User Gets

After successful execution:

1. **Worktrees created** at:
   - `~/worktrees/org/repo/karlhepler/authentication/`
   - `~/worktrees/org/repo/karlhepler/payment/`
   - `~/worktrees/org/repo/karlhepler/notifications/`

2. **TMUX windows** (detached, running in background):
   - Window: `authentication` (with burns running)
   - Window: `payment` (with burns running)
   - Window: `notifications` (with burns running)

3. **How to access:**
   - `tmux list-windows` - See all windows
   - `tmux select-window -t authentication` - Switch to window
   - Or use TMUX prefix + window number

## Error Handling

The `workout-claude burns` command is error-resilient:

- **Existing worktrees:** Reuses them (idempotent)
- **Invalid branch names:** Skips and continues with others
- **TMUX failures:** Reports warning but continues
- **Missing burns command:** Warning only, windows still created

**Summary report shows:**
- ✓ Successfully created worktrees
- ✗ Failed worktrees (with reasons)

## Example Usage

### Example 1: Multiple Worktrees Without Specific Context

**User request:**
"I need to work on three features: user authentication, payment processing, and email notifications. Set up worktrees with Claude for each."

**Your response:**

"I'll create worktrees for these branches:
- karlhepler/user-authentication
- karlhepler/payment-processing
- karlhepler/email-notifications

Each will have a dedicated worktree, TMUX window, and burns (Ralph Orchestrator) instance.

Ready to proceed?"

**After user confirms "yes":**

```bash
echo '[
  {"worktree": "user-authentication", "prompt": ""},
  {"worktree": "payment-processing", "prompt": ""},
  {"worktree": "email-notifications", "prompt": ""}
]' | workout-claude burns
```

**Then explain:**

"Created 3 worktrees with TMUX windows and burns instances:
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
"I have three Linear tickets to work on. Create worktrees and pass the ticket context to each burns instance:
- AUTH-123: Fix OAuth flow
- BUG-456: Null pointer in user profile
- REF-789: Refactor API error handling"

**Your response:**

"I'll create worktrees with custom prompts for each ticket:
- karlhepler/fix-auth-123 - OAuth flow fix (Linear AUTH-123)
- karlhepler/bug-456-null-check - Null pointer fix (Linear BUG-456)
- karlhepler/refactor-api-789 - API error handling refactor (Linear REF-789)

Each burns instance will receive the ticket context automatically.

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
]' | workout-claude burns
```

**Then explain:**

"Created 3 worktrees with TMUX windows and context-aware burns instances:
- `fix-auth-123` - Burns knows to look up AUTH-123 and fix OAuth
- `bug-456-null-check` - Burns knows to fix null pointer per BUG-456
- `refactor-api-789` - Burns knows to refactor API errors per REF-789

Each burns instance has the specific context and can start work immediately without you repeating the requirements.

Switch to any window with:
- `tmux select-window -t fix-auth-123`
- `tmux select-window -t bug-456-null-check`
- `tmux select-window -t refactor-api-789`

Or use `tmux list-windows` to see all windows."

## Single Worktree Mode

For single worktree creation (no TMUX batch mode), use the standalone `workout` command directly:

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

Both `workout-claude` and the standalone `workout` command handle this automatically:
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
- **burns command** is the Ralph Orchestrator with Ralph Coordinator output style
- **Worktree structure** is `~/worktrees/org/repo/branch/`
- **Idempotent** means safe to run multiple times with same branches
- **Error resilient** means skips failures and continues with others
