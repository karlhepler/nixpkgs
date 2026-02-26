---
name: review
description: Orchestrate a specialist team review of a GitHub PR. Auto-detects which domain experts to involve based on the diff and aggregates their findings into a structured PR review comment. Invoke when user says "review PR", "code review PR #N", "run a review on this PR", "get specialist review", or "review pull request".
disable-model-invocation: true
model: sonnet
argument-hint: "[pr-number or url] [--repo owner/repo]"
allowed-tools:
  - Bash(gh pr *)
  - Bash(gh api *)
  - Bash(kanban *)
  - Bash(prc *)
  - Bash(prr *)
  - Bash(git branch *)
  - Bash(git rev-parse *)
  - Bash(workout-claude *)
  - Bash(workout *)
---

# Review Pull Request

**Purpose:** Orchestrate a parallel specialist team review of a GitHub PR — auto-detecting which domain experts to involve, delegating to background agents, running AC review, and posting a single unified GitHub review with inline comments.

## Invocation

$ARGUMENTS

Parse `$ARGUMENTS` for:
- PR number (e.g., `123`) or URL (e.g., `https://github.com/owner/repo/pulls/123`)
- Optional `--repo owner/repo` flag for cross-repo reviews (if omitted, use current repo)

## Hard Prerequisites

**Before anything else: verify required permissions are in the project's `permissions.allow`.**

Due to a known Claude Code bug ([GitHub #5140](https://github.com/anthropics/claude-code/issues/5140)), global `~/.claude/settings.json` permissions are **not** inherited by projects with their own `permissions.allow` -- project settings replace globals entirely. To verify: read `.claude/settings.json` or `.claude/settings.local.json` in the project root and confirm each required permission appears in the `permissions.allow` array.

**Required:**
- `Bash(gh pr *)`
- `Bash(gh api *)`
- `Bash(kanban *)`
- `Bash(prc *)`
- `Bash(prr *)`
- `Bash(git branch *)`
- `Bash(git rev-parse *)`
- `Bash(workout-claude *)`
- `Bash(workout *)`

This skill fetches PR diffs, posts unified GitHub reviews via `prr`, runs kanban operations for specialist cards, verifies inline comments via `prc`, and creates git worktrees via `workout-claude` to give specialists full repository access. Without these permissions, operations silently fail in `dontAsk` mode.

**If any are missing:** Stop immediately. Do not start work. Surface to the user:
> "Blocked: One or more required permissions are missing from `permissions.allow`. Add `Bash(gh pr *)`, `Bash(gh api *)`, `Bash(kanban *)`, `Bash(prc *)`, `Bash(prr *)`, `Bash(git branch *)`, `Bash(git rev-parse *)`, `Bash(workout-claude *)`, and `Bash(workout *)` before running /review."

## Phase 1 — Worktree Setup + One-Way Handoff

**This is the first thing that happens.** The goal is to give specialists full branch context by running the review inside a dedicated worktree. The current session creates that environment and steps back.

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
  ```bash
  # Get the PR branch name
  gh pr view <number> --json headRefName --jq .headRefName

  # Get current branch
  git branch --show-current
  ```

  - **If current branch == PR's `headRefName`:** Already on the right branch. Proceed to Phase 2.

  - **If current branch != PR's `headRefName`:** Create the worktree + TMUX window and hand off:
    ```bash
    echo '[{"worktree": "<headRefName>", "prompt": "Review PR #<number>"}]' | workout-claude staff
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
    "persona": "swe-backend",
    "model": "sonnet",
    "criteria": [
      "Findings returned in required structured format (FILE/LINE/SEVERITY/COMMENT blocks)",
      "Verdict assigned (LGTM, concerns, or blocking)",
      "Backend focus areas checked: N+1 queries, error handling, input validation, race conditions, transaction boundaries"
    ]
  },
  {
    "type": "work",
    "action": "swe-security review of PR #<number>: <title>",
    "intent": "Identify security issues in this PR",
    "persona": "swe-security",
    "model": "sonnet",
    "criteria": [
      "Findings returned in required structured format (FILE/LINE/SEVERITY/COMMENT blocks)",
      "Verdict assigned (LGTM, concerns, or blocking)",
      "Security focus areas checked: auth/authz gaps, injection vectors, PII exposure, OWASP Top 10"
    ]
  }
]' --session <current-session>
```

Adapt the array to include only detected specialists. Note the card numbers returned.

### Launch All Specialists in Parallel

In a **single message**, make one Task tool call per specialist (all in parallel). Each specialist receives:

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
For any finding that references a best practice, standard, library API usage, or asserts that something "should be documented" — you MUST verify it and cite the source inline in your COMMENT text. Do not assert from memory.

Acceptable sources (in priority order):
1. Local docs: read `{repo_path}/docs/`, `{repo_path}/README.md`, CLAUDE.md, etc. (if repo_path is available)
2. Context7 MCP: use `mcp__context7__resolve-library-id` then `mcp__context7__query-docs` to look up library/framework documentation
3. Official online documentation: WebFetch the authoritative source URL

Embed the citation naturally in your COMMENT:
COMMENT: This approach can expose users to SQL injection (OWASP A03:2021 Injection — https://owasp.org/Top10/A03_2021-Injection/). Parameterized queries are the standard fix.

Findings that are purely observational (e.g., "this variable is shadowed") do not require citation.

**Tone and Scope:**
Write as if you personally reviewed this code — direct, collegial, human.
- One paragraph per inline finding — no more
- If a finding is borderline or minor, cut it entirely. Only include findings worth surfacing to the author
- No severity labels in the COMMENT text itself — severity belongs in the SEVERITY field only
- No specialist attribution in comments — they will be posted as a unified review
- Assume the author was deliberate — ask why before calling something wrong
- Flag issues clearly but without condescension

**Required Output Format:**
Write your complete findings to `.scratchpad/review-{number}-{domain}.md` using this structure:

## {Domain} Review

**Verdict:** ✅ LGTM | ⚠️ Concerns | 🚨 Blocking Issues

### Findings

FILE: path/to/file.go
LINE: 42
SEVERITY: blocking | concern
COMMENT: [Inline comment text — one paragraph, plain language, no severity label prefix, no specialist attribution, cite sources inline when referencing standards]

FILE: (none)
LINE: (none)
SEVERITY: concern
COMMENT: [Overall finding with no specific location — goes in review body]

### Summary
[1-2 sentences]

If no findings in your domain, return `✅ LGTM` with a one-line summary. No findings block needed.

**Kanban:**
Your card number is #{card-number}. Session is {current-session}.
When done: `kanban review #{card-number} --session {current-session}`
```

### Domain-Specific Focus Instructions

Include the appropriate block in each specialist's prompt:

**swe-backend:**
> N+1 queries, error handling patterns, input validation, API contract consistency, race conditions, data modeling soundness, transaction boundaries

**swe-frontend:**
> Accessibility (WCAG 2.1 AA), React performance (unnecessary re-renders, missing memo), bundle size impact, error boundaries, mobile responsiveness, keyboard navigation

**swe-security:**
> Auth/authz gaps, injection vectors (XSS, SQLi, path traversal), PII exposure, credential handling, OWASP Top 10, privilege escalation, SSRF

**swe-sre:**
> Timeout/retry/circuit-breaker patterns, observability gaps (logging/metrics/tracing), resource leaks, graceful degradation, health check coverage

**swe-devex:**
> CI/CD correctness and security (pinned actions), test coverage adequacy, dependency pinning, build safety, documentation accuracy

**swe-infra:**
> IAM least-privilege, resource sizing, HA considerations, secret management (no hardcoded secrets), idempotency of provisioning

**ai-expert:**
> Prompt injection risk, model selection justification, context window efficiency, output validation, token cost implications, prompt file structure quality

## Phase 5 — AC Review and Aggregate

Phase 4 ends when all specialist Task agents have been launched. Phase 5 begins as specialists complete their work and call `kanban review <card>`.

**Pipeline (per specialist — do NOT wait for all specialists before starting any AC reviews):**

1. Monitor the kanban board. As EACH specialist calls `kanban review <card>` (their card appears in the review column), IMMEDIATELY launch that specialist's AC reviewer — do not wait for other specialists to finish.
2. Launch the AC reviewer as a background subagent (model: haiku, skill: ac-reviewer) with the specialist's `.scratchpad/review-<number>-<domain>.md` content as context.
3. After the AC reviewer completes: `kanban done <card> '<one-line summary>' --session <id>`
4. **If `kanban done` fails** (unchecked AC): `kanban redo <card> --session <id>`, re-launch that specialist once with the same prompt. If it fails after one retry (two total attempts), proceed without that specialist's findings and note the gap in the aggregated review body.

**Do NOT proceed to aggregation until ALL specialist cards have reached `kanban done` or have been retried and excluded.**

### Read All Specialist Findings

```bash
# Read each specialist's scratchpad output
# e.g.:
# .scratchpad/review-<number>-swe-backend.md
# .scratchpad/review-<number>-swe-security.md
# etc.
```

### Assemble Aggregated Review Body

The review body must read as if one developer wrote it — no headers, no specialist attribution, no tooling metadata.

```
{If any specialist found blocking or concern-level issues:
Write 2–3 sentences in plain language summarizing the key concerns. No "## Expert Code Review" header.
No "Reviewed by:" line. No "Inline comments: N" metadata. No specialist names. Sounds like a
developer who read the PR.}

{If all specialists returned LGTM: leave the body empty.}
```

Write the aggregated review body to `.scratchpad/review-<number>.md` before posting.

### Write Findings JSON

In addition to the `.md` summary, write `.scratchpad/review-<number>.json` with the structured findings for `prr`:

```json
{
  "body": "<aggregated review body — plain text, no headers, no attribution, or empty string if all LGTM>",
  "comments": [
    {"path": "src/auth/login.go", "line": 42, "severity": "blocking", "body": "Have you considered..."},
    {"path": null, "line": null, "severity": "concern", "body": "Overall finding — no specific location"}
  ]
}
```

Aggregate all specialist FILE/LINE/SEVERITY/COMMENT findings into the `comments` array. Findings with `FILE: (none)` become `{"path": null, "line": null, ...}` entries.

**Comment body rules:**
- Use the specialist's COMMENT text verbatim — do not prepend severity labels (`[blocking]`, `[concern]`) or specialist attribution (`[swe-security]`)
- The comment body must be plain text only: one paragraph, developer voice

## Phase 6 — Post Review

Post a **single unified GitHub review** via `prr`.

### Submit via prr

```bash
prr submit <pr-number> --findings .scratchpad/review-<pr-number>.json
```

`prr` handles all mechanics: loading the findings JSON, fetching the head commit SHA, separating inline vs body-level comments, auto-determining the event from severity fields, and posting the review via the GitHub REST API.

Override the event explicitly if needed:

```bash
prr submit <pr-number> --findings .scratchpad/review-<pr-number>.json --event REQUEST_CHANGES
```

**Note on line numbers:** GitHub's review API requires the line number to be within the diff hunk. If a specialist's line number falls outside the diff, edit the findings JSON to set `path: null` and `line: null` for that comment before submitting so it becomes a body-level observation.

### Verify and Report

Read `inline_count` and `body_count` directly from `prr`'s JSON output — no separate `prc list` call needed.

Report back:
- How many inline comments were posted (`inline_count` from prr output)
- How many findings went into the review body (`body_count` from prr output)
- Which specialists flagged concerns vs. LGTM
- The overall review event (`event` from prr output)

## Critical Rules

**Worktree handoff is one-way:**
- When Phase 1 creates a worktree, the current session STOPS immediately after
- Do NOT continue doing review work in the current session after handing off
- Do NOT wait for the new session to complete

**Never post before all specialists complete:**
- Do NOT submit the GitHub review until every specialist card has reached `kanban done` or been retried and excluded per Phase 5
- Do NOT skip the AC lifecycle to save time

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

**No nits:**
- If a finding is borderline or minor, cut it entirely
- Only include findings worth surfacing to the author
- When in doubt, leave it out

**Preserve specificity:**
- Keep file:line pairs from specialist output intact in the inline comments array
- Never flatten findings into vague body-level summaries when a specific location exists

**Verification:**
- Read `inline_count` and `body_count` directly from `prr`'s JSON output to confirm counts (no separate `prc list` call needed)
- If inline comments are missing from `prr` output, check whether line numbers fell outside diff hunks and repost affected findings in the review body

## Key Principles

**Worktree is the review environment:**
The worktree gives specialists full branch context. Create it first, hand off immediately. The current session's only job is setup and launch — not review work.

**Auto-detection is a starting point, not gospel:**
If the diff has an unusual structure, use judgment to add specialists the heuristics missed. The goal is coverage, not mechanical matching.

**Parallelism is the point:**
All specialists run simultaneously. Sequential delegation defeats the purpose. Launch all Task agents in one message.

**The review body is a summary, not the review:**
Inline comments are where the substance lives. The body — if needed at all — is 2-3 sentences of plain language context. Keep it human.

**One review submission per PR invocation:**
GitHub shows multiple reviews as cluttered history. Aggregate everything into a single POST, even if some specialists found nothing.

**AC review is not optional:**
The lifecycle exists to verify specialist output quality. Do not shortcut it even when specialists look thorough.
