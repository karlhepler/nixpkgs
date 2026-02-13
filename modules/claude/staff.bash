#!/usr/bin/env bash
set -euo pipefail

# Staff Engineer CLI - Launch Claude Code with Staff Engineer output style
#
# Injects current date context to ensure the staff engineer has temporal awareness
# for evaluating dates, deadlines, and time-sensitive decisions.

# Get current date and time with timezone in unambiguous format
# Format: "Wednesday, 2026-02-12 14:32:45 PST"
current_date="$(date '+%A, %Y-%m-%d %H:%M:%S %Z')"

# Read the staff-engineer output style content
staff_engineer_content="$(cat ~/.claude/output-styles/staff-engineer.md)"

# Inject date context at the beginning of the system prompt
system_prompt="Today's date: ${current_date}

${staff_engineer_content}"

# Launch Claude Code with date-aware staff engineer output style
exec claude --system-prompt "$system_prompt" "$@"
