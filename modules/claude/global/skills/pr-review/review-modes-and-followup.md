---
name: review-modes-and-followup
description: Full flow for the /pr-review skill's two alternate invocation modes (re-review / straight-approval, restricted-output) and its post-review follow-through loop. Read by the /pr-review skill when a mode signal matches or a non-approving review is posted. Not intended for direct invocation.
user-invocable: false
---

# Alternate Modes and Follow-Through

Read this when SKILL.md § Alternate Review Modes matches a caller signal, or when SKILL.md § Follow-Through After a Non-Approving Review triggers. The triggers and the hard constraints are resident in SKILL.md; the flows are here.

## Re-Review / Straight-Approval Mode

**Trigger:** see SKILL.md § Alternate Review Modes — the signal words are `re-review` and `straight-approval`.

**In this mode, skip the full specialist review pass entirely.** The author has addressed prior feedback; the job is to confirm and help them land it, not to re-scrutinize the diff or surface a new round of findings. Opening a closed review loop with new findings is the failure mode to avoid.

**Re-review flow:**

1. Parse the PR number from `$ARGUMENTS` as normal.
2. Run the safety re-check: `gh pr view <pr> [--repo owner/repo] --json author,state,mergedAt,reviewDecision,reviews,latestReviews`.
3. **Abort conditions** (deliberate subset — a peer's COMMENTED does NOT block the straight approval; only CHANGES_REQUESTED by a non-author, non-bot human does):
   - `state != OPEN` or `mergedAt` non-null → nothing to do; exit cleanly.
   - `reviewDecision == APPROVED` AND at least one approving review is from a real human (not a bot/auto-approval account — apply the same three-rule bot-detection criteria used in Phase 5: login does NOT end in `[bot]`, `gh api users/<login>` returns HTTP 200, `type == "User"`) → already straight-approved by a human; exit cleanly (do NOT post a duplicate). A `reviewDecision == APPROVED` satisfied SOLELY by bot/auto-approval accounts does NOT trigger this abort.
   - Any non-author, non-bot human has `state == CHANGES_REQUESTED` in `reviews` → genuinely blocked by a peer; exit cleanly.
4. **If none of the abort conditions are true:** post a **straight approval** via `prr submit <pr> --event APPROVE` (add `--repo owner/repo` if cross-repo) with a brief, friendly body: `"Thanks for addressing the comments — looks good."`. No new findings. No new inline comments. No specialist delegation. No re-litigating.
5. Report the approval posted and exit. The follow-through loop is not needed — an APPROVE event is a terminal state.

**Do NOT:** run Phase 1–5. Do NOT spawn specialists. Do NOT generate findings. Do NOT write a `.scratchpad/review-<number>.json` with inline comments. The straight approval is the entire output.

## Restricted-Output Review Mode

**Trigger:** see SKILL.md § Alternate Review Modes — the signals are the `--restricted-output` flag and the phrase "restricted-output mode". § Caller Contract below specifies both precisely.

**What does NOT change in this mode:** Run the FULL normal internal review exactly as usual — Phase 1 through Phase 5 (worktree setup, PR context fetch, domain detection, parallel specialist delegation, aggregation) execute unchanged. Do not skip any specialist, do not shorten analysis, do not lower scrutiny. The only thing this mode restricts is what happens at the POST step (Phase 6).

**What changes — the POST step (Phase 6) is replaced entirely by this decision:**

After aggregation completes (end of Phase 5) and the FINAL PRE-POST CHECK (§ Phase 6) passes with no abort condition triggered, evaluate the aggregated verdict:

1. **CLEAN APPROVE** — every specialist returned LGTM (no blocking, no concern, no comment-level findings at all): submit an APPROVE review with an **empty body and zero inline comments**. This is the only case where anything gets written to GitHub in this mode:
   ```bash
   prr submit <pr-number> --event APPROVE --body ""
   ```
   Approve silently — no summary text, no "looks good" note, no follow-up notes folded in. Empty body, zero comments, APPROVE event only.

2. **NOT a clean approve** — any specialist returned a concern, a comment-level finding, or a blocking issue (anything that would normally produce an inline comment or a non-empty review body): **post NOTHING to the PR.** Do not call `prr submit`. Do not call `gh pr comment`. Do not write anything to GitHub. Instead, emit the verdict and a short summary back to the caller (see § Caller Contract) so the operator can handle it manually.

**HARD CONSTRAINT — the only permitted GitHub write in this mode is an empty APPROVE:**
- NEVER post inline comments in this mode, under any circumstance.
- NEVER post a COMMENTED or CHANGES_REQUESTED review in this mode, under any circumstance.
- If the aggregated findings contain anything beyond all-LGTM, the correct action is silence-plus-escalation, never a partial or watered-down post.

**No follow-up loop in this mode:** § Follow-Through Loop below does not apply — restricted-output mode never produces a non-approving GitHub review, so there are no comment threads to follow through on. A clean approve is terminal (same as any APPROVE). A non-clean escalation is also terminal from `/pr-review`'s perspective — the operator takes it from there.

### Caller Contract

**How the mode is triggered:** The caller (typically `pr-review-watcher`, but any caller may do this) signals restricted-output mode by either:
- Passing `--restricted-output` as a flag in `$ARGUMENTS` (e.g., `/pr-review 456 --restricted-output`), or
- Including the literal phrase "restricted-output mode" or "RESTRICTED-OUTPUT MODE" in the invocation brief text.

Either signal is sufficient and greppable — check for the flag or the phrase before Phase 1 begins, and set a mode flag for use at Phase 6.

**How `/pr-review` emits the escalation verdict/summary back to the caller:** When the case-2 (not-clean) path is taken, `/pr-review` reports its result to standard output in this exact format, then stops:

```
ESCALATE-<pr-number>: <verdict — LGTM/Concerns/Blocking counts> — <one-line summary of what was found>
```

Example: `ESCALATE-456: 1 concern, 1 blocking — swe-security flagged a missing auth check on the new endpoint; swe-backend flagged an N+1 query.`

When run under a `crew`-spawned session (the normal `pr-review-watcher` path), this printed line is what the caller reads via `crew read` to detect the escalation and route it to the operator. When the clean-approve case is taken, `/pr-review` prints `REVIEW-POSTED-<pr-number>` exactly as it does in normal mode — the caller's existing `REVIEW-POSTED-<pr>` detection logic (§ /pr-review Integration in `pr-review-watcher`) requires no change to recognize a silent approve.

## Follow-Through Loop

Entered only on the trigger stated in SKILL.md § Follow-Through After a Non-Approving Review, which also carries the guiding principle and the flag-file guard.

### Transition Into the Follow-Up Loop

After posting a COMMENT or CHANGES_REQUESTED review, schedule a follow-up check using `ScheduleWakeup` at a ~5-minute cadence. A foreground skill cannot busy-wait; use ScheduleWakeup to re-fire the follow-up check. One independent loop per PR — do not start a second loop if one is already running for this PR.

**Durable loop-dedup (flag file):** Because ScheduleWakeup spawns a fresh agent context where in-memory state does not persist, use a per-PR flag file to detect whether a follow-up loop is already running. This mirrors the `approval_watch` pattern in smithers.

- **File path:** `.scratchpad/review-<pr-number>-followup-running` (relative to the git repo root)
- **Check on entry:** `test -f .scratchpad/review-<pr-number>-followup-running` — if the flag exists, a loop is already active; do NOT schedule another wakeup.
- **Set when starting the loop:** `touch .scratchpad/review-<pr-number>-followup-running`
- **Clear when a stop condition is reached:** `rm -f .scratchpad/review-<pr-number>-followup-running`

Before scheduling the first wakeup, check for the flag. If it already exists, skip — a loop is in progress.

```bash
# Guard: skip if a follow-up loop is already running for this PR
test -f .scratchpad/review-<pr-number>-followup-running && exit 0

# Mark the loop as active (survives the ScheduleWakeup gap)
touch .scratchpad/review-<pr-number>-followup-running
```

Then schedule the first follow-up check:

```
ScheduleWakeup(
  delaySeconds=300,
  reason="Follow-up check for PR <pr-number> — waiting ~5 minutes before re-checking reply threads and new commits",
  prompt="Re-enter the follow-up loop for /pr-review on PR <pr-number>: check unresolved threads, check for new commits, approve if all concerns resolved, or schedule the next wakeup."
)
```

### On Each Wake

When the follow-up check fires:

1. **Re-check reply threads.** Pull the current state of all review comment threads on the PR:

   ```bash
   prc list <pr> --unresolved
   ```

   For each unresolved thread where a reply has arrived since the last check:

   - **If the author addressed the concern** (a fix was pushed or a satisfactory answer was given): VERIFY it genuinely resolves the issue AND the code still serves the author's stated intent. If both are true, resolve the thread — reply and resolve in two steps:
     ```bash
     prc reply <comment_id> '<brief acknowledgment>'
     prc resolve <thread_id>
     ```
     If more is needed, post a friendly, helpful reply explaining what's still outstanding.
   - **If waiting on the author:** just wait — do not post anything.

2. **Check for new commits.** Pull any new commits the author pushed since the last check:

   ```bash
   gh pr view <number> --json commits --jq '.commits[-3:]'
   ```

   If new commits are present, re-read the updated diff and assess whether outstanding concerns have been addressed in code:

   ```bash
   gh pr diff <number>
   ```

### Approving When All Concerns Are Resolved

When ALL previously raised concerns are resolved — threads resolved, code verified, no remaining outstanding issues — submit an APPROVE review:

```bash
prr submit <pr-number> --findings .scratchpad/review-<pr-number>-followup.json --event APPROVE
```

The follow-up findings JSON should have an empty `comments` array and a brief approval message in `body` (e.g., `"All concerns addressed — looks good to merge."`).

### Stop Conditions

Stop the follow-up loop only when the PR is **approved-by-us, merged, or closed**:

```bash
# Check current PR state
gh pr view <number> --json state,reviews --jq '{state: .state, reviews: [.reviews[] | {author: .author.login, state: .state}]}'
```

- `state` is `MERGED` or `CLOSED` → clear the flag file and stop immediately
- Our account appears in `reviews` with `state: APPROVED` → clear the flag file and stop immediately
- Otherwise → schedule the next ScheduleWakeup and continue the loop

When a stop condition is reached, clear the durable flag:

```bash
rm -f .scratchpad/review-<pr-number>-followup-running
```
