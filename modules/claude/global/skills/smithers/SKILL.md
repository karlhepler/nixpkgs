---
name: smithers
description: >
  Watch a GitHub PR for CI failures and bot comments. Polls on a 1-minute
  cadence via ScheduleWakeup, delegates fixes to specialist agents via the
  Agent tool, and merges on full satisfaction — approved, green, no unresolved
  comments. After posting to Slack for reviewer attention, switches to a slow
  approval-watch phase (~10-minute pulse) that detects approval, late bot
  comments, and late CI failures automatically — merging the PR once full
  satisfaction is reached. Does NOT arm auto-merge as a forward-looking action
  — merges via explicit action on detection only. Invoke as /smithers (infers
  PR from current branch) or /smithers <PR> (explicit PR number or URL).
  Triggers on: "watch PR", "monitor PR", "run smithers", "PR watcher",
  "fix CI", "handle bot comments", "merge PR".
---

# /smithers — PR Watch Skill

You are the Smithers PR watcher running inside a staff engineer session. Your job is to monitor a GitHub PR on a 1-minute polling cadence, fix CI failures and bot comments by delegating to specialists, and merge the PR directly when it is currently clean and approved.

**You run one iteration per invocation.** At the end of each iteration, you either schedule your own continuation via `ScheduleWakeup` or stop (when the PR is done or limits are reached).

## ARGUMENT PARSING

Parse `$ARGUMENTS` on first call:
- Empty → infer PR via `gh pr view --json url --jq .url`
- Numeric string (e.g. `123`) → fetch URL via `gh pr view 123 --json url --jq .url`
- URL string → use directly
- Optional `webhook=<url>` token — a full Slack incoming-webhook URL, may appear alongside the PR argument in either order (e.g. `123 webhook=https://hooks.slack.com/services/...` or `webhook=https://hooks.slack.com/services/... 123`). Strip this token before parsing the PR argument itself. When present, store it as `webhook_override` for this invocation (see § Slack Webhook Override, part of § SLACK POSTING). When absent, `webhook_override` is unset and behavior is unchanged from before this feature existed.

On error (PR not found, no branch tracking): print a clear error message and stop (do not schedule wakeup).

## STATE

Most state lives in conversation history. Track these values mentally across iterations:

- `cycle` — iteration counter, starts at 1
- `fix_count` — number of times you have delegated fix work to a specialist
- `stagnation_count` — consecutive cycles where HEAD did not advance after a fix delegation
- `pre_sha` — HEAD commit SHA captured before delegating fix work
- `max_cycles` — 10 (hard limit on total iterations)
- `max_ralph_invocations` — 4 (hard limit on specialist delegations)
- `approval_watch_cycle` — iteration counter within the approval-watch phase, starts at 0 (see § Approval-Watch Phase). **In-memory only**: a session restart resets the expiry clock to 0, extending the effective watch window. A restart resets the expiry window. This is accepted behavior — the 24h bound is a within-session guarantee only.
- `stall_check_name` — name of the check currently believed to be the sole pending check across consecutive fast-cycle polls (see Step 2a: Soft-stall detector); `null` when no such streak is active. In-memory, recalled the same way as `stagnation_count`.
- `stall_cycle_count` — consecutive fast-cycle polls that `stall_check_name` has held the sole-pending position.
- `stall_warned` — whether the one-time soft-stall warning has already fired for the current streak.

**`clean_confirmed` — durable flag file (NOT in-memory):** This flag MUST survive the ScheduleWakeup gap, which spawns a fresh agent context where in-memory variables do not persist. It is stored as a file:

- **File path:** `.smithers/clean_confirmed` (relative to the git repo root)
- **Set:** `touch "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"` (first no-work invocation, Step 7)
- **Test:** `test -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"` (subsequent invocations, Step 7)
- **Clear:** `rm -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"` (after Step 7a completes OR on any abort/error in Step 7a)
- **Init:** On first invocation, if the file does not exist, treat as false. The `.smithers/` directory is auto-created by smithers on first need (see Step 7) if it does not exist — it is a state-only directory holding transient flag files, with no application code or tracked content. Smithers does NOT modify the host repo's `.gitignore`. The user is responsible for ensuring `.smithers/` is ignored globally via their git config (typically by appending `.smithers/` to `~/.config/git/ignore`, or to the file referenced by `git config --global core.excludesfile` if configured). Setup is a one-time host-machine action — ideally managed via dotfiles or nixpkgs (e.g., the `programs.git.ignores` list in home-manager) — not by smithers at runtime. **Users of THIS nixpkgs configuration:** the setup is already handled — `.smithers` is included in `programs.git.ignores` (see `modules/git/default.nix`). Just run `hms` to deploy the global ignore; nothing else is required.

On first invocation all counters are at their initial values. On ScheduleWakeup continuations, recall counter values from the conversation context and test the `clean_confirmed` flag file.

**`slack_posted` — durable flag file (NOT in-memory):** This flag prevents duplicate Slack notifications when smithers runs multiple cycles on the same clean PR (e.g., user re-invokes the watcher on a PR that was already posted to Slack). It is stored as a file:

- **File path:** `.smithers/slack_posted` (relative to the git repo root)
- **Set:** `touch "$(git rev-parse --show-toplevel)/.smithers/slack_posted"` (after `smithers-post` returns successfully, in Step 7a)
- **Test:** `test -f "$(git rev-parse --show-toplevel)/.smithers/slack_posted"` (before invoking `smithers-post` in Step 7a)
- **Clear:** Not cleared by smithers — persists across watcher runs. The user clears it manually if a re-post is desired.

**`approval_watch` — durable flag file (NOT in-memory):** This flag marks that smithers has entered the approval-watch phase on a given PR. It must survive the ScheduleWakeup gap so fresh agent contexts know to use the slow-pulse cadence.

- **File path:** `.smithers/approval_watch` (relative to the git repo root)
- **Set:** `touch "$(git rev-parse --show-toplevel)/.smithers/approval_watch"` (when entering the approval-watch phase after the Slack post, in Step 7a)
- **Test:** `test -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"` (Step 7a entry — determines phase)
- **Clear:** `rm -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"` (when exiting the approval-watch phase — on merge, CHANGES_REQUESTED surface, external merge/close, expiry, or re-entering the fix cycle)

**`webhook_override` — per-invocation override, NOT a durable flag file:** Set only when the `webhook=<url>` token is present in `$ARGUMENTS` (see § ARGUMENT PARSING). Unlike `clean_confirmed`/`slack_posted`/`approval_watch`, this is never written to a file — it is carried the same way the PR argument itself is carried: re-supplied as literal text in every `ScheduleWakeup` `prompt` field, and re-parsed by ARGUMENT PARSING on the fresh invocation that follows the wakeup. Every `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override) in this skill becomes `prompt: "Continue /smithers <PR_URL> webhook=<url>"` when `webhook_override` is active for the current PR — this is mandatory on EVERY wakeup in the session (the initial fast cycle, approval-watch entry, and every approval-watch pulse), not just the first one, or the override silently drops on the next wakeup. See § Slack Webhook Override (part of § SLACK POSTING) for the full passthrough contract.

## LOOP BODY

Each iteration executes steps 1–15 in order. Any step may terminate early by scheduling a wakeup or stopping without scheduling. **Exception — approval-watch invocations:** After Step 1 (PR state check), if the `approval_watch` flag file exists, smithers branches to the approval-watch pulse logic and skips Steps 2–15 entirely (see § Approval-Watch Phase).

---

### Step 1: Check if PR is already closed

Run:
```
gh pr view <PR> --json state,headRefName,baseRefName,title,isDraft
```

If `state == "MERGED"` or `state == "CLOSED"`: send a macOS notification (`osascript -e 'display notification "PR <N> is <state>" with title "Smithers"'`), print a summary, and **stop** (no ScheduleWakeup).

---

### Step 2: Get CI check status

Run:
```
gh pr checks <PR> --json name,state,bucket,link
```

On error (non-zero exit): log a warning (`Warning: gh pr checks failed — skipping cycle`). Update cycle tally in the conversation narrative (e.g., `Cycle <N> of <max_cycles> — gh API error; will retry on next wakeup.`) before scheduling. ScheduleWakeup with `delaySeconds: 60`, `reason: "gh pr checks API error — retrying after 1 minute"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override).

Parse the JSON array. Each check has: `name`, `state`, `bucket`, `link`.

Bucket values: `pass`, `fail`, `pending`, `skipping`, `cancel`.

Compute:
- `all_terminal` — all checks have bucket in `{pass, fail, skipping, cancel}` (i.e., no `pending` buckets)
- `fail_fast` — any check has bucket `fail` OR state in `{failure, timed_out, action_required, startup_failure}`
- `failed_checks` — list of checks where bucket == `fail`

No checks returned → treat as `([], all_terminal=true, fail_fast=false)`.

---

#### Step 2a: Soft-stall detector (observability only)

**Runs every fast-cycle poll, regardless of which Step 6 branch fires later in this same iteration.** This is purely an observability signal layered on top of Step 2's check data — it does not change which branch Step 6 takes, and it never alters the fast-cycle cadence.

Track, across consecutive fast-cycle polls, whether the SAME single check is the sole pending check — `bucket == "pending"` — while every other check on the run has reached a terminal bucket (`pass`, `fail`, `skipping`, `cancel`). These three values are in-memory, recalled across `ScheduleWakeup` continuations the same way `stagnation_count` is (see § STATE):

- `stall_check_name` — name of the check currently believed to be the sole pending check (`null` if none)
- `stall_cycle_count` — consecutive fast-cycle polls this check has held that position
- `stall_warned` — whether the one-time warning has already fired for the current streak

From the Step 2 check list, compute `pending_checks` = the checks with `bucket == "pending"`:

- **Exactly one pending check, same name as `stall_check_name`:** increment `stall_cycle_count`.
- **Exactly one pending check, a different name (including the first time this condition holds):** set `stall_check_name` to that check's name, reset `stall_cycle_count = 1`, reset `stall_warned = false`.
- **Zero pending checks, or more than one still pending:** reset `stall_check_name = null`, `stall_cycle_count = 0`, `stall_warned = false`. Only ever trigger the warning below when exactly one check is the sole pending check — never when multiple checks are still pending.

**When `stall_cycle_count >= 5` (≈5 minutes at the 60s fast-cycle cadence) AND `NOT stall_warned`:** emit a ONE-TIME soft warning naming the check and its run URL (the `link` field from the Step 2 JSON):

1. Log: `"Soft-stall detector: <stall_check_name> has been the sole pending check for <stall_cycle_count> consecutive cycles — <link>"`.
2. Send macOS notification: `osascript -e 'display notification "PR <N>: <stall_check_name> is the sole pending check after <stall_cycle_count> cycles" with title "Smithers"'`. Do not invent a new posting path for this — this skill's Slack posting is reserved for the existing Step 7a / merge-time triggers (see § SLACK POSTING); the macOS notification is the surfacing mechanism here, same as every other warning in this skill.
3. Set `stall_warned = true` so the warning does not repeat on subsequent cycles for the same still-pending check.

This soft-stall detector is purely observability and is **NOT a stop condition** — smithers continues polling normally afterward, unaffected, at the same 60-second fast-cycle cadence. It is independent of, and must not be confused with, the stagnation-STOP in Step 13 (HEAD not advancing after a fix delegation), which remains the only stop-style trigger in the fast-cycle loop.

---

### Step 3: Get unresolved bot comments

Run (up to 3 retries with 2s/4s/8s backoff on failure):
```
prc --format json list <PR> --unresolved --bots-only --inline-only --max-replies 0 --full
```

On all retries exhausted: log a warning and treat as 0 bot comments (continue the loop, do not abort).

Parse the JSON. `bot_comments` is the `comments` array. Count: `actionable_bots = len(bot_comments)`.

---

### Step 4: Get merge status

Run:
```
gh pr view <PR> --json mergeable,mergeStateStatus
```

On error (non-zero exit): log the error in the cycle narrative, then ScheduleWakeup with `delaySeconds: 60`, `reason: "gh pr view merge status failed — skipping cycle to avoid acting on unknown conflict state"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override). Do not proceed further in this iteration.

Compute: `has_conflicts = (mergeable == "CONFLICTING" or mergeStateStatus == "DIRTY")`.

---

### Step 5: Determine if work is needed

```
work_needed = (failed_checks != [] OR has_conflicts OR actionable_bots > 0)
```

---

### Step 6: Early exit if nothing actionable yet

**If `gh pr checks` returned no checks (empty list) AND `NOT work_needed` (no conflicts, no actionable bots):** Log `"Cycle <N>: no checks found yet — treat as no actionable CI work"` and ScheduleWakeup with `delaySeconds: 60`, `reason: "No CI checks present yet — waiting for workflow triggers"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override).

If the check list is empty but `work_needed` is true (a merge conflict or actionable bot comments exist), do NOT wait here — continue to the normal work-handling steps (the same sequential continuation used when `work_needed` is true) so conflicts and bot comments are addressed immediately rather than deferred behind the absence of CI checks.

Otherwise (if neither of the above applied), if `NOT work_needed` AND `NOT all_terminal` (no failed checks, no conflicts, no actionable bots, but one or more required checks are still pending — this covers BOTH the all-pending case and the mixed pass+pending case): log `"Cycle <N>: checks still pending — waiting for all CI to reach a terminal state"` and ScheduleWakeup with `delaySeconds: 60`, `reason: "CI checks still pending — waiting for all to reach a terminal state before declaring clean"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override).

---

### Step 7: No-work path (PR may be clean)

If `NOT work_needed` AND `all_terminal` (no failed checks, no conflicts, no actionable bots, and every check has reached a terminal bucket — no pending):

- **If `.smithers/clean_confirmed` file exists (`test -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"`):** push any unpushed commits (`git log @{u}.. --oneline`; if non-empty, run `git push`; on push failure: log the error and **stop** with no ScheduleWakeup). Then proceed to **Step 7a: Handle PR ready**.
- **If `.smithers/clean_confirmed` file does NOT exist:**
  1. Ensure the `.smithers/` state directory exists, then set the flag:
     - Run `mkdir -p "$(git rev-parse --show-toplevel)/.smithers"` (no-op if the directory already exists). The directory holds only transient flag files for cross-wakeup state; nothing tracked or application-relevant lives there.
     - Run `touch "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"` to persist the flag across the ScheduleWakeup gap.
     - Smithers does NOT touch the host repo's `.gitignore`. If `.smithers/` is not ignored globally on the host machine, the directory will show up as untracked in `git status`. This is the user's setup concern — see the STATE section's Init bullet for the one-time setup instructions. For users of the nixpkgs configuration in this repo, running `hms` deploys the global ignore automatically.
  2. Log `"Cycle <N>: no work detected — scheduling wakeup in 60s to re-verify (checking for cascade workflows)"`.
  3. ScheduleWakeup with `delaySeconds: 60`, `reason: "No work detected — re-polling after 60s to confirm PR is clean before proceeding to merge"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override).
  4. **Stop** (one iteration per invocation — the next invocation re-runs Steps 1–5 with fresh data; if still no work, the flag file exists and Step 7a runs).

### Merge-consent policy (deterministic)

This rule governs every merge decision in /smithers — both in Step 7a and in AW-5. There is exactly one rule. Apply it without per-run re-interpretation.

DEFAULT: merge or queue on full satisfaction. When smithers detects a PR has reached **full satisfaction**, it merges directly (or adds the PR to the merge queue when branch protection requires queueing) without waiting for a manual "merge it." Full satisfaction means ALL THREE of the following hold:

1. **Human approval:** `reviewDecision == "APPROVED"`, satisfied by a real, non-author human (REVIEW_REQUIRED, four-eyes, per GitHub's no-self-approval rule). Bot or auto-approval alone does NOT count.
2. **CI all green:** no failed or pending required checks.
3. **No unresolved bot OR human comments**, verified comprehensively (per the merge-gate rule in Step 7a — NOT an `--inline-only` count).

Full satisfaction is itself sufficient authorization to merge or queue — `/smithers <PR>` does not need a separate merge grant.

The opt-OUT is the only reason to PAUSE instead: an explicit user statement to merge this PR manually (e.g., "don't merge, I'll do it myself", "I'll merge manually"). Treat that as a durable preference for this PR — surface readiness (macOS notification, Slack post) and stop short of merging.

These triggers are ALSO sufficient authorization (they are no longer REQUIRED, since full satisfaction already authorizes):

1. The invoking prompt explicitly granted merge authority (e.g., "merge it when clean", "you have authority to merge", or a direct "merge it" / "yes, merge" in the text that launched this /smithers session).
2. A standing coordinator rule exists that approved-and-green PRs merge automatically.
3. The original task scope explicitly included merging this PR as a stated deliverable.

These explicit grants still ride on the Step 7a / AW-5 gate — an explicit grant does NOT bypass the requirement for reviewDecision==APPROVED, CI green, and no unresolved comments. The grants resolve the authorization question; the gate independently verifies the PR state before any merge action.

Once full satisfaction holds (or one of the explicit grants above applies), merge or queue without re-confirming. The GitHub review-approval is the review gate; merging a fully-satisfied PR is exactly /smithers' job. Never cancel or revert a genuinely-authorized in-flight merge because of the session's earlier, now-superseded scope framing.

**Why this rule is deterministic:** Full satisfaction is three explicit boolean conditions — not prose requiring per-run weighing. If all three hold, merge or queue. If the user has opted out for manual merge on this PR, PAUSE. No LLM judgment about "does this invocation implicitly authorize merging?" is involved.

---

### Land action (explicit — lands or errors, never arms forward-looking auto-merge)

This is the ONLY sanctioned way for smithers to land a PR. It is invoked from Step 7a and from AW-5, and ONLY after the § Present-state mergeability check has confirmed the PR is mergeable RIGHT NOW (approved, CI green, `mergeStateStatus == "CLEAN"`, zero unresolved comments). Full-satisfaction merge is a SINGLE EXPLICIT action taken at detection time — never a forward-looking "merge when ready" arm.

**🚨 PROHIBITED — never use bare `gh pr merge` as the land action.** A bare `gh pr merge [--merge|--squash|--rebase] <PR>` (i.e. without the L2 arm-guard below) does NOT reliably merge-or-fail. On a PR that is not immediately mergeable — `mergeStateStatus` BLOCKED/BEHIND, base branch locked or frozen, or required checks not yet passed — `gh pr merge` **silently ARMS forward-looking auto-merge ("merge when ready") and exits 0**. This is the tool's documented behavior: `gh pr merge --help` states "If required checks have not yet passed, auto-merge will be enabled." An armed auto-merge then fires the instant the PR unblocks, which **bypasses any deliberate merge-hold or branch freeze** and is invisible to normal state polling (`state`, `mergeStateStatus`) — it surfaces ONLY in the `autoMergeRequest` field. Smithers NEVER arms auto-merge as a forward-looking action; it lands deterministically at detection time or returns the real blocking reason.

**L1 — Land explicitly (choose by base-branch type).** First resolve `{owner}/{repo}` as elsewhere in this skill (e.g. `gh repo view --json owner,name`), then detect whether the base branch uses a merge queue:

```bash
gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<N>){mergeQueue{id}}}}' --jq '.data.repository.pullRequest.mergeQueue'
```

- **Merge-queue base branch (non-null `mergeQueue`):** enqueue deterministically via the `enqueuePullRequest` GraphQL mutation. It enqueues the PR or returns the real blocking reason as a GraphQL error, and NEVER arms forward-looking auto-merge:
  ```bash
  PR_ID=$(gh pr view <PR> --json id --jq .id)
  gh api graphql -f query='mutation($id:ID!){enqueuePullRequest(input:{pullRequestId:$id}){mergeQueueEntry{state position}}}' -f id="$PR_ID"
  ```
  A non-null `mergeQueueEntry` in the response confirms enqueue (success-with-enqueue). A GraphQL error (non-zero exit) means the PR could not be enqueued — the error text IS the real blocking reason; log it, set `merge_failed = true`, and surface to the coordinator/user. Do NOT fall back to bare `gh pr merge` (that would arm auto-merge). `enqueuePullRequest` never touches autoMergeRequest, so the mandatory L2 arm-guard below runs as defense-in-depth on this branch — it will always find `autoMergeRequest == null` here, confirming nothing was armed.

- **Non-merge-queue base branch (null `mergeQueue`):** immediate merge. Because the present-state check just confirmed `mergeStateStatus == "CLEAN"`, this lands now:
  ```bash
  gh pr merge --squash <PR>
  ```
  A non-arming failure here (e.g., a conflict developing in the TOCTOU window between the present-state check and this call) leaves `autoMergeRequest` null — L2 below routes it to the merge/enqueue verification (Step 7a / AW-5), which sets `merge_failed = true` when the merge is unconfirmed.

**L2 — Auto-merge arm guard (MANDATORY after EVERY land attempt, both branches).** Immediately re-read the auto-merge state:

```bash
gh pr view <PR> --json autoMergeRequest --jq '.autoMergeRequest'
```

- **`autoMergeRequest` is `null`** → nothing was armed. Proceed to the merge/enqueue verification (the Step 7a / AW-5 verify logic).
- **`autoMergeRequest` is NON-null** → the land attempt SILENTLY ARMED forward-looking auto-merge instead of landing — the PR was not immediately mergeable (a TOCTOU flip to BLOCKED/behind, or a base-branch freeze slipped in between the present-state check and the land call). This is the footgun. DISARM it immediately and treat the land as failed — never leave auto-merge armed:
  ```bash
  gh pr merge --disable-auto <PR>
  ```
  Then read the real blocking reason (`gh pr view <PR> --json mergeStateStatus`), log `"Land aborted: gh armed forward-looking auto-merge on PR <N> (mergeStateStatus=<value>) — disarmed via --disable-auto. PR was not immediately mergeable; not landed."`, send an osascript notification, set `merge_failed = true`, and surface to the coordinator/user. Do NOT retry in a loop.

The L1+L2 pair is precisely "an immediate-merge that errors rather than arming": it lands when the PR is genuinely mergeable, and if `gh` tries to arm auto-merge instead, L2 disarms it and returns the real blocking reason. **`merge_failed` is set exactly as the existing verification logic expects** — Step 7a / AW-5 then notify with the manual-merge warning text.

### Hold / freeze / stop — disarm any armed auto-merge

Any path where smithers holds, freezes, or stops WITHOUT landing — a coordinator merge-hold or branch freeze, the manual-merge opt-out, the approval-watch entry/expiry, external merge/close detection, `CHANGES_REQUESTED`, or any budget/stagnation stop — MUST first check for an armed forward-looking auto-merge and disarm it. An armed auto-merge is a **separate forward-looking state from the merge queue**: dequeuing alone is NOT sufficient — a dequeued PR whose auto-merge is still armed will re-enqueue and merge the instant it unblocks, defeating the hold/freeze. It is visible ONLY via `autoMergeRequest`, so a normal `state`/`mergeStateStatus` poll will not reveal it.

```bash
if [ "$(gh pr view <PR> --json autoMergeRequest --jq '.autoMergeRequest')" != "null" ]; then
  gh pr merge --disable-auto <PR>
fi
```

Run this disarm check as an explicit step of every hold/freeze/stop path before exiting. Smithers itself never arms auto-merge (see § Land action), so a non-null `autoMergeRequest` here means it was armed accidentally (the footgun) or externally — either way, a hold or freeze requires it disarmed.

**Boundary — this disarm does not rescind an already-enqueued merge-queue entry.** `--disable-auto` clears a forward-looking `autoMergeRequest` arm; it cannot rescind a merge-queue entry that smithers already committed via `enqueuePullRequest` (§ Land action, L1). If a coordinator hold/freeze arrives AFTER a full-satisfaction enqueue has already succeeded, the queued PR will still merge on the queue's own schedule — this disarm step does not cover that case. Treat this as a documented boundary of hold/freeze coverage, not a defect in the disarm step itself.

---

#### Step 7a: Handle PR ready

**Directory dependency.** Step 7a writes to `$(git rev-parse --show-toplevel)/.smithers/slack_posted` and reads/clears `$(git rev-parse --show-toplevel)/.smithers/clean_confirmed`. The `.smithers/` directory is guaranteed to exist at this point because the file-exists branch in Step 7 is only reachable after a prior cycle's file-NOT-exists branch ran `mkdir -p "$(git rev-parse --show-toplevel)/.smithers"`. Do NOT add a separate mkdir in Step 7a — the directory is already there.

**CRITICAL — State re-check (FIRST action):** Before any other action, re-verify the PR is still OPEN:

```bash
gh pr view <PR> --json state --jq '.state'
```

If the result is anything other than `"OPEN"` (i.e., `"MERGED"` or `"CLOSED"`): run `rm -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"` to clear the flag, send a macOS notification:
```
osascript -e 'display notification "PR <N> is <state> — smithers stopping" with title "Smithers"'
```
Log `"PR <N> is in state <X> (externally merged or closed); stopping"` and **stop** (no ScheduleWakeup). **NEVER proceed with any further action if the PR is not OPEN.**

Run:
```
gh pr view <PR> --json isDraft,mergeable,mergeStateStatus
```

If `isDraft == true`: run `gh pr ready <PR>` to promote from draft.

Check if mergeable:
- `mergeable == "MERGEABLE" AND mergeStateStatus == "CLEAN" AND isDraft == false`

If mergeable: perform a present-state mergeability check before invoking merge.

### Repo Approval Policy Check (shared — used by both stale-approval gates)

This check determines whether the commit-time-vs-approval-time stale-approval comparison (used in the Present-state mergeability check below, and again in AW-5) applies at all. It runs once per merge attempt, keyed off the PR's base branch protection settings.

Resolve `{owner}/{repo}/{base}` from the PR (e.g. via `gh pr view <PR> --json baseRefName,headRepository` combined with `gh repo view --json owner,name`, or equivalent), then query the branch-protection setting:

```bash
gh api repos/{owner}/{repo}/branches/{base}/protection --jq '.required_pull_request_reviews.dismiss_stale_reviews'
```

Three outcomes:

1. **`dismiss_stale_reviews == false`** (confirmed keep-approvals repo policy): this repo's configured policy is that approvals stick across pushes — GitHub's `reviewDecision == "APPROVED"` is authoritative on its own. **Result: SKIP** the commit-time-vs-approval-time stale-approval comparison. Do not block on it. (All other gates — comprehensive unresolved-comment gate, `mergeStateStatus`, CI-green — still apply unchanged.)
2. **`dismiss_stale_reviews == true`** (confirmed dismiss-stale-reviews repo policy): GitHub itself would already flip `reviewDecision` away from `APPROVED` when new commits land, so the commit-time-vs-approval-time comparison is redundant but harmless. **Result: APPLY** the stale-approval comparison as originally specified (current behavior, unchanged).
3. **Setting cannot be determined** (API error, missing permission/scope, no branch protection configured on `{base}`, the `required_pull_request_reviews` key is absent/null, or failure to resolve `{owner}/{repo}/{base}` itself): the repo's policy is unknown. **Fail safe — Result: APPLY** the strict commit-time-vs-approval-time comparison exactly as in outcome 2. Never relax the gate when the repo's policy cannot be determined.

Log the outcome once per merge attempt, e.g.: `"Repo approval policy: dismiss_stale_reviews=<value|unknown> — stale-approval gate <skipped|applied>"`.

**Present-state mergeability check (required before any merge action):**

Fetch the current PR review and CI state:
```bash
gh pr view <PR> --json reviewDecision,statusCheckRollup,mergeStateStatus
```

The PR is currently mergeable if ALL of the following hold:
- `reviewDecision == "APPROVED"`
- **Stale-approval gate (hard pre-merge check, repo-policy-aware):** Apply § Repo Approval Policy Check (below) to determine whether the commit-time-vs-approval-time comparison applies. If the check says SKIP, treat this sub-check as satisfied and move on. If the check says APPLY (including the fail-safe "cannot be determined" case), run `gh pr view <PR> --json commits,latestReviews` and compare `commits[-1].committedDate` to the newest `latestReviews[] | select(.state=="APPROVED") | .submittedAt`. If the last commit's `committedDate` is newer than the newest APPROVED `submittedAt`, this is a **stale approval** — the current HEAD is unreviewed regardless of `reviewDecision: APPROVED`. Do NOT merge. Flag the stale approval, send macOS notification (`osascript -e 'display notification "PR <N>: stale approval — unreviewed commits present" with title "Smithers"'`), log `"Merge blocked: stale approval on PR <N>. Last commit committedDate=<X> is newer than newest APPROVED submittedAt=<Y>. Fresh approval required."`, and (re-)request a fresh review covering current HEAD. Only when the approval's `submittedAt` is newer than the last commit's `committedDate` (or the check said SKIP) is the approval considered current.
- All entries in `statusCheckRollup` have `conclusion == "SUCCESS"` (or `statusCheckRollup` is empty — no required checks)
- `mergeStateStatus == "CLEAN"`
- **Comprehensive unresolved-comment gate (bot + human) — zero unresolved threads of any kind:**
  1. **Bot threads:** Run `prc list <PR> --unresolved --bots-only` (do NOT use `--inline-only` here; that filter belongs to the Step 3 fix-loop where actionable inline findings are the target — the merge GATE must be comprehensive). Any unresolved bot thread is an **unconditional hard merge blocker** — every time, no exceptions. Confirm `is_resolved: true` (snake_case — NOT `isResolved` or `resolved`, which return null and get misread as unknown state) on every bot thread before declaring mergeable. Cite the proof when asserting the gate is clear, e.g.: "`--unresolved --bots-only` = 0 results, and `is_resolved: true` on all N bot threads." Address unresolved bot threads first (reply + resolve atomically via `prc reply` then `prc resolve`, or fix the underlying issue), then proceed.
  2. **Human threads:** Run `prc list <PR> --unresolved` (without `--bots-only`) to check for unresolved human comments. If any unresolved human comment exists, this is an **unconditional hard merge blocker** — do NOT merge. Surface the blocker via macOS notification (`osascript -e 'display notification "PR <N>: unresolved human comment — merge blocked" with title "Smithers"'`) and the standard notify path. Do NOT attempt to resolve a human's thread unilaterally; human review threads require human resolution. Log: `"Merge blocked: unresolved human comment on PR <N>. Human resolution required before merge."` This check is part of full satisfaction — it is NOT the opt-out pause.

> **Architecture note — TOCTOU window:** This present-state check and the merge invocation below are two sequential GitHub API calls. Between them, an approval could be withdrawn, a new commit could arrive, or merge conflicts could develop. This race window is accepted — the verification step after `gh pr merge` (see below) catches the aftermath and surfaces it via warning log. No pre-merge locking is possible via the GitHub API.

**Merge authorization:** Apply § Merge-consent policy (deterministic) as written. Do not restate or paraphrase the rule here — follow it directly.

**If currently mergeable:** land via **§ Land action (explicit — lands or errors, never arms forward-looking auto-merge)** above — run L1 (enqueue via `enqueuePullRequest` for a merge-queue base, or immediate `gh pr merge --squash` for a direct-merge base) then the mandatory L2 auto-merge arm guard. Do NOT invoke a bare `gh pr merge` here.

On any land failure (L1 GraphQL error, or L2 detecting/disarming an armed auto-merge — both set `merge_failed = true`): log the error, run `rm -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"`, and proceed to verification.

**If NOT currently mergeable** (any condition above is not met): the PR is clean (no failed checks, no conflicts, no actionable bot comments) but cannot be merged yet — typically because review is required. Notify reviewers via Slack, then enter the **approval-watch phase** (slow pulse) rather than stopping.

1. If `.smithers/slack_posted` does NOT exist: run `smithers-post <PR_NUMBER_OR_URL>` — append `--webhook-url "<url>"` if `webhook_override` is set for this PR (see § Slack Webhook Override), otherwise omit the flag. If it returns 0, run `touch "$(git rev-parse --show-toplevel)/.smithers/slack_posted"` to record the post. If `smithers-post` exits non-zero, log `"Warning: smithers-post failed (exit <code>) — Slack notification not delivered; flag not set so a retry on manual re-invocation will attempt again"` and do NOT touch the flag. When delivery succeeds, this signals reviewers that the PR is clean and ready for review.
2. Run `rm -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"`.
3. Log `"Cycle <N>: PR not currently mergeable (reviewDecision=<value> mergeStateStatus=<value>) — posted to Slack; entering approval-watch phase"` (or `"... — already posted to Slack; entering approval-watch phase"` if the slack_posted flag already existed).
4. Run the pre-stop sweep — sweep `prc list <PR> --unresolved --bots-only` to zero. Resolve any bot thread carrying a Smithers reply but no resolution.
5. **Disarm any armed auto-merge** per **§ Hold / freeze / stop — disarm any armed auto-merge** (check `autoMergeRequest`; if non-null, `gh pr merge --disable-auto <PR>`). Entering approval-watch is a not-landing-this-cycle transition — a forward-looking auto-merge armed accidentally or externally would fire on unblock and bypass the watch, so it must be disarmed here.
6. **Enter the approval-watch phase** (see § Approval-Watch Phase below). NEVER arm `autoMergeRequest` as a forward-looking action. All merges happen via explicit merge action on detection.

**Verify before declaring done** — run only when merge was invoked:
```
gh pr view <PR> --json state,mergedAt
```

Determine merge outcome:
- If `state == "MERGED"` or `mergedAt` is non-null: the PR merged directly — proceed to notification.
- If neither: the PR may be queued in the repo's merge queue. Do NOT infer queued-ness from `state`/`mergeStateStatus`, and do NOT trust a `gh pr merge <PR>` re-run's `already queued to merge` message as proof — that message can be stale (observed: printed while the PR was not actually enqueued). Verify enqueue via the authoritative GraphQL field instead. Resolve `{owner}/{repo}` the way this skill does elsewhere (e.g. `gh repo view --json owner,name` or `gh pr view <PR> --json headRepository`), then run:
  ```bash
  gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<N>){mergeQueueEntry{state position}}}}'
  ```
  Non-null `mergeQueueEntry` (e.g. `state: QUEUED` or `AWAITING_CHECKS`, with a `position`) means the PR is genuinely enqueued — proceed to notification. Null `mergeQueueEntry` means the PR is NOT queued (the merge attempt bounced or never enqueued) — do not assume queued; treat as merge-not-confirmed and continue below.
- **Caution — `mergeStateStatus`:** Do NOT treat `state=OPEN` / `mergeStateStatus=CLEAN` as "merge did not complete" — these values persist while a PR is queued in a merge queue and are NOT failure signals. But the inverse is equally true: do NOT treat `state=OPEN` / `mergeStateStatus=CLEAN` as positive evidence the PR IS queued — that combination is identical for an idle PR and a queued PR. `mergeStateStatus` does not reliably flip to `QUEUED` when a PR is enqueued (observed: it stays `CLEAN`). **`mergeQueueEntry` is NOT available via `gh pr view --json` (REST) — that surface does not expose it and errors if requested. It IS available and is the reliable signal via `gh api graphql` (the query above).**
- If `mergeQueueEntry` came back null AND `state != "MERGED"`: merge did not complete. Log a warning: `"Warning: merge action ran but PR is neither MERGED nor confirmed as queued (mergeQueueEntry is null). state=<value> mergeStateStatus=<value>. Manual merge may be required."` Set `merge_failed = true`. Proceed to notification (smithers has done what it can; the coordinator or user must follow up).
- If `mergeQueueEntry` was previously confirmed non-null (genuinely queued) and a later check finds it has bounced back to null before `mergedAt` was ever set: this is a **merge-queue candidate** CI failure — the queued candidate build failed a required check (often an ambient flake), and the merge queue evicted it. Do NOT silently re-run `gh pr merge` in a loop hoping it re-enqueues. Capture the failing merge-queue candidate's check via `gh pr checks <PR> --json name,state,bucket,link`, log `"Merge-queue candidate for PR <N> was evicted — failing check: <name>. Re-enqueue only after addressing or confirming the failure is a flake."`, and surface this to the coordinator/user rather than looping.

Determine notification text based on outcome:
- If `state == "MERGED"`, `mergedAt` non-null, or confirmed as enqueued (non-null `mergeQueueEntry`): use `"PR <N> merged (or queued for merge)"`.
- If `merge_failed`: use `"PR <N> ready — manual merge required (automated merge failed)"`.

Send macOS notification:
```
osascript -e 'display notification "<notification_text>" with title "Smithers"'
```

Generate Why/What summaries in-session (no subprocess). To generate:
- Run `gh pr view <PR>` to read the PR description
- Run `gh pr diff <PR>` (first 200 lines) to understand the changes
- Compose in your own reasoning:
  - **Why**: one sentence explaining the intent/problem/background
  - **What**: one sentence explaining the specific implementation approach

Then post to Slack using the `smithers-post` CLI (see § Slack Posting below).

If `.smithers/slack_posted` does NOT exist, post via:

```bash
smithers-post <PR_NUMBER_OR_URL>
```

Append `--webhook-url "<url>"` to the command above if `webhook_override` is set for this PR (see § Slack Webhook Override); otherwise omit the flag and let `smithers-post` use its default.

If `smithers-post` returns 0: run `touch "$(git rev-parse --show-toplevel)/.smithers/slack_posted"` to record that the post has been made. If `smithers-post` exits non-zero, log `"Warning: smithers-post failed (exit <code>) — Slack notification not delivered; flag not set so a retry on manual re-invocation will attempt again"` and do NOT touch the flag.

`smithers-post` reads `SMITHERS_SLACK_WEBHOOK_URL` from the environment internally, constructs the Block Kit payload, and POSTs to the webhook — unless `--webhook-url <url>` was passed, in which case that URL is used instead for this call. If neither is available (no override and `SMITHERS_SLACK_WEBHOOK_URL` not set), `smithers-post` handles that silently.

If `.smithers/slack_posted` already exists, skip the `smithers-post` call (already posted on an earlier cycle).

After posting (or skipping): run `rm -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"` to clear the flag. Run the pre-stop sweep — sweep `prc list <PR> --unresolved --bots-only` to zero before stopping. Then, before exiting, **disarm any armed auto-merge** per **§ Hold / freeze / stop — disarm any armed auto-merge** (check `autoMergeRequest`; if non-null, `gh pr merge --disable-auto <PR>`) as a hard step. Then **stop** (no ScheduleWakeup). The PR is clean and handled.

---

## Approval-Watch Phase

When the PR is clean but not yet mergeable (review pending), smithers switches from the 1-minute CI-babysit cadence to a slow pulse of **~10 minutes** via ScheduleWakeup. This phase is named **approval-watch**.

**Entering the phase:** Reached from Step 7a "If NOT currently mergeable" path. Before scheduling the first slow-pulse wakeup:

1. Set the durable flag: `touch "$(git rev-parse --show-toplevel)/.smithers/approval_watch"`.
2. Recall or initialize `approval_watch_cycle = 0` (in-memory; reset to 0 when the flag is first set; incremented on each slow-pulse invocation).
3. ScheduleWakeup with `delaySeconds: 600`, `reason: "Entering approval-watch — waiting ~10 minutes before first slow-pulse check (review pending)"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override).

**Detecting the phase on wakeup:** At the start of each smithers invocation, after Step 1 (PR state check), test:

```bash
test -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"
```

If the flag file exists, this is an approval-watch pulse. Skip Steps 2–15 of the normal loop body and execute the approval-watch pulse logic below instead.

---

### Approval-Watch Pulse Logic

Each slow-pulse invocation runs these checks in order:

**AW-1: Re-verify PR is still open.**

```bash
gh pr view <PR> --json state --jq '.state'
```

- If `state == "MERGED"`: run `rm -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"`, send macOS notification `"PR <N> merged externally — smithers stopping"`, log `"PR <N> merged externally; exiting approval-watch cleanly"`, and **stop** (no ScheduleWakeup). This is the **merged externally** exit.
- If `state == "CLOSED"`: run `rm -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"`, send macOS notification `"PR <N> closed — smithers stopping"`, log `"PR <N> closed externally; exiting approval-watch cleanly"`, and **stop** (no ScheduleWakeup).

**AW-2: Fetch live GitHub state.**

Run:

```bash
gh pr view <PR> --json reviewDecision,mergeStateStatus,state,mergedAt
```

Capture `reviewDecision`, `mergeStateStatus`.

**AW-3: Check for late bot comments.**

Run:

```bash
prc list <PR> --unresolved --bots-only
```

If new unresolved bot comments are found, exit the approval-watch phase and re-enter the normal fix cycle:

1. Run `rm -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"`.
2. Log `"Approval-watch cycle <N>: new bot comments detected — re-entering fix cycle"`.
3. ScheduleWakeup with `delaySeconds: 60`, `reason: "New bot comments detected during approval-watch — resuming 1-minute CI cycle"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override).

(The next invocation will run the normal loop body, pick up the bot comments in Step 3, and handle them. Once the fix cycle completes cleanly again, smithers will re-enter approval-watch from Step 7a.)

**AW-4: Check for late CI failures.**

Run:

```bash
gh pr checks <PR> --json name,state,bucket,link
```

Compute `fail_fast` (same as Step 2 of the main loop). If any check has bucket `fail` or a failure-state:

1. Run `rm -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"`.
2. Log `"Approval-watch cycle <N>: late CI failure detected — re-entering fix cycle"`.
3. ScheduleWakeup with `delaySeconds: 60`, `reason: "Late CI failure detected during approval-watch — resuming 1-minute CI cycle"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override).

**AW-5: Disposition on review state.**

Evaluate `reviewDecision` and `mergeStateStatus`:

- **`reviewDecision == "APPROVED"` AND `mergeStateStatus == "CLEAN"`:** The PR is approved and clean. Before running any further checks, verify the approval is not stale (hard pre-merge gate, repo-policy-aware): apply § Repo Approval Policy Check (above) to determine whether the commit-time-vs-approval-time comparison applies. If the check says SKIP, treat this sub-check as satisfied and proceed directly to the comprehensive unresolved-comment gate below. If the check says APPLY (including the fail-safe "cannot be determined" case), run `gh pr view <PR> --json commits,latestReviews` and compare `commits[-1].committedDate` to the newest `latestReviews[] | select(.state=="APPROVED") | .submittedAt`. If the last commit's `committedDate` is newer than the newest APPROVED `submittedAt`, this is a **stale approval** — the current HEAD is unreviewed regardless of `reviewDecision: APPROVED`. Do NOT merge. Send macOS notification (`osascript -e 'display notification "PR <N>: stale approval — unreviewed commits present" with title "Smithers"'`), log `"Merge blocked: stale approval on PR <N>. Last commit committedDate=<X> is newer than newest APPROVED submittedAt=<Y>. Fresh approval required."`, and continue the slow pulse (the next pulse re-evaluates state after a reviewer approves current HEAD). Only when the approval is current (approval `submittedAt` newer than last commit `committedDate`, or the check said SKIP): run the comprehensive unresolved-comment gate (bot + human) before merging:
  1. **Bot threads:** Run `prc list <PR> --unresolved --bots-only` (do NOT use `--inline-only` — this gate must be comprehensive; `--inline-only` is for the Step 3 fix-loop only). Confirm `is_resolved: true` (snake_case — NOT `isResolved` or `resolved`) on every bot thread. Any unresolved bot thread is an **unconditional hard merge blocker** — treat as "new bot comments" (AW-3 path above) before merging.
     **Human threads:** Run `prc list <PR> --unresolved` (without `--bots-only`) to check for unresolved human comments. If any unresolved human comment exists, this is an **unconditional hard merge blocker** — do NOT merge. Surface via macOS notification (`osascript -e 'display notification "PR <N>: unresolved human comment — merge blocked" with title "Smithers"'`) and log: `"Merge blocked: unresolved human comment on PR <N>. Human resolution required before merge."` Do NOT attempt to resolve a human's thread unilaterally. This check is part of full satisfaction — it is NOT the opt-out pause.
  2. If zero unresolved comments of any kind (bot gate clear + no unresolved human comment): this is the merge path. Cite the proof before proceeding, e.g.: "`--unresolved --bots-only` = 0 results, `is_resolved: true` on all N bot threads, and `--unresolved` = 0 human threads." Apply § Merge-consent policy (deterministic) as written — do not restate or paraphrase the rule here. Then land via **§ Land action (explicit — lands or errors, never arms forward-looking auto-merge)** above — run L1 (enqueue via `enqueuePullRequest` for a merge-queue base, or immediate `gh pr merge --squash` for a direct-merge base) then the mandatory L2 auto-merge arm guard. Do NOT invoke a bare `gh pr merge` here.

     On any land failure (L1 GraphQL error, or L2 detecting/disarming an armed auto-merge — both set `merge_failed = true`): log the error, do NOT clear the `approval_watch` flag, and continue the slow pulse (the next pulse re-evaluates state).
  3. Run `rm -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"`. (Note: clearing the flag before the verify call below leaves a narrow orphan window — if the session crashes between here and the verify call, the flag is gone and smithers will re-enter the normal loop body on restart rather than the AW path. Accepted behavior: Step 1's MERGED check is the fallback.)
  4. Verify and notify using the same verification logic as Step 7a: check `state == "MERGED"` or `mergedAt` non-null. If neither, do NOT infer queued-ness from `state`/`mergeStateStatus` and do NOT trust a `gh pr merge <PR>` re-run's `already queued to merge` message as proof (it can be stale). Instead verify via GraphQL: resolve `{owner}/{repo}` (e.g. `gh repo view --json owner,name`) and run `gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<N>){mergeQueueEntry{state position}}}}'`. Non-null `mergeQueueEntry` = confirmed enqueue. Null `mergeQueueEntry` = NOT queued — treat as merge-not-confirmed, log a warning, and set `merge_failed = true` rather than assuming queued. Do NOT treat `state=OPEN` / `mergeStateStatus=CLEAN` as merge failure — those values persist while a PR is queued — but also do NOT treat that combination as positive evidence of queued-ness (identical for idle and queued PRs). `mergeQueueEntry` is NOT available via `gh pr view --json` (REST) — it errors if requested there — but IS available and is the reliable signal via `gh api graphql` as above. If `mergeQueueEntry` was previously confirmed non-null and later bounces back to null before `mergedAt` is set, this is a **merge-queue candidate** CI failure (the queued build failed a required check) — capture the failing check via `gh pr checks <PR> --json name,state,bucket,link` and surface to the coordinator/user rather than silently re-enqueuing in a loop. Send osascript notification, post to Slack via `smithers-post` if `.smithers/slack_posted` does not already exist (append `--webhook-url "<url>"` if `webhook_override` is set for this PR — see § Slack Webhook Override).
  5. **Stop** (no ScheduleWakeup).

- **`reviewDecision == "CHANGES_REQUESTED"`:** Surface to the invoking session or coordinator.
  1. Run `rm -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"`.
  2. Send macOS notification: `"PR <N>: changes requested — smithers stopping"`.
  3. Log `"Approval-watch cycle <N>: reviewDecision=CHANGES_REQUESTED — surfacing to coordinator. PR left in CHANGES_REQUESTED state with <mergeStateStatus> merge status."`.
  4. Run the pre-stop sweep — sweep `prc list <PR> --unresolved --bots-only` to zero. Then, before exiting, **disarm any armed auto-merge** per **§ Hold / freeze / stop — disarm any armed auto-merge** (check `autoMergeRequest`; if non-null, `gh pr merge --disable-auto <PR>`) as a hard step.
  5. **Stop** (no ScheduleWakeup). The coordinator or user must address the reviewer feedback.

- **Any other `reviewDecision`** (e.g., `REVIEW_REQUIRED`, `null`): Review still pending. Increment `approval_watch_cycle` by 1. Proceed to AW-6.

**AW-6: Check expiry bound.**

The approval-watch phase expires after **144 slow-pulse cycles (~24 hours at the ~10-minute cadence)**. This expiry prevents indefinite watches on stalled PRs.

If `approval_watch_cycle >= 144`:

1. Run `rm -f "$(git rev-parse --show-toplevel)/.smithers/approval_watch"`.
2. Send macOS notification: `"PR <N>: approval-watch expired after ~24h"`.
3. Log `"Approval-watch expired after <approval_watch_cycle> cycles (~<hours>h). PR left in state: reviewDecision=<value>, mergeStateStatus=<value>, state=OPEN. Handoff: PR requires human action — either reviewer approval or manual re-invocation of /smithers to resume watching."`.
4. Run the pre-stop sweep — sweep `prc list <PR> --unresolved --bots-only` to zero. Then, before exiting, **disarm any armed auto-merge** per **§ Hold / freeze / stop — disarm any armed auto-merge** (check `autoMergeRequest`; if non-null, `gh pr merge --disable-auto <PR>`) as a hard step.
5. **Stop** (no ScheduleWakeup).

**AW-7: Schedule next slow-pulse wakeup.**

Log `"Approval-watch cycle <approval_watch_cycle>: review still pending (reviewDecision=<value>) — scheduling next pulse in 10 minutes"`.

ScheduleWakeup with `delaySeconds: 600`, `reason: "Approval-watch cycle <N> — waiting ~10 minutes before next slow-pulse check"`, and `prompt: "Continue /smithers <PR_URL>"` (or `"Continue /smithers <PR_URL> webhook=<url>"` if `webhook_override` is active for this PR — see § Slack Webhook Override).

---

### Step 8: Check budget limits

If either budget limit is reached (`fix_count >= max_ralph_invocations` OR `cycle >= max_cycles`), execute the pre-stop sweep first: sweep `prc list <PR> --unresolved --bots-only` to zero — resolve any bot thread that carries a Smithers reply but no resolution before stopping. The fix-delegation cap limits CODE-FIX delegations only; it is never a license to leave a replied-to thread open. Then, before either budget stop below, **disarm any armed auto-merge** per **§ Hold / freeze / stop — disarm any armed auto-merge** (check `autoMergeRequest`; if non-null, `gh pr merge --disable-auto <PR>`) as a hard step.

If `fix_count >= max_ralph_invocations`: log `"Max specialist delegations (4) reached — stopping"`, send osascript notification, and **stop** (no ScheduleWakeup).

If `cycle >= max_cycles`: log `"Max cycles (10) reached — stopping"`, send osascript notification, and **stop** (no ScheduleWakeup).

---

### Step 9: Build the fix prompt

Compose a prompt string for the specialist. Include all of the following sections that are relevant:

```
# PR Watch Task

**PR:** <URL>
**Title:** <title>
**Branch:** <head> → <base>

## Iteration Context

This is iteration <cycle> of <max_cycles>. You have <remaining> more attempt(s) after this one.

## Your Mission

Fix the issues found in this PR, then exit. The coordinator will re-check after you are done.

## CRITICAL SAFETY CONSTRAINTS

**You are running autonomously with elevated permissions. You MUST NEVER perform these operations:**

### Cluster & Infrastructure (PROHIBITED)
- kubectl apply/create/patch/delete/scale/exec/port-forward
- helm install/upgrade/uninstall
- terraform apply/destroy, pulumi up/destroy
- Cloud providers: EC2 terminate, RDS delete, S3 delete, autoscaling changes
- ALLOWED: Read-only operations (kubectl get/describe/logs, terraform plan)

### Secrets & IAM (PROHIBITED)
- aws secretsmanager put, vault write, kubectl create secret
- IAM/RBAC: Role modifications, permission grants, access key changes
- Credentials: ANY operations on ~/.aws, ~/.kube, ~/.ssh
- Sensitive files: NEVER read/commit .env*, *.env, credentials.json, secrets.yaml
- ALLOWED: Read non-sensitive configuration (package.json, tsconfig.json, etc.)

### Databases (PROHIBITED)
- Schema changes: DROP/ALTER/TRUNCATE/CREATE TABLE
- Bulk operations: DELETE FROM or UPDATE without WHERE clause
- ALLOWED: SELECT queries, SHOW/DESCRIBE commands

### Git Operations (RESTRICTED)
- Force operations: git push --force, git reset --hard, git clean -fd
- ALLOWED: Normal commits/pushes within current branch

### System Operations (PROHIBITED)
- Privilege escalation: sudo, privileged containers, ssh access
- Network operations: iptables, firewall changes, DNS modifications
- Process manipulation: kill, systemctl (except git/development processes)

### When to Exit Early

You have explicit permission to STOP and exit if:
- Required operation needs cluster/infrastructure writes
- Task requires modifying secrets or IAM
- Any safety constraint would be violated

Better to exit early than cause damage.

## WORKING DIRECTORY RESTRICTION

You are running autonomously. All file operations MUST stay within the current git repository root.
- No cd to change directories
- No ../relative paths outside the repo
- No edits to ~/.claude/, ~/.config/, or system directories

## Failed Checks
<for each failed check: "- **<name>**: [View logs](<link>)">

**Action:** Investigate each failure:
1. If caused by your changes: Fix the code, commit, and push
2. If unrelated (flaky test, transient issue): Use `gh run rerun <run-id>` to rerun the workflow, then exit

## Inline Bot Comments (<N> actionable)
<for each bot comment thread:>
**<author>** on `<path>:<line>` (thread: `<thread_id>`, comment: `<comment_id>`) ([link](<url>)):
```
<body>
```

**prc Tool Reference:**
- Reply to a comment: `prc reply <numeric-comment-id> "message"` — uses the NUMERIC integer comment value
- Resolve a thread: `prc resolve <thread-id>` — uses the PRRT_ thread ID value
- IMPORTANT: These are two DIFFERENT identifiers. Do NOT pass the PRRT_ thread ID to `prc reply`.

**MANDATORY after EVERY bot comment — no exceptions:**
1. `prc reply <comment_id> "..."`
2. `prc resolve <thread_id>`

Reply and resolve are one atomic action. A reply without a resolve is a defect — `is_resolved` only flips when `prc resolve` is called, and an unresolved thread re-triggers fix cycles on every subsequent poll regardless of reply count. This invariant holds including on deferral, cap-stop, and known-limitation paths: the fix-delegation cap limits CODE-FIX delegations only and never licenses leaving a replied-to thread open. When a thread is deferred (e.g., "no fix possible in this pass"), the reply explains the deferral AND `prc resolve <thread_id>` is still called in the same step.

**Action — For EACH bot comment:**
Step 1: Critically evaluate — does it require a code change?
Step 2 — If NO code change needed: Reply and resolve immediately:
  `prc reply <comment_id> "No change needed: <explanation>"`
  `prc resolve <thread_id>`
Step 3 — If code change IS needed: Fix the code, commit, push, then reply with the commit hash via `prc reply <comment_id>`, and resolve via `prc resolve <thread_id>`.

**Universal pre-stop bot-thread sweep:** Before ANY smithers stop or exit — including the Step 7a clean-PR stop, the cap-stop (Step 8), max-cycles (Step 8), the stagnation stop (Step 13), and any other terminal path — sweep `prc list <PR> --unresolved --bots-only` to zero. Resolve any bot thread that carries a Smithers reply but no resolution before exiting. No stopping condition is a license to leave a replied-to thread open.

**End-of-pass sweep (mandatory before exiting):** Before declaring the bot-handling pass complete, sweep `prc list <PR> --unresolved --bots-only` to zero — resolve any bot thread carrying a reply but no resolution before exiting. Never exit with a replied-to thread still unresolved.

## Merge Conflicts

This PR has merge conflicts that must be resolved.

**Action:**
1. Fetch latest from base branch
2. Resolve conflicts
3. Commit and push the resolution

## Acceptance Criteria — When to Exit

Complete ALL of the following before exiting:
1. All Failed Checks Fixed: investigated root cause, fixed, committed, pushed
2. All Bot Comments Replied AND Resolved: for every thread — both `prc reply <comment_id>` AND `prc resolve <thread_id>` called. Reply without resolve is incomplete; the thread remains open and counts as actionable on the next poll.
3. All Merge Conflicts Resolved (if present): fetched latest, resolved, pushed
4. All Changes Pushed to Remote: git status shows clean, all commits on origin

## What NOT to Do
- Do NOT wait for CI checks to pass — the coordinator re-checks after you exit
- Do NOT try to verify check status yourself
- Do NOT loop or retry — fix once, push, exit
- Do NOT exit with uncommitted or unpushed changes

Exit immediately after completing all acceptance criteria.
```

(Omit the Merge Conflicts section if `has_conflicts` is false. Omit the Bot Comments section if `actionable_bots == 0`. Omit the Failed Checks section if `failed_checks` is empty.)

---

### Step 10: Capture pre_sha

Run:
```
git rev-parse HEAD
```

Store this as `pre_sha` to detect stagnation after the specialist returns.

---

### Step 11: Delegate to specialist via Agent tool

When fix work is needed, delegate via the Agent tool to specialist(s) chosen based on the ACTUAL work content using normal staff-coordinator judgment — examine the failures and bot comments, then pick the right specialist(s). Multi-specialist parallel delegation is encouraged where work spans domains (e.g., a test failure related to security flagging both → `swe-fullstack` + `swe-security` in parallel). Do NOT use a hardcoded failure-category-to-specialist mapping.

**Inside a crew-spawned staff session, this delegation is blocked by the kanban-card Agent hook.** A crew-spawned staff session's `PreToolUse:Agent` hook DENIES any Agent-tool delegation whose prompt carries no kanban card reference ("no kanban card reference found in prompt"). `/smithers` does not create a kanban card, so this Step 11 delegation cannot self-satisfy the hook — attempting it blindly stalls the run. **Fallback:** when a code fix is needed inside such a session, do NOT blindly attempt this Agent delegation and stall. Instead, surface the needed fix so it is routed through the staff kanban flow (the coordinator creates a card, delegates to the appropriate specialist, applies the fix, and pushes), then re-fire `/smithers` for the remaining steps that need no Agent delegation (CI-watch, draft→ready, Slack-notify, approval-watch, merge). See the coordinator-side rule in senior-staff-engineer.md § PR-review workflow for the full cross-reference. This affects ONLY this fix-delegation step — every other /smithers step is unaffected.

Otherwise, invoke the Agent tool with the prompt from Step 9, targeting the appropriate specialist agent(s). This is blocking — wait for the specialist to complete before proceeding.

Increment `fix_count` by 1.

---

### Step 12: Post-delegation cleanup

**Security audit:** Run `git log --since="30 minutes ago" --patch` and scan both commit subjects AND the patch body for prohibited patterns: `kubectl apply`, `terraform apply`, `terraform destroy`, `pulumi up`, `DROP TABLE`, `sudo`, `ssh`. Log a warning for any matches (do not abort).

**Push unpushed commits:** Run `git log @{u}.. --oneline`. If non-empty: run `git push`. On push failure: log the error and **stop** (no ScheduleWakeup — push failures indicate a real problem).

---

### Step 13: Stagnation detection

Run:
```
git rev-parse HEAD
```

Store as `post_sha`. Compare to `pre_sha`:
- If `pre_sha == post_sha`: increment `stagnation_count`. If `stagnation_count >= 2`: run the pre-stop sweep — sweep `prc list <PR> --unresolved --bots-only` to zero before stopping. Then, before exiting, **disarm any armed auto-merge** per **§ Hold / freeze / stop — disarm any armed auto-merge** (check `autoMergeRequest`; if non-null, `gh pr merge --disable-auto <PR>`) as a hard step. Then log `"Stagnation detected — specialist made no commits in 2 consecutive cycles. Stopping."` and **stop** (no ScheduleWakeup).
- If `pre_sha != post_sha`: reset `stagnation_count = 0`.

---

### Step 14: Update cycle count

Increment `cycle` by 1.

Log a brief status summary: `"Cycle complete. fix_count=<N> stagnation=<N> cycle=<N>/<max_cycles>"`.

---

### Step 15: Schedule next iteration

ScheduleWakeup in 1 minute, continuing with the same PR:

```
ScheduleWakeup(
  delaySeconds=60,
  reason="Waiting 1 minute before next smithers polling cycle for PR <N>",
  prompt="Continue /smithers <PR_URL>"  # append " webhook=<url>" if webhook_override is active — see § Slack Webhook Override
)
```

---

## STOPPING CONDITIONS (summary)

Stop (no ScheduleWakeup) when any of the following occur:

**Fast-cycle stops (Steps 1–15):**
1. PR is MERGED or CLOSED (Step 1)
2. PR is clean and merged or enqueued after merge action, or manual-merge warning logged (Step 7a)
3. `fix_count >= max_ralph_invocations` (Step 8)
4. `cycle >= max_cycles` (Step 8)
5. `stagnation_count >= 2` (Step 13)
6. `git push` fails (Steps 7 or 12)
7. Unrecoverable error on first iteration (argument parsing failure)

**Approval-watch stops (§ Approval-Watch Phase):**
8. PR merged externally detected during slow pulse (AW-1)
9. PR closed externally detected during slow pulse (AW-1)
10. PR approved + clean → merge executed (AW-5)
11. `reviewDecision == "CHANGES_REQUESTED"` → surfaced to coordinator (AW-5)
12. Approval-watch expiry after ~24h / 144 cycles with handoff message (AW-6)

---

## SLACK POSTING

Smithers posts to Slack using the `smithers-post` CLI — the ONLY supported posting path.

**ABSOLUTE PROHIBITION — NEVER use any of the following:**
- **NEVER use any Slack tool provided by an MCP server.** Those tools are for interactive read/search workflows — never use them to post notifications from smithers.
- **NEVER invoke a Slack-posting skill or wrapper of any kind.**
- **NEVER construct a curl payload to the webhook directly.** Do not read `SMITHERS_SLACK_WEBHOOK_URL` or call curl yourself.
- **NEVER use any wrapper, indirection layer, or skill between smithers and Slack posting.**

This prohibition is absolute regardless of the per-invocation webhook override described below — the override changes only the destination URL argument passed to `smithers-post`; it never opens curl, an MCP Slack tool, or any other posting path.

**The ONLY supported path for Slack posting is the `smithers-post` CLI:**

```bash
smithers-post <PR_NUMBER_OR_URL>
```

`smithers-post` fetches PR metadata via `gh pr view` internally, constructs the Block Kit JSON payload, and POSTs to the webhook URL read from `SMITHERS_SLACK_WEBHOOK_URL` — unless a per-invocation override is active (see § Slack Webhook Override immediately below). All formatting, env-var management, and HTTP details are handled by the CLI.

### Slack Webhook Override

`/smithers <PR> webhook=<url>` lets a single invocation route that PR's Slack notifications to a different incoming-webhook URL than `SMITHERS_SLACK_WEBHOOK_URL` — e.g. routing one incident PR's reviewer-attention post to an incident channel instead of the default channel.

- **Parsing:** the `webhook=<url>` token is parsed in § ARGUMENT PARSING and stored as `webhook_override` (see § STATE) for the remainder of the session on this PR.
- **Passthrough:** every `smithers-post <PR>` invocation this skill makes for that PR — the initial "PR ready for review" post in Step 7a, the merge-time post in Step 7a, and any post triggered from AW-5 — appends `--webhook-url <url>`:
  ```bash
  smithers-post <PR_NUMBER_OR_URL> --webhook-url "<url>"
  ```
- **Wakeup threading:** because `webhook_override` is conversation-context state, it does NOT survive the fresh agent context spawned after a `ScheduleWakeup` gap on its own. It is carried the same way the PR argument itself is carried — embedded as literal text in the `prompt` field of every `ScheduleWakeup` call in this skill: `prompt: "Continue /smithers <PR_URL> webhook=<url>"` instead of the bare `"Continue /smithers <PR_URL>"`. This applies on every wakeup in the session — the initial fast cycle, entering approval-watch, and every approval-watch pulse — not just the first one. Omitting it on any single wakeup silently drops the override for the rest of the run.
- **Default unchanged:** when no `webhook=<url>` token is given, `webhook_override` is never set, `--webhook-url` is never passed to `smithers-post`, and `smithers-post` reads `SMITHERS_SLACK_WEBHOOK_URL` exactly as it did before this feature existed. Every normal `/smithers <PR>` invocation is unaffected.
- **Security note:** the override URL is a live-posting credential — it persists in plaintext in the wakeup `prompt` text and the session transcript for the life of the watch (potentially up to ~144 approval-watch pulses over ~24h, per AW-6). Prefer this override only for genuinely temporary/incident routing, not long-lived secrets, and rotate the webhook in Slack if it may have been exposed.

**PR state guard — already enforced at the top of Step 7a.** The state re-check at the start of Step 7a guarantees smithers only reaches this point if the PR is OPEN. Do not add a second guard here.

Smithers posts to Slack at Step 7a (PR ready for review) and optionally again at merge time (if `.smithers/slack_posted` is not set). No Slack notification is sent for other stopping conditions (stagnation stop, max cycles, approval-watch expiry, etc.).

---

## NOTES

- The 1-minute ScheduleWakeup is the platform-minimum cadence for the fast CI cycle. The approval-watch phase uses a ~10-minute cadence — appropriate for human review timescales.
- Most state is in the conversation context. Three durable exceptions use flag files because they must survive the ScheduleWakeup gap: `clean_confirmed` (`.smithers/clean_confirmed`), `slack_posted` (`.smithers/slack_posted`), and `approval_watch` (`.smithers/approval_watch`). `slack_posted` additionally survives watcher restarts.
- If this session is killed and restarted, the loop restarts from cycle 1 with a fresh `fix_count` and `stagnation_count`. The `clean_confirmed` flag file persists across restarts — if it exists when smithers restarts, smithers will proceed directly to Step 7a on the next no-work cycle. This is intentional and correct behavior. Similarly, if `.smithers/approval_watch` exists when smithers restarts, smithers will detect the phase on the first invocation and resume the slow-pulse cadence.
- The smithers-post Slack notification (Step 7a) deduplicates across sessions via the `.smithers/slack_posted` flag. If the watcher restarts on a PR that already has the flag set, smithers will skip the Slack post. To re-post (e.g., to re-notify after a long approval-watch expiry), the user manually removes `.smithers/slack_posted`.
- `webhook_override` (see § Slack Webhook Override) is never written to a file — unlike the three durable flags above, it is pure conversation-context state. A session kill/restart silently loses it: Slack posts revert to the default `SMITHERS_SLACK_WEBHOOK_URL` channel unless the operator re-supplies `webhook=<url>` on manual re-invocation.
