#!/usr/bin/env bash
set -euo pipefail

# Senior Staff Engineer CLI - Launch Claude Code with Senior Staff Engineer output style
#
# Injects current date context to ensure the senior staff engineer has temporal awareness
# for evaluating dates, deadlines, and time-sensitive decisions.

# Get current date and time with timezone in unambiguous format
# Format: "Wednesday, 2026-02-12 14:32:45 PST"
current_date="$(date '+%A, %Y-%m-%d %H:%M:%S %Z')"

# Read the senior-staff-engineer output style content
senior_staff_engineer_content="$(cat ~/.claude/output-styles/senior-staff-engineer.md)"

# Inject date context at the beginning of the system prompt
system_prompt="Today's date: ${current_date}

${senior_staff_engineer_content}"

# Launch Claude Code with date-aware senior staff engineer output style
export KANBAN_AGENT=senior-staff-engineer
export CLAUDIT_ROLE=senior-staff-engineer
exec claude --system-prompt "$system_prompt" "$@"
