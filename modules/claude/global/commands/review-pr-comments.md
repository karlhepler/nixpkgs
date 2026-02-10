---
name: review-pr-comments
description: Review and respond to unresolved PR comments when user asks to "review PR comments", "reply to PR comments", "check PR feedback", or "address PR review"
version: 1.0
keep-coding-instructions: true
---

# Review Pull Request Comments

**Purpose:** Systematically review and respond to all unresolved PR comments that you haven't replied to yet.

## When to Use

Activate this skill when the user asks to:
- "Review PR comments"
- "Reply to PR comments"
- "Check PR feedback"
- "Address PR review"
- "Respond to reviewers"

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
- ✅ Be concise, positive, curious, thankful
- ✅ Think critically about bot suggestions
- ✅ Trust but verify human suggestions

## Workflow

### Phase 1: Fetch Comments Needing Replies

```bash
# Get PR info
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
PR_NUM=$(gh pr view --json number -q .number)
USERNAME=$(gh api user -q .login)

# Fetch all comments
gh api "repos/$REPO/pulls/$PR_NUM/comments" --paginate > /tmp/pr_comments.json

# Filter to comments that need replies from Claude
jq --arg user "$USERNAME" '
  # Get all top-level comments not by Claude
  [.[] | select(.in_reply_to_id == null) | select(.user.login == $user | not)] as $top_level |

  # Group all comments for thread analysis
  . as $all_comments |

  # For each top-level comment, check if we should reply
  $top_level[] |
  . as $comment |

  # Get all replies to this comment
  ($all_comments | map(select(.in_reply_to_id == $comment.id))) as $replies |

  # Determine if we should reply
  select(
    # Case 1: No replies at all -> should reply
    ($replies | length == 0) or

    # Case 2: Has replies, but most recent reply is NOT by Claude -> should reply
    (($replies | length > 0) and ($replies | sort_by(.created_at) | last | .user.login == $user | not))
  )
' /tmp/pr_comments.json > /tmp/unreplied_comments.json
```

### Phase 2: Evaluate Each Comment

For each comment that needs a reply:

**1. Read the comment:**
```bash
cat /tmp/unreplied_comments.json | jq -r '.[] |
  "ID: \(.id)\nAuthor: \(.user.login)\nPath: \(.path):\(.line // .original_position)\n\(.body)\n---"'
```

**2. Determine comment type:**
- Bot comment: `user.login` matches `*bot*` or `*[bot]*`
- Human comment: Everything else

**3. Read the code:**
- Use Read tool on `.path` at line `.line` or `.original_position`
- Get surrounding context (±10 lines)
- Understand what code is doing

**4. Critically evaluate:**

**For bot comments:**
- What is the bot claiming?
- Read the actual code - is the claim valid?
- Do you have context the bot lacks?
- Is this a false positive?
- What's the right action?

**For human comments:**
- What concern are they raising?
- Read the code - do you see the issue?
- What edge cases might they know about?
- Is there merit to their suggestion?
- How should you respond?

**5. Decide action:**
- **Fix:** Implement change, commit, push, reply with commit SHA
- **Defer:** Valid but out of scope, reply explaining why
- **Reject:** Not applicable, reply with reasoning
- **Discuss:** Unclear, ask clarifying question in reply

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
gh api --method POST \
  repos/$REPO/pulls/$PR_NUM/comments/COMMENT_ID/replies \
  -f body='<your concise reply>'
```

**Reply templates (ALWAYS include signature):**

**Fixed:**
```
Good catch! Fixed in COMMIT_SHA. The issue was [X] because [Y].

---
_💬 Written by [Claude Code](https://claude.ai/code)_
```

**Rejected (bot false positive):**
```
Thanks for flagging this. After checking [context the bot missed], this is actually correct because [reason].

---
_💬 Written by [Claude Code](https://claude.ai/code)_
```

**Rejected (human - explain reasoning):**
```
Thanks for the suggestion! I investigated and found [X]. I think [alternative approach] is better here because [reason]. Thoughts?

---
_💬 Written by [Claude Code](https://claude.ai/code)_
```

**Deferred:**
```
Great point! This is out of scope for this PR, but I've created issue #XYZ to track it.

---
_💬 Written by [Claude Code](https://claude.ai/code)_
```

**Discussing:**
```
Interesting observation. Can you clarify [specific question]? I see [X] but wondering about [Y].

---
_💬 Written by [Claude Code](https://claude.ai/code)_
```

### Phase 5: Verify

After replying to all comments:

1. Check GitHub PR page in browser
2. Verify all replies are threaded under original comments
3. Confirm no PR-level comments were added
4. Verify original comments weren't edited

## Key Principles

**Critical Thinking for Bots:**
- You have full codebase access - bots see only the diff
- Bots follow patterns - you understand intent
- False positives are common - verify every claim
- Your judgment > bot suggestion when you have more context

**Trust but Verify for Humans:**
- Humans have domain knowledge you might lack
- They might see edge cases you missed
- Take their concerns seriously
- But still verify by reading code
- Discuss respectfully if you disagree

**Reply Conciseness:**
- One or two sentences maximum
- Skip "thank you so much" - just "Thanks!"
- Skip "I really appreciate" - just state what you did
- Focus on substance: what changed and why
- Be positive but not effusive

**Example progression:**

❌ Too verbose:
"Thank you so much for catching this! You're absolutely right that this could be a problem. I really appreciate you taking the time to review this so thoroughly. I've gone ahead and implemented your excellent suggestion in commit abc123. Let me know if there's anything else I should change!"

✅ Just right:
"Good catch! Fixed in abc123. The issue was X because Y."

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
- [ ] Replies are concise and substantive
- [ ] No PR-level comments added
- [ ] No original comments edited
