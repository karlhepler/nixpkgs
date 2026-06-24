---
name: pr-review-watcher
description: >
  Watch a Slack review-request channel and run /pr-review on PRs that genuinely need review,
  then follow through to resolution and approval. Requires a Slack channel as a mandatory
  launch argument (channel ID, name, or archive URL). Auto-detects operator identity
  (Slack self-user-id, GitHub login). Runs a recurring in-session cron (~5-minute pulse)
  via CronCreate. Spawns /pr-review sessions per PR via crew, deduplicates by skipping PRs
  already reviewed by an independent human, never reviews the operator's own PRs, and
  follows through with a follow-up loop until PRs are approved or closed. Uses ScheduleWakeup
  for follow-up self-pulses with the watcher cron as backstop. Requires the Slack MCP server
  (must run in an interactive session — NOT headless). Invoke when user says "watch review
  channel", "monitor PR review requests", "start pr-review-watcher", "watch slack for PRs
  to review", "run pr-review-watcher", "watch the review channel", "watch #<channel-name>
  for reviews", or "review PRs from slack".
argument-hint: "<channel-id | #channel-name | channel-name | slack-archive-url> [--lookback N] [--interval <minutes>] [--bot-logins login1,login2] [--model sonnet[1m]]"
---

# PR Review Watcher

**Purpose:** Watch a Slack review-request channel on a recurring ~5-minute cron pulse. For each new post containing a GitHub PR link that genuinely needs review (open, not the operator's own, not already reviewed by an independent human), spawn a `/pr-review` session via `crew create`, add reactions to the Slack post to signal status, and follow through — watching for replies to comments, resolving threads, and approving once concerns are addressed. Never "comment and leave."

**The intent:** Help teammates land their PRs, not gate them. Be curious and inquisitive, catch genuinely dangerous issues, confirm the code serves the author's stated intent. When a review is non-approving, follow through until the PR is approved, merged, or closed.

## Launch Arguments

`$ARGUMENTS`

### Required

**`channel`** — The Slack channel to watch. Accept any of:
- Channel ID (e.g., `C0AET46NL30`) — use directly.
- Channel name with or without `#` (e.g., `#team-platform-review-requests` or `team-platform-review-requests`) — resolve via `slack_search_channels`.
- Archive URL (e.g., `https://workspace.slack.com/archives/C0AET46NL30`) — parse the `/archives/<ID>` segment.

### Optional

- `--lookback N` (default 5): how many of the most-recent posts to consider on the FIRST run only.
- `--interval <minutes>` (default 5): integer number of minutes for the cron pulse cadence (used for `CronCreate` expression `*/N * * * *`).
- `--bot-logins login1,login2,...` (default: empty list — **empty by design** for generalization; operators should pass their org's review-bot login(s) here, e.g., `claude-maze`, so bot reviews are not counted as independent human reviews): GitHub logins treated as bots and excluded from the "already reviewed by a human" check.
- `--model` (default `'sonnet[1m]'`): model for spawned review and follow-up sessions. Single-quote the value when passing to `crew create` — zsh globs `[1m]` without quotes.

## Requirements (declare and verify on launch)

**Slack MCP server** (REQUIRED — this skill MUST run in an INTERACTIVE session, NOT headless/cron):
- `slack_read_channel` — fetch channel messages
- `slack_add_reaction` — add emoji reactions to posts
- `slack_get_reactions` — read current reactions on posts
- `slack_search_channels` — resolve channel name to ID
- `slack_read_user_profile` — auto-detect operator's Slack user ID

**NOTE: No remove-reaction tool exists in the Slack MCP.** Reaction scheme is add-only (see § Reaction Scheme).

**CLIs:** `gh`, `crew`, `prc`, `prr`, `git`.

**Skills invoked by spawned sessions:** `/pr-review` (specialist team review), `review-pr-comments` / `manage-pr-comments` (PR-comment reply/resolve workflow).

## Operator Identity (Auto-Detected — Never Args)

On launch, auto-detect both:

```bash
# Slack self user ID — the operator's identity in Slack
# Call slack_read_user_profile with no argument → returns the authenticated user's profile
# Extract the user ID field (e.g., U012AB3CD)
```

```bash
# GitHub login — the operator's identity in GitHub
gh api user --jq .login
```

Store both in the state file. Used to:
- **Slack user ID:** Skip posts authored by the operator (the watcher doesn't review its own requests).
- **GitHub login:** "Never review our own PRs" (author == operator login → skip). "Have we already reviewed?" (operator already in reviews → skip or transition to follow-up).

## Launch Sequence

1. **Resolve the channel ID** from the provided argument (parse archive URL, search by name, or use directly).
2. **Auto-detect operator identity** (Slack user ID + GitHub login).
3. **Initialize or load the state file** (`.scratchpad/<channel-id>-review-watcher.json`).
4. **Set `watermark_ts`** — on first run only: fetch the most-recent `lookback` posts; set `watermark_ts` to the timestamp of the `lookback`-th most-recent post (so only newer posts are acted on after the first tick).
5. **Create the watcher cron:**
   ```
   CronCreate(
     expression="*/<interval> * * * *",
     prompt="Run the pr-review-watcher cycle for channel <channel_id>. State file: .scratchpad/<channel_id>-review-watcher.json",
     recurring=true
   )
   ```
6. **Inform the user:**
   - Channel being watched, cron interval, operator identities (Slack + GitHub).
   - "This cron is session-bound — it stops when this session ends."
   - "The cron expires automatically after 7 days. Re-arm or tell me to restart it."

## State File

Path: `.scratchpad/<channel-id>-review-watcher.json`

Read at the START of every cycle. Persist at the END of every cycle. If the file doesn't exist, initialize with schema defaults.

```json
{
  "channel_id": "C...",
  "self_user_id": "U...",
  "github_login": "...",
  "spawn_model": "sonnet[1m]",
  "concurrency_cap": null,
  "bot_logins": [],
  "watermark_ts": "<newest processed slack message ts>",
  "active":   [{"pr": 123, "repo": "owner/repo", "message_ts": "...", "crew": "review-123", "status": "spawning|reviewing"}],
  "followup": [{"pr": 123, "repo": "owner/repo", "message_ts": "...", "crew": "fu-123", "our_review": "COMMENTED"}],
  "queue":    [],
  "done":     [{"pr": 123, "reason": "reviewed-approved | skipped-human-reviewed | skipped-own-pr | skipped-closed | approved-after-followup | merged | error"}]
}
```

**`watermark_ts`:** Only act on posts with `ts > watermark_ts`. On first run, initialize as described in § Launch Sequence.

**`active`:** PRs currently being reviewed by a spawned `crew` session.

**`followup`:** PRs where we posted a non-approving review and are now following through. Each entry has a `crew` window (`fu-<pr>`) that self-pulses via ScheduleWakeup.

**`done`:** Terminal entries. Never re-process a PR found in `done`.

## Reaction Scheme (Add-Only)

The Slack MCP has NO remove-reaction tool. Reactions accumulate:

- **Add 👀 (`eyes`)** — the moment a PR is picked up for review (spawn succeeded).
- **Add ✅ (`white_check_mark`)** — when our LATEST GitHub review on the PR is `APPROVED` (including approval reached via follow-up). 👀 remains alongside (cannot be removed).
- `COMMENTED` / `CHANGES_REQUESTED` → leave 👀 only.

**Enhancement (SLACK_USER_TOKEN detection):** If a `SLACK_USER_TOKEN` environment variable is set and begins with `xoxp-`, call the Slack `reactions.remove` Web API to do a true remove-👀-then-✅ when approval is detected. Detect via: `env | rg '^SLACK_USER_TOKEN=xoxp-'`. If absent, fall back to add-only and tell the user the limitation on first ✅ event.

## Per-Cycle Algorithm

**GUARD:** If `slack_read_channel` fails → log "Slack MCP unavailable — skipping cycle" and stop the cycle (do NOT crash or dismiss anything).

### A) Monitor Active Reviews

For each entry in `active`:

1. Run `gh pr view <pr> --repo <repo> --json state,reviews`
2. Run `crew read <crew-name>` to get pane output

Evaluate:

- **Pane shows buffered/unsubmitted brief** (pane content contains the spawn brief text or a paste placeholder like `[Pasted text #1]`, NO spinner, no tool activity, session never started — this is the PASTED-not-SUBMITTED state): a `crew create --tell` spawn signals `told=true` when the brief is PASTED into the worker's input buffer, NOT when it is SUBMITTED. The brief can sit unsubmitted indefinitely. Recovery: `crew tell <crew> --keys "Enter"` to submit it, then leave the entry active (status: reviewing). This self-healing is expected on normal spawns, not only after trust/MCP modals.
- **Pane shows `SKIPPED-<pr>`** (guard caught a human review mid-bootstrap) → `crew dismiss <crew-name>` + move active→done(`skipped-human-reviewed`). No reaction change.
- **Pane shows `SUPERSEDED-<pr>`** (pre-post check aborted the post — PR was superseded during review) → `crew dismiss <crew-name>` + move active→done(`superseded-race`). Leave any 👀 reaction in place. Do NOT add ✅.
- **Pane shows `REVIEW-POSTED-<pr>` AND our review appears in `gh pr view --json reviews`** → check the review state:
  - `APPROVED` → add ✅ reaction + `crew dismiss <crew-name>` + active→done(`reviewed-approved`).
  - `COMMENTED` or `CHANGES_REQUESTED` → leave 👀 + `crew dismiss <crew-name>` + spawn follow-up session (see § Follow-Up Brief) + move entry active→followup (crew=`fu-<pr>`, our_review=`<state>`). **A non-approving review NEVER just ends.**
- **Pane shows `REVIEW-POSTED-<pr>` but gh not yet showing our review** → wait one tick (leave in active, do nothing).
- **Pane shows stalled / error / context-exhausted / no output for >2 cycles** → surface to user ("review session for PR <pr> appears stalled — manual check needed"). Do NOT auto-dismiss. Leave in active.
- **Otherwise** (still working) → leave in active, do nothing.

### A2) Monitor Follow-Ups

For each entry in `followup`:

1. Run `gh pr view <pr> --repo <repo> --json state,reviews`
2. Run `crew read <crew-name>` to get pane output

Evaluate:

- **Pane shows `SUPERSEDED-<pr>`** (pre-post check aborted an approval — PR was superseded during follow-up) → `crew dismiss fu-<pr>` + followup→done(`superseded-race`). Leave any 👀 reaction in place. Do NOT add ✅.
- **Our LATEST review is `APPROVED`** → add ✅ reaction + `crew dismiss fu-<pr>` + followup→done(`approved-after-followup`).
- **`state != OPEN`** (merged or closed) → `crew dismiss fu-<pr>` + followup→done(`merged` or `closed`).
- **Otherwise** → leave it. The follow-up session self-pulses via ScheduleWakeup (the watcher cron is the backstop that detects completion).

### B) New Posts

Run `slack_read_channel(channel=<channel_id>, limit=15)`.

For each message with `ts > watermark_ts`, where:
- `user != self_user_id` (ignore operator's own posts)
- Message body contains a `github.com/<org>/<repo>/pull/<N>` link

Parse `repo` (as `owner/repo`) and `pr` (integer). Handle both common formats:
- Terse: `"Review please: <link>"`
- Structured: `"Review Request … :github: PR — <link>"`

Skip if `pr` already in `active`, `followup`, `queue`, or `done`.

Otherwise: candidate for review.

Update `watermark_ts = max(watermark_ts, newest ts seen in this batch)`.

### C) Dedup Each Candidate (MANDATORY immediately before spawning)

Run `gh pr view <pr> --repo <repo> --json state,author,reviews,isCrossRepository`.

**SKIP** (record in `done` with reason) if ANY of the following:

- `author.login == github_login` → **never review our own PRs**.
- `state != OPEN` (merged or closed) → skip, record as `skipped-closed`.
- operator (`github_login`) already appears in `reviews` → we already reviewed it; if `APPROVED`, done; if non-approving, should be in `followup` already.
- **Any review by a login that is NEITHER the PR author NOR a login in `bot_logins`** → an independent human already reviewed it → **skip if anybody reviewed**. The PR author's own self-review / self-comment does NOT count as an independent review — authors routinely self-comment to explain their change. Bot reviews do NOT count either.

Only if NONE of the above hold → the PR genuinely needs review.

### D) Spawn Reviews (Maximum Parallelism — No Concurrency Cap)

For each PR that needs review:

1. Add 👀 reaction to the Slack message (`slack_add_reaction(channel=<channel_id>, timestamp=<message_ts>, reaction="eyes")`).
2. Add to `active` with `status: "spawning"` BEFORE spawning (prevents next-tick double-spawn).
3. Persist state file.
4. Determine `repo_path`: derive from the org/repo in the PR link → `~/github.com/<org>/<repo>` (generalized convention; adjust to the actual local checkout path if known from the PR link).
5. Stagger ~6 seconds between parallel spawns to avoid git-worktree lock collisions.
6. Run (with `run_in_background=true`):
   ```
   crew create review-<pr> --repo <repo_path> --base main --model 'sonnet[1m]' --tell "<guarded review brief — SINGLE LINE, no newlines>"
   ```
   **Fork PR** (`isCrossRepository == true`) → omit the `gh pr checkout` step from the brief; pass `--cross-repo` note instead.
   **Worktree-name collision** → append `b` to the crew name (e.g., `review-123b`).
7. Update `active` entry `status` to `"reviewing"`. Persist state.

## The Two Briefs (Spawned Sessions)

**CRITICAL: Both briefs MUST be SINGLE-LINE when passed to `--tell`. Newlines in `--tell` cause early submission — the brief is truncated. Compose as a single line with no literal newlines.**

**Single-quote `sonnet[1m]` in the `crew create` command** — zsh globs `[1m]` without quotes and the model arg is silently mangled.

---

### Guarded Review Brief (pass to `crew create review-<pr>`)

Single-line form (no literal newlines):

`Review PR <pr> (<repo>). Step 1: run \`gh pr checkout <pr>\` (lands the worktree on the PR's exact branch). Step 2: BEFORE reviewing, run \`gh pr view <pr> --json author,reviews\` — extract author.login, then check if any review whose author.login is NEITHER the PR author NOR a known bot (<bot_logins_csv>) exists; the PR author's own self-review / self-comment does NOT count as an independent review (authors routinely self-comment to explain their change) — if such an independent review exists, print \`SKIPPED-<pr>-already-reviewed\` and STOP (do not run /pr-review). Step 3: otherwise run \`/pr-review <pr>\`. The /pr-review skill performs a FINAL PRE-POST CHECK before posting — if the PR is superseded (state!=OPEN, mergedAt non-null, reviewDecision==APPROVED, or reviewed by another real human), it aborts the post and you must print \`SUPERSEDED-<pr>\` and stop. When the review is POSTED, print \`REVIEW-POSTED-<pr>\` and stop. Review-only — no commit/push/branch.`

Where `<bot_logins_csv>` is the comma-separated list from `bot_logins` (e.g., `claude-maze`), or `none` if the list is empty.

**Guarded review brief (fork PR variant):** (use when `isCrossRepository == true` — omit `gh pr checkout` since the fork's head is not directly checkout-able the same way)

`Review PR <pr> (<repo>) [FORK/CROSS-REPO — no direct checkout]. Step 1: BEFORE reviewing, run \`gh pr view <pr> --json author,reviews\` — extract author.login, then check if any review whose author.login is NEITHER the PR author NOR a known bot (<bot_logins_csv>) exists; the PR author's own self-review / self-comment does NOT count as an independent review (authors routinely self-comment to explain their change) — if such an independent review exists, print \`SKIPPED-<pr>-already-reviewed\` and STOP (do not run /pr-review). Step 2: otherwise run \`/pr-review <pr>\`. The /pr-review skill performs a FINAL PRE-POST CHECK before posting — if the PR is superseded (state!=OPEN, mergedAt non-null, reviewDecision==APPROVED, or reviewed by another real human), it aborts the post and you must print \`SUPERSEDED-<pr>\` and stop. When the review is POSTED, print \`REVIEW-POSTED-<pr>\` and stop. Review-only — no commit/push/branch.`

---

### Follow-Up Brief (pass to `crew create fu-<pr>`)

Single-line form (no literal newlines):

`REVIEW FOLLOW-THROUGH for PR <pr> (<repo>). We already posted a non-approving review. Goal: help the author land this PR. Bias toward APPROVE — if the change is safe (no blocking issue: security / data-loss / regression / correctness) and serves the author's stated intent, approve; no nits; bots already review. Confirm intent before flagging a deviation as a defect. Setup once: \`gh pr checkout <pr>\`, then \`prc list <pr> --author <github_login>\` to see our comments. Then self-pulse ~every 5 min via \`ScheduleWakeup\`(270s): (1) \`git pull\`; (2) check replies to our comments via \`prc list <pr>\` + unresolved threads; (3) per reply — if the author addressed it, verify the fix truly resolves it and serves the author's intent, then resolve the thread via \`prc reply <comment_id> '<ack>'\` + \`prc resolve <thread_id>\`; if more is needed, research and post a friendly reply using tentative phrasing (e.g. 'might be worth ...' / 'could be worth considering ...', not 'you should ...'); if waiting, leave it; (4) when ALL concerns are resolved and the change is safe, run FINAL PRE-POST CHECK: \`gh pr view <pr> --json author,state,mergedAt,reviewDecision,reviews,latestReviews\` — if state!=OPEN, mergedAt non-null, reviewDecision==APPROVED, or any real human who is NOT the PR author (the PR author's own self-review / self-comment does NOT count — authors routinely self-comment to explain their change) and not a bot (login not ending in [bot], type==User) has reviewed, print \`SUPERSEDED-<pr>\` and stop; otherwise APPROVE (\`prr submit <pr> --event APPROVE\` or \`gh pr review <pr> --approve\`) then print \`FOLLOWUP-APPROVED-<pr>\` and stop; (5) if merged/closed, print \`FOLLOWUP-DONE-<pr>\` and stop; (6) else schedule the next pulse and end. Do NOT modify PR code. Be curious; catch dangerous things.`

## Worktree / Branch Mechanism (Hard-Won — Get This Right)

- `crew create` always creates a **new** branch off `--base` for the worktree. It CANNOT directly check out a teammate's existing remote branch. The spawned session runs `gh pr checkout <pr>` as its **first step** — this reliably lands the worktree on the PR's exact head branch. Confirmed working.
- **Model:** Repos with heavy startup-context injection (many auto-loaded rules/CLAUDE.md/scoped skills — e.g., a large monorepo) blow past standard Sonnet's 200k context window and auto-compact before the first deliverable. Default spawns to `sonnet[1m]`. Symptom if skipped: "0% until auto-compact" within minutes of spawn.
- **Do NOT use `crew resume`** to revive a heavy-context session — `crew resume` relaunches without `--model`, dropping it to default Sonnet and triggering immediate compaction. Re-spawn fresh instead.

## Lifecycle, Dedup Philosophy, and Gotchas

### Dedup Philosophy

**"Skip if anybody (an independent human, not the author, not a bot) has reviewed."**

Teammates often approve faster than we can spin up. Re-check reviewers in BOTH:
1. **Dedup step (§ C)** — before spawning.
2. **Inside the guarded brief** — right before `/pr-review` runs (human approvals frequently land during the bootstrap window).

This is what prevents wasted/duplicate reviews. The two-layer check is intentional — not redundant.

### Never Review Own PRs

If `author.login == github_login`, skip unconditionally. Record in `done` with `reason: "skipped-own-pr"`.

### Cron Exemption

The watcher cron MUST persist even when there are zero active reviews — it has to catch new posts. If a `pulse-cron-lifecycle` style hook tries to self-terminate "when zero crew windows remain," this watcher cron must be **exempt**. It is not a crew-monitoring pulse cron.

### Single-Line `--tell`

Newlines in `--tell` cause the shell to submit the command early — the brief is truncated. Compose briefs as a single line. No literal `\n` or multi-line heredoc.

### Stagger Parallel Spawns

Stagger ~6 seconds between parallel `crew create` calls to avoid git-worktree lock collisions when multiple PRs are picked up in the same cycle.

### Background Everything

All `crew create` calls use `run_in_background=true`. A blocking spawn can take minutes (pnpm bootstrap, large repo setup). Blocking the cron tick causes queued firings to pile up. Background everything — keep cron ticks short.

### Mark `spawning` Before Spawning

Add the entry to `active` with `status: "spawning"` and persist the state file BEFORE calling `crew create`. This prevents the next tick from double-spawning the same PR before the crew window appears.

### `/pr-review` Integration

`/pr-review` posts via `prr` as a real GitHub review (detectable via `gh pr view --json reviews`). It short-circuits its worktree-setup phase when already inside a worktree (the guarded brief's `gh pr checkout` sets this up). The sentinel strings `REVIEW-POSTED-<pr>` and `SKIPPED-<pr>-already-reviewed` are what the watcher reads via `crew read`.

### Worktree Cruft

`crew dismiss` kills the tmux window but does NOT remove the git worktree. Dismissed review/follow-up sessions leave orphaned worktrees (each a full bootstrapped checkout — real disk usage). The skill should:
1. Track spawned worktree names in the state file alongside each `active`/`followup` entry.
2. When dismissing a session, offer or perform cleanup: `git worktree remove <path>` (with `--force` if needed for dirty worktrees). Warn the user if cleanup is skipped.

**Re-spawning the same PR:** If you dismiss a review session and immediately re-spawn the same PR, `gh pr checkout <pr>` in the new session may fail with "already checked out in another worktree" — `crew dismiss` killed the tmux window but the git worktree still exists on disk. Before re-spawning, prune the prior worktree (`git worktree remove <path> --force` or `git worktree prune`). If pruning is not possible, the re-spawned session can still review via `gh pr diff <pr>` (diff fetched by number) without requiring a worktree-on-exact-branch.

### Report Discipline

Emit ONE concise line only when something changed: review posted / follow-up spawned / approved / reacted / dismissed / new post detected / error / stall. Otherwise stay silent. Do NOT emit per-tick heartbeat noise.

## Follow-Up Self-Pulse Pattern

The follow-up brief uses `ScheduleWakeup(270)` (~5 minutes) to self-pulse. This is the primary mechanism. The watcher cron is the **backstop**: on each cron tick, step A2 checks `gh pr view --json state,reviews` for every `followup` entry and acts if:
- Our LATEST review is `APPROVED` → ✅ + dismiss + done.
- PR is merged/closed → dismiss + done.

The backstop pattern remains regardless of whether the follow-up session's self-pulse is reliable. Both mechanisms run; the first to detect a terminal state wins (the state file update prevents double-processing on the next tick).

## Open Question Resolution (§13)

Implemented as BOTH:
- **(a) Self-pulse:** The follow-up brief schedules its own `ScheduleWakeup(270s)` continuation — primary mechanism for timely follow-through.
- **(b) Watcher cron backstop:** Step A2 detects approved/merged follow-ups on every tick and reacts/dismisses regardless of whether the self-pulse fired. This is the safety net.

The backstop pattern is non-negotiable and always present.

## Generalization Notes

This skill is fully generalized:
- The **channel** is a required argument — not hardcoded.
- **Operator identity** (Slack user ID, GitHub login) is auto-detected at runtime — not hardcoded.
- **Repo paths** are derived from the PR links (e.g., `~/github.com/<org>/<repo>`). Adjust the path convention to match the local checkout structure if it differs.
- The **bot-exclusion list** is a configurable argument with an empty default — pass your org review bot's GitHub login via `--bot-logins`.

The Maze-specific examples in the original spec (`C0AET46NL30`, `claude-maze`, `maze-monorepo`, `~/github.com/mazedesignhq/<repo>`) are illustrative only. Do not hardcode them. This skill works for any team's Slack review-request channel and GitHub repos.

## Complete Cycle Pseudocode

```
CYCLE START:
  read state file
  if slack_read_channel fails → log "Slack MCP unavailable" → stop cycle

  A) for each active entry:
       get pr state + reviews (gh pr view)
       get pane output (crew read)
       → buffered/unsubmitted brief (PASTED not SUBMITTED): crew tell <crew> --keys "Enter" + leave active
       → SKIPPED sentinel: dismiss + done(skipped)
       → SUPERSEDED sentinel: dismiss + done(superseded-race), leave 👀, no ✅
       → REVIEW-POSTED + review visible in gh:
           APPROVED: add ✅ + dismiss + done(reviewed-approved)
           COMMENTED/CHANGES_REQUESTED: dismiss + spawn follow-up + move to followup
       → REVIEW-POSTED but not yet in gh: wait tick
       → stalled/error: surface to user, leave in active

  A2) for each followup entry:
       get pr state + reviews (gh pr view)
       get pane output (crew read)
       → SUPERSEDED sentinel: dismiss + done(superseded-race), leave 👀, no ✅
       → APPROVED: add ✅ + dismiss + done(approved-after-followup)
       → state != OPEN: dismiss + done(merged/closed)
       → otherwise: leave it (self-pulses via ScheduleWakeup)

  B) slack_read_channel(limit=15)
       for each msg ts > watermark, author != self_user_id, contains github PR link:
         parse repo + pr
         skip if in active/followup/queue/done
         → candidate
       update watermark_ts

  C+D) for each candidate:
       gh pr view --json state,author,reviews,isCrossRepository
       skip if: own PR | closed | already reviewed by operator | independent human reviewed
       → needs review:
           add 👀 reaction
           add to active (status: spawning)
           persist state
           crew create review-<pr> ... --tell "<guarded brief>" (background, stagger 6s)
           update status: reviewing
           persist state

  persist final state
CYCLE END
```
