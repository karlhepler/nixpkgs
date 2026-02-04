# Detailed Tool Documentation

This file provides comprehensive documentation for critical Claude Code integration tools. For a complete list of all available commands and utilities, see TOOLS.md.

---

## burns

**Purpose:** Run Ralph Orchestrator with Staff Engineer output style

**Command:** `burns`

**Usage:**
```bash
# Inline prompt (uses -p flag)
burns "Your prompt here"

# Prompt from file (uses -P flag)
burns path/to/file.md

# Custom max iterations
burns --max-ralph-iterations 5 "Your prompt"
```

**Configuration:**

Priority: CLI flag > environment variable > default

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `--max-ralph-iterations N` | `BURNS_MAX_RALPH_ITERATIONS` | 3 | Maximum iterations for Ralph Orchestrator |

**Behavior:**
- Automatically sets `KANBAN_SESSION` to `burns-<cwd-hash>` for persistent session tracking
- Accepts either inline prompt strings or file paths
- Auto-detects file vs string based on file existence
- Handles Ctrl+C gracefully with full process tree cleanup

**Environment Variables Set:**
- `KANBAN_SESSION=burns-<cwd-hash>` - Persistent session ID based on current working directory

**Exit Codes:**
- `0` - Success
- `1` - Error (invalid arguments, missing Staff Engineer hat file)
- `130` - User interrupted (Ctrl+C)

**Examples:**
```bash
# Quick one-off task
burns "Review the authentication logic in auth.go"

# Complex multi-step task from file
burns project-plan.md

# Allow more iterations for complex tasks
burns --max-ralph-iterations 5 "Refactor the entire API layer"

# Override default with environment variable
BURNS_MAX_RALPH_ITERATIONS=2 burns "Quick code review"
```

**Related Commands:**
- `smithers` - Autonomous PR watcher that uses burns internally
- `kanban` - View cards created during burns sessions

---

## smithers

**Purpose:** Token-efficient autonomous PR watcher

**Command:** `smithers`

**Usage:**
```bash
# Infer PR from current branch
smithers

# Specify PR by number
smithers 123

# Specify PR by URL
smithers https://github.com/owner/repo/pull/123

# Custom Ralph iterations
smithers --max-ralph-iterations 5 123

# Custom watch cycles
smithers --max-iterations 6 123

# Combine both options
smithers --max-ralph-iterations 2 --max-iterations 3 123
```

**Configuration:**

Priority: CLI flag > environment variable > default

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `--max-ralph-iterations N` | `SMITHERS_MAX_RALPH_ITERATIONS` | 3 | How many times to ask Ralph to fix issues |
| `--max-iterations N` | `SMITHERS_MAX_ITERATIONS` | 4 | How many CI check cycles to monitor |

**How It Works:**

1. **Poll CI checks** (token-free) - Wait for checks to reach terminal state
2. **Gather intelligence** - Collect failed checks, bot comments, merge conflicts
3. **Invoke Ralph** (only when work needed) - Generate focused prompt and run `burns`
4. **Re-check** - Verify fixes worked, repeat if needed
5. **Complete** - Exit when PR is ready to merge or max cycles reached

**Behavior:**
- Automatically sets `KANBAN_SESSION` to `smithers-pr-<number>` for persistent tracking
- Polls CI checks every 10 seconds (configurable via `POLL_INTERVAL` constant)
- Only invokes Ralph when actionable work exists (failed checks or merge conflicts)
- Sends macOS notifications on completion, interruption, or max cycles reached
- Handles Ctrl+C gracefully with full process tree cleanup
- Dynamically extends watch cycles if unaddressed bot comments exist

**Environment Variables Set:**
- `KANBAN_SESSION=smithers-pr-<number>` - Persistent session ID based on PR number
- `BURNS_MAX_RALPH_ITERATIONS` - Passed to burns when invoking Ralph

**Exit Codes:**
- `0` - Success (PR ready to merge or already merged)
- `1` - Max cycles reached with unresolved issues
- `130` - User interrupted (Ctrl+C)

**Notifications:**
- **Success** (Glass sound) - PR ready to merge
- **Max Cycles** (Sosumi sound) - Reached limit without completing
- **Interrupted** (Basso sound) - User pressed Ctrl+C

**Examples:**
```bash
# Watch current branch's PR
smithers

# Watch specific PR with defaults
smithers 123

# Conservative approach (fewer Ralph invocations)
smithers --max-ralph-iterations 2 123

# Aggressive approach (more watch cycles)
smithers --max-iterations 6 123

# Quick check for small PRs
SMITHERS_MAX_RALPH_ITERATIONS=1 SMITHERS_MAX_ITERATIONS=2 smithers
```

**Integration:**
- Works seamlessly with `prc` for comment management
- Uses `burns` internally to invoke Ralph
- Creates kanban cards for work tracking
- Integrates with GitHub CLI (`gh`) for all PR operations

**Related Commands:**
- `burns` - Underlying orchestrator used by smithers
- `prc` - PR comment management (recommended in generated prompts)
- `kanban` - View work tracked during smithers sessions

---

## prc

**Purpose:** PR comment management using GitHub GraphQL API

**Command:** `prc`

**Usage:**
```bash
# List commands
prc list [PR]                    # List all comments
prc list --bots-only             # Only bot comments
prc list --max-replies 0         # Unanswered comments
prc list --author username       # By specific author
prc list --author-pattern ".*bot.*"  # By author regex
prc list --unresolved            # Only unresolved threads

# Reply to comments
prc reply <comment-id> "message"

# Resolve/unresolve threads
prc resolve <thread-id>
prc unresolve <thread-id>

# Collapse (minimize) comments
prc collapse [PR] --bots-only --reason resolved
```

**Subcommands:**

### list
Fetch and filter PR comments with powerful filtering options.

**Arguments:**
- `PR` (optional) - PR number, URL, or omit to infer from current branch

**Filters:**
- `--author USERNAME` - Filter by specific author username
- `--author-pattern REGEX` - Filter by author using regex pattern
- `--bots-only` - Show only bot comments
- `--max-replies N` - Show comments with at most N replies (use 0 for unanswered)
- `--resolved` - Show only resolved threads
- `--unresolved` - Show only unresolved threads

**Output:** JSON with comment metadata, reply counts, thread status

### reply
Reply to a comment (inline or PR-level).

**Arguments:**
- `comment-id` - Comment database ID (from `list` output)
- `message` - Reply message text

**Behavior:**
- Auto-detects comment type (inline vs PR-level)
- For inline comments: Uses review thread reply mutation
- For PR-level comments: Posts comment with @mention
- Rate-limited: 1 second delay between operations

**Output:** JSON with success status and new comment details

### resolve / unresolve
Mark a review thread as resolved or unresolved.

**Arguments:**
- `thread-id` - Thread node ID (from `list` output)

**Output:** JSON with success status and thread resolution state

### collapse
Minimize comments using GitHub's minimize feature.

**Arguments:**
- `PR` (optional) - PR number, URL, or omit to infer from current branch

**Filters:** Same as `list` command

**Options:**
- `--reason CHOICE` - Minimize reason (choices: off-topic, spam, outdated, abuse, resolved)
  - Default: resolved

**Output:** JSON with collapsed count and any errors

**Data Model:**

Comments returned by `list` include:

```json
{
  "id": 123456789,
  "node_id": "MDEyOklzc3VlQ29tbWVudDEyMzQ1Njc4OQ==",
  "type": "pr-level" | "inline",
  "author": "username",
  "author_type": "User" | "Bot",
  "is_bot": true,
  "body": "Full markdown body",
  "body_text": "Plain text body",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "is_minimized": false,
  "minimized_reason": null,
  "url": "https://github.com/...",
  "path": "path/to/file.go",
  "line": 42,
  "thread_id": "PRR_kwDOAbc123",
  "is_resolved": false,
  "in_reply_to_id": null,
  "reply_count": 2
}
```

**Common Workflows:**

**Find unanswered bot comments:**
```bash
prc list --bots-only --max-replies 0
```

**Reply to specific comment:**
```bash
# Get comment ID from list output
prc list --bots-only --max-replies 0 | jq -r '.comments[0].id'

# Reply to that comment
prc reply 123456789 "Fixed in commit abc123. The issue was..."
```

**Resolve thread after fixing:**
```bash
# Get thread ID from comment
prc list --unresolved | jq -r '.comments[0].thread_id'

# Resolve it
prc resolve PRR_kwDOAbc123
```

**Collapse resolved bot comments:**
```bash
prc collapse --bots-only --reason resolved
```

**Integration:**
- Uses GitHub GraphQL API exclusively for efficiency
- Outputs machine-readable JSON for consumption by agents
- Recommended by smithers in generated prompts
- Works seamlessly with current branch or explicit PR specification

**Rate Limiting:**
- All mutations include 1-second delays
- GraphQL cost information included in output
- Respects GitHub API rate limits

**Error Handling:**
- All errors returned as JSON with error codes
- Descriptive error messages for debugging
- Exit code 1 for errors, 0 for success

**Examples:**
```bash
# Daily workflow: Check for new bot comments
prc list --bots-only --max-replies 0

# Respond to bot feedback
prc reply 123456789 "Fixed in commit $(git rev-parse --short HEAD)"

# Clean up after PR review
prc resolve PRR_kwDOAbc123
prc collapse --author-pattern ".*bot.*" --reason resolved

# Filter by specific bot
prc list --author "dependabot[bot]"

# Check unresolved threads before merging
prc list --unresolved
```

**Related Commands:**
- `smithers` - Uses prc for efficient comment management
- `gh pr view` - View PR details
- `gh pr checks` - View CI check status

---

*For a complete list of all available tools and utilities, see TOOLS.md (auto-generated from package metadata).*
