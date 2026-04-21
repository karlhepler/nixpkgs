# Delegation Guide

Detailed guidance for Staff Engineer delegation patterns, permission handling, and edge cases.

---

## Permission Gate Recovery

Background sub-agents run in `dontAsk` mode. When an agent hits an interactive permission prompt (Edit, Write, Bash confirmation, destructive command), it auto-denies and returns a failure. This is not a bug — it is a structural constraint.

**This protocol also applies to skill pre-flight checks.** When a skill (e.g., `/review`) runs a prerequisites check and identifies missing permissions before any work starts, that is a permission gate — not an invitation to hand the fix back to the user. Treat it identically: present the three-option AskUserQuestion, use `perm` CLI based on the user's choice, then re-launch the skill.

**Perm session identity:** Use the perm session UUID printed at session start (`🔑 Your perm session is: <uuid>`) for all `perm --session` commands. This is distinct from the kanban session name. Stale temporary permissions from crashed/forgotten sessions are automatically cleaned up at session start.

**Git operation permission gates require AC review first.** If an agent returns requesting permission for a git operation — `git commit`, `git push`, `git merge`, or `gh pr create` — and the card has NOT yet completed the AC lifecycle (`kanban review` → AC reviewer → `kanban done`), do NOT proceed with the normal recovery path. Do not grant the permission. Instead: move the card to review, run the AC lifecycle, and only after `kanban done` succeeds, proceed with git operations. The permission gate recovery protocol is for unblocking legitimate work — not for bypassing the quality gate. An agent requesting commit/push is asking to signal "work is complete" before it has been verified. After `kanban done` succeeds, run the git operations directly (see § Rare Exceptions in the output style) rather than re-launching the agent — the work is done and verified; only the git operation remains.

### Detection, Three-Option Choice, and Execution

**When a background agent returns with a permission failure:**

1. **Detect** — Identify a permission gate, not a regular implementation error. Signals: agent output says it needed a confirmation, references a tool it couldn't invoke, or states it was blocked from executing an operation due to permissions. Identify the specific permission pattern needed (tool name + pattern, e.g., `"Bash(npm run lint)"`).
2. **Present choice** — Use AskUserQuestion with exactly three options. The question text must include a concise "Why" line explaining what the agent is trying to do and why it needs this permission. Flag potentially dangerous or mutating operations with ⚠️ — destructive shell commands (e.g., `terraform apply`, `rm -rf`, `git push --force`, database mutations) or permission patterns broad enough to cover destructive operations (e.g., `Edit(src/**)`).
   - **"Allow → Run in Background"** — Run `perm --session <your-session-id> allow "<pattern>"` to add the permission to `.claude/settings.local.json` tracked as temporary for your session, then re-launch the agent in background. Once the agent returns successfully, run `perm --session <your-session-id> cleanup` to remove your session's temporary permissions.
   - **"Always Allow → Run in Background"** — Run `perm always "<pattern>"` to add the permission permanently, then re-launch the agent in background. No cleanup after the agent completes.
   - **"Run in Foreground"** — Before re-launching, run `perm --session <your-session-id> cleanup` to remove all temporary permissions for your session. Then re-launch using the Task tool with `run_in_background: false`. Same prompt, same card, same agent type. Claude Code surfaces the permission prompt to the user natively.
3. **Execute the chosen path** — No other options exist. If the user wants none of these, that conversation is separate from this protocol.
4. **Resume** — After the chosen path completes, continue normal AC review lifecycle for remaining work.

**Tracking:** `perm` handles session-aware tracking. Run `perm list` to see current state with session IDs if you need to inspect what's active.

### Sequential Permission Gates

If the re-launched agent hits a permission gate — whether a **different** gate or the **same** gate again — restart from step 1. Each gate gets its own AskUserQuestion. Never bypass the three-option choice, even on repeated failures. If you anticipate multiple permissions will be needed and want to reduce trips through the recovery loop, you can proactively ask the user upfront: "I expect the agent may need these permissions — should I add them now?" Then use a single batched `perm` call with all patterns instead of waiting for each gate individually.

**Same gate fires again (pattern mismatch):** When the agent fails on the same permission after a pattern was already added, the pattern likely doesn't match the actual command the agent tried to run. Include diagnostic context in the AskUserQuestion: what pattern was added, that it didn't resolve the gate, and a hypothesis about why (e.g., "Pattern `Bash(auth0 *)` was added but the agent ran `bash -c 'auth0 ...'` — the pattern may need to be broader or differently structured"). This gives the user the information to decide: try a different pattern, escalate to Always Allow with a broader pattern, or switch to foreground where they can see the exact command.

Temporary permissions stay in place while the loop continues — cleanup happens once the agent returns (success or failure). On success, proceed to AC review. On implementation failure, run `perm --session <your-session-id> cleanup`, then `kanban redo` and re-delegate. After a few Allow or Always Allow selections, the agent typically has everything it needs and completes successfully. If the user selects "Run in Foreground" at any point mid-loop, run `perm --session <your-session-id> cleanup` before re-launching in foreground.

### Example: Three-Option AskUserQuestion

Sub-agent (card #15, /swe-backend) returns with a permission failure on `Bash(npm run lint)`. Staff engineer presents:

```
AskUserQuestion({
  questions: [{
    question: "Card #15's /swe-backend agent needs permission for Bash(npm run lint).\n\nWhy: Running lint check to verify code quality before completing the task.\n\nHow should we proceed?",
    header: "Permission",
    options: [
      {
        label: "Allow → Run in Background",
        description: "Add Bash(npm run lint) to .claude/settings.local.json temporarily and re-launch agent in background. Permission auto-removed after agent completes."
      },
      {
        label: "Always Allow → Run in Background",
        description: "Add Bash(npm run lint) to .claude/settings.local.json permanently and re-launch agent in background"
      },
      {
        label: "Run in Foreground",
        description: "Re-launch agent in foreground where Claude Code surfaces permissions natively"
      }
    ],
    multiSelect: false
  }]
})
```

If user selects **"Allow → Run in Background"**: run `perm --session <your-session-id> allow "Bash(npm run lint)"`, then re-launch the same agent in background with a scoped authorization constraint (see § Scoped Authorization below). After the agent returns successfully, run `perm --session <your-session-id> cleanup`. If you know multiple permissions will be needed upfront, batch them in a single call: `perm --session <your-session-id> allow "Bash(npm run lint)" "Read(src/**)"` — this is more efficient than running `perm` once per pattern. If user selects **"Always Allow → Run in Background"**: run `perm always "Bash(npm run lint)"`, then re-launch with scoped authorization — no cleanup after completion. If user selects **"Run in Foreground"**: run `perm --session <your-session-id> cleanup` first, then re-launch with `run_in_background: false`.

### Scoped Authorization

When re-launching after an Allow or Always Allow, the delegation prompt MUST include a scoped authorization constraint. The agent is not granted carte blanche — it is authorized to use the permitted tool only for the specific purpose that triggered the gate. Derive the scope from the "Why" line used in the AskUserQuestion. The constraint goes in the delegation prompt verbatim:

```
SCOPED AUTHORIZATION: You have been granted permission for Bash(auth0 ...) ONLY for reading Auth0 logs and inspecting user profiles. If you need to use this tool for any other purpose, you MUST stop and return with a description of what you need and why — do not proceed.
```

Adjust the tool pattern and purpose to match the actual gate. If multiple permissions have been granted across sequential gates, include one SCOPED AUTHORIZATION line per permission.

### Permission Pattern Format

When writing patterns via `perm`, you are writing to `settings.local.json` — a `settings.json` context. These patterns use **space-wildcard** syntax. Source: [Claude Code permissions docs](https://code.claude.com/docs/en/permissions).

- `Bash(npm run lint)` — exact command match
- `Bash(npm run test *)` — prefix match (any args after `test`)
- `Bash(git pull *)` — git pull with any arguments
- `Bash(git *)` — any git command
- `Read(src/auth/**)` — files in auth directory

**Word boundary:** A space before `*` enforces a word boundary. `Bash(git *)` matches `git status` but NOT `gitk`. `Bash(ls *)` matches `ls -la` but NOT `lsof`. Use this to avoid accidentally covering more commands than intended.

**`perm` handles format compatibility automatically.** When you call `perm` with a space-wildcard pattern (e.g., `Bash(npm run test *)`), it writes both the space-wildcard format and the legacy colon format (e.g., `Bash(npm:run:test:*)`) to `settings.local.json`. This ensures background sub-agents can match the permission regardless of which format Claude Code's permission checker uses internally. Always use space-wildcard format in your `perm` calls — `perm` handles the rest.

### Expanded Scope Requests

If the re-launched agent returns saying it needs to use an already-permitted tool for a broader or different purpose, treat it as a new permission gate. Present a fresh AskUserQuestion with the expanded "Why" context — same three options, same protocol. The agent does not inherit permission to use the tool for purposes beyond what was originally scoped.

### Cleanup After Allow Path

Run `perm --session <your-session-id> cleanup`. This removes only your session's temporary permissions from `settings.local.json`, leaving permanent (Always Allow) permissions and other sessions' claims intact.

### Re-launch vs. Redo

- Permission gate failure → Present three-option choice (Allow → Run in Background, Always Allow → Run in Background, or Run in Foreground), execute chosen path
- Implementation error → `kanban redo` and re-delegate background

Do not move the card to done or cancel it. The card stays in `doing` while the chosen path executes. Resume normal AC review lifecycle after the agent succeeds.

### Permission Pre-Approval Patterns (Quick Reference)

To reduce permission gates through proactive pre-approval, identify the full set of tools an agent will need before delegating and batch-approve them upfront. This is especially useful for agents running known workflows:

- **Linting/testing agents:** `perm --session <id> allow "Bash(npm run lint)" "Bash(npm run test *)"` before delegating
- **Git-workflow agents:** Defer until after `kanban done` (see git gate rule above) — do not pre-approve git operations
- **Infrastructure agents:** Identify read-only vs. mutating ops; pre-approve only read-only; flag mutating ops for per-gate decisions

**Local vs. committed settings:** If a project's committed `.claude/settings.json` has stricter rules that override global settings, write any permission overrides to `.claude/settings.local.json` (gitignored, machine-local) rather than modifying `.claude/settings.json` (committed, shared with team). This keeps local customizations separate from team-wide policy.

---

## References

- See [staff-engineer.md](../../output-styles/staff-engineer.md) § Permission Gate Recovery (authoritative)
- See [staff-engineer.md](../../output-styles/staff-engineer.md) § Model Selection (authoritative)

---

## Conflict Analysis Examples

### Safe Parallel Work

**Example 1: Frontend + Backend**
- Frontend: Styling changes in src/components/
- Backend: API endpoint in src/api/
- Result: Different files, no conflicts → Parallel

**Example 2: Features in Different Modules**
- Feature A: Dark mode toggle (theme system)
- Feature B: Password reset (auth system)
- Result: Different domains, no overlap → Parallel

**Example 3: Research + Implementation**
- Research: Investigate caching strategies
- Implementation: Build POC of feature X
- Result: No file conflicts → Parallel

### Conflicting Work (Sequential)

**Example 1: Same File**
- Agent A: Adding validation to src/auth/login.ts
- Agent B: Refactoring src/auth/login.ts
- Result: Both editing same file → Sequential

**Example 2: Interdependent Features**
- Backend: Change API contract (add required field)
- Frontend: Consume API
- Result: Frontend depends on backend change → Sequential

**Example 3: Shared Configuration**
- Agent A: Add environment variable to .env
- Agent B: Update environment variable in .env
- Result: Same config file → Sequential

### Conflict Analysis Decision Tree

```
Check board for active work
       ↓
Do agents touch same files? → YES → Sequential (or merge into one agent's work)
       ↓
      NO
       ↓
Is one's output needed by other? → YES → Sequential
       ↓
      NO
       ↓
Shared resources (DB, config)? → YES → Sequential or coordinate carefully
       ↓
      NO
       ↓
Safe to parallelize
```

---

## Edge Cases and Troubleshooting

### Agent Stuck in Blocked

**Symptom:** Agent moved to review but didn't document what they need

**Solution:**
1. Check the agent's Task return value for a description of what it needs
2. If no clear request → Re-launch the agent and ask: "What permission do you need?"
3. Agent clarifies → Execute → Resume

### Permission Requested But Unsafe

**Symptom:** Agent requests destructive operation you didn't anticipate

**Example:** Agent asks for `git push --force` or `rm -rf node_modules`

**Solution:**
1. Question the need: Why is this necessary?
2. Check if safer alternative exists
3. If truly needed → Execute with caution
4. If not needed → Resume agent with alternative approach

### Multiple Agents Hit Same Permission Gate

**Symptom:** Two agents both blocked on same operation (e.g., npm install same package)

**Solution:**
1. Execute operation once
2. Resume BOTH agents in parallel with confirmation
3. Note: This is why checking review queue before new work matters

### Agent Completed Work But No Review Needed

**Symptom:** Work complete, agent moved to review, but not in mandatory review table

**Solution:**
1. Verify work meets requirements
2. Check if ANY quality concerns (even if not in table)
3. If good → Move to done immediately
4. If concerns → Request changes or create review ticket

### Review Conflicts (Reviewers Disagree)

**Symptom:** Infrastructure peer approves, Security requires changes

**Solution:**
1. Security concerns override peer approval
2. Address security feedback first
3. May need second review round from infra peer
4. Move to done only when ALL reviewers approve

---

## Minimal Delegation Template

The card's action, intent, and AC carry the task. The delegation prompt is boilerplate — do not duplicate card content here.

```
KANBAN CARD #<N> | Session: <session-id>

Do the work described on the card. After completing each acceptance criterion, run: `kanban criteria check <N> <n> --session <session-id>`

Do NOT run any kanban commands except `kanban criteria check/uncheck` for card #<N>. Card lifecycle beyond criteria checking is handled by the SubagentStop hook.

If a tool use is denied, STOP and report which command was denied.
```

For re-launches after redo: state which criteria remain unchecked and why the previous attempt fell short — do not repeat card content.

---

## References

- See `review-protocol.md` for detailed review workflows
- See `parallel-patterns.md` for parallel delegation examples
- See [`staff-engineer.md`](../../output-styles/staff-engineer.md) for core behavior and protocols
