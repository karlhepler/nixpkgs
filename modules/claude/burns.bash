#!/usr/bin/env bash
# Burns: Run Ralph Orchestrator with Staff Engineer hat
# Usage:
#   burns "prompt string"    # Inline prompt (uses -p flag)
#   burns path/to/file.md    # Prompt from file (uses -P flag)

set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Error: burns requires one argument (prompt string or file path)"
  exit 1
fi

ARG="$1"

# Check if argument is a file path
if [ -f "$ARG" ]; then
  # It's a file - use -P flag
  exec ralph run -a -c STAFF_ENGINEER_HAT_YAML --max-iterations 100 -P "$ARG"
else
  # It's a prompt string - use -p flag
  exec ralph run -a -c STAFF_ENGINEER_HAT_YAML --max-iterations 100 -p "$ARG"
fi
