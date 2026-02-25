---
name: review-pr-comments
description: Review PR feedback and respond to code reviewers when user asks to "review PR feedback", "respond to reviewer", "address review comments", "reply to code review", "check PR feedback", or "address PR review"
version: 1.0
---

# Review Pull Request Comments

**Purpose:** Systematically review and respond to all unresolved PR comments that you haven't replied to yet.

## Invocation Context

$ARGUMENTS

## Hard Prerequisites

**Before anything else: verify required permissions are in the project's `permissions.allow`.**

Due to a known Claude Code bug ([GitHub #5140](https://github.com/anthropics/claude-code/issues/5140)), global `~/.claude/settings.json` permissions are **not** inherited by projects with their own `permissions.allow` -- project settings replace globals entirely. To verify: read `.claude/settings.json` or `.claude/settings.local.json` in the project root and confirm each required permission appears in the `permissions.allow` array.

**Required:**
- `Bash(git add *)`
- `Bash(git commit *)`
- `Bash(git push *)`
- `Bash(gh api --method POST *)`

This skill fixes code, commits, pushes, replies to PR comments, and resolves bot threads via the GitHub API. Without these permissions, the fix-commit-push-reply workflow silently fails in `dontAsk` mode.

**If any are missing:** Stop immediately. Do not start work. Surface to the staff engineer:
> "Blocked: One or more required permissions (`Bash(git add *)`, `Bash(git commit *)`, `Bash(git push *)`, `Bash(gh api --method POST *)`) are missing from `permissions.allow`. Add them before delegating review-pr-comments."

## Critical Rules

**The Four Nevers:**
1. ❌ Never add PR-level comments (`gh pr comment`)
2. ❌ Never edit original comments (PATCH method)
3. ❌ Never reply to a comment where your most recent reply is already the last one
   - Check the reply thread before responding
   - If there are no replies → OK to reply
   - If the most recent reply is from someone else → OK to reply
   - If the most recent reply is from Claude → SKIP (do not reply again)
4. ❌ Never reply without critical evaluation

**The One Critical Order:**
- ⚠️ **ALWAYS fix → commit → push → THEN reply**
- Never reply before the push completes successfully
- Reply MUST include the commit SHA if you fixed something

**Always:**
- ✅ Reply directly to comment threads
- ✅ Think critically about bot suggestions — false positives are common
- ✅ Treat human reviewers as authorities — their perspective matters
- ✅ Ask clarifying questions for ambiguous human comments instead of assuming
- ✅ Resolve bot threads after replying
- ✅ Leave human threads open (conversation, not closure)

## Workflow

### Phase 1: Fetch Comments Needing Replies

```bash
# Get PR info
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
PR_NUM=$(gh pr view --json number -q .number)
USERNAME=$(gh api user -q .login)  # Note: USERNAME assumes single-token GitHub auth (standard setup)

# Fetch all comments with is_bot field via prc
prc list $PR_NUM > .scratchpad/pr_comments.json

# Filter to comments that need replies from Claude
jq --arg user "$USERNAME" '
  .comments as $all_comments |

  # Get all top-level comments not by Claude
  [$all_comments[] | select(.in_reply_to_id == null) | select(.author == $user | not)] as $top_level |

  # For each top-level comment, apply thread-type-specific filtering
  $top_level[] |
  . as $comment |

  # Get all replies to this comment (chronological)
  ($all_comments | map(select(.in_reply_to_id == $comment.id)) | sort_by(.created_at)) as $replies |

  # Last reply in thread (null if none)
  (if ($replies | length) > 0 then ($replies | last) else null end) as $last_reply |

  if $comment.is_bot then
    # Bot threads: prc list returns all comments; the jq filter above selects which need replies.
    # Accept as-is — no additional filtering needed.
    select(true)
  else
    # Human threads:
    # - SKIP if our most recent reply is already the last one (waiting for human, do not double-reply)
    # - REVIEW if there is a new human reply after our last reply (conversation has continued)
    select(
      # Case 1: No replies yet -> OK to reply
      $last_reply == null or

      # Case 2: Most recent reply is NOT from Claude -> human responded, warrants another look
      ($last_reply.author != $user)
    )
  end
' .scratchpad/pr_comments.json > .scratchpad/unreplied_comments.json
```

### Phase 2: Evaluate Each Comment

For each comment that needs a reply:

**1. Read the comment:**
```bash
jq --slurp -r '.[] |
  "ID: \(.id)\nAuthor: \(.author)\nis_bot: \(.is_bot)\nPath: \(.path):\(.line)\n\(.body)\n---"' .scratchpad/unreplied_comments.json
```

**2. Identify comment author type (2-tier detection):**

**Tier 1 — prc detection (primary, authoritative):**
Every comment in `prc list` output includes an `is_bot` field. If `is_bot == true`, treat as bot. This covers all GitHub App bots (e.g., `github-actions[bot]`, `dependabot[bot]`, `renovate[bot]`).

**Tier 2 — Known machine user names (fallback):**
Some bots are "machine users" — GitHub classifies them as `User` type, so prc won't mark them as bots. If `is_bot == false`, check `.author` against this list: `codecov`, `dependabot`, `snyk`, `sonarcloud`, `renovate`, `deepsource`, `codeclimate`, `mergify`, `linear`. (Note: `dependabot` and `renovate` are already caught by Tier 1 as GitHub Apps, but their bare names appear here as a fallback for any non-App account variants Tier 1 might miss.) If matched, treat as bot.

**Routing:**
- `is_bot == true` → bot handling track
- `is_bot == false` AND `.author` matches known machine user names → bot handling track
- `is_bot == false` AND no match → human handling track

**When uncertain:** Treat as human. The cost of being curt with a real person outweighs the cost of being extra careful with a bot.

**3. Read the code:**
- Use Read tool on `.path` at line `.line`
- Get surrounding context (±10 lines)
- Understand what code is doing

**4. Critically evaluate:**

**For bot comments — mechanical, efficient:**
- What is the bot claiming?
- Read the actual code — is the claim valid?
- Do you have context the bot lacks?
- Is this a false positive?
- Decide: fix, reject with explanation, or ignore if clearly irrelevant.
- Bot threads: reply after any action, then **resolve the thread** (bots don't continue conversations).

**For human comments — authority, dialogue:**
- Treat the reviewer as someone whose perspective genuinely matters.
- What concern are they raising? What might they know that you don't?
- Read the code. Do you see the issue? Could there be an edge case you missed?
- When the comment is ambiguous, **ask a clarifying question** rather than assuming.
- Do NOT auto-resolve human threads — leave them open for the conversation to continue.
- Your reply is an invitation to dialogue, not a notification that it's done.

**5. Decide action:**
- **Fix:** Implement change, commit, push, reply with commit SHA
- **Defer:** Valid but out of scope, reply explaining why
- **Reject:** Not applicable, reply with reasoning
- **Discuss:** Ambiguous or you disagree, ask a clarifying question or share your thinking and invite response

### Phase 3: Take Action (if fixing)

**CRITICAL: If you decide to fix the issue, you MUST complete ALL steps below BEFORE replying:**

```bash
# 1. Make the change using Edit/Write tools
# 2. Verify the change
# 3. Commit
git add <file>
git commit -m "fix: address PR feedback - <concise description>

Addresses comment: <comment_url>"

# 4. Push
git push

# 5. Get commit SHA (needed for reply)
COMMIT_SHA=$(git rev-parse --short HEAD)
```

**STOP:** Do not proceed to Phase 4 until the push completes successfully.

### Phase 4: Reply to Comment

**Now reply (only after Phase 3 is complete if fixing):**

```bash
prc reply COMMENT_ID '<your concise reply>'
```

**For bot threads only — resolve after replying:**

```bash
# THREAD_ID is the thread_id field from prc list output (GraphQL node ID, not comment database ID)
prc resolve THREAD_ID
```

Do NOT resolve human threads. Leave them open.

**Reply guidelines by author type:**

**Bot — close the loop efficiently:**

Fixed:
```
Fixed in COMMIT_SHA. [One sentence on what changed.]
```

Rejected (bot is factually wrong):
```
This is correct because [specific reason the bot's analysis was incorrect].
```

Rejected (code is intentional, not an error):
```
This is intentional because [specific reason for the deviation by design].
```

After replying to a bot thread: resolve the thread.

---

**Human — tone requirements:**

Replies to humans must be:
- **Curious and respectful** — assume positive intent, engage with the idea
- **Short** — 1-3 sentences maximum. No walls of text.
- **Authentic** — sounds like a real person wrote it

**Explicitly prohibited language (never use these):**
- "good catch", "great point", "absolutely", "certainly", "of course"
- "happy to", "I went ahead and", "I've gone ahead"
- "rip it out", "no worries", "sounds good", "makes sense"
- Any opener that reads like a chatbot greeting
- Filler affirmations before the actual substance

If it sounds like a chatbot wrote it, rewrite it.

**Human reply templates:**

Fixed:
```
Fixed in COMMIT_SHA. [What changed and why in plain language.]
```

Disagreeing or offering alternative:
```
[Your specific concern or alternative.] [Reason.] [Optional: "What do you think?" or "Am I missing something?"]
```

Ambiguous — ask rather than assume:
```
[What you're uncertain about.] [Specific question to resolve it.]
```

Deferred:
```
[Acknowledge the validity.] Out of scope here — created #XYZ to track it.
```

Do NOT resolve human threads after replying.

### Phase 5: Verify

After replying to all comments:

```bash
# Re-fetch comments and confirm replies were posted under their parent threads
prc list $PR_NUM | jq '[.comments[] | select(.in_reply_to_id != null)] | length'

# Confirm no PR-level comments were added by Claude
prc list $PR_NUM | jq --arg user "$USERNAME" '[.comments[] | select(.type == "pr-level") | select(.author == $user)]'

# Confirm no inline comments were edited (all created_at should differ from updated_at only for the bot's own comments, not for original comments authored by others)
prc list $PR_NUM | jq '[.comments[] | select(.author != $user) | select(.created_at != .updated_at)]' --arg user "$USERNAME"
```

## Key Principles

**Bots — efficient, not conversational:**
- You have full codebase access — bots see only the diff
- False positives are common — verify every claim before acting
- Your judgment > bot suggestion when you have more context
- After replying, resolve the thread — bots don't continue conversations

**Humans — authority, dialogue, no AI clichés:**
- Treat reviewers as people whose perspective genuinely matters
- They may have domain knowledge or edge cases you don't
- When ambiguous, ask rather than assume
- Leave threads open — replies are invitations to keep talking, not closures
- Write like a real person: direct, specific, no filler

**Reply Conciseness:**
- 1-3 sentences maximum for humans, 1-2 for bots
- Start with substance — no opener filler
- Focus on what changed and why, or what question you're asking
- Never start with affirmations ("Good catch!", "Great point!", "Absolutely!")

**Example — human reply:**

❌ AI cliché:
"Good catch! You're absolutely right that this could be a problem. I've gone ahead and implemented your excellent suggestion in commit abc123. Let me know if there's anything else I should change!"

✅ Human:
"Fixed in abc123 — the null check was missing when the list is empty. Does that cover the case you had in mind?"

## Error Handling

**If command fails:**
- Check authentication: `gh auth status`
- Verify PR exists: `gh pr view`
- Check if comment was already deleted
- Verify you have write access to repo

**If reply appears in wrong place:**
- You likely used `gh pr comment` instead of the replies endpoint
- Delete the PR-level comment
- Use correct API endpoint with `/replies`

## Success Criteria

- [ ] All comments needing replies identified (excluding comments where Claude's reply is most recent)
- [ ] Each comment critically evaluated
- [ ] Code read for context on each
- [ ] Appropriate action taken (fix/defer/reject)
- [ ] **For fixes: Changes committed AND pushed BEFORE replying**
- [ ] **For fixes: Reply includes commit SHA**
- [ ] Direct reply posted to each comment (only if Claude's reply is NOT already the most recent)
- [ ] Replies are concise and substantive — no AI clichés in human replies
- [ ] Bot threads resolved after replying
- [ ] Human threads left open
- [ ] No PR-level comments added
- [ ] No original comments edited
