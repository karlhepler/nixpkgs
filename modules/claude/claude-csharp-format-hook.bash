#!/usr/bin/env bash

show_help() {
  echo "claude-csharp-format-hook - Internal Claude Code C# formatting hook"
  echo
  echo "DESCRIPTION:"
  echo "  Internal hook script called automatically by Claude Code."
  echo "  Should not be invoked manually by users."
  echo
  echo "PURPOSE:"
  echo "  Automatically formats C# files after Claude Code writes them."
  echo "  Uses dotnet-csharpier to apply consistent C# code formatting."
  echo
  echo "TRIGGER:"
  echo "  Automatically invoked by Claude Code after Write tool usage."
  echo "  Only processes files with .cs extension."
  echo
  echo "BEHAVIOR:"
  echo "  - Parses JSON input from stdin (Claude Code hook format)"
  echo "  - Extracts file_path from tool_input"
  echo "  - Formats C# files using dotnet-csharpier if available"
  echo "  - Suppresses output to avoid noise"
  echo "  - Always exits successfully to not block workflow"
  echo
  echo "CONFIGURATION:"
  echo "  Configured in modules/claude/default.nix as write hook."
}

# Parse arguments for help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

set -eou pipefail

# Read JSON from stdin
json=$(cat)

# Extract file path from JSON input using Python
file_path=$(echo "$json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    file_path = data.get('tool_input', {}).get('file_path', '')
    print(file_path)
except Exception:
    print('')
")

# Only process C# files
if [[ -n "$file_path" && "$file_path" == *.cs ]]; then
    # Check if dotnet-csharpier is available and the file exists
    if command -v dotnet-csharpier >/dev/null 2>&1 && [[ -f "$file_path" ]]; then
        # Run dotnet-csharpier on the file, suppress output to avoid noise
        dotnet-csharpier "$file_path" &>/dev/null || true
    fi
fi

# Always exit successfully to not block Claude's workflow
exit 0