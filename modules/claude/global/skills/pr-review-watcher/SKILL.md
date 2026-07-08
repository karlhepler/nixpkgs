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
- `--restricted-output-authors login1,login2,...` (default: empty list — **empty by design** for generalization, same convention as `--bot-logins` above; operators supply their own author logins here): GitHub logins whose PRs are routed into **Restricted-Output Review Mode** (see § Restricted-Output Review Mode) instead of the normal review path. The actual login(s) are operator configuration — never hardcode a specific login in this skill file.
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
  "restricted_output_review_authors": [],
  "watermark_ts": "<newest processed slack message ts>",
  "active":   [{"pr": 123, "repo": "owner/repo", "message_ts": "...", "crew": "review-123", "status": "spawning|reviewing"}],
  "followup": [{"pr": 123, "repo": "owner/repo", "message_ts": "...", "crew": "fu-123", "our_review": "COMMENTED"}],
  "awaiting_decision": [{"pr": 123, "repo": "owner/repo", "message_ts": "...", "crew": "review-123", "verdict": "CHANGES_REQUESTED | COMMENT | ...", "summary": "<one-line escalated summary>"}],
  "queue":    [],
  "done":     [{"pr": 123, "reason": "reviewed-approved | skipped-human-reviewed | skipped-own-pr | skipped-closed | approved-after-followup | merged | error | operator-dropped"}]
}
```

**`watermark_ts`:** Only act on posts with `ts > watermark_ts`. On first run, initialize as described in § Launch Sequence.

**`active`:** PRs currently being reviewed by a spawned `crew` session.

**`followup`:** PRs where we posted a non-approving review and are now following through. Each entry has a `crew` window (`fu-<pr>`) that self-pulses via ScheduleWakeup.

**`awaiting_decision`:** Review sessions that reached a verdict requiring an operator decision (e.g., a restricted-output review that escalated with `ESCALATE-<pr>`) but are being HELD ALIVE (idle) — NOT dismissed — pending that decision. Each entry records the crew window name and the escalated `verdict` + `summary` so the decision can be relayed to the still-live session via `crew tell`. Entries leave this bucket only after the operator decides AND the same still-alive session executes that decision; then the session is dismissed and the entry moves to `done`.

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

- **Pane shows buffered/unsubmitted brief** (pane content contains the spawn brief text or a paste placeholder like `[Pasted text #1]`, NO spinner, no tool activity, session never started — this is the PASTED-not-SUBMITTED state): a `crew create --tell` spawn signals `told=true` when the brief is PASTED into the worker's input buffer, NOT when it is SUBMITTED. The brief can sit unsubmitted indefinitely. Recovery: `crew tell <crew> --keys "Enter"` to submit it, then leave the entry active (status: reviewing). This self-healing is expected on normal spawns, not only after trust/MCP modals (the same paste-then-submit semantics apply to `--tell-file` spawns — the file content is delivered through the identical paste/Enter mechanism).
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

### A3) Monitor Awaiting-Decision Reviews

For each entry in `awaiting_decision` (review sessions escalated to the operator and HELD ALIVE per § Restricted-Output Review Mode → Escalation handling):

- **No operator decision yet** → the entry stays held. Do NOT dismiss the crew session and do NOT add ✅ — keep the session alive (idle) so it retains its full review context. Re-surface the pending verdict + summary to the operator per § Report Discipline (stay silent unless something changed — no per-tick heartbeat noise).
- **Operator has decided AND the decision has been relayed to and executed BY THE SAME still-alive session** (via `crew tell <crew>`) → branch by what was actually executed:
  - **Executed decision = APPROVE** → add ✅ + `crew dismiss <crew>` + move `awaiting_decision`→`done` (reason: `reviewed-approved`).
  - **Executed decision = operator says drop it (nothing posted)** → `crew dismiss <crew>` + move `awaiting_decision`→`done` (reason: `operator-dropped`).
  - **Executed decision = a real COMMENTED or CHANGES_REQUESTED review was posted** → move the entry `awaiting_decision`→`followup` (`our_review=<state>`), keeping the same still-alive session as the follow-up host, and follow through via § A2 / the Follow-Up loop exactly as the normal `active`→`followup` branch does at § A) Monitor Active Reviews. Do NOT dismiss-to-done in this case. **A posted non-approving review NEVER just ends.** This routes to followup exactly as the normal review path does.

  Never dismiss-then-respawn a fresh session to execute the decision.

Entries in `awaiting_decision` are still visible to the normal dedup/skip check in § B — a PR held here is NOT re-spawned as a new candidate (only § B checks bucket membership against `active`/`followup`/`awaiting_decision`/`queue`).

### B) New Posts

Run `slack_read_channel(channel=<channel_id>, limit=15)`.

For each message with `ts > watermark_ts`, where:
- `user != self_user_id` (ignore operator's own posts)
- Message body contains a `github.com/<org>/<repo>/pull/<N>` link

Parse `repo` (as `owner/repo`) and `pr` (integer). Handle both common formats:
- Terse: `"Review please: <link>"`
- Structured: `"Review Request … :github: PR — <link>"`

**Re-review detection (check BEFORE the skip-if-in-done path):** If the parsed `pr` is in `done` AND the post body contains re-review language — any of: `re-review`, `re review`, `addressed`, `resolved your comments`, `resolved all comments`, `resolved the comments`, `fixed the comments`, `updated since last review`, `updated since your review` — route to the **straight-approval flow** instead of the normal candidate path:

1. Re-fetch PR state: `gh pr view <pr> --repo <repo> --json author,state,mergedAt,reviewDecision,reviews,latestReviews`.
2. **If `state != OPEN` or `mergedAt` non-null** → nothing to do; skip silently.
3. **If `reviewDecision == APPROVED` AND at least one approving review is from a real human** (not a bot/auto-approval account — login does NOT end in `[bot]`, `gh api users/<login>` returns HTTP 200, `type == "User"`) → a human approval already stands; acknowledge with a ✅ reaction on the Slack post and stop. Do NOT post a duplicate approval. A `reviewDecision == APPROVED` satisfied SOLELY by bot/auto-approval accounts does NOT count as a standing approval — proceed to step 5.
4. **If any non-author, non-bot, non-operator login in `reviews` has `state == CHANGES_REQUESTED`** → genuinely blocked by a peer; leave it; skip silently.
5. **Otherwise** (our prior approval was dismissed by a new push, or we previously only COMMENTED / CHANGES_REQUESTED and the PR still needs our approval) → post a **straight approval**: `prr submit <pr> --repo <repo> --event APPROVE` with a brief friendly body (`"Thanks for addressing the comments — looks good."`). No new findings. No new inline comments. No re-litigating. Add ✅ reaction to the Slack post. Update the `done` entry reason to `straight-approved-re-review`.

Skip if `pr` already in `active`, `followup`, `awaiting_decision`, or `queue` (not yet processed).

For posts that contain a PR link but no re-review language and the PR is already in `done` → skip (normal behavior).

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

**Restricted-output routing check (run immediately after the above SKIP checks pass):** If `author.login` is in `restricted_output_review_authors`, this candidate does NOT follow the normal spawn path in § D below — route it into **Restricted-Output Review Mode** instead (see § Restricted-Output Review Mode). Normal dedup (own-PR, closed, already-reviewed-by-operator, already-independently-reviewed) still applies identically before this check; restricted routing only changes what happens AFTER dedup passes.

### D) Spawn Reviews (Maximum Parallelism — No Concurrency Cap)

For each PR that needs review AND whose author is NOT in `restricted_output_review_authors`:

1. Add 👀 reaction to the Slack message (`slack_add_reaction(channel=<channel_id>, timestamp=<message_ts>, reaction="eyes")`).
2. Add to `active` with `status: "spawning"` BEFORE spawning (prevents next-tick double-spawn).
3. Persist state file.
4. Determine `repo_path`: derive from the org/repo in the PR link → `~/github.com/<org>/<repo>` (generalized convention; adjust to the actual local checkout path if known from the PR link).
5. Stagger ~6 seconds between parallel spawns to avoid git-worktree lock collisions.
6. Compose the guarded review brief (see § Guarded Review Brief) as a single line with all `<pr>`/`<repo>`/`<bot_logins_csv>` substitutions filled, and write it to `.scratchpad/<pr>-guarded-review-brief.md`.
7. Run (with `run_in_background=true`):
   ```
   crew create review-<pr> --repo <repo_path> --base main --model 'sonnet[1m]' --tell-file .scratchpad/<pr>-guarded-review-brief.md
   ```
   **Fork PR** (`isCrossRepository == true`) → omit the `gh pr checkout` step from the brief; pass `--cross-repo` note instead.
   **Worktree-name collision** → append `b` to the crew name (e.g., `review-123b`).
8. Update `active` entry `status` to `"reviewing"`. Persist state.

## Restricted-Output Review Mode

**Trigger:** A candidate PR (post-dedup, § C) whose `author.login` is in `restricted_output_review_authors`.

**Intent:** Run the exact same full specialist review as normal — no shortcuts on analysis — but constrain what gets written back to GitHub to a single safe outcome: silent approval when clean, or nothing-plus-escalation when not. This mode exists for authors where the operator wants eyes-on-everything internally but does not want automated review comments landing on their PRs unless the operator has personally triaged them.

**Routing (instead of § D normal spawn):**

1. Add 👀 reaction to the Slack message, same as normal spawn.
2. Add to `active` with `status: "spawning"` BEFORE spawning, same as normal spawn.
3. Persist state file.
4. Determine `repo_path`, same convention as § D.
5. Stagger ~6 seconds between parallel spawns, same as § D.
6. Compose the restricted-output review brief (see below) as a single line with all `<pr>`/`<repo>`/`<bot_logins_csv>` substitutions filled, and write it to `.scratchpad/<pr>-restricted-review-brief.md`.
7. Run (with `run_in_background=true`):
   ```
   crew create review-<pr> --repo <repo_path> --base main --model 'sonnet[1m]' --tell-file .scratchpad/<pr>-restricted-review-brief.md
   ```
8. Update `active` entry `status` to `"reviewing"`. Persist state.

**Restricted-output review brief (deliver via `crew create review-<pr> ... --tell-file <path>`):**

Compose as a single line (no literal newlines), write it to `.scratchpad/<pr>-restricted-review-brief.md`, then pass that path via `--tell-file` (never inline `--tell`) — otherwise identical setup to the Guarded Review Brief (checkout, independent-review pre-check, sentinel printing). Restricted-output briefs are also long, so they use `--tell-file` — see § Single-Line `--tell` and Length-Based Truncation:

`Review PR <pr> (<repo>) [RESTRICTED-OUTPUT MODE]. Step 1: run \`gh pr checkout <pr>\` (lands the worktree on the PR's exact branch). Step 2: BEFORE reviewing, run \`gh pr view <pr> --json author,reviews\` — extract author.login, then check if any review whose author.login is NEITHER the PR author NOR a known bot (<bot_logins_csv>) exists; the PR author's own self-review / self-comment does NOT count as an independent review — if such an independent review exists, print \`SKIPPED-<pr>-already-reviewed\` and STOP (do not run /pr-review). Step 3: otherwise run \`/pr-review <pr> --restricted-output\` — this tells /pr-review to run its full internal specialist review as normal, but restrict the GitHub write to exactly one of: (a) a clean APPROVE with empty body and zero inline comments, posted silently, or (b) nothing posted at all, with the verdict and a short summary reported back to you instead. Step 4: if /pr-review reports back a non-clean verdict (case b), print \`ESCALATE-<pr>: <verdict + one-line summary>\` and stop — do NOT post anything to the PR yourself. Step 5: if /pr-review silently approved (case a), print \`REVIEW-POSTED-<pr>\` and stop. The /pr-review skill's FINAL PRE-POST CHECK still applies before any write — if the PR is superseded, print \`SUPERSEDED-<pr>\` and stop. Review-only — no commit/push/branch.`

Where `<bot_logins_csv>` is the comma-separated list from `bot_logins`, or `none` if empty.

**Follow-up loop disabled:** Restricted-output mode never posts a COMMENT or CHANGES_REQUESTED review — the only possible outputs are a silent APPROVE or nothing-plus-escalation. There is no comment thread to follow through on, so these PRs never enter `followup`. When the spawned session prints `REVIEW-POSTED-<pr>` (silent approve case), handle it exactly like § A) Monitor Active Reviews' `APPROVED` branch: add ✅ + dismiss + `active`→`done(reviewed-approved)`.

**Escalation handling:** When the spawned session prints `ESCALATE-<pr>: <verdict + summary>`, do NOT dismiss the crew session. Instead, **keep the review session alive** (idle) and move the entry `active`→`awaiting_decision`, recording the crew window name and the escalated `verdict` + `summary`. Surface the verdict + summary to the operator per § Report Discipline — do NOT post anything to the PR. Leave 👀 in place; do NOT add ✅.

Only after the operator decides AND that decision is executed BY THE SAME still-alive session do you act — branch by what was actually executed:
- **Executed decision = APPROVE** → add ✅ + `crew dismiss <crew>` + move `awaiting_decision`→`done` (reason: `reviewed-approved`).
- **Executed decision = operator says drop it (nothing posted)** → `crew dismiss <crew>` + move `awaiting_decision`→`done` (reason: `operator-dropped`).
- **Executed decision = a real COMMENTED or CHANGES_REQUESTED review was posted** → move `awaiting_decision`→`followup` (`our_review=<state>`), keeping the same still-alive session as the follow-up host, and follow through via § A2 / the Follow-Up loop exactly as the normal review path does. Do NOT dismiss-to-done in this case. **A posted non-approving review NEVER just ends.**

Relay the operator's decision to the live session via `crew tell <crew>` (e.g., submit the approval / post the agreed comments / request changes / drop it) — the session still holds the full review context and is best positioned to execute the decided action. Never dismiss-then-respawn a fresh session just to execute the operator's decision.

**Normal dedup still applies:** Skip if the PR is closed, is the operator's own PR, has already been independently human-reviewed, or is already `APPROVED` by a human-only review — exactly the same § C checks that apply to normal candidates, run BEFORE the restricted-output routing check.

## The Two Briefs (Spawned Sessions)

**CRITICAL: Both briefs MUST be composed as SINGLE-LINE text (no literal newlines) and delivered via `crew create --tell-file <path>` — NEVER inline `--tell`. Newlines in `--tell` cause early submission, and raw length above ~800-1000 chars (truncation observed near 1KB) causes silent length-based truncation (a mid-word cut, no special character required) even without newlines. Write each composed brief to a `.scratchpad/` file first, then pass the path via `--tell-file`.**

**Single-quote `sonnet[1m]` in the `crew create` command** — zsh globs `[1m]` without quotes and the model arg is silently mangled.

---

### Guarded Review Brief (deliver via `crew create review-<pr> ... --tell-file <path>`)

Compose as a single line (no literal newlines), write it to `.scratchpad/<pr>-guarded-review-brief.md`, then pass that path via `--tell-file` (never inline `--tell` — see § The Two Briefs and § Single-Line `--tell` and Length-Based Truncation):

`Review PR <pr> (<repo>). Step 1: run \`gh pr checkout <pr>\` (lands the worktree on the PR's exact branch). Step 2: BEFORE reviewing, run \`gh pr view <pr> --json author,reviews\` — extract author.login, then check if any review whose author.login is NEITHER the PR author NOR a known bot (<bot_logins_csv>) exists; the PR author's own self-review / self-comment does NOT count as an independent review (authors routinely self-comment to explain their change) — if such an independent review exists, print \`SKIPPED-<pr>-already-reviewed\` and STOP (do not run /pr-review). Step 3: otherwise run \`/pr-review <pr>\`. The /pr-review skill performs a FINAL PRE-POST CHECK before posting — if the PR is superseded (state!=OPEN, mergedAt non-null, reviewDecision==APPROVED by a real-human reviewer (not a bot or auto-approval account), or reviewed by another real human), it aborts the post and you must print \`SUPERSEDED-<pr>\` and stop. When the review is POSTED, print \`REVIEW-POSTED-<pr>\` and stop. Review-only — no commit/push/branch.`

Where `<bot_logins_csv>` is the comma-separated list from `bot_logins` (e.g., `claude-maze`), or `none` if the list is empty.

**Guarded review brief (fork PR variant):** (use when `isCrossRepository == true` — omit `gh pr checkout` since the fork's head is not directly checkout-able the same way; write this text to the same `.scratchpad/<pr>-guarded-review-brief.md` file instead of the base form)

`Review PR <pr> (<repo>) [FORK/CROSS-REPO — no direct checkout]. Step 1: BEFORE reviewing, run \`gh pr view <pr> --json author,reviews\` — extract author.login, then check if any review whose author.login is NEITHER the PR author NOR a known bot (<bot_logins_csv>) exists; the PR author's own self-review / self-comment does NOT count as an independent review (authors routinely self-comment to explain their change) — if such an independent review exists, print \`SKIPPED-<pr>-already-reviewed\` and STOP (do not run /pr-review). Step 2: otherwise run \`/pr-review <pr>\`. The /pr-review skill performs a FINAL PRE-POST CHECK before posting — if the PR is superseded (state!=OPEN, mergedAt non-null, reviewDecision==APPROVED by a real-human reviewer (not a bot or auto-approval account), or reviewed by another real human), it aborts the post and you must print \`SUPERSEDED-<pr>\` and stop. When the review is POSTED, print \`REVIEW-POSTED-<pr>\` and stop. Review-only — no commit/push/branch.`

---

### Follow-Up Brief (deliver via `crew create fu-<pr> ... --tell-file <path>`)

**Converted to `--tell-file` delivery:** this brief is ~1965 characters — well above the ~800-1000 char threshold in § Single-Line `--tell` and Length-Based Truncation — so it is delivered the same way as the Guarded and Restricted-Output briefs, never inline `--tell`.

Compose as a single line (no literal newlines), write it to `.scratchpad/<pr>-followup-brief.md`, then pass that path via `crew create fu-<pr> ... --tell-file .scratchpad/<pr>-followup-brief.md`:

`REVIEW FOLLOW-THROUGH for PR <pr> (<repo>). We already posted a non-approving review. Goal: help the author land this PR. Bias toward APPROVE — if the change is safe (no blocking issue: security / data-loss / regression / correctness) and serves the author's stated intent, approve; no nits; bots already review. Confirm intent before flagging a deviation as a defect. Setup once: \`gh pr checkout <pr>\`, then \`prc list <pr> --author <github_login>\` to see our comments. Then self-pulse ~every 5 min via \`ScheduleWakeup\`(270s): (1) \`git pull\`; (2) check replies to our comments via \`prc list <pr>\` + unresolved threads; (3) per reply — if the author addressed it, verify the fix truly resolves it and serves the author's intent, then resolve the thread via \`prc reply <comment_id> '<ack>'\` + \`prc resolve <thread_id>\`; if more is needed, research and post a friendly reply using tentative phrasing (e.g. 'might be worth ...' / 'could be worth considering ...', not 'you should ...'); if waiting, leave it; (4) when ALL concerns are resolved and the change is safe, run FINAL PRE-POST CHECK: \`gh pr view <pr> --json author,state,mergedAt,reviewDecision,reviews,latestReviews\` — if state!=OPEN, mergedAt non-null, reviewDecision==APPROVED by a real-human reviewer (not a bot or auto-approval account; login not ending in [bot], \`gh api users/<login>\` returns HTTP 200, type==User), or any real human who is NOT the PR author (the PR author's own self-review / self-comment does NOT count — authors routinely self-comment to explain their change) and not a bot (login not ending in [bot], type==User) has reviewed, print \`SUPERSEDED-<pr>\` and stop; otherwise APPROVE (\`prr submit <pr> --event APPROVE\` or \`gh pr review <pr> --approve\`) then print \`FOLLOWUP-APPROVED-<pr>\` and stop; (5) if merged/closed, print \`FOLLOWUP-DONE-<pr>\` and stop; (6) else schedule the next pulse and end. Do NOT modify PR code. Be curious; catch dangerous things.`

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

### Single-Line `--tell` and Length-Based Truncation

Inline `--tell` has TWO independent truncation failure modes — guard against both:

- **Newline-triggered:** newlines in `--tell` cause the shell to submit the command early — the brief is truncated mid-line. Compose briefs as a single line. No literal `\n` or multi-line heredoc.
- **Length-based truncation:** even a newline-free, single-line brief above ~800-1000 characters can be silently truncated on delivery — no special character required, raw length alone triggers it (observed: a ~1900-char single-line brief was cut mid-word around ~1KB, leaving the spawned session blocked on a malformed brief and costing a full cron cycle).

**Rule:** long briefs (above ~800-1000 chars (truncation observed near 1KB)) MUST be delivered via `crew create --tell-file <path>` — write the composed brief to a `.scratchpad/` file first, then pass the path. Reserve inline `--tell` for short briefs and short pointers only. All three spawned-session briefs in this skill (Guarded, Restricted-Output, Follow-Up — see § The Two Briefs) exceed this threshold and are delivered via `--tell-file`.

### Stagger Parallel Spawns

Stagger ~6 seconds between parallel `crew create` calls to avoid git-worktree lock collisions when multiple PRs are picked up in the same cycle.

### Serialize Worktree ADD/REMOVE (review→follow-up transition)

**Never run `git worktree remove` on a repo while a `crew create` (git worktree add) on the SAME repo is in-flight.** Concurrent add/remove operations contend on the repo's `.git/worktrees` administrative lock, which can stall the `crew create` for minutes. Symptom: the spawn task is still running, fetches have printed, but no `<created ...>` line appears and `crew status` shows no new window — this looks like a hang but is lock contention, not a crash.

This is distinct from § Stagger Parallel Spawns above, which covers ADD/ADD collisions between two parallel `crew create` calls. This rule covers ADD/REMOVE: one `crew create` (add) racing a `git worktree remove` on the same repo.

Serialize one of two ways:
- **(a) Add-then-remove (preferred for the review→follow-up transition):** spawn `fu-<pr>` via `crew create`, WAIT for its `<created ...>` line (spawn-task completion) — this keeps a Staff window alive for pulse-cron stability, per § A) Monitor Active Reviews — THEN dismiss the review session and run `git worktree remove` on its worktree (see § Worktree Cruft for cleanup mechanics).
- **(b) Remove-then-add (fully serial):** remove the old worktree first, then spawn the new session.

For the review→follow-up transition specifically: spawning `fu-<pr>` before dismissing the review session is correct and must be preserved — but the review-worktree removal MUST wait until the fu spawn's `<created ...>` line is observed, never fired concurrently with it.

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
- The **restricted-output-authors list** is a configurable argument with an empty default (`restricted_output_review_authors`), following the same convention as the bot-exclusion list — pass author logins that should get Restricted-Output Review Mode via `--restricted-output-authors`. No specific login is hardcoded anywhere in this skill.

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

  A3) for each awaiting_decision entry:
       → no operator decision yet: HELD ALIVE — do NOT dismiss, keep session idle (retains review context)
       → operator decided AND decision relayed to + executed by the SAME still-alive session (crew tell):
           executed = APPROVE: add ✅ + dismiss + done(reviewed-approved)
           executed = drop it (nothing posted): dismiss + done(operator-dropped)
           executed = COMMENTED/CHANGES_REQUESTED posted: move to followup (our_review=<state>) —
             exactly as the normal review path does; a posted non-approving review NEVER just ends
       (never dismiss-then-respawn a fresh session to execute the decision)

  B) slack_read_channel(limit=15)
       for each msg ts > watermark, author != self_user_id, contains github PR link:
         parse repo + pr
         if pr in done AND post has re-review language → straight-approval flow (see § B) New Posts)
         skip if in active/followup/awaiting_decision/queue
         if pr in done (no re-review language) → skip
         → candidate
       update watermark_ts

  C+D) for each candidate:
       gh pr view --json state,author,reviews,isCrossRepository
       skip if: own PR | closed | already reviewed by operator | independent human reviewed
       → needs review AND author in restricted_output_review_authors:
           add 👀 reaction, add to active (status: spawning), persist state
           write restricted-output brief to .scratchpad/<pr>-restricted-review-brief.md
           crew create review-<pr> ... --tell-file .scratchpad/<pr>-restricted-review-brief.md (background, stagger 6s)
           update status: reviewing, persist state
           (see § Restricted-Output Review Mode — silent APPROVE or escalate-to-operator only)
       → needs review (author NOT restricted):
           add 👀 reaction
           add to active (status: spawning)
           persist state
           write guarded brief to .scratchpad/<pr>-guarded-review-brief.md
           crew create review-<pr> ... --tell-file .scratchpad/<pr>-guarded-review-brief.md (background, stagger 6s)
           update status: reviewing
           persist state

  persist final state
CYCLE END
```
