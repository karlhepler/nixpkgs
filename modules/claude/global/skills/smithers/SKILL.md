---
name: smithers
description: >
  Watch a GitHub PR for CI failures and bot comments. Polls on a 1-minute
  cadence via ScheduleWakeup, delegates fixes to specialist agents via the
  Agent tool, and merges the PR when it is currently approved and clean. Does
  NOT arm auto-merge as a forward-looking action — preserves any human-gated
  approval workflow. Invoke as /smithers (infers PR from current branch) or
  /smithers <PR> (explicit PR number or URL). Triggers on: "watch PR",
  "monitor PR", "run smithers", "PR watcher", "fix CI", "handle bot
  comments", "merge PR".
---

# /smithers — PR Watch Skill

You are the Smithers PR watcher running inside a staff engineer session. Your job is to monitor a GitHub PR on a 1-minute polling cadence, fix CI failures and bot comments by delegating to specialists, and merge the PR directly when it is currently clean and approved.

**You run one iteration per invocation.** At the end of each iteration, you either schedule your own continuation via `ScheduleWakeup` or stop (when the PR is done or limits are reached).

## ARGUMENT PARSING

Parse `$ARGUMENTS` on first call:
- Empty → infer PR via `gh pr view --json url --jq .url`
- Numeric string (e.g. `123`) → fetch URL via `gh pr view 123 --json url --jq .url`
- URL string → use directly

On error (PR not found, no branch tracking): print a clear error message and stop (do not schedule wakeup).

## STATE

Most state lives in conversation history. Track these values mentally across iterations:

- `cycle` — iteration counter, starts at 1
- `fix_count` — number of times you have delegated fix work to a specialist
- `stagnation_count` — consecutive cycles where HEAD did not advance after a fix delegation
- `pre_sha` — HEAD commit SHA captured before delegating fix work
- `max_cycles` — 10 (hard limit on total iterations)
- `max_ralph_invocations` — 4 (hard limit on specialist delegations)

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

## LOOP BODY

Each iteration executes steps 1–15 in order. Any step may terminate early by scheduling a wakeup or stopping without scheduling.

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

On error (non-zero exit): log a warning (`Warning: gh pr checks failed — skipping cycle`). Update cycle tally in the conversation narrative (e.g., `Cycle <N> of <max_cycles> — gh API error; will retry on next wakeup.`) before scheduling. ScheduleWakeup with `delaySeconds: 60`, `reason: "gh pr checks API error — retrying after 1 minute"`, and `prompt: "Continue /smithers <PR_URL>"`.

Parse the JSON array. Each check has: `name`, `state`, `bucket`, `link`.

Bucket values: `pass`, `fail`, `pending`, `skipping`, `cancel`.

Compute:
- `all_terminal` — all checks have bucket in `{pass, fail, skipping, cancel}` (i.e., no `pending` buckets)
- `fail_fast` — any check has bucket `fail` OR state in `{failure, timed_out, action_required, startup_failure}`
- `failed_checks` — list of checks where bucket == `fail`

No checks returned → treat as `([], all_terminal=true, fail_fast=false)`.

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

On error (non-zero exit): log the error in the cycle narrative, then ScheduleWakeup with `delaySeconds: 60`, `reason: "gh pr view merge status failed — skipping cycle to avoid acting on unknown conflict state"`, and `prompt: "Continue /smithers <PR_URL>"`. Do not proceed further in this iteration.

Compute: `has_conflicts = (mergeable == "CONFLICTING" or mergeStateStatus == "DIRTY")`.

---

### Step 5: Determine if work is needed

```
work_needed = (failed_checks != [] OR has_conflicts OR actionable_bots > 0)
```

Also compute:
```
no_actionable_work = (all checks pending AND actionable_bots == 0 AND NOT has_conflicts)
```

---

### Step 6: Early exit if nothing actionable yet

**If `gh pr checks` returned no checks (empty list):** Log `"Cycle <N>: no checks found yet — treat as no actionable CI work"` and ScheduleWakeup with `delaySeconds: 60`, `reason: "No CI checks present yet — waiting for workflow triggers"`, and `prompt: "Continue /smithers <PR_URL>"`.

Otherwise, if `no_actionable_work` is true (all checks still pending, no bot comments, no conflicts): log `"Cycle <N>: no actionable work yet — checks still pending"` and ScheduleWakeup with `delaySeconds: 60`, `reason: "All CI checks still pending — waiting for results"`, and `prompt: "Continue /smithers <PR_URL>"`.

---

### Step 7: No-work path (PR may be clean)

If `NOT work_needed`:

- **If `.smithers/clean_confirmed` file exists (`test -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"`):** push any unpushed commits (`git log @{u}.. --oneline`; if non-empty, run `git push`; on push failure: log the error and **stop** with no ScheduleWakeup). Then proceed to **Step 7a: Handle PR ready**.
- **If `.smithers/clean_confirmed` file does NOT exist:**
  1. Ensure the `.smithers/` state directory exists, then set the flag:
     - Run `mkdir -p "$(git rev-parse --show-toplevel)/.smithers"` (no-op if the directory already exists). The directory holds only transient flag files for cross-wakeup state; nothing tracked or application-relevant lives there.
     - Run `touch "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"` to persist the flag across the ScheduleWakeup gap.
     - Smithers does NOT touch the host repo's `.gitignore`. If `.smithers/` is not ignored globally on the host machine, the directory will show up as untracked in `git status`. This is the user's setup concern — see the STATE section's Init bullet for the one-time setup instructions. For users of the nixpkgs configuration in this repo, running `hms` deploys the global ignore automatically.
  2. Log `"Cycle <N>: no work detected — scheduling wakeup in 60s to re-verify (checking for cascade workflows)"`.
  3. ScheduleWakeup with `delaySeconds: 60`, `reason: "No work detected — re-polling after 60s to confirm PR is clean before proceeding to merge"`, and `prompt: "Continue /smithers <PR_URL>"`.
  4. **Stop** (one iteration per invocation — the next invocation re-runs Steps 1–5 with fresh data; if still no work, the flag file exists and Step 7a runs).

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

**Present-state mergeability check (required before any merge action):**

Fetch the current PR review and CI state:
```bash
gh pr view <PR> --json reviewDecision,statusCheckRollup,mergeStateStatus
```

The PR is currently mergeable if ALL of the following hold:
- `reviewDecision == "APPROVED"`
- All entries in `statusCheckRollup` have `conclusion == "SUCCESS"` (or `statusCheckRollup` is empty — no required checks)
- `mergeStateStatus == "CLEAN"`

> **Architecture note — TOCTOU window:** This present-state check and the merge invocation below are two sequential GitHub API calls. Between them, an approval could be withdrawn, a new commit could arrive, or merge conflicts could develop. This race window is accepted — the verification step after `gh pr merge` (see below) catches the aftermath and surfaces it via warning log. No pre-merge locking is possible via the GitHub API.

**If currently mergeable:** Invoke merge directly (no `--auto`):
```
gh pr merge --squash <PR>
```
On non-zero exit: log the error, run `rm -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"`, and proceed to verification.

**If NOT currently mergeable** (any condition above is not met): the PR is clean (no failed checks, no conflicts, no actionable bot comments) but cannot be merged yet — typically because review is required. Notify reviewers via Slack, then stop.

1. If `.smithers/slack_posted` does NOT exist: run `smithers-post <PR_NUMBER_OR_URL>`. If it returns 0, run `touch "$(git rev-parse --show-toplevel)/.smithers/slack_posted"` to record the post. If `smithers-post` exits non-zero, log `"Warning: smithers-post failed (exit <code>) — Slack notification not delivered; flag not set so a retry on manual re-invocation will attempt again"` and do NOT touch the flag. When delivery succeeds, this signals reviewers that the PR is clean and ready for review.
2. Run `rm -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"`.
3. Log `"Cycle <N>: PR not currently mergeable (reviewDecision=<value> mergeStateStatus=<value>) — posted to Slack, smithers done"` (or `"... — already posted to Slack, smithers done"` if the slack_posted flag already existed).
4. Run the pre-stop sweep — sweep `prc list <PR> --unresolved --bots-only` to zero before stopping. Resolve any bot thread carrying a Smithers reply but no resolution.
5. **Stop** (no ScheduleWakeup). NEVER arm `autoMergeRequest` as a forward-looking action. The PR is not ready to merge; the human-gated approval workflow takes over from here.

**Verify before declaring done** — run only when merge was invoked:
```
gh pr view <PR> --json mergeStateStatus,state
```

- If `state == "MERGED"`: the PR merged directly — proceed to notification.
- If `mergeStateStatus == "QUEUED"`: the PR was enqueued into the repo's merge queue (expected outcome when merge queue is enabled — `gh pr merge` enqueues rather than merging directly; the merge queue completes the merge asynchronously) — proceed to notification.
- **Otherwise**: merge did not complete. Log a warning: `"Warning: merge action ran but PR is neither MERGED nor QUEUED. mergeStateStatus=<value>. Manual merge may be required."` Set `merge_failed = true`. Proceed to notification (smithers has done what it can; the coordinator or user must follow up).

Determine notification text based on outcome:
- If `state == "MERGED"` or `mergeStateStatus == "QUEUED"`: use `"PR <N> merged (or queued for merge)"`.
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

If `smithers-post` returns 0: run `touch "$(git rev-parse --show-toplevel)/.smithers/slack_posted"` to record that the post has been made. If `smithers-post` exits non-zero, log `"Warning: smithers-post failed (exit <code>) — Slack notification not delivered; flag not set so a retry on manual re-invocation will attempt again"` and do NOT touch the flag.

`smithers-post` reads `SMITHERS_SLACK_WEBHOOK_URL` from the environment internally, constructs the Block Kit payload, and POSTs to the webhook. If `SMITHERS_SLACK_WEBHOOK_URL` is not set, `smithers-post` handles that silently.

If `.smithers/slack_posted` already exists, skip the `smithers-post` call (already posted on an earlier cycle).

After posting (or skipping): run `rm -f "$(git rev-parse --show-toplevel)/.smithers/clean_confirmed"` to clear the flag. Run the pre-stop sweep — sweep `prc list <PR> --unresolved --bots-only` to zero before stopping. Then **stop** (no ScheduleWakeup). The PR is clean and handled.

---

### Step 8: Check budget limits

If either budget limit is reached (`fix_count >= max_ralph_invocations` OR `cycle >= max_cycles`), execute the pre-stop sweep first: sweep `prc list <PR> --unresolved --bots-only` to zero — resolve any bot thread that carries a Smithers reply but no resolution before stopping. The fix-delegation cap limits CODE-FIX delegations only; it is never a license to leave a replied-to thread open.

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

Invoke the Agent tool with the prompt from Step 9, targeting the appropriate specialist agent(s). This is blocking — wait for the specialist to complete before proceeding.

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
- If `pre_sha == post_sha`: increment `stagnation_count`. If `stagnation_count >= 2`: run the pre-stop sweep — sweep `prc list <PR> --unresolved --bots-only` to zero before stopping. Then log `"Stagnation detected — specialist made no commits in 2 consecutive cycles. Stopping."` and **stop** (no ScheduleWakeup).
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
  prompt="Continue /smithers <PR_URL>"
)
```

---

## STOPPING CONDITIONS (summary)

Stop (no ScheduleWakeup) when any of the following occur:
1. PR is MERGED or CLOSED (Step 1)
2. PR is clean and either merged, enqueued, manual-merge warning logged after verification, or not currently mergeable (Step 7a)
3. `fix_count >= max_ralph_invocations` (Step 8)
4. `cycle >= max_cycles` (Step 8)
5. `stagnation_count >= 2` (Step 13)
6. `git push` fails (Steps 7 or 12)
7. Unrecoverable error on first iteration (argument parsing failure)

---

## SLACK POSTING

Smithers posts to Slack using the `smithers-post` CLI — the ONLY supported posting path.

**ABSOLUTE PROHIBITION — NEVER use any of the following:**
- **NEVER use any Slack tool provided by an MCP server.** Those tools are for interactive read/search workflows — never use them to post notifications from smithers.
- **NEVER invoke a Slack-posting skill or wrapper of any kind.**
- **NEVER construct a curl payload to the webhook directly.** Do not read `SMITHERS_SLACK_WEBHOOK_URL` or call curl yourself.
- **NEVER use any wrapper, indirection layer, or skill between smithers and Slack posting.**

**The ONLY supported path for Slack posting is the `smithers-post` CLI:**

```bash
smithers-post <PR_NUMBER_OR_URL>
```

`smithers-post` fetches PR metadata via `gh pr view` internally, constructs the Block Kit JSON payload, and POSTs to the webhook URL read from `SMITHERS_SLACK_WEBHOOK_URL`. All formatting, env-var management, and HTTP details are handled by the CLI.

**PR state guard — already enforced at the top of Step 7a.** The state re-check at the start of Step 7a guarantees smithers only reaches this point if the PR is OPEN. Do not add a second guard here.

Smithers posts to Slack only at Step 7a (PR ready). No Slack notification is sent for other stopping conditions (stagnation stop, max cycles, etc.).

---

## NOTES

- The 1-minute ScheduleWakeup is the platform-minimum cadence; sufficient for typical CI pipelines.
- Most state is in the conversation context. Two exceptions are `clean_confirmed` and `slack_posted`, which use flag files (`.smithers/clean_confirmed`, `.smithers/slack_posted`) because they must survive the ScheduleWakeup gap and — in the case of `slack_posted` — also survive watcher restarts.
- If this session is killed and restarted, the loop restarts from cycle 1 with a fresh `fix_count` and `stagnation_count`. The `clean_confirmed` flag file persists across restarts — if it exists when smithers restarts, smithers will proceed directly to Step 7a on the next no-work cycle. This is intentional and correct behavior.
- The smithers-post Slack notification (Step 7a) deduplicates across sessions via the `.smithers/slack_posted` flag. If the watcher restarts on a PR that already has the flag set, smithers will skip the Slack post. To re-post (e.g., after a status change such as REVIEW_REQUIRED → APPROVED → MERGED that warrants re-notifying reviewers), the user manually removes `.smithers/slack_posted`.
