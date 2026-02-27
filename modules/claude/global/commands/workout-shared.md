---
name: workout-shared
description: Shared workflow patterns for workout-burns and workout-staff skills. Contains common procedures for batch worktree creation with TMUX windows. Not invoked directly — referenced by workout-burns and workout-staff.
version: 1.0
---

# Workout Shared - Common Batch Worktree Workflow Patterns

This document defines shared workflow patterns used by both `workout-burns` and `workout-staff`. Both skills use `workout-claude` — a Nix shellapp (available system-wide after `hms`) that accepts a JSON array via stdin, creates git worktrees, and launches agents in TMUX windows. When executing either skill, follow all procedures defined here in addition to the skill-specific instructions.

## Hard Prerequisites

**Before anything else: verify required permissions are in the project's `permissions.allow`.**

Due to a known Claude Code bug ([GitHub #5140](https://github.com/anthropics/claude-code/issues/5140)), global `~/.claude/settings.json` permissions are **not** inherited by projects with their own `permissions.allow` -- project settings replace globals entirely. To verify: read `.claude/settings.json` or `.claude/settings.local.json` in the project root and confirm each required permission appears in the `permissions.allow` array.

**Required:**
- `Bash(workout-claude *)` -- the batch launcher command used to create worktrees and TMUX windows
- `Bash(workout *)` -- needed internally by workout-claude to create git worktrees
- `Bash(tmux *)` -- needed internally by workout-claude to create TMUX windows

**If any are missing:** Stop immediately. Do not start work. Surface to the staff engineer with the specific skill name and which permissions are missing.

## Common Key Features

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
3. **Show what agent will run** in each window (burns or staff, per the active skill)
4. **Wait for explicit approval** before running the command

**Only proceed if user confirms with "yes" or equivalent affirmative response.**

## JSON Input Format (Required)

**CRITICAL: workout-claude ONLY accepts JSON input via stdin.**

```bash
echo '[{"worktree": "branch", "prompt": "context"}]' | workout-claude <subcommand>
```

Replace `<subcommand>` with `burns` or `staff` depending on the active skill.

**JSON format requirements:**
- Array of objects (MUST be valid JSON array)
- Each object MUST have `worktree` (branch name) and `prompt` (context string)
- Each object MAY have `repo` (path to a different git repository — see Cross-Repo below)
- `prompt` can be empty string `""` to launch the agent interactively without initial prompt
- Branch names auto-prefixed with `karlhepler/` (strips first if present)

**The command will:**
- Parse JSON input from stdin (fails immediately if invalid JSON or missing fields)
- Auto-prefix each branch with `karlhepler/`
- Create worktrees if they don't exist
- Create TMUX windows in detached mode
- Launch the agent in each window (passes prompt as positional argument)
- Prepend worktree context to prompt (orients agent to correct directory)
- Report summary of created/failed worktrees

**If user wants simple worktree creation without prompts:**
- For multiple worktrees without context, build JSON with empty prompts: `[{"worktree": "branch1", "prompt": ""}, {"worktree": "branch2", "prompt": ""}]`
- For single worktree, use `workout` command directly (not `workout-claude`)

## Complex Prompts (Use Scratchpad)

**CRITICAL: `tmux send-keys` cannot safely handle long prompts with shell special characters.**

`workout-claude` passes the `prompt` field to each agent via `tmux send-keys`. Short, simple prompts work fine — but multi-line content, quotes, backticks, `$` variables, and braces will be **interpreted as shell commands** in the terminal instead of being injected as a prompt. The result is a corrupted or broken agent launch.

**The rule:**
- **Short, safe prompt** (no special characters, single line): Pass inline in the JSON `prompt` field.
- **Complex prompt** (multi-line, quotes, backticks, `$`, braces, etc.): Write to a scratchpad file first, then reference the file path in a short safe prompt.

**Pattern for complex prompts:**

Step 1 — Write the full task context to a scratchpad Markdown file:
```bash
cat > .scratchpad/workout-task-feature-x.md << 'EOF'
# Task: Feature X

Full multi-line task context here, including quotes, code
examples, and special characters — all stored safely in a file.
EOF
```

Step 2 — Pass a short safe reference prompt in the JSON:
```bash
echo '[{"worktree": "feature-x", "prompt": "Read your task from: /absolute/path/.scratchpad/workout-task-feature-x.md"}]' | workout-claude staff
```

The agent receives the short reference prompt cleanly via `tmux send-keys`, then reads the full context from the file.

**Use absolute paths** in the reference prompt — relative paths may not resolve correctly depending on where the agent's working directory starts.

## Cross-Repo Support

To create a worktree in a **different repository** than the current one, add a `repo` field to any JSON entry:

```bash
echo '[
  {"worktree": "fix-infra", "prompt": "Fix the deployment pipeline", "repo": "~/ops"}
]' | workout-claude <subcommand>
```

**`repo` field rules:**
- Path to any git repository on disk — absolute, `~`-prefixed, or relative (relative paths resolve against CWD at invocation time)
- When present: worktree is created in that repo instead of the current one
- When absent: default behavior (current repo) — fully backward compatible
- Can be mixed: some entries with `repo`, others without (each uses its own repo)

**Example — parallel work across two repos:**
```bash
echo '[
  {"worktree": "feature-x", "prompt": "Implement feature X", "repo": "~/maze-monorepo"},
  {"worktree": "fix-deploy", "prompt": "Fix staging deployment", "repo": "~/ops"}
]' | workout-claude <subcommand>
```

**When to use:** Whenever the user asks to set up a worktree for work that lives in a different repository than the current session context.

## What the User Gets

After successful execution:

1. **Worktrees created** at:
   - `~/worktrees/org/repo/karlhepler/<branch>/`

2. **TMUX windows** (detached, running in background):
   - One window per branch, named by branch suffix (no `karlhepler/` prefix)
   - Agent instance running in each window

3. **How to access:**
   - `tmux list-windows` - See all windows
   - `tmux select-window -t <branch-suffix>` - Switch to window
   - Or use TMUX prefix + window number

## Error Handling

The `workout-claude` command is error-resilient:

- **Existing worktrees:** Reuses them (idempotent)
- **Invalid branch names:** Skips and continues with others
- **TMUX failures:** Reports warning but continues
- **Missing agent command:** Warning only, windows still created

**Summary report shows:**
- ✓ Successfully created worktrees
- ✗ Failed worktrees (with reasons)

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
- [ ] Complex prompts written to scratchpad file with absolute path reference (when applicable)
- [ ] Summary provided showing created TMUX windows
- [ ] Instructions given on how to access windows

## Notes

- **Detached mode** means windows are created in background (no focus switch)
- **Window names** use branch suffix only (no `karlhepler/` prefix)
- **Worktree structure** is `~/worktrees/org/repo/branch/`
- **Idempotent** means safe to run multiple times with same branches
- **Error resilient** means skips failures and continues with others
