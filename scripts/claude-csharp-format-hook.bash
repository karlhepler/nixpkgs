#!/usr/bin/env bash
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
    # Check if csharpier is available and the file exists
    if command -v csharpier >/dev/null 2>&1 && [[ -f "$file_path" ]]; then
        # Run csharpier on the file, suppress output to avoid noise
        csharpier "$file_path" &>/dev/null || true
    fi
fi

# Always exit successfully to not block Claude's workflow
exit 0