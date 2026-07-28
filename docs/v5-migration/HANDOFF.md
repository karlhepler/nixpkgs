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

**Unit 1.5 landed and is committed.** Both Stage 1 edits are done. Expected state:

```
wc -l CLAUDE.md                                  → 338   (was 314; see amendment below)
wc -l modules/claude/global/CLAUDE.md            → 450
bash docs/v5-migration/invariant-assertions.sh   → exit 0, 31/31
git status --short                               → clean apart from .scratchpad/
```

If any of that differs, **stop and surface it to the user** — another session may have run overnight.

### ⚠️ AMENDMENT 2026-07-28 — the project file is 338, and the 314 cap is superseded

**The user committed `82160b4`, adding 24 lines to the project-root `CLAUDE.md`: `## 🚨 ALL WORK HAPPENS DIRECTLY ON \`main\` — NO BRANCHES, EVER 🚨` at lines 9–31.** The file is now **338 lines against a cap this document recorded as 314**.

**This is not a regression of Stage 1 and must not be treated as one.** Two separate facts:

| | Value | Meaning |
|---|---|---|
| Stage 1's achieved reduction | **153 lines** (917 → 764) | historical, correct, unchanged — do not restate it as anything else |
| Current net reduction | **129 lines** (917 → 788) | Stage 1's 153 minus 24 lines of *new policy content* the user added afterward |

Stage 1 removed 153 lines. The user then added 24 lines of new content. Conflating the two would both understate Stage 1's outcome and misdescribe the file today.

**The cap yields to the content, by this document's own rule** — "Do not treat a cap as a quota," two sections down. `82160b4` documents a prohibition whose absence had already caused real damage: a branch created in this shared checkout captured two unrelated commits from a concurrent session (`4fdc9e9`, `0561642` — Stage 1's own work). That content is worth more than the number. **The 314 figure is superseded; the operative cap for the project-root file is 338.**

**Every other `314` in this document and in `D-implementation-plan.md` is now historical.** It correctly describes the state at Stage 1's close. Do not blanket-replace it — 95 lines across the migration docs match `314` or `387`, and most are legitimate history (`387` was the true pre-migration count). Fix only figures asserted as *current state*.

**Nothing live is broken.** `invariant-assertions.sh` was re-run at this amendment: **31/31 passing**. It asserts content presence, not line counts — its only `387` is a corpus comment — so no tripwire depends on either figure. This staleness was documentary only.

### ⚠️ Unit 1.5 IS LIVE — corrected claim, read carefully

An earlier draft of this document said unit 1.5 was "committed but not deployed, so the review gate survives." **That was wrong.** The correction:

**The project-root `CLAUDE.md` is not a Nix-deployed artifact.** Claude Code reads it **in place from the repository**. `hms` deploys `modules/claude/global/*` into `~/.claude/`; the project file has no deploy step. Confirmed: `~/.claude/CLAUDE.md` is 450 lines — that is the *global* file — while the project file (314 lines at Stage 1's close, **338 today** after `82160b4`) is read directly from the repo path.

**Consequence: unit 1.5's change took effect the moment the file changed on disk.** Any session started in this repository since then uses the post-edit version (314 lines then, **338 now**). There was never an `hms` gate to withhold, so the Tier-1 review is now reviewing something already in effect rather than gating it.

**Why this was not reverted:** the tripwire passes 31/31, so every protected invariant is verified intact — the unreviewed dimension is *quality* (pointer usefulness, coherence of relocated content), not invariant correctness. Reverting a change whose safety properties are verified, purely to restore a process ordering, would have been worse than recording accurately that the ordering did not hold.

**Unit 1.4 is different and is fine.** The global file at 450 lines passed its full Tier-1 review, had its findings resolved, and was deployed through `hms` afterward. Its gates held.

### The 291 → 314 cap correction

Unit 1.5 reported `blocked` rather than hitting its cap, which is the escalation contract working. It proved 291 unreachable: the number equalled `82 protected + 113 KEEP + 96 sub-agent-needed` **exactly**, budgeting nothing for the 16-line git-alias block, 4 structural lines, or 3 mandated pointers. Even removing the off-limits categories leaves 295.

Root cause, cited: `D-implementation-plan.md:704-710` subtracted the ledger's full safe set including row 6's span 106–108 — that section's own heading and subheading. **Row 6 is a SPLIT that retains KEEP content, so it must retain a heading.** The subtraction treated a SPLIT's structural overhead as removable. The ledger flagged this risk at its line 90 and the zero-slack design left nothing to absorb it.

Row 6's git-alias block measured **16–17 lines, not 49**, so verified-safe dropped 96 → 79.

**The cap was raised to 314. Card #2996's criterion 1 was replaced accordingly.** ~~Document D still states 291 in several places — **it has not been amended yet.** See § Next action.~~ **✅ DONE — corrected 2026-07-28.** Amendment 3 (card #2999) amended Document D. It carries 63 lines mentioning 291, all of them **explicitly marked superseded** with `⚠ SUPERSEDED BY AMENDMENT 3` callouts — that is the document's deliberate convention ("superseded arithmetic is left standing throughout this document so corrections stay auditable"), not an oversight. Verified: § Executive Summary and § Recomputed Numbers — the two sections next-action 5 named specifically — both carry the corrected 450 / 314 / 764 / 153 figures immediately after their superseded blocks. **Do not re-do this work.**

---

## Stage 1 numbers — measured, not estimated

| File | Original | Cap | Status |
|---|---|---|---|
| `modules/claude/global/CLAUDE.md` | 530 | **450** | ✅ reviewed, deployed, committed |
| `CLAUDE.md` (project root) | 387 | ~~314~~ → **338** | ✅ reviewed, committed, live; cap superseded by `82160b4` |
| Aggregate | 917 | ~~764~~ → **788** | **Stage 1 reduction 153 — disk only, see below; 129 net after `82160b4`** |

> **This table was itself stale until 2026-07-28.** It said 291 / 741 / 176 after the cap correction had already been recorded elsewhere in this same document — exactly the failure this document warns about two sections down. Caught on re-read at resume. If you find another stale figure here, fix it and do not assume the rest are right.

> **⚠ Injection smoke test result (card #3004): `OLD BOTH`.** A sub-agent spawned from this session, instructed not to read either Tier-1 file directly, received the pre-edit content of both — the project-root file still carried `## External References` and `## Configuration Structure`, headings Stage 1 removed, and neither file carried any of the four reference markers the edits added. Injection is structurally intact (both files were present); the content served was stale. **The 153-line reduction above is a disk measurement, not a confirmed saving** — it is unrealized in the session that made it, and untested for a session started afterward. Full result: `.scratchpad/S1-injection-smoke-test.md`; the rule this establishes and the corrected achievement claim: `docs/v5-migration/D-implementation-plan.md` § The in-session verification limit and § Amendment 4. **Consequence: the owner soak below must begin from a FRESH session started after Stage 1's edits landed.** Soaking from a session started before the edits exercises the pre-edit files and validates nothing — restarting `staff`/`sstaff` first makes the soak both the behavioral check and the only planned confirmation that a fresh session actually picks up the reduced files, which remains untested until that soak runs.

> **⚠ UPDATE (2026-07-28, card #3013): cross-session realization is now CONFIRMED, not untested.** Two fresh sessions — neither the session that made Stage 1's edits nor a sub-agent spawned from it — were each asked whether their injected instruction file contains a marker the edits **added** (deliberately an added marker, not a removed one — absence of a removed marker proves nothing, since it is equally consistent with a different file or no injection at all). The project-level session (started in this repository) found `nixpkgs-repo-reference.md` referenced in its injected `CLAUDE.md`; the global-level session (started in a **different** repository, valid because the global file is user-scope and injected regardless of which repository the session starts in) found `cli-and-mcp-reference.md` referenced in its injected global `CLAUDE.md`. It also independently described the pointer-not-import mechanism correctly. **The `OLD BOTH` verdict directly above is unchanged and still stands** — it describes the session that made the edit and any sub-agent spawned from it, which still receive pre-edit content; this update describes a *different*, later-started session, which does not. Both findings are true and coexist. The corrected claim: 153 lines removed from disk; benefit unrealized in the session that made the change (`OLD BOTH`); realization on a fresh session **confirmed**. **Label the inference correctly:** marker presence proves the post-edit version is what a fresh session receives — the 153-line figure then follows from combining that with the verified disk line counts, not from counting injected lines directly, which nobody did. This confirmation was obtained from *outside* the session that made the change, which is `D-implementation-plan.md` § The in-session verification limit's own rule being followed, not overridden — that rule still governs how Stages 2–4 must each be checked. An earlier, invalid attempt at this test asked about a *removed* marker in the wrong repository and proved nothing; the corrected design (added marker, correct repository) is recorded in `D-implementation-plan.md` § Amendment 5 for Stages 2–4 to copy. Full evidence: `D-implementation-plan.md` § Amendment 5 (card #3013).

The plan originally promised 357 lines. Measurement cut that to 176, and unit 1.5's proof cut it again to **153**, because **151 lines across both files are needed by every sub-agent and cannot be relocated anywhere** — no available mechanism both reduces context and reliably reaches a background sub-agent — and because a SPLIT section's structural overhead was wrongly counted as relocatable. **Anthropic's 200-line target is unreachable by prompt editing alone.** The hook-enforcement route is the tracked follow-on.

**Do not treat a cap as a quota.** If a unit cannot reach its cap without touching protected or sub-agent-needed content, it must report the achievable floor and the coordinator raises the cap. Never reclassify content to hit a number.

---

## Next action

**START HERE — in this order:**

**1. Tier-1 review of unit 1.5.** Mandatory; prompt files are Tier 1. Model the card on #2993 (unit 1.4's review): state what is already mechanically confirmed — **338** lines (314 at Stage 1's close, plus the user's 24-line `82160b4`, which is out of scope for this review), tripwire 31/31, global file untouched, scope isolation held — and direct the reviewer at what the tripwire structurally **cannot** check: pointer quality, whether content lifted into `~/.claude/docs/` reads coherently arriving cold, silent losses against `.scratchpad/S1-unit-1.5-accounting.md`, and scope creep against decision Q1.

Note for the reviewer: unit 1.4's review found its accounting asserted "no inbound references exist" **in prose without running the search** — it was false and hid a stale pointer. Unit 1.5 was told to write coverage claims as command-and-output pairs. Verify it actually did.

**2. Resolve non-low findings.** Auto-implement blocking / high / medium; surface lows.

**3. `hms`.** The real build gate — `nix flake check` does not run flake8. All Stage 1 destination files are already tracked, so nothing needs staging first, but re-check `git status` in case the review added a file.

**4. Commit any review fixes.** Unit 1.5's own work is already committed; this covers only what the review changes.

**5. ~~Amend Document D for the 291 → 314 correction.~~ ✅ DONE — verified complete 2026-07-28. Do not re-do.** Amendment 3 (card #2999) landed this. Every location this item named was checked: the Stage 1 arithmetic, the unit table (`:376`), the validation gate, `## Recomputed Numbers` (`:1358`), and `## Executive Summary` (`:21`) all carry **450 / 314 / 764 / 153**. The 63 remaining lines mentioning 291 are each preceded by an explicit `⚠ SUPERSEDED BY AMENDMENT 3` callout, per the document's convention of leaving superseded arithmetic standing so corrections stay auditable — they are history, not stale targets. The SPLIT-overhead root cause is recorded in § The SPLIT structural-overhead rule, with the mandatory fourth check for Stages 2–4.

> **⚠ The project-root cap is now 338, not 314** — the user's commit `82160b4` added 24 lines of branching policy. See § AMENDMENT 2026-07-28 near the top of this document, and `D-implementation-plan.md` § Amendment 6. **Stage 1's achieved reduction remains 153; the current net is 129.** Those are different numbers measuring different things — do not substitute one for the other.

**6. Then the two remaining Stage 1 gates:**
   - **Sub-agent injection smoke test — DONE, verdict `OLD BOTH` (card #3004); re-run from a fresh session — DONE, CONFIRMED (card #3013).** Both files were present in the injected `claudeMd` block, but both carried pre-edit content, for the parent session and any sub-agent spawned from it — that verdict stands unchanged. Separately, two sessions started **after** Stage 1's edits landed were each checked for an added marker from those edits and both confirmed presence. See the callout above § Stage 1 numbers and `D-implementation-plan.md` § Amendment 5. This gate is now satisfied for a session started after the edits landed.
   - **Owner soak.** One week of ordinary `staff` and `sstaff` work with no behavioral surprise, **starting from a FRESH session** — not the session that made Stage 1's edits, which would only exercise pre-edit files. **This soak no longer needs to serve as confirmation that a fresh session receives the reduced files — card #3013 settled that separately (see § Stage 1 numbers above).** The soak remains the *behavioral* check: whether the relocated pointers get followed and prove useful in ordinary use, whether any rule reads as having lost force once relocated, and whether anything reads as missing rather than merely moved. **Stage 2 does not open until the owner confirms this.** That gate is theirs, not yours.

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
