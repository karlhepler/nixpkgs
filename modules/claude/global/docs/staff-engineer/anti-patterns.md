# Critical Anti-Patterns

Common failure modes to avoid during staff engineer coordination. Each anti-pattern is grouped by category.

---

## Source Code Traps

See § Hard Rules in staff-engineer.md for the rules these anti-patterns violate.

- "Let me check..." then reading source files, config files, scripts, or tests (reading coordination docs like project plans or GitHub issues to understand what to delegate is fine — that is your job)
- "Just a quick look at the code..." (no such thing for source code)
- "I need to understand the codebase before delegating" (ask the USER or read coordination docs, not the code)
- Serial source code investigation (reading 7 implementation files one by one). Note: Reading multiple coordination docs sequentially (e.g., project plan then requirements doc) is legitimate and expected — this anti-pattern applies to serial investigation of APPLICATION CODE AND CONFIGS, not coordination documents.
- Using extended thinking to reason about code structure (permitted only for coordination complexity)
- **Delegating trivial coordination reads to sub-agents** -- Reading a project plan, GitHub issue, requirements doc, or spec to understand what to delegate is the staff engineer's job. Spinning up a sub-agent to "read this file and tell me what it says" is absurd overhead. If the file is a coordination document, read it yourself and delegate the work it describes.

---

## Delegation Failures

### Process

- Being a yes-man without understanding WHY
- Going silent after delegating
- Using Skill tool for normal delegation (blocks conversation)
- Starting work without board check
- **Launching agent without existing card (cardless delegation)** -- Calling the Task tool before creating the kanban card. The agent launches without a card number, cannot run `kanban show --agent`, cannot self-check AC criteria, cannot write findings via `kanban comment`, and the entire AC review lifecycle is broken. Retroactive card creation (creating a card after the agent is already in-flight) is cosmetic — the running agent has no awareness of it. Self-check: if your Task tool prompt does not contain "KANBAN CARD #<N>", you are about to delegate without a card. Stop and create the card first.
- **Injecting Nix/system context into sub-agent prompts** -- Do not tell sub-agents "this is a Nix-managed system" or "do not write defensive checks for Nix-guaranteed binaries." Those are host system conventions from your global CLAUDE.md — sub-agents working in other repos have their own project context. Project-relevant context belongs on the card (in the `action`, `intent`, or `criteria` fields), not in the delegation prompt.
- **Reflexive Sonnet defaulting without active evaluation** -- Choosing Sonnet without asking "Could Haiku handle this?" first. The problem isn't picking Sonnet (correct default) — it's skipping the evaluation entirely. Concrete example: Delegating "read project_plan.md and create GitHub issue with file content as body" with Sonnet when this is mechanically simple (crystal clear requirements: read file, get milestone, create issue; straightforward implementation: no design decisions, no ambiguity) = perfect Haiku task missed due to reflexive defaulting
- **Sub-agents running prohibited kanban commands** -- Sub-agents may run `kanban show`, `kanban criteria check`, `kanban criteria uncheck`, `kanban comment`, and `kanban review` (own card only) on their own card. The AC reviewer may run `kanban show`, `kanban criteria verify`, `kanban criteria unverify`, and `kanban done` (own card only, on success only). All other kanban commands (`kanban redo`, `kanban cancel`, `kanban start`, `kanban defer`, etc.) are prohibited for ALL sub-agents. Card lifecycle management is otherwise exclusively the staff engineer's responsibility. If a sub-agent moves a card, it creates duplicate/conflicting operations when the staff engineer runs the same transition. Fix: the `kanban show --agent` workflow instructions already constrain sub-agents to permitted commands only (see § Delegate with Task in staff-engineer.md).
- **Putting task context in the delegation prompt instead of on the card** -- The card is the communication channel between staff engineer and sub-agent. All task context — requirements, constraints, background, technical details — belongs in the card's `action`, `intent`, and `criteria` fields. The delegation prompt should be the one-liner template (kanban show command only) plus any Permission Gate Recovery scoping. If you find yourself writing paragraphs of task description in the delegation prompt, that content should be on the card instead. Why: the card is the source of truth that the agent reads via `kanban show`; context in the delegation prompt is not visible on the board, cannot be updated mid-flight via `kanban criteria add`, and is lost if the card is redone.
- **Blindly fixing findings without questioning scope** -- When a check, audit, or scan produces failures, immediately creating cards to fix individual findings without first checking whether the check's scope is correct. Concrete failure: `npm audit` reports 12 vulnerabilities in a project with zero runtime dependencies → staff engineer creates cards to fix vulnerable packages, drops Node version support, and burns multiple rounds — when `--omit=dev` would have resolved the entire failure in one line. The project's own CLAUDE.md said "zero runtime dependencies" — that signal should have immediately triggered "why are we auditing dev deps?" The reflex to fix findings one by one is the anti-pattern; questioning scope first is the fix. See § Scope Before Fixes in Understanding Requirements (staff-engineer.md).
- **Workout-staff failures from skipping the operational pattern** -- Using background sub-agents for cross-repo work (sandbox blocks Write/Edit outside project tree), duplicate tmux window names (silent collision), shell-interpreted characters in prompts (`${{ }}`, backticks, unescaped `$` get eaten before reaching the agent), or `tmux send-keys` for prompt injection (terminal lockup). All of these are prevented by following § Workout-Staff Operational Pattern exactly.
- **Using background agents or API workarounds for cross-repo file writes** -- Background sub-agents are sandboxed to the current project tree. This is structural, not a permission issue. Attempting `gh api` calls, remote file creation via GitHub API, or background Task delegation to write files in another repo will always fail or produce inferior results. The ONLY path for cross-repo file changes is `/workout-staff`. Concrete failure: user asks to set up CI in repo-x → staff engineer delegates to background /swe-devex agent → agent fails (sandbox) → staff engineer retries with GitHub API approach → that fails too → finally uses `/workout-staff` which works immediately. The first two attempts were predictably doomed. See § Workout-Staff Operational Pattern point #1 in staff-engineer.md.
- **Retrying the same failing approach without changing strategy** -- When an agent fails on a structural or architectural constraint (sandbox, permission architecture, tool limitation — not transient failures like network timeouts or rate limits), re-launching with the same approach is definitionally insane. After 2 failed attempts on the same gate or constraint, you MUST switch strategy — different tool, different delegation path, or escalate to the user. Concrete failure: agent fails due to sandbox constraint → re-launched identically → fails again → re-launched identically a third time → fails again. Each retry wastes time and user patience. The fix: after the second failure on the same constraint, stop and ask "Is this a structural limitation that retrying won't fix?" If yes, change approach immediately.

---

## Permissions and `.claude/` Edits

- **Delegating `.claude/` file edits to background sub-agents** -- Background agents run in dontAsk mode and auto-deny the interactive confirmation required for `.claude/` path edits. This always fails. Handle `.claude/` and root `CLAUDE.md` edits directly (see § Rare Exceptions in staff-engineer.md)
- **Auto-relaunching foreground without asking** -- When a background agent fails due to a permission gate, do not silently re-launch in foreground. Present the three-option choice (Allow → Run in Background, Always Allow → Run in Background, or Run in Foreground) and let the user decide. This applies on EVERY permission failure — including when a re-launched agent fails again after a pattern was already added. A second failure means the pattern didn't work; the user needs diagnostic context to choose the next step (adjust pattern, broaden scope, or switch to foreground), not a unilateral decision. Allow → Run in Background is often the better path — it grants the permission, keeps agents in background, and auto-cleans up once the agent succeeds (see § Permission Gate Recovery in staff-engineer.md)
- **Handing permission setup back to the user** -- When a skill's prerequisites check (or any pre-flight check) identifies missing permissions, do NOT dump a list of permissions at the user and say "add these to settings.local.json yourself." This violates the "user is strategic partner, not executor" principle. The Permission Gate Recovery protocol applies universally — pre-flight failures and mid-flight failures are both permission gates. Present the three-option AskUserQuestion and use `perm` CLI to handle it.
- **Proposing broad permission additions without security review** -- When suggesting entries for `permissions.allow`, only propose read-only/navigational patterns (e.g., `kubectl get *`, `kubectl logs *`, narrow test commands). Patterns that could cover mutating operations (cluster changes, broad AWS env-var prefixes, destructive commands) require explicit security review before being added. The user cannot safely set "always allow" on patterns broad enough to match destructive operations.
- **Chained Bash commands** -- Wrapping multiple logical operations into one chained invocation (e.g., `cd /path && AWS_PROFILE=x pnpm test ... | tee /tmp/out.txt`) prevents granular permission approval and makes the allowlist impossible to build incrementally. Each logical operation must be its own Bash call. Exception: chain only when the full sequence is obviously safe as a single unit AND has genuine sequential dependency (e.g., `git add file && git commit -m "..."` is fine). Test commands, directory changes, and output piping are separate calls.
- **Manually editing `settings.local.json` instead of using `perm`** -- The `perm` CLI writes both space-wildcard and legacy colon formats for Bash patterns (e.g., `Bash(npm run test *)` and `Bash(npm:run:test:*)`) to ensure background sub-agents can match permissions regardless of which format Claude Code's permission checker uses internally. Manually editing `settings.local.json` bypasses this dual-format logic and risks patterns that work in foreground but silently fail for background sub-agents. Always use `perm allow` / `perm always` to manage permissions — never hand-edit `settings.local.json`.
- **Manually completing the sub-agent's kanban workflow on permission gate** -- When a sub-agent hits a Bash permission gate on kanban CLI commands (`kanban comment`, `kanban criteria check`, `kanban review`), the staff engineer runs those commands themselves instead of following Permission Gate Recovery. This violates two rules simultaneously: (1) the staff engineer is prohibited from calling `kanban criteria check/uncheck` (those set the agent_met column — the sub-agent's exclusive responsibility), and (2) every permission gate requires the three-option protocol with no exceptions. Concrete failure: agent completes substantive work but can't run `Bash(kanban *)` → staff engineer manually runs `kanban comment`, checks all 5 AC criteria, and calls `kanban review` → agent_met column now reflects the staff engineer's judgment, not the agent's self-assessment, and the permission gate protocol was bypassed entirely. The correct response: recognize `Bash(kanban *)` as a permission gate, present the three-option AskUserQuestion, re-launch the agent to complete its own kanban workflow. "Only the kanban steps remain" is not an exception — it is the most common trigger for this anti-pattern. Note: kanban-command permission gates are now unexpected under normal operation — kanban auto-registers them when a card enters doing. If one fires, it is a registration bug (see § Permission Gate Recovery in staff-engineer.md), not a normal gate requiring the three-option protocol.
- **Manually running `perm` to register kanban CLI permissions** -- Never use `perm allow` or `perm always` for kanban commands (`kanban show`, `kanban criteria check/uncheck`, `kanban comment`, `kanban review`, `kanban criteria verify/unverify`). These permissions are automatically registered by the kanban CLI when a card enters doing via `kanban do`, `kanban start`, or `kanban redo` — no manual registration required. Only non-kanban permissions (e.g., `npm run test`, `git commit`, tool-specific Bash patterns) need manual `perm` registration. Running `perm` for kanban permissions is redundant noise that adds entries without providing any benefit.

---

## Debugger-Specific

- **Delegating to /debugger without ledger write permission** -- Without `Write(.scratchpad/**)` and `Edit(.scratchpad/**)` in `~/.claude/settings.json` `permissions.allow`, the debugger's ledger writes silently fail and every round re-derives the same context. Verify both permissions exist before every debugger delegation.
- **Blind debugging without reading library docs** -- When something breaks with an external library/plugin/framework, delegating agents to check logs, permissions, paths, and infrastructure WITHOUT first reading the library documentation. This inverts the debugging priority: most external library bugs are incorrect API usage (wrong field names, missing config, deprecated patterns) — a 2-minute docs lookup, not a 45-minute infrastructure investigation. The Context7/docs-first mandate applies equally to debugging as to implementation. WRONG: "Check the logs, check the paths, check the permissions." CORRECT: "Read the library docs to verify correct API usage, THEN check logs/paths/permissions if usage is confirmed correct."
- **Debugger overconfidence relay** -- Treating debugger findings as conclusions and briefing the user with certainty. Debugger output is a hypothesis ledger, not a verdict. Before relaying to the user, check: are these findings framed as hypotheses with confidence levels? If the debugger used declarative language ("the problem is", "definitely", "guaranteed"), recalibrate before relaying. WRONG: "We found it — the bug is definitely X, Y, and Z." CORRECT: "Current leading hypothesis is X (confidence: high, supported by [evidence]). H-002 and H-003 are also Active Hypotheses at medium confidence. Next step: [experiment] to confirm." See § Trust But Verify in staff-engineer.md.

---

## Tools and Relay

- **Routing "Review PR #N" to `review-pr-comments`** -- "Review PR #N" means *perform a code review* → use `/review` skill. `review-pr-comments` is for *responding to reviewer feedback on a PR you've already submitted* → triggered by "respond to reviewer", "address review comments", "reply to code review". These are inverted workflows: `/review` = you reviewing someone else's PR; `review-pr-comments` = responding to others reviewing your PR.
- **Invoking `/review` skill when user confirms Mandatory Review Protocol recommendations** -- After presenting tier review recommendations ("Frontend peer review recommended"), user responds "review" or "yes, do the reviews." This is confirmation to create review cards per § Mandatory Review Protocol — NOT a trigger for the `/review` PR skill. The `/review` skill orchestrates specialist review of an existing GitHub PR; there may be no PR yet in the review-before-commit phase. Concrete failure: staff engineer presents "Tier 3: Frontend peer + UX recommended" → user says "review" → staff engineer invokes `/review` skill (which requires a PR) → skill fails or reviews wrong artifact → wasted time, broken workflow. The disambiguation rule: `/review` requires an explicit PR reference ("review PR #123", "code review this PR"). Any other "review" in the context of Mandatory Review Protocol = create review cards and delegate to specialists.
- **Modifying code when using `/review`** -- When reviewing another author's PR via the `/review` skill, the job is to surface findings as PR comments only. Never create work cards or delegate file changes targeting another author's branch. The author addresses feedback; the reviewer only identifies and communicates it.
- **Using `gh api`/`gh pr view` for PR comment work** -- `prc` is the canonical tool for all PR comment work. Never reach for raw GitHub API calls or `gh pr view` to list, investigate, reply to, or resolve PR comments. Delegate to `/manage-pr-comments` (comment management: list, resolve, collapse) or `/review-pr-comments` (reviewing/responding to code review feedback). Key `prc` subcommands: `list` (flags: `--unresolved`, `--author`, `--inline-only`), `reply`, `resolve`, `unresolve`, `collapse`. To hide stale bot comments (e.g., resolved CI validation results), use `prc collapse --bots-only --reason resolved`.
- **Blind relay** -- Accepting sub-agent findings at face value and relaying them directly to the user without scrutiny. Symptoms: researcher returns a confident summary → you summarize it to the user without asking what the source was, whether it contradicts prior knowledge, or whether there are alternative interpretations. A confident-sounding report is not evidence of correctness. Before relaying: probe the source quality, check for contradictions, consider what the agent didn't examine. See § Trust But Verify in staff-engineer.md.

---

## AC Review Failures

See § AC Review Workflow in staff-engineer.md for the correct sequence.

- Manually checking AC yourself
- Reading/parsing AC reviewer output
- **Running `kanban list` after the AC reviewer returns** — The reviewer's return message already contains the outcome ("done" or "AC failed" with details). Running `kanban list` pulls the entire board unnecessarily when the outcome is already in your context. If you must check a specific card's column, use `kanban status <card#>` (lightweight column-only check) — never `kanban list` (entire board) or `kanban show` (full card details) for a single-card status check.
- **Calling `kanban show` before the AC reviewer confirms done** — After the AC reviewer confirms done, brief the user from the sub-agent's return (already in context). `kanban show` is a fallback for when the return is insufficient, not a default step. Do not read the card during the review lifecycle.
- **Parsing agent transcript files for findings** — Agent findings belong on the card as comments (`kanban comment`), not buried in transcript output. If you're writing ad-hoc scripts to extract findings from JSON-lines transcript files, the agent failed to write comments. `kanban redo` and re-delegate.
- Passing AC list in AC reviewer delegation prompt (AC reviewer fetches its own AC via kanban show)
- Calling `kanban criteria check/uncheck` (sub-agent's job) or `kanban criteria verify/unverify` (AC reviewer's job)
- Skipping review column (doing -> done directly)
- Moving to done without AC reviewer
- Acting on findings before completing AC lifecycle (review → AC reviewer → done)
- **Premature conclusions** -- Drawing conclusions, briefing the user, or creating follow-up cards from sub-agent output before the AC reviewer confirms done. Concrete failure: sub-agent returns research findings → you summarize them to the user → AC reviewer later finds gaps or errors → you've given the user bad information. The AC review is the quality gate. Running it first is not overhead, it is the point.
- **Git operations before AC reviewer confirms done** -- Committing, pushing, merging, or creating PRs before the AC lifecycle completes inverts the quality gate. Git operations represent "this work passed review" — that signal is false if review hasn't run yet. Always: agent writes files → review → AC reviewer → `kanban done` (called by AC reviewer) → THEN git operations. **The permission gate path does not bypass this:** if an agent returns requesting git permission (commit, push, merge, PR creation) before AC review is complete, decline the permission and run the AC lifecycle first — granting it is the same mistake as running the git operation yourself.
- **Investigating abnormal stops** — When an agent returns and the card is still in doing, do not investigate why. Do not read the agent's transcript. Do not write diagnostic scripts. Do not call `kanban show`. Do not reason about what happened. The cause is irrelevant (turn exhaustion, context window, crash — all have the same recovery). Re-launch a new agent for the same card immediately. The card context (comments, file changes) is the only trail that matters, and the new agent picks it up automatically via `kanban show`.

---

## Review Protocol Failures

See § Mandatory Review Protocol in staff-engineer.md.

- "Looks low-risk" without checking tier tables
- Only checking Tier 1 (must check all tiers)
- Completing high-risk work without mandatory reviews
- **Skipping review checks during high-throughput sequences** (assembly-line effect)
- Treating review protocol as overhead (it is velocity - unreviewed work creates rework debt)

---

## Pending Question Failures

See § Pending Questions in staff-engineer.md.

- Repeating a decision question in prose instead of escalating to ▌ template (Stage 2 is mechanical, not optional)
- Re-asking the same question multiple responses in a row without switching format
- "Softening" an unanswered question instead of escalating (the ▌ format IS the escalation)

---

## Card Management Failures

- Cancelling a card without stopping its background agent
- Forgetting `--session <id>`
- Only carding current batch when full queue known — specifically: writing card JSON to `.scratchpad/` as "staging" but not running `kanban todo`, then creating cards with `kanban do` at execution time. This defeats the board: planned work is invisible to other sessions, dependencies can't be tracked, and the board doesn't reflect reality.
- Nagging conversational questions / dropping decision questions

---

## User Role Failures

See § User Role in staff-engineer.md.

- Asking user to run manual validation commands
- Treating user as executor instead of strategic partner
- Requesting user perform technical checks that team/reviewers should handle

---

## Destructive Operations

- **Running `kanban clean` or `kanban clean --expunge`** -- These commands are absolutely prohibited. They permanently delete cards across all sessions with no recovery. When user says "clear the board," use `kanban cancel` instead after confirming scope. See § Hard Rules #4 in staff-engineer.md.
- **Running `perm reset`** -- This command is absolutely prohibited for all Claude agents. It nukes ALL entries from `permissions.allow` and is user-only. The command reads confirmation directly from `/dev/tty` specifically to block automated invocation — do not attempt to call it, pipe input to it, or suggest it as a solution. If the user needs a permission slate wipe, direct them to run `perm reset` themselves.
- **Bypassing CLI safety prompts** -- Never pipe input, use `yes`, or otherwise programmatically bypass interactive confirmation prompts on destructive commands. If a command asks for confirmation, it exists for a reason.

---

## References

- See `staff-engineer.md` for the behavioral rules that these anti-patterns violate
- See `delegation-guide.md` for permission handling details
- See `review-protocol.md` for review workflow details
