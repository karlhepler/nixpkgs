# v5 Migration — Handoff

**Paused:** 2026-07-27 ~17:00 EDT · **Resume:** 2026-07-28 09:00
**Prior kanban session:** `stout-ember` — its cards will not show as `<mine>` in a new session. Use `kanban list` with no session filter.

> **Read this before touching anything.** It is authoritative for state. Do not re-derive from the board or git alone.

---

## What this project is

Restructuring this repository's Claude prompt configuration (24,210 lines / 44 files) to suit the Opus 5 and Sonnet 5 models. Four analysis documents were produced, then a staged migration began. **Rollout is staged by tier, shared layer first** — the owner's choice. Stage 1 = the two always-injected `CLAUDE.md` files; Stage 2 = coordinator output styles; Stage 3 = sub-agent definitions; Stage 4 = skills.

**Owner's hard constraint: the way they work must not change.** Every workflow invariant survives byte-for-byte in behavior even where wording changes. This effort changes how prompts are written, never what they make Claude do.

---

## The four documents (all committed)

| Doc | Path | Size |
|---|---|---|
| A — Anthropic's v5 guidance | `docs/v5-migration/A-anthropic-v5-guidance.md` | 2,044 |
| B — current configuration | `docs/v5-migration/B-current-configuration.md` | 908 |
| C — gap analysis | `docs/v5-migration/C-gap-analysis.md` | 1,002 |
| D — implementation plan | `docs/v5-migration/D-implementation-plan.md` | ~1,195 |

Plus `invariant-assertions.sh` (the tripwire) and `invariant-assertions.md` (its companion note).

---

## The ten owner decisions — DO NOT RE-LITIGATE

Recorded in full in Document D § `## Decisions`. Summary:

| Q | Decision |
|---|---|
| **Q1** | **Cited changes only.** Nothing ships without an Anthropic citation. Revisit after Stage 4. This is a hard constraint on all remaining work. |
| Q2 | Keep all incident provenance (follows from Q1) |
| Q3 | Keep the absolute delegation rule, add its motivation (D13 addition) |
| Q4 | Preserve restatement at successive workflow moments |
| Q5 | Keep both coordinator files, add a **mechanical sync check** (Stage 2 work) |
| Q6 | Accept reachable targets, track the path to 200 — **re-answered mid-Stage-1, see below** |
| Q7 | Defer the WI-14 `SubagentStop` check until after Stage 3 |
| Q8 | Keep `--effort xhigh`, document the rationale citing D14 |
| Q9 | **Reversed to (A):** remove the `ac-reviewer` roster line rather than annotate it |
| Q10 | `manage-pr-comments` `Bash(gh *)` grant → deny-override (Stage 4) |

**Q1 is the one that shapes everything.** Emphasis de-escalation, siren removal, output-style length, agent-definition length, restatement consolidation, and provenance stripping are all OUT OF SCOPE. Do not restyle.

---

## Committed (5 commits)

```
31038e8  claude: shrink always-injected global CLAUDE.md to 450 lines   ← Stage 1 unit 1.4
73d7e2d  docs: harden invariant tripwire against reword mutation
74f5214  docs: invariant tripwire for the always-injected prompt layer
1644184  docs: correct v5 migration plan against Stage 1 measurement
4ec6f8e  docs: Claude v5 prompt-migration analysis and approved plan
```

`31038e8` is **deployed** — `hms` ran successfully and all three pointers were verified to resolve at `~/.claude/docs/`.

---

## STATE AT PAUSE — verify this first

**Working tree was CLEAN at pause** apart from `.scratchpad/` (untracked, expected).

**Card #2996 — Stage 1 unit 1.5 — was IN FLIGHT when the session paused.** Its agent may have completed, partially completed, or died. **Check this before anything else:**

```
kanban list | rg 2996
git status --short
wc -l CLAUDE.md
bash docs/v5-migration/invariant-assertions.sh
```

Interpretation:
- `CLAUDE.md` still **387 lines** and tree clean → 1.5 never landed. Re-launch it (card #2996 is still in `doing`; see § Next action).
- `CLAUDE.md` at **≤291** and tree dirty → 1.5 completed but was never reviewed, deployed, or committed. Go to § Next action step 2.
- Anything else → surface to the user before proceeding. Another session may have run overnight.

---

## Stage 1 numbers — measured, not estimated

| File | Original | Cap | Status |
|---|---|---|---|
| `modules/claude/global/CLAUDE.md` | 530 | **450** | ✅ done, deployed, committed |
| `CLAUDE.md` (project root) | 387 | **291** | ⏳ unit 1.5 |
| Aggregate | 917 | **741** | 176-line reduction |

The plan originally promised 357 lines. Measurement cut that to 176 because **151 lines across both files are needed by every sub-agent and cannot be relocated anywhere** — no available mechanism both reduces context and reliably reaches a background sub-agent. **Anthropic's 200-line target is unreachable by prompt editing alone.** The hook-enforcement route is the tracked follow-on.

**Do not treat a cap as a quota.** If a unit cannot reach its cap without touching protected or sub-agent-needed content, it must report the achievable floor and the coordinator raises the cap. Never reclassify content to hit a number.

---

## Next action

**1. If unit 1.5 has not landed:** re-launch card #2996 with an `ai-expert` agent on Opus. Its card body carries the full spec. Note the two things most likely to go wrong: it must quantify **row 6's non-git-alias subset first** (its ledger counts row 6 in full while its own prose qualifies it — this may raise the 291 floor), and the **macOS Trash CLI section (~19 lines) must stay** — it looks like project trivia but is a protected mechanism explanation recording a real failure that destroyed 160 folders.

**2. Once 1.5 has landed, in this order:**
   a. Verify independently: line count ≤ its floor, `bash docs/v5-migration/invariant-assertions.sh` exits 0, `modules/claude/global/CLAUDE.md` untouched.
   b. **Tier-1 AI Expert review** — mandatory, non-optional. Prompt files are Tier 1. Model it on card #2993's card (unit 1.4's review): tell the reviewer what is already mechanically confirmed and direct it at what the tripwire structurally cannot check — pointer quality, coherence of relocated content in its new home, silent losses, scope creep against Q1.
   c. Resolve non-low findings. Auto-implement blocking/high/medium; surface lows.
   d. `hms` — the real build gate. `nix flake check` does not run flake8.
   e. **`git add` any new destination files before `hms`** — Nix excludes untracked files, so a new file that is not staged never reaches `~/.claude/docs/` and its pointer is dead on arrival.
   f. Commit.

**3. Then the two remaining Stage 1 gates:**
   - **Sub-agent injection smoke test.** Spawn one trivial background sub-agent and confirm its injected `claudeMd` block contains BOTH `CLAUDE.md` files and that the 31 assertions still pass against what it actually received. This is the only check that proves the *injection path* works rather than that the files say the right thing.
   - **Owner soak.** One week of ordinary `staff` and `sstaff` work with no behavioral surprise. **Stage 2 does not open until the owner confirms this.** That gate is theirs, not yours.

---

## The tripwire

`docs/v5-migration/invariant-assertions.sh` — 31 assertions, run from the repo root, no arguments. Exit 0 = all pass.

It survived three mutation rounds and provably catches both **deletion** and **reword-dilution** of every protected invariant. Round one found 12 of 28 assertions blind to rewording; round three closed the last two by anchoring on full sentences including their trailing periods.

**Known limitation, named honestly:** substring anchors cannot catch a *contradicting sentence appended after an untouched anchor*. If someone leaves "never skip hooks" intact and adds "except when X", every assertion passes. Human review covers that class.

**If it fails after an edit, the edit broke an invariant. Fix the edit, never the script.** It is committed and is not to be modified to make a run green.

---

## Open hand-offs to later stages

| Item | Owner |
|---|---|
| Stale pointer `senior-staff-engineer.md:1904` (roster reference) | Stage 2 |
| Stale pointer `senior-staff-engineer.md:1298` (roster reference) | Stage 2 |
| Check-in 5-field template now behind a discretionary read for the staff tier — decide whether to inline it in `staff-engineer.md` | Stage 2 |
| Mechanical sync check between the two coordinator prompts (Q5) | Stage 2 |
| `manage-pr-comments` `Bash(gh *)` deny-override (Q10) | Stage 4 |
| `default.nix:61,350` describe a deleted "dual-loop AC review via haiku" — out of migration scope, one-line fix whenever | unscheduled |
| Document D's 183-line protected table is keyed to the pre-edit 530-line global file — **re-derive before any further edit to that file** | whoever edits it next |

---

## Improvement notes filed (Notes MCP, tag `claude-improvement`)

| ID | Finding |
|---|---|
| `4ec25be8-b9ec-4cc9-833f-38138209c4d8` | Agents finish work then never run `criteria check` — 5 occurrences. Prompt hardening falsified; automate recovery in the `SubagentStop` hook. |
| `e5c7c5c4-1023-438d-a063-d867aab8d517` | Corpus partitioned from a hand-written glob; census corrected 4× |
| `adbdf062-375b-4f96-a1bd-58bfbe9dd803` | `upsert_note` keys on id, not title — "updating" a note creates a duplicate |
| `bb5ee147-3e43-452b-b324-0d829ca7fe55` | Artifacts assert coverage they never verified — 3 instances; the existing rule detects but does not prevent |

---

## Cautions

- **This repository carries uncommitted work from other sessions.** Never run `git restore`, `git checkout --`, `git reset`, `git clean`, or `git stash`. Check `kanban list` across all sessions before any file-level git operation.
- **Never bypass a git hook.** No `--no-verify`, and never route the bypass to the human either.
- **The scheduled 9am cron job was session-only** and does not survive this session exiting. If you are reading this because the cron fired, good. If the user started you manually, that is why.
- Five agents this session did substantial work then stopped without running a single `kanban criteria check`, two at the exact moment of turning from work to verification. Expect it. The recovery that worked 5/5 times: a narrow re-launch stating the deliverable already exists, naming the one remaining gap, forbidding whatever killed the prior run, and listing the exact check commands.
