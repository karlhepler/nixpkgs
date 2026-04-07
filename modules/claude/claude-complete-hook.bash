#!/usr/bin/env bash

show_help() {
  echo "claude-complete-hook - Internal Claude Code completion hook"
  echo
  echo "DESCRIPTION:"
  echo "  Internal hook script called automatically by Claude Code."
  echo "  Should not be invoked manually by users."
  echo
  echo "PURPOSE:"
  echo "  Consumes Claude Code completion events without triggering any"
  echo "  notifications or tmux attention flags. Kanban state transition"
  echo "  notifications and tmux red highlights are handled exclusively by"
  echo "  claude-kanban-transition-hook.bash (notification = red tab)."
  echo
  echo "TRIGGER:"
  echo "  Automatically invoked by Claude Code on completion events:"
  echo "  - Stop (main task completion)"
  echo "  - SubagentStop (subagent task completion)"
  echo
  echo "BEHAVIOR:"
  echo "  - Consumes stdin (required by hook protocol)"
  echo "  - Does NOT send macOS notifications"
  echo "  - Does NOT set tmux @claude_attention (no notification = no red tab)"
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

# Consume stdin (required by hook protocol)
read -r -d '' _ < /dev/stdin 2>/dev/null || true
