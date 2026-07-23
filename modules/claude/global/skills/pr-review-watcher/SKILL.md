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

**The authority model — findings-first is the DEFAULT for EVERY review, ALL authors (no configured subset):** The watcher NEVER editorializes onto a PR autonomously. Every review, regardless of author, is findings-first. If a PR is cleanly approvable, it gets a silent empty APPROVE with no human round-trip. If it is NOT clean, the coordinator is NOT authorized to post any comment (inline or body) or a change-request on its own — instead the spawned review session RETURNS its structured findings (an enumerable list of candidate comments) and is HELD ALIVE (idle) while the coordinator walks the operator through each candidate ONE AT A TIME via `AskUserQuestion`. Each candidate is surfaced with an ELI5 of any technical concept plus enough PR background/context for the operator to decide, and the operator says per-finding whether a comment should be posted and what it should say. Autonomous write authority for a review is limited to exactly one outcome: a clean empty APPROVE. Everything else — any comment, any change-request — requires per-finding human confirmation. The reviewer is a findings-generator plus an operator-directed comment-poster; it always comes to the operator first, one issue at a time. A severity floor further constrains what even reaches that per-finding walkthrough: nit-severity findings are never surfaced to the operator and never posted — the default severity floor for surfacing and posting is concern-level (see § Findings-First Review Model → Severity Floor).

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
- `--restricted-output-authors login1,login2,...` (**DEPRECATED / no-op — retained only for backward-compatible arg parsing**): findings-first review is now the DEFAULT for every review and every author (see § Findings-First Review Model), so this argument no longer gates anything — it does not change routing for any author. It is still accepted silently so existing launch commands do not break, but it selects nothing: all authors already get findings-first behavior. Do not rely on it; it will be removed once no launch commands pass it.
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
  "followup": [{"pr": 123, "repo": "owner/repo", "message_ts": "...", "crew": "fu-123", "our_review": "CHANGES_REQUESTED"}],
  "awaiting_decision": [{"pr": 123, "repo": "owner/repo", "message_ts": "...", "crew": "review-123", "verdict": "CHANGES_REQUESTED | COMMENT | ...", "summary": "<one-line escalated summary>", "findings": [{"idx": 1, "file": "src/x.go", "line": 42, "severity": "concern", "comment": "<candidate comment text>"}], "walkthrough_idx": 0}],
  "queue":    [],
  "done":     [{"pr": 123, "reason": "reviewed-approved | skipped-human-reviewed | skipped-own-pr | skipped-closed | approved-after-followup | merged | error | operator-dropped"}]
}
```

**`watermark_ts`:** Only act on posts with `ts > watermark_ts`. On first run, initialize as described in § Launch Sequence.

**`active`:** PRs currently being reviewed by a spawned `crew` session.

**`followup`:** PRs where we posted a non-approving review and are now following through. Each entry has a `crew` window (`fu-<pr>`) that self-pulses via ScheduleWakeup.

**`awaiting_decision`:** Non-clean review sessions (the review found something that would call for a comment or change-request) that are being HELD ALIVE (idle) — NOT dismissed — pending the per-finding operator walkthrough (see § Findings-First Review Model → Per-Finding Walkthrough). Each entry records the crew window name, the escalated `verdict` + `summary`, the enumerable `findings` list (the candidate comments the coordinator walks the operator through, one at a time), and `walkthrough_idx` (the index of the next candidate to surface). The still-alive session retains full review context; it ACCUMULATES the operator-approved comments relayed via `crew tell` and, at walkthrough end, submits ONE unified review — executing the operator's decision. Entries leave this bucket only after the walkthrough is complete AND the still-alive session has submitted the resulting review. On an APPROVE — whether a clean empty approve or an **APPROVE-with-comments** carrying accumulated operator-approved comments — or an operator-drop, the session is dismissed and the entry moves to `done`: an APPROVE terminal is a normal completion, not a non-approving-review follow-up. On a posted `REQUEST_CHANGES` review (the only terminal that is not an approval) a **fresh `fu-<pr>` is spawned with the Follow-Up Brief** and the review session is then dismissed (§ Worktree Cruft (a) add-then-remove — spawn `fu-<pr>`, wait for its `<created ...>` line, THEN dismiss the review session), and the entry moves to `followup`. The review session is never reused as the follow-up host; the fresh `fu-<pr>` runs the § A2 Follow-Up loop.

**`done`:** Terminal entries. Never re-process a PR found in `done`.

**`restricted_output_review_authors`:** Retained in the schema for backward-compatible parsing ONLY — it no longer gates anything and selects nothing (findings-first is the default for every review and every author; see § Findings-First Review Model). A future reader should NOT think it still routes reviews; it does not gate or route anything.

## Reaction Scheme (Add-Only)

The Slack MCP has NO remove-reaction tool. Reactions accumulate:

- **Add 👀 (`eyes`)** — the moment a PR is picked up for review (spawn succeeded).
- **Add ✅ (`white_check_mark`)** — when our LATEST GitHub review on the PR is `APPROVED` (including approval reached via follow-up). 👀 remains alongside (cannot be removed).
- `CHANGES_REQUESTED` → leave 👀 only. (This is now the only non-approving terminal state — `APPROVE`-with-comments resolves to the ✅ case above, same as any other APPROVE.)

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
- **Pane shows `ESCALATE-<pr>: <verdict + summary>` followed by the enumerated candidate-findings list** (non-clean review — findings-first, the common non-approve case) → do NOT dismiss the crew session; **keep it alive (idle)** and move the entry active→`awaiting_decision`, recording the crew window name, `verdict` + `summary`, the parsed `findings` list, and `walkthrough_idx: 0`. Leave 👀 in place; do NOT add ✅; do NOT post anything to the PR. The per-finding operator walkthrough runs from § A3). See § Findings-First Review Model → Escalation handling.
- **Pane shows `REVIEW-POSTED-<pr>` AND our review appears in `gh pr view --json reviews`** → in findings-first mode the only autonomous write is a clean empty APPROVE, so `REVIEW-POSTED` accompanies an `APPROVED` review: add ✅ reaction + `crew dismiss <crew-name>` + active→done(`reviewed-approved`). (A non-approving review is NEVER posted autonomously — that path escalates via `ESCALATE-<pr>` above. If a `CHANGES_REQUESTED` review nonetheless appears — e.g., posted by the still-alive session under operator direction after a walkthrough that started here — transition to follow-up exactly as § A3) does: spawn a fresh `fu-<pr>` with the Follow-Up Brief (§ Worktree Cruft (a) add-then-remove), WAIT for its `<created ...>` line, THEN `crew dismiss` the review session, and move active→followup; the `fu-<pr>` session runs the § A2 Follow-Up loop. A posted `REQUEST_CHANGES` review NEVER just ends. An `APPROVE`-with-comments review appearing here is already handled by the branch above — add ✅ + dismiss + done — exactly like a clean APPROVE: it is a normal completion, not a follow-up.)
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

### A3) Monitor Awaiting-Decision Reviews (drive the per-finding walkthrough)

For each entry in `awaiting_decision` (non-clean review sessions HELD ALIVE per § Findings-First Review Model → Escalation handling): the review session stays alive (idle) and retains its full review context. Never dismiss it while the walkthrough is unfinished; never add ✅. Never dismiss-then-respawn a fresh session to execute a decision — the still-alive session is the actor.

**Walkthrough not yet complete** (`walkthrough_idx < len(findings)`) → first apply the severity floor (§ Findings-First Review Model → Severity Floor) as a backstop: starting at `walkthrough_idx`, judge each candidate against the nit definition — a content-based judgment, NOT a lookup on the SEVERITY field (`blocking | concern | comment` has no `nit` value, and COMMENT is never treated as synonymous with nit) — and auto-skip any candidate that matches it — increment `walkthrough_idx` and persist, no `AskUserQuestion` fired, not even a batched one — and keep advancing until either a concern-level-and-above candidate is found or the list is exhausted. (This backstop should rarely fire since `/pr-review` already drops nits hard at specialist-authoring time and the spawned session re-judges and excludes any nit before relaying — see § Findings-First Review Brief — but the coordinator never trusts a nit-classified candidate to reach the operator without its own judgment.) If a concern-level-and-above candidate is found, surface THAT single candidate to the operator per § Findings-First Review Model → Per-Finding Walkthrough: exactly ONE `AskUserQuestion` for the candidate, preceded by an ELI5 prose preamble (intent recap + the finding + an ELI5 of any technical concept + enough PR background/context to decide). One `AskUserQuestion` per candidate comment — never batch findings. On the operator's answer:
- **Post a comment (operator supplied / edited the text)** → relay it to the still-alive session via `crew tell <crew>`, which RECORDS that comment into the accumulated review set (nothing is submitted to GitHub yet); then increment `walkthrough_idx` and persist.
- **Skip this finding (no comment)** → increment `walkthrough_idx` and persist; move to the next candidate on the next turn.

On the "post a comment" answer, the approved comment text is relayed to the still-alive session via `crew tell <crew>`, which RECORDS it into the accumulated review set (nothing is submitted to GitHub yet — a single unified review is submitted once at walkthrough end).

Advance the walkthrough only one candidate per turn (one `AskUserQuestion` per turn — consistent with the one-at-a-time discipline in § AskUserQuestion Discipline). Stay silent between turns per § Report Discipline — no per-tick heartbeat noise.

**Walkthrough complete** (`walkthrough_idx >= len(findings)`, every candidate decided or auto-skipped) → submit exactly ONE review (matching `/pr-review`'s single-unified-review model — never one review per comment) and finalize by how many comments the operator approved:
- **All candidates were nit-severity and auto-skipped — no `AskUserQuestion` was ever fired for this entry** (per the severity-floor backstop above, including the case where `findings` was empty from the moment the entry entered `awaiting_decision`) → resolve automatically, with no operator round-trip: tell the still-alive session to submit the empty APPROVE, then add ✅ + `crew dismiss <crew>` + move `awaiting_decision`→`done` (reason: `reviewed-approved`). No `fu-<pr>` is spawned. Never surface a walkthrough for an entry that resolves to zero concern-level-and-above candidates.
- **Zero comments approved** (operator was shown at least one concern-level-and-above candidate but skipped every one, or directed a clean APPROVE) → if the operator directed an APPROVE, tell the still-alive session to submit the empty APPROVE, then add ✅ + `crew dismiss <crew>` + move `awaiting_decision`→`done` (reason: `reviewed-approved`); if the operator dropped everything with no post, `crew dismiss <crew>` + move `awaiting_decision`→`done` (reason: `operator-dropped`). No `fu-<pr>` is spawned in either sub-case.
- **One or more comments approved** → the terminal event is binary — **never a bare COMMENT**: not approving is itself a blocking action that silently withholds the merge green-light, so a bare COMMENT is never offered or submitted. First decide the **review event** with the operator via one final `AskUserQuestion` (see § Per-Finding Walkthrough → Choosing the review event): **APPROVE-with-comments** (non-blocking → GitHub `APPROVE`, carrying every accumulated operator-approved comment) or **REQUEST_CHANGES** (blocking → GitHub `CHANGES_REQUESTED`).
  - **APPROVE-with-comments chosen** → an APPROVE terminal is a normal completion, not a non-approving-review follow-up: tell the still-alive session to submit ONE unified `APPROVE` review via a single `prr submit --findings <json>` carrying every accumulated operator-approved comment, then add ✅ + `crew dismiss <crew>` + move `awaiting_decision`→`done` (reason: `reviewed-approved`). No `fu-<pr>` is spawned.
  - **REQUEST_CHANGES chosen** → tell the still-alive session to submit ONE unified `REQUEST_CHANGES` review via a single `prr submit --findings <json>` carrying every accumulated operator-approved comment — the still-alive session EXECUTES this decision (it is NOT dismissed-then-respawned to post). Once that review is posted, transition to follow-up via § Worktree Cruft (a) add-then-remove: **spawn a fresh `fu-<pr>` with the Follow-Up Brief** (`crew create fu-<pr> ... --tell-file`), WAIT for its `<created ...>` line, THEN `crew dismiss <crew>` the review session. Move the entry `awaiting_decision`→`followup` with `our_review` set to `CHANGES_REQUESTED`; the fresh `fu-<pr>` session runs the § A2 Follow-Up loop. Do NOT dismiss-to-done in this case. **A posted non-approving review NEVER just ends.**

Entries in `awaiting_decision` are still visible to the normal dedup/skip check in § B — a PR held here is NOT re-spawned as a new candidate (only § B checks bucket membership against `active`/`followup`/`awaiting_decision`/`queue`).

### B) New Posts

Run `slack_read_channel(channel=<channel_id>, limit=15)`.

**Gap-coverage guard (this watcher's instance of the global Pagination Discipline rule — never draw a complete-set conclusion from a single partial page):** a fixed `limit=15` read can be truncated. If more than 15 messages have posted since `watermark_ts`, the oldest ones in that gap would silently fall below the watermark the moment it advances past only the newest ones actually read — the silent-drop failure mode this guard prevents. Before advancing `watermark_ts`, confirm the read covered the whole gap: check the OLDEST message returned in this batch. If it still has `ts > watermark_ts` (meaning older-but-still-new messages may exist beyond this page), keep paginating — re-run `slack_read_channel` bounded to before the oldest ts seen so far (concretely: the underlying Slack `conversations.history` Web API's `latest` parameter is the standard before-timestamp bound — set it to the oldest `ts` already seen this cycle; verify the exact parameter name against this MCP tool's own schema, since it is not otherwise documented in this skill) — until a returned message has `ts <= watermark_ts`, confirming the full new-message set for this cycle is in hand. **Stop condition (history-exhausted):** if a paginated re-run returns an empty page, or fewer than `limit` messages, without ever producing a message with `ts <= watermark_ts`, treat this as history-exhausted — stop paginating, advance `watermark_ts` to the newest message actually seen across all pages read this cycle, and log a warning (e.g., "pr-review-watcher: history-exhausted before reaching watermark_ts — advancing to newest-seen; older gap messages may be unrecoverable"). Do NOT advance the watermark until every message down to the old watermark has actually been examined this way, or the history-exhausted stop condition above has fired.

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

Once the gap-coverage guard above confirms the full new-message set is in hand, update `watermark_ts = max(watermark_ts, newest ts seen in this batch)`.

### C) Dedup Each Candidate (MANDATORY immediately before spawning)

Run `gh pr view <pr> --repo <repo> --json state,author,reviews,isCrossRepository`.

**SKIP** (record in `done` with reason) if ANY of the following:

- `author.login == github_login` → **never review our own PRs**.
- `state != OPEN` (merged or closed) → skip, record as `skipped-closed`.
- operator (`github_login`) already appears in `reviews` → we already reviewed it; if `APPROVED`, done; if non-approving, should be in `followup` already.
- **Any review by a login that is NEITHER the PR author NOR a login in `bot_logins`** → an independent human already reviewed it → **skip if anybody reviewed**. The PR author's own self-review / self-comment does NOT count as an independent review — authors routinely self-comment to explain their change. Bot reviews do NOT count either.

Only if NONE of the above hold → the PR genuinely needs review.

**No author-based routing branch:** every candidate that passes the SKIP checks above follows the SINGLE findings-first spawn path in § D below — regardless of author. There is no longer a subset of authors routed differently; `restricted_output_review_authors` no longer gates anything (see § Launch Arguments). Findings-first is the default for all reviews.

### D) Spawn Reviews (Maximum Parallelism — No Concurrency Cap)

For **every** PR that needs review (all authors — there is no per-author routing branch):

1. Add 👀 reaction to the Slack message (`slack_add_reaction(channel=<channel_id>, timestamp=<message_ts>, reaction="eyes")`).
2. Add to `active` with `status: "spawning"` BEFORE spawning (prevents next-tick double-spawn).
3. Persist state file.
4. Determine `repo_path`: derive from the org/repo in the PR link → `~/github.com/<org>/<repo>` (generalized convention; adjust to the actual local checkout path if known from the PR link).
5. Stagger ~6 seconds between parallel spawns to avoid git-worktree lock collisions.
6. Compose the findings-first review brief (see § Findings-First Review Brief) as a single line with all `<pr>`/`<repo>`/`<bot_logins_csv>` substitutions filled, and write it to `.scratchpad/<pr>-review-brief.md`.
7. Run (with `run_in_background=true`):
   ```
   crew create review-<pr> --repo <repo_path> --base main --model 'sonnet[1m]' --tell-file .scratchpad/<pr>-review-brief.md
   ```
   **Fork PR** (`isCrossRepository == true`) → use the fork variant of the findings-first review brief (omits `gh pr checkout` since the fork head is not directly checkout-able).
   **Worktree-name collision** → append `b` to the crew name (e.g., `review-123b`).
8. Update `active` entry `status` to `"reviewing"`. Persist state.

## Findings-First Review Model

**This is the single review model for every PR and every author.** There is no separate autonomous-post path — the watcher never posts a comment or a change-request without per-finding operator confirmation.

**Intent:** Run the exact same full specialist review as always — no shortcuts on analysis — but constrain what the watcher writes back to GitHub. The only outcome the watcher may post autonomously is a clean empty APPROVE. Anything else routes each candidate comment through the operator, one at a time, before a single character lands on the PR.

**The two outcomes of a review:**

1. **CLEAN case — silent empty APPROVE (no human round-trip):** if the review is cleanly approvable (zero concern-level-and-above findings — see § Severity Floor; nits never count toward this determination), the spawned session posts an APPROVE with an empty body and zero comments, silently. This clean-approve fast path is the ONLY autonomous GitHub write the watcher is authorized to make. When the spawned session prints `REVIEW-POSTED-<pr>` (silent approve case), handle it exactly like § A) Monitor Active Reviews' `APPROVED` branch: add ✅ + dismiss + `active`→`done(reviewed-approved)`.

2. **NON-CLEAN case — return findings, hold alive, walk the operator through:** the coordinator is NOT authorized to post any comment (inline or body) or a change-request autonomously. The spawned session instead RETURNS its structured findings (an enumerable list of candidate comments) to the coordinator and STAYS ALIVE (idle) in `awaiting_decision`. The coordinator then walks the operator through each candidate ONE AT A TIME (see § Per-Finding Walkthrough).

**Escalation handling:** When the spawned session prints `ESCALATE-<pr>: <verdict + summary>` followed by its enumerated candidate-findings list, do NOT dismiss the crew session. Instead, **keep the review session alive** (idle) and move the entry `active`→`awaiting_decision`, recording the crew window name, the escalated `verdict` + `summary`, the parsed `findings` list, and `walkthrough_idx: 0`. Leave 👀 in place; do NOT add ✅; do NOT post anything to the PR. The still-alive session retains full review context and is the actor that will post any operator-approved comment. Never dismiss-then-respawn a fresh session just to execute a decision.

### Severity Floor — Nits Are Never Surfaced Or Posted

**The default severity floor for surfacing to the operator AND for posting is concern-level.** Nit-severity findings are NEVER surfaced to the operator and NEVER posted to the PR. This is a hard, standing operator preference — not a per-PR judgment call ("ALWAYS SKIP NITS. I HATE NITS."). It applies to every reviewer, every author, every repo — not a configured subset.

**Mechanism — content-based judgment, not a severity-field filter:** `/pr-review`'s findings-JSON SEVERITY field has exactly three values — `blocking | concern | comment` (pr-review/SKILL.md:375) — there is no `nit` value to filter on. `/pr-review` already drops nits hard at the specialist-authoring step ("No nits — drop them hard", pr-review/SKILL.md:358), so its findings JSON should already be nit-free by its own standard. Nit-exclusion here is therefore a content-based JUDGMENT backstop — applied against the nit definition below — never a lookup on the SEVERITY field, in case a nit nonetheless slips through. **COMMENT severity is NOT synonymous with nit:** COMMENT is `/pr-review`'s default severity for ordinary non-blocking concerns (pr-review/SKILL.md:357), so a COMMENT-severity finding that is a substantive concern is still surfaced — never blanket-drop COMMENT as if it meant nit. Severity is a signal (blocking and concern are never nits) but the nit-vs-concern decision is always judged against the definition below, not by dropping a severity value wholesale.

**Definitions:**
- **Nit-severity** — a minor/cosmetic finding: comment-wording or doc-accuracy fixes, cardinality/label math in comments, style, edge-case-only tag collisions, minor span/metric inconsistencies — anything that is NOT a substantive correctness / design / security / purpose-undermining concern.
- **Concern-level (and above)** — findings that materially affect correctness, design, security, or the PR's purpose. This is the severity floor: only concern-level-and-above findings are ever surfaced to the operator or posted to the PR.

This floor is enforced at two points, so a nit has to slip past both to ever reach GitHub:
1. **The spawned review session** judges each candidate against the nit definition above when composing the candidate-comments list it relays back to the coordinator — it relays only concern-level-and-above candidates (§ Findings-First Review Brief).
2. **The coordinator's per-finding walkthrough** applies the same content-based judgment as a backstop to any candidate that slips through anyway — never an `AskUserQuestion` for a nit, not even a batched one (§ Per-Finding Walkthrough, § A3).

If, after excluding nits at both points, zero concern-level-and-above findings remain, there is no walkthrough at all — the review resolves as a clean outcome (see § Walkthrough complete in § A3) with nothing surfaced to the operator).

### Per-Finding Walkthrough

Driven from § A3) on each cycle. For a held `awaiting_decision` entry, surface its candidate comments to the operator **one at a time** — one `AskUserQuestion` per candidate comment, never batched, and never for a nit.

**Severity-floor backstop (do this before surfacing anything):** apply § Findings-First Review Model → Severity Floor. Starting at `walkthrough_idx`, judge each candidate against the nit definition — a content-based judgment applied to the candidate's text, NOT a lookup on the SEVERITY field (`blocking | concern | comment` has no `nit` value; COMMENT is `/pr-review`'s default severity for ordinary non-blocking concerns and is never treated as synonymous with nit) — and auto-skip every candidate that matches the nit definition: increment `walkthrough_idx` and persist for each, with no `AskUserQuestion` fired, not even a batched one — until either a concern-level-and-above candidate is found or the list is exhausted. Only a concern-level-and-above candidate ever reaches step 1 below; if the list is exhausted by auto-skipping, there is no walkthrough at all for this entry (see § A3 → Walkthrough complete).

For the candidate at `walkthrough_idx` (now guaranteed concern-level-and-above), follow § AskUserQuestion Discipline:

1. Write an **ELI5 prose preamble BEFORE the `AskUserQuestion` call** containing: an intent recap (what this PR is trying to do, one sentence), the candidate finding (file:line + what the reviewer noticed), an **ELI5** of any technical concept the finding depends on (plain language, analogy or concrete example when useful), and enough PR background/context that the operator can decide without reconstructing state from scrollback. This is where the operator can talk about the PR and confirm the author's intent is right instead of a comment being added automatically.
2. Fire exactly ONE `AskUserQuestion` for this one candidate: the decision is "post a comment here, or skip?" — meaning "record this comment into the accumulated review set, or skip it" (the single review is submitted once at walkthrough end, not per comment) — with a `(Recommended)` first option, the candidate comment text as an editable option, and the free-form escape hatch (the operator can reword the comment or say something the coordinator turns into the recorded text).
3. On the answer:
   - **Post** → relay the exact operator-approved comment text to the still-alive session via `crew tell <crew>`, which RECORDS it into the accumulated review set (nothing is submitted to GitHub yet); then increment `walkthrough_idx`, persist.
   - **Skip** → increment `walkthrough_idx`, persist; next candidate on the next turn.
4. Advance one candidate per turn. Repeat next, next, next until `walkthrough_idx >= len(findings)` — the hard part of the review is exhausted. Each approved comment is ACCUMULATED into the review set as it is confirmed; nothing lands on the PR mid-walkthrough.
5. **At walkthrough end, submit exactly ONE review** (matching `/pr-review`'s single-unified-review model — never one review per comment): if zero comments were accumulated (including when every candidate was nit-severity and auto-skipped, with no operator round-trip at all), the outcome is a clean empty APPROVE (or an operator-drop with nothing posted); if one or more comments were accumulated, choose the review event (below), then tell the still-alive session to submit ONE unified review via a single `prr submit --findings <json>` carrying all accumulated comments with the chosen event.

**Choosing the review event (only when ≥1 comment was accumulated):** fire one final `AskUserQuestion` (same ELI5-preamble + one-question-per-turn discipline in § AskUserQuestion Discipline) presenting the accumulated comment set as context and asking the operator to choose the GitHub **review event**. The terminal event is binary — **never a bare COMMENT**: not approving is itself a blocking action that silently withholds the merge green-light, so submitting a bare COMMENT (GitHub `COMMENTED`) is never a valid outcome. The operator chooses between **APPROVE-with-comments** (non-blocking → posted as GitHub `APPROVE`, carrying every accumulated comment) vs **REQUEST_CHANGES** (blocking → posted as `CHANGES_REQUESTED`). The finalize branch in § A3) is wired to the event actually submitted: an **APPROVE-with-comments** terminal is a normal completion (→ `done`, no `fu-<pr>` spawned, exactly like a clean APPROVE); a **REQUEST_CHANGES** terminal is the only terminal that is not an approval, so it alone carries the review into follow-up (`our_review` = `CHANGES_REQUESTED` → `followup`, fresh `fu-<pr>` spawned) — the follow-up state matches what the walkthrough produced.

When the walkthrough completes, finalize per § A3) (Walkthrough complete): zero comments accumulated → clean APPROVE or operator-drop → `done` (no `fu-<pr>` spawned); one or more comments accumulated → decide the review event (APPROVE-with-comments or REQUEST_CHANGES). **APPROVE-with-comments** is a normal completion exactly like the clean-APPROVE case: tell the still-alive session to submit the unified APPROVE, add ✅, dismiss the session, and move to `done` — no `fu-<pr>` spawned. **REQUEST_CHANGES** is the only terminal that is not an approval, so it alone continues into follow-up: tell the still-alive session to submit ONE unified review, THEN spawn a fresh `fu-<pr>` with the Follow-Up Brief and dismiss the review session (§ Worktree Cruft (a) add-then-remove) → `followup` (a posted REQUEST_CHANGES review NEVER just ends). Relay each per-finding decision to the live session via `crew tell <crew>` — that session holds the full review context, accumulates the approved comments, and submits the single review. Never dismiss-then-respawn a fresh session to EXECUTE the review-posting decision; the fresh `fu-<pr>` (spawned only for the REQUEST_CHANGES branch) handles only the distinct, long-running follow-up-watching phase (replying, resolving threads, re-approving), not the posting of the review itself.

### AskUserQuestion Discipline

The per-finding walkthrough uses the SAME one-at-a-time `AskUserQuestion` discipline already defined for coordinators in the Staff / Senior Staff output styles (`~/.claude/output-styles/staff-engineer.md` and `senior-staff-engineer.md`, § Decision Questions): ELI5 prose preamble BEFORE the call, one question per turn, typed options with a `(Recommended)` first option and a rationale, plus the free-form "Other" escape hatch, and never a bare question in prose. Announce the count first ("I have N findings to walk through — one at a time.") so the operator has scaffolding. Do not restate that discipline in full here — follow it.

**Anti-bundling — one decision per turn, never co-mingled (sharpest risk during a high-volume pulse cycle).** Surface exactly ONE finding, one PR, or one decision per turn. Never co-mingle multiple PRs, threads, findings, or status items into a single decision surfacing — this prohibition covers the surrounding prose too, not just the `AskUserQuestion` call itself: even when the call covers only one candidate, wrapping it in prose that also touches a second unrelated PR, thread, finding, or status item is a co-mingling violation. If multiple PRs each have candidates awaiting the operator, announce the total count across all of them, then surface exactly one candidate fully (one PR, one finding) before moving to the next — never blend two PRs' findings into the same walkthrough turn or the same status line. This discipline is hardest to hold, and matters most, during a high-volume pulse cycle where several PRs land in `awaiting_decision` at once.

**Mandatory ELI5 preamble every time, including author attribution.** The full ELI5 preamble (§ Per-Finding Walkthrough, step 1) is required on EVERY candidate surfaced — never skip or shorten it because a related PR or finding was discussed moments ago in the same pulse cycle; the operator cannot be assumed to remember earlier turns during high-volume review-watching. In addition to the intent recap, the finding, and any technical ELI5, ALWAYS state who authored the artifact under decision — the PR author, human teammate vs AI — since it changes register and treatment (a human teammate's PR warrants collaborative, curious framing; an AI-authored PR warrants the scrutiny appropriate to unreviewed model output). Classify the PR author with the same bot/human detection already used for reviewers elsewhere in this file (login not ending in `[bot]`, `gh api users/<login>` returns HTTP 200 with `type == "User"`, and not in `bot_logins`), applied to the `author.login` field from `gh pr view`.

**Pre-surfacing gut-check on review findings.** Before walking the operator through any candidate, run a gut-check pass over the findings returned by the spawned review session: beyond the severity-floor judgment backstop already applied (§ Findings-First Review Model → Severity Floor), honestly judge which remaining candidates genuinely matter and which are droppable nits that slipped past that backstop. Compute this ranked, honest read of what's worth the operator's attention and what you'd drop BEFORE the walkthrough loop begins — but never deliver it as a single bundled summary or raw dump for the operator to triage themselves. Instead, it is folded into each candidate's `(Recommended)`-option rationale as the existing one-at-a-time walkthrough proceeds, one candidate at a time.

(These three paragraphs mirror the decision-surfacing discipline in `senior-staff-engineer.md` § Decision Questions and restate it here only because it is domain-specific to review-watching — keep them in sync if that base discipline changes.)

**Normal dedup still applies:** Skip if the PR is closed, is the operator's own PR, has already been independently human-reviewed, or is already `APPROVED` by a human-only review — the same § C checks that apply to every candidate, run BEFORE spawning.

## The Two Briefs (Spawned Sessions)

**CRITICAL: Both briefs MUST be composed as SINGLE-LINE text (no literal newlines) and delivered via `crew create --tell-file <path>` — NEVER inline `--tell`. Newlines in `--tell` cause early submission, and raw length above ~800-1000 chars (truncation observed near 1KB) causes silent length-based truncation (a mid-word cut, no special character required) even without newlines. Write each composed brief to a `.scratchpad/` file first, then pass the path via `--tell-file`.**

**Single-quote `sonnet[1m]` in the `crew create` command** — zsh globs `[1m]` without quotes and the model arg is silently mangled.

The two briefs are the **Findings-First Review Brief** (the single review brief for every PR and every author) and the **Follow-Up Brief**.

---

### Findings-First Review Brief (deliver via `crew create review-<pr> ... --tell-file <path>`)

This is the ONLY review brief — used for every author. It runs the full internal review via `/pr-review <pr> --restricted-output`, which restricts the GitHub write to exactly one of: (a) a clean empty APPROVE posted silently, or (b) nothing posted, with the verdict/summary reported back. On the non-clean case the session ALSO relays its enumerated candidate findings back and stays alive so the coordinator can walk the operator through them — the session never posts a comment or change-request on its own.

Compose as a single line (no literal newlines), write it to `.scratchpad/<pr>-review-brief.md`, then pass that path via `--tell-file` (never inline `--tell` — see § The Two Briefs and § Single-Line `--tell` and Length-Based Truncation):

`Review PR <pr> (<repo>) [FINDINGS-FIRST]. Step 1: run \`gh pr checkout <pr>\` (lands the worktree on the PR's exact branch). Step 2: BEFORE reviewing, run \`gh pr view <pr> --json author,reviews\` — extract author.login, then check if any review whose author.login is NEITHER the PR author NOR a known bot (<bot_logins_csv>) exists; the PR author's own self-review / self-comment does NOT count as an independent review (authors routinely self-comment to explain their change) — if such an independent review exists, print \`SKIPPED-<pr>-already-reviewed\` and STOP (do not run /pr-review). Step 3: otherwise run \`/pr-review <pr> --restricted-output\` — this runs the FULL internal specialist review as normal but restricts the GitHub write to exactly one of: (a) a clean APPROVE with empty body and zero inline comments, posted silently, or (b) nothing posted at all. The /pr-review skill's FINAL PRE-POST CHECK still applies before any write — if the PR is superseded, print \`SUPERSEDED-<pr>\` and stop. Step 4 (clean case a): if /pr-review silently approved, print \`REVIEW-POSTED-<pr>\` and stop. Step 5 (non-clean case b): print \`ESCALATE-<pr>: <verdict + one-line summary>\`, THEN on the following lines print an enumerated candidate-comments list — EXCLUDE nit-severity findings by judging each candidate against the nit definition (minor/cosmetic: comment-wording, doc-accuracy, cardinality/label math, style, edge-case-only tag collisions, minor span/metric inconsistencies — not a substantive correctness/design/security/purpose-undermining concern), applied as a content-based backstop to /pr-review's own upstream drop-nits-hard authoring standard — this is NOT a lookup on the SEVERITY field (blocking|concern|comment has no 'nit' value, and COMMENT is /pr-review's default severity for ordinary non-blocking concerns, so never blanket-drop COMMENT as if it meant nit) — relay ONLY concern-level-and-above candidates: nits are excluded here and never reported upward — read from the findings /pr-review already wrote to \`.scratchpad/review-<pr>.json\` (one numbered line per candidate: index, file:line, severity, and the comment text) plus any body-level observations from \`.scratchpad/review-<pr>.md\` (excluding nit-level observations there too) — this is what the coordinator walks the operator through — if excluding nits leaves zero candidates, still print \`ESCALATE-<pr>\` with an empty candidate list; the coordinator resolves that automatically (§ Severity Floor) with no operator round-trip. Then DO NOT post anything to the PR yourself and DO NOT dismiss yourself: stay idle and await instructions from the coordinator via crew tell. As the coordinator relays each operator-approved comment, RECORD it into an accumulated review set — do NOT post per comment. When the coordinator says the walkthrough is complete and gives the chosen review event (APPROVE-with-comments or REQUEST_CHANGES), submit ONE unified review via a single \`prr submit --findings <json>\` carrying exactly the accumulated operator-approved comments with that event — never add a comment on your own initiative. Review-only — no commit/push/branch.`

Where `<bot_logins_csv>` is the comma-separated list from `bot_logins` (e.g., `claude-maze`), or `none` if the list is empty.

**Findings-first review brief (fork PR variant):** (use when `isCrossRepository == true` — omit `gh pr checkout` since the fork's head is not directly checkout-able the same way; write this text to the same `.scratchpad/<pr>-review-brief.md` file instead of the base form)

`Review PR <pr> (<repo>) [FINDINGS-FIRST — FORK/CROSS-REPO, no direct checkout]. Step 1: BEFORE reviewing, run \`gh pr view <pr> --json author,reviews\` — extract author.login, then check if any review whose author.login is NEITHER the PR author NOR a known bot (<bot_logins_csv>) exists; the PR author's own self-review / self-comment does NOT count as an independent review (authors routinely self-comment to explain their change) — if such an independent review exists, print \`SKIPPED-<pr>-already-reviewed\` and STOP (do not run /pr-review). Step 2: otherwise run \`/pr-review <pr> --restricted-output\` — full internal review as normal, GitHub write restricted to exactly one of: (a) a clean empty APPROVE posted silently, or (b) nothing posted. The /pr-review FINAL PRE-POST CHECK still applies — if the PR is superseded, print \`SUPERSEDED-<pr>\` and stop. Step 3 (clean case a): if /pr-review silently approved, print \`REVIEW-POSTED-<pr>\` and stop. Step 4 (non-clean case b): print \`ESCALATE-<pr>: <verdict + one-line summary>\`, THEN on the following lines print an enumerated candidate-comments list — EXCLUDE nit-severity findings by judging each candidate against the nit definition (minor/cosmetic: comment-wording, doc-accuracy, cardinality/label math, style, edge-case-only tag collisions, minor span/metric inconsistencies — not a substantive correctness/design/security/purpose-undermining concern), applied as a content-based backstop to /pr-review's own upstream drop-nits-hard authoring standard — this is NOT a lookup on the SEVERITY field (blocking|concern|comment has no 'nit' value, and COMMENT is /pr-review's default severity for ordinary non-blocking concerns, so never blanket-drop COMMENT as if it meant nit) — relay ONLY concern-level-and-above candidates: nits are excluded here and never reported upward — read from \`.scratchpad/review-<pr>.json\` (one numbered line per candidate: index, file:line, severity, comment text) plus any body-level observations from \`.scratchpad/review-<pr>.md\` (excluding nit-level observations there too) — if excluding nits leaves zero candidates, still print \`ESCALATE-<pr>\` with an empty candidate list; the coordinator resolves that automatically (§ Severity Floor) with no operator round-trip. Then DO NOT post anything yourself and DO NOT dismiss yourself: stay idle and await coordinator instructions via crew tell; as the coordinator relays each operator-approved comment, RECORD it into an accumulated review set (do NOT post per comment), and when the coordinator gives the completed walkthrough's chosen review event (APPROVE-with-comments or REQUEST_CHANGES), submit ONE unified review via a single \`prr submit --findings <json>\` carrying exactly those accumulated comments with that event — never on your own initiative. Review-only — no commit/push/branch.`

---

### Follow-Up Brief (deliver via `crew create fu-<pr> ... --tell-file <path>`)

**Converted to `--tell-file` delivery:** this brief is ~1965 characters — well above the ~800-1000 char threshold in § Single-Line `--tell` and Length-Based Truncation — so it is delivered the same way as the Findings-First Review brief, never inline `--tell`.

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
2. **Inside the findings-first review brief** — right before `/pr-review` runs (human approvals frequently land during the bootstrap window).

This is what prevents wasted/duplicate reviews. The two-layer check is intentional — not redundant.

### Never Review Own PRs

If `author.login == github_login`, skip unconditionally. Record in `done` with `reason: "skipped-own-pr"`.

### Cron Exemption

The watcher cron MUST persist even when there are zero active reviews — it has to catch new posts. If a `pulse-cron-lifecycle` style hook tries to self-terminate "when zero crew windows remain," this watcher cron must be **exempt**. It is not a crew-monitoring pulse cron.

### Single-Line `--tell` and Length-Based Truncation

Inline `--tell` has TWO independent truncation failure modes — guard against both:

- **Newline-triggered:** newlines in `--tell` cause the shell to submit the command early — the brief is truncated mid-line. Compose briefs as a single line. No literal `\n` or multi-line heredoc.
- **Length-based truncation:** even a newline-free, single-line brief above ~800-1000 characters can be silently truncated on delivery — no special character required, raw length alone triggers it (observed: a ~1900-char single-line brief was cut mid-word around ~1KB, leaving the spawned session blocked on a malformed brief and costing a full cron cycle).

**Rule:** long briefs (above ~800-1000 chars (truncation observed near 1KB)) MUST be delivered via `crew create --tell-file <path>` — write the composed brief to a `.scratchpad/` file first, then pass the path. Reserve inline `--tell` for short briefs and short pointers only. Both spawned-session briefs in this skill (Findings-First Review, Follow-Up — see § The Two Briefs) exceed this threshold and are delivered via `--tell-file`.

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

The watcher always invokes `/pr-review <pr> --restricted-output` (§ Findings-First Review Brief). In `--restricted-output` mode, `/pr-review` runs its full internal specialist review (Phases 1–5 unchanged) and restricts the GitHub write at Phase 6 to exactly one outcome: a clean empty APPROVE posted silently (`prr` — detectable via `gh pr view --json reviews`), or nothing posted plus an `ESCALATE-<pr>: ...` line emitted back to the caller. `/pr-review` short-circuits its worktree-setup phase when already inside a worktree (the review brief's `gh pr checkout` sets this up). Crucially, `/pr-review` still writes its aggregated structured findings to `.scratchpad/review-<pr>.json` (and `.scratchpad/review-<pr>.md`) during Phase 5 even in restricted-output mode — so the spawned session can read that file and relay an enumerated candidate-comments list after the `ESCALATE-<pr>` line without any change to `/pr-review`. The sentinel strings the watcher reads via `crew read` are `REVIEW-POSTED-<pr>` (silent clean approve), `ESCALATE-<pr>: ...` (non-clean → hold alive + per-finding walkthrough), `SKIPPED-<pr>-already-reviewed`, and `SUPERSEDED-<pr>`.

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
- The **restricted-output-authors list** (`restricted_output_review_authors`) is DEPRECATED and no longer gates anything — findings-first review is the default for every review and every author (§ Findings-First Review Model). The `--restricted-output-authors` argument is still parsed for backward compatibility but selects nothing. No specific login is hardcoded anywhere in this skill.

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
       → ESCALATE sentinel + enumerated findings (non-clean, findings-first): HELD ALIVE — do NOT dismiss;
           move to awaiting_decision (record crew, verdict, summary, findings, walkthrough_idx:0), leave 👀, no ✅
       → REVIEW-POSTED + review visible in gh (clean empty APPROVE — the only autonomous write):
           APPROVED: add ✅ + dismiss + done(reviewed-approved)
       → REVIEW-POSTED but not yet in gh: wait tick
       → stalled/error: surface to user, leave in active

  A2) for each followup entry:
       get pr state + reviews (gh pr view)
       get pane output (crew read)
       → SUPERSEDED sentinel: dismiss + done(superseded-race), leave 👀, no ✅
       → APPROVED: add ✅ + dismiss + done(approved-after-followup)
       → state != OPEN: dismiss + done(merged/closed)
       → otherwise: leave it (self-pulses via ScheduleWakeup)

  A3) for each awaiting_decision entry (HELD ALIVE — never dismiss mid-walkthrough, session stays idle + retains context):
       → walkthrough not complete (walkthrough_idx < len(findings)):
           severity-floor backstop: auto-skip nit-severity candidates from walkthrough_idx onward
             (increment walkthrough_idx + persist each, NO AskUserQuestion — not even batched)
             until a concern-level+ candidate is found or the list is exhausted
           if a concern-level+ candidate is found, surface ONE candidate (findings[walkthrough_idx]) via AskUserQuestion —
             ELI5 prose preamble first (intent recap + finding + ELI5 of any concept + PR context),
             one AskUserQuestion per candidate comment, (Recommended) first option + free-form
           post → crew tell <crew> the operator-approved comment text; increment walkthrough_idx; persist
           skip → increment walkthrough_idx; persist
           (advance one candidate per turn — one AskUserQuestion per turn)
       → walkthrough complete (all candidates decided or auto-skipped; approved comments ACCUMULATED by the still-alive session):
           all candidates were nit-severity and auto-skipped (including findings empty from the start) —
             no AskUserQuestion ever fired: tell session to submit clean APPROVE, add ✅/dismiss + done(reviewed-approved) — no fu-<pr>
           zero comments accumulated (operator saw ≥1 concern-level+ candidate but skipped/dropped all): (tell session to submit clean APPROVE if directed) add ✅/dismiss + done(reviewed-approved | operator-dropped) — no fu-<pr>
           ≥1 comment accumulated: choose review event via one AskUserQuestion — binary, never a bare COMMENT (APPROVE-with-comments→APPROVED | REQUEST_CHANGES→CHANGES_REQUESTED):
             APPROVE-with-comments (no blocking finding survives) → normal completion, same as clean APPROVE:
               tell session to submit unified APPROVE (prr submit --findings <json>, event=APPROVE); add ✅/dismiss + done(reviewed-approved) — no fu-<pr>
             REQUEST_CHANGES (a blocking finding survives) →
               tell the still-alive session to submit ONE unified review (prr submit --findings <json>, event=REQUEST_CHANGES);
               THEN spawn fresh fu-<pr> with Follow-Up Brief (add-then-remove: wait for <created>, then dismiss the review session);
               move to followup (our_review=CHANGES_REQUESTED); fu-<pr> runs § A2 loop; a posted REQUEST_CHANGES review NEVER just ends
       (the still-alive session EXECUTES the review-posting decision; the fresh fu-<pr> — spawned only for the REQUEST_CHANGES branch — handles only the follow-up-watching phase — never dismiss-then-respawn to execute the posting decision)

  B) slack_read_channel(channel=<channel_id>, limit=15)
       gap-coverage guard (Pagination Discipline — see § B) New Posts prose): while OLDEST msg in batch has ts > watermark_ts:
         paginate — re-run slack_read_channel bounded to before the oldest ts seen so far (before-timestamp bound,
           e.g. Slack conversations.history's `latest` param — verify exact name against this tool's schema);
           merge into this cycle's batch
         → empty page OR fewer than `limit` msgs returned, without ever reaching ts <= watermark_ts: history-exhausted —
           stop paginating, log a warning
       (loop ends when OLDEST msg in batch has ts <= watermark_ts — full gap coverage confirmed — OR history-exhausted fires)
       for each msg ts > watermark, author != self_user_id, contains github PR link (across the full, gap-covered batch):
         parse repo + pr
         if pr in done AND post has re-review language → straight-approval flow (see § B) New Posts)
         skip if in active/followup/awaiting_decision/queue
         if pr in done (no re-review language) → skip
         → candidate
       update watermark_ts = max(watermark_ts, newest ts seen in this batch)

  C+D) for each candidate (SINGLE findings-first path — all authors, no routing branch):
       gh pr view --json state,author,reviews,isCrossRepository
       skip if: own PR | closed | already reviewed by operator | independent human reviewed
       → needs review:
           add 👀 reaction
           add to active (status: spawning)
           persist state
           write findings-first review brief to .scratchpad/<pr>-review-brief.md (fork variant if isCrossRepository)
           crew create review-<pr> ... --tell-file .scratchpad/<pr>-review-brief.md (background, stagger 6s)
           update status: reviewing
           persist state
           (see § Findings-First Review Model — silent clean APPROVE, or ESCALATE + return findings + hold alive
            for the per-finding operator walkthrough; never post a comment/change-request autonomously)

  persist final state
CYCLE END
```
