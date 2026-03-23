#!/usr/bin/env bash
#
# kanban-permission-hook — PermissionRequest hook that auto-approves kanban commands
#
# DESCRIPTION:
#   Internal Claude Code hook script. Auto-approves any Bash tool call whose
#   command starts with "kanban", removing the need for interactive approval
#   prompts on every kanban invocation by background sub-agents.
#
# TRIGGER:
#   Invoked by Claude Code on every PermissionRequest event (before the user
#   is asked to approve a tool call).
#
# BEHAVIOR:
#   - Reads Claude Code PermissionRequest JSON from stdin
#   - If tool_name is "Bash" and command starts with "kanban": emits allow decision
#   - Otherwise: exits 0 silently (falls through to next hook or normal flow)
#   - Never blocks — always exits 0 (fails open on any parse error)
#
# INPUT (stdin):
#   Claude Code PermissionRequest JSON with at minimum:
#     { "tool_name": "Bash", "tool_input": { "command": "kanban ..." } }
#
# OUTPUT (stdout, when approving):
#   {"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
#
# CONFIGURATION:
#   Wired in modules/claude/default.nix under hooks.PermissionRequest.

set -euo pipefail

json=$(cat)

# Empty stdin — fail open
if [[ -z "${json}" ]]; then
  exit 0
fi

# Extract tool_name and command with a single jq call (tab-delimited)
extracted=$(printf '%s' "${json}" | jq -rj '
  (.tool_name // "") + "\t" +
  (.tool_input.command // "")
' 2>/dev/null) || exit 0

tool_name="${extracted%%$'\t'*}"
command="${extracted#*$'\t'}"

# Only act on Bash tool calls whose command starts with "kanban"
if [[ "${tool_name}" == "Bash" && "${command}" == kanban* ]]; then
  printf '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
fi

exit 0
