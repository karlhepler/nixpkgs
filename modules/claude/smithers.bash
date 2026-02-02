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

# Create PROMPT.md with PR watching instructions
cat > PROMPT.md <<EOF
You are watching a pull request and ensuring it is completely ready to merge.

PR: $PR_URL

## Your Mission

Watch this PR continuously until it is **completely green and ready to merge**.

## Tasks

1. **Monitor ALL checks:**
   - Use \`gh pr checks\` to see check status
   - Ensure they all pass (green checkmarks)

2. **Handle check failures:**
   - If any check fails, investigate the failure
   - Fix the issue (spawn sub-agents for investigation/implementation)
   - Commit and push the fix
   - Wait for checks to re-run
   - If you cannot fix a failing check, STOP and notify me

3. **Handle bot comments:**
   - Find ALL bot comments (any user with [bot] in username)
   - Use \`gh api repos/:owner/:repo/issues/:number/comments\` to get PR comments
   - Use \`gh api repos/:owner/:repo/pulls/:number/comments\` to get inline comments
   - Use \`gh api repos/:owner/:repo/pulls/:number/reviews\` to get review comments
   - For each bot comment:
     - Critically evaluate if it needs addressing
     - Address the concern if necessary (make code changes, commit, push)
     - Reply directly to the comment using \`gh api\` (ALWAYS reply)
     - Skip comments where I (the user) already replied

4. **Fix merge conflicts:**
   - Check for merge conflicts using \`gh pr view\`
   - If conflicts exist, fix them
   - Commit and push the resolution

5. **Loop until complete:**
   - All checks pass (green)
   - All bot comments addressed
   - No merge conflicts
   - PR is ready to merge

6. **When done:**
   - Publish LOOP_COMPLETE to signal completion
   - Provide a summary of actions taken

## Important

- Use your Staff Engineer delegation patterns - spawn sub-agents for investigation and fixes
- Stay available to coordinate while sub-agents work
- Be thorough and obsessive about details (you're Smithers!)
EOF

# Run ralph with Staff Engineer hat and generated prompt
exec ralph run -a -c STAFF_ENGINEER_HAT_YAML --max-iterations 100 -P PROMPT.md
