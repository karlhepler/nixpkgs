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

3. **Standard workflow is always:** `hms` (validation gate) → `git add <specific files>` → `git commit` (per `## Commit Message Convention` below) → `git push origin main`. The `origin main` argument is explicit — not bare `git push` which could push the wrong ref if the worktree is somehow not on `main`. **Exception — git-invisible-only fixes:** a fix touching ONLY machine-specific git-invisible files (`overconfig.nix`, `user.nix`, or a skill/config they host) deploys via `hms` alone and skips `git add`/`git commit`/`git push` entirely — there is nothing to commit (see Step 7g's Deploy variant). **Holding a ready commit is NOT an exception to this rule:** § 7g describes deferring a commit for a cycle when the tree is not deployable, and deferring a ready commit is not an exception to this rule — `hms`, staging, commit, and push all still run, just on a later cycle. A cycle that ends while holding a commit MUST file a HELD note first (see § 7g).

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

Call `kanban list --session <id> --output-style=xml` to get ALL sessions' in-flight work.

**Always pass `--session <id>`; never the bare form.** Passing it loses no coverage — the `<others>` bucket returns the identical foreign cards, correctly attributed. The bare form buckets foreign cards under a heading that reads as this session's own, so cross-session conflicts are the exact thing it obscures.

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

> **"Never stage X" means never `git add`/commit X — it does NOT mean the fix is out of scope.** Machine-specific files (`overconfig.nix`, `user.nix`) are git-invisible and never committed, yet they are fully editable and deploy via `hms`-only (see Step 7c scope + Step 7g's deploy variant). Never auto-fail a note just because its target is a never-staged file.

For each note:

#### 7a. Fetch Full Content

Call `mcp__notes__get_note` with `ids: [<note-id>]` to retrieve the full note content.

#### 7b. Delete Note IMMEDIATELY (Before Any Implementation)

Call `mcp__notes__delete_note` with `ids: [<note-id>]` **immediately after reading** — before scope check, before any implementation work.

This is crash-loop prevention: if the implementer fails mid-fix, the note is already gone from the queue. Recovery uses the `claude-improvement-failed` note mechanism.

**Do not skip this step. Do not implement first.**

**Precondition on card creation: no kanban card may be created for a note that is still in the pending queue.** Before the first `kanban do` / `kanban todo` call for a note, confirm `delete_note` has already been issued for it. If not, issue it first.

This is worded as a precondition on card creation rather than as "delete immediately" because "immediately" has no enforcement surface — it was already stated, and was still missed three times across two sessions. "No card without a completed delete" attaches the requirement to a concrete action the cycle must take anyway.

Be honest about what that buys, though: it is still a prose rule, read at cycle time, enforced by nothing — the same enforcement class that already failed three times. Aiming it at card creation helps because that action is unmissable; it does not make it a gate. Per § 7c-stale, a mechanical check would be worth more here if one becomes available.

**The high-risk shape is a note that spawns multiple cards.** The delete is one small MCP call sitting between reading the note and designing the cards; when the card-design work is substantial (multi-file split, MoV authoring, banned-pattern self-check), that call is what gets dropped. All three known misses had this shape. In the third, the note describing the slip was visible in the pending list the coordinator had just read, and the slip happened anyway.

Detection, and it is weak: the note reappears in the next cycle's Step 6 pending list. That relies on recognizing a familiar title in a long list, which is not a mechanism. Treat the precondition above as the real control.

**Deliberately NOT adopted:** batching `get_note` and `delete_note` into one tool block. Step 8 depends on distinguishing a failed `get_note` (note survives, no failure note, retried next cycle) from a later failure (note already gone, failure note required). Batching would delete on a malformed or failed get and destroy that recovery path.

#### 7c. Scope Check

The proposed fix must target one of:
- A file inside this repository (`~/.config/nixpkgs/`) — any subdirectory. Most fixes target `modules/claude/` (prompts, hooks, agents, shellapps, nix configs, output styles), but fixes to other parts of the repo (`modules/kanban/`, `modules/git/`, repo-root `CLAUDE.md`, etc.) are also in-scope.
- **Machine-specific, git-invisible in-repo files** — `overconfig.nix` and `user.nix`, AND the skills/config they host (e.g. a `home.file.".claude/commands/*.md"` text block) — ARE in scope. Being git-invisible / never-staged does NOT make them out of scope; it only changes the deploy path (edit → `hms`, no commit — see Step 7g's Deploy variant). Do NOT auto-fail a note as "out of scope" merely because its target lives in `overconfig.nix` / `user.nix`.
- A new project-local `.claude/skills/...` file.

Only a path genuinely OUTSIDE `~/.config/nixpkgs/` is out of scope. If the fix targets a path OUTSIDE the repo (e.g., `$HOME/something`, `/tmp/`, another repo), write a failure note using the SAME full format as Step 8:
- `title`: `"FAILED: <original improvement title>"`
- `tags`: `["claude-improvement-failed"]`
- `content`: original note content verbatim + `## Failure reason` section explaining `out of scope for implementer: <proposed path> is outside ~/.config/nixpkgs/`

Then move to the next note.

#### 7c-stale. Your Own Prompt Is Stale (applies to EVERY note, not just self-modification)

**This subsection is deliberately OUTSIDE § 7c-self.** It applies whenever a note targets a coordinator output style — which is most cycles — and § 7c-self is entered only for notes targeting THIS skill file. Placing it there would have hidden it from exactly the case it exists for. (That mis-placement actually happened and was caught in review; it is the same defect class as a correct rule living somewhere nobody consults at the decision moment.)

**🚨 Your own prompt is stale, and this loop is the one participant its own fixes do not protect.**

A coordinator output style (`staff-engineer.md`, `senior-staff-engineer.md`) is loaded ONCE at session start. Any fix this loop ships to one of those files is live for future sessions and **inert for the current one** — for the rest of this session you are operating on the pre-fix prompt. This skill file is better (re-read per invocation); output styles are not.

Sub-agents are NOT affected the same way: each spawns fresh and picks up the deployed prompt, so an agent-definition fix takes effect on the very next spawn. That asymmetry is sharp and worth stating plainly: **this loop can improve every agent it delegates to, and cannot improve itself until it restarts.**

Observed instance: a session shipped a rule forbidding reconstructed note identifiers, then roughly seven cycles later fabricated one — right 8-character prefix, tail borrowed from the previously-processed note. The rule was verifiably present in the deployed file. It was not in the session's context. It survived only because the call happened to be a read; the documented upsert semantics would have silently created a duplicate note at the fabricated id and raised nothing.

Consequences to act on:
- **Do not assume your own behaviour reflects a rule you committed this session.** When you commit a coordinator-prompt fix, you have not acquired the behaviour — you have shipped it to your successor.
- **Prefer mechanical enforcement for anything guarding this loop's own operation.** A hook, a CLI validator, or a tool-contract change takes effect at the next invocation rather than the next session, so it is not subject to prompt staleness. When a note offers both a prose-rule fix and a mechanical one for the same defect, the mechanical one is worth more here than the note may credit — and a prose rule added to THIS file to guard this loop is worth less than it looks.
- **Restarting the session is the only thing that actually re-arms the coordinator with its own output** — and the cost is real: the self-schedule is session-scoped and in-memory, so a restart drops the cron and a human must re-invoke the skill once to re-arm. That makes unattended restart impossible as currently built. Do not restart mid-run on your own initiative; surface the tradeoff instead.

#### 7c-self. Self-Modification Safety

If the note proposes changes to THIS skill file (`.claude/skills/claude-improvement-implementer/SKILL.md`), process it normally — the scope gate allows `.claude/skills/` paths. However:

- Add a flag to the cycle summary: `"Self-modification occurred — review this commit with extra attention."`
- Treat self-modification like any other prompt-file change: run the full Tier 1 `ai-expert` review before committing.
- The change takes effect on the NEXT self-scheduled firing (the skill file is re-read per invocation). Do NOT attempt to hot-reload mid-cycle. See § 7c-stale above for why a fix shipped to a coordinator OUTPUT STYLE is different — that one does not change the behaviour of the session that shipped it at all.
- **`.claude/` WRITE constraint:** background sub-agents CANNOT write `.claude/` files — they run in dontAsk mode and auto-deny the interactive confirmation `.claude/` edits require (staff-engineer.md § Rare Exceptions item 4). So do NOT delegate the WRITE to a background `ai-expert` (it will stall requesting authorization). The coordinator makes the edit DIRECTLY after confirming with the user (Rare Exception item 4). The coordinator MAY still delegate the read-only AC verification — a sub-agent running `kanban criteria check` only READS the file (reading `.claude/` is permitted; only writing is gated) — so the card still completes via the normal hook flow.

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

**Ordering for NEW files (`git add` BEFORE `hms`):** if this cycle CREATED any new file (a new skill, new agent, or new doc under `modules/claude/global/`), run `git add <new-files>` BEFORE `hms`. This repo is a Nix flake, and flakes only include **git-tracked files** when evaluating the `./global` source tree into the Nix store — an **untracked** new file is invisible to the build, so `hms` copies from a store path that lacks it and the file silently fails to deploy (no error is raised). For MODIFIED already-tracked files, staging order does not matter (the flake sees uncommitted modifications to tracked files). This matches the project CLAUDE.md "git add (if needed) → hms → commit → push" guidance.

**`hms` deploys the WHOLE working tree — staging does not scope the deploy.** The `git add <file1> <file2> ...` step below scopes the COMMIT, and that is all it scopes. `hms` runs first and deploys everything in the tree, including other notes' uncommitted work. Completing one note's commit therefore deploys whatever else happens to be sitting there. This is the mirror image of the new-file paragraph above: that one is about a tracked-file requirement making a new file LESS visible to the build than you expect, this one is about `hms` making tracked modifications MORE visible than the staging list implies.

Before running `hms`, run `git status --short` and **name the note each modified path belongs to and whether that note's review has cleared.** A path you cannot attribute is itself the answer. Then ask: **does the tree hold another note's in-progress work I would not choose to deploy right now?** If it does, either finish that work to a deployable state first, or hold the ready commit until it is. A reviewed change left uncommitted for one more cycle is recoverable from its own records; content destroyed by deploying a change whose own review found reachable defects is not. This is a judgement about deployability, NOT permission to skip `hms` — Hard Rule 3 still holds, and when the tree is deployable, `hms` runs.

Observed instance: a cycle had a reviewed, clean output-style rewrite ready to commit while the same tree held a kanban CLI guard whose security review had just confirmed six live bypasses letting an allowlisted command execute code or overwrite arbitrary files. Those bypasses were inert only because the installed CLI predated the uncommitted change. Running `hms` to commit the unrelated Markdown change would have made them live. Nothing in this step prompted the check; it was caught while reasoning about commit ordering, which is not a mechanism. Those bypasses and the design that replaced them are recorded in commit `8874f39`.

The reverse is worth knowing too: a cycle that never runs `hms` leaves everything uncommitted AND leaves nothing deployed. Mid-cycle that is sometimes the safer state rather than a failure.

**If a cycle ends while holding a commit, file a HELD note before printing the summary.** Tag it `claude-improvement`, title it `HELD: <what is uncommitted>`, and record which files are held, which note they belong to, what has already cleared them, and what still blocks. This is not bookkeeping for its own sake: `kanban done` fires when the agent stops, BEFORE the deploy step runs, so the board shows the card complete while its work sits uncommitted, and nothing in the note, failure-note, or card lifecycle carries that signal. Step 6's pending list is the one place the next firing is guaranteed to look.

Be clear-eyed about the checkpoint above, though: this checkpoint is prose, read at cycle time, enforced by nothing — the same class § 7c-stale calls weakest, and the class this very gap already failed in. The HELD note is the part with a mechanism behind it, because the next cycle reads the queue whether or not it reads this paragraph. A pre-`hms` validator comparing the tree against notes whose reviews have not cleared would be stronger again; none exists yet. If one is ever built, this paragraph should shrink to a pointer at it.

(If either this paragraph group or the new-file ordering paragraph above is edited later, re-check the mirror-image cross-reference between them to keep that cross-reference accurate.)

Run in sequence:
```bash
# If this cycle CREATED new files, git add them FIRST — flakes ignore untracked files:
git add <any-new-files>
hms
# Stage the remaining files modified in this cycle (no wildcard staging).
# The delegating sub-agent should return the list of modified files.
# If not provided, discover them: git diff --name-only HEAD
# Never stage: user.nix, overconfig.nix, or any .env* file
git add <file1> <file2> ...
git commit -m "claude-improvement: <short title from note>"
git push origin main
```

**Verify new-file deploys:** after `hms`, for any new file expected to deploy to `~/.claude/`, confirm the artifact deployed (e.g. `test -f ~/.claude/<dest>`). A silent no-op leaves no error, so an explicit existence check is the only signal that an untracked-file ordering mistake did not occur.

Each command must succeed before the next. If any fail, go to Step 8 (failure handling).

Note: every git / hms / kanban call relies on cwd being `~/.config/nixpkgs`. Do NOT `cd` during the cycle.

**Deploy variant — git-invisible / never-stage files (`overconfig.nix`, `user.nix`, or a skill/config they host):** these files are made git-invisible by `hms` and must NEVER be `git add`ed / committed — but that does NOT mean they cannot be changed. Their deploy path is: **edit → `hms` → verify the deployed artifact (e.g. `test -f` / `rg` the `~/.claude/...` output) → DONE.** Skip `git add` / `git commit` / `git push` entirely — there is nothing to commit; the change is live the moment `hms` deploys it. (If a single note's fix touches BOTH a normally-committed file AND a git-invisible file, deploy once via `hms`, then commit ONLY the committed file — never the git-invisible one.)

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
Run `kanban list --session <id> --output-style=xml` — always with `--session`, never the bare form (see Step 3 for why: the `<others>` bucket already returns every foreign card, correctly attributed). Never put two agents on the same file in parallel. Defer if conflict detected.

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

One commit per successfully processed note — **except a git-invisible-only fix, which produces ZERO commits** (it deploys via `hms` alone; see Step 7g's Deploy variant). **Never batch multiple improvements into one commit.**

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
