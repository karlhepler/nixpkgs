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
  - Bash(git worktree *)
  - Bash(git branch *)
  - Bash(git rev-parse *)
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
- `Bash(git worktree *)`
- `Bash(git branch *)`
- `Bash(git rev-parse *)`

This skill fetches PR diffs, posts unified GitHub reviews via `prr`, runs kanban operations for specialist cards, verifies inline comments via `prc`, and creates/removes git worktrees to give specialists full repository access. Without these permissions, operations silently fail in `dontAsk` mode.

**If any are missing:** Stop immediately. Do not start work. Surface to the user:
> "Blocked: One or more required permissions are missing from `permissions.allow`. Add `Bash(gh pr *)`, `Bash(gh api *)`, `Bash(kanban *)`, `Bash(prc *)`, `Bash(prr *)`, `Bash(git worktree *)`, `Bash(git branch *)`, and `Bash(git rev-parse *)` before running /review."

## Phase 1 — Fetch PR Context

```bash
# Fetch PR metadata (add --repo owner/repo if cross-repo)
gh pr view <number> --json number,title,author,body,url,baseRefName,headRefName [--repo owner/repo]

# Fetch full diff
gh pr diff <number> [--repo owner/repo]
```

Extract `{owner}/{repo}` for the Phase 5 API URL: use the `--repo` flag value if provided, otherwise parse it from the PR's `url` field (e.g., `https://github.com/owner/repo/pull/123`).

Extract changed file paths from diff header lines matching `+++ b/...`.

Store PR metadata, `{owner}/{repo}`, and diff text in memory — all three are passed to each specialist and used in Phase 5.

### Worktree Setup for Full Repository Context

After fetching PR metadata, determine whether specialists can have full repository access:

**If `--repo` flag was used (cross-repo review):**
- Set `repo_path = null`, `worktree_created = false`
- Specialists will receive the diff only

**If same-repo review:**

First, check whether the PR is from a fork:
```bash
gh pr view <number> --json isCrossRepository --jq .isCrossRepository
```

- If `isCrossRepository` is `true` (fork PR):
  - Set `repo_path = null`, `worktree_created = false`
  - Specialists will receive the diff only — note in each specialist prompt that this is a fork PR and full repository context is unavailable (diff-only review)

- If `isCrossRepository` is `false` (same-repo branch):
  ```bash
  # Get current branch
  git branch --show-current
  ```

  - If current branch == PR's `headRefName`:
    ```bash
    git rev-parse --show-toplevel
    ```
    Set `repo_path` to that output, `worktree_created = false`

  - If current branch != PR's `headRefName`:
    ```bash
    git worktree add $HOME/worktrees/review-pr-<number>/ <headRefName>
    ```
    Set `repo_path = $HOME/worktrees/review-pr-<number>/`, `worktree_created = true`

## Phase 2 — Detect Domains

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

## Phase 3 — Parallel Specialist Delegation

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

**Tone:**
Write findings in a collegial, curious tone. These are teammates, not suspects.
- Frame observations as questions or suggestions before conclusions ("I noticed...", "Have you considered...", "Curious about...")
- Acknowledge trade-offs and context before suggesting alternatives
- Assume the author was deliberate — ask why before calling something wrong
- Flag blocking issues clearly but without condescension
- Frame nitpicks as "up to you" suggestions

**Required Output Format:**
Write your complete findings to `.scratchpad/review-{number}-{domain}.md` using this structure:

## {Domain} Review

**Verdict:** ✅ LGTM | ⚠️ Concerns | 🚨 Blocking Issues

### Findings

FILE: path/to/file.go
LINE: 42
SEVERITY: blocking | concern | nit
COMMENT: [Inline comment text — collegial tone, assume good intent — embed citations inline when referencing standards or library APIs]

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

## Phase 4 — AC Review and Aggregate

Phase 3 ends when all specialist Task agents have been launched. Phase 4 begins as specialists complete their work and call `kanban review <card>`.

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

```markdown
## Expert Code Review

**Reviewed by:** {comma-separated specialist list}
**Inline comments:** {N} comments on specific lines

{For each specialist with ⚠️ or 🚨 verdict: one short paragraph summarizing their domain findings}

{If all ✅ LGTM: "All specialists gave this a clean bill of health."}

---
*Specialist team review via Claude Code*
```

Keep the body brief. Inline comments carry the detail. One paragraph per specialist with concerns; LGTM specialists need only a mention in "Reviewed by".

Write the full aggregated review body to `.scratchpad/review-<number>.md` before posting.

### Write Findings JSON

In addition to the `.md` summary, write `.scratchpad/review-<number>.json` with the structured findings for `prr`:

```json
{
  "body": "<full aggregated review body text from above>",
  "comments": [
    {"path": "src/auth/login.go", "line": 42, "severity": "blocking", "body": "Have you considered..."},
    {"path": null, "line": null, "severity": "concern", "body": "Overall finding — no specific location"}
  ]
}
```

Aggregate all specialist FILE/LINE/SEVERITY/COMMENT findings into the `comments` array. Findings with `FILE: (none)` become `{"path": null, "line": null, ...}` entries. Build the `body` from the aggregated review body text assembled above.

## Phase 5 — Post Review

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

### Worktree Cleanup

If `worktree_created` is true:
```bash
git worktree remove $HOME/worktrees/review-pr-<number>/ --force
```

Run this after the review is posted. Do not skip cleanup — stale worktrees accumulate and consume disk space.

## Critical Rules

**Never post before all specialists complete:**
- Do NOT submit the GitHub review until every specialist card has reached `kanban done` or been retried and excluded per Phase 4
- Do NOT skip the AC lifecycle to save time

**Single unified review:**
- All findings go into ONE GitHub review submission
- Never submit multiple separate reviews or `gh pr comment` calls
- Inline placement (file:line) preferred; body-level for findings without a specific location

**Preserve specificity:**
- Never flatten findings into vague summaries
- Keep file:line pairs from specialist output intact in the inline comments array
- If a specialist gives LGTM with no findings, acknowledge them in the "Reviewed by" header — do not omit them

**Tone discipline:**
- All specialist delegation prompts must include the tone block (curious, collegial, assume good intent)
- The aggregated review body inherits that tone

**Verification:**
- Read `inline_count` and `body_count` directly from `prr`'s JSON output to confirm counts (no separate `prc list` call needed)
- If inline comments are missing from `prr` output, check whether line numbers fell outside diff hunks and repost affected findings in the review body

## Key Principles

**Auto-detection is a starting point, not gospel:**
If the diff has an unusual structure, use judgment to add specialists the heuristics missed. The goal is coverage, not mechanical matching.

**Parallelism is the point:**
All specialists run simultaneously. Sequential delegation defeats the purpose. Launch all Task agents in one message.

**The review body is a summary, not the review:**
Inline comments are where the substance lives. Keep the body scannable — one short paragraph per specialist with concerns.

**One review submission per PR invocation:**
GitHub shows multiple reviews as cluttered history. Aggregate everything into a single POST, even if some specialists found nothing.

**AC review is not optional:**
The lifecycle exists to verify specialist output quality. Do not shortcut it even when specialists look thorough.
