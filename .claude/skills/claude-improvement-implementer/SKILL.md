---
name: claude-improvement-implementer
description: Processes pending claude-improvement issues from GitHub (karlhepler/nixpkgs) and applies fixes to this repo with full staff-engineer review discipline. Invoke as `/claude-improvement-implementer` inside a dedicated tmux session running Claude Code from ~/.config/nixpkgs. Self-schedules via session-scoped CronCreate to run every 15 minutes — executes ONE cycle per firing.
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

2. **Never run `gh pr create`** or any PR-creation primitive (`gh pr create`, `gh pr new`, etc.). Hard prohibition — no exceptions, no 'the change is risky so let me PR it' rationalization. If the implementer ever feels the urge to PR a change instead of committing directly, that urge is the failure mode. STOP and record the failure on the issue being processed per the Step 8 format — add the `claude-improvement-failed` label and a comment describing what triggered the urge. The original body is already on the issue, so there is nothing to transcribe.

3. **Standard workflow is always:** `hms` (validation gate) → `git add <specific files>` → `git commit` (per `## Commit Message Convention` below) → `git push origin main`. The `origin main` argument is explicit — not bare `git push` which could push the wrong ref if the worktree is somehow not on `main`. **Exception — git-invisible-only fixes:** a fix touching ONLY machine-specific git-invisible files (`overconfig.nix`, `user.nix`, or a skill/config they host) deploys via `hms` alone and skips `git add`/`git commit`/`git push` entirely — there is nothing to commit (see Step 7g's Deploy variant). **Holding a ready commit is NOT an exception to this rule:** § 7g describes deferring a commit for a cycle when the tree is not deployable, and deferring a ready commit is not an exception to this rule — `hms`, staging, commit, and push all still run, just on a later cycle. A cycle that ends while holding a commit MUST file a HELD issue first (see § 7g).

4. **If a hook rejection, merge conflict, or push failure on `main` occurs,** STOP and record the failure on the issue (per Step 8). Do NOT route around the failure by creating a branch and opening a PR — that violates Rule 1 and Rule 2 simultaneously. The `claude-improvement-failed` label plus an explanatory comment is the recovery path; the human operator resolves it manually.

**Pre-cycle branch check (mandatory at Step 1 — Scope Gate):** after the sentinel-file check passes, run `git branch --show-current`. If the output is anything other than `main`, run `git status --short` to confirm clean tree; if clean, run `git checkout main` and continue. If NOT clean, STOP and open a NEW issue (this failure has no originating issue to attach to — it happens before any issue is read):

```bash
gh issue create --repo karlhepler/nixpkgs \
  --title "FAILED: pre-cycle branch check — unexpected non-main branch with dirty tree" \
  --body-file <path> --label claude-improvement-failed
```

Write the body to a scratchpad file first (never `--body`) describing the current branch name, `git status --short` output, and the most recent commit on the unexpected branch. Do NOT proceed with work on a non-`main` branch.

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

Log deferrals to stdout only — do not record them on the issue:
```
DEFERRED: #<n> "<issue title>" — conflicts with in-flight work on <file> in session <session-id>
```

---

### Step 4 — Queue Reachability Check

<!-- Ordering rationale: scope gate runs first (Step 1); self-scheduling runs second (Step 2 — schedule must survive later failures so retries happen); board awareness runs third (Step 3 — cheap local check before the network round-trip); queue reachability runs fourth (Step 4). -->

Run `gh auth status` and confirm the queue repo is reachable:

```bash
gh auth status
gh issue list --repo karlhepler/nixpkgs --label claude-improvement --state open --limit 1
```

If either errors (not authenticated, network failure, repo unreachable):
- Print: `"GitHub queue unreachable — run gh auth login, then re-invoke /claude-improvement-implementer to re-arm."`
- **STOP the cycle entirely.** Do not proceed to any other steps.
- The self-scheduled cron will call again in 15 min, but the user needs to see this signal now.

**Queue semantics (the whole model, in four lines):**
- **Pending** = OPEN issue labelled `claude-improvement`. This is the queue.
- **Dequeued / in progress** = the `claude-improvement` label removed, issue still open (Step 7b).
- **Done** = issue CLOSED (Step 7g).
- **Failed** = OPEN, labelled `claude-improvement-failed`, awaiting a human (Step 8).

The issue number is the stable id. Closing rather than deleting preserves a permanent audit trail of every improvement ever applied — the old delete-to-dequeue design destroyed that history.

**🚨 ALWAYS `--body-file`, NEVER `--body`.** Improvement bodies are dense with backticked identifiers, paths, and flags. Passing them through `--body "..."` hits the shell backtick-expansion trap: the shell expands the backticked span before `gh` sees it, the command SUCCEEDS, and the content is silently deleted. Write the body to a scratchpad file and pass `--body-file` (or `--body-file -` for stdin). Same rule for `gh issue comment --body-file`.

---

### Step 5 — Surface Failure Backlog

Run:

```bash
gh issue list --repo karlhepler/nixpkgs --label claude-improvement-failed --state open --limit 200 --json number,title
```

**`--limit` is mandatory on every queue-counting query.** `gh issue list` defaults to **30** and truncates silently — no error, no warning, no indicator that more exist. A step whose entire job is "give me the true count" cannot use the default. This is global CLAUDE.md § Pagination Discipline in `gh` clothing: a partial page treated as the complete set. If the backlog ever legitimately approaches 200, raise the number rather than removing it.

If count > 0, print a prominent warning at the top of output:

```
WARNING: N claude-improvement-failed issues pending human review:
  - #<number> <title 1>
  - #<number> <title 2>
  ...
```

The cycle continues regardless — the user may intervene separately.

---

### Step 5b — Orphan Sweep (issues in NO contract state)

Run:

```bash
gh issue list --repo karlhepler/nixpkgs --state open --limit 200 --json number,title,labels --jq '.[] | select((.labels | map(.name)) | (index("claude-improvement") | not) and (index("claude-improvement-failed") | not)) | "#\(.number) \(.title)"'
```

**Why this step exists.** Step 7b dequeues by removing the `claude-improvement` label BEFORE any implementation, which is correct crash-loop prevention — but it opens a window. An issue dequeued at 7b and then abandoned before Step 7g closes it or Step 8 labels it failed is in **none** of the four contract states: not pending, not failed, not closed, not in progress with anyone. Step 5 queries only `claude-improvement-failed`; Step 6 queries only `claude-improvement`. Neither finds it. Without this step, that improvement is lost permanently — not mis-filed, lost — and no cycle ever reports it.

The prose guard at the end of Step 8 ("never exit mid-issue-processing without recording the failure") cannot cover this. Every non-graceful termination — context exhaustion, session kill, a tool-block, `hms` hanging past the cron window, the machine sleeping — reaches the abandoned state precisely BECAUSE no further instruction runs. A guard that requires the agent to execute one more thing is unavailable in exactly the case it exists for. This query is the mechanical counterpart, and per § 7c-stale a mechanical check is worth more here than any prose rule: it runs at the next invocation rather than the next session.

Two known non-crash paths also land here, so this is not only a crash backstop: the git-invisible deploy variant in Step 7g (which skips the commit block where `gh issue close` lives), and the HELD path (which files a new issue but never returns the original to a contract state).

**If the sweep returns anything**, print it under the Step 5 warning:

```
WARNING: N orphaned issues (open, dequeued, never closed or failed):
  - #<number> <title>
```

Then re-label each one `claude-improvement` so the next cycle retries it:

```bash
gh issue edit <n> --repo karlhepler/nixpkgs --add-label claude-improvement
```

Re-labelling rather than closing is deliberate — the issue was dequeued but its fix was never confirmed applied, so returning it to Pending is the honest state. If the fix *did* land and only the close was missed, the next cycle re-reads it, finds the change already present, and closes it cheaply. Re-doing applied work costs one cycle; losing an improvement costs it entirely.

Do NOT re-label an orphan that a HELD issue already references — the HELD issue is its retry path. The HELD body names the original's number.

---

### Step 6 — Fetch Pending Improvements

Run:

```bash
gh issue list --repo karlhepler/nixpkgs --label claude-improvement --state open --limit 200 --json number,title,body
```

`--limit 200` for the same reason as Step 5 — the 30-issue default would silently hide a backlog tail.

If zero issues returned:
- If Step 5 found a non-zero failure backlog, re-surface the warning: `"WARNING: N claude-improvement-failed issues pending human review (see Step 5 output)."`
- Print:
```
No pending improvements. Next cycle in ~15 min (self-scheduled).
```
Exit cleanly.

---

### Step 7 — Process Issues Sequentially

Process each issue **one at a time** in the order returned. Issues that would conflict with in-flight cross-session work are NOT read via `gh issue view` and NOT dequeued — they keep the `claude-improvement` label and stay in the queue for the next cycle to retry. Deferral happens at the top of processing (informed by Step 3 board picture); no special deferral label or mechanism is used.

> **"Never stage X" means never `git add`/commit X — it does NOT mean the fix is out of scope.** Machine-specific files (`overconfig.nix`, `user.nix`) are git-invisible and never committed, yet they are fully editable and deploy via `hms`-only (see Step 7c scope + Step 7g's deploy variant). Never auto-fail an issue just because its target is a never-staged file.

For each issue:

#### 7a. Fetch Full Content

Run `gh issue view <n> --repo karlhepler/nixpkgs --json title,body,labels` to retrieve the full issue content.

(Step 6's list already returns `body`, so this is a re-read for safety rather than a strict necessity — but read it explicitly, because Step 8 distinguishes a failed READ from a later failure, and that distinction needs a read that can actually fail on its own.)

#### 7b. Dequeue IMMEDIATELY (Before Any Implementation)

Run **immediately after reading** — before scope check, before any implementation work:

```bash
gh issue edit <n> --repo karlhepler/nixpkgs --remove-label claude-improvement
```

This is crash-loop prevention: if the implementer fails mid-fix, the issue is already out of the pending queue. Recovery uses the `claude-improvement-failed` mechanism in Step 8.

**Why remove-label here and not `gh issue close`.** Closing is the DONE signal (Step 7g). Closing at this point would assert the work was applied before it was, and a crash immediately after would leave a closed-but-unapplied issue that no query surfaces — the failure would be invisible in both directions. Removing the label dequeues without claiming completion: the issue stays OPEN, so it is still visible to a human scanning the repo, but it will not be picked up by the next cycle's Step 6.

**Do not skip this step. Do not implement first.**

**Precondition on card creation: no kanban card may be created for an issue that still carries the `claude-improvement` label.** Before the first `kanban do` / `kanban todo` call for an issue, confirm the `--remove-label` call has already succeeded. If not, issue it first.

This is worded as a precondition on card creation rather than as "dequeue immediately" because "immediately" has no enforcement surface — it was already stated, and was still missed three times across two sessions. "No card without a completed dequeue" attaches the requirement to a concrete action the cycle must take anyway.

Be honest about what that buys, though: it is still a prose rule, read at cycle time, enforced by nothing — the same enforcement class that already failed three times. Aiming it at card creation helps because that action is unmissable; it does not make it a gate. Per § 7c-stale, a mechanical check would be worth more here if one becomes available.

**The high-risk shape is an issue that spawns multiple cards.** The dequeue is one small `gh` call sitting between reading the issue and designing the cards; when the card-design work is substantial (multi-file split, MoV authoring, banned-pattern self-check), that call is what gets dropped. All three known misses had this shape. In the third, the item describing the slip was visible in the pending list the coordinator had just read, and the slip happened anyway.

Detection is better than it used to be, though still not a gate: the issue reappears in the next cycle's Step 6 pending list, AND — unlike the previous transport — a skipped dequeue is now directly observable at any time via `gh issue list --repo karlhepler/nixpkgs --label claude-improvement --state open`, because the label is the queue. Treat the precondition above as the real control.

**Deliberately NOT adopted:** batching the `gh issue view` read and the `--remove-label` dequeue into one tool block. Step 8 depends on distinguishing a failed READ (issue keeps its label, no failure record, retried next cycle) from a later failure (already dequeued, failure record required). Batching would dequeue on a malformed or failed read and destroy that recovery path.

#### 7c. Scope Check

The proposed fix must target one of:
- A file inside this repository (`~/.config/nixpkgs/`) — any subdirectory. Most fixes target `modules/claude/` (prompts, hooks, agents, shellapps, nix configs, output styles), but fixes to other parts of the repo (`modules/kanban/`, `modules/git/`, repo-root `CLAUDE.md`, etc.) are also in-scope.
- **Machine-specific, git-invisible in-repo files** — `overconfig.nix` and `user.nix`, AND the skills/config they host (e.g. a `home.file.".claude/commands/*.md"` text block) — ARE in scope. Being git-invisible / never-staged does NOT make them out of scope; it only changes the deploy path (edit → `hms`, no commit — see Step 7g's Deploy variant). Do NOT auto-fail an issue as "out of scope" merely because its target lives in `overconfig.nix` / `user.nix`.
- A new project-local `.claude/skills/...` file.

Only a path genuinely OUTSIDE `~/.config/nixpkgs/` is out of scope. If the fix targets a path OUTSIDE the repo (e.g., `$HOME/something`, `/tmp/`, another repo), record it on the SAME issue using the Step 8 mechanism:

```bash
gh issue edit <n> --repo karlhepler/nixpkgs --add-label claude-improvement-failed --remove-label claude-improvement
gh issue comment <n> --repo karlhepler/nixpkgs --body-file <path>
```

Comment body: `out of scope for implementer: <proposed path> is outside ~/.config/nixpkgs/`. The original body is already on the issue — do not transcribe it.

Then move to the next issue.

#### 7c-stale. Your Own Prompt Is Stale (applies to EVERY issue, not just self-modification)

**This subsection is deliberately OUTSIDE § 7c-self.** It applies whenever an issue targets a coordinator output style — which is most cycles — and § 7c-self is entered only for issues targeting THIS skill file. Placing it there would have hidden it from exactly the case it exists for. (That mis-placement actually happened and was caught in review; it is the same defect class as a correct rule living somewhere nobody consults at the decision moment.)

**🚨 Your own prompt is stale, and this loop is the one participant its own fixes do not protect.**

A coordinator output style (`staff-engineer.md`, `senior-staff-engineer.md`) is loaded ONCE at session start. Any fix this loop ships to one of those files is live for future sessions and **inert for the current one** — for the rest of this session you are operating on the pre-fix prompt. This skill file is better (re-read per invocation); output styles are not.

Sub-agents are NOT affected the same way: each spawns fresh and picks up the deployed prompt, so an agent-definition fix takes effect on the very next spawn. That asymmetry is sharp and worth stating plainly: **this loop can improve every agent it delegates to, and cannot improve itself until it restarts.**

Observed instance: a session shipped a rule forbidding reconstructed note identifiers, then roughly seven cycles later fabricated one — right 8-character prefix, tail borrowed from the previously-processed note. The rule was verifiably present in the deployed file. It was not in the session's context. It survived only because the call happened to be a read; the documented upsert semantics would have silently created a duplicate note at the fabricated id and raised nothing.

Consequences to act on:
- **Do not assume your own behaviour reflects a rule you committed this session.** When you commit a coordinator-prompt fix, you have not acquired the behaviour — you have shipped it to your successor.
- **Prefer mechanical enforcement for anything guarding this loop's own operation.** A hook, a CLI validator, or a tool-contract change takes effect at the next invocation rather than the next session, so it is not subject to prompt staleness. When an issue offers both a prose-rule fix and a mechanical one for the same defect, the mechanical one is worth more here than the issue may credit — and a prose rule added to THIS file to guard this loop is worth less than it looks.
- **Restarting the session is the only thing that actually re-arms the coordinator with its own output** — and the cost is real: the self-schedule is session-scoped and in-memory, so a restart drops the cron and a human must re-invoke the skill once to re-arm. That makes unattended restart impossible as currently built. Do not restart mid-run on your own initiative; surface the tradeoff instead.

#### 7c-self. Self-Modification Safety

If the issue proposes changes to THIS skill file (`.claude/skills/claude-improvement-implementer/SKILL.md`), process it normally — the scope gate allows `.claude/skills/` paths. However:

- Add a flag to the cycle summary: `"Self-modification occurred — review this commit with extra attention."`
- Treat self-modification like any other prompt-file change: run the full Tier 1 `ai-expert` review before committing.
- The change takes effect on the NEXT self-scheduled firing (the skill file is re-read per invocation). Do NOT attempt to hot-reload mid-cycle. See § 7c-stale above for why a fix shipped to a coordinator OUTPUT STYLE is different — that one does not change the behaviour of the session that shipped it at all.
- **`.claude/` WRITE constraint:** background sub-agents CANNOT write `.claude/` files — they run in dontAsk mode and auto-deny the interactive confirmation `.claude/` edits require (staff-engineer.md § Rare Exceptions item 4). So do NOT delegate the WRITE to a background `ai-expert` (it will stall requesting authorization). The coordinator makes the edit DIRECTLY after confirming with the user (Rare Exception item 4). The coordinator MAY still delegate the read-only AC verification — a sub-agent running `kanban criteria check` only READS the file (reading `.claude/` is permitted; only writing is gated) — so the card still completes via the normal hook flow.

#### 7d. Implement the Fix

**STOP — confirm the 7b dequeue succeeded before creating any card.** § 7b states the precondition ("no kanban card may be created for an issue that still carries the `claude-improvement` label"), but it states it in the step that PERFORMS the dequeue, and two digressive subsections (§ 7c-stale, § 7c-self) sit between there and here. Card creation is the action the precondition gates, so the reminder belongs here, at the moment it fires — a rule stated only where it is DEFINED is a rule read forty lines before the decision it governs. If the `--remove-label` call has not already succeeded for this issue, issue it now, before step 1 below. This precondition has been missed three times across two sessions; all three misses had the shape of an issue that spawned multiple cards, where the card-design work crowded out the one small `gh` call.

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

**Default review-findings policy:** Implement all review findings — BLOCKING + HIGH + MEDIUM + LOW — without asking the coordinator for approval on individual findings. Only skip a finding if the improvement issue itself explicitly says to. The single exception is a BLOCKING finding that requires architectural judgment the implementer cannot make (see 7f below).

#### 7f. Post-Review Actions

- Apply all **blocking** findings before proceeding. If a blocking finding requires architectural judgment the implementer cannot determine how to make (e.g., requires human architectural decision), do NOT attempt a guess — record the failure on the issue per Step 8 (add the `claude-improvement-failed` label and a comment containing the blocking finding text), mark the step as `"blocked on review finding — requires human architectural decision"`, then move to the next issue.
- Surface **non-blocking** findings to stdout
- Implement non-blocking findings by default (per staff-engineer § After Review Cards Complete)

#### 7g. Deploy and Verify

**Ordering for NEW files (`git add` BEFORE `hms`):** if this cycle CREATED any new file (a new skill, new agent, or new doc under `modules/claude/global/`), run `git add <new-files>` BEFORE `hms`. This repo is a Nix flake, and flakes only include **git-tracked files** when evaluating the `./global` source tree into the Nix store — an **untracked** new file is invisible to the build, so `hms` copies from a store path that lacks it and the file silently fails to deploy (no error is raised). For MODIFIED already-tracked files, staging order does not matter (the flake sees uncommitted modifications to tracked files). This matches the project CLAUDE.md "git add (if needed) → hms → commit → push" guidance.

**`hms` deploys the WHOLE working tree — staging does not scope the deploy.** The `git add <file1> <file2> ...` step below scopes the COMMIT, and that is all it scopes. `hms` runs first and deploys everything in the tree, including other issues' uncommitted work. Completing one issue's commit therefore deploys whatever else happens to be sitting there. This is the mirror image of the new-file paragraph above: that one is about a tracked-file requirement making a new file LESS visible to the build than you expect, this one is about `hms` making tracked modifications MORE visible than the staging list implies.

Before running `hms`, run `git status --short` and **name the issue each modified path belongs to and whether that issue's review has cleared.** A path you cannot attribute is itself the answer. Then ask: **does the tree hold another issue's in-progress work I would not choose to deploy right now?** If it does, either finish that work to a deployable state first, or hold the ready commit until it is. A reviewed change left uncommitted for one more cycle is recoverable from its own records; content destroyed by deploying a change whose own review found reachable defects is not. This is a judgement about deployability, NOT permission to skip `hms` — Hard Rule 3 still holds, and when the tree is deployable, `hms` runs.

Observed instance: a cycle had a reviewed, clean output-style rewrite ready to commit while the same tree held a kanban CLI guard whose security review had just confirmed six live bypasses letting an allowlisted command execute code or overwrite arbitrary files. Those bypasses were inert only because the installed CLI predated the uncommitted change. Running `hms` to commit the unrelated Markdown change would have made them live. Nothing in this step prompted the check; it was caught while reasoning about commit ordering, which is not a mechanism. Those bypasses and the design that replaced them are recorded in commit `8874f39`.

The reverse is worth knowing too: a cycle that never runs `hms` leaves everything uncommitted AND leaves nothing deployed. Mid-cycle that is sometimes the safer state rather than a failure.

**If a cycle ends while holding a commit, file a HELD issue before printing the summary.** Open it with the `claude-improvement` label (so the next cycle's Step 6 picks it up), title it `HELD: <what is uncommitted>`, and record which files are held, which issue they belong to, what has already cleared them, and what still blocks:

```bash
gh issue create --repo karlhepler/nixpkgs \
  --title "HELD: <what is uncommitted>" \
  --body-file <path> --label claude-improvement
```

This is not bookkeeping for its own sake: `kanban done` fires when the agent stops, BEFORE the deploy step runs, so the board shows the card complete while its work sits uncommitted, and nothing in the issue or card lifecycle carries that signal. Step 6's pending list is the one place the next firing is guaranteed to look.

Cross-link it: mention the held issue's number in the HELD body, and comment the HELD issue's number on the held issue. Under the previous transport that linkage had to be maintained by hand in prose; issue numbers are stable ids, so use them.

**The original issue is still dequeued, and nothing closes it unless you say so.** It was dequeued at 7b, no push happened so 7g never closed it, and it is not failed — it is sitting in Step 5b's orphan bucket for as long as the hold lasts. The cross-link is what keeps it recoverable rather than lost, which is why it is required and not merely tidy. Two consequences: Step 5b must NOT re-label an orphan that a HELD issue already references (the HELD issue is its retry path — this is stated there too), and **when a later cycle completes the HELD issue, it closes the original in the same step**, not only the HELD one:

```bash
gh issue close <held-n> --repo karlhepler/nixpkgs --comment "applied in <sha>"
gh issue close <original-n> --repo karlhepler/nixpkgs --comment "applied in <sha> (was held; see #<held-n>)"
```

Be clear-eyed about the checkpoint above, though: this checkpoint is prose, read at cycle time, enforced by nothing — the same class § 7c-stale calls weakest, and the class this very gap already failed in. The HELD issue is the part with a mechanism behind it, because the next cycle reads the queue whether or not it reads this paragraph. A pre-`hms` validator comparing the tree against issues whose reviews have not cleared would be stronger again; none exists yet. If one is ever built, this paragraph should shrink to a pointer at it.

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
git commit -m "claude-improvement: <short title from the issue>"
git push origin main
# Mark done ONLY after the push succeeds — closing is the done signal:
gh issue close <n> --repo karlhepler/nixpkgs --comment "applied in <sha>"
```

A `Fixes #<n>` trailer in the commit message also closes the issue automatically (same repo, commits land directly on `main`) and is a fine belt-and-braces addition — but the explicit `gh issue close` above is deterministic and is the documented mechanism. Do not rely on the trailer alone.

**Verify new-file deploys:** after `hms`, for any new file expected to deploy to `~/.claude/`, confirm the artifact deployed (e.g. `test -f ~/.claude/<dest>`). A silent no-op leaves no error, so an explicit existence check is the only signal that an untracked-file ordering mistake did not occur.

Each command must succeed before the next. If any fail, go to Step 8 (failure handling).

Note: every git / hms / kanban call relies on cwd being `~/.config/nixpkgs`. Do NOT `cd` during the cycle.

**Deploy variant — git-invisible / never-stage files (`overconfig.nix`, `user.nix`, or a skill/config they host):** these files are made git-invisible by `hms` and must NEVER be `git add`ed / committed — but that does NOT mean they cannot be changed. Their deploy path is: **edit → `hms` → verify the deployed artifact (e.g. `test -f` / `rg` the `~/.claude/...` output) → close the issue → DONE.** Skip `git add` / `git commit` / `git push` entirely — there is nothing to commit; the change is live the moment `hms` deploys it.

**Close the issue explicitly on this path — it is easy to miss and the miss is silent.** The `gh issue close` call lives inside the `Run in sequence` block above, among the `git add`/`commit`/`push` lines this variant tells you to skip, and it is guarded by the comment "Mark done ONLY after the push succeeds" — a precondition this variant can never satisfy, since a git-invisible-only fix produces ZERO commits by design. Its `--comment "applied in <sha>"` has no `<sha>` to interpolate either. So an agent following this variant literally reaches the word "DONE" with the issue still dequeued, open, and unclosed — Step 5b's orphan bucket, reached on a fully SUCCESSFUL path rather than a crash. Run instead:

```bash
gh issue close <n> --repo karlhepler/nixpkgs --comment "applied via hms (git-invisible file; no commit)"
``` (If a single issue's fix touches BOTH a normally-committed file AND a git-invisible file, deploy once via `hms`, then commit ONLY the committed file — never the git-invisible one.)

#### 7h. On Success

Move to the next issue. Increment success counter.

---

### Step 8 — Failure Handling

**If step 7a fails** (the `gh issue view` read errors out after the Step 6 list succeeded): the issue has NOT been dequeued yet — it still carries the `claude-improvement` label and will be picked up by the next cycle automatically. Record NO failure (no duplication risk). Increment the failure counter and move to the next issue.

If **any step (7b through 7g)** fails and cannot be automatically recovered:

1. Record the failure **on the SAME issue** — do not open a second one. The failure belongs attached to the thing that failed, and the original body is already there verbatim, so there is nothing to transcribe:

   ```bash
   gh issue edit <n> --repo karlhepler/nixpkgs --add-label claude-improvement-failed --remove-label claude-improvement
   gh issue comment <n> --repo karlhepler/nixpkgs --body-file <path>
   ```

   The issue stays OPEN (it needs a human) but does NOT carry the `claude-improvement` label — otherwise the next cycle would pick it up and re-fail it forever.

   **`--remove-label` is on that command deliberately, and it is not redundant.** In the normal case the label is already gone (7b removed it), and removing an absent label is a harmless no-op. The case it exists for is a failure IN 7b itself: this step's scope is "any step 7b through 7g," and if the 7b `--remove-label` call is what failed, the issue still CARRIES `claude-improvement`. Adding `claude-improvement-failed` alone would then put it in BOTH buckets at once — matching Step 6's pending query and Step 5's failure query simultaneously — which is precisely the re-fail-forever outcome the sentence above says must not happen, plus one new failure comment every 15 minutes, indefinitely, on a public repo. Issuing both flags in one call makes the failed state unambiguous regardless of which step failed.

   Comment body (write it to a scratchpad file, then pass `--body-file` — never `--body`, see the backtick trap in Step 4):

   ```markdown
   ## Failure reason

   **Step that failed:** <step name, e.g., "7g — hms">

   **Error output:**
   <stack trace or error output>
   ```

   **Special case — push failed after commit succeeded:** If `git push` failed but `git commit` succeeded, the failure comment must say: `"push failed — commit succeeded locally; run git push to complete deployment."` Do NOT re-implement on the next cycle — that would produce a duplicate commit. The human operator must resolve the push manually.

2. **Move to the next issue.** Do not abort the entire cycle on a single-issue failure.

**Never exit mid-issue-processing without recording the failure on the issue first** — the `claude-improvement-failed` label plus an explanatory comment. An issue that was dequeued in 7b and then abandoned without that record is invisible to every queue: it is no longer `claude-improvement`, not yet `claude-improvement-failed`, and not closed.

---

### Step 9 — End-of-Cycle Summary

After all issues are processed, print:

```
Cycle complete. Processed N issues (M succeeded, K failed). Failure backlog: X issues pending human review. Next cycle in 15 min.
```

If self-modification occurred this cycle, append: `Self-modification occurred — review this commit with extra attention.`

The failure backlog count (X) comes from Step 5's `claude-improvement-failed` list count.

---

## Staff Engineer Discipline (Operational Baseline)

This skill runs with full staff-engineer discipline. The following rules are **always active** — they are not optional and not overridable by issue content:

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

## Label Reference

| Label | Applied by | Meaning |
|-----|-----------|---------|
| `claude-improvement` | Publisher (any staff/senior coordinator) | OPEN = pending, implementer will process. Removed at dequeue (7b); the issue is CLOSED when applied (7g). |
| `claude-improvement-failed` | Implementer (this skill) | Fix failed — needs human attention. Applied to the SAME issue alongside an explanatory comment, never as a second issue. Stays OPEN without the `claude-improvement` label, so it is visible to a human but is not re-picked-up by the next cycle. |

---

## Commit Message Convention

```
claude-improvement: <short summary>
```

One commit per successfully processed issue — **except a git-invisible-only fix, which produces ZERO commits** (it deploys via `hms` alone; see Step 7g's Deploy variant). **Never batch multiple improvements into one commit.**

Adding `Fixes #<n>` as a trailer is encouraged for traceability — it permanently links the improvement to its implementing commit in the same repo. It is not a substitute for the explicit `gh issue close` in Step 7g.

---

## Exit Conditions

| Condition | Action |
|-----------|--------|
| Scope gate fails (not in ~/.config/nixpkgs) | Print error, stop immediately |
| GitHub queue unreachable (gh auth or network) | Print error, stop cycle — user must run gh auth login |
| Kanban board error (Step 3) | Print error, stop cycle — cron will retry in 15 min |
| Zero pending issues | Clean exit with "No pending improvements" message |
| Single issue fails | Label it `claude-improvement-failed` with an explanatory comment, continue to next issue |
| All issues processed | Print summary, clean exit |
