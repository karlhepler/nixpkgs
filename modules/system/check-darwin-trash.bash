#!/usr/bin/env bash
# check-darwin-trash.bash
# Regression guard: fails if any non-macOS trash mechanism is referenced in config source.
#
# Forbidden patterns:
#   - trash-cli       (freedesktop.org Nix package — routes to ~/.local/share/Trash)
#   - send2trash      (Python library — routes to freedesktop trash on Linux)
#   - .local/share/Trash  (hardcoded freedesktop trash path)
#   - XDG_DATA_HOME   (env-based freedesktop trash path construction)
#
# SELF-REFERENCE NOTE: This script contains the forbidden strings as search patterns.
# It is explicitly excluded from the search to avoid a false-positive match.
#
# Correct package: pkgs.darwin.trash (macOS-native ~/.Trash — visible in Finder)
# See: CLAUDE.md § macOS Trash CLI

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Patterns to search for (each matched separately for clear error messages)
readonly FORBIDDEN_PATTERNS=(
    'trash-cli'
    'send2trash'
    '\.local/share/Trash'
    'XDG_DATA_HOME.*[Tt]rash'
)

# This script itself — excluded to avoid self-reference false positive
readonly THIS_SCRIPT="${SCRIPT_DIR}/check-darwin-trash.bash"

found_violation=0

for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
    # Search modules/**/*.nix, modules/**/*.bash, modules/**/*.py, and flake.nix
    # Exclude: this script, *.md files, .scratchpad/, .git/
    matches=$(
        rg --color=never -l \
            --glob '*.nix' \
            --glob '*.bash' \
            --glob '*.py' \
            -e "${pattern}" \
            "${REPO_ROOT}/modules" \
            "${REPO_ROOT}/flake.nix" \
            2>/dev/null \
        | rg -v '\.md$' \
        | rg -v '/\.scratchpad/' \
        | rg -v '/\.git/' \
        | rg -v "^${THIS_SCRIPT}$" \
        || true
    )

    if [[ -n "${matches}" ]]; then
        echo "ERROR: FORBIDDEN trash mechanism detected."
        echo "Pattern '${pattern}' found in:"
        while IFS= read -r file; do
            echo "  ${file}"
            rg --color=never -n -e "${pattern}" "${file}" | sed 's/^/    /'
        done <<< "${matches}"
        echo ""
        echo "FORBIDDEN trash mechanism detected. Use pkgs.darwin.trash (macOS-native ~/.Trash) only. See CLAUDE.md macOS Trash CLI section."
        found_violation=1
    fi
done

if [[ "${found_violation}" -eq 0 ]]; then
    echo "OK: No forbidden trash mechanisms found."
    exit 0
else
    exit 1
fi
