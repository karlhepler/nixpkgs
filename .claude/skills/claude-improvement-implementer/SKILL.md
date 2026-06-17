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

## Hard Rules

These rules are not judgment calls. No 'just this one branch' or 'I'll PR the risky change.' Violation breaks the implementer contract.

1. **Never create a git branch.** All work happens on `main`. If the worktree is not on `main` at session start, run `git checkout main` (after confirming a clean tree via `git status --short`) BEFORE doing any implementation work. The repo is deployed via `hms` against `main` — every change must land on `main` to take effect.

2. **Never run `gh pr create`** or any PR-creation primitive (`gh pr create`, `gh pr new`, etc.). Hard prohibition — no exceptions, no 'the change is risky so let me PR it' rationalization. If the implementer ever feels the urge to PR a change instead of committing directly, that urge is the failure mode. STOP and file a `claude-improvement-failed` note describing what triggered the urge. Include the original note content verbatim in the failure note per the Step 8 format.

3. **Standard workflow is always:** `hms` (validation gate) → `git add <specific files>` → `git commit` (per `## Commit Message Convention` below) → `git push origin main`. The `origin main` argument is explicit — not bare `git push` which could push the wrong ref if the worktree is somehow not on `main`.

4. **If a hook rejection, merge conflict, or push failure on `main` occurs,** STOP and file a `claude-improvement-failed` note (per Step 8). Do NOT route around the failure by creating a branch and opening a PR — that violates Rule 1 and Rule 2 simultaneously. The failure note is the recovery path; the human operator resolves it manually.

**Pre-cycle branch check (mandatory at Step 1 — Scope Gate):** after the sentinel-file check passes, run `git branch --show-current`. If the output is anything other than `main`, run `git status --short` to confirm clean tree; if clean, run `git checkout main` and continue. If NOT clean, STOP and file a `claude-improvement-failed` note with `title: 'FAILED: pre-cycle branch check — unexpected non-main branch with dirty tree'`, `tags: ['claude-improvement-failed']`, and content describing the current branch name, `git status --short` output, and the most recent commit on the unexpected branch. Do NOT proceed with work on a non-`main` branch.

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

> **Then run the pre-cycle branch check from `## Hard Rules` above** — confirm `git branch --show-current` outputs `main`; if not, follow the branch-check protocol there.

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

Build a mental picture of which files are being edited by other sessions (look at cards in `doing` status). If any improvement this cycle would touch the same files, **defer those improvements** to the next cycle — do not create file conflicts.

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
- A file inside this repository (`~/.config/nixpkgs/`) — any subdirectory. Most fixes target `modules/claude/` (prompts, hooks, agents, shellapps, nix configs, output styles), but fixes to other parts of the repo (`modules/kanban/`, `modules/git/`, repo-root `CLAUDE.md`, etc.) are also in-scope.
- A new project-local `.claude/skills/...` file.

If the fix targets a path OUTSIDE the repo (e.g., `$HOME/something`, `/tmp/`, another repo), write a failure note using the SAME full format as Step 8:
- `title`: `"FAILED: <original improvement title>"`
- `tags`: `["claude-improvement-failed"]`
- `content`: original note content verbatim + `## Failure reason` section explaining `out of scope for implementer: <proposed path> is outside ~/.config/nixpkgs/`

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
3. Run the AC lifecycle normally (delegate → done). See staff-engineer.md § Delegation for the full protocol.

Model selection for delegation: use `model: sonnet` by default. Use `model: opus` only for architectural complexity (multi-file restructures, cross-cutting behavior changes). Use `model: haiku` only for strictly mechanical edits with zero ambiguity. See staff-engineer.md § Model Selection for the full decision tree.

**MoV authoring banned-pattern self-check (mandatory before `kanban do --file`):** Before invoking `kanban do --file <path>`, scan every `mov_commands[].cmd` field in the card JSON for these banned patterns:

- `rg -qF ... '|' ...` or `rg -qiF ... '|' ...` — `-F` makes `|` a LITERAL pipe character, NOT alternation. Use bare `rg -qi 'A|B'` (no `-F`) OR split into separate `mov_commands` entries (one per phrase).
- `rg -qF ...` with regex metacharacters in the pattern — `-F` (fixed-strings) makes ALL regex metacharacters literal: `|` is NOT alternation, `()` are NOT grouping, `\d` is NOT a digit class, etc. If you intend regex behavior, drop `-F` and use bare `rg -qi`.
- `rg -qi 'a\|b\|c'` (backslash-pipe alternation) — RECURRENT authoring failure. In ripgrep's default Rust regex engine, `\|` is a LITERAL pipe character, NOT alternation. Bare `|` IS alternation. Root cause: JSON-escape muscle memory misfire — `|` is a regular character in JSON strings and requires NO escaping. Use bare `|` for alternation OR split into separate `mov_commands` entries.
- `&&` (AND-chain) — split into separate array entries. (The kanban CLI validator rejects this explicitly, but the self-check catches it before the CLI round-trip.)
- `rg -E ...` — `-E` means `--encoding` in ripgrep, NOT extended regex. Use bare `rg -qi`.
- `rg -qF ... -- '<dash-leading-pattern>' ...` with NO `--` or `-e` separator — `rg` parses dash-leading patterns as flags (exit 2). Use `rg -qF -- '-leading'` or `rg -qi -e '-leading'`.
- `test $(rg -c 'pattern' file) -le 0` for pattern-absence — broken when stdout is empty (`rg -c` produces NO output on zero matches, making `test $(empty) -le 0` syntactically broken with exit 2). Use `! rg -q 'pattern' file` instead — exits 0 if pattern is absent.
- File-wide negation MoVs (`! rg -q '<phrase>' <file>`) as removal assertions when the phrase may appear elsewhere in the file — file-wide negation forces the implementing agent to rephrase unrelated occurrences as collateral damage. The AC's intent is usually section-local ("remove this phrase from the NEW subsection I just added") but the MoV is file-wide. Fixes: (a) anchor on a longer multi-word distinctive phrase unique to the target section (e.g., `! rg -q 'stakes are real; default-idle' <file>` instead of `! rg -q 'stakes are real' <file>`); (b) extract the section first via heading anchors and grep the slice (e.g., `! sed -n '/^### Start Heading/,/^### Next Heading/p' <file> | rg -q '<phrase>'` — the shell pipe `|` here is fine, this is NOT the `\|` JSON-escape trap); (c) re-frame the AC as a positive presence assertion of the replacement phrase, which has no file-wide collateral. Option (c) is the safest default.
- **Code idiom** exclusion without a unique identifier — when authoring a `! rg -q` removal/exclusion MoV for a **code idiom** (a predicate or call shape like `any(pat in content for pat in ...)`, `.get(`, `await fetch(`, `subprocess.run(`), scope the pattern to the **unique adjacent identifier** (the list name, function name, or variable) so it cannot match a sibling occurrence of the same idiom in an unrelated function. The bare idiom matches every occurrence; the agent will alter ALL of them to satisfy the exclusion — silently mutating unrelated code. **Rule: the pattern must contain a unique identifier that distinguishes the target occurrence.** Worked example: a card used `! rg -q 'any\(pat in content' crew.py` to confirm a modal detector was changed from `any()` to `all()`. But `any(pat in content for pat in <LIST>)` also appeared in the unrelated function `_pane_shows_prompt_ready` (using `_PROMPT_READY_PATTERNS`). The agent flipped BOTH to `all()` to satisfy the file-wide exclusion, silently breaking prompt-ready detection (latent regression — required a follow-up revert). Correct form: scope by the unique list name — `! rg -q 'all\(pat in content for pat in _PROMPT_READY_PATTERNS'` and `rg -q 'all\(pat in content for pat in _MCP_TRUST_MODAL_PATTERNS'`.
- **Fixed-string (`-F`) anchor containing a code identifier** — when a `-F` MoV pattern includes a code identifier (e.g., `updatedInput`, `run_in_background`, `editFiles`) that the agent will naturally render as inline code in Markdown (backtick-wrapped), the MoV forces the agent to strip backtick formatting to satisfy the literal match, creating a formatting inconsistency in the artifact. **Worked example (card #2457):** the MoV used `rg -qiF 'via updatedInput'` (plain), while the agent correctly wrote the identifier backtick-wrapped; to pass, the agent stripped the backticks. **FIX options (prefer prose-only anchors — prefer in order):** (a) anchor on prose-only words that exclude the code identifier entirely; (b) drop `-F` and use a regex tolerating optional surrounding backticks (e.g., `rg -qi 'via \`?updatedInput\`?'`); (c) include the backticks in the literal pattern. Option (a) is safest.

If ANY pattern is present, fix BEFORE the CLI call. The kanban CLI validator catches `&&` and a few others, but the `-F` + `|` combination passes the validator and produces silently-broken MoVs — the implementing agent then either reports the MoV as unsatisfiable OR corrupts the artifact to make the literal pattern match. Both failure modes are preventable at authoring time.

**Worked example of the failure:** Card #1995 (broadcast voice patterns added to user-voice/SKILL.md) used `rg -qiF 'parens-reference|(reference)' file.md` intending alternation between two voice-profile entries. The agent inserted the literal string `parens-reference|(reference)` into the file to satisfy the MoV (artifact corruption). A follow-up cleanup card was required. Catch this at authoring time.

**Worked example of the collateral-rephrase failure:** Card #2016 (apply Tier 1 review findings to the Ghost Autocomplete subsection) used `! rg -q 'stakes are real' senior-staff-engineer.md` intending to remove the softening phrase from the new subsection only. The phrase appeared at two unrelated pre-existing locations (lines 1480 and 1497 — Check-In Cadence and Trust Calibration). To satisfy the file-wide negation, the agent rephrased both unrelated locations as collateral damage ("consequences are real", "the decision matters"). The rephrases were semantically reasonable in this case but the pattern is dangerous: the next collateral rephrase could damage important phrasing or destroy a deliberate hedge that exists for good reason. Section-scope the negation MoV using one of the three fixes above.

**Two gates:** This self-check fires before `kanban do --file`. There is ALSO a Write-tool-time reflex (see staff-engineer.md § Card Management — Write-tool-time reflex): scan the `cmd` fields BEFORE invoking the Write tool on the card JSON. Two gates = defense in depth. Both fire on every card.

**See also:** `kanban-cli` SKILL § MoV Authoring Banned Patterns and `staff-engineer.md` § Card Management — Card Fields (banned MoV patterns) for the comprehensive list (~14 patterns) and rationale. The self-check above is a short-form summary of the most-common failures. (For the cross-card analogue of the file-wide-negation trap above — file-scope leakage across parallel card editFiles — see `staff-engineer.md` § MoV Scope Isolation.)

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
git push origin main
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
