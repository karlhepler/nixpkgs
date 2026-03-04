#!/usr/bin/env bash
# pre-commit hook: prevent sensitive files from being committed to nixpkgs
#
# Blocks commits that include overconfig.nix or user.nix, which contain
# personal data, secrets, and machine-specific configuration that must
# never be version controlled.

set -euo pipefail

sensitive_files=("overconfig.nix" "user.nix")
staged_files=$(git diff --cached --name-only)
blocked=()

for file in "${sensitive_files[@]}"; do
    if echo "$staged_files" | grep -qx "$file"; then
        blocked+=("$file")
    fi
done

if [[ ${#blocked[@]} -gt 0 ]]; then
    echo ""
    echo "ERROR: Commit blocked — sensitive file(s) staged:"
    echo ""
    for file in "${blocked[@]}"; do
        echo "  - $file"
    done
    echo ""
    echo "These files contain personal data and machine-specific secrets."
    echo "They must NEVER be committed to version control."
    echo ""
    echo "To unstage and proceed:"
    for file in "${blocked[@]}"; do
        echo "  git restore --staged $file"
    done
    echo ""
    exit 1
fi
