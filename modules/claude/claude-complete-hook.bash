#!/usr/bin/env bash

show_help() {
  echo "claude-complete-hook - Internal Claude Code completion hook"
  echo
  echo "DESCRIPTION:"
  echo "  Internal hook script called automatically by Claude Code."
  echo "  Should not be invoked manually by users."
  echo
  echo "PURPOSE:"
  echo "  Sets tmux window attention flags when Claude Code completes a task"
  echo "  or subagent finishes. Kanban state transition notifications are"
  echo "  handled by dedicated hooks (kanban-subagent-stop-hook.py and"
  echo "  claude-kanban-transition-hook.bash)."
  echo
  echo "TRIGGER:"
  echo "  Automatically invoked by Claude Code on completion events:"
  echo "  - Stop (main task completion)"
  echo "  - SubagentStop (subagent task completion)"
  echo
  echo "BEHAVIOR:"
  echo "  - Parses JSON input from stdin (Claude Code hook format)"
  echo "  - Sets tmux @claude_attention window option"
  echo "  - Does NOT send macOS notifications (handled by transition hooks)"
  echo
  echo "CONFIGURATION:"
  echo "  Configured in modules/claude/default.nix as completion hook."
}

# Parse arguments for help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -euo pipefail

# @COMMON_FUNCTIONS@ - Will be replaced by Nix at build time

# Consume stdin (required by hook protocol)
cat > /dev/null

# Set tmux attention flags only
set_tmux_attention
