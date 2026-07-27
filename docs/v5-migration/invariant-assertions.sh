#!/usr/bin/env bash
#
# Stage 1 invariant tripwire — kanban card #2979.
#
# WHAT THIS IS. Twenty-eight `rg -q` assertions, each checking that one
# distinctive, load-bearing phrase from a workflow invariant is still present
# in one of the two always-injected Tier-1 files. Stages 1.4/1.5 of
# docs/v5-migration/D-implementation-plan.md will relocate/trim roughly 176
# lines out of these two files. This script is meant to be run BEFORE that
# edit (to prove the anchors are real) and AFTER it, unchanged, as the
# mechanical half of the Stage 1 validation gate (D-implementation-plan.md
# § Stage 1 validation gate, item 3).
#
# WHY THIS SCRIPT DOES NOT ABORT ON THE FIRST FAILING CHECK. A failing
# assertion must not abort the run — every assertion needs to execute so the
# summary reports the true pass/fail count, not just the first failure. (No
# fail-fast shell option is enabled at the top of this script for that
# reason.)
#
# TARGET FILES.
#   modules/claude/global/CLAUDE.md  (530 lines, "the global file")
#   CLAUDE.md                        (387 lines, project root, "the project file")
#
# ANCHOR-SELECTION REASONING — spot-checked for at least three assertions,
# reasoning recorded inline above each assertion below. The general test
# applied to every anchor: "would this still pass against a file where the
# invariant had been deleted but similar prose remained nearby?" If yes, the
# anchor was rejected and a more distinctive one was chosen instead.
#
#   Spot-check 1 (assertion 2, human-delegated-bypass sentence). A rewriter
#   softening "NEVER skip hooks" into vaguer language could still leave a
#   generic "ask the user first" sentence nearby. "Human-delegated bypass is
#   equally prohibited" survives that rewording risk because it names the
#   exact failure mode (routing the bypass through a different actor) that
#   this repository was burned by — no generic hook-skip rewrite produces
#   this specific five-word opening by accident.
#
#   Spot-check 2 (assertion 21, ripgrep encoding-flag footnote). A rewriter
#   trimming the rg/fd section for length could plausibly keep "use rg not
#   grep" and drop the `-E` footnote as a seemingly minor detail — this is
#   the whole reason the footnote is separately anchored rather than folded
#   into assertion 20. The anchor `rg -E\` means \`--encoding\`, not extended
#   regex` requires the *specific* misconception the footnote corrects to
#   still be spelled out; a shortened "rg uses regex by default" sentence
#   would not satisfy it.
#
#   Spot-check 3 (assertion 3, perm purge as user-only). Anchoring on the
#   literal string "perm purge" alone would still pass if the file listed
#   "perm purge" in some unrelated reference table with the user-only
#   constraint quietly dropped — a real risk, since § Reference Documentation
#   describes other perm subcommands nearby. Anchoring instead on "Claude
#   agents must NEVER call this" ties the assertion to the *prohibition*
#   itself, not merely the command's name, so a table-ification of this line
#   that drops the prohibition would correctly fail the check.
#
#   Spot-check 4 (assertion 28, macOS Trash mechanism). Anchoring on
#   "pkgs.trash-cli" alone would still pass if a rewrite kept the package
#   name but deleted the explanation of *why* it's wrong. Anchoring on the
#   mechanism sentence itself ("moves files to the freedesktop.org trash
#   directory") requires the causal explanation to survive, which is the
#   D13-protected content SG4 calls out by name in D-implementation-plan.md.
#
# RIPGREP NOTES FOR THIS SCRIPT.
#   - Every assertion uses `rg -q -- 'pattern' "$FILE"` or
#     `rg -qF -- 'pattern' "$FILE"`. The `--` guards every assertion against
#     an accidental leading-dash misparse, even though none of the chosen
#     anchors start with a dash by construction (each begins with a word).
#   - No `\|` alternation and no combined multi-invariant patterns anywhere.
#     Every invariant gets its own `rg -q` line so a failure names exactly
#     one thing.
#   - `-F` (fixed string) is used only where the anchor is pure literal text
#     with no benefit from regex; default (non -F) is used everywhere else.
#     No assertion mixes a backslash into a `-F` pattern.
#   - The one anchor containing an apostrophe (assertion 10, worktree
#     category 3) is built via bash string concatenation
#     ('...'"'"'...') rather than substituting a `.` wildcard for the
#     apostrophe, per the explicit pitfall in this card's instructions.

GLOBAL_FILE="modules/claude/global/CLAUDE.md"
PROJECT_FILE="CLAUDE.md"

PASS=0
FAIL=0
FAILED_NAMES=()

# ---------------------------------------------------------------------------
# 1. Never-skip-hooks clause.
# Anchor: the enforcement sentence immediately following the rule, rather
# than the rule's own heading words ("NEVER skip hooks"), which are generic
# enough that a softened rewrite could plausibly keep the heading while
# gutting its force. "Hooks are part of the contract" is the specific
# framing that makes the rule non-negotiable and is unlikely to survive a
# rewording that weakens the rule.
if rg -q -- 'Hooks are part of the contract' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: never-skip-hooks clause"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("never-skip-hooks clause")
  echo "FAIL: never-skip-hooks clause — pattern not found in $GLOBAL_FILE: 'Hooks are part of the contract'"
fi

# ---------------------------------------------------------------------------
# 2. Human-delegated-bypass sentence (separate from assertion 1 by design —
# this is the sentence the card names as "most likely to be lost in a
# rewrite"). Anchor reasoning: see Spot-check 1 above.
if rg -q -- 'Human-delegated bypass is equally prohibited' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: human-delegated-bypass sentence"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("human-delegated-bypass sentence")
  echo "FAIL: human-delegated-bypass sentence — pattern not found in $GLOBAL_FILE: 'Human-delegated bypass is equally prohibited'"
fi

# ---------------------------------------------------------------------------
# 3. `perm purge` as user-only. Anchor reasoning: see Spot-check 3 above —
# anchors on the prohibition itself, not just the command name.
if rg -q -- 'Claude agents must NEVER call this' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: perm purge as user-only"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("perm purge as user-only")
  echo "FAIL: perm purge as user-only — pattern not found in $GLOBAL_FILE: 'Claude agents must NEVER call this'"
fi

# ---------------------------------------------------------------------------
# 4-7. The four ask-first operations, by name, one assertion each so a
# failure names exactly which operation's guard disappeared. Each anchor
# includes the command's own preceding word (e.g. "git", "hms", "rm") so the
# pattern never begins with a dash, sidestepping the leading-dash pitfall
# entirely rather than working around it with -e/--.
if rg -q -- 'hms --purge' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: ask-first op named: hms --purge"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("ask-first op: hms --purge")
  echo "FAIL: ask-first op: hms --purge — pattern not found in $GLOBAL_FILE: 'hms --purge'"
fi

if rg -q -- 'git reset --hard' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: ask-first op named: git reset --hard"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("ask-first op: git reset --hard")
  echo "FAIL: ask-first op: git reset --hard — pattern not found in $GLOBAL_FILE: 'git reset --hard'"
fi

if rg -q -- 'git push --force' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: ask-first op named: git push --force"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("ask-first op: git push --force")
  echo "FAIL: ask-first op: git push --force — pattern not found in $GLOBAL_FILE: 'git push --force'"
fi

if rg -q -- 'rm -rf' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: ask-first op named: rm -rf"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("ask-first op: rm -rf")
  echo "FAIL: ask-first op: rm -rf — pattern not found in $GLOBAL_FILE: 'rm -rf'"
fi

# ---------------------------------------------------------------------------
# 8-11. Every enumerated worktree-confinement prohibited-target category,
# one assertion per bullet so a rewrite that drops or merges a category is
# caught by name rather than by an aggregate count.
if rg -q -- 'applies to the whole category, not any single tool' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: worktree category 1 (tool-manager configs, whole-category scope)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("worktree category 1: tool-manager configs")
  echo "FAIL: worktree category 1 — pattern not found in $GLOBAL_FILE: 'applies to the whole category, not any single tool'"
fi

# Fixed-string, not default regex: the pattern includes an unbalanced literal
# '(' which would otherwise need regex escaping. -F avoids that entirely.
if rg -qF -- 'Shell rc files (`~/.bashrc`' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: worktree category 2 (shell rc files)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("worktree category 2: shell rc files")
  echo "FAIL: worktree category 2 — literal string not found in $GLOBAL_FILE: 'Shell rc files (\`~/.bashrc\`'"
fi

# Apostrophe built via bash concatenation ('...'"'"'...'), not a '.' wildcard
# substitution, per the explicit pitfall warning for this card.
if rg -q -- 'that belongs to the user'"'"'s environment, not the repo' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: worktree category 3 (~/.config/ user environment)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("worktree category 3: ~/.config/ user environment")
  echo "FAIL: worktree category 3 — pattern not found in $GLOBAL_FILE: 'that belongs to the user'\''s environment, not the repo'"
fi

if rg -q -- 'Global or system-level package or tool installs' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: worktree category 4 (global/system-level installs)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("worktree category 4: global/system-level installs")
  echo "FAIL: worktree category 4 — pattern not found in $GLOBAL_FILE: 'Global or system-level package or tool installs'"
fi

# ---------------------------------------------------------------------------
# 12. The --draft requirement for PR creation.
if rg -q -- 'All pull requests MUST be created in draft mode' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: draft-PR requirement"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("draft-PR requirement")
  echo "FAIL: draft-PR requirement — pattern not found in $GLOBAL_FILE: 'All pull requests MUST be created in draft mode'"
fi

# ---------------------------------------------------------------------------
# 13-17. Every entry in the PR-description banned-phrasing list. Each is a
# fixed-string match (-F) since the anchors are literal example phrases with
# no benefit from regex, and none contain apostrophes.
if rg -qF -- 'Placeholders are now guarded against duplicates' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: banned-phrasing entry 1 (Placeholders are now guarded...)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("banned-phrasing entry 1")
  echo "FAIL: banned-phrasing entry 1 — literal string not found in $GLOBAL_FILE: 'Placeholders are now guarded against duplicates'"
fi

if rg -qF -- 'Eliminating the brief gap where no loading indicator was shown' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: banned-phrasing entry 2 (Eliminating the brief gap...)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("banned-phrasing entry 2")
  echo "FAIL: banned-phrasing entry 2 — literal string not found in $GLOBAL_FILE: 'Eliminating the brief gap where no loading indicator was shown'"
fi

if rg -qF -- 'Now correctly handles X' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: banned-phrasing entry 3 (Now correctly handles X)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("banned-phrasing entry 3")
  echo "FAIL: banned-phrasing entry 3 — literal string not found in $GLOBAL_FILE: 'Now correctly handles X'"
fi

if rg -qF -- 'No longer fails when Y' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: banned-phrasing entry 4 (No longer fails when Y)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("banned-phrasing entry 4")
  echo "FAIL: banned-phrasing entry 4 — literal string not found in $GLOBAL_FILE: 'No longer fails when Y'"
fi

if rg -qF -- 'Updated to support Z' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: banned-phrasing entry 5 (Updated to support Z)"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("banned-phrasing entry 5")
  echo "FAIL: banned-phrasing entry 5 — literal string not found in $GLOBAL_FILE: 'Updated to support Z'"
fi

# ---------------------------------------------------------------------------
# 18. The karlhepler/ branch-name prefix requirement.
if rg -q -- 'MUST use `karlhepler/` prefix' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: karlhepler/ branch prefix requirement"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("karlhepler/ branch prefix requirement")
  echo "FAIL: karlhepler/ branch prefix requirement — pattern not found in $GLOBAL_FILE: 'MUST use \`karlhepler/\` prefix'"
fi

# ---------------------------------------------------------------------------
# 19. GitHub Actions SHA-pinning requirement.
if rg -q -- 'MUST be pinned to commit SHA with version comment' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: GitHub Actions SHA-pinning requirement"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("GitHub Actions SHA-pinning requirement")
  echo "FAIL: GitHub Actions SHA-pinning requirement — pattern not found in $GLOBAL_FILE: 'MUST be pinned to commit SHA with version comment'"
fi

# ---------------------------------------------------------------------------
# 20. rg-not-grep and fd-not-find (kept as one combined assertion, matching
# how the card's own Stage 1 gate item 3 lists this pair as a single bullet
# rather than as two independently-tracked invariants).
if rg -q -- 'Use `rg` and `fd` respectively' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: rg-not-grep and fd-not-find"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("rg-not-grep and fd-not-find")
  echo "FAIL: rg-not-grep and fd-not-find — pattern not found in $GLOBAL_FILE: 'Use \`rg\` and \`fd\` respectively'"
fi

# ---------------------------------------------------------------------------
# 21. The ripgrep -E encoding-flag footnote. Anchor reasoning: see
# Spot-check 2 above — anchors on the specific misconception corrected, not
# on the generic "use rg not grep" guidance already covered by assertion 20.
if rg -q -- 'rg -E` means `--encoding`, not extended regex' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: ripgrep -E encoding-flag footnote"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("ripgrep -E encoding-flag footnote")
  echo "FAIL: ripgrep -E encoding-flag footnote — pattern not found in $GLOBAL_FILE: 'rg -E\` means \`--encoding\`, not extended regex'"
fi

# ---------------------------------------------------------------------------
# 22. One-command-per-Bash-call.
if rg -q -- 'Do NOT chain multiple logical operations with `&&` in a single Bash tool call' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: one-command-per-Bash-call"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("one-command-per-Bash-call")
  echo "FAIL: one-command-per-Bash-call — pattern not found in $GLOBAL_FILE: 'Do NOT chain multiple logical operations with \`&&\` in a single Bash tool call'"
fi

# ---------------------------------------------------------------------------
# 23. The nested-shell (sh -c) prohibition.
if rg -q -- 'wrap commands in `sh -c' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: nested-shell (sh -c) prohibition"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("nested-shell (sh -c) prohibition")
  echo "FAIL: nested-shell (sh -c) prohibition — pattern not found in $GLOBAL_FILE: 'wrap commands in \`sh -c'"
fi

# ---------------------------------------------------------------------------
# 24. The Homebrew prohibition.
if rg -q -- 'Homebrew is FORBIDDEN' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: Homebrew prohibition"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("Homebrew prohibition")
  echo "FAIL: Homebrew prohibition — pattern not found in $GLOBAL_FILE: 'Homebrew is FORBIDDEN'"
fi

# ---------------------------------------------------------------------------
# 25. One-task-one-deliverable.
if rg -q -- 'One task = one deliverable' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: one-task-one-deliverable"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("one-task-one-deliverable")
  echo "FAIL: one-task-one-deliverable — pattern not found in $GLOBAL_FILE: 'One task = one deliverable'"
fi

# ---------------------------------------------------------------------------
# 26. The LLM-specific abstraction trap.
if rg -q -- 'DO NOT default to building abstractions for hypothetical future use cases' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: LLM-specific abstraction trap"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("LLM-specific abstraction trap")
  echo "FAIL: LLM-specific abstraction trap — pattern not found in $GLOBAL_FILE: 'DO NOT default to building abstractions for hypothetical future use cases'"
fi

# ---------------------------------------------------------------------------
# 27. The rule of three.
if rg -q -- 'wait for 3\+ repetitions of genuinely-same logic before abstracting' "$GLOBAL_FILE"; then
  PASS=$((PASS+1)); echo "PASS: rule of three"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("rule of three")
  echo "FAIL: rule of three — pattern not found in $GLOBAL_FILE: 'wait for 3+ repetitions of genuinely-same logic before abstracting'"
fi

# ---------------------------------------------------------------------------
# 28. The macOS Trash mechanism sentence (project-root file — the only
# assertion in this script targeting $PROJECT_FILE rather than $GLOBAL_FILE).
# Anchor reasoning: see Spot-check 4 above.
if rg -qF -- 'moves files to the freedesktop.org trash directory' "$PROJECT_FILE"; then
  PASS=$((PASS+1)); echo "PASS: macOS Trash mechanism sentence"
else
  FAIL=$((FAIL+1)); FAILED_NAMES+=("macOS Trash mechanism sentence")
  echo "FAIL: macOS Trash mechanism sentence — literal string not found in $PROJECT_FILE: 'moves files to the freedesktop.org trash directory'"
fi

# ---------------------------------------------------------------------------
TOTAL=$((PASS+FAIL))
echo ""
echo "Summary: $PASS passed, $FAIL failed, $TOTAL total."

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "Failed invariants:"
  for name in "${FAILED_NAMES[@]}"; do
    echo "  - $name"
  done
  exit 1
fi

exit 0
