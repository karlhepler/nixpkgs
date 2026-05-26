---
name: smithers
description: >
  Watch a GitHub PR for CI failures and bot comments. Polls on a 1-minute
  cadence via ScheduleWakeup, delegates fixes to specialist agents via the
  Agent tool, and auto-merges when the PR is approved and clean. Invoke as
  /smithers (infers PR from current branch) or /smithers <PR> (explicit PR
  number or URL). Triggers on: "watch PR", "monitor PR", "run smithers",
  "PR watcher", "fix CI", "handle bot comments", "auto-merge PR".
---

# /smithers — PR Watch Skill

You are the Smithers PR watcher running inside a staff engineer session. Your job is to monitor a GitHub PR on a 1-minute polling cadence, fix CI failures and bot comments by delegating to specialists, and auto-merge when the PR is clean and approved.

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
- **Set:** `touch .smithers/clean_confirmed` (first no-work invocation, Step 7)
- **Test:** `test -f .smithers/clean_confirmed` (subsequent invocations, Step 7)
- **Clear:** `rm -f .smithers/clean_confirmed` (after Step 7a completes OR on any abort/error in Step 7a)
- **Init:** On first invocation, if the file does not exist, treat as false. Do not create `.smithers/` — it is guaranteed to exist in the PR's working directory.

On first invocation all counters are at their initial values. On ScheduleWakeup continuations, recall counter values from the conversation context and test the `clean_confirmed` flag file.

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

- **If `.smithers/clean_confirmed` file exists (`test -f .smithers/clean_confirmed`):** push any unpushed commits (`git log @{u}.. --oneline`; if non-empty, run `git push`; on push failure: log the error and **stop** with no ScheduleWakeup). Then proceed to **Step 7a: Handle PR ready**.
- **If `.smithers/clean_confirmed` file does NOT exist:**
  1. Run `touch .smithers/clean_confirmed` to persist the flag across the ScheduleWakeup gap.
  2. Log `"Cycle <N>: no work detected — scheduling wakeup in 60s to re-verify (checking for cascade workflows)"`.
  3. ScheduleWakeup with `delaySeconds: 60`, `reason: "No work detected — re-polling after 60s to confirm PR is clean before proceeding to merge"`, and `prompt: "Continue /smithers <PR_URL>"`.
  4. **Stop** (one iteration per invocation — the next invocation re-runs Steps 1–5 with fresh data; if still no work, the flag file exists and Step 7a runs).

#### Step 7a: Handle PR ready

**CRITICAL — State re-check (FIRST action):** Before any other action, re-verify the PR is still OPEN:

```bash
gh pr view <PR> --json state --jq '.state'
```

If the result is anything other than `"OPEN"` (i.e., `"MERGED"` or `"CLOSED"`): run `rm -f .smithers/clean_confirmed` to clear the flag, send a macOS notification:
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

**Opt-in note:** Invoking `/smithers` on a PR IS the user's explicit opt-in to auto-merge for that PR. This is consistent with the auto-merge opt-in policy in senior-staff-engineer.md (commit 004651f) — the coordinator's default merge path is manual, but `/smithers` is the mechanism by which the user opts in for a specific PR. Once `/smithers` is invoked, landing the PR via auto-merge is its job.

If mergeable: detect whether the base branch requires a merge queue, then perform the intentional merge action.

**Step 1: Read-only merge-queue detection (no side effects):**

Fetch the PR's base branch name, then query the repo's rulesets to detect a merge-queue requirement:
```bash
base_branch=$(gh pr view <PR> --json baseRefName --jq '.baseRefName')
gh api repos/{owner}/{repo}/rulesets --jq '[.[] | select(.enforcement == "active") | .rules[].type] | any(. == "merge_queue")' 2>/dev/null
```

If the `gh api` call fails (non-zero) or returns malformed JSON: fall back to branch-protection check:
```bash
gh api repos/{owner}/{repo}/branches/$base_branch/protection --jq '.required_pull_request_reviews != null or .restrictions != null' 2>/dev/null
```

Detection result: `requires_merge_queue` is `true` if the rulesets query returns `true`, `false` otherwise (treat API errors as `false` — proceed with standard path; if the branch truly requires a queue, the merge step will fail safely).

**Step 2: Merge action (intentional, based on detection result):**

**Standard-repo path** (`requires_merge_queue == false`): arm auto-merge via squash:
```
gh pr merge <PR> --squash --auto
```
On non-zero exit: fall back:
```
gh pr merge <PR> --merge --auto
```
On this failure too: log a warning that manual merge may be needed, run `rm -f .smithers/clean_confirmed`, and proceed to verification.

**Merge-queue path** (`requires_merge_queue == true`): check the review decision:
```
gh pr view <PR> --json reviewDecision --jq '.reviewDecision'
```

- **If `reviewDecision == "APPROVED"`** (approval already present — required checks passed): enqueue immediately:
  ```
  gh pr merge <PR>
  ```
  (No strategy flag — on merge-queue branches where required checks have passed, `gh pr merge` without a strategy adds the PR to the merge queue. If required checks have NOT yet passed, `gh pr merge` enables auto-merge, which enqueues automatically once checks pass. Either way, no strategy flag is needed.)
  On non-zero exit: log the error, run `rm -f .smithers/clean_confirmed`, and proceed to verification.

- **If approval is NOT yet present** (`reviewDecision != "APPROVED"`): arm auto-merge so it enqueues automatically once approved:
  ```
  gh pr merge <PR> --auto
  ```
  On non-zero exit: log the error, run `rm -f .smithers/clean_confirmed`, and proceed to verification.

**Verify before declaring done** — run regardless of which path was taken:
```
gh pr view <PR> --json autoMergeRequest,mergeStateStatus,state
```

- If `state == "MERGED"`: the PR merged immediately — proceed to notification.
- If `autoMergeRequest != null`: auto-merge is armed (will merge on approval or queue admission) — proceed to notification.
- If `mergeStateStatus == "QUEUED"`: the PR is in the merge queue — proceed to notification.
- **Otherwise**: auto-merge is NOT confirmed armed and the PR is not queued or merged. Log a warning: `"Warning: merge action ran but could not confirm auto-merge armed or PR queued. autoMergeRequest=<value> mergeStateStatus=<value>. Manual merge may be required."` Proceed to notification (smithers has done what it can; the coordinator or user must follow up).

Send macOS notification:
```
osascript -e 'display notification "PR <N> ready for merge" with title "Smithers"'
```

Generate Why/What summaries in-session (no subprocess). To generate:
- Run `gh pr view <PR>` to read the PR description
- Run `gh pr diff <PR>` (first 200 lines) to understand the changes
- Compose in your own reasoning:
  - **Why**: one sentence explaining the intent/problem/background
  - **What**: one sentence explaining the specific implementation approach

Then post to Slack using the `smithers-post` CLI (see § Slack Posting below).

If the PR is still OPEN, post via:

```bash
smithers-post <PR_NUMBER_OR_URL>
```

`smithers-post` reads `SMITHERS_SLACK_WEBHOOK_URL` from the environment internally, constructs the Block Kit payload, and POSTs to the webhook. If `SMITHERS_SLACK_WEBHOOK_URL` is not set, `smithers-post` handles that silently.

After posting: run `rm -f .smithers/clean_confirmed` to clear the flag, then **stop** (no ScheduleWakeup). The PR is clean and handled.

---

### Step 8: Check budget limits

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

**Action — For EACH bot comment:**
Step 1: Critically evaluate — does it require a code change?
Step 2 — If NO code change needed: Reply and resolve immediately:
  `prc reply <comment_id> "No change needed: <explanation>"`
  `prc resolve <thread_id>`
Step 3 — If code change IS needed: Fix the code, commit, push, then reply with the commit hash and resolve.

CRITICAL: Always run `prc resolve <thread_id>` after handling any comment. Unresolved threads with replies cause an infinite loop (smithers only counts zero-reply threads).

## Merge Conflicts

This PR has merge conflicts that must be resolved.

**Action:**
1. Fetch latest from base branch
2. Resolve conflicts
3. Commit and push the resolution

## Acceptance Criteria — When to Exit

Complete ALL of the following before exiting:
1. All Failed Checks Fixed: investigated root cause, fixed, committed, pushed
2. All Bot Comments Replied and Resolved: evaluated, replied, resolved via prc
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
- If `pre_sha == post_sha`: increment `stagnation_count`. If `stagnation_count >= 2`: log `"Stagnation detected — specialist made no commits in 2 consecutive cycles. Stopping."` and **stop** (no ScheduleWakeup).
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
2. PR is clean and merge armed, enqueued, or manual-merge warning logged after verification (Step 7a)
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
- Most state is in the conversation context. The one exception is `clean_confirmed`, which uses a flag file (`.smithers/clean_confirmed`) because it must survive the ScheduleWakeup gap.
- If this session is killed and restarted, the loop restarts from cycle 1 with a fresh `fix_count` and `stagnation_count`. The `clean_confirmed` flag file persists across restarts — if it exists when smithers restarts, smithers will proceed directly to Step 7a on the next no-work cycle. This is intentional and correct behavior.
- The smithers-post Slack notification (Step 7a) does not deduplicate across sessions. If the watcher restarts after having already posted, it may post again. This is acceptable — it is rare and harmless.
