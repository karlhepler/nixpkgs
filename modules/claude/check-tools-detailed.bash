#!/usr/bin/env bash
#
# check-tools-detailed — assert every tool documented in TOOLS-DETAILED.md is
# still shipped, using the generated TOOLS.md as the authority.
#
# WHY THIS EXISTS
#   TOOLS.md is regenerated on every activation from live package metadata
#   (modules/claude/generate-tools-md.nix, wired at modules/claude/default.nix).
#   TOOLS-DETAILED.md is hand-written. That asymmetry produced a real defect:
#   burns.py was deleted in ddc7255 (2026-05-18) and the generated TOOLS.md
#   dropped `burns` automatically and immediately, while the hand-written file
#   kept documenting it for over two months until a migration audit happened to
#   look. Nothing was watching. This is the thing that watches.
#
#   The generated file is the authority on purpose — a check that needed its own
#   hand-maintained list of live tools would be the same failure one level out.
#
# THE INVARIANT — ONE-DIRECTIONAL, DELIBERATELY
#   Every `## <tool>` heading in TOOLS-DETAILED.md must have a corresponding
#   `### <tool>` heading in the generated TOOLS.md.
#
#   Every documented tool must exist. NOT every tool must be documented.
#   TOOLS-DETAILED.md is a deep-dive companion for a subset of tools, not an
#   index; it cross-references TOOLS.md for the full list. `smithers-post` is a
#   real, registered shellapp that it deliberately omits. A bidirectional check
#   would fail on the very first run, and a check that fails on correct state
#   gets disabled rather than fixed. So the subset relation is asserted in one
#   direction only, and a shipped-but-undocumented tool is never an error.
#
# EXACT MATCHING, NEVER HEURISTIC
#   Heading text is compared with shell string equality: no case folding, no
#   substring matching, no fuzzy or semantic comparison. This check runs on the
#   deploy path, where a false positive does not block a documentation change —
#   it blocks EVERY configuration change until resolved. So a failure must
#   always be a real difference and never a heuristic's opinion. The only
#   normalisation is stripping trailing whitespace, which markdown itself
#   ignores in an ATX heading and which the generated side cannot contain.
#
#   Known limitation, accepted rather than papered over: headings are matched by
#   line prefix without tracking fenced code blocks, so a literal `## ` at the
#   start of a line inside a code fence would be read as a documented tool. The
#   failure message names the offending text verbatim, so that case diagnoses
#   itself in one step rather than requiring an investigation.
#
# USAGE
#   check-tools-detailed [DETAILED_PATH] [GENERATED_PATH]
#
#   Standalone, with no arguments — checks the repository source against the
#   currently deployed TOOLS.md:
#     bash modules/claude/check-tools-detailed.bash
#
#   The activation path (modules/claude/default.nix) passes both paths
#   explicitly, so the deploy gate runs against the TOOLS.md being built right
#   now rather than the one a previous activation left behind.
#
# EXIT CODES
#   0 — every documented tool is present in the generated TOOLS.md
#   1 — a documented tool is absent, or an input file is missing/unusable

set -euo pipefail

readonly default_detailed_path="$HOME/.config/nixpkgs/modules/claude/global/TOOLS-DETAILED.md"
readonly default_generated_path="$HOME/.claude/TOOLS.md"

detailed_path="${1:-$default_detailed_path}"
generated_path="${2:-$default_generated_path}"

die() {
    echo "check-tools-detailed: $*" >&2
    exit 1
}

# Strip a trailing whitespace run. Markdown ignores it in an ATX heading, so
# treating `## prc ` and `### prc` as the same heading is normalisation, not a
# heuristic — the comparison itself stays exact.
strip_trailing_whitespace() {
    local text="$1"
    printf '%s' "${text%"${text##*[![:space:]]}"}"
}

# Collect heading text by exact line prefix via `case` globbing — not regex.
# `### foo` does not match '## '* because its third character is `#`, not a
# space, so TOOLS-DETAILED.md's `### <subcommand>` headings are correctly
# ignored and only top-level `## <tool>` sections count as documented.
collect_headings() {
    local prefix="$1" file="$2" line
    while IFS= read -r line || [[ -n "$line" ]]; do
        case "$line" in
            "$prefix"*) strip_trailing_whitespace "${line#"$prefix"}"; printf '\n' ;;
        esac
    done < "$file"
}

[[ -f "$detailed_path" ]] || die "documented-tools file not found: $detailed_path"
[[ -f "$generated_path" ]] || die "generated-tools file not found: $generated_path"

documented=()
while IFS= read -r heading; do
    documented+=("$heading")
done < <(collect_headings '## ' "$detailed_path")

shipped=()
while IFS= read -r heading; do
    shipped+=("$heading")
done < <(collect_headings '### ' "$generated_path")

# A generated file with zero tool headings means we were handed the wrong file,
# not that every tool was retired at once. Say that, instead of reporting every
# documented section as stale — this is the check's own worst false-positive
# mode, so it gets its own diagnosis.
if [[ ${#shipped[@]} -eq 0 ]]; then
    die "no '### <tool>' headings found in $generated_path — that file is not a generated TOOLS.md; refusing to report every documented tool as retired"
fi

if [[ ${#documented[@]} -eq 0 ]]; then
    echo "check-tools-detailed: OK — $detailed_path documents no tools; nothing to verify."
    exit 0
fi

missing=()
for documented_tool in "${documented[@]}"; do
    found=0
    for shipped_tool in "${shipped[@]}"; do
        if [[ "$documented_tool" == "$shipped_tool" ]]; then
            found=1
            break
        fi
    done
    if [[ $found -eq 0 ]]; then
        missing+=("$documented_tool")
    fi
done

if [[ ${#missing[@]} -eq 0 ]]; then
    echo "check-tools-detailed: OK — all ${#documented[@]} documented tools are present in the generated TOOLS.md (${#shipped[@]} tools shipped; the check is one-directional, so shipped-but-undocumented tools are not an error)."
    exit 0
fi

{
    echo "check-tools-detailed: FAILED — ${#missing[@]} tool(s) documented in TOOLS-DETAILED.md are absent from the generated TOOLS.md."
    echo
    echo "  documented file: $detailed_path"
    echo "  generated file:  $generated_path"
    echo
    echo "Stale section(s):"
    for missing_tool in "${missing[@]}"; do
        echo "  ## $missing_tool    <- documented here, no '### $missing_tool' in the generated TOOLS.md"
    done
    echo
    echo "TOOLS.md is regenerated on every activation from live package metadata, so"
    echo "it is the authority on what this configuration actually ships. A tool"
    echo "documented above but missing there has been retired."
    echo
    echo "To fix, for each section listed above, either:"
    echo "  - delete that '## <tool>' section from modules/claude/global/TOOLS-DETAILED.md"
    echo "    because the tool is retired; or"
    echo "  - confirm the tool still ships — its shellapp is still registered in"
    echo "    modules/claude/default.nix — and make the '## <tool>' heading match its"
    echo "    '### <tool>' heading in TOOLS.md exactly."
    echo
    echo "This check is one-directional by design: a tool that ships without being"
    echo "documented here is fine and will never fail this check."
} >&2

exit 1
