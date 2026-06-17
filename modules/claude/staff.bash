#!/usr/bin/env bash
set -euo pipefail

# Staff Engineer CLI - Launch Claude Code with Staff Engineer output style
#
# Temporal awareness (current date/time) is injected via the UserPromptSubmit
# hook on every user turn — no need to embed it in the system prompt here.

export KANBAN_AGENT=staff-engineer
export CLAUDIT_ROLE=staff-engineer
export CLAUDE_CODE_NO_FLICKER=1
exec claude --permission-mode auto \
  --settings '{"skipAutoPermissionPrompt": true}' \
  --system-prompt-file ~/.claude/output-styles/staff-engineer.md \
  "$@"
