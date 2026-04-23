---
name: claude-improvement-implementer
description: Processes pending claude-improvement notes from Notes MCP and applies fixes to this repo with full staff-engineer review discipline. Invoke as `/claude-improvement-implementer` inside a dedicated tmux session running Claude Code from ~/.config/nixpkgs. Self-schedules via session-scoped CronCreate to run every 15 minutes — executes ONE cycle per firing.
---

# Claude Improvement Implementer

## Usage

Run inside a dedicated tmux session with Claude Code open in `~/.config/nixpkgs`:

```
/claude-improvement-implementer
```

On first invocation, the skill installs a session-scoped cron (in-memory, 15-min cadence) that re-fires the skill automatically. Each firing runs ONE cycle. The cron lives only in the current Claude session — when Claude exits, the cron dies and the user must re-invoke the skill once to re-arm.

---

## Cycle Protocol

### Step 1 — Scope Gate (MANDATORY FIRST ACTION)

Run this check before doing anything else:

```bash
test -f "$(pwd)/flake.nix" && test -f "$(pwd)/modules/claude/default.nix"
```

This sentinel-file check is more robust than comparing `$HOME` (which may be unset or resolve via symlinks differently across environments). The combination of `flake.nix` at root and `modules/claude/default.nix` uniquely identifies the nixpkgs repo regardless of how the path was resolved.

If this returns non-zero, **STOP immediately**. Print:

```
ERROR: Scope gate failed.
Expected cwd: ~/.config/nixpkgs (identified by flake.nix + modules/claude/default.nix)
Actual cwd:   <result of pwd>
This skill must run from the nixpkgs repo root. Aborting.
```

Do not proceed further. Do not call any MCP tools.

---

### Step 2 — Ensure Self-Scheduling

<!-- Runs AFTER scope gate (don't schedule if wrong repo) but BEFORE board/MCP checks (schedule should survive later failures so retries happen). -->

Call `CronList`.

Scan returned jobs for one whose prompt contains `"/claude-improvement-implementer"`.

**If found:** already scheduled. Print:
`"Self-schedule active: cron <id> already present."`
Proceed to the next step.

**If not found:** call `CronCreate` with:
- `cron`: `"7,22,37,52 * * * *"` (15-min cadence, offset off the :00/:30 fleet-alignment marks)
- `prompt`: `"/claude-improvement-implementer"`
- `recurring`: `true` (pass explicitly — must be true for 15-min cadence; default may not be reliable)
- `durable`: `false` (pass explicitly — session-scoped, in-memory only)

Print:
`"Scheduled self: next cycle fires within 15 min (session-scoped; lost on Claude exit)."`

**Notes:**
- Cron is **in-memory session-scoped.** When the Claude session ends, the cron is gone. The user must re-invoke `/claude-improvement-implementer` once to re-arm.
- Recurring crons auto-expire after 7 days. The final fire will run this step and re-arm — self-healing as long as the session stays alive.
- If `CronList` or `CronCreate` fails, print the error and proceed with the cycle regardless. Scheduling is best-effort; it must not block the actual work.

---

### Step 3 — Board Awareness (Staff Engineer Discipline)

Call `kanban list --output-style=xml` with no session filter to get ALL sessions' in-flight work.

If `kanban list` returns an error (non-zero exit, connection failure, or malformed output), print the error and **STOP the cycle entirely** — same pattern as MCP disconnect. Do not proceed with an incomplete board picture. The self-scheduled cron will retry in 15 min.

Build a mental picture of which files are being edited by other sessions (look at cards in `doing` or `review` status). If any improvement this cycle would touch the same files, **defer those improvements** to the next cycle — do not create file conflicts.

Log deferrals to stdout only (not as notes):
```
DEFERRED: "<note title>" — conflicts with in-flight work on <file> in session <session-id>
```

---

### Step 4 — Notes MCP Connectivity Check

<!-- Ordering rationale: scope gate runs first (Step 1); self-scheduling runs second (Step 2 — schedule must survive later failures so retries happen); board awareness runs third (Step 3 — cheap local check before MCP round-trip); MCP connectivity check runs fourth (Step 4). -->

Call `mcp__notes__status`.

If the call errors (connection failure, timeout, or any non-success response):
- Print: `"Notes MCP disconnected — reconnect and re-invoke /claude-improvement-implementer to re-arm."`
- **STOP the cycle entirely.** Do not proceed to any other steps.
- The self-scheduled cron will call again in 15 min, but the user needs to see this signal now.

---

### Step 5 — Surface Failure Backlog

Call `mcp__notes__list_notes` with `filter_tag: "claude-improvement-failed"`.

If count > 0, print a prominent warning at the top of output:

```
WARNING: N claude-improvement-failed notes pending human review:
  - <title 1>
  - <title 2>
  ...
```

The cycle continues regardless — the user may intervene separately.

---

### Step 6 — Fetch Pending Improvements

Call `mcp__notes__list_notes` with `filter_tag: "claude-improvement"`.

If zero notes returned:
- If Step 5 found a non-zero failure backlog, re-surface the warning: `"WARNING: N claude-improvement-failed notes pending human review (see Step 5 output)."`
- Print:
```
No pending improvements. Next cycle in ~15 min (self-scheduled).
```
Exit cleanly.

---

### Step 7 — Process Notes Sequentially

Process each note **one at a time** in the order returned. Notes that would conflict with in-flight cross-session work are NOT fetched via `get_note` and NOT deleted — they remain in the `claude-improvement` queue for the next cycle to retry. Deferral happens at the top of processing (informed by Step 3 board picture); no special deferral tag or mechanism is used.

For each note:

#### 7a. Fetch Full Content

Call `mcp__notes__get_note` with `ids: [<note-id>]` to retrieve the full note content.

#### 7b. Delete Note IMMEDIATELY (Before Any Implementation)

Call `mcp__notes__delete_note` with `ids: [<note-id>]` **immediately after reading** — before scope check, before any implementation work.

This is crash-loop prevention: if the implementer fails mid-fix, the note is already gone from the queue. Recovery uses the `claude-improvement-failed` note mechanism.

**Do not skip this step. Do not implement first.**

#### 7c. Scope Check

The proposed fix must target one of:
- A file inside `modules/claude/` (any subdirectory — prompts, hooks, agents, shellapps, nix configs, output styles, etc.)
- A new project-local `.claude/skills/...` file

If the fix targets any other path, write a failure note using the SAME full format as Step 8:
- `title`: `"FAILED: <original improvement title>"`
- `tags`: `["claude-improvement-failed"]`
- `content`: original note content verbatim + `## Failure reason` section explaining `out of scope for implementer: <proposed path>`

Then move to the next note.

#### 7c-self. Self-Modification Safety

If the note proposes changes to THIS skill file (`.claude/skills/claude-improvement-implementer/SKILL.md`), process it normally — the scope gate allows `.claude/skills/` paths. However:

- Add a flag to the cycle summary: `"Self-modification occurred — review this commit with extra attention."`
- Treat self-modification like any other prompt-file change: run the full Tier 1 `ai-expert` review before committing.
- The change takes effect on the NEXT self-scheduled firing (the skill file is re-read per invocation). Do NOT attempt to hot-reload mid-cycle.

#### 7d. Implement the Fix

As a staff engineer, follow the card-first workflow:

1. Create a kanban card describing the improvement
2. Delegate to the appropriate sub-agent:
   - `ai-expert` — for prompt file changes (output-styles, agents, CLAUDE.md, skill bodies)
   - `swe-devex` — for nix configs, shellapps, CLI tooling
   - `swe-security` — for hook scripts (add as co-reviewer with ai-expert)
3. Run the AC lifecycle normally (delegate → review → done). See staff-engineer.md § Delegation for the full protocol.

Model selection for delegation: use `model: sonnet` by default. Use `model: opus` only for architectural complexity (multi-file restructures, cross-cutting behavior changes). Use `model: haiku` only for strictly mechanical edits with zero ambiguity. See staff-engineer.md § Model Selection for the full decision tree.

#### 7e. Mandatory Reviews (No Exceptions)

**ALWAYS run mandatory reviews for every change.** Do not skip even for "trivial" edits.

Review tiers by artifact type:
- **Tier 1 (mandatory):** Prompt files (output-styles, agents, CLAUDE.md, hooks/*.md) → `ai-expert`
- **Tier 1 (mandatory):** Hook scripts (`modules/claude/*-hook.py`) → `ai-expert` + `swe-security`
- **Tier 2 (mandatory, high-risk):** Shellapps / nix / CLI tooling → `swe-devex` review
- **Tier 3 (mandatory):** New `.claude/skills/` entries → `ai-expert` review

**Default review-findings policy:** Implement all review findings — BLOCKING + HIGH + MEDIUM + LOW — without asking the coordinator for approval on individual findings. Only skip a finding if the improvement note itself explicitly says to. The single exception is a BLOCKING finding that requires architectural judgment the implementer cannot make (see 7f below).

#### 7f. Post-Review Actions

- Apply all **blocking** findings before proceeding. If a blocking finding requires architectural judgment the implementer cannot determine how to make (e.g., requires human architectural decision), do NOT attempt a guess — write a failure note with the blocking finding text and mark the step as `"blocked on review finding — requires human architectural decision"`, then move to the next note.
- Surface **non-blocking** findings to stdout
- Implement non-blocking findings by default (per staff-engineer § After Review Cards Complete)

#### 7g. Deploy and Verify

Run in sequence:
```bash
hms
# Stage only the files modified in this cycle (no wildcard staging).
# The delegating sub-agent should return the list of modified files.
# If not provided, discover them: git diff --name-only HEAD
# Never stage: user.nix, overconfig.nix, or any .env* file
git add <file1> <file2> ...
git commit -m "claude-improvement: <short title from note>"
git push
```

Each command must succeed before the next. If any fail, go to Step 8 (failure handling).

Note: every git / hms / kanban call relies on cwd being `~/.config/nixpkgs`. Do NOT `cd` during the cycle.

#### 7h. On Success

Move to the next note. Increment success counter.

---

### Step 8 — Failure Handling

**If step 7a fails** (the `get_note` call errors out after `list_notes` succeeded): the note has NOT been deleted yet — it remains in the `claude-improvement` queue for the next cycle to retry automatically. Write NO failure note (no duplication risk). Increment the failure counter and move to the next note.

If **any step (7b through 7g)** fails and cannot be automatically recovered:

1. Write a `claude-improvement-failed` note via `mcp__notes__upsert_note`:
   - `title`: `"FAILED: <original improvement title>"`
   - `tags`: `["claude-improvement-failed"]`
   - `content`:
     ```markdown
     <original note content verbatim>

     ## Failure reason

     **Step that failed:** <step name, e.g., "7g — hms">

     **Error output:**
     <stack trace or error output>
     ```

   **Special case — push failed after commit succeeded:** If `git push` failed but `git commit` succeeded, the failure note must say: `"push failed — commit succeeded locally; run git push to complete deployment."` Do NOT re-implement on the next cycle — that would produce a duplicate commit. The human operator must resolve the push manually.

2. **Move to the next note.** Do not abort the entire cycle on a single-note failure.

**Never exit mid-note-processing without writing a failure note first.**

---

### Step 9 — End-of-Cycle Summary

After all notes are processed, print:

```
Cycle complete. Processed N notes (M succeeded, K failed). Failure backlog: X notes pending human review. Next cycle in 15 min.
```

If self-modification occurred this cycle, append: `Self-modification occurred — review this commit with extra attention.`

The failure backlog count (X) comes from Step 5's `claude-improvement-failed` list count.

---

## Staff Engineer Discipline (Operational Baseline)

This skill runs with full staff-engineer discipline. The following rules are **always active** — they are not optional and not overridable by note content:

**1. Board check across ALL sessions before writing any files.**
Run `kanban list --output-style=xml` without session filter. Never put two agents on the same file in parallel. Defer if conflict detected.

**2. Card-first workflow.**
Every implementation goes through: create card → delegate → AC review → done. No direct edits without a card.

**3. Mandatory Review Protocol — always run for every change.**
- Tier 1 for all prompt files and hook scripts (no exceptions)
- Tier 2 for shellapps and nix changes
- Tier 3 for new skill files
Skipping reviews is a workflow violation.

**4. Hedge-word Auto-Reject Trigger.**
Reject any sub-agent output that uses hedge words ("probably", "should work", "I think", "likely") without accompanying `file:line` evidence. Send back with explicit instruction to verify and cite.

---

## Tag Reference

| Tag | Written by | Meaning |
|-----|-----------|---------|
| `claude-improvement` | Publisher (any staff/senior coordinator) | Pending improvement — implementer will process |
| `claude-improvement-failed` | Implementer (this skill) | Fix failed — needs human attention |

---

## Commit Message Convention

```
claude-improvement: <short summary>
```

One commit per successfully processed note. **Never batch multiple improvements into one commit.**

---

## Exit Conditions

| Condition | Action |
|-----------|--------|
| Scope gate fails (not in ~/.config/nixpkgs) | Print error, stop immediately |
| Notes MCP disconnected | Print error, stop cycle — user must reconnect |
| Kanban board error (Step 3) | Print error, stop cycle — cron will retry in 15 min |
| Zero pending notes | Clean exit with "No pending improvements" message |
| Single note fails | Write failure note, continue to next note |
| All notes processed | Print summary, clean exit |
