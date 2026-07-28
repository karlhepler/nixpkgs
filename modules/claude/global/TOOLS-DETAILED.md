# Detailed Tool Documentation

This file provides comprehensive documentation for critical Claude Code integration tools. For a complete list of all available commands and utilities, see TOOLS.md.

---

## smithers

**Purpose:** Foreground CLI that watches one pull request to completion — polls GitHub directly and invokes Claude only when there is actual work to do

**Command:** `smithers`

**Usage:**
```bash
# Auto-detect the PR for the current git branch and watch it in the foreground
smithers

# Watch a specific PR by number or full URL
smithers 123
smithers https://github.com/owner/repo/pull/123

# `watch` is accepted for backward compatibility but never required
smithers watch 123

# Resolve the PR and run the billing preflight only — no polling, no mutation
smithers --dry-run
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Resolve the PR and run the billing preflight only; exit without polling |
| `--i-accept-api-billing` | off | The only way to run with a raw-API billing credential present in the environment (see Billing Preflight below); there is no environment-variable override |
| `--log-file PATH` | see `SMITHERS_LOG_PATH` below | JSONL structured log destination |
| `--informational-bot-authors AUTHORS` | see `SMITHERS_INFORMATIONAL_BOT_AUTHORS` below | Comma-separated bot authors excluded from the actionable-bot-comment trigger |
| `--no-merge` | off | Watch and fix the PR, but never merge it — the operator merges manually |

**Environment Variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `SMITHERS_LOG_PATH` | `~/.local/state/smithers/smithers.jsonl` | JSONL log destination (overridden by `--log-file`) |
| `SMITHERS_INFORMATIONAL_BOT_AUTHORS` | `codecov[bot]` | Comma-separated bot-author exclusion list for the actionable-bot-comment trigger (overridden by `--informational-bot-authors`) |
| `SMITHERS_APPROVAL_WATCH_POLL_SECONDS` | `900` | Poll interval while the PR is clean and only waiting on human review; no CLI override |
| `SMITHERS_SLACK_DEDUP_TIMEOUT_SECONDS` | `45` | Wall-clock bound on the cross-restart Slack dedup probe; no CLI override |
| `SMITHERS_FIX_INVOCATION_TIMEOUT_SECONDS` | `1200` | Wall-clock ceiling on one fix-session invocation before its process tree is killed; no CLI override |

There is no `--max-ralph-iterations` / `--max-iterations` flag, or any equivalent environment variable, in the current CLI — the fix-attempt budget (4 attempts) and poll-cycle budget (10 cycles) are fixed constants, not operator-configurable.

**Billing Preflight:**
- Runs before every poll cycle, not just once at startup
- Fails closed: refuses to run if a raw-API billing credential (e.g. `ANTHROPIC_API_KEY`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`) is present — no degraded mode
- The only bypass is `--i-accept-api-billing`
- The subscription-billed headless-auth token is deliberately exempt from this refusal list

**How It Works (the gate):**

Each cycle: fetch a fresh PR snapshot (`gh pr view`, `gh pr checks`, `prc list`) → close out any actionable bot thread via `prc reply` + `prc resolve` before evaluating this same cycle → check five triggers → if a trigger fires and none of six suppressors block it, act.

Triggers (any one is sufficient): a failing CI check; a merge conflict with the base branch; an actionable, unresolved bot comment thread; a confirmed merge-queue entry bouncing (currently unreachable — no GitHub field yet exposes merge-queue state); or the PR being fully clean, approved, and ready to land, which routes to an automatic merge rather than a fix session.

Suppressors block action even when a trigger fires. Transient ones: only pending checks with nothing else actionable; a fix session already in flight; the operator's `--no-merge` opt-out. Terminal ones end the watch entirely (logged and notified): the fix-attempt budget is exhausted (4 attempts), the poll-cycle budget is exhausted (10 cycles), or HEAD hasn't advanced across two consecutive fix attempts (stagnation).

**Fix Execution:** a single blocking `staff -p --model sonnet --effort high --permission-mode dontAsk` invocation, given a bounded task brief via stdin, with deny rules blocking `gh pr merge`, `kubectl`, `aws`, and `gcloud`. Bounded by `SMITHERS_FIX_INVOCATION_TIMEOUT_SECONDS` (default 1200s / 20 minutes); on timeout the whole subprocess tree is killed. Runs with a small allowlisted environment, never the operator's full shell environment.

**Landing:** when the ready-to-land trigger fires, smithers merges the PR itself via `gh pr merge --squash` (unless `--no-merge` is set), then permanently revokes its own merge authority for the rest of the run.

**Behavior:**
- Fully ephemeral — no state file, no persistence across a restart; all counters live only in the running process's memory
- Polls every 60 seconds as the baseline cadence; falls back to `SMITHERS_APPROVAL_WATCH_POLL_SECONDS` (default 900s) while the PR is clean and merely awaiting human review, returning to the 60s cadence the moment that stops being true
- A GitHub fetch failure backs off exponentially (300s / 900s / 1800s) rather than reaching the gate at all

**Exit Codes:**
- `0` - Success (dry run completed, or the watch loop returned after a terminal stop)
- `1` - Error (PR could not be resolved, or the billing preflight refused to run)

**Notifications:**
- **macOS** via `osascript` — every terminal stop fires an audible notification; the recurring "clean and awaiting review" notice is silent. There is one sound, not distinct sounds per outcome.
- **Slack** via the separate `smithers-post` command, posted when the PR is clean and awaiting review. With no state file, cross-restart duplicate posts are avoided by asking Slack itself (a scoped headless Claude search) whether a post already exists before posting again.

**Examples:**
```bash
# Watch current branch's PR, auto-detecting it
smithers

# Watch a specific PR, never merging it automatically
smithers --no-merge 123

# Custom log destination and a wider bot exclusion list
smithers --log-file /tmp/smithers.jsonl --informational-bot-authors "codecov[bot],dependabot[bot]" 123

# Confirm PR resolution and billing preflight without polling
smithers --dry-run 123
```

**Integration:**
- Uses `prc` to read and close out PR comment threads every cycle
- Merges via `gh pr merge` when the gate decides the PR is ready to land
- Posts Slack notifications via the separate `smithers-post` command

**Related Commands:**
- `prc` - PR comment management; smithers sweeps bot threads through it every cycle
- `smithers-post` - Slack notification delivery (see `TOOLS.md`)

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

**Output Format:**

`--format {xml,json,human}` (default: `xml`) is a top-level flag that applies to every subcommand. Machine-readable examples that pipe through `jq` need `--format json` explicitly — XML is the default, not JSON.

**Subcommands:**

### list
Fetch and filter PR comments with powerful filtering options.

**Arguments:**
- `PR` (optional) - PR number, URL, or omit to infer from current branch

**Filters:**
- `--author USERNAME` - Filter by specific author username
- `--author-pattern REGEX` - Filter by author using regex pattern
- `--bots-only` - Show only bot comments
- `--inline-only` - Show only inline review comments (exclude PR-level comments)
- `--max-replies N` - Show comments with at most N replies (use 0 for unanswered)
- `--resolved` - Show only resolved threads
- `--unresolved` - Show only unresolved threads
- `--full` - Include full comment body text (default: metadata-only, no body)
- `--max-body-len N` - Truncate each comment body to N chars (requires `--full`)

**Output:** Comment metadata, reply counts, and thread status (XML by default; JSON with `--format json`)

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

**Output:** Success status and new comment details (XML by default; JSON with `--format json`)

### resolve / unresolve
Mark a review thread as resolved or unresolved.

**Arguments:**
- `thread-id` - Thread node ID (from `list` output)

**Output:** Success status and thread resolution state (XML by default; JSON with `--format json`)

### collapse
Minimize comments using GitHub's minimize feature.

**Arguments:**
- `PR` (optional) - PR number, URL, or omit to infer from current branch

**Filters:** `--author`, `--author-pattern`, `--bots-only` only — unlike `list`, `collapse` does not support `--max-replies`, `--resolved`, or `--unresolved`.

**Options:**
- `--reason CHOICE` - Minimize reason (choices: off-topic, spam, outdated, abuse, resolved)
  - Default: resolved
- `--verbose` / `-v` - Emit a success report (format controlled by `--format`)

**Output:** Silent on success (exit 0) unless `--verbose`/`-v` is passed, in which case it emits the collapsed count and any errors. Errors always go to stderr with exit 1, regardless of `--verbose`.

**Data Model:**

Comments returned by `list` include (shown here with `--full`; by default `body`, `body_text`, and `diff_hunk` are omitted entirely — metadata-only):

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
  "diff_hunk": null,
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
# Get comment ID from list output (--format json required for jq)
prc list --format json --bots-only --max-replies 0 | jq -r '.comments[0].id'

# Reply to that comment
prc reply 123456789 "Fixed in commit abc123. The issue was..."
```

**Resolve thread after fixing:**
```bash
# Get thread ID from comment (--format json required for jq)
prc list --format json --unresolved | jq -r '.comments[0].thread_id'

# Resolve it
prc resolve PRR_kwDOAbc123
```

**Collapse resolved bot comments:**
```bash
prc collapse --bots-only --reason resolved
```

**Integration:**
- Uses GitHub GraphQL API exclusively for efficiency
- Outputs XML by default; `--format json` for JSON consumption by agents/scripts
- Invoked directly by smithers for its GitHub read adapter and bot-thread sweep (`prc list --format json`, `prc reply`, `prc resolve`)
- Works seamlessly with current branch or explicit PR specification

**Rate Limiting:**
- All mutations include 1-second delays
- GraphQL cost information included in `list` output's `rate_limit` field
- Respects GitHub API rate limits

**Error Handling:**
- All errors returned in the selected output format (XML by default; JSON with `--format json`) with error codes
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
