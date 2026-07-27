# Document B — Current Configuration

**Status:** descriptive only. This document records what the configuration IS. It does not evaluate whether any rule is good policy and it proposes no changes. Diagnosis belongs to the gap analysis; remedies belong to the plan.

**Written:** 2026-07-27, session `stout-ember`, kanban card #2944.

**Synthesized from seven independent inventory passes**, each produced by a sibling card against a disjoint slice of the corpus:

| Input | Slice characterized |
|---|---|
| `.scratchpad/B1-staff-engineer.md` | `output-styles/staff-engineer.md` (2,918 lines) |
| `.scratchpad/B2-senior-staff-engineer.md` | `output-styles/senior-staff-engineer.md` (3,061 lines) |
| `.scratchpad/B3-shared-layer.md` | global `CLAUDE.md` + the `docs/staff-engineer/` reference set |
| `.scratchpad/B4-swe-agents.md` | the seven `swe-*` sub-agent definitions |
| `.scratchpad/B5-support-agents.md` | debugger, scribe, ai-expert, researcher, qa-engineer, visual-designer, product-ux |
| `.scratchpad/B6-business-and-reference.md` | finance, lawyer, marketing + the operational/CLI-reference skills |
| `.scratchpad/B7-workflow-skills.md` | project-planner, smithers, pr-review, pr-review-watcher, user-voice |

All seven inputs were present and complete. No input was missing, empty, or truncated.

**Amended 2026-07-27, same session `stout-ember`, kanban card #2951**, from two later gap-fill passes that closed known holes in the wave-1 coverage. Everything in this document that is not attributed to B8 or B9 is the original synthesis. § Amendment Log at the very end records exactly what the amendment changed and which input drove each change.

| Amendment input | Slice characterized |
|---|---|
| `.scratchpad/B8-missed-files.md` | the two prompt-bearing files no wave-1 inventory card reached — project-root `CLAUDE.md` and `modules/claude/global/TOOLS-DETAILED.md` |
| `.scratchpad/B9-accretion-history.md` | an empirical test of this document's own accretion hypothesis against git history, answering question (a) of § Accretion Analysis |

Both amendment inputs were present and complete. Neither was missing, empty, or truncated.

**Independent verification performed for the amendment.** B8's structural and technique counts for both newly-covered files were re-derived rather than copied: heading counts (`rg -c '^## '`, `'^### '`, `'^#### '`), siren counts (`rg -o '🚨' | wc -l`), fenced-code-block line counts (`rg -c '^```'`), rule-strength vocabulary line counts, `✅`/`❌` counts, and checklist-item counts. All reproduced exactly except one bold-density figure, which is corrected and flagged in § Authoring Style Profile and in CT-20. B9's commit census was re-derived for `modules/claude/global/CLAUDE.md` (78 total / 12 `claude-improvement:` / 6 other `fix`) and for the `kanban-cli` versus `crew-cli` pair (25/21 and 13/8) — all four figures reproduced exactly — and B9's counter-example commit `607de07` was re-read directly (`git show 607de07 --stat`), confirming both its 2025-09-12 date and its generic bulk-rewrite character. B8's orphan verdict on `TOOLS-DETAILED.md` was re-verified independently: a repo-wide `rg -i 'TOOLS-DETAILED' --glob '!.git' --glob '!.scratchpad' -l` now returns exactly one path — this document — and `fd -i burns`, `fd -i smithers`, and `rg -n 'name = "smithers"|name = "burns"' modules/` corroborate its staleness findings.

**Independent verification performed for this synthesis.** Line counts in § Configuration Inventory were re-derived with `wc -l` rather than copied from the inputs, and the hook/CLI enforcement claims in § Workflow Invariants To Preserve were verified by reading `modules/claude/default.nix`, `modules/kanban/kanban.py`, and the hook scripts directly. Every other number in this document is reported as the inputs measured it, with the source input named.

All paths are relative to `/Users/karlhepler/.config/nixpkgs`. Unless stated otherwise, a citation of the form `filename.md:NNN` refers to the file named in the surrounding sentence or the nearest preceding path.

---

## Executive Summary

This repository holds **24,210 lines of Claude Code configuration across 44 prompt-bearing Markdown files** — 23,869 lines across 43 files in five tiers with fundamentally different injection economics, plus one 341-line orphan that reaches no context at all. **Two** files totalling 917 lines (`modules/claude/global/CLAUDE.md` at 530 and the project-root `CLAUDE.md` at 387) are injected into every session and every sub-agent. Two output styles totalling 5,979 lines convert a session into one of two coordinator tiers. Nine reference documents (2,661 lines) are read on demand by the coordinator. Seventeen sub-agent definitions (8,050 lines) are injected only into the sub-agent each defines. Thirteen skills (6,262 lines) load on demand, except two CLI references that a `SessionStart` hook injects wholesale for the matching coordinator tier. The 341-line `modules/claude/global/TOOLS-DETAILED.md` sits in the corpus tree with no injection path, no deploy rule, and no inbound reference.

The corpus figure of 23,482 lines across 42 files carried by the original synthesis is superseded. It was internally inconsistent: the Tier-1 table listed the project-root `CLAUDE.md` and its tier subtotal counted it, but the grand total did not, and `TOOLS-DETAILED.md` was excluded entirely as uncharacterized. Both files are now characterized (B8), so the full census is used. § Configuration Inventory reconciles the arithmetic line by line.

Four things stand out about how this corpus is authored.

First, it is Markdown all the way down. Across all 44 files the inputs found zero structural XML tags — no `<context>`, `<task>`, or `<instructions>` wrappers anywhere. Every angle-bracket token in the corpus is a CLI placeholder inside a command example. Structure is carried entirely by ATX headings, bold labels, tables, and fenced code blocks. B8 confirmed the pattern holds for both newly-covered files: project-root `CLAUDE.md`'s 8 angle-bracket tokens and `TOOLS-DETAILED.md`'s 2 are all CLI placeholders.

Second, the register is overwhelmingly prohibitive. The two coordinator prompts alone carry roughly 700 negative-framed tokens against roughly 250 affirmative ones, and the `❌`-to-`✅` ratio in the largest file is 2:1 — about half of the "wrong example" callouts have no paired right example. In the seventeen agent definitions, `✅` is close to absent entirely.

Third, the corpus is deliberately self-contained rather than factored. Each agent definition repeats boilerplate its siblings also carry, and repeats guidance the always-injected layer already supplies: 22.8% of the seven `swe-*` files is duplicated text (B4). The project's own documentation states this self-containment is intentional.

Fourth, and most consequentially for a rewrite: a large amount of text exists to defend against a specific past failure. Named-incident citations, per-incident anti-pattern catalogue entries, escalating "no exceptions, ever, period" phrasing, and banned-pattern lists that grew one entry at a time account for an estimated 750–825 lines. **That this content accreted reactively is no longer a hypothesis — B9 tested it against git history and it SUPPORTS, but only file by file, not corpus-wide.** The two coordinator output styles and `kanban-cli/SKILL.md` carry incident-tagged commit fractions of 58.7%, 87.2%, and 88.0% respectively; the always-injected global `CLAUDE.md` carries only 23.1%, so the hypothesis does not hold for the one file every context receives, whose bulk reads as ordinary feature and documentation work. B9 also found one clear counter-example: the 🚨 siren technique originated in a generic bulk-rewrite commit, not an incident. Whether any of this shape is warranted remains undecided here — § Accretion Analysis reports the empirical verdict for question (a) and leaves question (b), whether the resulting form is good practice, explicitly open for the gap analysis.

Fifth, and reasoning from a completely separate basis: the always-injected layer's cost is concentrated in content most sessions do not need. B8 classified the project-root `CLAUDE.md`'s 14 H2 sections by audience breadth and found roughly 317 of 387 lines (~82%) are narrow, task-specific reference material — Nix packaging, shellapp scripting, `hms` workflow mechanics — against B3's roughly 30% narrow-audience share for the global `CLAUDE.md`. This is an argument about relevance distribution in a file every session and every sub-agent pays for, and it stands or falls independently of the accretion question above: text can be perfectly deliberate in origin and still be irrelevant to most of the contexts it is injected into. The two lines of reasoning must not be merged.

Finally, the load-bearing behaviors split unevenly between mechanical and textual enforcement. Some are backed by a hook or CLI validator and cannot be broken by rewording. Others — the review protocol, the user-decision question protocol, draft-first pull requests, the sub-agent return contract — exist only as prose. § Workflow Invariants To Preserve separates the two, because that line determines what a rewrite can silently destroy.

---

## Configuration Inventory

### Tier 1 — Always-injected shared layer

Injected into every session and into every background sub-agent, via the `claudeMd` system-reminder block. Confirmed live: this synthesis session's own context contains both files below.

| File | Lines | Injection |
|---|---|---|
| `modules/claude/global/CLAUDE.md` | 530 | auto-injected, every session + every sub-agent |
| `CLAUDE.md` (project root) | 387 | auto-injected in this repo, every session + every sub-agent |

**Tier total: 917 lines across 2 files.** Both files are now characterized. The original synthesis noted that only the global file was in any input's scope and that the 387-line project file was covered by no inventory card; **that note is obsolete** — B8 characterized the project-root file in full, and its findings appear in § Configuration Inventory (below), § Authoring Style Profile, § Redundancy And Duplication Map (Category 5), and § Tensions And Contradictions.

B8 confirmed the project-root file's Tier-1 status the same way B3 confirmed the global file's — by observing it in its own context. B8 ran as a background `ai-expert` sub-agent dispatched via the Agent tool and received the full text of both files in the leading `claudeMd` system-reminder block, unrequested, before any task instruction (`.scratchpad/B8-missed-files.md:9`). Since a sub-agent is the most stripped-down context in the architecture, receiving it there establishes Tier-1 membership rather than assuming it.

**Structure of the project-root `CLAUDE.md` (387 lines).** 14 H2 sections, 7 H3, 2 H4 — verified independently for this amendment (`rg -c '^## '`, `'^### '`, `'^#### '` → 14 / 7 / 2, matching B8 exactly). The H2 sequence is: NEVER HOMEBREW (:9), macOS Trash CLI (:13), SOURCE OF TRUTH PRINCIPLE (:32), Team Member Terminology (:72), Quick Commands (:106), Critical Requirements (:160), Configuration Structure (:167), Development Workflows (:175), Scripting Principles (:228), File Management (:310), Claude Code Integration (:331), Your Team (:351), Reference Documentation (:355), External References (:378). It carries **zero** `- [ ]` checklist items (verified: `rg -c '^- \[ \]' CLAUDE.md` returns no matches), so the § Authoring Style Profile finding that checklists exist in exactly three files is unaffected by this amendment.

**Relevance breadth — what every context pays for.** Because both Tier-1 files are injected everywhere, every line is a cost paid universally whether or not the session's task touches the subject. B8 classified the project-root file's H2 sections on that axis (`.scratchpad/B8-missed-files.md:33-36`):

| Bucket | Sections | Lines | Share |
|---|---|---|---|
| Broad — applies to essentially any task in this repo | intro/identity (:1-7), SOURCE OF TRUTH PRINCIPLE (:32-70), Critical Requirements (:160-165), Your Team (:351-353) | ≈55 | ~14% |
| Narrow — applies only to a task-specific subset | macOS Trash CLI (:13-30), Team Member Terminology (:72-104), Quick Commands (:106-158), Configuration Structure (:167-173), Development Workflows (:175-227), Scripting Principles (:228-309), File Management (:310-329), Claude Code Integration (:331-349), Reference Documentation (:355-376), External References (:378-387) | ≈317 | ~82% |

The two buckets cover 13 of the 14 H2 sections; the 3-line NEVER HOMEBREW headline at :9-11 sits in neither, so roughly 372 of 387 lines are classified and the remainder is section whitespace. The single largest narrow block is Scripting Principles at 82 lines, which is irrelevant to any session that does not author or review a shellapp or Python script — including every research and review card in this migration effort.

**The contrast with the global file is the load-bearing part.** B3 estimated the global `CLAUDE.md` at roughly 160 of 530 lines (~30%) narrow-audience content; the project-root file is roughly 82% narrow. The smaller file therefore carries proportionally far more per-session dead weight than the larger one it sits beside. **This is an argument about relevance distribution, not about accretion** — see the note in § Accretion Analysis on keeping the two separate. Nothing in B8 or B9 establishes that the narrow content grew reactively, and for the global file B9's evidence points the other way (23.1% incident signal).

### Tier 2 — Coordinator output styles

Loaded as the active output style for the matching launcher (`staff` / `sstaff`); effectively auto-injected for that session type, and absent from every other session type including all sub-agents.

| File | Lines | Injection |
|---|---|---|
| `modules/claude/global/output-styles/senior-staff-engineer.md` | 3,061 | auto-injected for `sstaff` sessions only |
| `modules/claude/global/output-styles/staff-engineer.md` | 2,918 | auto-injected for `staff` sessions only |

**Tier total: 5,979 lines across 2 files.**

Frontmatter is minimal in both: `name`, `description`, `keep-coding-instructions: false` and nothing else (staff-engineer.md:1-5, senior-staff-engineer.md:1-5). Neither declares a `model`, `tools`, or `allowed-tools` field. Model guidance appears in prose (staff-engineer.md:19), not in frontmatter.

### Tier 3 — Coordinator on-demand reference docs

Read on demand by the coordinator when a pointer in `staff-engineer.md` fires. Never auto-injected.

| File | Lines | Inbound pointers from either output style |
|---|---|---|
| `modules/claude/global/docs/staff-engineer/review-protocol.md` | 648 | 2 — staff-engineer.md:1547, :1587 |
| `modules/claude/global/docs/staff-engineer/mov-verification-taxonomy.md` | 641 | 5 — staff-engineer.md:1659, :1665, :1911, :2151, :2917 |
| `modules/claude/global/docs/staff-engineer/parallel-patterns.md` | 417 | 1 — staff-engineer.md:1164 |
| `modules/claude/global/docs/staff-engineer/edge-cases.md` | 366 | **0** |
| `modules/claude/global/docs/staff-engineer/delegation-guide.md` | 261 | 3 — staff-engineer.md:1014, :1109, :1113 |
| `modules/claude/global/docs/staff-engineer/anti-patterns.md` | 136 | 1 — staff-engineer.md:2799 (thin: "Full reference:" only) |
| `modules/claude/global/docs/staff-engineer/card-creation.md` | 76 | 1 — staff-engineer.md:783 |
| `modules/claude/global/docs/staff-engineer/understanding-requirements.md` | 69 | 1 — staff-engineer.md:713 |
| `modules/claude/global/docs/staff-engineer/self-improvement.md` | 47 | 1 — staff-engineer.md:2910 |

**Tier total: 2,661 lines across 9 files.**

Two inventory findings on this tier are load-bearing for the migration. First, `edge-cases.md` (366 lines) has **zero** inbound pointers from either coordinator prompt; B3 verified this with an exhaustive case-insensitive sweep of both output styles. Its only inbound reference in the entire eleven-file set B3 examined is understanding-requirements.md:65, which points at one of its eight scenario sections. The other seven sections — User Interruptions (edge-cases.md:7), Partially Complete Work (:36), Review Disagreement (:71), Iterating on Work (:117), Blocked on External Dependency (:180), Multiple Sessions (:212), Permission Gate (:244) — are reachable from no coordinator prompt at all. Second, the tier is 9 files, not ten; card #2944's own brief described B3 as covering "the ten `docs/staff-engineer` reference files," which is an off-by-one — B3's ten targets were the 9 docs plus global `CLAUDE.md`.

### Tier 4 — Delegatable sub-agent definitions

Each file is injected only into the sub-agent it defines, at spawn. None is visible to the coordinator, and none is visible to any sibling sub-agent.

| File | Lines | Group |
|---|---|---|
| `modules/claude/global/agents/debugger.md` | 938 | support |
| `modules/claude/global/agents/scribe.md` | 700 | support |
| `modules/claude/global/agents/ai-expert.md` | 650 | support |
| `modules/claude/global/agents/swe-frontend.md` | 613 | engineering |
| `modules/claude/global/agents/swe-backend.md` | 590 | engineering |
| `modules/claude/global/agents/researcher.md` | 504 | support |
| `modules/claude/global/agents/swe-sre.md` | 469 | engineering |
| `modules/claude/global/agents/swe-devex.md` | 451 | engineering |
| `modules/claude/global/agents/finance.md` | 423 | business |
| `modules/claude/global/agents/marketing.md` | 416 | business |
| `modules/claude/global/agents/swe-security.md` | 410 | engineering |
| `modules/claude/global/agents/swe-infra.md` | 380 | engineering |
| `modules/claude/global/agents/qa-engineer.md` | 363 | support |
| `modules/claude/global/agents/swe-fullstack.md` | 361 | engineering |
| `modules/claude/global/agents/lawyer.md` | 352 | business |
| `modules/claude/global/agents/visual-designer.md` | 245 | support |
| `modules/claude/global/agents/product-ux.md` | 185 | support |

**Tier total: 8,050 lines across 17 files** — engineering 3,274 (7 files), support 3,585 (7 files), business 1,191 (3 files). These sub-totals match B4's and B5's independently computed figures exactly.

Frontmatter is uniform across all 17: `name`, `description`, `model`, `tools`, `mcp`, `permissionMode`, `maxTurns`, `background`, with the closing `---` at line 11 in every `swe-*` file (B4). All 17 declare `model: sonnet` and `background: true`. Only three content variances exist across the whole tier: `maxTurns` is 105 for swe-frontend.md:9 and swe-backend.md:9 versus 100 for the other five `swe-*` files (B4, unexplained); `maxTurns` is 150 for debugger.md:9, the only file in the corpus carrying an inline comment justifying its value; and researcher.md:5 is the only file omitting `Edit` from `tools`, which B5 confirmed is internally consistent — nothing in researcher.md's body calls Edit.

**Roster reconciliation.** `CLAUDE.md:521` lists `ac-reviewer` in the Support row of the team roster, but no `agents/ac-reviewer.md` exists anywhere in the repository (B5 confirmed with `fd`, zero output). It is referenced only as a `KANBAN_AGENT` sentinel that short-circuits the sub-agent bootstrap (`modules/claude/default.nix:169-174`) and in a leftover cleanup line (`default.nix:1244`). Whether it has an LLM prompt body defined dynamically elsewhere could not be determined from static search.

### Tier 5 — Skills

Mostly on demand via the Skill tool or description-based auto-invocation. Two are exceptions: a `SessionStart` hook injects the full body of `kanban-cli/SKILL.md` for `staff` sessions and `crew-cli/SKILL.md` for `sstaff` sessions, and is a silent no-op for every other session type including all sub-agents (`default.nix:1121-1130`, comment at `default.nix:1122-1126`).

| File | Lines | Injection |
|---|---|---|
| `modules/claude/global/skills/project-planner/SKILL.md` | 1,332 | on demand (Skill tool) |
| `modules/claude/global/skills/smithers/SKILL.md` | 804 | on demand |
| `modules/claude/global/skills/pr-review/SKILL.md` | 705 | on demand |
| `modules/claude/global/skills/user-voice/SKILL.md` | 634 | on demand |
| `modules/claude/global/skills/pr-review-watcher/SKILL.md` | 549 | on demand |
| `modules/claude/global/skills/crew-cli/SKILL.md` | 549 | **auto-injected at SessionStart for `sstaff`** |
| `modules/claude/global/skills/kanban-cli/SKILL.md` | 542 | **auto-injected at SessionStart for `staff`** |
| `modules/claude/global/skills/manage-pr-comments/SKILL.md` | 528 | on demand |
| `modules/claude/global/skills/review-pr-comments/SKILL.md` | 332 | on demand |
| `modules/claude/global/skills/event-driven-investigation/SKILL.md` | 170 | on demand |
| `modules/claude/global/skills/pr-review/review-domains.md` | 60 | inlined by pr-review into specialist prompts |
| `modules/claude/global/skills/agent-browser/SKILL.md` | 37 | on demand |
| `modules/claude/global/skills/pr-review/review-citation-guide.md` | 20 | inlined by pr-review into specialist prompts |

**Tier total: 6,262 lines across 13 files** — workflow skills 4,104 (7 files, matching B7) and operational/reference skills 2,158 (6 files, matching B6). B6 reconciled the skills directory exhaustively: `fd SKILL.md` returned 11 `SKILL.md` files, split 6/5 between B6's and B7's scopes with no file belonging to neither.

Skill frontmatter is markedly less uniform than the agent tier. `pr-review/SKILL.md` declares `name`, `description`, `model`, `argument-hint`, and `allowed-tools`; `user-voice/SKILL.md` declares only `name` and `description`; `crew-cli`, `kanban-cli`, and `event-driven-investigation` declare only `name` and `description`; `manage-pr-comments` and `review-pr-comments` declare `version: 1.0`, which no other skill uses; `agent-browser` declares `allowed-tools` but no `version`. The two `pr-review` supporting files carry no frontmatter at all.

### Unconsumed — prompt-bearing source with no injection path

Deliberately **not** numbered as a sixth tier. Every tier above is defined by which contexts receive its files; this file reaches none, so calling it a tier would misdescribe the architecture. It is nonetheless prompt-shaped Markdown living inside `modules/claude/global/`, so a census that omitted it would understate the corpus a rewrite has to account for.

| File | Lines | Injection |
|---|---|---|
| `modules/claude/global/TOOLS-DETAILED.md` | 341 | **none** — not injected, not deployed, not referenced by any prompt |

**Subtotal: 341 lines across 1 file.**

**Structure (B8).** Only 3 H2 sections across 341 lines — `burns` (:7), `smithers` (:64), `prc` (:159) — plus 4 H3 sections, all four nested under `prc` (`list` :188, `reply` :204, `resolve / unresolve` :219, `collapse` :227). Verified independently for this amendment: `rg -c '^## '` → 3, `rg -c '^### '` → 4. That is one H2 roughly every 114 lines, **the lowest heading density of any prose file in the corpus** — against, for example, self-improvement.md's one H2 per 9 lines and anti-patterns.md's one per 12. Each of the three sections follows an identical template: Purpose → Command → Usage (fenced bash) → Configuration table (`burns`/`smithers` only) → Behavior → Exit Codes → Examples → Related Commands. B8 characterizes this as a reference-manual register rather than a rule or directive register, with mov-verification-taxonomy.md's per-scenario catalogue as its nearest structural analogue in the corpus — though that file documents verification methods and this one documents CLI tools. It carries **zero** `- [ ]` checklist items (verified).

**Orphan verification (B8, re-verified for this amendment).** B8 ran `rg -n -i 'TOOLS-DETAILED' /Users/karlhepler/.config/nixpkgs --glob '!.git' --glob '!.scratchpad'` and got hits in exactly one file: this document, at its own two mentions of the gap. Re-run for the amendment with `-l`, the result is unchanged — one path, this document. B8 additionally ruled out indirect consumption four ways: `fd -e nix . modules --exec rg -l 'TOOLS-DETAILED' {} \;` exits 1 with no output, so no `.nix` file references it; no wildcard `*.md` copy rule exists in `modules/claude/default.nix` that could sweep it up incidentally (the one `*.md` hit at `default.nix:467` is an unrelated comment about `Edit(*.md)` permission syntax); a recursive `rg` across `agents/`, `skills/`, `output-styles/`, and `docs/` returns zero matches; and the sibling it points at is a different file.

**It is hand-authored source, not generated output.** This distinction matters because generated output would be a build artifact rather than a maintenance liability. `TOOLS.md` — the file both TOOLS-DETAILED.md:3 and :341 point outward to — **is** generated: `default.nix:1201-1202` imports `./generate-tools-md.nix`, `default.nix:1204` wraps it in `pkgs.runCommand "TOOLS.md"`, and `default.nix:1280` installs it to `~/.claude/TOOLS.md`. `TOOLS-DETAILED.md` has no generator, no `generate-tools-detailed-md.nix`, and no install or copy rule anywhere (B8). It is hand-written content that nothing builds, deploys, or reads. `~/.claude/TOOLS.md` is itself explicitly **not** injected either (`default.nix:223`: "reference `~/.claude/TOOLS.md` on demand … it is NOT injected into context") — but it is at least deployed and pointed at, which TOOLS-DETAILED.md is not.

Two of its three documented commands have drifted out of sync with what the repository ships; that is recorded as a defect at CT-21 rather than here.

### Grand total and a reconciled discrepancy

**24,210 lines across 44 prompt-bearing files.**

| Group | Files | Lines |
|---|---|---|
| Tier 1 — always-injected shared layer | 2 | 917 |
| Tier 2 — coordinator output styles | 2 | 5,979 |
| Tier 3 — coordinator on-demand reference docs | 9 | 2,661 |
| Tier 4 — delegatable sub-agent definitions | 17 | 8,050 |
| Tier 5 — skills | 13 | 6,262 |
| **Five-tier subtotal** | **43** | **23,869** |
| Unconsumed (`TOOLS-DETAILED.md`) | 1 | 341 |
| **Total** | **44** | **24,210** |

All five tier subtotals were re-derived with `wc -l` for this amendment and each matches the figure in its tier table above.

**Three superseded or reconciled figures, recorded so no reader treats them as conflicts.**

First, **the original synthesis's 23,482 lines across 42 files is superseded, and it was internally inconsistent.** 23,869 − 387 = 23,482 and 43 − 1 = 42: the grand total silently excluded the project-root `CLAUDE.md` even though the Tier-1 table listed it and the Tier-1 subtotal of 917 counted it. `TOOLS-DETAILED.md` was excluded from both. With B8 closing both gaps there is no longer any reason to exclude either, so this document now uses 24,210 across 44 files throughout.

Second, **card #2944's stated intent gives the corpus as 23,402 lines**, which is the original 23,482 minus `pr-review/review-domains.md` (60) and `pr-review/review-citation-guide.md` (20) — the two non-`SKILL.md` supporting files. Both are genuinely prompt-bearing: `pr-review/SKILL.md:398` inlines them into every specialist delegation prompt, so this document counts them. Relative to the corrected 24,210 figure, the card's number is short by those 80 lines plus the 728 lines of the two files B8 has now characterized.

Third, **the "728 lines, 3.1% of the corpus" figure the original synthesis used for the two uncovered files is arithmetically restated, not withdrawn.** 387 + 341 = 728 remains correct; as a share of the corrected 24,210-line total it is 3.0%, not 3.1%. The difference is immaterial to any conclusion and is recorded only for traceability.

---

## Architecture Of The System

### The five tiers and who sees what

The architecture is a layered injection model, not a call graph. Nothing in the corpus imports anything else at runtime; a file either arrives in a context window or it does not.

**Every context** — coordinator or sub-agent — receives Tier 1: global `CLAUDE.md` (530 lines) and project `CLAUDE.md` (387 lines). That is the only content guaranteed to be present everywhere.

**A `staff` session** additionally receives `staff-engineer.md` (2,918 lines) as its output style and `kanban-cli/SKILL.md` (542 lines) via the `SessionStart` autoload hook. It can reach the nine Tier-3 reference docs on demand by following a pointer, and can invoke any skill.

**An `sstaff` session** additionally receives `senior-staff-engineer.md` (3,061 lines) and `crew-cli/SKILL.md` (549 lines) by the same mechanism. It does not receive `staff-engineer.md`, which matters because senior-staff-engineer.md:347, :851, :928, :930, :1192, :1323, :1650, :2379, :2414-2416, :2428, :2535, :2914, :2939 all cross-reference sections of `staff-engineer.md` by name — sixteen references, per B2 — to a file the `sstaff` context does not contain.

**A sub-agent** receives Tier 1, its own single agent definition from Tier 4, and the kanban card XML injected by a `PreToolUse(Agent)` hook. That is all.

### What a sub-agent does NOT receive

This is the sharpest structural fact in the architecture, and the source of several defects catalogued in § Tensions And Contradictions.

A background sub-agent does **not** receive: either coordinator output style; any of the nine Tier-3 reference docs; any sibling agent definition; the `kanban-cli`/`crew-cli` skill bodies (the autoload hook is a documented no-op for sub-agents, `default.nix:1126`); the auto-generated `TOOLS.md`; `TOOLS-DETAILED.md`, which no context receives (B8); or access to any MCP server. The MCP constraint is stated unconditionally in the always-injected layer, which also notes that the `mcp: - context7` frontmatter field present in all 17 agent definitions is informational only and wires nothing.

Two consequences follow directly. First, the 7-field sub-agent return contract specified at staff-engineer.md:1016-1078 reaches the sub-agent only because the coordinator pastes it verbatim into the delegation prompt — no agent definition carries it (B4, B5 both confirm across all 17 files). Second, every instruction in the agent tier telling an agent to query Context7 itself is unsatisfiable as written.

### How work is dispatched and verified, end to end

1. **Card creation.** The coordinator authors kanban cards via the `kanban` CLI. Structural validation happens in the CLI, not in the prompt: `modules/kanban/kanban.py:734-736` requires a non-empty `mov_commands` array for any programmatic criterion and forbids one for a semantic criterion; `kanban.py:827`, `:836`, `:844` require a `cmd` and a valid `timeout` per command; `kanban.py:1419-1420` catches the `movCommands`-instead-of-`mov_commands` typo with an actionable error rather than passing silently.
2. **Banned-pattern validation.** `kanban.py:1258-1276` validates every `mov_commands[].cmd` against a banned-pattern list — backslash-pipe, AND-chain, `rg -E`, absence-via-count, hook-skip flags. `kanban.py:1376` makes `&&` a hard prohibition in MoV commands. `kanban.py:1236` detects the capital `-E` flag specifically. A card that violates these does not get created.
3. **Conflict-aware scheduling.** `kanban.py:1818` and `:1848` defer a card back to `todo` when its `editFiles` set collides with an in-flight card owned by another session, printing the conflicting path and card number. This is CLI behavior, not coordinator judgment.
4. **Launch.** The coordinator issues one Agent tool call per card. A `PreToolUse(Agent)` hook (`default.nix:1030-1038`) injects the card XML into the sub-agent prompt and, per `kanban-pretool-hook.py:1060-1094`, denies foreground launches — injecting `run_in_background: true` via `updatedInput` rather than validating the incoming value, precisely because the value was observed being serialized as the string `"true"` and then dropped before the hook ran.
5. **Sub-agent execution.** The sub-agent works and calls `kanban criteria check` per criterion. `kanban-subagent-cmd-hook.py:392`, `:496` deny every other kanban subcommand from a sub-agent context.
6. **Verification.** On `SubagentStop`, four hooks fire in order (`default.nix:991-1010`), including `kanban-subagent-stop-hook` with a 600-second timeout, described at `default.nix:350` as running "dual-loop AC review via haiku before allowing agent stop." Card closure is driven by this hook, not by the coordinator — edge-cases.md:38 makes the same point in prose, though buried mid-paragraph under a heading that does not signal it.
7. **Review.** The coordinator then runs the mandatory review protocol (staff-engineer.md:1472-1526, review-protocol.md:7-68) and the post-review learning pass (staff-engineer.md:1589-1630). This step has no hook or CLI backstop whatsoever.

### Session bootstrap

`SessionStart` runs four hooks (`default.nix:1102-1132`): `claude-session-start-hook` (which pipes session JSON through `kanban session-hook` at `default.nix:190` and `perm session-hook` at `default.nix:214`), `senior-staff-cron-hook`, `crew-lifecycle-hook` (drops a readiness sentinel so `crew create --tell` can wait deterministically), and `skill-autoload-hook`. A `PostCompact` hook (`default.nix:1133-1148`) re-injects the full kanban board state after compaction. A reader should conclude that session identity, board state, and CLI-reference availability are all mechanically guaranteed and require no prompt text at all.

---

## Authoring Style Profile

Every count below is reported as the named input measured it. Where two inputs measured the same thing differently, both numbers appear with the discrepancy flagged. Where an aggregate is impossible because inputs used incompatible metric definitions, that is stated rather than papered over.

### Delimiter style and XML-tag usage

**Zero structural XML tags exist anywhere in the corpus.** All seven inputs checked independently and all seven reached the same conclusion. B1 found 161 angle-bracket tokens in staff-engineer.md and confirmed every one is a literal placeholder inside an example payload (`<PR_NUMBER_OR_URL>` at staff-engineer.md:530), not a document-structuring element. B2 found 269 such tokens in senior-staff-engineer.md, grepped explicitly for `<context>`, `<task>`, `<example>`, `<instructions>`, `<system>`, `<thinking>`, and got zero matches. B3 found non-zero angle-bracket counts in 7 of 10 files (CLAUDE.md 12, delegation-guide.md 10, card-creation.md 8, mov-verification-taxonomy.md 4, anti-patterns.md 2, review-protocol.md 1, parallel-patterns.md 1) and confirmed all are CLI placeholders. B4 found the same across all seven `swe-*` files, with the higher counts in swe-frontend.md:355-374 traceable to HTML inside embedded code examples. B7 counted 40/162/62/163/0 across its five files and sampled the tokens: `<slug>`, `<PR>`, `<pr>`, `<repo>`, `<number>`. B8 extends the finding to both newly-covered files and it holds there too: project-root `CLAUDE.md` has 8 angle-bracket tokens (`<branch>`, `<file>`, `<id>`, `<name>`, `<new-files>`, `<package-name>`, `<package>`, `<pattern>` — e.g. `which <package-name>` at CLAUDE.md:190) and `TOOLS-DETAILED.md` has 2 (`<comment-id>` at :176, `<thread-id>` at :179). All ten are CLI-usage placeholders, the same false-positive shape B3 documented for delegation-guide.md's `<your-session-id>`. Neither file uses XML tags as a structuring device. **With B8's pass complete, the zero-structural-XML finding now covers all 44 files with no remaining unexamined file.**

The one partial exception is instructive: ai-expert.md:186, :192, :196, :203, :261, :266, :271, :277 contain eight XML tags — but only inside worked examples demonstrating how a *third-party* prompt should be structured. The file that teaches XML-tag prompting does not itself use XML-tag prompting.

Structure is therefore carried entirely by ATX headings, bold labels, tables, and fenced code blocks. Heading counts: staff-engineer.md has 103 heading lines (1 H1, 30 H2, 63 H3, 9 H4); senior-staff-engineer.md has 144 (1 H1, 39 H2, 70 H3, 34 H4). Both inputs independently flagged the same methodological hazard — raw `rg '^# '` over-counts because bash and Python comments inside fenced code blocks match. B1 found two false positives at staff-engineer.md:2454 and :2457; B2 found 13 of 14 raw `^# ` hits were bash comments (senior-staff-engineer.md:731, :1472-1482, :1551-1559).

Non-heading delimiters: `card-creation.md` has zero `##`/`###` headings anywhere in its 76 lines, organizing purely by bold lead-sentences (B3). `kanban-cli/SKILL.md:279` is the only file in B6's set using blockquote-as-emphasis. `debugger.md:489-491` uses HTML-comment sentinels (`<!-- END ASSUMPTIONS -->`) — but for the ledger file the agent produces, not for its own body.

### ALL-CAPS, bold, and emoji-siren emphasis

**Bold is the dominant technique everywhere, by a wide margin.** staff-engineer.md has 880 bold spans across 772 distinct lines — 26.5% of all lines contain at least one (B1). senior-staff-engineer.md has 832, of which 328 are the colon-terminated label form `**Label:**` (B2). project-planner/SKILL.md has 381 bold spans in 1,332 lines, the highest density in the corpus at 0.286 per line versus pr-review's 0.167 (B7).

**Metric-definition inconsistency, flagged.** B1 and B2 and B7 counted bold *occurrences*; B4 counted *lines containing* bold; B3 counted occurrences via `rg -co`. These are not the same measure and cannot be summed into a corpus total. The per-file figures below are reported in whichever unit their input used.

Bold by file: CLAUDE.md 120, review-protocol.md 103, edge-cases.md 80, parallel-patterns.md 69, mov-verification-taxonomy.md 61, anti-patterns.md 43, delegation-guide.md 42, understanding-requirements.md 29, card-creation.md 19, self-improvement.md 11 (B3, occurrences). swe-devex.md 87, swe-sre.md 74, swe-security.md 69, swe-frontend.md 64, swe-infra.md 53, swe-backend.md 41, swe-fullstack.md 38 (B4, lines). smithers 158, pr-review-watcher 139, pr-review 118, user-voice 114 (B7, occurrences).

**B8's two bold figures are in different units from each other, so they are reported here corrected rather than as stated.** This is the one place in the amendment where an input's number did not reproduce, and it is recorded in full because the card that commissioned this amendment required exactly this discipline — aggregate only what shares a convention.

B8 reports "bold-span raw counts (`rg -co '\*\*'`): `CLAUDE.md` (project root) = 150; `TOOLS-DETAILED.md` = 47" (`.scratchpad/B8-missed-files.md:56`). Re-derived for this amendment:

| File | `rg -co '\*\*'` (delimiters) | `rg -co '\*\*[^*]+\*\*'` (spans) | `rg -c '\*\*'` (lines) | `rg -c '^\*\*'` (line-start) | `rg -co '\*\*[^*]+:\*\*'` (label form) |
|---|---|---|---|---|---|
| `CLAUDE.md` (project root, 387 lines) | **150** | 75 | 71 | 50 | 41 |
| `TOOLS-DETAILED.md` (341 lines) | 110 | 55 | 55 | **47** | **47** |
| `modules/claude/global/CLAUDE.md` (530 lines) | 242 | **120** | 113 | — | 51 |

Three things follow. **(1)** B8's 150 for the project-root file is a `**` *delimiter* count — two per bold span — so the span figure is 75. **(2)** B8's 47 for `TOOLS-DETAILED.md` reproduces under neither the delimiter count (110) nor the span count (55), but reproduces exactly under both line-start-bold and colon-label-bold. Its two figures are therefore not the same measure, and the per-line normalization B8 derives from them is not a like-for-like comparison. **(3)** B8 states that B3's 120 for the global `CLAUDE.md` is a "raw bold-mark" count and treats its own 150 as directly comparable to it. That is not right either: 120 reproduces exactly as a *span* count and not at all as a delimiter count (242). B3's unit is spans, which places B3 in the same class as B1, B2, and B7 — not in a separate `rg -co`-delimiter class as the flagged note above implies.

**Corrected like-for-like, all three files as spans per line:** global `CLAUDE.md` 120/530 = **0.226**; project-root `CLAUDE.md` 75/387 = **0.194**; `TOOLS-DETAILED.md` 55/341 = **0.161**. B8's directional conclusion that `TOOLS-DETAILED.md` is the sparsest of the three **survives** the correction. Its conclusion that "project-root `CLAUDE.md` is the most bold-dense of the three files in this comparison" **does not** — the global file is denser. And the ordering is convention-dependent rather than robust: under the colon-label-form convention it inverts entirely, giving `TOOLS-DETAILED.md` 0.138/line against project-root 0.106 and global 0.096, making the supposedly sparsest file the densest. Any claim about relative bold density in this corpus should name its convention. Recorded as an addition to CT-20.

**Siren counts for both newly-covered files (B8, verified).** Project-root `CLAUDE.md` has **8** 🚨 markers across 5 lines (:9, :13, :32, :177, :185 — three of them paired sirens in headers); `TOOLS-DETAILED.md` has **zero** anywhere in its 341 lines. Both figures reproduce exactly. This makes the project-root file the third-heaviest siren user in the corpus, behind staff-engineer.md (20) and the global `CLAUDE.md` (11, measured for this amendment), and ahead of senior-staff-engineer.md (2).

**The 🚨 siren is concentrated almost entirely in two places.** staff-engineer.md has 20; senior-staff-engineer.md has 2 — a tenfold density difference between the two coordinator tiers that B2 flagged as a deliberate stylistic divergence, not merely a quantity difference. In the shared layer, 🚨 appears in CLAUDE.md (including CLAUDE.md:8, :372, :387), review-protocol.md:2, and card-creation.md:1, and in **zero** of the other seven Tier-3 docs (B3). In the agent tier it is near-vestigial: exactly one occurrence per `swe-*` file, and in all seven cases it is the identical Output Protocol line (swe-frontend.md:610, swe-backend.md:587, swe-sre.md:466, swe-devex.md:448, swe-security.md:407, swe-infra.md:377, swe-fullstack.md:358). Among support agents: ai-expert 3, debugger 1, scribe 1, researcher 1, qa-engineer 1, visual-designer 0, product-ux 0 (B5). Among B6's nine files, 🚨 appears exactly twice, both in kanban-cli/SKILL.md (line 31 heading and line 279 inline) and zero times in the three business agents or the other five skills. Among B7's five files: pr-review 3, project-planner 2, smithers 1, pr-review-watcher 0, user-voice 0.

Corpus estimate: roughly 50 siren markers total, with about 43% of them inside the two coordinator output styles plus the shared layer. **Revised for the amendment: roughly 58 markers**, since B8 adds 8 from the project-root `CLAUDE.md` and 0 from `TOOLS-DETAILED.md`. The concentration is sharper than the original figure implied: Tier 1 alone now accounts for 19 sirens (global 11 + project-root 8) and the two output styles for 22, so 41 of roughly 58 — about 71% — sit in the always-injected layer plus the two coordinator prompts, and the remaining ~17 are spread thinly across 41 files.

**ALL-CAPS is pervasive but not cleanly measurable.** B4's `rg -o '\b[A-Z]{3,}\b'` gave swe-security.md 182, swe-infra.md 128, swe-sre.md 113, swe-backend.md 94, swe-frontend.md 92, swe-devex.md 78, swe-fullstack.md 74 — and then correctly noted the count conflates emphasis-caps with domain acronyms (OWASP, CVSS, NIST, SOC 2, PCI DSS, STRIDE, SAST/DAST), so swe-security.md's outlier status is an artifact of vocabulary, not shouting. B1 declined to count ALL-CAPS in staff-engineer.md for the same reason.

### MUST / NEVER / ALWAYS / MANDATORY vocabulary

**No file in the corpus declares an RFC-2119-style vocabulary convention.** B1 and B2 both checked explicitly and both found no such declaration.

staff-engineer.md, case-sensitive (B1): MUST 66, NEVER 21, ALWAYS 5, MANDATORY 60 (case-insensitive), CRITICAL 26 (case-insensitive), SHOULD 4.
senior-staff-engineer.md, case-sensitive (B2): MUST 53, NEVER 23, ALWAYS 2, and **zero** bare all-caps `MANDATORY` or `CRITICAL` — that file reaches the same register through title-case section names plus bold.

**Discrepancy, flagged.** B2's comparison table reports staff-engineer.md as MUST 159, NEVER 154, ALWAYS 73, DO NOT 150 — measured case-insensitively — against B1's case-sensitive 66/21/5. These are different metrics rather than contradictory measurements, but the two inputs do not label the difference clearly, and a reader combining them would double-count. Both sets are reported here; neither is averaged.

Shared layer, line counts (B3): CLAUDE.md MUST 6, NEVER 9, ALWAYS 2 — the highest concentration of all three per line in the entire Tier-3 set, consistent with its role as the hard-constraint layer (CLAUDE.md:29 "NEVER skip hooks", CLAUDE.md:56 "NEVER run without explicit user approval"). Across the nine docs: review-protocol.md MUST 3 / ALWAYS 1; delegation-guide.md MUST 2; parallel-patterns.md MUST 2; understanding-requirements.md, anti-patterns.md, edge-cases.md MUST 1 each; card-creation.md and self-improvement.md NEVER 1 each. **mov-verification-taxonomy.md uses none of the three across 641 prescriptive lines**, favoring "Rule of thumb" table phrasing instead (mov-verification-taxonomy.md:18).

**The two newly-covered files sit at opposite extremes of this axis (B8, all figures verified as matching-line counts, B3's convention).** Project-root `CLAUDE.md`: MUST 1 (:162, "MUST be installed at"), NEVER 8 (:9, :13, :34, :110, :164, :185, :201, :232), ALWAYS 0. `TOOLS-DETAILED.md`: MUST 0, NEVER 0, ALWAYS 0 — **it contains no rule-strength vocabulary of any kind across 341 lines**, which is consistent with its reference-manual register and matches the pattern B3 found in mov-verification-taxonomy.md. Two observations follow. First, the project-root file is `NEVER`-only: it reaches for the strongest available marker 8 times and never uses `ALWAYS` or a graduated middle term, so its `NEVER` density (8 over 387 lines) is marginally higher than the global file's (9 over 530) — the always-injected layer's prohibitive register is therefore slightly *more* concentrated in the smaller of its two files, not less. Second, `TOOLS-DETAILED.md` joins mov-verification-taxonomy.md as the second file in the corpus that is entirely prescription-free by this measure.

Agent tier (B4, B5): the vocabulary is essentially absent as an authoring choice. Every `swe-*` file has exactly one case-sensitive `MUST` — the `.kanban/` hard rule at line 19 — and exactly one `ALWAYS`, the "(ALWAYS read this)" parenthetical. `NEVER` is inconsistent: zero in swe-frontend, swe-backend, swe-security, swe-fullstack; one in swe-sre.md:78 and swe-devex.md:78; three in swe-infra.md (:80, :82, :94). Support agents: ai-expert MUST 3 / ALWAYS 2, debugger NEVER 1 / MUST 1, scribe MUST 1 / ALWAYS 1, researcher MUST 1, qa-engineer MUST 1, visual-designer MUST 1, **product-ux zero**.

**Consistency verdict.** The vocabulary is internally consistent but effectively single-tier. `SHOULD` appears 4 times in staff-engineer.md and is never used as a deliberate weaker marker, so B1 concluded there is no graduated system to audit — the absence of a middle tier is itself the finding. senior-staff-engineer.md is the only file with meaningful `SHOULD` (63) and `MAY` (39) usage, and B2 flagged one soft inconsistency there: `MUST NOT` (12 uses) and plain `NEVER` (senior-staff-engineer.md:41 "Never use the Agent tool") are used interchangeably for identical rule strength with no stated rule for choosing between them.

### Prohibition-to-affirmative ratio

staff-engineer.md (B1): 305 explicit negative-framing tokens — `do not` 150, `don't` 41, `prohibited` 17, `banned` 20, `forbidden` 3, `❌` 74. Against those, `✅` 36. **The ❌:✅ ratio is roughly 2:1**, meaning about half of all wrong-example callouts lack an adjacent right-example counterpart; staff-engineer.md:238-239 is a cited instance where two ❌ bullets have no matching ✅ and the correct behavior appears only in preceding prose at :225.

senior-staff-engineer.md (B2): 395 negative tokens (NEVER 186, DO NOT 138, MUST NOT 12, prohibit/forbid/banned 59) against 153 affirmative (MUST 110, ALWAYS 43) — **roughly 2.6:1 negative**.

Shared layer (B3): CLAUDE.md is the corpus's most balanced file at 12 ❌ / 11 ✅, near 1:1. card-creation.md is the only ✅-weighted file at 3 ❌ / 7 ✅. parallel-patterns.md (3 ❌ / 0 ✅) and self-improvement.md (5 ❌ / 0 ✅) are negative-only. Six of the nine docs use neither glyph, relying on `// WRONG` / `// RIGHT` code comments instead (mov-verification-taxonomy.md:597, :602).

**The two Tier-1 files diverge sharply on this axis (B8, verified).** Project-root `CLAUDE.md` is 8 ❌ / 3 ✅ — roughly **2.7:1 negative**, close to senior-staff-engineer.md's 2.6:1 and nowhere near the near-1:1 balance of the global file it sits beside. Its paired CORRECT/WRONG package-installation examples at CLAUDE.md:192-204 are the clearest instance of the device. `TOOLS-DETAILED.md` uses **neither glyph anywhere** — 0 ❌ and 0 ✅ across 341 lines. So the original synthesis's observation that the global `CLAUDE.md` is the corpus's most balanced file survives, but it is not a property of the always-injected layer as a whole: the layer's two files are 1.1:1 and 2.7:1 respectively, and a reader who generalized from the global file alone would misjudge the register of the 387 lines injected alongside it.

Agent tier: the ratio collapses. Every `swe-*` file has exactly 4 ❌ and all 28 instances corpus-wide are the same inherited "Concrete examples of what NOT to do" boilerplate block (B4, e.g. swe-frontend.md:65-71) — no `swe-*` file's own domain content employs the device independently. Across the seven support agents, **`✅` appears zero times** (B5): ❌ appears 3× in debugger.md (:67, :69, :71) and 4× in qa-engineer.md (:65, :67, :69, :71), with no paired affirmative glyph anywhere. Outside the boilerplate, negative framing takes three further unmarked forms: bare bullet lists of bad practices (swe-infra.md:249-260), the words "Bad:"/"Good:" (swe-sre.md:422-425), and prose "Issues:"/"Improvements:" headers (scribe.md:174-260).

kanban-cli/SKILL.md is the corpus's one systematically symmetric file: 23 ❌ markers, each paired with exactly one ✅ fix (kanban-cli/SKILL.md:41-42, :49-50), across roughly 14 catalogue entries — though B6 notes the document *structure* remains negative-first, naming the banned pattern before the fix in every case.

### Example usage and do/don't pairing

`Worked example` as a labeled callout appears 17 times in staff-engineer.md (B1: :1286, :1731, :1782, :1792, :1797, :1802, :1816, :1889, :2877 among them) and 8 times in senior-staff-engineer.md (B2: :765, :808, :1222, :2622, :2783, :2831). B2 additionally found 3 `Counter-example` callouts (senior-staff-engineer.md:305, :307) and concluded that in that file **most examples are single-sided** — only the failure case is shown (senior-staff-engineer.md:1286, :1718, :1850) — so few-shot pairing is the exception there, not the norm.

Code-fence distribution is highly uneven. Tier-3 blocks (B3, `^```` lines ÷ 2): review-protocol.md ~20, mov-verification-taxonomy.md ~17, parallel-patterns.md ~17, edge-cases.md ~15, CLAUDE.md ~11, card-creation.md ~4, delegation-guide.md ~4; **anti-patterns.md, understanding-requirements.md, and self-improvement.md have zero**, relying entirely on prose failure narratives. Agent tier (B4): swe-backend 4 blocks, swe-fullstack 4, swe-frontend 3, swe-security 1 — and **swe-sre, swe-devex, and swe-infra have zero fenced code examples**, despite swe-infra's Terraform/Kubernetes domain being at least as code-amenable as swe-backend's. B7: project-planner 30 fence lines, smithers 54, pr-review 38, pr-review-watcher 8, **user-voice 0**. B8, verified: project-root `CLAUDE.md` 14 fence lines (~7 blocks) and `TOOLS-DETAILED.md` 22 (~11 blocks). Normalized, `TOOLS-DETAILED.md`'s 0.065 fence lines per line is nearly double the project-root file's 0.036, which is consistent with it being almost entirely worked CLI invocations — a Usage block and an Examples block per command (:14-23, :44-56) — rather than prose directives. The project-root file's own example use is narrower but sharper: its CORRECT/WRONG Nix-versus-Homebrew pair at CLAUDE.md:192-204 and its ❌-fallback-chain versus ✅-assume-dependencies pair in Scripting Principles (:265-296) are genuine two-sided do/don't pairs, the pattern B2 found to be the exception rather than the norm in senior-staff-engineer.md.

The heaviest example user in the corpus is project-planner/SKILL.md, where two full worked examples (`SKILL.md:984-1131`, `:1132-1241`) reproduce the entire six-heading framework — 258 of 1,332 lines, 19%, and B7 characterizes roughly 45% of the file (lines 984-1241 in context) as worked-example repetition of a skeleton stated abstractly earlier rather than new instruction.

Full Before/After example pairs appear in only three support agents (B5): scribe.md:161-651 (three examples), ai-expert.md:169-536 (three), researcher.md:180-431 (one large). **visual-designer.md and product-ux.md contain no worked examples of any kind** — zero Before/After pairs, zero glyph lists.

### Incident-anecdote footprint

This technique is unevenly but heavily used, and the concentration pattern matters more than the totals.

staff-engineer.md (B1): 4 `Real incident` markers (:1820, :1824, :1826, :2181), 2 `A real failure` (:2434, :2478), and **9 distinct `PLA-####` incident identifiers cited 13 times**. `PLA-1124` alone is cited five times (:1381, :2136, :2354, :2368, :2432) — and B1 verified these are five *different* lessons extracted from one multi-card session, not five restatements of one lesson. Estimated prose footprint 45–55 lines, 1.5–1.9% of the file, concentrated almost entirely inside `## Card Management` (staff-engineer.md:1631-2608).

senior-staff-engineer.md (B2): 7 `Real incident` markers, each naming a session — sharp-trail (:305), true-frost (:335), a pulse-miss (:789), a concurrent-PR-attribution incident (:1718), fair-flame (:1850, and again at :2264), a `/deliver` incident (:1912) — plus unlabeled narrations at :214 and :2993. Estimated 60–80 lines, ~2%. B2 adds a structural observation that raises the real weight considerably: each anecdote anchors 1–3 paragraphs of generalized rule extracted from it, so influence exceeds line count.

anti-patterns.md is the densest file in the corpus by this measure: nearly all of its ~40 bullets follow a bold-name / em-dash / `Concrete failure:` micro-pattern (anti-patterns.md:28, :35, :39, :42), giving 11 H2 sections in 136 lines — one heading every 12 lines (B3).

kanban-cli/SKILL.md carries 5 named citations (`kanban-cli/SKILL.md:180` card #2457, `:189`, `:209`, `:220` PLA-3559 card #9, `:226`) and B6 quantified its defensive fraction precisely: the `🚨 MoV Authoring Banned Patterns` section spans lines 31-254, **223 of 542 lines — 41% of the file**. Its sibling `crew-cli/SKILL.md` is at roughly 3% by the same measure (~15-20 of 549 lines: `crew-cli/SKILL.md:10`, `:62-67`, plus scattered asides at `:48`, `:63`, `:395`) — a 13-fold asymmetry between two files of near-identical length and near-identical purpose.

The agent tier is nearly anecdote-free: exactly one incident writeup across all seven `swe-*` files (swe-infra.md:311, the ArgoCD `oncePer` de-dup key finding) and exactly one across all seven support agents (ai-expert.md:418, the `run_in_background` string-serialization failure). Zero across the three business agents and zero across `crew-cli`, `manage-pr-comments`, `review-pr-comments`, and `agent-browser` (B6).

**Both newly-covered files are anecdote-free, and for the project-root `CLAUDE.md` that is a load-bearing negative result.** B8 found no incident anecdotes of its own in the project-root file — it is procedural and reference in register, unlike anti-patterns.md, which is built almost entirely from `Concrete failure:` bullets — and none at all in `TOOLS-DETAILED.md`, whose 341 lines are Purpose/Usage/Behavior documentation throughout. The project-root result matters because this file is one of only two the whole corpus receives unconditionally: the incident-anecdote technique, which § Accretion Analysis treats as the corpus's clearest accretion signature, is **absent from the layer every context pays for** and concentrated in the tiers only one session type sees. B9's commit census points the same way independently — see § Accretion Analysis, where the always-injected layer is the one census target whose history does not read as incident-driven.

user-voice/SKILL.md is a different species of the same technique: it is built from **quoted verbatim user corrections** (`SKILL.md:49` "Karl: 'I NEVER SAY "HONEST"! I HATE IT!'", `:57`, `:58-59`), one per banned phrase, across the Hard Avoids section at `SKILL.md:32-117`.

### Checklist design

Checklists exist in exactly three files in the entire corpus, all in Tier 1 and Tier 2.

staff-engineer.md has 61 `- [ ]` items total (B1), split across `## PRE-RESPONSE CHECKLIST (Planning Time)` at :474-511 (38 lines, 22 items), `## BEFORE SENDING (Send Time)` at :512-537 (26 lines, 17 items), and 22 more scattered items. senior-staff-engineer.md has 25 items across the same two section names at :476-505 (30 lines) and :506-525 (20 lines). CLAUDE.md has a 5-item "Before EVERY Task" checklist at CLAUDE.md:11-20.

The design intent is compression-by-pointer, and it mostly holds: senior-staff-engineer.md:512 reads "Zero tmux, ever. See § Hard Rule 9." and :513 "See § Hard Rule 12." — index entries, not duplicates. B1 identified three staff-engineer.md items that break the pattern by restating substantive content instead of pointing: :503 (the full backslash-pipe explanation), :524 (re-explains the ripgrep regex-engine mechanism), and :527 (restates the entire banned-phrasing list inline).

**No agent definition and no skill contains a checklist section.** All four of B4/B5/B6/B7 report none.

### Output-format specification

The corpus specifies output formats in four structurally different ways.

**Plain-text labeled fields, coordinator tier.** `### Final Return Format (REQUIRED — sub-agent instruction)` at staff-engineer.md:1016-1078 is the most rigorously specified format in the corpus: a 7-field block (`Status`, `AC`, `Findings`, `Scratchpad`, `Commits`, `Blocker`, `Notes`) given as a literal blockquoted template at :1020-1034 that the coordinator is told to paste VERBATIM, plus a card-type applicability table at :1038-1044 and three worked examples at :1047-1077. senior-staff-engineer.md:1365 carries the analogue. B1 noted that the contract is neither XML nor JSON, matching the corpus-wide avoidance of XML scaffolding even where a machine-checkable contract is being defined. B1 also observed that the delegation prompt spawning that very review used a near-identical 7-field format — direct evidence the pattern is live.

**Reusable prose templates.** review-protocol.md:263-336 defines five named result formats (APPROVE, APPROVE WITH SUGGESTIONS, APPROVE WITH MINOR FIX, CHANGES REQUIRED, BLOCK) as fenced templates, plus a prompt-file-review variant at :494-514. It is the only Tier-3 file that does this (B3).

**Literal JSON schemas.** pr-review/SKILL.md:478-485 (aggregated review), :239-292 (kanban card array); pr-review-watcher/SKILL.md:105-120 (state file). smithers/SKILL.md:50-53 uses flag-file paths and shell test/set/clear commands as its state format instead of JSON. B8 adds a fourth: `TOOLS-DETAILED.md:246-267` defines a literal reusable JSON output schema for `prc list`, enumerating 19 fields (`id`, `node_id`, `type`, `author`, `author_type`, `is_bot`, `body`, `body_text`, `created_at`, `updated_at`, `is_minimized`, `minimized_reason`, `url`, `path`, `line`, `thread_id`, `is_resolved`, `in_reply_to_id`, `reply_count`) — the same named-literal-template technique review-protocol.md uses for its five result formats. It is the most rigorously specified output contract in the corpus that **no context ever receives**, which is a fair summary of that file's whole situation.

**Neither Tier-1 file specifies an output format.** The project-root `CLAUDE.md`'s only structured-output content is configuration snippets — the Nix package examples at :193-199 and the `runtimeInputs`/`writePython3Bin` examples at :265-296 — not runtime output schemas (B8). So the 7-field sub-agent return contract's total absence from the always-injected layer, already recorded at CT-3 for the agent tier, extends to Tier 1 as well: no file that every context receives states any return format at all.

**Domain-facing output blocks, business tier.** finance.md:131-142 mandates a `## Sources` block with Primary/Secondary subsections; lawyer.md:235-254 mandates `## Legal Authorities / Sources` with four named tiers; marketing.md has no equivalent, defining "Success Criteria" (marketing.md:373-384) as a self-check instead. B6 flags that all three also carry a *separate* `Output Protocol` meta-section (finance.md:386-424, marketing.md:385-417, lawyer.md:328-352) governing the return to the coordinator, and that the two are easy to conflate on a skim.

The tier-4 picture is the notable one: **zero of the 17 agent definitions specify the 7-field format**, and the tier carries at least three competing self-declared conventions instead — `Completed:`/`Blockers:` in swe-backend.md:560-569, swe-security.md:364-373, and ai-expert.md:615-624; an unstructured "3-5 bullets" in five `swe-*` files plus scribe, qa-engineer, visual-designer, product-ux; and bespoke field sets in debugger.md:876-896 (`Findings:/Root Cause:/Recommendations:/Ledger:/Escalated Assumptions:`) and researcher.md:469-478 (`Findings:/Gaps:`).

### Tool-use guidance style

The dominant style in the coordinator and reference tiers is **gotcha-driven and tool-specific**, teaching exact flag semantics inline rather than deferring to external documentation. staff-engineer.md:2157 teaches that `rg -E` means `--encoding` in ripgrep and not extended regex. staff-engineer.md:2316-2330 gives a decision rule for instructing a sub-agent to use Read versus `cat`/`sed`/`awk`, keyed on whether semantic understanding of the content is needed. mov-verification-taxonomy.md names an exact invocation shape per verification method (`:426` gives `curl -s -o /dev/null -w '%{http_code}'`) and documents the ripgrep bare-pipe trap at `:617-633`. delegation-guide.md:79-91 documents `perm` pattern syntax including word-boundary semantics at `:89`.

The reference-skill style is a fixed per-command micro-template: usage line → arguments → behavior/examples → error handling, visibly repeated across crew-cli/SKILL.md:22-99, :102-135, :138-, :180- (B6), with jump-indexes at kanban-cli/SKILL.md:12-29 and crew-cli/SKILL.md:12-19.

`TOOLS-DETAILED.md` is the most exhaustive instance of that same style in the corpus (B8): every one of its three H2 sections carries its own Configuration table of env-var / CLI-flag / default triples (:29-31, :95-98), its own Exit Codes enumeration (:38-41, :118-121), and its own worked Examples block — per-flag documentation rather than workflow guidance. The project-root `CLAUDE.md` sits at the other end of the same spectrum: its tool guidance is broad-brush and workflow-shaped — the four-step "Add new package" recipe at :183-190, the `git add` → `hms` → `commit` → `push` deployment-order rule at :177-181 — with no per-flag detail anywhere. The corpus therefore contains both the most granular and one of the least granular tool-guidance registers inside the same `modules/claude/global/` tree, and only one of the two is ever loaded.

The agent tier gives almost no tool guidance at all. All seven `swe-*` files declare an identical `tools` list and never narrow or sequence it; no file says when to prefer Grep over Read (B4). The only body-level tool guidance is the shared Context7 two-step line (swe-frontend.md:100 and six siblings) and the `Reviewing regex / pattern-matching code` section present in 4 of 7 (swe-backend.md:105, swe-sre.md:113, swe-security.md:105, swe-fullstack.md:105). The single exception in the whole tier is debugger.md:715-812, which gates *which* tools may be called at what point via seven numbered Write Gates — for example debugger.md:727 blocks Read/Glob/Grep/WebFetch/WebSearch until the ledger file exists. No other agent imposes any sequencing constraint on tool calls (B5).

At the opposite extreme, agent-browser/SKILL.md:23-27 explicitly refuses to reproduce its tool's documentation, instructing an on-demand fetch instead and noting that the upstream skill is 2,235 lines.

### Cross-reference density

staff-engineer.md is heavily self-referential: 220 `§` pointers per B1, of which only 13 point to an external file — all into `docs/staff-engineer/` (staff-engineer.md:713, :783, :1014, :1109, :1113, :1164, :1547, :1587, :1659, :1665, :1911, :2151, :2799, :2910, :2917). The remaining ~207 point at headings inside the same 2,918-line file, roughly a 16:1 internal-to-external ratio.

**Discrepancy, flagged.** B2's comparison table gives staff-engineer.md 188 `§` marks against B1's 220. Both inputs describe the same measurement (total `§` character count in one file) and the numbers disagree by 32. Neither is adopted here as correct.

senior-staff-engineer.md has 205 `§` marks, of which ~19 are external (16 to `staff-engineer.md` and 3-4 to global `CLAUDE.md`, per B2), leaving ~91% internal. That file also declares its own citation convention explicitly at senior-staff-engineer.md:25: "No line-number cross-references in this file. Section names + quoted bullet titles are the only stable anchors."

In Tier 3, five of nine files end in a dedicated `## References` footer — review-protocol.md:644, parallel-patterns.md:413, edge-cases.md:361, anti-patterns.md:132, and delegation-guide.md, which uniquely has **two** at :120 and :257 with different content in each. mov-verification-taxonomy.md:527 and understanding-requirements.md:65 use inline pointers instead. card-creation.md and self-improvement.md contain zero sibling cross-references. B3 characterizes the graph as a near-clique among {review-protocol, parallel-patterns, edge-cases, delegation-guide, anti-patterns} with the other four as peripheral nodes.

The agent tier has effectively no cross-reference apparatus. None of B4, B5, or B6 reports `§` pointers between agent files; the design is a flat set of self-contained documents.

**The two newly-covered files add a third and fourth cross-reference style (B8).** `TOOLS-DETAILED.md` uses a **per-section inline "Related Commands" list**, one at the end of every H2 section — :58-60 (`burns` → `smithers`/`kanban`), :152-155 (`smithers` → `burns`/`prc`/`kanban`), :334-337 (`prc` → `smithers`/`gh`) — rather than the single footer `## References` section B3 found in 5 of 9 Tier-3 docs. Both :3 and :341 point outward to `TOOLS.md` as the umbrella catalogue. **Its cross-reference graph is entirely outbound: nothing anywhere in the repository points into it** (see § Configuration Inventory, Unconsumed). The project-root `CLAUDE.md` is the opposite — heavily outbound *and* linked from the layer beside it: it defers to the global `CLAUDE.md` by name at :11 ("See global CLAUDE.md § PACKAGE INSTALLATION for details") and :353, points into `modules/system/HMS.md` at :115 and :359, and lists five `docs/staff-engineer/*.md` files at :378-387 — and the global `CLAUDE.md:511` points back into it for the agent add/update/remove workflow, making these the only two files in the corpus with a documented bidirectional pointer pair.

### Section-skeleton conformance

Conformance is high within the agent tier and near-zero within the skills tier.

The seven `swe-*` files share an 11-heading skeleton in the same relative order with identical wording (B4, verified by exact-string `rg -l`): `Hard Rule: Never edit .kanban/ files directly`, `Hard Rule: STOP on structurally broken MoV`, `Your Task`, `Hard Prerequisites`, `CRITICAL: Before Starting ANY Work`, `Your Expertise`, `Your Style`, `Code Quality Standards`, `Your Output`, `When Done`, `Output Protocol`. That is 11 of 118 total headings — 9.3% shared, 90.7% per-file domain content. swe-devex.md is most divergent (21 headings, 10 unique); swe-frontend.md least (13 headings, 1 unique). One near-skeleton slot has three different names for the same concept: `## Verification` in 5 of 7, `## Success Verification` in swe-frontend.md:590, `## Success Criteria` in swe-sre.md:444.

The seven support agents share only two sections verbatim across all seven — `Hard Rule: Never edit .kanban/ files directly` and `Output Protocol` — giving 2 of 13-17 per file, roughly 12-15% (B5). Beyond those the skeleton fragments: `CRITICAL: Before Starting ANY Work` in 5 of 7, with debugger.md:120 and researcher.md:39 using an unadorned `Before Starting` with materially different content; `Your Expertise` in 5 of 7; `Your Style` in 4 of 7, with scribe and researcher substituting `Your Personality` + `Your Voice`.

The three business agents share seven anchors and follow a consistent Hard Rule → Your Task → Before Starting → Your Expertise → Your Style → How You Work → Research Standards → domain sections → Your Output → Voice Examples → Output Protocol shape (B6). They diverge from the `swe-*` skeleton in one structural way: none hoists the broken-MoV rule to its own heading, folding it into the `.kanban/` block instead (finance.md:25, marketing.md:25, lawyer.md:25).

The five workflow skills share **zero** headings verbatim across all five (B7). Only `Hard Prerequisites` recurs at all, in 2 of 5 (project-planner/SKILL.md:85, pr-review/SKILL.md:43). Most tellingly, the two files B7's card framed as the same category — smithers and pr-review-watcher, both autonomous loops — use different step-labeling conventions: numeric `Step 1`-`Step 15` (smithers/SKILL.md:80-723) versus lettered `A/A2/A3/B/C/D` (pr-review-watcher/SKILL.md:149-247).

**`TOOLS-DETAILED.md` is the corpus's highest-conformance file and its lowest-heading-density file at once (B8).** All three of its H2 sections follow the identical eight-slot template — Purpose → Command → Usage → Configuration → Behavior → Exit Codes → Examples → Related Commands — with only the Configuration table varying (present for `burns` and `smithers`, absent for `prc`). That is stricter internal conformance than any tier above achieves: the `swe-*` files share 11 of 118 headings (9.3%), the support agents 2 per file (~12-15%), and the five workflow skills zero. The project-root `CLAUDE.md` has no skeleton to conform to — it is a single-instance document with 14 topical H2 sections in no repeated shape, which is the same structural situation as the global `CLAUDE.md` it accompanies.

### Persona and preamble framing

Persona framing is a Tier-4 technique and is absent from Tier 5 entirely (B6).

All seven `swe-*` files open with exactly one identity sentence at line 13, following the template "You are a **Principal \<Domain> Engineer** with deep practice in \<3-5 specialties>" (B4). Two deviate: swe-devex.md:13 runs to a second sentence, and swe-security.md:13 is the only file appending a real credential list ("CISSP, OSCP, CEH, CISM, CISA"). The three business agents open with credentialed personas — finance.md:13 ("CFO, CPA, CFA, and CFP"), marketing.md:13 ("a veteran CMO"), lawyer.md:13 ("passed the bar in Cary, North Carolina") — and B6 flags that finance.md:13 and lawyer.md:13 share the same oddly specific locale anchor while marketing.md:13 has none.

Support agents are uniform at one or two sentences (scribe.md:13, ai-expert.md:13, researcher.md:13, visual-designer.md:13, product-ux.md:13, qa-engineer.md:13), except debugger.md:13-17 at three paragraphs — which B5 judged proportionate to the 82% of that file given over to methodology.

Skills use no persona at all, opening with a purpose statement (manage-pr-comments/SKILL.md:12) or a bare directive (agent-browser/SKILL.md:9, "READ THIS ENTIRE FILE before running agent-browser commands.").

Neither newly-covered file uses a persona either. The project-root `CLAUDE.md` opens with a bare orientation statement (:3, "This file provides guidance to Claude Code when working with code in this repository") followed immediately by the repository's identity and the install-location requirement; `TOOLS-DETAILED.md` opens with a one-line scope note pointing at `TOOLS.md` (:3). Persona framing therefore remains a Tier-4-only technique across the full 44-file corpus — absent from Tier 1, Tier 2, Tier 3, Tier 5, and the unconsumed file alike.

### Load-bearing instruction placement

Front-loading is the norm, but staff-engineer.md is bookended rather than purely top-weighted. B1 measured emphasis-marker distribution across three equal line-thirds: `MUST` 30/11/20, `NEVER` 8/8/5, `🚨` 6/11/3. `## Hard Rules` occupies staff-engineer.md:92-357 — the first 9% of the file — while `## Critical Anti-Patterns` at :2797-2892 re-catalogues many of the same rules as 41 named failure modes near the end, and the 🚨 concentration sits in the middle third dominated by `## Card Management` (:1631-2608, 977 lines, ~33% of the file).

senior-staff-engineer.md front-loads similarly: `## Hard Rules` at :29 opens with "These rules are not judgment calls. No 'just quickly.'" (:31) and runs 16 numbered rules to :364.

Neither output style contains an explicit "read this document in this order" instruction. staff-engineer.md:23-88 provides a hand-maintained table of contents listing every heading, which implies sequential organization without mandating a reading order; B2 found the only "in order" language in senior-staff-engineer.md is local to specific lists (:1994, :2072, :2728, :2949).

Two placement facts from the skills tier are worth recording. smithers/SKILL.md:21 puts its single most load-bearing structural fact ("You run one iteration per invocation") in the first paragraph, at 2.6% depth, while deliberately placing its most consequential decision rule — the merge-consent policy — at :197, 24% deep, after all detection machinery is established. project-planner/SKILL.md inverts the pattern: its `## Your Workflow` section, the instructions on how to actually work, sits at :1264 — after roughly 95% of the reference content.

---

## Redundancy And Duplication Map

Five categories are separated below because each implies a different remedy. The first three are within-file, between-the-two-coordinator-prompts, and restatement-of-the-shared-layer. A fourth — cross-sibling duplication inside the agent tier — is separated because its duplicated content has no upstream source at all. A fifth, added by the amendment, is separated because it is the only category whose cost is paid unconditionally in every context: duplication *between the two always-injected files*.

### Category 1 — Duplication within a single file

**staff-engineer.md.** B1 audited six named rules and found restatement-only content totalling roughly 60-75 lines of 2,918, about 2-2.5%. This is explicitly a lower bound: only 6 of the file's 63 `###` subsections were audited.

The clearest case is the backslash-pipe MoV rule, **fully re-explained from scratch at six separate sites** — staff-engineer.md:503 (checklist item), :524 (second checklist item), :1729 (JSON authoring corollary with the RFC 8259 escaping detail), :1738 (Write-tool-time reflex), :1740 (forced self-test), :1831 (pre-`kanban do --file` lint). Four further sites correctly point rather than restate (:1861, :2157, :2196, :2218). B1 found the core claim identical across all six with no semantic divergence — the same explanation independently re-derived at three different workflow moments.

The densest is the AskUserQuestion rule, with roughly 21 distinct citations: a 67-line primary statement at :1265-1332 containing six numbered sub-rules and two worked examples, a separate permission-gate-specific application at :1093 and :1105, a Hard Rules cross-reference at :243, a full inline restatement in a checklist item at :517, and a third full-length restatement as a named anti-pattern at :2808.

**senior-staff-engineer.md.** B2 estimated 15-20 short passages, 60-90 lines, under 3%. The "mutating git" prohibition recurs across 8 locations (:216-218, :492, :513, :1144 among them), with the core sentence near-verbatim at both :216 and :513. B2's conclusion is that the file's size comes from breadth — 144 headings on genuinely different topics — not from repetition.

**Other single-file cases.** researcher.md restates the Research Priority Order **three times against itself** (researcher.md:58-79, :129-144, :437-440). project-planner/SKILL.md:984-1241 repeats its own six-heading template twice as worked examples, 258 of 1,332 lines. pr-review-watcher/SKILL.md documents the same deprecated field as dead in two places (`:43` and `:133`). delegation-guide.md has two `## References` sections (:120, :257). understanding-requirements.md:1 and :3 carry a duplicated H1/H2 title.

### Category 2 — Duplication between the two coordinator prompts

Five sections share identical titles across the two files: `Claude Improvement Reporter` (senior-staff-engineer.md:2585 / staff-engineer.md:388), `Investigate Before Stating` (:2935 / :598), `Mandatory Review Protocol` (:2357 / :1472), `Post-Review Learning Pass (Compounding Improvement)` (:2412 / :1589), `Programming Principles Anchor` (:2912 / :2707). `Model Selection` diverges in name only, and intentionally: senior-staff-engineer.md:2533 is `## Sub-agent Model Selection (Rare Direct Delegation)` and :2535 explicitly scopes it as not applying to Staff Engineer sessions.

**B2's quantified estimate: roughly 250-300 lines of senior-staff-engineer.md — about 9-10% of its 3,061 lines — restate or tier-split content whose fuller version lives in staff-engineer.md**, spanning :2357-2469, :2533-2549, :2585-2667, :2912-2935, :2935-2975.

The design intent is a single source of truth with a manual sync boundary, stated explicitly twice: senior-staff-engineer.md:2414 ("This mirrors staff-engineer.md's Post-Review Learning Pass mechanism exactly — that file is the canonical spec") and senior-staff-engineer.md:2379 ("the same STOP condition … are mirrored in staff-engineer.md § Mandatory Review Protocol — keep both in sync if modifying either"). **That sync has already failed** — see § Tensions And Contradictions, CT-4.

Two sections exist in only one file by design: `Worktree Discipline` (staff-engineer.md:1168) and `Parallel Execution` (staff-engineer.md:1130) have no senior-staff-engineer.md counterpart and are cross-referenced by name instead (senior-staff-engineer.md:347, :1192). staff-engineer.md:1549-1587 has a ~38-line `Review Output Handling` apparatus with a severity decision table that senior-staff-engineer.md replaces with two inline sentences (:2408, :2410) — consistent with senior-staff-engineer.md:2359's rule that Senior Staff does not create review cards.

### Category 3 — Restatement of the auto-injected shared layer

This is duplication of content every file in question already receives for free.

**`swe-*` tier, ~133 lines minimum (B4).** The four-step Research Priority Order is restated in full in all seven files (swe-frontend.md:94-103, swe-backend.md:94-103, swe-sre.md:102-111, swe-devex.md:102-111, swe-security.md:94-103, swe-infra.md:118-127, swe-fullstack.md:94-103) — 70 lines. The bash variable-naming convention is restated verbatim in all seven (swe-frontend.md:570-572 and siblings) — 14 lines. SOLID/YAGNI/KISS/DRY/12-Factor concept names are re-listed as bare bullets in all seven `Code Quality Standards` sections — ~42 lines. The Context7 tool pairing is restated in all seven (swe-frontend.md:100 and siblings) — 7 lines.

**Support-agent tier, ~75 lines (B5).** Six of seven restate the Research Priority Order: ai-expert.md:63-68 (a 3-tier variant that drops the local-docs tier), scribe.md:49-54, qa-engineer.md:91-95, visual-designer.md:45-50, product-ux.md:43-48, plus researcher.md's triple restatement noted in Category 1. The Context7 `CONTEXT7_API_KEY`/`overconfig.nix`/fallback facts are re-explained per agent in five of seven (scribe.md:35-37, researcher.md:35-37, qa-engineer.md:82-84, visual-designer.md:35-37, product-ux.md:35-37).

**Business tier.** finance.md:37-42 and marketing.md:37-42 each restate a 4-tier priority list with paraphrase drift — CLAUDE.md's tier 4 reads "ONLY when above sources don't have what you need" against their "Last resort only" (B6). lawyer.md does not restate it.

**Skills tier.** review-citation-guide.md:11-14 restates the three-tier source priority **without attributing it to CLAUDE.md at all**, so a reader of that file alone cannot know it mirrors a global rule (B7). pr-review-watcher/SKILL.md:206 restates the Pagination Discipline rule near-verbatim but *does* name its source, then elaborates ~10 lines for the Slack case. pr-review/SKILL.md:234-299 reimplements staff-engineer.md's create-all-cards-then-launch-all-agents protocol inline — ~65 lines duplicating a pattern staff-engineer.md:829 and :831 already state generically.

**Three clean counter-examples exist and are worth recording as the contrasting pattern.** The Homebrew prohibition (CLAUDE.md:7, :15, :144, :387-391) is never restated in either coordinator prompt — B3 confirmed zero matches for `homebrew` in both output styles — making it the corpus's cleanest single-source rule. agent-browser/SKILL.md:17 states "**NEVER Homebrew.** This is a Nix-managed system — see global CLAUDE.md," deferring rather than duplicating. mov-verification-taxonomy.md:637 explicitly declines to duplicate the banned-syntax list: "That list is not duplicated here." staff-engineer.md:1770 likewise acknowledges the base layer explicitly: "(This augments the `rg -E` footnote in global CLAUDE.md § Use `rg` and `fd`.)"

### Category 4 — Cross-sibling duplication within the agent tier

Distinct from Category 3 because the duplicated content has no upstream source — it is boilerplate baked independently into each file.

**`swe-*`: ~613 of 3,274 lines, 18.7% (B4).** The largest block is `Hard Rule: STOP on structurally broken MoV`, byte-identical across 46 lines × 7 files (swe-frontend.md:29-74 and siblings) — 276 redundant lines. Then `Hard Rule: Never edit .kanban/ files directly`, 13 lines × 7 (swe-frontend.md:15-27 and siblings) — 78 redundant. Then `Reviewing regex / pattern-matching code`, 25 lines × 4 — 75 redundant. Then `Hard Rule: Secret-Safe Environment Inspection`, 7 lines × 3 (swe-sre.md:76-82, swe-devex.md:76-82, swe-infra.md:92-98) — 14 redundant. Plus the `Output Protocol` closing block, the `Code Quality Standards` core bullets, the Context7-unavailable blockquote, and the ultra-concise `When Done` pattern in 2 of 7. Combined with Category 3, B4 gives 22.8% of the seven-file corpus as duplicated text.

**Support tier (B5).** The `.kanban/` hard rule is verbatim-identical in all seven — 13 lines × 7 = 91 lines (debugger.md:19-31, scribe.md:15-27, ai-expert.md:15-27, researcher.md:15-27, qa-engineer.md:15-27, visual-designer.md:15-27, product-ux.md:15-27). The broken-MoV rule appears in only 2 of 7 with minor drift (debugger.md:33-73 versus qa-engineer.md:29-74, which adds a fourth ❌ bullet and a loop-counter paragraph). The Output Protocol 4-bullet block is verbatim in 5 of 7 and a 3-bullet subset in 2.

**Business tier (B6).** The same `.kanban/` block is word-for-word identical at finance.md:15-27, marketing.md:15-27, lawyer.md:15-27. B6 verified this block appears in **neither** global CLAUDE.md nor staff-engineer.md — it has no upstream source. The Output Protocol block is near-identical at finance.md:386-409 and marketing.md:385-408, with lawyer.md:328-345 sharing the first three bullets word-for-word and substituting domain-specific examples at :341-350.

**Reference-skill overlap.** kanban-cli/SKILL.md and staff-engineer.md § Card Fields duplicate near-verbatim prose, not merely topic (B6, four items cross-checked): the length-based secret-detection worked example with identical numbers (kanban-cli/SKILL.md:226 versus staff-engineer.md:1826), the card #2457 fixed-string anchor example (kanban-cli/SKILL.md:169-180 versus staff-engineer.md:1816), the line-ordering example (kanban-cli/SKILL.md:182-189 versus staff-engineer.md:1818 and :2179), and the BSD/GNU coreutils list (kanban-cli/SKILL.md:152-167 versus staff-engineer.md:2194). B6 found no contradictory guidance on any cross-checked item, but the cross-reference is circular — see CT-9.

### Category 5 — Duplication between the two always-injected files

**Added by the amendment (B8). Separated from all four categories above because its remedy differs from all of them: there is no deferral target.** In Categories 1 through 4, the duplicated content has somewhere else to live — an on-demand reference doc, a sibling coordinator prompt, the shared layer, or a template. Here both copies are resident in every context by construction, so the overlap is not paid once per file load but **once per session and once per sub-agent spawn, unconditionally, with no way to opt out**. A pointer cannot fix it either, because the pointer's target is already in the context window.

**The finding: `## Team Member Terminology` is a genuine double-injected duplicate core, not a short-plus-long split.** Both Tier-1 files carry an H2 by that exact name — global `CLAUDE.md:506` and project-root `CLAUDE.md:72`, both confirmed present for this amendment via `rg -n '^## Team Member Terminology'` against both paths. The global copy runs roughly 20 lines (:506-525, per B3's line numbering); the project copy runs 33 (:72-104). The overlap is not a headline-and-detail split: **both sections independently restate the same three-category exception/workflow/multi-file skill taxonomy with the same named examples** (`.scratchpad/B8-missed-files.md:103-107`) —

- Global `CLAUDE.md`: "learn, project-planner — interactive exception skills; live at `skills/<name>/SKILL.md`" / "review-pr-comments, manage-pr-comments — workflow skills" / "pr-review — multi-file skill with supporting files"
- Project `CLAUDE.md:100-102`: "**Exception skills** (project-planner) — Run via Skill tool directly…" / "**Workflow skills** (manage-pr-comments, review-pr-comments) — Live at `skills/<name>/SKILL.md`…" / "**Multi-file skills** (pr-review) — Live in `skills/<name>/SKILL.md`…"

**Estimated double-paid cost: ≈20 lines** — the shorter side, global `CLAUDE.md:506-525` — charged twice to every context. As a share of the 917-line always-injected layer that is roughly 2.2%.

**The rest of the split is correctly delegated and is not double-paid.** Project `CLAUDE.md:72-95` carries roughly 13 additional lines of concrete add/update/remove step-by-step recipes that exist nowhere else, and global `CLAUDE.md:511` explicitly points at them ("See project CLAUDE.md § Team Member Terminology for the full add/update/remove workflow"). That is the same short-plus-pointer shape B3 validated for Model Selection. **The double-pay is the taxonomy naming specifically, not the workflow steps** — a distinction that matters because the two halves sit under one heading and a remedy that removed the whole section would delete unique content.

**Two candidate overlaps that B8 examined and dismissed, recorded so they are not re-flagged.** The Homebrew prohibition is *not* a meaningful duplicate: project `CLAUDE.md:9-11` restates only the headline and explicitly defers ("See global CLAUDE.md § PACKAGE INSTALLATION for details") — three lines of overlap, correctly delegated, and consistent with the Homebrew rule's status as the corpus's cleanest single-source rule recorded in Category 3. Scratchpad guidance is also not a duplicate: the global file has a dedicated `## Scratchpad` section while the project file mentions `.scratchpad/` only in passing as one bullet in its Source-of-Truth exception list (:62) — different granularity, not the same content twice.

---

## Accretion Analysis

**Amended by B9. Question (a) is now an empirical finding; question (b) remains open.**

The original synthesis framed this entire section as an untested hypothesis, because no wave-1 input examined git history. B1 stated the limitation as its second open question — the prose "strongly suggests reactive patching," but whether the compensatory passages were added in later commits after an observed failure, versus present from an early version, **was not verified** — and B5 and B6 recorded the same limitation for the agent and skill tiers. All of the § The signatures observed evidence below remains what it always was: textual form, the shape of the prose rather than its provenance.

**The two questions the original synthesis insisted on separating remain separate, and only one of them has been answered.**

- **(a) Did this content in fact accrete reactively?** Answerable from git history. **B9 answered it. It is reported below as a finding, with a verdict, a confidence level, and cited evidence.**
- **(b) Is the resulting form good practice under current guidance?** Answerable only from Document A's account of Anthropic's guidance. **Still open. B9 explicitly declines to touch it** (`.scratchpad/B9-accretion-history.md:159`: "This document does not and must not answer question (b)"). Nothing in this amendment brings the gap analysis any closer to a conclusion on (b), and the original warning stands unchanged: a rewrite that treats (a) as established and (b) as obvious would be removing text on the strength of an inference this document still declines to make.

### Question (a) — the empirical finding

**Verdict, as B9 wrote it: SUPPORTS, with one clearly-documented exception, at moderate-to-high confidence** (`.scratchpad/B9-accretion-history.md:137`). The critical qualification, in B9's own words at `:146`: **"the hypothesis is file-dependent, not corpus-wide."**

Four results carry that verdict, and all four must travel together. Any summary that reduces them to "accretion confirmed" is a misreading of the evidence, for reasons spelled out under § What this finding does not license below.

#### Commit-message census

B9 counted commits per file with `git log --oneline --follow -- <path>`, bucketing subjects two ways: (1) the literal `claude-improvement:` prefix, this repository's explicit convention for correcting an observed behavioral failure, and (2) `fix(...)`/`fix:` conventional-commits prefixes not already in bucket 1. Repository history is **not** shallow (`git rev-list --count HEAD` → 1650; no `.git/shallow`), so the counts reflect genuine full history.

| File | Total commits | `claude-improvement:` | Other `fix` | Combined incident signal |
|---|---|---|---|---|
| `output-styles/staff-engineer.md` | 436 | 167 (38.3%) | 89 (20.4%) | **256/436 = 58.7%** |
| `output-styles/senior-staff-engineer.md` | 180 | 154 (85.6%) | 3 (1.7%) | **157/180 = 87.2%** |
| `skills/kanban-cli/SKILL.md` | 25 | 21 (84.0%) | 1 (4.0%) | **22/25 = 88.0%** |
| `modules/claude/global/CLAUDE.md` | 78 | 12 (15.4%) | 6 (7.7%) | **18/78 = 23.1%** |

Re-derived for this amendment: the global `CLAUDE.md` row reproduces exactly (78 / 12 / 6), as do the `kanban-cli` totals (25 / 21).

**Result 1 — the hypothesis holds strongly for three of four census targets.** The two coordinator output styles and `kanban-cli/SKILL.md` sit at 58.7%, 87.2%, and 88.0% combined incident signal. For these files the premise the original synthesis inferred from prose shape is confirmed from provenance.

**Result 2 — the hypothesis does NOT hold for the always-injected `CLAUDE.md`, and this is the single most consequential result in the amendment.** At 23.1% combined incident signal, non-incident commits — `feat`, `refactor`, `docs`, and unprefixed early commits — are the **majority** of that file's history. B9's reading (`:45`): its growth mechanism "is closer to conventional feature development than to the two coordinator prompts." **The bulk of the one file every session and every sub-agent receives appears substantially deliberate rather than reactive.** Two further observations sharpen this. First, B9 notes a visible shift in commit-message convention across that file's history: the oldest commits carry no structured prefix at all (`607de07 Update Claude Code configuration and documentation`, `1825a7f update global claude`), a `feat`/`fix`/`docs`/`refactor` convention appears partway through, and `claude-improvement:` is the newest, concentrated in roughly the last 15% of the file's commits — so the tagging discipline the census depends on did not exist for much of the history it measures. Second, B9 flags a **false positive inside its own 23.1%**: `50c4058 fix(claudit): CAST strftime epoch to INTEGER for Grafana time-range filters` is a metrics-pipeline fix with nothing to do with prompt content, yet was counted into that file's fix bucket. B9 therefore instructs that 23.1% be read as an upper bound (`:155`) — the true prompt-content-specific incident fraction for this file is **lower than 23.1%**, making the negative result stronger, not weaker.

This result is independently corroborated by textual evidence in this document: § Authoring Style Profile records that the incident-anecdote technique — the corpus's clearest accretion signature — is **entirely absent** from both always-injected files (B8). Two independent methods, provenance and prose form, agree that the always-injected layer is the part of the corpus least explained by reactive growth.

#### Introducing-commit traces

B9 traced four named passages to the commit that introduced them, via `git log -S "<substring>" --oneline --follow -- <path>` and then reading the earliest hit's full body. **Three of four are incident-driven; the fourth is the counter-example.**

1. **"Session length and batch count are never exemptions"** (staff-engineer.md:1478) → `ff49729`, 2026-04-15, `fix(staff): add session-fatigue guard to mandatory review protocol`. Body names the observed degradation directly: "Long sessions caused review protocol degradation — early batches got proper tier checks, later batches skipped them as velocity built up." **Incident-driven**, though not `claude-improvement:`-prefixed.
2. **The "if you find yourself" construction** (staff-engineer.md:1280 and others) → `5c0133a`, 2026-05-15, `claude-improvement: codify prose-list decision-surface anti-pattern`. **Incident-driven.** B9 notes the string's occurrence count changed across 15 separate commits, meaning the construction became a reusable template applied to new rules over time — phrase-level accretion rather than a single stylistic decision.
3. **The `🚨 MoV Authoring Banned Patterns` section** (kanban-cli/SKILL.md) → `2045260`, 2026-04-30, `claude-improvement: surface MoV banned-pattern reminders in kanban-cli skill`. Body: "Triggered by improvement note: coordinator authored `\|` in rg MoV despite the banned-pattern docs, exposing a reinforcement gap between the auto-loaded skill body and the agent-prompt-only documentation," and it cites "ai-expert review #1692 findings (1 high + 3 medium + 3 low) all applied," naming six banned-pattern subsections added in response to a numbered review. **Incident-driven, and the best-documented instance in the whole investigation** — the commit states the trigger, cites the review by number, and enumerates the sub-fixes.
4. **The 🚨 emoji siren** (traced in the always-injected `CLAUDE.md` lineage, whose predecessor path was `claude-global.md`) → `607de07`, 2025-09-12, `Update Claude Code configuration and documentation`. **NOT incident-driven at its origin.**

**Result 3 — the counter-example, and it must not be dropped from any summary of this section.** The siren's first appearance in this lineage is inside a bulk "rewrite the whole config" commit with a generic message and **no incident named anywhere in it**. B9 confirmed by reading the diff that the introducing hunk is `## Critical Debugging Philosophy` / `**🚨 NEVER STOP AT THE FIRST ISSUE 🚨**` — a general debugging-philosophy heading, introduced as a generic emphasis device for a general principle. Re-verified for this amendment with `git show 607de07 --stat`: the commit is dated 2025-09-12, its body reads "Rewrite CLAUDE.md with comprehensive nixpkgs configuration guide / Add global Claude Code configuration (claude-global.md) / …", and it touches exactly two files (`CLAUDE.md` +123/−39, `claude-global.md` +93) — a bulk-authoring commit, not a reactive patch. **The corpus's single most recognizable "defensive" visual marker was not born defensive.** B9 is careful about scope: this trace settles the technique's *origin* only, and the 8 further count-changing commits to that file plus the roughly 58 sirens spread corpus-wide are a separate question it did not pursue.

#### The kanban-cli versus crew-cli asymmetry, mechanically confirmed

The original synthesis called the 13-fold defensive-content asymmetry between these two near-identical files "the strongest single piece of textual evidence for the hypothesis," and hypothesized a mechanical cause it could not test: if `kanban-cli` simply had many more incident-driven commits, that would explain the asymmetry without invoking any difference in authoring style.

| File | Current lines | Total commits | `claude-improvement:` | Fraction |
|---|---|---|---|---|
| `kanban-cli/SKILL.md` | 542 | 25 | 21 | 84.0% |
| `crew-cli/SKILL.md` | 549 | 13 | 8 | 61.5% |

Both figures re-derived for this amendment and both reproduce exactly.

**Result 4 — CONFIRMED, and B9 calls it the strongest quantitative evidence in its investigation.** Two files of near-identical current length (542 versus 549 lines) and near-identical purpose have histories that are not comparable: `kanban-cli` carries roughly **double** the total commit count (25 versus 13) and roughly **2.6×** the absolute number of incident-tagged commits (21 versus 8). That is a direct, mechanical, commit-count explanation for a structural asymmetry the original synthesis could only describe from prose shape — the defensive section reaching 41% of `kanban-cli`'s length against roughly 3% of `crew-cli`'s. B9's caveat: the comparison counts commits, not lines added per commit, so it does not prove every one of the 21 `kanban-cli` incident commits added banned-pattern text specifically rather than touching other sections.

#### Growth curve

Both coordinator files are much younger than the repository: `staff-engineer.md` was created 2026-01-30 (`529ebab feat(claude): Add staff-engineer output style`), `senior-staff-engineer.md` on 2026-04-14 (`462eac6`).

| Date | `staff-engineer.md` | `senior-staff-engineer.md` |
|---|---|---|
| 2026-03-31 | 954 | not yet created |
| 2026-04-15 | 1,080 | 846 |
| 2026-05-15 | 2,398 | 2,422 |
| 2026-06-15 | 2,665 | 2,727 |
| 2026-06-30 | 2,845 | 2,815 |
| 2026-07-15 | 2,894 | 3,018 |
| 2026-07-24 | 2,918 | 3,061 |

**The curve is punctuated, not steady.** `staff-engineer.md` grew ~8.4 lines/day to mid-April, spiked to ~44 lines/day across the following month (+1,318 lines), then decelerated through ~9, ~12, ~3.3, and ~2.7 lines/day. `senior-staff-engineer.md` shows the identical shape at the same time, +1,576 lines in the same one-month window.

**B9 resolved the ambiguity that spike created**, which matters because a single bulk-rewrite commit would have argued *against* accretion. `git log --follow --since="2026-04-15" --until="2026-05-16"` over `staff-engineer.md` returns **116 separate commits** in that window, of which **93 (80%) carry the `claude-improvement:` prefix**. The spike is high-velocity incident-tagged accretion, not a redesign. B9 notes the window also contains ordinary feature work (e.g. `7609803 refactor(kanban): eliminate review column, dual-column AC, kanban redo`), so it is a mix — but the incident-tagged majority holds even inside the spike.

#### Confidence, and what would change the verdict

**B9's stated confidence is split by file** (`.scratchpad/B9-accretion-history.md:148`): **moderate-to-high** for the two coordinator prompts and `kanban-cli/SKILL.md`; **low-to-moderate** for `CLAUDE.md`, given both its lower incident fraction and its mix of pre- and post-`claude-improvement:`-convention history.

B9 names three levers that would move the verdict: (a) reading all 89 non-`claude-improvement` `fix(...)` commit bodies for `staff-engineer.md` and finding most are not reactive would weaken the coordinator-tier finding; (b) reading all 116 April-May spike commit bodies and finding the spike was substantially reorganizational rather than additive would weaken the growth-curve finding; (c) conversely, finding that `CLAUDE.md`'s older unprefixed commits *do* describe specific past failures in their bodies — B9 checked subjects, not bodies, for that file — would strengthen the hypothesis for the one file where it is currently weakest. All three remain unpursued; they are recorded in § Coverage Gaps.

#### What this finding does not license

**A blanket "accretion confirmed" is not what B9 found, and acting on that reading would authorize rewriting a file the evidence says was designed rather than accreted.** This paragraph exists specifically to prevent that error in the downstream gap analysis and implementation plan.

Three constraints follow directly from the results above.

1. **The finding is per-file and must be applied per-file.** A de-accretion argument is well-evidenced for `staff-engineer.md`, `senior-staff-engineer.md`, and `kanban-cli/SKILL.md`. It is **not** evidenced for the global `CLAUDE.md`, whose majority-non-incident history points the other way and whose true incident fraction is below the 23.1% upper bound B9 reports. Any plan that treats the always-injected layer's bulk as reactive debt is contradicted by this document's evidence.
2. **A technique's shape is not evidence of a technique's origin.** The 🚨 siren looks like the most defensive marker in the corpus and originated in a generic bulk rewrite. Reasoning from prose form to provenance failed on the one case that was actually traced to a commit, so it should not be trusted on the untraced ones.
3. **Reactive origin is not the only argument available, and it is not the strongest one for the always-injected layer.** The relevance-distribution finding in § Configuration Inventory — roughly 82% of the project-root `CLAUDE.md` and roughly 30% of the global `CLAUDE.md` is narrow-audience content, in files every context receives — is an evidence-backed cost argument that **does not depend on the accretion hypothesis at all**. Content can be entirely deliberate in origin and still be the wrong thing to inject into every context. Keep the two lines of reasoning separate; conflating them would make a sound relevance argument look like it rests on a hypothesis that does not hold for those very files.

### Question (b) — still open

Whether any of this content, however it arrived, represents good practice under Anthropic's current guidance is untouched by B9 and untouched by this amendment. It belongs to the gap analysis against Document A. The original posture stands: this document describes what exists and does not evaluate it.

### The signatures observed

**1. Compensatory escalation prose co-located with a rule** — language whose function is to pre-empt a specific rationalization rather than to state the rule. staff-engineer.md:1478: "**🚨 Session length and batch count are never exemptions.** … No exceptions. No 'we've been reviewing all day, this one is fine.'" The same phrasing is echoed at staff-engineer.md:527. In senior-staff-engineer.md the same rhetorical device is redeployed independently at five or more separate rule sites rather than defined once as a document-wide severity marker: "ever, period" (:118, :218), "Not an exemption but an active prohibition" (:2373), "no exceptions" (:2724, :2726, :2781), "no exception even when … discussed moments ago" (:2743). **Traced (B9): this exact passage was introduced by `ff49729`, 2026-04-15, whose body names the observed degradation it was written to close — see § Question (a), Introducing-commit traces #1. Incident-driven, confirmed from provenance.**

**2. Rules visibly patched after an observed workaround.** staff-engineer.md:223-244 contains two layers within one subsection: the base rule at :225 ("No hook-skip flags, ever") and a separate clause at :236 closing the human-delegated-bypass loophole ("Human-delegated bypass is equally prohibited"). The second clause targets routing the prohibited act through a different actor — a shape that only becomes worth prohibiting after someone attempts it. Similarly, staff-engineer.md:2867 disambiguates a "blanket bypass" anti-pattern from the similarly-named `SKILL_AGENT_BYPASS` permission mechanism, which B1 read as deliberate care against a specific observed conflation.

**3. Per-incident anti-pattern catalogue entries.** `## Critical Anti-Patterns` at staff-engineer.md:2797-2892 is 96 lines holding 41 named bold-bullet entries. Three of them (:2816, :2817, :2818) are three distinct failure shapes of the *same* review protocol — "Re-review cascade," "Review skip," "Body-unchanged review skip on security-perimeter migrations." anti-patterns.md carries roughly 40 more in 136 lines, each ending in a `Concrete failure:` scenario.

**4. Banned-pattern catalogues that grew one entry per failure.** kanban-cli/SKILL.md:31-254 is 223 of 542 lines — 41% of the file — and its entries carry incident citations naming specific cards (`:180` card #2457, `:220` PLA-3559 card #9). Its sibling crew-cli/SKILL.md, near-identical in length and purpose, is at roughly 3%. The 13-fold asymmetry between two structurally parallel files is the strongest single piece of textual evidence for the hypothesis: the difference is not authoring style, since both files were written to the same per-command template, but incident history. **Traced (B9): CONFIRMED mechanically — `kanban-cli` has 25 commits to `crew-cli`'s 13 and 21 incident-tagged commits to its 8, and the section itself was introduced by `2045260`, whose body cites the triggering authoring error and a numbered prior review. See § Question (a), Result 4 and trace #3. This is the one signature where the textual inference and the provenance evidence converge completely.**

**5. "If you find yourself…" and "STOP — that IS the failure mode."** staff-engineer.md:1280 ("If you find yourself drafting 'Option 1: …' STOP"), :1316 ("This shape … is the failure mode. Convert to AskUserQuestion."), :1625, :2605. These sentences describe the model's own prospective behavior rather than the rule, which only makes sense as text written after observing that behavior. **Traced (B9): introduced by `5c0133a`, 2026-05-15, `claude-improvement: codify prose-list decision-surface anti-pattern` — incident-driven. B9 adds a finding the textual reading could not have produced: the construction's occurrence count changed across 15 separate commits, so it did not merely originate reactively, it became a reusable template re-applied to new rules over time. See § Question (a), trace #2.**

**6. The same rule restated at multiple workflow moments.** The backslash-pipe rule is stated at card-drafting time (staff-engineer.md:503), at Write-tool time (:1738), and as a forced self-test (:1740). B1's reading is that one restatement was judged insufficient in practice — the restatements are positioned at successive points where the error could still be caught.

**7. Named-incident anchoring.** Nine `PLA-####` identifiers in staff-engineer.md cited 13 times; seven `Real incident` markers in senior-staff-engineer.md each naming a session (sharp-trail, true-frost, fair-flame); five in kanban-cli/SKILL.md; one each in swe-infra.md:311 and ai-expert.md:418.

**8. Verbatim user corrections as rule sources.** user-voice/SKILL.md:32-117 is a banned-phrase catalogue in which the justification for each entry *is* a quoted correction (`:49`, `:57`, `:58-59`).

### Estimated footprint

Bounding the total conservatively, from the passages the inputs actually measured:

| Component | Lines |
|---|---|
| staff-engineer.md § Critical Anti-Patterns (:2797-2892) | 96 |
| staff-engineer.md incident-anecdote prose (B1 estimate) | 45–55 |
| staff-engineer.md restatement-only content, 6 audited rules (B1) | 60–75 |
| senior-staff-engineer.md anecdote footprint (B2 estimate) | 60–80 |
| senior-staff-engineer.md internal restatement (B2 estimate) | 60–90 |
| anti-patterns.md, concrete-failure bullets | ~120 of 136 |
| kanban-cli/SKILL.md banned-pattern section (:31-254) | 223 |
| user-voice/SKILL.md Hard Avoids (:32-117) | ~85 |

**Total: roughly 750–825 lines, about 3.1–3.4% of the corrected 24,210-line corpus** (the original synthesis gave 3.2–3.5% against its 23,482-line figure; the line range itself is unchanged).

**B9 does not supersede this estimate, and the estimate is retained.** B9's method counted *commits*, not lines added per commit, so it produces no competing line-footprint figure and revises none of the eight rows above. Two things it does establish about the table are worth recording. First, **every row draws from a file where B9's verdict is positive or untested — not one row comes from the always-injected layer.** The three census targets with 58.7%, 87.2%, and 88.0% incident signal supply six of the eight rows; the global `CLAUDE.md`, the one file where the hypothesis does not hold, contributes nothing to the estimate. The negative result therefore does not reduce the footprint figure. Second, the two remaining rows — anti-patterns.md's ~120 concrete-failure bullets and user-voice/SKILL.md's ~85-line Hard Avoids catalogue — are from files B9 did **not** census, so their inclusion still rests on textual form alone and is recorded as a gap.

Three caveats on that figure. It is a floor, not a ceiling: B1 audited only 6 of 63 subsections in staff-engineer.md for restatement, so the file-wide rate is unknown. It counts only text whose *own lines* carry the signature, and B2 observed that each anecdote typically anchors one to three paragraphs of generalized rule extracted from it — so the influenced footprint is materially larger than the signature footprint. And it cannot count rules whose *existence*, rather than wording, traces to an incident, since nothing in the static text distinguishes those from rules authored proactively.

**That third caveat is now partially addressable, and one worked case shows why it matters.** Git history can distinguish existence-from-incident where the static text cannot — B9 demonstrated the method on four passages and got three incident-driven origins and one that was not. The 🚨 siren case is the instructive one: a technique whose form reads as maximally defensive turns out, on provenance, to have originated in a generic bulk rewrite. Applying B9's `git log -S` trace to the remaining signature passages would convert more of this estimate from inference to finding, in either direction. Four of the eight signatures above remain untraced (see § Coverage Gaps).

---

## Tensions And Contradictions

Ordered cross-tier first, because those are the hardest for any single agent to notice — no context contains both sides. Several entries are outright correctness defects rather than style observations; they are reported plainly and descriptively, with no remedy proposed.

**CT-1 (cross-tier, correctness defect). Every agent definition instructs a direct Context7 MCP query; the always-injected layer states no sub-agent can reach any MCP server.** All seven `swe-*` bodies instruct "Query Context7 MCP for authoritative documentation before implementing" as a first-person action (swe-frontend.md:98-102 and six siblings). Six of seven support agents restate the same priority order (ai-expert.md:63-68, scribe.md:49-54, qa-engineer.md:91-95, visual-designer.md:45-50, product-ux.md:43-48, researcher.md:58-79), as do finance.md:37-42 and marketing.md:37-42. Global `CLAUDE.md` § Research Priority Order states unconditionally that no standard specialist sub-agent can access any MCP server directly, that there is no per-agent exception, and that the `mcp:` frontmatter field present in all 17 files is informational only. B4 flags this as a genuine contradiction baked into all seven `swe-*` files simultaneously; an agent following its own prompt attempts a call it cannot make.

**CT-2 (cross-tier). Context7-unavailable behavior: stop-and-escalate versus fall-back-silently.** Every agent file's Context7-unavailable blockquote instructs the agent to stop and surface a blocker (swe-frontend.md:82-84 and siblings; scribe.md:35-37, researcher.md:35-37, qa-engineer.md:82-84, visual-designer.md:35-37, product-ux.md:35-37). Global `CLAUDE.md` § MCP Integration states flatly "When it fails: Fall back to WebSearch for official documentation" — no escalation step. Both are in every agent's context simultaneously and no file reconciles them.

**CT-3 (cross-tier, correctness defect). The 7-field return contract exists in the coordinator tier and in zero of the 17 agent definitions, which carry three competing alternatives instead.** Specified at staff-engineer.md:1016-1078 and senior-staff-engineer.md:1365. B4 and B5 independently confirmed no agent file states it. The agent tier instead specifies `Completed:/Blockers:` (swe-backend.md:560-569, swe-security.md:364-373, ai-expert.md:615-624), an unstructured "3-5 bullets" (swe-frontend.md:600-606, swe-sre.md:456-463, swe-devex.md:438-445, swe-infra.md:367-374, swe-fullstack.md:348-355, scribe.md:688-693, qa-engineer.md:346-352, visual-designer.md:241-245, product-ux.md:181-185), or a bespoke field set (debugger.md:876-896, researcher.md:469-478). B4's assessment: the largest cross-agent inconsistency in that tier, and it is unclear whether the in-file text is load-bearing at all or vestigial.

**CT-4 (cross-tier, correctness defect). The Re-review STOP condition's exclusions exist in one coordinator prompt and not the other.** staff-engineer.md:1486-1488 states three explicit exceptions to the STOP condition: the file is new to this session, the deployment context has changed, or the code is auth/authz, permission-gating, credential-handling, or security-perimeter. senior-staff-engineer.md:2371-2379 states the base rule with **no mention of any exclusion**, even though senior-staff-engineer.md:2359 claims Senior Staff "applies the same tier framing." B2's conclusion: a Senior Staff session evaluating re-review eligibility from its own file would incorrectly suppress a review that staff-engineer.md's fuller rule still requires — an auth/authz migration being the concrete case. This is precisely the drift the sync-reminder at senior-staff-engineer.md:2379 was written to prevent.

**CT-5 (cross-tier, correctness defect). card-creation.md documents an AC/MoV format the live schema no longer accepts.** card-creation.md:49 documents the criterion format as a bracketed inline string, `"<statement> [MoV: <command or path>]"`, with 11 occurrences of the literal `[MoV:` substring across the file (card-creation.md:36, :51-55, :59-60, :66-68) and zero occurrences of `mov_commands`. staff-engineer.md uses `mov_commands`/`movCommands` 75 times and contains zero bracketed-format instances. mov-verification-taxonomy.md:476-481 shows the structured JSON shape. B3 confirmed against live card XML that the structured form is current. Verified independently for this synthesis: `modules/kanban/kanban.py:734-736` requires the `mov_commands` array structurally and `kanban.py:1419-1420` errors on the `movCommands` spelling specifically — so a card authored per card-creation.md's documented convention would fail CLI validation. That file's worked examples and its ✅/❌ AC-quality pairs at card-creation.md:51-60 therefore teach a convention that cannot be used.

**CT-6 (within-file, correctness defect). scribe.md and ai-expert.md contradict themselves in consecutive sentences.** scribe.md:41 and ai-expert.md:51 both state that CLAUDE.md "is already injected into your context … you may skip the explicit file reads below." The immediately following lines say "**FIRST, read these files to understand the environment:** 1. `~/.claude/CLAUDE.md` … (ALWAYS read this) … **Read them BEFORE doing anything else.**" One sentence says skip; the next says read first, always, before anything. Both files carry the contradiction verbatim. Live confirmation for this synthesis: ai-expert.md's body is this session's own system prompt, and both statements are present in it.

**CT-7 (within-file, correctness defect). The same note cites a frontmatter field no agent file has.** scribe.md:41 and ai-expert.md:51 both refer to "an agent definition (the `skills:` frontmatter)." No file in Tier 4 has a `skills:` key; all 17 use `name`/`description`/`model`/`tools`/`mcp`/`permissionMode`/`maxTurns`/`background`. The project's own documentation states the architecture deliberately removed that indirection. The note is a stale carryover describing a mechanism the current design does not use.

**CT-8 (cross-file). Business agents disagree on whether to read CLAUDE.md.** finance.md:35 and marketing.md:35 state it is already injected and skippable. lawyer.md:33-37, under a `CRITICAL` label, instructs an active read of both CLAUDE.md files. All three carry identical `background: true` frontmatter, so both cannot be optimal guidance for the same runtime.

**CT-9 (cross-tier). Circular "comprehensive reference."** kanban-cli/SKILL.md:254 states the comprehensive banned-patterns reference lives in staff-engineer.md § Card Management — Card Fields. staff-engineer.md:2194 states, for the BSD/coreutils sub-list, that the full list lives in kanban-cli/SKILL.md. Each names the other as authoritative for overlapping content; no terminal single-sourced list exists. B6 found no contradictory guidance on any of ~10 cross-checked items, so this is a maintenance and navigation defect rather than a content disagreement.

**CT-10 (cross-tier, correctness defect). A 366-line reference document is unreachable from either coordinator prompt.** edge-cases.md has zero inbound pointers from staff-engineer.md or senior-staff-engineer.md, verified by B3 with an exhaustive case-insensitive sweep. Its sole inbound reference anywhere in the eleven-file set is understanding-requirements.md:65, reaching one of eight sections via a two-hop path. Meanwhile edge-cases.md:361-366 presents itself as a peer of delegation-guide.md, parallel-patterns.md, and review-protocol.md — all three of which are directly pointed to.

**CT-11 (within-file, correctness defect). smithers describes two incompatible models of what survives a wakeup.** smithers/SKILL.md:48 states the ScheduleWakeup gap "spawns a fresh agent context where in-memory variables do not persist," which is the stated justification for externalizing three flags to files. smithers/SKILL.md:56 instructs "On ScheduleWakeup continuations, recall counter values from the conversation context" — and per `:35`, the counters *are* the conversation-context state ("Most state lives in conversation history"). If the post-wakeup context is genuinely fresh, there is no history to recall from. The file never reconciles the two, and the practical consequence — whether `cycle`, `fix_count`, and `stagnation_count` survive a wakeup or silently reset — is unresolved by the text.

**CT-12 (cross-file, correctness defect). Two agent definitions omit the incremental-criteria-check instruction that the other fifteen carry.** The Output Protocol bullet "🚨 Call `kanban criteria check` after completing each acceptance criterion" appears in 15 of 17 agent files (debugger.md:935, scribe.md:697, ai-expert.md:647, researcher.md:501, qa-engineer.md:337, and all seven `swe-*` plus the three business agents). visual-designer.md:219-223 and product-ux.md:161-165 open Output Protocol directly with "Return findings as direct text output," skipping it entirely (B5). Neither file instructs incremental criteria checking anywhere. Both remain subject to the hook-enforced AC review at `default.nix:1003`, so the consequence is a failed gate rather than an unverified card.

**CT-13 (cross-tier). A rostered team member has no prompt file.** `CLAUDE.md:521` lists `ac-reviewer` among Support team members. No `agents/ac-reviewer.md` exists (B5, `fd`, zero output). It appears in code only as a `KANBAN_AGENT` sentinel short-circuiting the sub-agent bootstrap (`default.nix:169-174`) and as a leftover cleanup line (`default.nix:1244`).

**CT-14 (cross-file). `allowed-tools` is applied inconsistently across skills with comparable risk.** manage-pr-comments/SKILL.md:5-7 declares `allowed-tools` for read/reply/resolve operations. agent-browser/SKILL.md:4 declares a long explicit allow-list. review-pr-comments/SKILL.md:1-5 declares **none**, despite performing `git add`, `git commit`, `git push`, and `gh api --method POST` per its own Hard Prerequisites at review-pr-comments/SKILL.md:22-25. That file compensates with a body-level instruction to verify `permissions.allow` manually (:17-30) — an instruction the model must remember, not a frontmatter-level mechanism.

**CT-15 (within-file, soft). senior-staff-engineer.md tells the reader not to reconstruct crew syntax from memory, then reproduces ~340 lines of crew procedure.** :19 says exhaustive syntax lives in the `/crew-cli` skill and should be consulted directly. :570-909 is a large body of crew mechanics. B2 notes both can be simultaneously true if the skill covers syntax and this file covers decision-making, which :19's own wording supports — but no boundary statement says which knowledge belongs where. Verified for this synthesis: `crew-cli/SKILL.md` is `SessionStart`-injected for `sstaff` sessions (`default.nix:1121-1130`), so its body is already present when senior-staff-engineer.md tells the reader to go consult it — the pointer is largely redundant for its primary audience, and B6 reached the same conclusion about both CLI-reference skills' description-based auto-invocation triggers.

**CT-16 (within-file, soft, framing). The 95%/5% time-allocation claim versus the prose footprint of exceptions.** staff-engineer.md:13 states "95% conversation and coordination, 5% rare operational exceptions." `## Rare Exceptions` at :2774-2796 enumerates a non-trivial permitted set, and `## Hard Rules` alone spans 265 lines (:92-357) of exception-adjacent carve-outs. B1's judgment: not a contradiction, since the split describes session time and not word count, but a reader measuring "rare" by prose footprint would find the framing surprising.

**CT-17 (within-file, documented exception, not a defect). "Never end a turn idle" versus mandated stopping points.** staff-engineer.md:1242 states "KEEP WORK FLOWING. Never end a turn idle when there is a known next action," then immediately carves two exceptions. The document mandates stopping for AskUserQuestion in numerous places (:1093, :1265-1332). B1 confirms these are explicitly reconciled at :1242 itself; the entry is recorded only because the high density of mandated stopping points sits in the same file as the keep-flowing framing.

**CT-18 (within-file, documented and self-resolved). swe-infra.md is the only file that anticipates and resolves its own internal tension.** swe-infra.md:90 states its Verification/Experiment-Safety hard rule "takes precedence over the general 'Always Be Curious' mindset (Code Quality Standards) and over the chaos engineering / fault injection expertise framing," naming both competing sections (:201, :241-242) and declaring which wins. B4 notes no other file contains a comparable precedence statement, including swe-security.md and swe-sre.md, which combine similar exploratory framing with scope-widening temptation.

**CT-19 (structural warts).** delegation-guide.md has two `## References` sections with different content (:120, :257) — the only duplicate-heading instance in Tier 3. understanding-requirements.md:1 and :3 duplicate the same title across H1 and H2. pr-review-watcher/SKILL.md documents the same deprecated field as inert twice (:43, :133) rather than removing it.

**CT-20 (measurement discrepancies between inputs, reported not resolved).** B1 gives staff-engineer.md 220 `§` marks; B2 gives 188 for the same measurement — unresolved. B1 gives case-sensitive MUST/NEVER/ALWAYS as 66/21/5; B2's table gives 159/154/73 case-insensitively for the same file — different metrics, inconsistently labeled. Bold spans are counted as occurrences by B1/B2/B3/B7 and as matching lines by B4, so no corpus total is computable. The card's 23,402-line corpus figure differs from this document's 23,482 by exactly the two `pr-review` supporting files. The card brief describes B3's docs set as ten files; there are nine.

**Added by the amendment, same category.** B8's two bold figures are in different units from each other: its 150 for the project-root `CLAUDE.md` is a `**` *delimiter* count (75 spans), while its 47 for `TOOLS-DETAILED.md` reproduces under neither delimiters (110) nor spans (55) but exactly under line-start-bold and colon-label-bold. B8 also mischaracterizes B3's 120 for the global `CLAUDE.md` as a raw delimiter count when it reproduces exactly as a *span* count and not at all as a delimiter count (242) — which means the "B3 counted occurrences via `rg -co`" note in § Authoring Style Profile understates the compatibility: B3's unit is spans, the same as B1's, B2's, and B7's. The consequence for the reader is a genuine one: **the relative bold-density ordering of the three shared-layer files inverts depending on which convention is used**, so B8's conclusion that the project-root `CLAUDE.md` is "the most bold-dense of the three" does not hold, while its conclusion that `TOOLS-DETAILED.md` is the sparsest does. Corrected figures and the full five-convention comparison are in § Authoring Style Profile. Separately, the original synthesis's own 23,482/42 grand total was internally inconsistent with its Tier-1 subtotal of 917 across 2 files; that is reconciled in § Configuration Inventory and the corpus figure is now 24,210 across 44 files.

**CT-21 (cross-tier, correctness defect — added by the amendment). A 341-line hand-authored reference file is reachable from nothing, and two of the three tools it documents no longer exist in the form it describes.** `modules/claude/global/TOOLS-DETAILED.md` is not merely unreferenced; it has drifted out of sync with what the repository ships, which is the expected failure mode for a file nobody consults or maintains. The orphan half is established in § Configuration Inventory (Unconsumed) — a repo-wide `rg -i 'TOOLS-DETAILED'` excluding `.git` and `.scratchpad` returns exactly one path, this document, re-verified for the amendment; no `.nix` file references it; no wildcard copy rule sweeps it up; and unlike its sibling `TOOLS.md` it has no generator, so it is hand-authored source rather than build output. The staleness half is three findings:

- **`burns` is documented as a live, invokable shellapp that does not exist.** TOOLS-DETAILED.md:7-62 gives it 57 lines of Purpose / Command / Usage / Configuration table / Behavior / Exit Codes / Examples / Related Commands treatment. Evidence, re-verified for this amendment: `fd -i burns` from the repository root returns **zero files**; `rg -n -i 'burns' modules/claude/default.nix` returns exactly four hits, one an unrelated comment about detecting "Burns/Ralph" sessions (`default.nix:18`) and three **cleanup lines actively deleting old burns-branded artifacts** (`default.nix:1262` `rm -f ~/.claude/commands/workout-burns.md`, `:1274` `rm -f ~/.claude/agents/stk-burns.md`, `:1276` `rm -f ~/.claude/commands/stk-burns.md`); and `rg -n 'name = "burns"' modules/` exits 1 with no output, so no `writeShellApplication` or `writePython3Bin` block defines the binary. The repository is actively removing this tool's traces while this file documents it as current.
- **`smithers` is documented with an invocation model that contradicts the live implementation.** TOOLS-DETAILED.md:64-157 documents it as a bare shellapp CLI — `smithers 123`, `smithers --max-ralph-iterations 5 123`, its own exit codes, its own macOS notification sounds. The actual implementation is `modules/claude/global/skills/smithers/SKILL.md`: re-verified for this amendment, `fd -i smithers` returns only that skill directory, and `rg -n 'name = "smithers"' modules/` exits 1 with no output. staff-engineer.md:380 and :516 document `/smithers` as a Skill-tool-invoked exception skill that explicitly cannot be delegated as a background sub-agent. The documented exit-code, environment-variable, and notification interface describes a surface that does not exist.
- **Only `prc` is current.** TOOLS-DETAILED.md:159-338 matches a live shellapp — `prc` is defined at `modules/claude/default.nix:37` (`pkgs.writers.writePython3Bin "prc"`, verified) — and is consistent with project `CLAUDE.md:143`.

**One further independent orphan signal.** Project `CLAUDE.md:143` documents `prc` and routes the reader to the `/manage-pr-comments` skill for usage documentation, even though TOOLS-DETAILED.md:159-338 holds a materially deeper `prc` reference — full subcommand catalogue, 19-field JSON data model, rate-limiting notes. The repository's own cross-reference network bypasses this file even where its content is the deepest available (B8).

**Recorded negative finding.** B8 found **no** tension between either newly-covered file and the SOLID / Ports-and-Adapters / DRY / 12-Factor programming-preference sections of the global `CLAUDE.md`. Neither file makes any programming-pattern claim that could conflict; both are purely operational and reference in nature. This is recorded so a later reader does not re-investigate it.

---

## Workflow Invariants To Preserve

**This is the contract that protects the repository owner's stated hard constraint: the way they work must not change.**

Each invariant below states where it is currently defined and — critically — whether it is enforced by prompt text alone or also by a hook or CLI. That distinction determines what a rewrite can silently break. **Prompt-only invariants are the ones a rewording can destroy without any test failing.** All enforcement classifications were verified directly against `modules/claude/default.nix`, `modules/kanban/kanban.py`, and the hook scripts for this synthesis; they are not inferred from the inputs.

### WI-1 — Kanban card lifecycle and its four statuses

**Defined:** `modules/kanban/kanban.py:54` (`COLUMNS = ["todo", "doing", "done", "canceled"]`), `kanban.py:8`; behavioral guidance in staff-engineer.md:1631-2608 (`## Card Management`, 977 lines).
**Enforced by:** **CLI.** The four statuses are directory-backed columns in the CLI. `defer` is a transition back to `todo` (`kanban.py:545` lists it as an event type; `kanban.py:1818` performs it), not a fifth column.
**Rewrite risk:** low. Prompt rewording cannot alter the status set.

### WI-2 — Every acceptance criterion carries an executable verification command

**Defined:** staff-engineer.md:1659, :1665, :1911, :2151 (pointers into the MoV taxonomy); mov-verification-taxonomy.md:8-31 (layered verification model), :476-481 (schema), :330-587 (verification-method catalogue).
**Enforced by:** **CLI, structurally.** `kanban.py:734-736` requires a non-empty `mov_commands` array for a programmatic criterion and forbids one for a semantic criterion; `kanban.py:774` and `:783` are the error paths; `kanban.py:827`, `:836`, `:844`, `:852` require and range-check `cmd` and `timeout` per command; `kanban.py:1419-1420` catches the `movCommands` misspelling with an actionable error. Banned-pattern content validation is also CLI-side: `kanban.py:1258-1276`, with `&&` forbidden at `kanban.py:1376` and `rg -E` detected at `kanban.py:1236`.
**Rewrite risk:** low for the requirement itself, moderate for the authoring guidance. Deleting the MoV-authoring prose (staff-engineer.md:1633-1859, kanban-cli/SKILL.md:31-254) would not produce unverified criteria — card creation would simply fail — so the failure mode is wasted cycles, not silent loss of verification.

### WI-3 — Sub-agents may run only `kanban criteria check` and `criteria uncheck`

**Defined:** all 17 agent definitions state it (swe-frontend.md:17, debugger.md:19-31, scribe.md:15-27, ai-expert.md:15-27, researcher.md:15-27, qa-engineer.md:15-27, visual-designer.md:15-27, product-ux.md:15-27, finance.md:15-27, marketing.md:15-27, lawyer.md:15-27, and the six other `swe-*` files at line 15).
**Enforced by:** **hook.** `modules/claude/kanban-subagent-cmd-hook.py:392` allows only those two subcommands; `:496` is the denial message. Registered as a `PreToolUse(Bash)` hook at `default.nix:1066`.
**Rewrite risk:** low. Double-covered by prompt and hook.

### WI-4 — Acceptance criteria are independently reviewed before a card can close

**Defined:** staff-engineer.md:1333-1384 (`## AC Review Workflow`), including the hedge-word rejection rule at :1381.
**Enforced by:** **hook.** `default.nix:991-1005` registers four `SubagentStop` hooks including `kanban-subagent-stop-hook` with a 600-second timeout; `default.nix:350` describes it as running "dual-loop AC review via haiku before allowing agent stop." The `ac-reviewer` system-agent short-circuit at `default.nix:169-174` is part of the same mechanism.
**Rewrite risk:** low for the gate, moderate for the coordinator's handling of its results. Note edge-cases.md:38 states in prose that the hook handles `kanban done` automatically in normal flow — a scoping caveat buried mid-paragraph with no heading signalling it.

### WI-5 — Delegation-only posture of the coordinator tiers, with opposite postures per tier

**Defined:** staff-engineer.md:3 and :7 (frontmatter and opening), :17-19 (operating mode, "delegate nearly exclusively" plus named carve-outs), :122 (`### 3. Implementation`, the absolute delegation rule: every work card MUST delegate, "No exceptions for size, simplicity, or convenience"), :2774-2796 (`## Rare Exceptions`). For the other tier, the posture inverts: senior-staff-engineer.md:41 ("Never use the Agent tool"), :51 (Senior Staff MAY use kanban plus direct sub-agent spawning in narrow cases).
**Enforced by:** **split.** The background-execution half is hook-enforced: `kanban-pretool-hook.py:1060-1094` denies foreground Agent launches and injects `run_in_background: true` via `updatedInput` rather than validating the incoming value. The "delegate rather than implement yourself" half is **prompt-only** — nothing prevents a coordinator from editing source files.
**Rewrite risk:** **high.** Two tiers hold opposite rules about the same tool and both must survive. B1 also notes a reader encountering only staff-engineer.md:17-19 could believe the exceptions are broader than :122 later clarifies.

### WI-6 — Card content reaches the sub-agent by platform injection, not by paste

**Defined:** `default.nix:56` (comment), `default.nix:1030-1038` (`PreToolUse` matcher `Agent`).
**Enforced by:** **hook.** `kanban-pretool-hook.py:884-899` documents the critical constraint that `updatedInput` must carry all original `tool_input` fields because Claude Code replaces rather than merges — omitting `run_in_background`, `subagent_type`, `model`, or `description` silently reverts them.
**Rewrite risk:** low, and the mechanism is invisible to prompt text.

### WI-7 — Mandatory review protocol and its tiers

**Defined:** staff-engineer.md:1472-1526, with the tier table at :1486 and the STOP condition plus its three exclusions at :1486-1488; the fatigue-escalation clause at :1478; `Review Output Handling` and `After Review Cards Complete` at :1549-1587 with a Blocking/High/Medium/Low decision table. Full detail in review-protocol.md:7-68 (Tier 1/2/3 keyword-match tables), :71-105 (deep dive), :107-259 (three worked examples), :261-336 (five result formats), :342-388 (conflict handling), :390-430 (when to skip), :432-514 (prompt-file two-part review), :518 (Post-Review Decision Flow). Mirrored, incompletely, at senior-staff-engineer.md:2357-2379.
**Enforced by:** **prompt only.** No hook and no CLI subcommand gates it. Verified: no reference to review tiers or review gating exists in any hook script or in `kanban.py`.
**Rewrite risk:** **highest.** This is a multi-hundred-line protocol with zero mechanical backstop, and it has already drifted between the two coordinator files (CT-4). Any rewrite must verify both copies, or consolidate to one, and must preserve the three STOP-condition exclusions at staff-engineer.md:1486-1488 specifically, since those are what keep security-perimeter work from being wrongly exempted.

### WI-8 — Permission-gate recovery flow

**Defined:** staff-engineer.md:1079 (`### Permission Gate Recovery`), :1093 and :1105 (AskUserQuestion mandatory, exactly two options, "No exceptions"). Full protocol in delegation-guide.md:7-118 — Detection/Choice/Execution at :17, sequential gates at :31, worked AskUserQuestion example at :39-65, scoped authorization at :69, pattern format at :79-91 with word-boundary semantics at :89, expanded-scope requests at :93, cleanup at :97, re-launch versus redo at :101, pre-approval patterns at :108 — which explicitly disclaims authority to staff-engineer.md at delegation-guide.md:122.
**Enforced by:** **mixed.** The mechanism is CLI-backed: `modules/claude/perm.py:184` (`cmd_allow`), `:210` (`cmd_always`), and a `SessionStart` hook wires per-session permission state at `default.nix:214`. The **decision protocol** — stop, present exactly two options via AskUserQuestion, execute, resume — is **prompt-only**.
**Rewrite risk:** **high.** Also note B3's open question: nobody has diffed staff-engineer.md:1079-onward against delegation-guide.md:7-118, so an undetected drift of the card-creation.md class may already exist between them.

### WI-9 — Git and PR conventions

**Defined:** CLAUDE.md:29 (never skip hooks, including the human-delegated-bypass prohibition and the AskUserQuestion-options prohibition), CLAUDE.md:395-405 (`## PR Creation`, draft-only), CLAUDE.md:407-440 (`## PR Descriptions`, two questions, banned-phrasing list), CLAUDE.md:442-449 (`karlhepler/` branch prefix), CLAUDE.md:457-465 (Actions SHA pinning). Coordinator-tier restatements at staff-engineer.md:223-244 (`### 7. Never Bypass Git Hooks`, with the human-delegated clause at :236 and the AskUserQuestion cross-reference at :243) and staff-engineer.md:2654-2695 (`## PR Descriptions (Operational Guidance)`), plus the catalogue entries at staff-engineer.md:2806 and :2867.
**Enforced by:** **split.** Hook-skip flags are **hook-enforced**: `modules/claude/git-no-verify-hook.py:61` defines `_BYPASS_FLAGS`, `:331` is the denial message, `:321` logs bypasses; registered at `default.nix:1058`. Draft-first, the branch prefix, and the PR-description phrasing rules are **prompt-only** — verified, a search for `draft` across the hook scripts and `default.nix` returns nothing.
**Rewrite risk:** **high for draft-first and the description rules**, low for hook-skip. The banned-phrasing list at CLAUDE.md:407-440 is particularly exposed: it is a specific, enumerated list with no mechanical check.

### WI-10 — Structured question protocol for user decisions

**Defined:** staff-engineer.md:1265-1332 — 67 lines, six numbered sub-rules (AskUserQuestion tool only, one question per turn, ELI5 preamble, `(Recommended)` first option, free-form escape hatch), two worked examples at :1286 and :1321, explicit failure-mode callouts at :1280 and :1316. Restated in full at staff-engineer.md:517, again at :2808, applied to permission gates at :1093 and :1105, cross-referenced at :243 and :506. In the other tier: senior-staff-engineer.md:2708-2851, with the five-element ELI5 checklist at :2728 and absolute-emphasis clauses at :2724, :2726, :2743, :2781. Reinforced in delegation-guide.md:39-65 and in pr-review-watcher/SKILL.md:315 (`AskUserQuestion Discipline`).
**Enforced by:** **prompt only.** Verified: `AskUserQuestion` appears in six `.md` files and in **zero** hook scripts or CLI sources.
**Rewrite risk:** **highest, alongside WI-7.** This is simultaneously the most-restated rule in the corpus (roughly 21 citations in staff-engineer.md alone) and the least mechanically protected — a combination that is itself evidence the author does not trust prompt-only enforcement here. A rewrite that consolidates the restatements must not lose any of the five component requirements.

### WI-11 — Parallel-execution and file-conflict scheduling discipline

**Defined:** staff-engineer.md:1130-1167 (`## Parallel Execution`), :829 and :831 (create ALL cards first in the same response turn, then launch ALL agents; the literal next N tool calls must be Agent launches). Full detail in parallel-patterns.md:9-10 (same-message equals parallel, sequential messages equal sequential — the file's single load-bearing statement), four numbered patterns at :14, :105, :174, :228, three anti-patterns at :260 (sequential dependencies), :284 (same file), :309 (shared config), and conflict-detection heuristics at :381. Conflict-analysis worked examples in delegation-guide.md:127-183.
**Enforced by:** **mixed.** The file-conflict half is **CLI-enforced**: `kanban.py:1818` and `:1848` defer a card back to `todo` when its `editFiles` set collides with an in-flight card owned by another session, printing the conflicting path and card number. Batch atomicity and the parallel-versus-sequential judgment are **prompt-only**.
**Rewrite risk:** moderate. The dangerous half — two agents editing one file — is CLI-guarded; the judgment half is not.

### WI-12 — Worktree confinement and worktree-bound sessions

**Defined:** CLAUDE.md:37-51 (`### Worktree Confinement`, with the enumerated prohibited-target categories); staff-engineer.md:1168-1199 (`## Worktree Discipline`); senior-staff-engineer.md:337 (`### 15. Staff Sessions Are Worktree-Bound`). senior-staff-engineer.md has no `Worktree Discipline` section of its own and cross-references staff-engineer.md's copy by name at :347 — a file its own context does not contain.
**Enforced by:** **prompt only.** No hook or CLI check found.
**Rewrite risk:** **high**, compounded by the cross-tier reference to an absent file.

### WI-13 — Improvement-note capture loop

**Defined:** staff-engineer.md:388-473 (`## Claude Improvement Reporter`, five-field format Context / What happened / Expected / Proposed fix / Trigger, tag specified at :412, the `claude-improvement-failed` counterpart noted at :446), :1438 (file a note on each authoring bug), :1456 (recurring authoring traps each have their own note), :1589-1630 (`### Post-Review Learning Pass`), :1602 (drafting, five-field format, artifact targeting), :1605 (filing mechanics, sequential one-at-a-time for two or more notes, autonomous filing plus the mandatory transparency rule), :2899 (bash-pattern codification sister-rule), :2893-2913 (`## Self-Improvement Protocol`). In the other tier: senior-staff-engineer.md:2412-2417 (default versus tactical-work exception), :2585. Supporting detail in self-improvement.md:3 (thesis), :5 (recognition triggers), :13 (automation priority chain), :25 (protocol), :41 (five anti-patterns).
**Enforced by:** **prompt only**, and dependent on a coordinator-only capability. The filing mechanism is an MCP tool (`mcp__notes__upsert_note`, staff-engineer.md:1605), and the always-injected layer states no sub-agent can reach any MCP server. Sub-agents can therefore draft notes to scratchpad but cannot file them; the coordinator must.
**Rewrite risk:** **high.** Prompt-only, split across two tiers, and structurally dependent on a capability only one tier has. staff-engineer.md:1603 also notes the Notes-MCP constraint separately at :1603 — one of three places the same MCP limitation is anchored to a different concrete tool.

### WI-14 — The 7-field sub-agent final-return contract

**Defined:** staff-engineer.md:1016-1078 — the literal blockquoted template at :1020-1034 to be pasted VERBATIM, the card-type applicability table at :1038-1044, three worked examples at :1047-1077. Analogue at senior-staff-engineer.md:1365, which adds a git-ownership disclaimer sub-agents must follow.
**Enforced by:** **prompt only, and at the delegation-prompt level specifically.** Zero of the 17 agent definitions carry it (CT-3), so the contract exists solely in text the coordinator composes per launch.
**Rewrite risk:** **high and asymmetric.** Deleting or altering the template in staff-engineer.md changes the contract corpus-wide instantly, with no agent-side copy to fall back on and nothing to detect the loss.

### WI-15 — Exception-skill routing: Skill tool versus Agent delegation

**Defined:** staff-engineer.md:370-387 (`## Exception Skills (Use Skill Tool Directly)`, a table), with checklist triggers at :482 and :500. Project documentation enumerates the exception and workflow skills and the reason they have no agent definition.
**Enforced by:** **prompt only.**
**Rewrite risk:** moderate. Losing the table would cause a coordinator to attempt Agent delegation to a skill that has no agent definition.

### WI-16 — Search-tool and shell discipline

**Defined:** CLAUDE.md:372-385 (`rg` not `grep`, `fd` not `find`, plus the `rg -E` footnote), CLAUDE.md:343-355 (`## Bash/Shell Guidelines`, one command per Bash call, no standalone `cd`), CLAUDE.md:356-363 (no `sh -c` wrapping). Card-authoring extension at staff-engineer.md:1770 and :1930.
**Enforced by:** **mixed.** The `cd`-compound half is **hook-enforced**: `default.nix:1050` registers `bash-cd-compound-hook`, described at `default.nix:366` as blocking `cd <dir> && cmd` and `cd <dir>; cmd`. The `rg`/`fd` preference, the one-command-per-call rule, and the `sh -c` prohibition are **prompt-only**.
**Rewrite risk:** moderate.

### WI-17 — Never Homebrew

**Defined:** CLAUDE.md:7, :15, :144, :387-391; project `CLAUDE.md` restates it as its own section.
**Enforced by:** **prompt only.**
**Rewrite risk:** moderate — and worth recording that this is the corpus's cleanest single-source rule, restated in neither coordinator prompt and correctly deferred to by pointer at agent-browser/SKILL.md:17.

### WI-18 — Destructive-operation prohibitions and the ask-first set

**Defined:** CLAUDE.md:26-35 (`### Outright Prohibitions`, including `perm purge` as user-only and the full never-skip-hooks clause), CLAUDE.md:53-62 (`### Ask-First Operations`: `hms --purge`, `git reset --hard`, `git push --force`, `rm -rf`). Coordinator-tier reinforcement at staff-engineer.md:143 (`### 4. Destructive Kanban Operations`) and anti-patterns.md:124 (`## Destructive Operations`). Project `CLAUDE.md` adds the `--purge` prohibition with its full EXIT-trap rationale.
**Enforced by:** **prompt only**, except the hook-skip subset covered under WI-9.
**Rewrite risk:** **high.** These are irreversible operations guarded entirely by text.

### WI-19 — Session bootstrap and post-compaction board re-injection

**Defined:** `default.nix:1102-1132` (four `SessionStart` hooks: `claude-session-start-hook` piping through `kanban session-hook` at `default.nix:190` and `perm session-hook` at `default.nix:214`; `senior-staff-cron-hook`; `crew-lifecycle-hook` readiness sentinel; `skill-autoload-hook`) and `default.nix:1133-1148` (`PostCompact` board re-injection).
**Enforced by:** **hook, entirely.** No prompt text is required for any of it.
**Rewrite risk:** **none from prompt rewriting.** Recorded here so a rewrite does not mistakenly try to re-implement in prose what is already mechanical.

---

## Coverage Gaps

**What this document does not cover, and why.**

### Gaps closed by the 2026-07-27 amendment

Both gaps below were listed as open by the original synthesis. Each is now closed, and the original wording is retained so a later reader can see what was closed and by what.

**CLOSED — "Files no inventory card reached."** The original entry read: two prompt-bearing files were outside all seven inputs' scopes, the project-root `CLAUDE.md` (387 lines) and `modules/claude/global/TOOLS-DETAILED.md` (341 lines), and neither file's authoring style, redundancy, or contradictions had been characterized — together 728 lines. **B8 characterized both in full.** Their inventory rows, structure, and injection status are in § Configuration Inventory; their technique counts are folded into § Authoring Style Profile; the project-root file's overlap with the global file is § Redundancy And Duplication Map Category 5; and `TOOLS-DETAILED.md`'s orphan and staleness defects are CT-21. **There is no longer any known prompt-bearing file in `modules/claude/global/` or at the project root that this document has not characterized.**

**CLOSED — "The accretion hypothesis is untested."** The original entry read: no input examined git history, every claim in § Accretion Analysis rests on textual form, and whether the compensatory passages were added in later commits following an observed failure is unknown and answerable with `git log -p`. **B9 tested it.** Question (a) is now reported as a finding with a verdict, a per-file confidence level, and cited commit evidence in § Accretion Analysis § Question (a). The verdict is file-dependent rather than corpus-wide, and it includes one traced counter-example. Question (b) — whether the resulting form is good practice — was never in scope for this document and remains open for the gap analysis by design, not by omission.

### Gaps that remain open

**Redundancy was audited exhaustively for no file.** B1 audited 6 named rules out of 63 `###` subsections in staff-engineer.md, and states its ~2-2.5% restatement estimate is a lower bound for those six rules only, with no claim about the other ~85% of that file. No equivalent exhaustive pass exists for any file in the corpus.

**Two suspected drifts are unmeasured.** B3's first open question: nobody diffed staff-engineer.md:1079-onward against delegation-guide.md:7-118, the two Permission Gate Recovery sections, even though delegation-guide.md:122 explicitly names the former as authoritative. This is the exact structural setup that produced the card-creation.md defect (CT-5), so a comparable drift may already exist and be unrecorded. B3's second: the roughly 390 internal `§` anchors inside the two 3,000-line output styles were never validated against actual headings, so an unknown number of internal pointers may be dangling.

**Metric definitions are inconsistent across inputs**, so several § Authoring Style Profile aggregates are approximate rather than exact. Bold spans were counted as occurrences by four inputs and as matching lines by one. MUST/NEVER/ALWAYS were counted case-sensitively by two inputs and case-insensitively by one for the same file. The `§`-count discrepancy for staff-engineer.md (220 versus 188) is unresolved. B1 additionally flags that its own code-fence line count for staff-engineer.md is approximate, because its parser toggled state only on flush-left fences and so mis-bucketed the 38 indented fences nested inside checklist items.

**Questions the inputs left open.** Whether `ac-reviewer` has any LLM prompt body at all or is purely an environment-variable sentinel (B5, first). Why swe-frontend.md:9 and swe-backend.md:9 get `maxTurns: 105` while five siblings get 100 (B4). Why the regex-review section appears in exactly 4 of 7 `swe-*` files. Why three `swe-*` files carry zero code examples. Whether the in-file `When Done` sections in the agent tier are load-bearing at runtime or vestigial, given the coordinator injects its own format (B4, B5). Whether the `.kanban/` and Output Protocol boilerplate is templated at some authoring step or hand-copied per file (B6, first). Which of smithers' two state models is correct, which requires the ScheduleWakeup implementation semantics rather than the skill text (B7, first). Whether `disable-model-invocation` and `user-invocable` frontmatter fields are used anywhere in the repo (B6).

**Gaps the accretion investigation left open (B9).** Six, in rough order of how much each could move the verdict.

1. **The 116 commits in the April-May 2026 growth spike were prefix-classified but not individually read for content.** B9 names this as the strongest lever that could change its verdict: if that window turns out to be substantially reorganizational — moving, renaming, and restructuring existing text — rather than additive, the growth-curve support for the hypothesis weakens. Not pursued given the card's stated step priority and tool-use caps.
2. **The 89 non-`claude-improvement` `fix(...)`-prefixed commits to `staff-engineer.md` were counted but not read**, as were the smaller equivalent sets for the other three census files. B9 confirmed at least one false positive in its own counts — `50c4058 fix(claudit): CAST strftime epoch to INTEGER for Grafana time-range filters`, a metrics-pipeline fix with no prompt content, landed in the `CLAUDE.md` fix bucket — which is why the 23.1% figure is an **upper bound**. The magnitude of the same error in the `staff-engineer.md` bucket is unmeasured.
3. **No growth curve exists for the always-injected layer.** B9 sampled growth for `staff-engineer.md` and `senior-staff-engineer.md` only, as its own card instructed; `kanban-cli/SKILL.md` and `modules/claude/global/CLAUDE.md` were not sampled. The step was scoped, not dropped for budget — but the effect is that the one file whose verdict is weakest, and where a curve would be most diagnostic, has none.
4. **Four of the eight signatures in § The signatures observed remain untraced to an introducing commit.** B9 traced four, per its card's stated minimum. Untraced: the per-incident entries in `## Critical Anti-Patterns`, the human-delegated-bypass closing clause at staff-engineer.md:236, the named-`PLA-####` incident anchoring, and user-voice/SKILL.md's verbatim-user-correction catalogue. Given that the one signature traced to a *generic* commit was the 🚨 siren, these four could resolve in either direction.
5. **Two files contributing to the accretion footprint estimate were never censused** — anti-patterns.md (~120 lines) and user-voice/SKILL.md (~85 lines). Their inclusion still rests on textual form alone.
6. **The census regex undercounts by construction.** Commits that fix a past failure without a `claude-improvement:` or `fix(...)`/`fix:` prefix — B9's example, a hypothetical `refactor: correct broken permission logic` — are invisible to it. B9 flagged this in its method section and did not correct it.

**Gaps the missed-files characterization left open (B8).** Four.

1. **No repo-wide staleness sweep exists.** B8 found that 2 of the 3 commands `TOOLS-DETAILED.md` documents have drifted out of sync with what the repository ships (CT-21), but its search was scoped to its two assigned files. **Whether any other file in the corpus documents retired tools or superseded interfaces with the same pattern is unknown** — exactly one of 44 files has been checked on that axis. This is the most actionable gap the amendment adds.
2. **Whether the ≈20-line Team Member Terminology duplicate core was deliberate design or organic drift is undetermined.** B8 consulted no version history for it, the same caveat B3 raised for the shared layer generally. B9's `git log -S` method could answer it but was not pointed at that section.
3. **What should happen to `TOOLS-DETAILED.md`'s `burns` and `smithers` sections — deletion versus rewrite — is a policy question** B8 correctly declined, and which this document declines for the same reason it declines every remedy: it describes rather than proposes.
4. **The corpus-wide bold total remains uncomputable, now across more unit conventions than before.** Bold has been measured as spans (B1, B2, B3, B7), as matching lines (B4), and as `**` delimiters plus at least one line-start or label-form variant (B8). CT-20 records the corrected per-file figures; no total is offered.

**Deliberate scope exclusions.** No domain content was evaluated for correctness — financial frameworks, legal citation tiers, GTM frameworks, SRE formulas, and CLI syntax were characterized structurally only. No file outside `modules/claude/global/` and the project-root `CLAUDE.md` was inventoried; hook scripts and CLI sources were read only to classify enforcement in § Workflow Invariants To Preserve, not characterized as artifacts in their own right. And per this document's stated posture, nothing here evaluates whether any rule is good policy or proposes any change.

**One note on process, for the reader six months from now.** During this synthesis, a harness-injected block of MCP-server instructions and a date notice appeared in the working context between tool calls. These were context reminders from the harness, not content of any file read — no `.scratchpad/B*.md` input and no configuration file contains injected instruction text, and no file:line can be cited for them because they do not exist in any file. They are recorded here only so a future reader who sees similar artifacts does not mistake them for a finding about the corpus.

The same thing happened during the 2026-07-27 amendment pass: a block of MCP-server instructions (Context7, Datadog, incident.io, Linear) and a current-date notice appeared in the working context immediately after a `Read` tool call. These were harness-injected context reminders, part of the agent's context rather than content of the file being read. **No file:line can be cited for them, because they appear in no file** — neither `.scratchpad/B8-missed-files.md`, nor `.scratchpad/B9-accretion-history.md`, nor this document, nor any configuration file in the corpus contains injected instruction text. Both amendment inputs do open with their own author-written meta-review lines (`.scratchpad/B8-missed-files.md:1` and `.scratchpad/B9-accretion-history.md:3`, both noting platform status is not applicable to a documentation card), and those are ordinary file content, not injection.

---

## Amendment Log

**Amendment 1 — 2026-07-27, session `stout-ember`, kanban card #2951.** Written by the `ai-expert` agent. Inputs: `.scratchpad/B8-missed-files.md` (130 lines) and `.scratchpad/B9-accretion-history.md` (159 lines). This was an amendment to the existing 641-line synthesis, not a rewrite: no original finding was deleted, no section was reorganized, and no heading was removed or renamed.

**What changed, by section, and what drove it.**

| Section | Change | Driven by |
|---|---|---|
| Header | Added the two amendment inputs as a second table; added an independent-verification paragraph for the amendment | both |
| § Executive Summary | Corpus figure corrected from 23,482/42 to 24,210/44; Tier 1 restated as two files / 917 lines; the "untested hypothesis" framing replaced with B9's verdict and its file-dependence; a fifth standout point added for the relevance-distribution finding | both |
| § Configuration Inventory | Tier-1 obsolete-coverage note replaced; project-root `CLAUDE.md` structure and relevance-breadth table added; new non-tier "Unconsumed" subsection for `TOOLS-DETAILED.md`; grand total rebuilt as a per-tier table with three superseded figures reconciled | B8 |
| § Architecture Of The System | `TOOLS-DETAILED.md` added to what a sub-agent does not receive | B8 |
| § Authoring Style Profile | Technique data folded into ten subsections: XML/placeholders, bold and siren, MUST/NEVER/ALWAYS, ❌/✅ ratio, code fences, incident anecdotes, output formats, tool-use guidance, cross-references, skeleton conformance, persona. Corpus siren estimate revised from ~50 to ~58. One bold-density figure corrected rather than adopted | B8 |
| § Redundancy And Duplication Map | Intro updated from four categories to five; new Category 5 for duplication between the two always-injected files (≈20 double-paid lines) | B8 |
| § Accretion Analysis | **Largest change.** Question (a) converted from hypothesis to finding, with commit census, four introducing-commit traces, the mechanically-confirmed `kanban-cli`/`crew-cli` asymmetry, the growth curve, per-file confidence, and an explicit "what this finding does not license" subsection. Question (b) given its own subsection and left open. B9 traces cross-referenced into signatures 1, 4, and 5. Footprint estimate retained and re-based on the corrected corpus size | B9 |
| § Tensions And Contradictions | CT-20 extended with the bold-unit finding and the grand-total inconsistency; **CT-21 added** for `TOOLS-DETAILED.md`'s orphan-plus-staleness defect, with per-command evidence; one negative finding recorded | B8 |
| § Coverage Gaps | Two gaps moved to a new "closed" subsection with their original wording retained; ten new open gaps added (six from B9, four from B8); remaining gaps grouped under "Gaps that remain open" | both |
| § Workflow Invariants To Preserve | **Unchanged.** Neither input bore on enforcement classification | — |

**The one input figure that did not reproduce.** B8's bold count of 47 for `TOOLS-DETAILED.md` matches neither the delimiter nor the span count for that file, and its characterization of B3's global-`CLAUDE.md` figure as a delimiter count is also wrong. Corrected figures under five conventions are in § Authoring Style Profile; the discrepancy is filed under CT-20. Every other B8 count — headings, sirens, fences, rule-strength vocabulary, glyphs, checklists — and every B9 figure re-derived (the `CLAUDE.md` census, the `kanban-cli`/`crew-cli` pair, and commit `607de07`) reproduced exactly.

**What the amendment deliberately did not do.** It proposed no change to the repository; it evaluated no rule as good or bad policy; it did not answer question (b) of § Accretion Analysis; it edited nothing under `modules/`; and it did not soften B9's negative result for the always-injected `CLAUDE.md` to protect the original synthesis's framing. Where the amendment's evidence contradicts the original synthesis — the corpus total, the bold-density ordering, and the accretion hypothesis as applied to `CLAUDE.md` — the contradiction is stated plainly and the superseded figure is recorded rather than deleted.
