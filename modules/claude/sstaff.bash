#!/usr/bin/env bash
set -euo pipefail

# Senior Staff Engineer CLI - Launch Claude Code with Senior Staff Engineer output style
#
# Temporal awareness (current date/time) is injected via the UserPromptSubmit
# hook on every user turn — no need to embed it in the system prompt here.

export KANBAN_AGENT=senior-staff-engineer
export CLAUDIT_ROLE=senior-staff-engineer
exec claude --permission-mode auto \
  --system-prompt-file ~/.claude/output-styles/senior-staff-engineer.md \
  "$@"
