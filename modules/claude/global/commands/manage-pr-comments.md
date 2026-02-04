---
name: manage-pr-comments
description: Manage PR comments using prc CLI when user asks to "review PR comments", "reply to comments", "check bot feedback", "filter PR comments", "manage comment threads", or "resolve comment threads"
allowed-tools:
  - Bash(prc *)
  - Bash(gh *)
---

# Manage Pull Request Comments

**Purpose:** Efficiently manage PR comments and review threads using the `prc` CLI tool, which provides GraphQL-powered operations for filtering, replying to, and resolving comment threads.

## When to Use This Skill

Activate when the user asks to:
- "Review PR comments"
- "Reply to PR comments"
- "Check bot feedback"
- "Filter PR comments"
- "Manage comment threads"
- "Resolve comment threads"
- "Find unanswered comments"
- "Collapse bot comments"

## Overview

`prc` (PR Comments) is a GraphQL-based CLI tool for managing pull request comments. It provides:

- **Efficient filtering** - Find specific comments by author, bot status, reply count
- **Thread management** - Reply to threads, resolve/unresolve discussions
- **Bot comment handling** - Identify and manage automated feedback
- **Machine-readable output** - JSON output for programmatic use
- **Rate-limit aware** - Built-in 1-second delays between mutations

All operations use GitHub's GraphQL API for consistent, structured data access.

## Common Use Cases

### 1. Smithers Integration (Autonomous PR Watching)

The `smithers` command uses `prc` to handle bot comments during automated PR monitoring.

**Typical workflow:**
```bash
# Find all unanswered bot comments
prc list --bots-only --max-replies 0

# Reply to specific comment
prc reply <thread-id> "Fixed in commit abc123"

# Resolve thread after addressing
prc resolve <thread-id>
```

### 2. Manual Review Feedback Response

When responding to human reviewers, use `prc` to manage comment threads efficiently.

**Workflow:**
```bash
# List all comments from specific reviewer
prc list --author "reviewer-username"

# Reply to their feedback
prc reply <thread-id> "Good catch! Updated the logic."

# Resolve after discussion complete
prc resolve <thread-id>
```

### 3. Bulk Thread Resolution

After addressing all review feedback, resolve threads in bulk.

**Workflow:**
```bash
# List unresolved threads (JSON output for scripting)
prc list | jq -r '.[] | select(.isResolved == false) | .id'

# Resolve each thread
for thread_id in $(prc list | jq -r '.[] | select(.isResolved == false) | .id'); do
  prc resolve "$thread_id"
done
```

### 4. Bot Comment Cleanup

Minimize or collapse outdated bot comments to reduce noise.

**Workflow:**
```bash
# Find all bot comments
prc list --bots-only

# Collapse specific bot comments
prc collapse <comment-id>
```

## Command Reference

### list - Query Comments

**Purpose:** Fetch and filter PR comments.

**Usage:**
```bash
prc list [--author USERNAME] [--author-pattern REGEX] [--bots-only] [--max-replies N]
```

**Options:**
- `--author USERNAME` - Filter by exact author username
- `--author-pattern REGEX` - Filter by author username pattern (regex)
- `--bots-only` - Only show comments from bot accounts (author.__typename == "Bot")
- `--max-replies N` - Filter threads with at most N replies (use 0 for unanswered)

**Output:** JSON array of comment/thread objects with fields:
- `id` - GraphQL node ID (use for mutations)
- `databaseId` - Integer ID (for REST API compatibility)
- `author` - Author object with `__typename`, `login`, `name`
- `body` - Comment text (markdown)
- `bodyText` - Plain text version
- `isResolved` - Boolean (for review threads)
- `replyCount` - Number of replies in thread
- `createdAt` / `updatedAt` - Timestamps

**Examples:**

Find unanswered bot comments:
```bash
prc list --bots-only --max-replies 0
```

Find comments from specific user:
```bash
prc list --author "octocat"
```

Find all Dependabot comments:
```bash
prc list --author-pattern "dependabot"
```

### reply - Reply to Thread

**Purpose:** Add reply to existing review thread.

**Usage:**
```bash
prc reply <THREAD_ID> "Your reply text"
```

**Parameters:**
- `THREAD_ID` - GraphQL node ID from `prc list` output
- Reply text in quotes (supports markdown)

**Mutation:** Uses `addPullRequestReviewThreadReply` GraphQL mutation

**Rate limiting:** Automatically waits 1 second between replies

**Example:**

Reply with commit reference:
```bash
prc reply "MDEyOlB1bGxSZXF1ZXN0UmV2aWV3VGhyZWFkMTIzNDU=" "Fixed in commit abc123. The issue was X because Y."
```

### resolve - Resolve Thread

**Purpose:** Mark review thread as resolved.

**Usage:**
```bash
prc resolve <THREAD_ID>
```

**Parameters:**
- `THREAD_ID` - GraphQL node ID from `prc list` output

**Mutation:** Uses `resolveReviewThread` GraphQL mutation

**Permissions:** Requires Repository Contents: Read and Write

**Example:**

Resolve thread after addressing feedback:
```bash
prc resolve "MDEyOlB1bGxSZXF1ZXN0UmV2aWV3VGhyZWFkMTIzNDU="
```

### unresolve - Reopen Thread

**Purpose:** Reopen previously resolved thread.

**Usage:**
```bash
prc unresolve <THREAD_ID>
```

**Parameters:**
- `THREAD_ID` - GraphQL node ID from `prc list` output

**Mutation:** Uses `unresolveReviewThread` GraphQL mutation

**Example:**

Reopen thread for further discussion:
```bash
prc unresolve "MDEyOlB1bGxSZXF1ZXN0UmV2aWV3VGhyZWFkMTIzNDU="
```

### collapse - Minimize Comment

**Purpose:** Hide/collapse comment (marks as minimized).

**Usage:**
```bash
prc collapse <COMMENT_ID> [--reason CLASSIFIER]
```

**Parameters:**
- `COMMENT_ID` - GraphQL node ID from `prc list` output
- `--reason` - Optional classifier: SPAM, ABUSE, OFF_TOPIC, OUTDATED, DUPLICATE, RESOLVED

**Mutation:** Uses `minimizeComment` GraphQL mutation

**Known issue:** GitHub lowercases classifier enum, resulting in generic "This comment has been minimized" message instead of specific reason.

**Example:**

Collapse outdated bot comment:
```bash
prc collapse "MDEyOklzc3VlQ29tbWVudDEyMzQ1" --reason OUTDATED
```

## Workflows

### Workflow: Responding to Bot Feedback

**Scenario:** Smithers detected bot comments requiring action.

**Steps:**

1. **List unanswered bot comments:**
```bash
prc list --bots-only --max-replies 0
```

2. **Review each comment in context:**
```bash
# Extract comment details from JSON
prc list --bots-only --max-replies 0 | jq -r '.[] | "\(.id) \(.author.login) \(.path):\(.line) \(.body)"'
```

3. **Read the code at commented location:**
```bash
# Use Read tool on file:line from comment
```

4. **Critically evaluate:**
- Is the bot claim valid?
- Do you have context the bot lacks?
- Is this a false positive?

5. **Take action:**
- **If actionable:** Fix code → commit → push → reply with commit SHA
- **If false positive:** Reply explaining why bot is incorrect
- **If out of scope:** Reply deferring to future work

6. **Reply and resolve:**
```bash
prc reply <thread-id> "Fixed in abc123. The issue was X."
prc resolve <thread-id>
```

### Workflow: Bulk Thread Resolution

**Scenario:** All feedback addressed, ready to resolve all threads.

**Steps:**

1. **Fetch unresolved threads:**
```bash
THREADS=$(prc list | jq -r '.[] | select(.isResolved == false) | .id')
```

2. **Verify all addressed:**
```bash
# Review each thread body to ensure no pending work
prc list | jq -r '.[] | select(.isResolved == false) | "\(.id) \(.body[:100])"'
```

3. **Resolve each thread:**
```bash
echo "$THREADS" | while read thread_id; do
  prc resolve "$thread_id"
  sleep 1  # Rate limiting
done
```

### Workflow: Finding Specific Comments

**Scenario:** Need to find comments from specific reviewer or about specific topic.

**Filter strategies:**

Find comments by reviewer:
```bash
prc list --author "reviewer-username"
```

Find Dependabot comments:
```bash
prc list --author-pattern "dependabot"
```

Find unanswered comments:
```bash
prc list --max-replies 0
```

Combine filters (client-side with jq):
```bash
# Find unanswered comments from bots about security
prc list --bots-only --max-replies 0 | jq '.[] | select(.body | test("security"; "i"))'
```

## Decision Trees

### When to Use prc vs gh api Directly

**Use prc when:**
- ✅ You need filtered comment lists (by author, bot status, reply count)
- ✅ You want machine-readable JSON output
- ✅ You're replying to review threads
- ✅ You're resolving/unresolving threads
- ✅ You need rate-limit handling built-in
- ✅ You want consistent GraphQL interface

**Use gh api when:**
- ⚠️ You need PR-level comments (not review threads)
- ⚠️ You need raw GraphQL for complex custom queries
- ⚠️ prc doesn't support specific operation yet

### Which Filters to Combine

**For bot comment triage:**
```bash
prc list --bots-only --max-replies 0
```
Finds: Unanswered bot comments (typical smithers use case)

**For reviewer-specific feedback:**
```bash
prc list --author "username"
```
Finds: All comments from specific person

**For pattern-based filtering:**
```bash
prc list --author-pattern "bot|dependabot|renovate"
```
Finds: Comments from any bot matching pattern

**For manual review workflow:**
```bash
prc list --max-replies 0
```
Finds: All unanswered threads (bots + humans)

## Examples with jq Parsing

### Extract Thread IDs for Scripting

Get all unresolved thread IDs:
```bash
prc list | jq -r '.[] | select(.isResolved == false) | .id'
```

### Create Summary Report

Generate human-readable comment summary:
```bash
prc list --bots-only | jq -r '.[] | "[\(.author.login)] \(.path // "PR"):\(.line // "N/A") - \(.body[:80])..."'
```

Output example:
```
[dependabot[bot]] package.json:5 - Bumps lodash from 4.17.19 to 4.17.21...
[github-actions[bot]] PR:N/A - Workflow failed: build step...
```

### Count Comments by Author

```bash
prc list | jq -r '.[] | .author.login' | sort | uniq -c | sort -rn
```

Output example:
```
  5 dependabot[bot]
  3 octocat
  2 reviewer-name
```

## Integration with Smithers

The `smithers` autonomous PR watcher uses `prc` during its bot comment handling cycle.

**Smithers workflow:**
1. Poll CI checks until terminal state
2. Gather failed checks, bot comments, merge conflicts
3. Generate focused prompt for Ralph
4. **In prompt:** Recommend `prc` for bot comment management:

```markdown
**Recommended Tool:** Use `prc` CLI for efficient comment management:
- List unanswered bot comments: `prc list --bots-only --max-replies 0`
- Reply to specific comment: `prc reply <comment-id> "your message"`
- Resolve discussion thread: `prc resolve <thread-id>`
- See full workflow: `/manage-pr-comments` skill
```

**Why this pattern:**
- Smithers polls (cheap, no tokens)
- Ralph fixes (targeted, uses prc)
- prc manages comments (GraphQL-efficient)

## Key Principles

### Critical Thinking for Bot Comments

- **You have full codebase access** - Bots see only the diff
- **Bots follow patterns** - You understand intent
- **False positives are common** - Verify every claim
- **Your judgment > bot suggestion** when you have more context

### Trust but Verify for Human Comments

- Humans have domain knowledge you might lack
- They might see edge cases you missed
- Take their concerns seriously
- But still verify by reading code
- Discuss respectfully if you disagree

### Reply Quality

**Concise and substantive:**
- One or two sentences maximum
- Focus on what changed and why
- Include commit SHA if you fixed something
- Be positive but not effusive

**Example progression:**

❌ Too verbose:
"Thank you so much for catching this! You're absolutely right that this could be a problem. I really appreciate you taking the time to review this so thoroughly. I've gone ahead and implemented your excellent suggestion in commit abc123."

✅ Just right:
"Good catch! Fixed in abc123. The issue was X because Y."

## Error Handling

**If prc command fails:**

1. **Check authentication:**
```bash
gh auth status
```

2. **Verify PR context:**
```bash
gh pr view
```

3. **Check permissions:**
- `prc resolve` requires Repository Contents: Read and Write
- `prc reply` requires Pull Requests: Write

4. **Verify node ID format:**
- Use IDs from `prc list` output (GraphQL node IDs)
- Don't use database IDs from REST API

**Common errors:**

- `401 Unauthorized` - Check gh auth and token permissions
- `403 Forbidden` - Insufficient repository permissions
- `404 Not Found` - Invalid node ID or thread doesn't exist
- `Rate limit exceeded` - Wait for reset (check `gh api rate_limit`)

## Rate Limits

**GitHub GraphQL Limits:**
- 5,000 points/hour for authenticated users
- 2,000 points/minute maximum
- Built-in 1-second delays between mutations in `prc`

**Best practices:**
- Let `prc` handle rate limiting automatically
- Avoid rapid-fire bulk operations without delays
- Monitor rate limit if scripting: `gh api rate_limit`

## Success Criteria

Before completing work:

- [ ] All relevant comments identified and filtered correctly
- [ ] Each comment critically evaluated (bots verified, humans considered)
- [ ] Code read for context on each comment
- [ ] Appropriate action taken (fix/defer/reject/discuss)
- [ ] For fixes: Changes committed AND pushed BEFORE replying
- [ ] For fixes: Reply includes commit SHA
- [ ] Threads resolved appropriately
- [ ] No generic PR-level comments added (use threaded replies)
- [ ] Machine-readable JSON output used for scripting where appropriate
