#!/usr/bin/env bash
set -euo pipefail

# Staff Engineer CLI - Launch Claude Code with Staff Engineer output style
#
# Temporal awareness (current date/time) is injected via the UserPromptSubmit
# hook on every user turn — no need to embed it in the system prompt here.

export KANBAN_AGENT=staff-engineer
export CLAUDIT_ROLE=staff-engineer
export CLAUDE_CODE_NO_FLICKER=1
# Pinned to CC 2.1.178: CC 2.1.179 serializes the Agent tool's run_in_background as a JSON
# string "true" instead of boolean true; CC strips the type-mismatched value before PreToolUse
# hooks run, so the kanban Agent-gate hook sees it missing and denies all delegations. 2.1.178
# emits the boolean correctly. Revert to bare `claude` once Anthropic ships a CC release that
# fixes this Agent-tool run_in_background regression.
exec "$HOME/.local/share/claude/versions/2.1.178" --permission-mode auto \
  --settings '{"skipAutoPermissionPrompt": true}' \
  --system-prompt-file ~/.claude/output-styles/staff-engineer.md \
  "$@"
