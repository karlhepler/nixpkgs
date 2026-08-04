#!/usr/bin/env bash
set -euo pipefail

# Senior Staff Engineer CLI - Launch Claude Code with Senior Staff Engineer output style
#
# Temporal awareness (current date/time) is injected via the UserPromptSubmit
# hook on every user turn — no need to embed it in the system prompt here.
#
# Effort was previously pinned to `xhigh` per D14's step-up clause for
# "demanding coding and agentic work"
# (docs/v5-migration/A-anthropic-v5-guidance.md:492) — this coordinator
# session qualified under that clause. It is now pinned to `high` per an
# owner decision to lower the default. D16 separately calls for a fresh
# effort sweep rather than carrying settings over; that sweep was not run
# here — this is a stated rationale, not an empirical result. See
# .scratchpad/2-7-effort-assessment.md and D-implementation-plan.md Q8(C).

export KANBAN_AGENT=senior-staff-engineer
export CLAUDIT_ROLE=senior-staff-engineer
export CLAUDE_CODE_NO_FLICKER=1
exec claude --permission-mode auto \
  --model 'opus[1m]' \
  --effort high \
  --settings '{"skipAutoPermissionPrompt": true}' \
  --system-prompt-file ~/.claude/output-styles/senior-staff-engineer.md \
  "$@"
