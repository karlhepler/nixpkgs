#!/usr/bin/env bash
#
# check-output-style-sync — assert that every `SYNC:<id>`-delimited block is
# present in BOTH coordinator output styles and byte-identical between them.
#
# WHY THIS EXISTS
#   staff-engineer.md and senior-staff-engineer.md deliberately duplicate a
#   handful of shared rules. Keeping both files was a decision, not an accident
#   (docs/v5-migration/D-implementation-plan.md § Q5(B)); the defect was never
#   that the content was duplicated, it was that the duplication DRIFTED
#   UNDETECTED.
#
#   The concrete failure: senior-staff-engineer.md was missing three
#   STOP-condition exclusions that staff-engineer.md carried — in a review
#   SUPPRESSION path, the highest-risk prompt-only invariant in the corpus —
#   while the same file asserted its own synchronisation ("...are mirrored in
#   staff-engineer.md — keep both in sync if modifying either"). A prose note is
#   a reminder. This is the mechanism. It converts an invariant that has already
#   failed silently into one that fails loudly.
#
# THE INVARIANT — BIDIRECTIONAL, UNLIKE check-tools-detailed
#   For every id marked in either file:
#     * the id is marked in the OTHER file too, and
#     * the two extracted blocks are byte-identical.
#
#   Bidirectional is correct here and one-directional would be wrong: a shared
#   rule that exists in one coordinator prompt and not the other IS the drift.
#   That is the opposite of check-tools-detailed, where a shipped-but-
#   undocumented tool is legitimate.
#
# SCOPE — EXACTLY ONE MARKED SECTION, ON PURPOSE
#   Five sections carry identical titles across the two files, but they
#   legitimately differ by tier: the Staff copy is written as self-directives,
#   the Senior Staff copy as monitoring awareness. Marking all five would assert
#   byte-identity over content that is SUPPOSED to differ, and the first false
#   positive would discredit the check and get it disabled rather than fixed. So
#   only the block that actually drifted is marked. Add ids later, one at a
#   time, as real drift is found.
#
# EXACT MATCHING, NEVER HEURISTIC
#   Comparison is shell string equality over the exact bytes between the
#   markers. No case folding, no whitespace normalisation, no fuzzy or semantic
#   comparison, not even a trailing-whitespace strip. This check runs on the
#   deploy path, where a false positive does not block a prompt change — it
#   blocks EVERY configuration change until resolved. So a failure must always
#   be a real difference and never a heuristic's opinion.
#
# MARKERS MAY BE INLINE, AND MAY SPAN LINES
#   A marker pair may sit inside a markdown table cell, wrap a standalone
#   paragraph, or span several lines. Inline support is required, not
#   incidental: in staff-engineer.md the exclusions live inside a table cell,
#   and a markers-on-their-own-lines rule would have forced a restructuring of
#   that table just to make it checkable.
#
#   One deliberate restriction: at most ONE marked section may begin on a given
#   line. A second opening marker on the same line is refused with a named
#   error rather than silently dropped.
#
# ZERO MARKED SECTIONS IS A FAILURE, DELIBERATELY
#   This script, its markers, and its wiring in modules/claude/default.nix are
#   one atomic change. Reverting the markers while leaving the check wired would
#   leave the invariant unguarded, silently — the exact failure shape this
#   script exists to prevent. So "no marked sections" fails loudly and names the
#   remedy (unwire it in default.nix in the same commit) instead of passing
#   vacuously.
#
# NO EXTERNAL TOOLS — NOT EVEN diff
#   Pure bash: no rg, no awk, no jq, and no diff. Nothing to declare in
#   runtimeInputs, nothing that can go missing at activation time. The failure
#   message hand-rolls its own difference report — the offset where the copies
#   first diverge, the divergent tail from each side, and both copies in full —
#   which for a single delimited block is more legible than diff output anyway.
#
# PERFORMANCE — WHY THIS READS LINE BY LINE INSTEAD OF SLURPING THE FILE
#   These files are ~370-400 KB. Bash's pattern-based prefix/suffix removal is
#   pathological at that size. Measured on the 366 KB senior output style, one
#   single call:
#
#       [[ "$content" == *"$needle"* ]]     0.01 s
#       "${content%%"$needle"*}"           14.36 s
#       "${content#*"$needle"}"            37.39 s
#       "${content:100}"                    0.01 s
#
#   A whole-file-in-one-variable implementation of this check took 159 seconds
#   as a direct result. Reading line by line keeps every pattern operation on a
#   string of at most a few thousand characters, and the check finishes in well
#   under a second. That matters more than elegance here: this runs on the
#   deploy path, and a check that makes `hms` hang is strictly worse than one
#   that makes it fail. Do not reintroduce whole-file `${var#*...}` or
#   `${var%%...}` operations.
#
# USAGE
#   check-output-style-sync [FILE_A] [FILE_B]
#
#   Standalone, with no arguments — checks the repository sources in place, so
#   debugging never requires a full activation:
#     bash modules/claude/check-output-style-sync.bash
#
#   The activation path (modules/claude/default.nix) passes both paths
#   explicitly, so the deploy gate reads the files being deployed right now
#   rather than whatever a previous activation left behind.
#
# EXIT CODES
#   0 — every marked id is present in both files and byte-identical
#   1 — a marked id is missing from one side, two copies differ, no ids are
#       marked at all, a marker is malformed/duplicated/unterminated, or an
#       input file is missing

set -euo pipefail

readonly open_prefix='<!-- SYNC:'
readonly close_prefix='<!-- /SYNC:'
readonly marker_suffix=' -->'

readonly default_style_dir="$HOME/.config/nixpkgs/modules/claude/global/output-styles"
readonly default_file_a="$default_style_dir/staff-engineer.md"
readonly default_file_b="$default_style_dir/senior-staff-engineer.md"

file_a="${1:-$default_file_a}"
file_b="${2:-$default_file_b}"

die() {
    echo "check-output-style-sync: $*" >&2
    exit 1
}

# collect_blocks FILE
#   Populates the globals `collected_ids` (marked ids in document order) and
#   `collected_blocks` (id -> exact text between the marker pair).
declare -a collected_ids=()
declare -A collected_blocks=()

collect_blocks() {
    local file="$1"
    collected_ids=()
    collected_blocks=()

    local line segment rest id close buffer=''
    local current_id='' lineno=0 open_line=0 in_block=0 first_segment=0 block_done=0

    while IFS= read -r line || [[ -n "$line" ]]; do
        lineno=$((lineno + 1))

        if [[ $in_block -eq 0 ]]; then
            # The opening marker is looked for FIRST, because a single line may
            # legitimately carry a complete pair — that is exactly how the
            # exclusions are marked inside a markdown table cell. Only a closing
            # marker with no opening marker ahead of it on the same line is
            # stray.
            if [[ "$line" != *"$open_prefix"* ]]; then
                [[ "$line" != *"$close_prefix"* ]] \
                    || die "stray closing marker at $file:$lineno — no section is open here"
                continue
            fi
            [[ "${line%%"$open_prefix"*}" != *"$close_prefix"* ]] \
                || die "stray closing marker at $file:$lineno — it precedes the opening marker on the same line"

            # Safe on a single line: these files' longest line is a few thousand
            # characters, where pattern removal costs nothing.
            rest="${line#*"$open_prefix"}"
            [[ "$rest" == *"$marker_suffix"* ]] \
                || die "malformed opening marker at $file:$lineno — '$open_prefix' with no closing '$marker_suffix'"
            id="${rest%%"$marker_suffix"*}"

            # Reject anything that is not a plain identifier. Without this a
            # mistyped marker would swallow the rest of the line and be reported
            # as an unreadable id.
            [[ -n "$id" ]] \
                || die "empty section id at $file:$lineno — expected '${open_prefix}<id>${marker_suffix}'"
            [[ "$id" != *[!a-z0-9-]* ]] \
                || die "invalid section id at $file:$lineno: '$id' — ids may contain only lowercase letters, digits, and hyphens"
            [[ -z "${collected_blocks[$id]+set}" ]] \
                || die "section '$id' is marked more than once in $file (again at line $lineno) — ids must be unique per file"

            current_id="$id"
            open_line=$lineno
            segment="${rest#*"$marker_suffix"}"
            in_block=1
            first_segment=1
        else
            segment="$line"
            first_segment=0
        fi

        close="$close_prefix$current_id$marker_suffix"
        block_done=0
        if [[ "$segment" == *"$close"* ]]; then
            segment="${segment%%"$close"*}"
            block_done=1
        elif [[ "$segment" == *"$close_prefix"* ]]; then
            die "mismatched closing marker at $file:$lineno — section '$current_id' (opened at line $open_line) is still open"
        fi

        [[ "$segment" != *"$open_prefix"* ]] \
            || die "a second opening marker appears at $file:$lineno — at most one marked section may begin on a line"

        if [[ $first_segment -eq 1 ]]; then
            buffer="$segment"
        else
            buffer+=$'\n'"$segment"
        fi

        if [[ $block_done -eq 1 ]]; then
            collected_ids+=("$current_id")
            collected_blocks["$current_id"]="$buffer"
            in_block=0
            current_id=''
            buffer=''
        fi
    done < "$file"

    [[ $in_block -eq 0 ]] \
        || die "unterminated section '$current_id' opened at $file:$open_line — no '${close_prefix}${current_id}${marker_suffix}' found"
}

# Hand-rolled stand-in for `diff`, so the script keeps its zero-dependency
# property. Reports where the two copies first diverge and shows both in full;
# for one delimited block that is more useful than a line-oriented diff.
report_difference() {
    local id="$1" text_a="$2" text_b="$3" offset=0
    while [[ $offset -lt ${#text_a} && $offset -lt ${#text_b} \
             && "${text_a:offset:1}" == "${text_b:offset:1}" ]]; do
        offset=$((offset + 1))
    done

    echo "  section:  $id"
    echo "  diverges at character offset $offset (length ${#text_a} in A, ${#text_b} in B)"
    echo
    echo "  A from the divergence — $file_a:"
    echo "    ...${text_a:offset:160}"
    echo
    echo "  B from the divergence — $file_b:"
    echo "    ...${text_b:offset:160}"
    echo
    echo "  A in full — $file_a:"
    echo "    $text_a"
    echo
    echo "  B in full — $file_b:"
    echo "    $text_b"
}

[[ -f "$file_a" ]] || die "output style not found: $file_a"
[[ -f "$file_b" ]] || die "output style not found: $file_b"

declare -a ids_a=() ids_b=()
declare -A blocks_a=() blocks_b=()

collect_blocks "$file_a"
ids_a=("${collected_ids[@]}")
for id in "${ids_a[@]}"; do blocks_a["$id"]="${collected_blocks[$id]}"; done

collect_blocks "$file_b"
ids_b=("${collected_ids[@]}")
for id in "${ids_b[@]}"; do blocks_b["$id"]="${collected_blocks[$id]}"; done

if [[ ${#ids_a[@]} -eq 0 && ${#ids_b[@]} -eq 0 ]]; then
    {
        echo "check-output-style-sync: FAILED — no '${open_prefix}<id>${marker_suffix}' sections are marked in either output style."
        echo
        echo "  file A: $file_a"
        echo "  file B: $file_b"
        echo
        echo "This check is wired into the deploy path but has nothing to check, which"
        echo "leaves the shared coordinator rules unguarded without saying so. The markers,"
        echo "this script, and its wiring in modules/claude/default.nix are one atomic unit."
        echo
        echo "To fix, either:"
        echo "  - restore the marker pair around the shared section in both output styles; or"
        echo "  - if the mechanism is being retired deliberately, remove its invocation from"
        echo "    modules/claude/default.nix in the same commit that removes the markers."
    } >&2
    exit 1
fi

# Three parallel arrays rather than one delimiter-packed record: a file path can
# in principle contain any character, and a packed record would misparse it.
declare -a missing_ids=() missing_absent_from=() missing_present_in=()
for id in "${ids_a[@]}"; do
    if [[ -z "${blocks_b[$id]+set}" ]]; then
        missing_ids+=("$id")
        missing_absent_from+=("$file_b")
        missing_present_in+=("$file_a")
    fi
done
for id in "${ids_b[@]}"; do
    if [[ -z "${blocks_a[$id]+set}" ]]; then
        missing_ids+=("$id")
        missing_absent_from+=("$file_a")
        missing_present_in+=("$file_b")
    fi
done

if [[ ${#missing_ids[@]} -gt 0 ]]; then
    {
        echo "check-output-style-sync: FAILED — ${#missing_ids[@]} marked section(s) exist in only one output style."
        echo
        for i in "${!missing_ids[@]}"; do
            echo "  section '${missing_ids[i]}' is missing from ${missing_absent_from[i]}"
            echo "    (it is marked in ${missing_present_in[i]})"
        done
        echo
        echo "A shared rule that exists in one coordinator prompt and not the other is the"
        echo "drift this check exists to catch."
        echo
        echo "To fix, either add the matching '${open_prefix}<id>${marker_suffix}' … '${close_prefix}<id>${marker_suffix}' pair"
        echo "around the same content in the file that lacks it, or remove the marker pair"
        echo "from the file that has it if the section is no longer shared."
    } >&2
    exit 1
fi

declare -a drifted=()
for id in "${ids_a[@]}"; do
    if [[ "${blocks_a[$id]}" != "${blocks_b[$id]}" ]]; then
        drifted+=("$id")
    fi
done

if [[ ${#drifted[@]} -eq 0 ]]; then
    echo "check-output-style-sync: OK — ${#ids_a[@]} marked section(s) present in both output styles and byte-identical."
    exit 0
fi

{
    echo "check-output-style-sync: FAILED — ${#drifted[@]} marked section(s) have drifted between the two output styles."
    echo
    echo "  A: $file_a"
    echo "  B: $file_b"
    echo
    for id in "${drifted[@]}"; do
        report_difference "$id" "${blocks_a[$id]}" "${blocks_b[$id]}"
        echo
    done
    echo "These two blocks are deliberately duplicated and must stay byte-identical."
    echo "Comparison is exact — no whitespace or case normalisation — so this is a real"
    echo "difference, not a heuristic's opinion."
    echo
    echo "To fix, edit whichever copy is wrong so the text between the markers matches byte"
    echo "for byte. Do not change the marker syntax, and do not widen the markers to cover"
    echo "content that legitimately differs between the coordinator tiers."
} >&2

exit 1
