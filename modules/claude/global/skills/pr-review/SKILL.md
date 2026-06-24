---
name: pr-review
description: Orchestrate a specialist team review of a GitHub PR. Auto-detects which domain experts to involve based on the diff and aggregates their findings into a structured PR review comment. Invoke when user says "review PR", "code review PR #N", "run a review on this PR", "get specialist review", or "review pull request".
model: sonnet
argument-hint: "[pr-number or url] [--repo owner/repo]"
# allowed-tools grants permissions for THIS skill's own Claude invocation only.
# It does NOT propagate to Task sub-agents spawned within the skill.
# Sub-agent permissions must be pre-approved in the project's permissions.allow
# (see Hard Prerequisites section below).
allowed-tools:
  - Read
  - Bash(gh pr *)
  - Bash(gh api *)
  - Bash(kanban *)
  - Bash(prc *)
  - Bash(prr *)
  - Bash(git branch *)
  - Bash(git rev-parse *)
  - Bash(crew *)
  - Bash(workout *)
---

# Review Pull Request

**Purpose:** Orchestrate a parallel specialist team review of a GitHub PR — auto-detecting which domain experts to involve, delegating to background agents, and posting a single unified GitHub review with inline comments.

## Invocation

$ARGUMENTS

Parse `$ARGUMENTS` for:
- PR number (e.g., `123`) or URL (e.g., `https://github.com/owner/repo/pulls/123`)
- Optional `--repo owner/repo` flag for cross-repo reviews (if omitted, use current repo)

**If no PR number or URL is provided in `$ARGUMENTS`:** Auto-detect from the current branch before doing anything else:

```bash
gh pr view --json number,url
```

Use the returned `number` as the PR to review. If this command fails (e.g., the current branch has no associated PR), stop immediately and tell the user: "No PR found for the current branch. Pass a PR number or URL directly."

## Hard Prerequisites

**Before anything else: verify required permissions are in the project's `permissions.allow`.**

Due to a known Claude Code bug ([GitHub #5140](https://github.com/anthropics/claude-code/issues/5140)), global `~/.claude/settings.json` permissions are **not** inherited by projects with their own `permissions.allow` -- project settings replace globals entirely. To verify: read `.claude/settings.json` or `.claude/settings.local.json` in the project root and confirm each required permission appears in the `permissions.allow` array.

**Required:**
- `Read`
- `Bash(gh pr *)`
- `Bash(gh api *)`
- `Bash(kanban *)`
- `Bash(prc *)`
- `Bash(prr *)`
- `Bash(git branch *)`
- `Bash(git rev-parse *)`
- `Bash(crew *)`
- `Bash(workout *)`

This skill fetches PR diffs, posts unified GitHub reviews via `prr`, runs kanban operations for specialist cards, verifies inline comments via `prc`, and creates git worktrees via `crew` to give specialists full repository access. Without these permissions, operations silently fail in `dontAsk` mode.

**If any are missing:** Stop immediately. Do not start work. Surface to the user:
> "Blocked: One or more required permissions are missing from `permissions.allow`. Add `Bash(gh pr *)`, `Bash(gh api *)`, `Bash(kanban *)`, `Bash(prc *)`, `Bash(prr *)`, `Bash(git branch *)`, `Bash(git rev-parse *)`, `Bash(crew *)`, and `Bash(workout *)` before running /pr-review."

## Re-Review / Straight-Approval Mode

**Trigger:** When `/pr-review` is invoked explicitly in re-review mode — i.e., the invocation context, the watcher brief, or `$ARGUMENTS` contains the word `re-review` or `straight-approval` (greppable signal from the caller).

**In this mode, skip the full specialist review pass entirely.** The author has addressed prior feedback; the job is to confirm and help them land it, not to re-scrutinize the diff or surface a new round of findings. Opening a closed review loop with new findings is the failure mode to avoid.

**Re-review flow:**

1. Parse the PR number from `$ARGUMENTS` as normal.
2. Run the safety re-check: `gh pr view <pr> [--repo owner/repo] --json author,state,mergedAt,reviewDecision,reviews,latestReviews`.
3. **Abort conditions** (deliberate subset — a peer's COMMENTED does NOT block the straight approval; only CHANGES_REQUESTED by a non-author, non-bot human does):
   - `state != OPEN` or `mergedAt` non-null → nothing to do; exit cleanly.
   - `reviewDecision == APPROVED` → already straight-approved; exit cleanly (do NOT post a duplicate).
   - Any non-author, non-bot human has `state == CHANGES_REQUESTED` in `reviews` → genuinely blocked by a peer; exit cleanly.
4. **If none of the abort conditions are true:** post a **straight approval** via `prr submit <pr> --event APPROVE` (add `--repo owner/repo` if cross-repo) with a brief, friendly body: `"Thanks for addressing the comments — looks good."`. No new findings. No new inline comments. No specialist delegation. No re-litigating.
5. Report the approval posted and exit. The follow-through loop is not needed — an APPROVE event is a terminal state.

**Do NOT:** run Phase 1–5. Do NOT spawn specialists. Do NOT generate findings. Do NOT write a `.scratchpad/review-<number>.json` with inline comments. The straight approval is the entire output.

## Phase 1 — Worktree Setup + One-Way Handoff

**This is the first thing that happens.** The goal is to give specialists full branch context by running the review inside a dedicated worktree. The current session creates that environment and steps back.

### Worktree Handoff Guard

**Check the session startup message first.** If the IMPORTANT instruction injected at the top of this conversation contains ANY of the following signals:
- "You are already in the correct git worktree"
- "Do all your work in this directory"
- "Do NOT create new branches or new worktrees"

**→ Skip Phase 1 entirely. Proceed directly to Phase 2.**

The startup instruction is the authoritative override. A previous `/pr-review` invocation already performed the handoff — this session IS the worktree session. Branch name string comparison is irrelevant; running worktree logic again would create an infinite handoff loop.

### Determine Review Mode

**If `--repo` flag was used (cross-repo review):**
- Cannot create a local worktree for a different repository
- Skip worktree setup; proceed directly to Phase 2 (diff-only review)

**If same-repo review:**

Check whether the PR is from a fork:
```bash
gh pr view <number> --json isCrossRepository --jq .isCrossRepository
```

- **If fork PR (`true`):** Cannot check out the fork branch locally. Skip worktree setup; proceed to Phase 2 (diff-only review).

- **If same-repo branch (`false`):**

  **First: check whether the current session is already inside a git worktree.**

  ```bash
  # List all worktrees — primary entry is first; non-primary follow
  git worktree list --porcelain

  # Get current repo root
  git rev-parse --show-toplevel
  ```

  Compare the `git rev-parse --show-toplevel` output against the worktree list entries. If the current root matches a **non-primary** entry (any entry after the first) → **already in a worktree. Skip Phase 1 entirely. Proceed directly to Phase 2.**

  Being in a worktree is the reliable signal that a review environment is already set up. Branch-name comparison is irrelevant when already inside a worktree — the user may be on a tracking branch with a personal prefix (e.g., `karlhepler/signup-webapp`) while the PR `headRefName` is `signup-webapp`. Comparing these produces a false negative and creates an unnecessary nested worktree.

  **Only proceed to branch-name comparison if confirmed to be in the primary (main checkout) worktree:**

  ```bash
  # Get the PR branch name
  gh pr view <number> --json headRefName --jq .headRefName

  # Get current branch
  git branch --show-current
  ```

  - **If current branch == PR's `headRefName`:** Already on the right branch. Proceed to Phase 2.

  - **If current branch != PR's `headRefName`:** Create the worktree + TMUX window and hand off:
    ```bash
    crew create "<headRefName>" --tell "Review PR #<number>"
    ```
    Tell the user: "Opened a new TMUX window to review PR #<number> — switch to it to watch the review run."

    **STOP. Do not proceed.** The new staff session in the worktree will handle everything from here.

## Phase 2 — Fetch PR Context

```bash
# Fetch PR metadata (add --repo owner/repo if cross-repo)
gh pr view <number> --json number,title,author,body,url,baseRefName,headRefName [--repo owner/repo]

# Fetch full diff
gh pr diff <number> [--repo owner/repo]
```

Extract `{owner}/{repo}` for the Phase 6 API URL: use the `--repo` flag value if provided, otherwise parse it from the PR's `url` field (e.g., `https://github.com/owner/repo/pull/123`).

Extract changed file paths from diff header lines matching `+++ b/...`.

**Repository access:**
- Same-repo reviews: `git rev-parse --show-toplevel` gives `repo_path` — pass this to specialists for full codebase access
- Cross-repo or fork reviews: set `repo_path = null` — specialists receive diff only

Store PR metadata, `{owner}/{repo}`, and diff text in memory — all three are passed to each specialist and used in Phase 6.

## Phase 3 — Detect Domains

Apply these detection rules against changed file paths and diff content to build the specialist list:

| Specialist | Trigger Signals |
|---|---|
| `swe-backend` | `api/`, `routes/`, `handlers/`, `controllers/`, `db/`, `migrations/`, `*.go`, `*.py`, `*.rs`, server-side `*.ts` |
| `swe-frontend` | `components/`, `pages/`, `*.tsx`, `*.jsx`, `*.css`, `*.scss`, `*.html` |
| `swe-security` | `auth/`, `authz/`, `middleware/`, `jwt`, `oauth`, `password`, `token`, `secret`, `pii`, `payment`, input handling |
| `swe-sre` | `monitoring/`, `metrics/`, `alerts/`, retry/timeout/circuit-breaker patterns, error handling |
| `swe-devex` | `.github/`, `Dockerfile`, `Makefile`, `*.yml` (CI), test configs, build scripts |
| `swe-infra` | `*.tf`, `k8s/`, `helm/`, `*.yaml` (infra), cloud configs |
| `ai-expert` | `commands/`, `agents/`, `output-styles/`, `CLAUDE.md`, `hooks/`, prompt files |

**Security rule:** Always include `swe-security` when any auth, payment, PII, or public API surface is touched — even if no `auth/` directory appears in the diff.

**Minimum one specialist:** If detection yields none, default to `swe-backend`. Single-specialist reviews are valid.

## Phase 4 — Parallel Specialist Delegation

### Create All Kanban Cards at Once

Create all specialist cards in a single `kanban do '[...]'` array call. Each card:

```bash
kanban do '[
  {
    "type": "work",
    "action": "swe-backend review of PR #<number>: <title>",
    "intent": "Identify issues in the backend domain of this PR",
    "model": "sonnet",
    "criteria": [
      {
        "text": "Findings written to scratchpad file",
        "mov_commands": [
          {"cmd": "test -f .scratchpad/review-<number>-swe-backend.md", "timeout": 10}
        ]
      },
      {
        "text": "Verdict assigned (LGTM, concerns, or blocking)",
        "mov_commands": [
          {"cmd": "rg -q \"Verdict:\" .scratchpad/review-<number>-swe-backend.md", "timeout": 10}
        ]
      },
      {
        "text": "Scratchpad contains at least one FILE: finding or an LGTM verdict",
        "mov_commands": [
          {"cmd": "rg -q \"FILE:|LGTM\" .scratchpad/review-<number>-swe-backend.md", "timeout": 10}
        ]
      }
    ]
  },
  {
    "type": "work",
    "action": "swe-security review of PR #<number>: <title>",
    "intent": "Identify security issues in this PR",
    "model": "sonnet",
    "criteria": [
      {
        "text": "Findings written to scratchpad file",
        "mov_commands": [
          {"cmd": "test -f .scratchpad/review-<number>-swe-security.md", "timeout": 10}
        ]
      },
      {
        "text": "Verdict assigned (LGTM, concerns, or blocking)",
        "mov_commands": [
          {"cmd": "rg -q \"Verdict:\" .scratchpad/review-<number>-swe-security.md", "timeout": 10}
        ]
      },
      {
        "text": "Scratchpad contains at least one FILE: finding or an LGTM verdict",
        "mov_commands": [
          {"cmd": "rg -q \"FILE:|LGTM\" .scratchpad/review-<number>-swe-security.md", "timeout": 10}
        ]
      }
    ]
  }
]' --session <current-session>
```

Adapt the array to include only detected specialists. Note the card numbers returned.

**Note:** Specialist identity (e.g., `swe-backend`, `swe-security`) is supplied via the Agent tool's `subagent_type` parameter at launch time — it is NOT a card field.

### Launch All Specialists in Parallel

**Before constructing each specialist prompt:** fully resolve every `{if ...}` conditional block. Evaluate each condition against the actual context values collected in Phase 2. Replace each block with its inner text if the condition is true, or with nothing if false. Never pass an unresolved `{if ...}` marker to a specialist — the specialist receives only clean, literal text.

In a **single message**, make one Agent tool call per specialist (all in parallel), setting `subagent_type` to the specialist identity (e.g., `subagent_type: "swe-backend"`, `subagent_type: "swe-security"`). Each specialist receives:

```
You are a {domain} specialist reviewing PR #{number}: {title}

**Author:** {author}
**Base ← Head:** {baseRefName} ← {headRefName}

**PR Description:**
{body}

**Full Diff:**
{diff text}

---

**Your Domain Focus ({domain}):**
{domain-specific focus instructions — see below}

**Full Repository Access:**
<!-- ORCHESTRATOR: Replace the block below with resolved text — never emit {if ...} markers literally in the final prompt. -->
{if repo_path is set:
The complete PR branch is checked out at: `{repo_path}`

You have full read access to the entire repository. Use it to:
- Read surrounding code to understand context beyond the diff
- Check existing patterns, conventions, and abstractions in the codebase
- Look at tests to understand expected behavior and coverage gaps
- Read local docs (README, docs/ folder) for project conventions
- Understand import relationships and how changed code fits the larger system

You are NOT limited to the diff. Treat the diff as the focal point, but use the full repository to give informed, contextual reviews.
}
{if repo_path is null:
  {if --repo flag was used:
**Note:** This PR is in a different repository (`--repo` flag). The repository is not checked out locally — review is based on the diff only.
  }
  {if fork PR:
**Note:** This PR is from a forked repository. The fork branch is not available locally for worktree checkout — review is based on the diff only.
  }
}

**Citation Requirement:**
For citation rules, acceptable sources, and examples, Read [review-citation-guide.md](review-citation-guide.md).

**Reviewer Orientation:**
You are on the author's side. Your job is to help confirm that intent is carried through and to catch things that might bite them — not to audit or gatekeep. Assume the author was deliberate and had a reason. Approach every finding with curiosity and respect.

**Tone and Format (applies to all output — inline comments and body-level findings alike):**
- **1–3 sentences max** per inline finding. Use line breaks to stay readable. If a comment covers multiple distinct points, use bullets instead of one dense paragraph.
- **Curious when uncertain** — "did you mean to...?", "is this intentional?", "curious if this could...", "curious if..." Sound like a friend whose PR you want to help land.
- **No severity label prefixes** in comment text — never write `[blocking]`, `[concern]`, `[nit]`, or any square-bracket qualifier. Severity belongs in the SEVERITY field only.
- **No chain-of-thought** — state the observation, optionally note why it matters, done. No "I confirmed this by reviewing..." explanations.
- **No specialist attribution** — comments are posted as a unified review. No `[swe-security]` or similar.
- **Default to COMMENT severity** — only use blocking for high-risk issues: regressions, security vulnerabilities, or data loss.
- **When in doubt, leave it out** — if a finding is borderline or minor, cut it entirely. No nits — drop them hard; bots already review the PR and surface style/nit-level observations.
- **Confirm intent before flagging** — a deviation that looks wrong may be the intentional design. Before treating it as a defect, ask: "is this intentional?" If the code could plausibly serve the author's stated intent, verify intent first rather than flagging it outright. Use curious phrasing ("did you mean to...?", "is this intentional?") to surface the question instead.
- **Bias toward APPROVE** — when a change is safe (no blocking issue: security / data-loss / regression / correctness) AND serves the author's stated intent, approve. Non-blocking suggestions become optional 'follow-up to consider' notes folded inside the approval, not a withheld verdict. Reserve COMMENT / CHANGES_REQUESTED for genuinely blocking issues only.
- **Tentative phrasing for suggestions** — for non-blocking findings and suggestions, use tentative, collaborative language. Preferred phrasings: "probably worth ...", "might be worth ...", "could be worth considering ...", "one option might be ...", "no strong opinion, but ...". These pair naturally with the curious framing above ("curious if...", "did you mean to...?"). Reserve firmer, more direct wording only for genuinely blocking issues (security, data-loss, regression) — and even then stay respectful.
  - **Anti-patterns for non-blocking suggestions:** "worth doing X", "you should X", and bare imperatives — they land as directives even when meant as suggestions.

**Required Output Format:**
Write your complete findings to `.scratchpad/review-{number}-{domain}.md` using this structure:

## {Domain} Review

**Verdict:** ✅ LGTM | ⚠️ Concerns | 🚨 Blocking Issues

### Findings

FILE: path/to/file.go
LINE: 42
SEVERITY: blocking | concern | comment
COMMENT: [Inline comment text — 1–3 sentences, plain language, no severity label prefix, no specialist attribution. Use bullets if multiple distinct points. Cite sources inline when referencing standards.]

### Overall Observations
[Findings with no specific file or line location — e.g. architecture concerns, missing test coverage patterns, cross-cutting issues. These will be folded into the review body as bullet points, NOT posted as inline comments. Write each as a short plain-language statement — no severity prefixes.]

- [observation]

### Summary
[1–3 sentences]

If no findings in your domain, return `✅ LGTM` with a one-line summary. No findings or observations block needed.

**Kanban:**
Your card number is #{card-number}. Session is {current-session}.
After completing each AC, run: `kanban criteria check #{card-number} <n> --session {current-session}`
When all AC are checked, stop. The SubagentStop hook calls `kanban done` automatically.
```

### Domain-Specific Focus Instructions

For domain-specific focus text to include under **Your Domain Focus ({domain}):** in each specialist's prompt, see [review-domains.md](review-domains.md).

**Injection rule for the Cross-Cutting section:** After the per-domain focus line, append the full **Cross-Cutting: Composition Wiring and Lifecycle** section from `review-domains.md` to EVERY specialist's prompt. This section is in addition to the domain-focus line — not a replacement for it. Every specialist receives both: their one-line domain block AND the full cross-cutting section.

## Phase 5 — Wait for Specialists and Aggregate

Phase 4 ends when all specialist Task agents have been launched. Phase 5 monitors their completion and aggregates findings.

**Simplified lifecycle — specialists complete cards directly via criteria checks; the SubagentStop hook finalizes each card:**

- Each specialist calls `kanban criteria check` after each AC. The kanban CLI runs MoVs synchronously.
- When a specialist finishes and stops, the SubagentStop hook automatically calls `kanban done`.
- If `kanban done` fails (unchecked AC), the hook blocks the specialist with feedback; the specialist re-runs in `doing`. The kanban CLI enforces a max of 3 cycles.
- The orchestrator monitors completion by polling `kanban list --session <id>` and checking for cards in the `done` status.

**Monitor specialist completion:**

```bash
# Poll until all specialist card numbers appear in done status
kanban list --session <current-session>
```

Check whether each specialist card number has reached `done`. Repeat periodically until all specialist cards are `done` or until max retries have been exhausted (kanban CLI enforces this — the card will show as `canceled` after 3 failed cycles).

**Do NOT proceed to aggregation until ALL specialist cards have reached `done` or `canceled`.**

If a card ends up `canceled` (exhausted retries), proceed without that specialist's findings and note the gap in the aggregated review body.

### Read All Specialist Findings

```bash
# Read each specialist's scratchpad output
# e.g.:
# .scratchpad/review-<number>-swe-backend.md
# .scratchpad/review-<number>-swe-security.md
# etc.
```

### Assemble Aggregated Review Body

**Minimal-footprint output:** This PR is also reviewed by automated bots — bots already review for style, nits, and surface-level observations. At aggregation, drop nits and non-important findings hard. High-effort review process (keep all specialists, collect their full guidance) — minimal-footprint posted output. When in doubt about whether to include a finding, leave it out. No nits.

**Verdict bias:** bias toward APPROVE when the change is safe (no blocking issue: security / data-loss / regression / correctness) and serves the author's stated intent. Non-blocking suggestions fold inside the approval as optional follow-up notes — they do not withhold the verdict.

The review body must read as if one developer wrote it — no headers, no specialist attribution, no tooling metadata.

**Tone rules — no exceptions:**
- No openers like "The core logic is sound", "Overall this looks good, but...", or "X concerns worth discussing before merging"
- No audit framing — this is not a formal assessment, it's a colleague talking to you
- No `## Expert Code Review` header, no `**Reviewed by:**` line, no `**Inline comments: N**` metadata
- If everything looks good: one sentence saying so — or leave the body empty
- If there's something to flag: say it directly and naturally, like you're Slacking the author
- **Tentative phrasing for suggestions** — apply the same rule from the inline comment guidance above: suggestions use "probably worth ...", "might be worth ...", "could be worth considering ..." phrasing; never "worth doing X", "you should X", or bare imperatives for non-blocking findings; firmer wording is fine for genuinely blocking issues (security, data-loss, regression)

```
{If any specialist found blocking or concern-level issues:
Write 1–3 sentences in plain, conversational language about what's worth looking at.
If there are null-path findings (Overall Observations), append them as a flat bullet list after
the prose — one bullet per finding, plain language, no severity label prefixes.}

{If all specialists returned LGTM: leave the body empty string "".}
```

Write the aggregated review body to `.scratchpad/review-<number>.md` before posting.

### Voice-Conformance Check

Before writing the findings JSON, load `~/.claude/skills/user-voice/SKILL.md` and run a voice-conformance check (use the work-peer register: direct, contractions, curious-direct phrasing — "did you mean to...?", "curious if..." — casual-professional formality, customer/user-impact-first framing, no Hard Avoids from that profile, close on the upshot not evidence framing, short paragraphs, no prologue) on:

1. The aggregated review body
2. Every inline comment in the `comments` array

Apply light voice-conformance editing to conform phrasing — preserve technical content exactly. Hard Avoids to check at minimum: `leverage`, `genuinely`, `circle back`, hedging closers, evidence-framing closes. Remove any instance of `Genuinely` as an emphasis word. Conform curious phrasing to "did you mean to...?", "curious if...?", "is this intentional?" forms.

### Write Findings JSON

In addition to the `.md` summary, write `.scratchpad/review-<number>.json` with the structured findings for `prr`:

```json
{
  "body": "<aggregated review body — 1–3 sentence conversational summary followed by null-path findings as bullet points, or empty string if all LGTM>",
  "comments": [
    {"path": "src/auth/login.go", "line": 42, "severity": "blocking", "body": "Have you considered..."}
  ]
}
```

Aggregate all specialist FILE/LINE/SEVERITY/COMMENT findings (those with actual file paths) into the `comments` array.

**🚨 Never put null-path findings in `comments`.** Entries with `path: null` are silently dropped or mishandled by `prr`. Instead, fold all null-path findings (from specialists' "Overall Observations" sections) directly into the `body` field as bullet points appended after the summary text.

**Comment body rules:**
- Preserve technical content exactly — do not prepend severity labels (`[blocking]`, `[concern]`) or specialist attribution (`[swe-security]`). Light voice-conformance editing (see voice-conformance step above) supersedes any instruction to use the specialist's COMMENT text verbatim: conform phrasing to the user-voice profile while preserving technical content exactly.
- The comment body must be plain text only: 1–3 sentences or bullets, developer voice

## Phase 6 — Post Review

Post a **single unified GitHub review** via `prr`.

### FINAL PRE-POST CHECK

**Run this check immediately before `prr submit` — after all aggregation, voice-conformance, and JSON-writing are complete.** The race window is the entire review duration; stale/redundant output is discarded silently rather than posted.

Re-fetch the PR state at the last possible moment:

```bash
gh pr view <pr> --repo <org>/<repo> --json author,state,mergedAt,reviewDecision,reviews,latestReviews
```

**ABORT the post (emit "superseded — not posting" and exit cleanly, posting NOTHING) if ANY of the following are true:**

- `state` != `OPEN` (merged or closed)
- `mergedAt` is non-null
- `reviewDecision` == `APPROVED` — another approval already satisfied requirements; also covers merge-queue entry since approval is a prerequisite for the queue

  Note: `gh pr view --json` exposes NO `mergeQueueEntry` field. `reviewDecision == APPROVED` already covers the merge-queue case — a PR cannot enter the merge queue without being approved.

- Any review in `reviews` or `latestReviews` by a **real human** (not a bot) who is not the PR author AND whose `state` is one of `{APPROVED, COMMENTED, CHANGES_REQUESTED}`.

  **The PR author's own self-review / self-comment does NOT count as an independent review — authors routinely self-comment to explain their change.** Only count a review if the reviewer is (a) NOT the PR author and (b) a real human (not a bot).

  **Bot detection rules (all three must hold to treat a reviewer as a real human):**
  1. Login does NOT end in `[bot]` (e.g., `dependabot[bot]`, `github-actions[bot]`)
  2. `gh api users/<login>` returns HTTP 200 (login exists — not a phantom or deleted account)
  3. `type == "User"` in the GitHub API user response (not `"Bot"` or `"Organization"`)

**Rationale:** "We already did the work" is NOT a reason to post. Stale, duplicate, or superseded output is discarded silently. The check runs at the LAST possible moment before the write because the race window IS the entire review duration.

If the check passes (none of the abort conditions are true), proceed immediately to `prr submit` below.

### Submit via prr

```bash
prr submit <pr-number> --findings .scratchpad/review-<pr-number>.json
```

`prr` handles all mechanics: loading the findings JSON, fetching the head commit SHA, separating inline vs body-level comments, auto-determining the event from severity fields, and posting the review via the GitHub REST API.

**All-LGTM case:** When all specialists returned LGTM (body is `""` and `comments` array is empty), submit an explicit APPROVE event:

```bash
prr submit <pr-number> --findings .scratchpad/review-<pr-number>.json --event APPROVE
```

Override the event explicitly if needed:

```bash
prr submit <pr-number> --findings .scratchpad/review-<pr-number>.json --event REQUEST_CHANGES
```

**Note on line numbers:** GitHub's review API requires the line number to be within the diff hunk. If a specialist's line number falls outside the diff, remove that entry from the `comments` array and apply the voice-conformance check (per the Voice-Conformance Check step above) before folding the comment text into the `body` field manually as a bullet point — do not set `path: null` and `line: null`, as null-path entries in `comments` are silently dropped by `prr`.

### Verify and Report

Read `inline_count` and `body_count` directly from `prr`'s JSON output — no separate `prc list` call needed.

Report back:
- How many inline comments were posted (`inline_count` from prr output)
- How many findings went into the review body (`body_count` from prr output)
- Which specialists flagged concerns vs. LGTM
- The overall review event (`event` from prr output)

## Follow-Through After a Non-Approving Review

**Trigger:** Only when the submitted review event is COMMENT or CHANGES_REQUESTED — a non-approving review. An APPROVE review needs no follow-up.

**Guiding principle:** The intent of review is to HELP the author land their change — be curious and inquisitive, catch genuinely dangerous issues, confirm the code serves the author's stated intent. Do not gate; do not leave teammates hanging. Help our friends get their PRs through. This behavior generalizes to ANY automated PR-review workflow, not just one repo or channel.

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

## Critical Rules

**Worktree handoff is one-way:**
- When Phase 1 creates a worktree, the current session STOPS immediately after
- Do NOT continue doing review work in the current session after handing off
- Do NOT wait for the new session to complete

**Never post before all specialists complete:**
- Do NOT submit the GitHub review until every specialist card has reached `done` or `canceled` per Phase 5
- Do NOT skip specialist completion monitoring to save time

**Single unified review:**
- All findings go into ONE GitHub review submission
- Never submit multiple separate reviews or `gh pr comment` calls
- Inline placement (file:line) preferred; body-level for findings without a specific location

**Human voice — no tooling artifacts:**
- No `## Expert Code Review` header or any header in the review body
- No `**Reviewed by:**` or specialist attribution of any kind
- No severity labels in comment text (`[blocking]`, `[concern]`, `[nit]`)
- No `*Specialist team review via Claude Code*` footer
- The posted review must read as if one developer wrote it

**No nits — minimal-footprint output:**
- Bots already review the PR — do not duplicate what bots already surface
- If a finding is borderline or minor, cut it entirely; no nits
- Only include findings worth surfacing to the author
- When in doubt, leave it out
- **Bias toward APPROVE**: safe changes that serve the author's stated intent get approved; non-blocking suggestions go inside the approval as optional follow-up notes, not a withheld verdict
- Confirm intent before flagging a deviation as a defect — it may be the intentional design

**Preserve specificity:**
- Keep file:line pairs from specialist output intact in the inline comments array
- Never flatten findings into vague body-level summaries when a specific location exists

**Verification:**
- Read `inline_count` and `body_count` directly from `prr`'s JSON output to confirm counts (no separate `prc list` call needed)
- If inline comments are missing from `prr` output, check whether line numbers fell outside diff hunks and repost affected findings in the review body

**Detection is a starting point, not gospel:**
- If the diff has an unusual structure, use judgment to add specialists the heuristics missed — the goal is coverage, not mechanical matching

**Specialist completion monitoring is not optional:**
- Wait for every specialist card to reach `done` or `canceled` before aggregating. The kanban lifecycle verifies specialist output quality automatically via MoV checks in the SubagentStop hook.
