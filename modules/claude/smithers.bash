#!/usr/bin/env bash
# Smithers: Autonomous PR watcher ensuring checks pass and bot comments addressed
# Usage:
#   smithers          # Infer PR from current branch
#   smithers 123      # Use PR #123
#   smithers <url>    # Use specific PR URL

set -euo pipefail

# Parse optional PR argument
if [ $# -eq 0 ]; then
  # No argument: infer PR from current branch
  PR_URL=$(gh pr view --json url --jq .url 2>/dev/null || true)
  if [ -z "$PR_URL" ]; then
    echo "Error: No PR found for current branch. Please provide a PR number or URL."
    exit 1
  fi
else
  # Argument provided: could be PR number or URL
  ARG="$1"
  if [[ "$ARG" =~ ^[0-9]+$ ]]; then
    # It's a PR number
    PR_URL=$(gh pr view "$ARG" --json url --jq .url 2>/dev/null || true)
    if [ -z "$PR_URL" ]; then
      echo "Error: Could not find PR #$ARG"
      exit 1
    fi
  elif [[ "$ARG" =~ ^https?:// ]]; then
    # It's already a URL
    PR_URL="$ARG"
  else
    echo "Error: Invalid PR argument. Provide a PR number or URL."
    exit 1
  fi
fi

# Create temporary prompt file (will be auto-cleaned by OS)
PROMPT_FILE=$(mktemp /tmp/smithers-prompt.XXXXXX.md)
trap 'rm -f "$PROMPT_FILE"' EXIT

cat > "$PROMPT_FILE" <<EOF
You are watching a pull request and ensuring it is completely ready to merge.

PR: $PR_URL

## Your Mission

Watch this PR continuously until it is **completely green and ready to merge**.

## Tasks

1. **Monitor ALL checks - CONTINUOUS POLLING:**
   - Use \`gh pr checks\` to see check status
   - **CRITICAL:** Wait for ALL checks to reach terminal states:
     - Terminal states: pass, fail, skipping, cancelled
     - Non-terminal states: pending, running, queued, in_progress
   - **DO NOT proceed** while ANY check is in a non-terminal state
   - Poll every 30-60 seconds until all checks are terminal
   - Only consider the PR ready when you see ONLY green checkmarks (no yellow circles)

2. **Handle check failures:**
   - If any check fails (not skipped/cancelled), investigate the failure
   - For cancelled checks (like claude-review):
     - Check if it's expected/normal (some checks cancel when superseded)
     - If it's blocking, investigate why it was cancelled
   - Fix the issue (spawn sub-agents for investigation/implementation)
   - Commit and push the fix
   - **Wait for checks to re-run and complete** (back to step 1)
   - If you cannot fix a failing check, STOP and notify the user

3. **Handle bot comments:**
   - Find ALL bot comments (any user with [bot] in username)
   - Use \`gh api repos/:owner/:repo/issues/:number/comments\` to get PR comments
   - Use \`gh api repos/:owner/:repo/pulls/:number/comments\` to get inline code review comments
   - Use \`gh api repos/:owner/:repo/pulls/:number/reviews\` to get review comments
   - For each bot comment:
     - Check if there are already replies in the thread (look at full thread, not just the first comment)
     - If user already replied, skip it
     - If no replies OR only bot replies, critically evaluate if it needs addressing
     - Informational bots (linear[bot] linkbacks, currents-bot test summaries) usually don't need replies
     - Actionable bots (security warnings, linter feedback, failed test analysis) need addressing
     - If addressing: make code changes, commit, push, THEN reply to the comment thread
     - Use \`gh api\` to reply (NOT \`gh pr comment\` which doesn't thread)
     - **After replying: if the comment is fully addressed, resolve the thread** using \`gh pr review --comment-body "" --resolve\` or the appropriate API endpoint

4. **Fix merge conflicts:**
   - Check for merge conflicts using \`gh pr view\`
   - If conflicts exist, fix them
   - Commit and push the resolution
   - Wait for checks to re-run (back to step 1)

5. **Loop until complete - STRICT VERIFICATION:**
   - **All checks in terminal states** (no pending/running/queued)
   - **All required checks pass** (green checkmarks only)
   - **All actionable bot comments addressed** (or confirmed as informational-only)
   - **No merge conflicts**
   - PR is ready to merge

6. **Before emitting LOOP_COMPLETE:**
   - **MANDATORY FINAL VERIFICATION:**
     - Run \`gh pr checks\` one final time
     - Verify ZERO checks in non-terminal states
     - Verify all required checks show "pass"
     - List any failed/cancelled checks and confirm they're non-blocking
   - Only emit LOOP_COMPLETE after this final verification passes
   - Provide a summary of actions taken

## Important

- Use your Staff Engineer delegation patterns - spawn sub-agents for investigation and fixes
- Stay available to coordinate while sub-agents work
- Be thorough and obsessive about details (you're Smithers!)
- **NEVER declare completion while checks are still running** (yellow circles = not done)
- When in doubt, wait longer and poll again
EOF

# Run ralph with Staff Engineer hat and generated prompt
exec ralph run -a -c STAFF_ENGINEER_HAT_YAML --max-iterations 100 -P "$PROMPT_FILE"
