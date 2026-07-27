# Document D — Implementation Plan

**Status:** durable project documentation. **Written:** 2026-07-27, session `stout-ember`, kanban card #2947. **Scope:** a plan. Nothing under `modules/` was edited to produce it, and no replacement prompt text is drafted here.

**Inputs, all five read in full before any line below was written:**

| Input | Lines | What it supplies |
|---|---|---|
| `docs/v5-migration/A-anthropic-v5-guidance.md` | 2,012 | What Anthropic officially says, quoted and cited (D1–D46, C1–C16) |
| `docs/v5-migration/B-current-configuration.md` | 908 | What this repository is — 24,210 lines across 44 files, five injection tiers, and the nineteen workflow invariants with their enforcement classification verified against source |
| `docs/v5-migration/C-gap-analysis.md` | 1,002 | The diagnosis, as amended: 18 gaps, 9 authority-less proposals, 11 validated practices, 5 contested gaps |
| `.scratchpad/C-verification.md` | 252 | Adversarial verification of Document C. Verdict: *"sound enough to plan from"* with four corrections, all now applied inside Document C |
| `.scratchpad/C-measurements.md` | 140 | Three closed coverage gaps: the session model mapping, D42 `description`-field quality, and severity-gating language |

**Foundation.** `C-verification`'s `## Overall Assessment` says Document C is sound to plan from. Its four required corrections are already applied inside `C-gap-analysis`, so this plan is written against Document C as it now stands. Every change proposed below traces to a gap Document C still carries after amendment. Where this document reaches a conclusion Document C did not, the reasoning is shown and labelled.

**Deployment, for every unit in every stage.** Edit source under `modules/`, `git add` if the file is new, run `hms`, then commit. `hms` is the real validation gate — it runs flake8, which `nix flake check` does not. Never bypass a git hook, and never `git reset --hard`, `git checkout --`, or `git clean` to undo a stage; see each stage's revert procedure.

---

## Executive Summary

**Status: approved, not proposed.** All nine questions this document originally put to the owner were answered on 2026-07-27 and are recorded in § Decisions, which sits immediately before the style guide so a reader meets the decisions before the work. Two of the nine shape everything else and are stated here so no card has to go looking for them.

1. **Cited changes only — Q1(A).** Nothing ships without an Anthropic citation. This is now a hard **constraint on the plan**, not a preference the owner might revisit mid-effort. It closes emphasis register, output-style length, and agent-definition length for this effort entirely. § Q1 Audit walks every surviving work unit against it and states the two admissible bases for a change.
2. **360 lines for the global `CLAUDE.md`, 200 for the project-root `CLAUDE.md` — Q6(B).** These are the **committed numbers**, not a revised proposal awaiting sign-off. The subtraction that forces 360 is shown in § Stage 1 and re-shown there with the decisions applied, so it stays auditable. A tracked follow-on carries the two routes to 200; G12's `PreToolUse` hook work is its gating dependency.

Four stages, in tier order, each used in real work before the next begins. Nothing about how the owner works changes; only how the prompts are written.

**Stage 1 — the always-injected shared layer (2 files, 917 lines).** The highest-leverage change, and the only one with an Anthropic number tied to *adherence* rather than cost. It is also where the arithmetic breaks. The 200-line-per-file target is reachable for the 387-line project-root `CLAUDE.md` and **unreachable for the 530-line global `CLAUDE.md`**: after excluding the 183 lines of protected invariant and Anthropic-prescribed content, and after relocating every one of the 172 candidate narrow-audience lines, the global file floors at **≈358 lines — 1.79x the target**. See § Stage 1 for the subtraction. The committed targets are therefore **200 lines for the project-root file and 360 for the global file** (aggregate 560, a 357-line reduction), with the global overshoot recorded as a reasoned deviation from a soft target. Any card that names 200 for the global file would send an agent hunting 158 lines it may only find inside a protected prohibition. Plausible duration: 1–2 weeks of elapsed calendar time, most of it the owner's soak period. Owner gate: a week of ordinary `staff` and `sstaff` work — the target sign-off gate is discharged by Q6.

**Stage 2 — the two coordinator output styles (2 files, 5,979 lines).** Fix the missing STOP-condition exclusions in `senior-staff-engineer.md` (G11); build the **mechanical sync check** Q5(B) commissions, which is the stage's structural addition and the one change that converts a prompt-only invariant into a mechanically checked one; act on D1/D2 for the checklists now that the model mapping is measured — both coordinator tiers run `--model 'opus[1m]' --effort xhigh`, so Opus 5 guidance governs them; and add the two D13-motivated passages Q3 and Q8 commission. **Two things are closed here rather than decided here.** Consolidating the two output styles is closed by Q5(B): both files stay, with their duplication accepted and mechanically policed. Length reduction is closed by Q1(A): NA3 has no Anthropic authority in either direction, so the 250–300 restated lines in `senior-staff-engineer.md` stay. Plausible duration: 2–3 weeks. Owner gate: two weeks of real coordination work, watching specifically for a suppressed review.

**Stage 3 — the seventeen sub-agent definitions (8,050 lines).** Mostly defect repair: the MCP contradiction and the inert `mcp:` frontmatter field (G3 + G9), self-contradicting sentence pairs (G4), competing return formats (G10), and the one D42 `description` violation. Seventeen disjoint files means this is the most parallelizable stage. Q1(A) closes NA4 and NA7, so **no line-reduction work exists in this stage at all** — every unit is a defect fix or a cited normalization. Plausible duration: 1–2 weeks. Owner gate: every agent type exercised at least once. Q7(C) puts a decision point immediately after unit 3.3: observe WI-14's real failure rate, then decide on the `SubagentStop` structural check with data.

**Stage 4 — the thirteen skills (6,262 lines).** Adopt the supporting-file mechanism, then reduce the seven over-cap files — with **D32** standing as Anthropic authority *against* relocating `kanban-cli/SKILL.md:31-254`, the 223-line banned-pattern catalogue. This is the only stage whose length work survives Q1(A) unaltered, because the 500-line `SKILL.md` cap is stated three times across two official hosts. Plausible duration: 2 weeks. Owner gate: each touched skill invoked once.

**Two decisions add text, and the plan owns that.** Q3(C) adds a motivation passage to `staff-engineer.md:122`; Q8(C) adds a rationale comment to `staff.bash` and `sstaff.bash`. Both are D13 additions and both cut, slightly, against the reduction narrative. They are counted in § Stage 1's recomputed arithmetic and in § Stage 2's unit table rather than omitted for being inconvenient. Q9(B) adds a clause to the one file with the tightest line budget in the corpus, and § Stage 1 shows exactly what that costs.

**At each gate the owner:** approves the stage's unit list; uses the system normally for the soak period; reports any behavior that surprised them. That last item is this plan's only detector for the failure mode it fears most.

**The honest limit.** Rewriting a prompt cannot be proven behavior-preserving. Mechanical checks can prove a rule is still *present*; only the owner can notice that Claude has started doing something differently. § Verification Strategy says which is which and names the rollback trigger.

---

## Decisions

**All nine questions this document originally posed are answered.** Answered by the owner on 2026-07-27, one at a time, and recorded here verbatim in substance. This section is placed before the style guide deliberately: a reader who meets the work before the decisions will re-argue settled questions.

Each subsection states the question in one line, the option chosen, the rationale as the owner gave it, and — the part later cards actually need — the **consequence** for the plan, naming the specific work units added, removed, or reshaped.

**Read the consequences as binding.** Where a decision closes something, it is closed for this effort, not merely discouraged. Where a decision defers something, § Out Of Scope → `### Deferred pending post-Stage-4 review` holds the reasoning so a later effort does not have to re-derive it.

### Q1 — Do changes that rest on our judgment rather than Anthropic's guidance ship?

**Chosen: (A) No — cited changes only, revisited after Stage 4.**

**Rationale as given.** Nothing ships without an Anthropic citation. The owner explicitly accepted the trade-off: the corpus keeps its current emphasis register and both long output styles for now.

**Consequence.** This is the single largest change to the plan, and it is a **constraint** rather than a work item. Six of Document C's authority-less proposals are closed for this effort: **NA1** (emoji sirens), **NA2** (ALL-CAPS and modal intensity), **NA3** (output-style length), **NA4** (agent-definition length), **NA7** (Sonnet prompt bulk — already refuted independently), **NA8** (restatement treated as a substitute for enforcement). Specifically:

- **No scheduled work unit dies.** None of the six was ever a numbered unit. Each was carried as an owner-gated ambition in § Executive Summary, as a conditional permission in SG10 or SG12, or as an explicit non-item in Stage 3's *"Not planned here, deliberately."* What changes is their status: **gated → closed.** Saying five units were deleted would be inventing deletions to make the arithmetic look tidier than it is.
- **SG10's second bucket closes.** *"Change modal intensity, remove a 🚨, or downcase a `NEVER`"* was *"never authorized by this plan… gated on Open Question 1."* It is now closed outright for this effort.
- **SG12's two conditional entries close.** The emphasis-de-escalation entry and the restatement-consolidation entry (the latter also by Q4) become unconditional prohibitions.
- **Stage 2's length-reduction ambition closes.** The 250–300 restated lines in `senior-staff-engineer.md` stay. Combined with Q5(B), Stage 2 now produces *no* net line reduction at all — see § Recomputed Numbers.
- **Stage 3's length-reduction ambition closes.** Every Stage 3 unit is a defect fix or a cited normalization.
- **NA5 survives.** `C-gap-analysis` itself reclassified NA5's three items as plain correctness, and Q1 does not disturb that reclassification. Units 4.8–4.10 stand.
- **NA6 is re-examined rather than closed by default** — see § NA6 Reclassification for the verdict and the evidence.
- **A standing obligation is added:** § The Q1 Audit walks every surviving unit against this constraint and states the two admissible bases for a change. Every later card is executed against that audit as well as against the style guide.

### Q2 — Incident provenance: remove the decorative instances, or leave all of it?

**Chosen: (B) Keep all provenance.**

**Rationale as given.** Chosen for consistency with Q1: provenance removal has no citation. The evidentiary sites in the banned-pattern catalogue are therefore protected **by default rather than by exception.**

**Consequence.**

- **SG4 collapses to two operative categories.** The mechanism sentence stays (D13-protected); provenance stays (no citation to remove it). Category 3, *decorative provenance*, remains a defined category with a stated test but **no removal path** for this effort. SG4 is now a classification rule that never authorizes a deletion — which is worth saying plainly rather than leaving a rewriter to discover it.
- **The option-(C) sweep of the two output styles is closed.** No unit existed; the ambition is gone.
- **`kanban-cli/SKILL.md:180` and `:220` are protected by default.** Under the original recommendation they were protected by construction only because option (C) happened to exclude skills. They are now protected because nothing may be removed anywhere. The *"dozens of per-site judgment calls made correctly"* risk that option (A) carried is eliminated rather than mitigated.
- **Unit 2.4's constraint tightens.** `anti-patterns.md`'s ~120 `Concrete failure:` bullets were governed by *"SG4's category test… for every one of them."* They are now simply retained; 2.4 is a pure `✅`-pairing addition with no deletion component.
- **R8 largely dissolves** — see § Risks And Mitigations, where it is restated rather than removed, because the reasoning still explains why the sites matter.

### Q3 — Is the absolute delegation rule load-bearing, or a cost inefficiency? (CG1)

**Chosen: (C) Keep the absolute delegation rule unchanged AND add its motivation.**

**Rationale as given.** State in the prompt that delegation is the verification boundary, not a cost preference. This is a pure D13 addition with **no behavioral change.** Its purpose is to make the rule survive future readers who encounter Anthropic's contrary example policy and conclude the rule is a mistake.

**Consequence.**

- **CG1 closes with the rule unchanged.** `staff-engineer.md:122` keeps *"No exceptions for size, simplicity, or convenience."*
- **New unit 2.10** adds the motivation passage naming the four mechanisms that direct coordinator work bypasses: `PreToolUse(Agent)` card injection (WI-6), `SubagentStop` AC review (WI-4), the `editFiles` conflict scheduler (WI-11), and the foreground-launch denial (WI-5's enforced half).
- **This ADDS lines** to a Stage 2 file. Output styles have no line target — NA3 is closed by Q1 — so there is no budget to breach, but the addition is recorded in § Recomputed Numbers rather than netted away.
- **A card-level constraint:** 2.10 may add a reason and may not touch the imperative. SG10's first bucket authorizes exactly this shape and its third bucket prohibits softening.

### Q4 — Restatement at successive workflow moments: consolidate, or preserve? (CG2)

**Chosen: (A) Preserve restatement as D11-compliant per-site scope statement. No consolidation. Revisit after Stage 4.**

**Rationale as given.** Preserve; revisit after Stage 4.

**Consequence.**

- **CG2 closes as preserve.** The AskUserQuestion protocol's roughly 21 citations and the backslash-pipe MoV rule's six sites are untouched, in every stage.
- **SG2's bound becomes permanent for this effort** rather than pending an answer. Its final sentence — *"Those are Open Question 4"* — now points at this decision.
- **SG12's restatement entry becomes unconditional.**
- **120–165 measured lines leave the reachable reduction.** They were never in a stage's unit list, so no unit dies; but any later arithmetic that assumed them is wrong. Stated in § Recomputed Numbers.
- **WI-7 and WI-10 keep every catch point.** This is the conservative outcome for the two least mechanically protected invariants in the corpus, which is why it was the recommendation.

### Q5 — Consolidating the two coordinator output styles? (CG5)

**Chosen: (B) Keep both coordinator files, accept the duplication, and add a mechanical sync check.**

**Rationale as given.** A CI or `hms`-time assertion that the shared sections are byte-identical across both output styles. *The observed failure was not that content was duplicated, it was that the duplication drifted **undetected**.* This converts a prompt-only invariant that has already failed silently into one that fails loudly, which is the direction D39 points. G11's fix shape follows from this answer.

**Consequence.**

- **Unit 2.9 is reshaped, not deleted.** It was *"whatever the owner decides on consolidation."* It is now a concrete deliverable: build the sync check. Full specification, including the CI-versus-`hms` recommendation and its validation gate, is in § Stage 2 units.
- **G11's fix shape is now determined.** Copy the three missing STOP-condition exclusions into `senior-staff-engineer.md` *and* bring the shared sections under the check, so the same drift cannot recur silently. Unit 2.1 keeps its opus tier and gains a dependency on 2.9's section markers.
- **Both files keep their 250–300 duplicated lines**, their five identically-titled sections, and their sixteen cross-references into a file the `sstaff` context does not contain. The dangling-reference problem is *not* fixed by this decision; it is baselined by Stage 2's gate check 5 and left standing, because fixing it was option (A)'s job and option (A) was not chosen.
- **The architecture is affirmed:** two genuinely different roles with opposite postures on the same tool, which D40 supports.

### Q6 — Do you accept a 360-line target for the global `CLAUDE.md` instead of 200?

**Chosen: (B) Accept 360 for the global `CLAUDE.md` and 200 for the project-root file, and open a tracked follow-on for the two routes to 200.**

**Rationale as given.** The follow-on investigates whether user-scope path-scoped rules exist, and covers the `PreToolUse` hook work that would let the destructive-operation and worktree prohibitions become a double cover and then be safely shortened. **The owner was explicitly told, and accepted, that this makes the hook work the gating item for ever reaching 200.**

**Consequence.**

- **360 and 200 are committed numbers.** Not a revised proposal. § Stage 1 restates the subtraction with the decisions applied so it stays auditable, and SG8's table already carries them.
- **Stage 1's sign-off gate is discharged.** *"Neither may begin until Open Question 6 is answered"* is satisfied; units 1.4 and 1.5 now block on their ledgers (1.1, 1.2) and on 1.3 only.
- **A tracked follow-on item is added** to § Out Of Scope, naming both routes and identifying G12's hook work as the gating dependency for route 2 — the only Anthropic-endorsed route.
- **Unit 1.0 keeps its place but changes purpose.** Its read-only finding now feeds the follow-on rather than this effort's target. Nothing in Stages 1–4 is planned on its answer either way, which was already true.
- **R5's detector matters more, not less.** With 360 committed rather than proposed, a later card that reads `C-gap-analysis`'s 200 is contradicting an approved number.

### Q7 — Add a `SubagentStop` structural check for the 7-field return contract (WI-14)?

**Chosen: (C) Defer the WI-14 `SubagentStop` structural check until after Stage 3.**

**Rationale as given.** Unit 3.3 is the change most likely to disturb the return contract, and building a hook against three competing formats means specifying a check for a shape that is about to change. Observe the failure rate after 3.3, then decide with data.

**Consequence.**

- **No WI-14 hook work exists in any stage.** § Workflow Invariant Preservation Plan's WI-14 resolution stands unchanged: prompt-only, not treated as hookable, G12's hookable subset remains WI-18 and WI-12 only.
- **A decision point is added after unit 3.3**, before Stage 4's gate: collect the return-shape outcomes from Stage 3 gate check 6 (the live delegation test per touched agent type) and decide then, with a measured failure rate rather than a guess.
- **WI-14's asymmetric risk is accepted through Stage 3**, explicitly and on the record. Document B rates it *"high and asymmetric."* R1's residual risk covers it and is not reduced by this decision.

### Q8 — Run a fresh effort sweep, or keep `--effort xhigh` pinned?

**Chosen: (C) Keep `--effort xhigh` pinned and add a documented rationale in the launcher scripts naming D14's step-up clause.**

**Rationale as given.** No sweep. D16's target is settings reused **without thought**, so recording the reasoning addresses the substance without building an eval harness whose output would not be measurable here.

**Consequence.**

- **New unit 2.11** adds the rationale comment to `staff.bash:12-16` and `sstaff.bash:12-16`.
- **This is the one authorized touch of non-prompt source in the entire plan.** § Out Of Scope's blanket code exclusion is amended for exactly this and nothing else: **comment lines only**, no change to any flag, argument, model alias, or executable line. Any card that reads 2.11 as license to edit a launcher's behavior is misreading it.
- **No sweep, no eval harness.** Unit 2.7's read-only assessment stands as the record of *why* `xhigh` is defensible, and 2.11 puts a pointer to that reasoning where the setting actually lives.
- **This ADDS lines** to two files outside the 44-file prompt corpus, so no line budget is affected. Recorded in § Recomputed Numbers anyway, because the honest count of "what this plan adds" includes it.

### Q9 — `ac-reviewer`: correct the roster entry, or add the missing agent definition?

**Chosen: (C) then (B) — determine first, then add a clarifying clause.**

**Rationale as given.** Run the read-only determination of whether `ac-reviewer` has a dynamic prompt body. Then, if it is a pure sentinel, keep the roster line and add a clause explaining that it is the automatic `SubagentStop` AC reviewer and **not a delegation target** — rather than deleting the line. A clarifying clause is correct under either answer and it prevents the failed delegation attempt.

**Consequence.**

- **Unit 1.3 keeps its place**, and its output now gates a *clause's wording* rather than a *line's deletion*. That lowers the stakes on 1.3 considerably: a wrong answer no longer deletes a real roster entry.
- **Unit 1.4 gains the clause.** Global `CLAUDE.md:521`'s roster line stays; a clause naming `ac-reviewer` as the automatic `SubagentStop` AC reviewer and not a delegation target is added beside it. G16's Stage 1 share is now an addition, not a correction-by-deletion.
- **This ADDS a line to the file with the tightest budget in the corpus.** § Stage 1 re-shows the subtraction with it applied: the floor moves from 358 to 359 against a 360 cap, so slack falls from 2 lines to 1. That is the honest cost and it is not netted against anything.
- **The clause is correct under either answer**, which is the property that makes deferring 1.3 harmless. If 1.3 finds a dynamic prompt body, the clause's wording changes; its existence does not.

### The Q1 Audit — every surviving unit against the cited-changes-only constraint

Q1 is only real if someone walks the surviving units and checks each one can actually cite. Here is that walk. **Two bases are admissible, and naming the second one explicitly is the point of this subsection** — smuggling it in silently would be the failure mode.

1. **An Anthropic citation.** A directive in `A-anthropic-v5-guidance` that the change traces to.
2. **A factual defect** — the prompt text states something about *this repository* that is verifiably false, or contradicts itself, such that the text is wrong independent of anyone's taste.

**Why basis 2 is admissible, stated rather than assumed.** Q1's question was whether *aesthetic or maintainability preference* is sufficient reason to change working prompt text. A statement that is factually false about this repository is not a preference; there is no register in which it is correct. Two independent confirmations that basis 2 is intended to be in scope: `C-gap-analysis` itself reclassified NA5 out of the authority-less set *"as plain correctness"*, and the owner's own Q9 and Q5 answers commission work whose entire justification is a factual defect — a roster entry naming a non-delegatable agent, and a duplication that drifted. If basis 2 were inadmissible, Q9(B) and Q5(B) would be self-contradictory.

**Basis 2 is narrow and does not blur into basis 1.** It licenses correcting a false statement. It does not license shortening, reordering, restyling, or de-emphasizing anything adjacent to the false statement.

| Unit | Basis | The citation or the defect |
|---|---|---|
| 1.0 | 1 | D33's own sentence prescribing path-scoped rules; Document A § Splitting Content on their real context reduction |
| 1.1, 1.2 | 1 | D33 (length↔adherence), D36 (what a CLAUDE.md is for), `/doctor`'s keep-pitfalls test |
| 1.3 | 2 | Feeds G16, a roster entry that may name a non-delegatable agent |
| 1.4 | 1 + 2 | G1 → D33. G2 → D33 + D36. G19 → D31 + D36 + SG2. G16 and the Q9 clause → basis 2 |
| 1.5 | 1 + 2 | Same, plus the D13-protected Trash mechanism as a hard boundary |
| 2.1 | 2 | G11: the rule is present in both files and its exclusions are present in one. A self-contradicting corpus state; D35 (contradictions resolve arbitrarily) corroborates |
| 2.2, 2.3, 2.4, 3.6 | 1 | Document A § Emphasis And Over-Steering finding 3, corroborated on three pages, cross-model |
| 2.5, 2.6 | 1 | D1 and D2, Opus 5, scope fixed by `C-measurements` Measurement 1 |
| 2.7 | 1 | D14 and D16. Read-only |
| 2.8 | 1 | D40's CLAUDE.md-substitution warning — an output style is not the place for project knowledge |
| 2.9 (sync check) | 1 | D39 — prefer a mechanism over prompt text where one is available. Q5(B)'s explicit rationale |
| 2.10 (new, Q3) | 1 | D13 — add motivation. D25 protects the imperative it sits beside |
| 2.11 (new, Q8) | 1 | D14's step-up clause, recorded against D16's reuse-without-thought concern |
| 3.1a/b/c | 1 + 2 | G3: the MCP-reachability claim is false. G9: `mcp:` is inert, and A7 records **no documented `mcp:` field** on the sub-agents page |
| 3.2 | 2 | G4: a sentence pair that contradicts itself, plus a `skills:` reference to nothing |
| 3.3 | 1 | D41, the corpus's only twice-corroborated directive; the coordinator's paste is canonical |
| 3.4 | 1 | D31 (every CLAUDE.md level reaches a non-fork sub-agent), D36, D30 |
| 3.5 | 1 | D43 — *"grant only necessary permissions for security and focus"*, scoped by Anthropic to sub-agents, which is exactly this tier |
| 3.7, 3.8 | 1 | D42, with Anthropic's own paired worked example as the shape |
| 3.9 | — | Read-only; gates 3.3 |
| 4.1–4.6 | 1 | The 500-line `SKILL.md` cap, stated three times across two official hosts; D32 bounds *what* may move |
| 4.7 | 1 + 2 | **Weakest surviving citation.** D31 + SG2 for the attribution; basis 2 for the latent drift. See the note below |
| 4.8 | 2 | `card-creation.md` teaches a criterion format the CLI rejects at `kanban.py`. Verifiable by running the CLI |
| 4.9 | 2 | A 341-line file documenting two tools the repository no longer ships |
| 4.10 | 2 | A supporting file nothing routes to from either output style — the guidance it carries never loads. See the constraint below |

**Result of the audit: no unit is removed.** Every surviving unit cites on basis 1, basis 2, or both. That is a real finding rather than a rubber stamp, and the two places where it was close are named rather than smoothed over:

- **4.7 is the weakest.** `review-citation-guide.md:11-14` restates the three-tier source priority without attributing it. Nothing is currently false — the restatement is accurate today. The change adds four lines of attribution to prevent a future drift. That is a maintainability argument wearing a correctness costume, and under a strict reading of Q1 it is the one unit that could have been cut. **It survives on this narrow ground and no wider one:** an unattributed restatement of a rule whose canonical statement lives elsewhere is the exact structure D31 and SG2 govern, and Document C names it *"a latent drift source"* in a corpus where the same structure has already drifted once in a security-relevant way (G11). **Card-level constraint:** 4.7 may add attribution only. It may not reword, shorten, or consolidate the restatement — that would be Q4 work, which is closed.
- **4.10's remedy must not smuggle in NA3.** The defect is that `edge-cases.md`'s 366 lines are unreachable from either output style. The remedy options were *"either add pointers or fold the content in."* **Folding in is now prohibited**: it would change an output style's length, and NA3 is closed by Q1(A). 4.10 may add pointers only. If pointers turn out to be insufficient, 4.10 stops and reports rather than reaching for the folding option.

### NA6 Reclassification — the verdict, and the evidence for it

**The question posed.** Q1 removed `allowed-tools` normalization from scope as an authority-less aesthetic matter. But `review-pr-comments/SKILL.md` performs `git push` and `gh` API writes **without** declaring `allowed-tools`, while its sibling `manage-pr-comments/SKILL.md:5-7` does declare it. Is that omission a correctness or security matter, in which case NA6 is a cited gap that ships under Q1 — or is it genuinely cosmetic?

**Verdict: genuinely cosmetic. NA6 ships nothing and stays out of scope.** The evidence, and then the three findings it supports.

**Evidence 1 — the official semantics. `allowed-tools` is a permission *grant*, not a restriction.** From https://code.claude.com/docs/en/skills, § *Pre-approve tools for a skill*, fetched 2026-07-27:

> The `allowed-tools` field grants permission for the listed tools during the turn that invokes the skill, so Claude can use them without prompting you for approval. The grant clears when you send your next message… **It does not restrict which tools are available: every tool remains callable, and your permission settings still govern tools that are not listed.** To pre-approve tools for the whole session rather than a single turn, add allow rules to those permission settings instead.

**Evidence 2 — the restriction field is a different field, and neither skill declares it.** Same page, Frontmatter reference table:

> `allowed-tools` — Tools Claude can use without asking permission during the turn that invokes this skill. The grant clears when you send your next message.

> `disallowed-tools` — **Tools removed from Claude's available pool** while this skill is active. Use for autonomous skills that should never call certain tools… The restriction clears when you send your next message.

**Evidence 3 — in-repo corroboration, arrived at independently of the documentation.** `modules/claude/default.nix:937-941` blocks `Bash(agent-browser eval*)`, `Bash(agent-browser install*)`, and `Bash(agent-browser upgrade*)` with the comment *"(skill's allowed-tools grants everything; these deny-overrides are required)"* — even though `agent-browser/SKILL.md:4`'s `allowed-tools` list enumerates thirteen subcommands and omits all three of those. If `allowed-tools` restricted, those deny-overrides would be redundant. They were required. Second corroboration at `pr-review/SKILL.md:6-9`: *"allowed-tools grants permissions for THIS skill's own Claude invocation only. It does NOT propagate to Task sub-agents spawned within the skill."*

**Finding 1 — the omission cannot create a security hole, because the field cannot grant capability it withholds.** `review-pr-comments`'s missing `allowed-tools` leaves its `git push` and `gh api --method POST` calls governed entirely by `permissions.allow`. That is a **strictly narrower** posture than its sibling's, not a wider one. The asymmetry between the two skills runs in the opposite direction from the one NA6 assumed.

**Finding 2 — there is no behavioral consequence either, because the skill already uses the mechanism the docs prescribe.** `review-pr-comments/SKILL.md:17-30` requires `Bash(git add *)`, `Bash(git commit *)`, `Bash(git push *)`, and `Bash(gh api --method POST *)` in `permissions.allow`, names `dontAsk` mode as the failure mode, and hard-STOPs with a message to the staff engineer if any is missing. The official docs prescribe exactly that instrument for this situation: *"To pre-approve tools for the whole session rather than a single turn, add allow rules to those permission settings instead."* A turn-scoped `allowed-tools` grant would be the **weaker** instrument here, because the grant clears on the next message while a fix→commit→push→reply loop across many comments spans many.

**Finding 3 — Document C's D39 framing of NA6 is inverted, and the correction is recorded here.** `C-gap-analysis.md:427` reads the omission as the D39 shape: *"a mechanism-level control is being substituted with prompt text."* On the documented semantics that inverts the relationship. `permissions.allow` **is** the mechanism-level control; `allowed-tools` is a turn-scoped convenience layered over it. `review-pr-comments` points at the mechanism, and the prompt text at `:17-30` is an instruction to *verify the mechanism is configured* — not a substitute for it. NA6 therefore fails its own D39 argument, which was the only argument that made it look like it might be more than cosmetic.

**No splitting of the difference:** NA6 is not moved into a stage, not partially scheduled, and not left ambiguous. It is recorded in § Out Of Scope with this verdict so that a later effort reading `C-gap-analysis.md:427` does not re-open it as a security item on the strength of a framing this document has refuted.

**One genuinely new question falls out of the verdict, running in the opposite direction.** Because the field grants rather than restricts, the sibling that *declares* it is the one widening its own surface. That question is stated alone in § The One Remaining Open Question and is the only thing in this document still awaiting an owner answer.

---

## Style Guide For The Rewrite

Every later card is executed against this section, **and against § The Q1 Audit.** Q1(A) means a rule below that is not cited authorizes nothing. Each rule cites `A-anthropic-v5-guidance`, gives a before/after drawn from real current text, and states a test a rewriter can mechanically apply. A rule that cannot be mechanically applied is not a rule and is not here.

### SG1 — XML tags only at a content-type boundary; markdown headings everywhere else

**Authority.** Document A § Structural Conventions For Prompts: *"XML tags help Claude parse complex prompts unambiguously, especially when your prompt mixes instructions, context, examples, and variable inputs."* And its bound, stated in the same section: *"No source in this corpus states that XML tags outperform markdown headings for section delimitation in general."* D34 prescribes markdown headers and bullets for CLAUDE.md files specifically.

**Rule.** Markdown headings remain the structuring device in all 44 files. Add an XML tag at exactly one kind of site: where a **literal payload intended to be copied verbatim into a different context** is embedded inside instruction prose.

**Test.** Will a reader copy this block, unchanged, into somewhere else? Yes → wrap it in a named tag. No → it is a section; use a heading.

**Before/after.** `staff-engineer.md:1020-1034` is the 7-field return contract the coordinator is told to paste VERBATIM into a delegation prompt. It is delimited only by a blockquote sitting inside surrounding instruction prose. After: the same fifteen lines wrapped in `<return_contract>` … `</return_contract>`, with the surrounding prose unchanged. This is G18's entire surface — a handful of sites, not a corpus conversion.

**Do not.** Convert section structure to XML anywhere. Document C § Non-Gaps rejects it, and Document A carries a mechanism claim that cuts against it: *"removing markdown from your prompt can reduce the volume of markdown in the output."*

### SG2 — A rule lives at exactly one tier: the shallowest tier whose injection set covers every context that must obey it

**Authority.** D36: *"Keep it to facts Claude should hold in every session … If an entry is a multi-step procedure or only matters for one part of the codebase, move it to a skill or a path-scoped rule instead."* D31, on what a non-fork sub-agent receives: *"**CLAUDE.md files**: every level of the CLAUDE.md hierarchy the main conversation loads."* D30 (skills-scoped): *"Only add context Claude doesn't already have."*

**Rule.** Name the set of contexts that must obey the rule. Place it at the shallowest tier whose injection set covers that set, and nowhere else. An agent definition or skill may state only the **delta** its own domain adds.

**Test.** For each restatement: is the canonical statement already present in every context that reads the restatement? If yes, the restatement is deletable and only the delta survives.

**Before/after.** The four-step Research Priority Order is restated in full in all seven `swe-*` files (`swe-frontend.md:94-103` and six siblings, 70 lines), while global `CLAUDE.md:130-151` already reaches every sub-agent by platform injection. After: the seven restatements are deleted; the global copy stands. The delta for `swe-*` is nothing, so nothing replaces them.

**Bound — read this before applying SG2.** This rule governs restatement *across tiers*. Restatement of one rule at successive *workflow moments within one tier* is CG2, and **§ Q4 closed it as preserve.** Do not consolidate the AskUserQuestion protocol's roughly 21 citations, or the backslash-pipe MoV rule's six sites, under SG2 — in any stage, for any reason. This is no longer a pending question a card may resolve by judgment; it is a decision.

### SG3 — Every prohibition carries an adjacent affirmative; add, never replace

**Authority.** Document A § Emphasis And Over-Steering finding 3, corroborated on three pages: *"Tell Claude what to do instead of what not to do"*; *"Positive examples of the communication style you want tend to be more effective than instructions about what not to do"* (Opus 5); the parallel Sonnet 5 sentence.

**Rule.** Every `❌` gets a `✅` in the same block, showing the correct form. The `❌` stays. This is an addition, never a substitution.

**Test.** Per file, `rg -c '❌'` must be less than or equal to `rg -c '✅'`.

**Before/after.** `debugger.md:67`, `:69`, `:71` carry three `❌` bullets and the file contains zero `✅` anywhere (verified in `C-verification` § Citation Audit #17). After: three paired `✅` bullets adjacent to them. The template is `kanban-cli/SKILL.md:41-42` and `:49-50`, the corpus's one systematically symmetric file (VP8).

**Hard exclusion.** WI-18's destructive-operation prohibitions — global `CLAUDE.md:26-36` and `:53-65` — are not style or format instructions, which is where Anthropic's claim is scoped. Document A finding 7 records that Anthropic uses ALL-CAPS negative framing in its own recommended prompt blocks. Do not touch them under SG3.

### SG4 — Keep the mechanism; classify the provenance before removing it

**Authority.** D13: *"Providing context or motivation behind your instructions … can help Claude better understand your goals."* Document A's own strength note at `A-anthropic-v5-guidance.md:488`: *"Anthropic's stated variable is the presence of motivation, not the capitalization."* Document C VP3 (narrowed) and NA9 (with its exception).

**Rule.** Three categories. **§ Q2 chose (B) keep all provenance, so none of the three is available for removal in this effort.** SG4 is therefore a classification rule that never authorizes a deletion — stated plainly so a rewriter does not go looking for the removal path.

1. **The mechanism sentence** — explains *how* violating the rule produces a bad outcome. D13-protected. Survives every pass verbatim.
2. **Evidentiary provenance** — a card number or incident count whose function is to establish that the banned pattern is real. No Anthropic authority for retention, but removing it is a behavioral change, not a simplification. **Retained by Q2(B), by default rather than by exception.**
3. **Decorative provenance** — a session name or date in a prose rule that already carries its mechanism. **Retained by Q2(B).** The category and its test are kept because classification still matters for judging whether an *addition* is decorative, and because a post-Stage-4 review will need them.

**Test.** Delete the provenance and re-read the rule. If the rule now reads as an opinion a reader could argue with, it was evidentiary — restore it.

**Before/after — the test working, including where it says stop.** Project-root `CLAUDE.md:13-31` (macOS Trash). The mechanism — *"moves files to the freedesktop.org trash directory … invisible to Finder"* — is category 1 and is protected. The clause *"160 worktree folders silently routed to the freedesktop dir instead of macOS Trash"* looks like category 3 but passes the test as category 2: strip it and the section reads as a preference between two packages rather than as a report of damage already done in this repository. **Keep it.** By the same test, `kanban-cli/SKILL.md:180` (card #2457) and `:220` (PLA-3559 card #9) are category 2 and stay.

### SG5 — A checklist item is a pointer or a restatement; restatements collapse to pointers

**Authority.** D1 (Opus 5): *"If your prompt contains explicit verification instructions … remove them … removing them reduces wasted tokens with no loss in quality."* D2 (Opus 5): *"Avoid instructing re-checks it already performs."* Scope is fixed by `C-measurements` Measurement 1: both coordinator tiers run `--model 'opus[1m]'`, so D1/D2 govern them. Document A INFERENCE 1 forbids extending either to Sonnet.

**Rule.** For each `- [ ]` item in the two output styles: if it contains normative content not present in the section it names, it is a restatement — replace it with a pointer to the canonical statement. If it is already a pointer, keep it.

**Test.** Does the item state any rule the referenced section does not? Yes → restatement.

**Before/after.** `senior-staff-engineer.md:512` reads *"Zero tmux, ever. See § Hard Rule 9."* — a pointer, kept. `staff-engineer.md:503`, `:524`, `:527` restate substantive content (Document B identifies exactly these three as breaking the index pattern) — collapsed to pointers.

**Hard scope.** Coordinator tier only. The agent tier's `## Verification` / `## Success Verification` / `## Success Criteria` sections stay untouched: those seventeen files are `model: sonnet`, D1/D2 are Opus-5-only, and Anthropic still endorses self-check for every model other than Opus 5. The same edit is a fix in one tier and a regression in the other.

### SG6 — A sub-agent's output format is stated once, and the coordinator's paste is canonical

**Authority.** D41, the only directive in Document A's catalog corroborated by two official product pages: *"Output styles apply to the main conversation only: a subagent runs its own system prompt, so styles don't change how subagents respond."* Document C VP5: the paste-verbatim instruction is a correct D41 workaround — *"Document D must not 'fix' the paste."*

**Rule.** The canonical return contract is `staff-engineer.md:1020-1034`, pasted per launch, and it stays card-type-aware. An agent definition either restates it byte-identically or says nothing about return shape at all — it may not carry a competing convention.

**Test.** Does this file's `## When Done` / Output Protocol section state a return shape that differs from `staff-engineer.md:1020-1034`? If yes, it is a competing format.

**Before/after.** `swe-frontend.md:600-606` carries an unstructured "3-5 bullets maximum" convention while the coordinator pastes a seven-field template into the same context. After: one line deferring to the delegation prompt's contract, and the "3-5 bullets" concision guidance is retained as a *length* instruction rather than a *format* one.

**Hard off-limits.** The `Hard Rule: STOP on structurally broken MoV` block, present in all 17 files, contains `Status: blocked` and the `Blocker:` line. That block is **WI-3's prompt half** and is off-limits to any SG6 pass. `C-verification` § Invariant Endangerment item 3 names it; `C-gap-analysis` G10 carries it. WI-3 is hook-backed so the mechanical guarantee survives an accident there, but the deliberate double cover does not.

### SG7 — Do not move a rule for positional reasons

**Authority — a documented absence, not a finding.** Document A § Structural Conventions For Prompts: *"Instruction ordering within a system prompt is not addressed."* A1 checked all four Opus-5-family pages, A2 checked three more, and both report the absence. The one positional claim in the corpus is about longform **data** placement in long-context tasks, and Document A states plainly: *"Do not cite this document as authority for a front-loading rule about instructions."*

**Rule.** Position changes only as a consequence of a cited change. When a section is split or relocated for a reason (G2, G14, G6), its new position is chosen by topical grouping per D34. Perceived importance is not a reason to move anything.

**Test.** Is the only justification for this move "this is important, so it should appear earlier"? Then it is not authorized.

**Why this is a rule rather than an omission.** A rewriter handed two 3,000-line files and a mandate to improve them will reach for reordering. There is no evidence base for it, and reordering a 3,000-line file is the single cheapest way to invalidate the roughly 390 internal `§` anchors Document B records as never having been validated against actual headings.

### SG8 — Target length by file category, and which categories may cite Anthropic

| Category | Target | Authority | May a length change cite Anthropic? |
|---|---|---|---|
| Project-root `CLAUDE.md` | **200 lines — committed (§ Q6)** | D33, tied to *adherence*: *"target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence."* | **Yes** |
| Global `CLAUDE.md` | **360 lines — committed (§ Q6)**, a reasoned overshoot; see § Stage 1 for the subtraction that forces it | D33, as a soft target: *"CLAUDE.md files are loaded in full regardless of length"* | **Yes, for the direction. No, for the number** — 360 is ours |
| `SKILL.md` body | **500 lines** | Stated three times across two official hosts | **Yes** |
| Output styles | **No target, and no length change authorized** | Confirmed absence from a full-page read (NA3), **closed by § Q1(A)** | **No** — and no other ground is available either |
| Agent definitions | **No target, and no length change authorized** | Confirmed absence from a full-page read (NA4), **closed by § Q1(A)** | **No** — and no other ground is available either |

**Test.** Is a length reduction being justified by citing Anthropic? Only the first three rows may. **For output styles and agent definitions there is no longer an owner-judgment fallback:** the original version of this rule allowed such a change if the card labelled it *owner judgment, no Anthropic authority*, and Q1(A) removed that path. Document A forbids extending D33 to them and calls that extension *"the single most likely overreach in the whole effort"*; Q1(A) now forbids reaching the same outcome by preference instead. The first two rows' numbers are committed, not proposed — a card that names 200 for the global file is contradicting an approved decision, not proposing a stretch goal.

### SG9 — Match degrees of freedom to task fragility before relocating or compressing anything

**Authority.** **D32** (`A-anthropic-v5-guidance.md:723`), skills-scoped: fragile, error-prone, must-be-exact operations get *"exact scripts with no room for interpretation"*; open-ended judgment calls get heuristic guidance.

**Rule.** Classify the operation a block governs before touching the block. Low freedom → stays inline and complete. High freedom → heuristics, relocatable.

**Test.** Does deviating from this block produce a **hard failure** — CLI rejection, hook denial, an API 400 — rather than a worse-but-working outcome? Hard failure → low freedom → do not relocate.

**Before/after — the rule protecting something.** `kanban-cli/SKILL.md:31-254`, the 223-line banned-pattern catalogue. Deviating from it produces a hard rejection at `kanban.py:1258-1276`. **Low freedom: stays inline and complete.** `C-verification` calls the omission of D32 from Document C *"the most substantive miss"* precisely because D32 is authority against a change Document C proposed in two places (G5 and G6). At 542 lines against a 500-line cap this file is 8% over — trivially so. It is not a Stage 4 length target.

**Counter-example, so the rule is not read as blanket protection.** `project-planner/SKILL.md:984-1131` and `:1132-1241` are 258 lines of worked-example repetition of a framework already stated abstractly earlier. Deviating produces a worse plan, not a rejection. **High freedom: relocatable** to a supporting file, and it is Stage 4's cleanest first use of the mechanism.

### SG10 — Adding a reason is always authorized; changing intensity never is

**Authority.** D13 (add motivation) and D25 (*"Use direct imperatives when you want action, not suggestions"* — cross-model, VP11) on one side; NA1 and NA2 on the other, where Document A's § Emphasis And Over-Steering opens: *"Anthropic does not take a position on ALL-CAPS, emoji emphasis, or restating instructions."*

**Rule.** Three buckets.

- **Add a mechanism-grounded reason to a bare prohibition** — always authorized, D13. **Units 2.10 and 2.11 are this bucket**, commissioned by Q3(C) and Q8(C).
- **Change modal intensity, remove a 🚨, or downcase a `NEVER`** — **closed by § Q1(A), not merely gated.** Nothing in any stage may do this. The scar-tissue rationale for siren removal is independently refuted: Document B traced the marker's origin to commit `607de07`, a generic bulk-rewrite commit.
- **Soften an imperative into a suggestion** — prohibited outright. It moves the corpus away from D25, a cross-model directive.

**Test.** Does the edit change *whether a reason is stated* (do it), *how loudly the rule is stated* (closed by Q1(A) — never), or *whether it is stated as an instruction at all* (never)?

**Before/after.** D13's own paired example is the shape: `NEVER use ellipses` → *"Your response will be read aloud by a text-to-speech engine, so never use ellipses since the text-to-speech engine will not know how to pronounce them."* Note what changed and what did not: a reason appeared; the prohibition remained.

### SG11 — A `description` names the domain and states the trigger

**Authority.** D42: *"Claude uses each subagent's description to decide when to delegate tasks."* Anthropic's worked example pairs both halves: *"Expert code review specialist. Proactively reviews code for quality, security, and maintainability. Use immediately after writing or modifying code."*

**Rule.** Every agent `description` = a domain sentence + an explicit trigger clause. Where two descriptions share domain keywords, both carry a reciprocal boundary clause naming the other.

**Test.** `rg -N '^description: ' <file> | rg -q 'Use for|Use when|Use immediately|Use proactively'`. Applied per file, isolating the frontmatter line so body prose cannot produce a false positive — the method `C-measurements` Measurement 2 used.

**Before/after.** `swe-security.md:5` is the tier's lone violation: a bag of domain keywords with no verb phrase stating when to invoke it. After: the same keywords plus a trigger clause — *"Use for security review, threat modeling, and vulnerability assessment; use before merging authentication, authorization, credential-handling, or cryptography changes."* Sixteen of seventeen already comply. The reciprocal-boundary shape already exists at `product-ux` ↔ `visual-designer` and `ai-expert` ↔ `scribe`.

### SG12 — What this style guide does not authorize

Stated as a closed list so a rewriter cannot infer permission from silence. **Every entry that was previously conditional is now unconditional** — the owner's decisions closed each gate rather than opening it.

- **No emphasis de-escalation.** ALL-CAPS, emoji sirens, `MANDATORY`/`CRITICAL` escalation. No Anthropic authority (NA1, NA2). **Closed by § Q1(A).**
- **No length change to an output style or an agent definition, in either direction, on any ground.** Confirmed absences (NA3, NA4), **closed by § Q1(A).** Note what this means for Stage 2 and Stage 3: they produce defect fixes and cited normalizations, not shorter files.
- **No provenance removal anywhere.** Card numbers, incident counts, session names, dates. **Closed by § Q2(B).**
- **No `allowed-tools` normalization across skills.** NA6, adjudicated as cosmetic on the documented grant semantics — see § NA6 Reclassification.
- **No XML conversion of section structure.** § Non-Gaps.
- **No `@path` imports as a length remedy.** D37: *"Splitting into `@path` imports helps organization but doesn't reduce context, since imported files load at launch."* A plan that shrank a file this way *"would achieve nothing and believe it had succeeded."*
- **No positional reshuffling.** SG7.
- **No shortening of any invariant section**, in any stage, for any reason. § Workflow Invariant Preservation Plan enumerates them.
- **No consolidation of restatement across workflow moments**, ever, in this effort. **Closed by § Q4(A).**
- **No relocation of `kanban-cli/SKILL.md:31-254`** on a line-count argument. SG9, D32.
- **No consolidation of the two coordinator output styles.** **Closed by § Q5(B)** — both files stay and their duplication is policed mechanically instead.
- **No change to any launcher flag.** Unit 2.11 adds comment lines to `staff.bash` and `sstaff.bash` and nothing else. **§ Q8(C).**
- **No folding of `edge-cases.md` into an output style.** Unit 4.10 may add pointers only; folding would be an NA3 length change. See § The Q1 Audit.

---

## Stage 1: Shared Layer

### The Stage 1 line budget — the arithmetic, shown

`C-gap-analysis` states three times that this subtraction must appear here before Stage 1 begins, and `C-verification` calls its absence *"the single largest behavioral risk in the plan."* Here it is. All spans measured 2026-07-27 against the live files.

**Global `modules/claude/global/CLAUDE.md` — 530 lines.**

Protected: sections that may not be shortened, because a prompt-only invariant or an Anthropic-prescribed block lives in them.

| What | Section | Span | Lines |
|---|---|---|---|
| WI-18 | `### Outright Prohibitions (Never Run)` | 26–36 | 11 |
| WI-12 | `### Worktree Confinement` | 37–52 | 16 |
| WI-18 | `### Ask-First Operations (Require User Approval)` | 53–65 | 13 |
| — | `## Dangerous Operations` heading hosting the three above | 24–25 | 2 |
| WI-16 | `## Bash/Shell Guidelines` | 343–371 | 29 |
| WI-16 | `## 🚨 Use rg and fd — NEVER grep or find 🚨` | 372–386 | 15 |
| WI-17 | `## 🚨 PACKAGE INSTALLATION: NEVER HOMEBREW 🚨` | 387–394 | 8 |
| WI-9 | `## PR Creation` (draft-first) | 395–406 | 12 |
| WI-9 | `## PR Descriptions` (the banned-phrasing list) | 407–441 | 35 |
| WI-9 | `## Git Branch Naming` | 442–450 | 9 |
| WI-9 | `## GitHub Actions Security` | 457–467 | 11 |
| VP10 / D4 | `## Scope Discipline` | 152–160 | 9 |
| VP10 / D4 | `### YAGNI + KISS` | 252–260 | 9 |
| VP10 / D4 | rule-of-three line in `### DRY with nuance` | 273 | 1 |
| WI-17 | single-line anchors at 7, 15, 144 | — | 3 |
| **Protected floor** | | | **183** |

**A correction to VP10's citation, which `C-gap-analysis` asked Document D to resolve.** VP10 attributes the anti-over-engineering block to *"the seven `swe-*` agent definitions … through their **YAGNI + KISS** sections."* Measured: `rg -c 'YAGNI|KISS'` returns **1** for each of the seven `swe-*` files — a single bullet in a list, not a section. The full D4-shaped content (`## Scope Discipline`, `### YAGNI + KISS` with the LLM-specific trap at `:256`, the rule of three at `:273`) lives **entirely in the global `CLAUDE.md`**, inside the file Stage 1 shortens. That makes VP10's protection tighter than Document C implied, not looser.

Relocatable ceiling: Document B's B3 pass estimated roughly 160 of 530 lines (~30%) narrow-audience, without enumerating them, and `C-gap-analysis`'s amendment binds that figure as an **upper bound on relocatable content, not a measurement**. Enumerating the candidate set by section span:

| Candidate narrow section | Span | Lines |
|---|---|---|
| `## AWS Credentials (SSO Assume-Role Chains)` | 66–93 | 28 |
| `## Tool-First Integration` | 94–116 | 23 |
| `## Pagination Discipline` | 117–129 | 13 |
| `## 12-Factor Configuration` | 290–328 | 39 |
| `## PR Comment Replies` | 451–456 | 6 |
| `## Glossary` | 468–481 | 14 |
| `## MCP Integration` | 482–491 | 10 |
| `## Technology Selection` | 492–497 | 6 |
| `## Scratchpad` | 498–505 | 8 |
| `## Team Member Terminology` | 506–525 | 20 |
| `## Reference Commands` | 526–530 | 5 |
| **Ceiling** | | **172** |

172 corroborates B3's ~160 from a different method, which is mild evidence the classification is not wildly off.

**The subtraction.**

```
530  global CLAUDE.md, actual
-172  every candidate narrow line relocated (the optimistic bound)
─────
 358  floor
-200  D33 target
─────
 158  SHORTFALL
```

The 358-line floor decomposes into 183 protected lines plus 175 lines of conventions, always-do-X rules, and epistemic/model-selection guidance — which is precisely the content D36 says a CLAUDE.md is *for*. So closing the 158-line gap requires cutting either protected content (forbidden) or D36-endorsed content (self-defeating). **The 200-line target is unreachable for the global file. Stating it in a card would send an agent hunting 158 lines with only those two places left to look.**

**Project-root `CLAUDE.md` — 387 lines.**

```
Protected: NEVER HOMEBREW (9-12, WI-17)                            4
           macOS Trash CLI (13-31, D13 mechanism + /doctor pitfall) 19
           Critical Requirements (160-166, WI-18 --purge rationale)  7
D36 must-stay: SOURCE OF TRUTH PRINCIPLE (32-71)                   40
               Your Team (351-354)                                   4
               intro/identity (1-8)                                  8
                                                          floor =  82

387 - 298 (Document B's ~317 narrow, less the 19 protected Trash lines) = 89
89 <= 200.  TARGET REACHABLE, 111 lines of headroom.
Required hit rate on the ceiling: 187 of 298 = 63%.
```

**Aggregate and the revised target.**

| | Lines |
|---|---|
| Current | 917 |
| Best achievable (358 global + 200 project-root) | 558 |
| Reduction achievable | 359 |
| `C-gap-analysis`'s stated target | 517 |
| **Shortfall, located entirely in the global file** | **158** |

**What changes.** The committed Stage 1 target is **360 lines for the global file and 200 for the project-root file** — aggregate 560, a 357-line reduction — with the global overshoot recorded as a reasoned deviation from a soft target that Anthropic states in the same breath as *"CLAUDE.md files are loaded in full regardless of length."* **§ Q6 approved this: (B), accept 360/200 and open a tracked follow-on for the two routes to 200.** The owner sign-off gate this paragraph originally carried is discharged.

### The Stage 1 line budget with the decisions applied

The subtraction above is the pre-decision arithmetic and is left standing so the two versions can be compared. Here it is again with every decision that touches the global file applied. **One decision touches it: Q9(B).**

```
530   global CLAUDE.md, actual
-172  every candidate narrow line relocated (the optimistic bound)
─────
 358  pre-decision floor
  +1  Q9(B): keep the ac-reviewer roster line and add its clarifying clause
─────
 359  post-decision floor
-360  committed target (§ Q6(B))
─────
  -1  SLACK REMAINING: 1 line
```

**What that number means, stated plainly.** 360 was proposed against a 358-line floor, giving 2 lines of slack. Q9(B) consumes 1 of them. **The committed target does not move — the slack does, from 2 lines to 1.** The aggregate stays 560 and the reduction stays 357, because the target is a cap and the floor still sits under it.

**Three consequences a Stage 1 card must know.**

1. **Unit 1.4 has essentially no headroom.** Any *additional* line added to the global file during Stage 1, for any reason, breaches the committed cap. There is no room for a second Q9-style clarifying clause, a second mechanism sentence, or a paired `✅` — note that SG3 does not apply to this file's protected prohibitions by its own hard exclusion, which is the only reason that last one is not already a conflict.
2. **The 172-line ceiling is now load-bearing rather than optimistic.** Pre-decision, the floor could absorb a small shortfall in unit 1.1's ledger. It cannot now. **If 1.1's re-derivation comes in below 171 relocatable lines, the 360 target fails and Q6 reopens** — R6 already says this, and Q9(B) tightened the threshold from 170 to 171.
3. **No double-counting between G19 and G2.** G19's ~20 double-paid `## Team Member Terminology` lines sit *inside* the `## Team Member Terminology` section (506–525, 20 lines) that the relocation ceiling already counts. They are one 20-line opportunity claimed by two gap numbers, not two. Unit 1.4's card must state which mechanism removes them so the ledger does not credit both.

**The project-root file is unaffected.** No decision adds or removes a line there; its floor stays 82, its ceiling-based estimate stays 89, its committed target stays 200, and its 111 lines of headroom stand. It is the only part of the Stage 1 budget with real slack.

**Two routes exist to reach 200 later, and neither is prompt editing.** Both are named here so the committed target is understood as a floor for *this* effort rather than a permanent verdict. **§ Q6(B) commissions a tracked follow-on covering both** — see § Out Of Scope → `### The tracked follow-on to 200 (§ Q6(B))`.

1. **Path-scoped rules.** D33's own sentence prescribes them: *"If your instructions are growing large, use path-scoped rules so instructions load only when Claude works with matching files."* Document A § Splitting Content confirms they genuinely reduce context, unlike `@path` imports. Two facts are unestablished and gate this: whether a *user-scope* path-scoped rule directory exists at all (Document A records only `.claude/rules/`, project-scoped), and whether the `paths:` gating applies inside a non-fork sub-agent, whose documented context includes *"project rules"* without stating whether the gating survives. Unit 1.0 investigates; nothing is planned on it.
2. **G12's hook work.** If WI-18's and WI-12's prohibitions become `PreToolUse`-hook-enforced per D39, their 40 prompt lines stop being the sole guarantee and become a double cover — at which point they could be *shortened* without removing a guarantee, because the guarantee moved to the mechanism. **This is the only Anthropic-endorsed route to 200 on the global file, and it is not a prompt edit.** It is tracked in § Out Of Scope.

### Stage 1 file list

- `modules/claude/global/CLAUDE.md` (530)
- `CLAUDE.md`, project root (387)
- Destination files for relocated content, to be created — path and mechanism determined by Unit 1.0

### Stage 1 units

Stage 1 has an inherent parallelism ceiling of **two** concurrent edit units, because it has two files. Saying otherwise would be inventing a decomposition. Read-only units run in parallel with anything.

| Unit | Files touched | Work | Model | Why that model |
|---|---|---|---|---|
| **1.0** | none (read-only) | Determine whether user-scope path-scoped rules exist and whether `paths:` gating survives into a non-fork sub-agent. Output: a scratchpad finding, no edits | sonnet | Bounded external-documentation research with a yes/no output. No judgment about this repository |
| **1.1** | none (read-only) | Re-derive the global file's narrow-audience classification section by section against `/doctor`'s explicit *keep pitfalls, rationale, and conventions that differ from tool defaults* test — not against audience breadth alone, which `C-verification` showed misclassifies at least one case. Output: a per-section relocate/keep ledger | sonnet | Mechanical classification against a stated written test |
| **1.2** | none (read-only) | Same re-derivation for the project-root file. Must reach ≥187 relocatable lines or Stage 1's project-root target also fails | sonnet | Same |
| **1.3** | none (read-only) | Determine whether `ac-reviewer` has an LLM prompt body defined dynamically, which Document B could not settle by static search. **Per § Q9(C), this determines the clause's wording, not whether the roster line survives** | sonnet | Requires reading `default.nix` and hook sources. **Q9(B) lowered this unit's stakes**: a wrong answer now mis-words a clause rather than deleting a real roster entry |
| **1.4** | `modules/claude/global/CLAUDE.md` + its destination files | G16 **as an addition per § Q9(B)** — keep line 521's roster entry and add a clause naming `ac-reviewer` as the automatic `SubagentStop` AC reviewer and not a delegation target; G19 (the ~20 double-paid `## Team Member Terminology` lines — remove the taxonomy duplication only, not the unique recipes, and **do not double-count them against G2's ceiling**); G2 relocation per 1.1's ledger; G1 to the committed 360 lines | **opus** | The highest-risk file in the corpus: five prompt-only invariants, 183 protected lines, and a failure mode that is silent. Judgment-dense and irreversible-by-omission. **Now also the tightest budget in the corpus — 1 line of slack** |
| **1.5** | `CLAUDE.md` project root + its destination files | Same gap set, committed target 200, per 1.2's ledger. No decision adds a line here | **opus** | Three protected sections and the D13-protected Trash mechanism, whose misclassification risk `C-gap-analysis` G2 names specifically |

1.0–1.3 run in parallel. 1.4 and 1.5 run in parallel after both their ledgers land, and 1.4 additionally waits on 1.3 for its clause wording. **The target sign-off precondition is discharged by § Q6(B)** — the original *"neither may begin until Open Question 6 is answered"* is satisfied, and 360/200 are the numbers every Stage 1 card must state.

### Stage 1 validation gate

Every check below must pass before Stage 2 begins. This is the validation gate, stated as commands rather than intentions.

1. **`hms` completes successfully.** The real gate — it runs flake8, which `nix flake check` does not.
2. **Line counts match the committed targets.** `wc -l modules/claude/global/CLAUDE.md CLAUDE.md` → global ≤ 360, project-root ≤ 200.
3. **Invariant presence assertions — the mechanical heart of this gate.** One `rg -q` pattern per protected invariant, run against the post-edit files, all of which must exit 0. Drawn from each invariant's most distinctive phrase so that rewording the surrounding prose cannot satisfy them accidentally: the never-skip-hooks clause and its human-delegated-bypass sentence; each of the four ask-first operations by name (`hms --purge`, `git reset --hard`, `git push --force`, `rm -rf`); `perm purge` as user-only; every enumerated worktree-confinement prohibited-target category; the `--draft` requirement; every entry in the PR-description banned-phrasing list; the `karlhepler/` prefix; SHA-pinning; `rg` not `grep` and `fd` not `find`; the `rg -E` footnote; one-command-per-Bash-call; the `sh -c` prohibition; the Homebrew prohibition; `One task = one deliverable`; the LLM-specific abstraction trap; the rule of three; and the macOS Trash mechanism sentence. **This list becomes a committed script in the Stage 1 unit so Stages 2–4 can re-run it unchanged.**
4. **Line accounting on the diff.** Every line removed from a Tier-1 file appears in a destination file in the same commit, or the commit body states it as a deliberate deletion with a reason. No silent losses.
5. **Sub-agent injection smoke test.** Spawn one trivial background sub-agent and confirm its leading `claudeMd` block contains both files and that assertion set 3 still passes against what it received. This is the only check that proves the *injection path* still works rather than that the *files* still say the right thing — the composition-root problem applied to prompts.
6. **Owner soak.** One week of ordinary `staff` and `sstaff` work with no reported behavioral surprise.

### Stage 1 revert procedure

One commit per unit, so a revert is one commit wide. To revert: `git revert <sha>`, run `hms`, then re-run gate checks 2, 3, and 5. Do not use `git reset --hard`, `git checkout --`, or `git clean` — this repository routinely carries uncommitted work from other sessions, and all three are either ask-first or destructive under the global guidelines. If a revert must happen after Stage 2 has begun, revert Stage 1's commits first and then re-apply Stage 2's, because Stage 2's deduplication assumes what Stage 1 left in the shared layer.

---

## Stage 2: Coordinator Prompts

### Stage 2 file list

- `modules/claude/global/output-styles/staff-engineer.md` (2,918)
- `modules/claude/global/output-styles/senior-staff-engineer.md` (3,061)
- Individually, as destinations or as G13 targets: `docs/staff-engineer/review-protocol.md` (648), `anti-patterns.md` (136), `self-improvement.md` (47), `parallel-patterns.md` (417)

### Stage 2 units

| Unit | Files touched | Gaps closed | Model | Why |
|---|---|---|---|---|
| **2.1** | `senior-staff-engineer.md` | **G11** — the three missing STOP-condition exclusions at `:2371-2379`. **Fix shape fixed by § Q5(B):** copy the exclusions in, and bring the shared section under 2.9's sync check so the copy cannot drift again | **opus** | Security-relevant suppression path in WI-7, the corpus's highest-risk prompt-only invariant. Both available remedies change `sstaff` behavior, and the fix must be verified against `:47-53` (the default card-creation prohibition) as well as `:2371-2379`, or it can make the path *more* reachable while closing the drift |
| **2.2** | `staff-engineer.md` | **G13** coordinator share — pair unmatched `❌` callouts, e.g. `staff-engineer.md:238-239` | sonnet | Additive, mechanically testable by SG3's per-file ratio. Excludes WI-18 by SG3's hard exclusion |
| **2.3** | `senior-staff-engineer.md` | **G13** share — the single-sided examples at `:1286`, `:1718`, `:1850` | sonnet | Same. Disjoint from 2.2, so the two run in parallel |
| **2.4** | `anti-patterns.md`, `self-improvement.md`, `parallel-patterns.md` | **G13** — three files at 3 `❌` / 0 `✅`, 5 / 0, and ~120 of 136 lines of `Concrete failure:` bullets | sonnet | Additive. But `anti-patterns.md`'s bullets each anchor a specific past failure, so SG4's category test governs every one of them |
| **2.5** | `staff-engineer.md` | **CG4 / D1 / D2** — collapse the three restating checklist items at `:503`, `:524`, `:527` to pointers; leave the other 58 items alone | **opus** | Requires distinguishing pointer from restatement across 61 items in a file where WI-10's five component requirements must survive intact |
| **2.6** | `senior-staff-engineer.md` | Same, its 25 items | **opus** | Same |
| **2.7** | none (read-only) | Assess whether `--effort xhigh` matches Anthropic's recommendation — `C-gap-analysis`'s new coverage gap. Also re-run the D1–D46 set-difference against the amended Document C as a completeness check | sonnet | Bounded assessment against quoted guidance |
| **2.8** | `staff-engineer.md` | **G14** — relocate the project-scoped subset out of the output style | **opus** | Highest remedy risk in the stage: Anthropic's prescribed destination is CLAUDE.md, which Stage 1 has just constrained. Cannot begin until Stage 1's budget is committed |
| **2.9** | both output styles (section markers only) + a new check script + `modules/claude/default.nix` | **CG5, resolved by § Q5(B)** — build the **mechanical sync check**: an assertion that the shared sections are byte-identical across both output styles. Full specification below | **opus** | Touches both highest-risk coordinator files and the deploy path. Choosing the section boundaries *is* the design: too coarse and the check fails on legitimate per-tier divergence, too fine and it misses the drift it exists to catch |
| **2.10** | `staff-engineer.md` | **CG1, resolved by § Q3(C)** — add the motivation passage to the absolute delegation rule at `:122`, naming delegation as the verification boundary and the four mechanisms direct coordinator work bypasses (WI-6 card injection, WI-4 AC review, WI-11 conflict scheduler, WI-5's foreground-launch denial) | sonnet | Pure D13 addition with a fixed target and a fixed content list. **Hard constraint: add a reason, do not touch the imperative** — SG10 bucket 1 authorizes the shape, bucket 3 prohibits softening |
| **2.11** | `staff.bash`, `sstaff.bash` (**comment lines only**) | **§ Q8(C)** — add the documented rationale for `--effort xhigh` naming D14's step-up clause, with a pointer to unit 2.7's assessment | sonnet | Two comment blocks. **The one authorized touch of non-prompt source in this plan**: no flag, argument, model alias, or executable line may change. Runs after 2.7 so it can cite a finding rather than a guess |

**Sequencing.** 2.1 first and alone. Then 2.2/2.3/2.4/2.7/2.10 in parallel — all disjoint by file except 2.2 and 2.10, which both touch `staff-engineer.md` and must therefore run sequentially with respect to each other, not concurrently. Then 2.5/2.6 in parallel. Then 2.8. Then 2.11 (after 2.7). **2.9 runs last**, because its section markers must be placed against the post-edit text; placing them first would mean asserting byte-identity over content five other units are still changing.

### Unit 2.9 in full — the mechanical sync check (§ Q5(B))

Q5(B) commissions this and states its purpose precisely: *the observed failure was not that content was duplicated, it was that the duplication drifted undetected.* The check converts a prompt-only invariant that has already failed silently into one that fails loudly.

**Recommendation: an `hms`-time assertion, not a CI check.** Three reasons, and the trade-off it costs.

1. **`hms` is the documented real gate in this repository.** It runs flake8 where `nix flake check` does not, and the project's own deployment rule is `git add` → `hms` → `commit` → `push`. A check that runs at `hms` time fires *before* the drifted prompt is ever deployed.
2. **CI would fire too late to matter.** These prompt files take effect the moment `hms` deploys them locally, which happens before any push. A CI check would detect the drift only after the drifted coordinator prompt had already been live in the owner's sessions — which is precisely the window in which G11's drift did its damage.
3. **`hms` is the gate the owner cannot route around while still deploying.** A CI check can be merged past; a deploy-time assertion cannot be skipped without also not deploying. That property is what makes it a mechanism rather than a reminder.

**Trade-off, stated rather than buried.** An `hms`-time check adds a failure mode to the deploy path: a false positive blocks `hms` entirely, which blocks *every* configuration change until it is resolved, not just a prompt change. Two mitigations. Make the assertion **byte-identity over explicitly delimited section markers** rather than a fuzzy or semantic comparison, so a failure is always a real difference and never a heuristic's opinion. And emit the offending section name plus a `diff` of the two copies in the failure message, so the fix is obvious rather than a hunt. A second, smaller cost: the check does not fire on a commit that is never deployed. Accepted — an undeployed prompt file changes no behavior.

**Implementation shape.**

- Delimit each shared section in **both** output styles with a matched marker pair carrying a shared identifier, e.g. `<!-- SYNC:review-stop-conditions -->` … `<!-- /SYNC:review-stop-conditions -->`. Markers are HTML comments so they are invisible in rendered markdown and inert as prompt text.
- The check extracts every `SYNC:<id>` block from both files, and asserts: every id present in one file is present in the other, and the two extractions are byte-identical.
- Wire it into `modules/claude/default.nix` on the same path `hms` already exercises for these files. It is a shell or Python assertion, not a new service.
- **Start with exactly one section: WI-7's STOP-condition exclusions**, the block that actually drifted. Add sections as later drift is found. Marking all five identically-titled sections on day one would assert byte-identity over content that legitimately differs by tier, and the first false positive would discredit the check.

**Validation gate for 2.9.** All four must pass before Stage 2's gate closes.

1. **`hms` completes** with the check wired in and the corpus in its post-2.1 state.
2. **The check fails on an injected drift.** Deliberately alter one character inside one marked block in one file, run `hms`, confirm it fails and names the section. Revert. **A check never observed failing is not known to work** — this is the composition-root problem applied to the assertion itself, and it is the single most important item in this gate.
3. **The check passes on the real corpus** after 2.1's exclusions are copied in.
4. **Marker inertness.** Spawn one `sstaff` session and confirm the markers appear nowhere in behavior — no reference to `SYNC:` in output, no attempt to interpret them as instructions.

**What 2.9 does not do.** It does not consolidate, does not remove the 250–300 duplicated lines, and does not fix the sixteen cross-references pointing into a file the `sstaff` context lacks. Those were option (A)'s job and option (A) was not chosen. The dangling references stay baselined by gate check 5 and unfixed.

**One assessment closed here rather than deferred.** `--effort xhigh` is defensible on Anthropic's own text: D14 says *"Start with `high`, the default … step up to `xhigh` for demanding coding and agentic work"*, and a coordinator session is demanding agentic work. The residual finding is D16's imperative — *"If you carried effort settings over from an earlier model, run a fresh effort sweep on your evals rather than reusing them"* — against an unconditional pin that applies to trivial sessions as well as demanding ones. **§ Q8(C) settled it: keep the pin, add the rationale, run no sweep.** Unit 2.11 implements that. **Bound, unchanged and still load-bearing:** no eval was run, and "demanding agentic work" is a judgment. Unit 2.7 confirms or overturns the assessment, and 2.11 runs after it precisely so the recorded rationale cites a finding rather than this paragraph's guess.

**A second closed with a clean negative.** `C-gap-analysis` requires Document D to check D20 (*"Remove any rule telling the model not to think or not to reason"*, Opus 5) against the two output styles. Measured: `rg -ni 'skip (explanations|reasoning)|do not (think|reason)|without (thinking|reasoning)|no reasoning|don.t (think|reason)|skip.{0,15}reasoning'` over both files returns **zero matches**. The ambiguous phrasing *"Skip explanations, reasoning, or evidence"* exists only in the agent tier (`finance.md:397`, `ai-expert.md:612`, `marketing.md:396`, `swe-backend.md:557`, `swe-security.md:361`, `qa-engineer.md:349`) — which is `model: sonnet`, outside D20's scope, and where INFERENCE 1 forbids extending it. **No D20 work item exists in any stage.** Like CG3, this is an honest negative: the check could have found a defect and did not.

### Stage 2 validation gate

1. `hms` completes.
2. **Stage 1's invariant assertion script still passes** — the coordinator prompts restate several Tier-1 rules, and 2.8's relocation must not take a restatement's only surviving copy.
3. **A new assertion set for WI-7 and WI-10**, added by this stage and re-run in Stages 3 and 4: all three STOP-condition exclusions present in **both** output styles (this is G11's actual fix, expressed as a check); `senior-staff-engineer.md:47-49`'s default card-creation prohibition still present; all five WI-10 component requirements (AskUserQuestion-tool-only, one question per turn, ELI5 preamble, `(Recommended)` first, free-form escape hatch) present; the seven-field return template present verbatim at its canonical site.
4. **`❌` ≤ `✅` per file** for every file 2.2–2.4 touched, and unchanged `❌` counts — proving additions rather than substitutions.
5. **Internal anchor validation.** Every `§` reference in both output styles resolves to an actual heading. Document B records roughly 390 such anchors as never validated; any stage that renames a heading must not increase the dangling count. Baseline it before 2.8, re-measure after. **Q5(B) means the sixteen `sstaff` cross-references into an absent file stay** — baseline them, do not fix them, and do not let the count grow.
6. **The sync check's own four-item gate passes** — see § Unit 2.9 in full. Item 2, the injected-drift test, is not optional: an assertion never observed failing is not known to work.
7. **The two additions are present and bounded.** `staff-engineer.md:122`'s imperative is byte-identical to its pre-2.10 form and a motivation passage now sits beside it — proving 2.10 added rather than substituted, the same test SG3 applies to `❌`/`✅`. And `git diff` on `staff.bash` and `sstaff.bash` shows **comment lines only**, with no flag, argument, or model alias altered.
8. **Owner soak, two weeks**, watching specifically for: a review that should have fired and did not; an AskUserQuestion that arrived malformed; a sub-agent returning the wrong shape.

### Stage 2 revert procedure

Same commit-per-unit shape, same `git revert` + `hms` + re-assert cycle. **Stage 2's revert hazard changed shape with § Q5(B).** The original hazard was a Tier-3 consolidation leaving the corpus pointing at a deleted file; (B) chose no consolidation, so that hazard is gone. The replacement hazard is worse-behaved and lives on the deploy path: 2.9 touches **three things at once** — the section markers in both output styles, the check script, and its wiring in `default.nix`. Reverting any two of the three without the third leaves either markers with no check (silent, harmless) or a check with no markers (`hms` fails on every subsequent deploy until fixed). **Keep all three in one commit**, and after any 2.9 revert re-run `hms` before doing anything else, to confirm the deploy path is clean. Unit 2.10's revert is trivial — it removes added lines. Unit 2.11's revert touches comments only and cannot change behavior.

---

## Stage 3: Sub-Agent Definitions

### Stage 3 file list

All 17 of `modules/claude/global/agents/*.md`: `debugger.md` (938), `scribe.md` (700), `ai-expert.md` (650), `swe-frontend.md` (613), `swe-backend.md` (590), `researcher.md` (504), `swe-sre.md` (469), `swe-devex.md` (451), `finance.md` (423), `marketing.md` (416), `swe-security.md` (410), `swe-infra.md` (380), `qa-engineer.md` (363), `swe-fullstack.md` (361), `lawyer.md` (352), `visual-designer.md` (245), `product-ux.md` (185).

### Stage 3 units

Seventeen disjoint files make this the most parallelizable stage. The constraint is that several gaps are cross-file normalizations, so those are **batched by disjoint file group** — engineering (7), support (7), business (3) — and the three batches run in parallel while a per-file unit and a batch touching the same file may not.

| Unit | Files touched | Gaps closed | Model | Why |
|---|---|---|---|---|
| **3.1a/b/c** | engineering 7 / support 7 / business 3 | **G3 + G9 together** — correct the MCP-reachability claim and remove the inert `mcp:` frontmatter key. Correct the reachability statement; **do not delete the four-tier research priority order**, which is useful guidance independent of the error | sonnet | Mechanically bounded: a known-wrong claim replaced by a known-right one, with an explicit do-not-delete boundary. Three batches, disjoint files, fully parallel |
| **3.2** | `scribe.md`, `ai-expert.md`, `finance.md`, `marketing.md`, `lawyer.md` | **G4** — the skip-then-always-read contradiction and the phantom `skills:` frontmatter reference. Document B settles which side wins: Tier 1 arrives unrequested, so "skip the read" is correct | sonnet | ~6 lines, one correct answer, already determined |
| **3.3** | all 17, one at a time or batched by group | **G10** — replace competing return-format conventions per SG6 | **opus** | Three-way inconsistency inside each file, and the `Hard Rule: STOP on structurally broken MoV` block is off-limits because it is WI-3's prompt half. A sonnet pass normalizing "return format vocabulary" would plausibly edit exactly that block |
| **3.4** | engineering 7 / support 5 / business 2, batched | **G7** — ~208 lines of shared-layer restatement, per SG2. **Start with the paraphrase-drift instances** (`finance.md:37-42`, `marketing.md:37-42`), which are the actively harmful subset | sonnet | Deletion of text verifiably present elsewhere. Blocked on Stage 1: deduplicating against a CLAUDE.md section Stage 1 then relocates would leave the content nowhere |
| **3.5** | all 17 frontmatter blocks, batched by group | **G15** — narrow `tools` grants | sonnet | Cheap but changes runtime capability, and sub-agents run in `dontAsk` mode, so an over-narrowed grant is denied outright with no interactive recovery. Use `researcher.md:5`'s method: confirm the body never calls the tool before removing it |
| **3.6** | `debugger.md`, `qa-engineer.md` | **G13** — the support tier's zero-`✅` files, `debugger.md:67`-`:71` and `qa-engineer.md:65`-`:71` | sonnet | Additive, SG3's test applies |
| **3.7** | `swe-security.md` | **D42** — add the missing trigger clause per SG11 | sonnet | One frontmatter line, one measured violation, mechanically checkable |
| **3.8** | `swe-devex.md` + `swe-infra.md`; `swe-backend.md` + `swe-fullstack.md`; `debugger.md` + `swe-sre.md` | **D42 collision pairs** — add reciprocal boundary clauses to the three unhandled pairs | sonnet | The remedy shape already exists in the corpus. Three units, each touching two files, all disjoint from each other |
| **3.9** | none (read-only) | Determine whether the in-file `When Done` sections are load-bearing at runtime or vestigial — Document B's open question, on which 3.3's design depends | sonnet | Must precede 3.3 |

**Not planned here — and now closed rather than gated.** NA4 (agent-definition length) and NA7 (Sonnet prompt bulk) are both authority-less, and **§ Q1(A) closed both for this effort.** NA7 in particular was **refuted** as a gap independently of Q1: Anthropic names no size threshold, and D17's prescribed remedy *adds* steering text rather than cutting lines. Deduplicating the 13-line `.kanban/` block would also remove the prompt half of WI-3's deliberate double cover. **Consequence for the stage as a whole: Stage 3 removes no lines on a length argument anywhere.** Every unit above is a defect fix (3.1, 3.2, 3.3) or a cited normalization (3.4's SG2 deduplication, 3.5's D43 grants, 3.6's SG3 pairs, 3.7/3.8's D42 descriptions). A card that arrives at Stage 3 looking to shrink 8,050 lines has misread this document.

**A decision point sits immediately after unit 3.3, per § Q7(C).** Q7 deferred the WI-14 `SubagentStop` structural check until after Stage 3, on the ground that building a hook against three competing return formats specifies a check for a shape 3.3 is about to change. The mechanics: **collect the return-shape outcomes from gate check 6** — the live delegation test per touched agent type — and treat that as the failure-rate measurement. Then decide, with data, whether a presence-only check is worth its new failure mode (a sub-agent blocked from stopping over formatting, in a path that currently always succeeds). **This is a decision point, not a work unit.** Nothing in Stage 4 depends on it, and it must not be quietly upgraded into hook work by a Stage 3 card.

### Stage 3 validation gate

1. `hms` completes.
2. Stage 1's and Stage 2's assertion scripts still pass.
3. **`mcp:` absent from all 17 frontmatter blocks**, and the four-tier research priority order still present wherever 3.1 touched a file.
4. **`Status: blocked` and the `Blocker:` line still present in all 17** — the direct check that 3.3 did not edit WI-3's prompt half. Also: the `.kanban/` block present in all 17, unchanged.
5. **SG11's trigger test passes for all 17** `description` fields, and the three collision pairs each carry a reciprocal clause.
6. **A live delegation test per touched agent type.** Spawn each agent on a trivial real card and confirm it returns in the coordinator's seven-field shape and that `kanban criteria check` still succeeds from inside it. `dontAsk` mode means an over-narrowed tool grant surfaces only at runtime — this is the only check that finds it.
7. **Owner soak:** every touched agent type exercised at least once on real work.

### Stage 3 revert procedure

Per-file commits make this the cleanest stage to revert: `git revert <sha>` for the single agent file, `hms`, re-run check 6 for that agent type. Batched units (3.1, 3.4, 3.5) commit per batch, so a revert takes the whole group back — acceptable, because the whole group shares one change shape. If check 6 fails for an agent after 3.5, revert 3.5's batch rather than hand-patching the `tools` line, so the frontmatter returns to a known state.

---

## Stage 4: Skills

### Stage 4 file list

All 13 of the Tier-5 files, with the seven over-cap ones as the primary targets: `project-planner/SKILL.md` (1,332), `smithers/SKILL.md` (804), `pr-review/SKILL.md` (705), `user-voice/SKILL.md` (634), `pr-review-watcher/SKILL.md` (549), `crew-cli/SKILL.md` (549), `kanban-cli/SKILL.md` (542). Plus `card-creation.md` (76), `TOOLS-DETAILED.md` (341), and `edge-cases.md` (366) for NA5's correctness defects.

### Stage 4 units

| Unit | Files touched | Gaps closed | Model | Why |
|---|---|---|---|---|
| **4.1** | `project-planner/SKILL.md` + a new supporting file | **G6 then G5** — relocate `:984-1131` and `:1132-1241`, 258 lines of worked-example repetition, into one supporting file referenced one level deep | sonnet | SG9 classifies this content high-freedom: deviating produces a worse plan, not a hard rejection. The cleanest first use of the mechanism |
| **4.2** | `smithers/SKILL.md` | **G5** — 804 lines. Must first resolve which of its two state models is correct, which Document B flags as requiring the `ScheduleWakeup` implementation semantics rather than the skill text | sonnet | Blocked on a correctness determination that is not a prompt question |
| **4.3** | `pr-review/SKILL.md` | **G5** — 705 lines. Note `:398` inlines both supporting files into every specialist prompt, so they are not read-on-demand in practice; the mechanism is present but defeated | sonnet | Requires understanding why the inline exists before removing it |
| **4.4** | `user-voice/SKILL.md` | **G5** — 634 lines | sonnet | Straightforward, and SG4's category test governs its verbatim-user-correction catalogue |
| **4.5** | `pr-review-watcher/SKILL.md` | **G5**; **G16** (`:43`, `:133` document the same deprecated field as inert twice); **G8** (`:206`'s Pagination Discipline restatement, per SG2) | sonnet | Three small independent changes in one file |
| **4.6** | `crew-cli/SKILL.md` | **G5** — 549 lines, and hook-injected wholesale at `SessionStart` for `sstaff`, so its cost is unconditional per session | sonnet | Apply SG9 first: which parts of a CLI reference are low-freedom exact scripts? |
| **4.7** | `review-citation-guide.md` | **G8** — `:11-14` restates the three-tier source priority without attributing it, a latent drift source | sonnet | Four lines, add attribution |
| **4.8** | `card-creation.md` | **NA5 defect 1** — the file teaches a criterion format the CLI rejects: 11 occurrences of `[MoV:` and zero of `mov_commands` | sonnet | Plain correctness, verifiable against `kanban.py`. Independent of everything else; can run any time |
| **4.9** | `TOOLS-DETAILED.md` | **NA5 defect 2** — a 341-line orphan documenting two tools the repository no longer ships | sonnet | Blocked on a policy call both Document B and Document C declined: delete or rewrite. **Not one of the nine decided questions** — it is tracked in § Out Of Scope and 4.9 stays blocked until it is made |
| **4.10** | `edge-cases.md` **and** `staff-engineer.md` (pointers only) | **NA5 defect 3** — 366 lines with zero inbound pointers from either output style, so the guidance never loads | sonnet | **Remedy narrowed by § Q1(A): add pointers only.** The original *"or fold the content in"* option is prohibited — folding changes an output style's length and NA3 is closed. If pointers prove insufficient, 4.10 stops and reports rather than reaching for the folding option. Touches a Stage 2 file, so it runs after Stage 2 |

**`kanban-cli/SKILL.md` is not a length target, and this is the plan's clearest instance of evidence stopping a change.** **D32** (`A-anthropic-v5-guidance.md:723`) says fragile, error-prone, must-be-exact operations get exact scripts with no room for interpretation. The 223-line banned-pattern catalogue at `:31-254` governs card authoring whose failure mode is a hard CLI rejection at `kanban.py:1258-1276` — SG9 classifies it low-freedom, so it stays inline and complete. At 542 lines against a 500-line cap it is 8% over. `C-verification` calls D32's omission from Document C *"the most substantive miss"* for exactly this reason, and two further constraints point the same way: VP8 makes this file G13's **template**, and NA9's exception establishes that its incident citations at `:180` and `:220` function as evidence that the banned patterns are real. The only Stage 4 change authorized for this file is the small `G16` class of stale-content fix, if any is found. **Any card proposing to relocate `:31-254` must argue against D32, not against a line count.**

**Hard sequencing.** G6 before G5 — the supporting-file mechanism is what G5's fix depends on. And references stay **one level deep from SKILL.md**: Anthropic documents that nested references cause partial reads via `head -100` previews, which for any catalogue would be worse than leaving it inline.

### Stage 4 validation gate

1. `hms` completes.
2. Stages 1–3 assertion scripts still pass.
3. **Every over-cap file at or under 500 lines, or carrying a stated D32 exemption in the plan.** `kanban-cli/SKILL.md` carries the exemption.
4. **Reference depth ≤ 1 from every `SKILL.md`.** Mechanically checkable: no supporting file may itself reference a third file.
5. **`kanban-cli/SKILL.md:31-254` byte-identical** to its pre-Stage-4 state, apart from any explicitly approved stale-content fix. This is the check that enforces the D32 exemption rather than merely stating it.
6. **A card authored per `card-creation.md`'s post-fix format is accepted by `kanban`.** The defect is that the current format is rejected; the fix is verified by the CLI accepting it, not by reading the file.
7. **Each touched skill invoked once on real work**, confirming supporting files are found and read.
8. **Owner soak:** one full planning cycle through `project-planner`, one `pr-review`.

### Stage 4 revert procedure

Skills are the safest tier to revert because each is independently invocable. Per-skill commits; `git revert <sha>`, `hms`, re-invoke that skill once. One hazard: reverting a G6 relocation must also revert the `SKILL.md` reference that points at the now-deleted supporting file. Keep the content move and its reference in one commit. If a supporting file was `git add`-ed as new, the revert removes it and `hms` must be re-run to drop it from the deployed tree.

---

## Workflow Invariant Preservation Plan

Document B's nineteen invariants, walked in order. **The load-bearing distinction: an invariant protected only by prompt wording can be destroyed by a rewrite with nothing failing.** Enforcement classifications are Document B's, verified there directly against `modules/claude/default.nix`, `modules/kanban/kanban.py`, and the hook scripts.

### WI-14 — resolving the contradiction, and stating which reading was adopted

`C-verification` contradicts itself: its `## Overall Assessment` correction 2 lists WI-14 among G12's three *hookable* invariants, while its own body places WI-14's return-format contract in the *unhookable* list on the ground that no hook can enforce it as content quality. `C-gap-analysis` G12 records the discrepancy with an explicitly labelled hypothesis and leaves it open for this document.

**I checked Document B rather than taking the instruction on faith.** `B-current-configuration.md:806`, in the WI-14 entry, reads: *"**Enforced by:** **prompt only, and at the delegation-prompt level specifically.** Zero of the 17 agent definitions carry it (CT-3), so the contract exists solely in text the coordinator composes per launch."* Document B's `## Workflow Invariants To Preserve` header states that all enforcement classifications were verified directly against `default.nix`, `kanban.py`, and the hook scripts and are *"not inferred from the inputs."*

**Document B is explicit that WI-14 is currently prompt-only, and silent on whether it could be hooked.** Per the safe-assumption rule — over-protecting costs friction, under-protecting can silently delete an invariant — **this plan treats WI-14 as prompt-only and not hookable.** Consequences, stated so no later card re-litigates them:

- **G12's hookable subset is WI-18 and WI-12 only.** WI-14 is excluded.
- WI-14 remains in § Non-Gaps' unhookable subset, where `C-gap-analysis` currently places it.
- The verification's body reading is adopted; its `## Overall Assessment` reading is not.
- A structural-presence check at `SubagentStop` — asking only whether the seven field labels appear, not whether their content is good — is technically available, because the repository already runs four `SubagentStop` hooks. It is **not planned as gap work in any stage**. **§ Q7(C) deferred it until after Stage 3**, to be decided against the return-shape failure rate that Stage 3 gate check 6 produces. Two things follow: WI-14's *"high and asymmetric"* prompt-only risk is accepted through Stage 3 on the record, and no Stage 3 card may upgrade the deferral into hook work.

### The invariant walk

| # | Invariant | Currently lives | After the rewrite | How the rewrite verifies it survived | Hook or CLI in addition to prompt? |
|---|---|---|---|---|---|
| WI-1 | Card lifecycle, four statuses | `kanban.py:54`; guidance at `staff-engineer.md:1631-2608` | Guidance may move under G14; the statuses are code | CLI is the source of truth; nothing to assert | **Yes — CLI** |
| WI-2 | Every AC carries an executable command | `kanban.py:734-736` etc.; authoring prose at `staff-engineer.md:1633-1859`, `kanban-cli/SKILL.md:31-254` | Both prose sites stay. The catalogue stays inline per **D32** | Gate 4.5: `kanban-cli/SKILL.md:31-254` byte-identical | **Yes — CLI** |
| WI-3 | Sub-agents may run only `criteria check`/`uncheck` | `kanban-subagent-cmd-hook.py:392`, `:496`; 13-line prompt block in all 17 agents | Unchanged. The `.kanban/` block is not deduplicated | Gate 3.4: block present in all 17 | **Yes — hook** |
| WI-4 | ACs independently reviewed before close | Four `SubagentStop` hooks; `staff-engineer.md:1333-1384` | Prose may be reworded; the gate is mechanical | Gate 3.6: a live card still closes | **Yes — hook** |
| WI-5 | Delegation-only posture, opposite per tier | `staff-engineer.md:122`, `:17-19`; `senior-staff-engineer.md:43`, `:51` | Both tiers' rules survive as written unless the owner answers CG1 otherwise | Gate 2.3 assertions; **CG1 is out of scope** | **Split** — background execution hook-enforced; delegate-rather-than-implement prompt-only |
| WI-6 | Card content reaches sub-agents by injection | `default.nix:1030-1038`, `kanban-pretool-hook.py:884-899` | Untouched; invisible to prompt text | Gate 1.5: the injection smoke test | **Yes — hook** |
| WI-7 | Mandatory review protocol and its tiers | `staff-engineer.md:1472-1526` (exclusions at `:1486-1488`); mirrored incompletely at `senior-staff-engineer.md:2357-2379`; `review-protocol.md` | Exclusions present in **both** output styles after 2.1 | Gate 2.3: all three exclusions asserted in both files, plus `senior-staff-engineer.md:47-49` still present | **No — prompt only. Highest care.** |
| WI-8 | Permission-gate recovery flow | `staff-engineer.md:1079-` and `delegation-guide.md:7-118`; `perm.py:184`, `:210` | Unchanged. **Diff the two copies before editing either** — Document B records an unmeasured suspected drift and `delegation-guide.md:122` names `staff-engineer.md` authoritative | Gate 2.3 asserts the two-options rule; the diff is a precondition on 2.5 | **Mixed** — `perm` CLI backs the mechanism; the decision protocol is prompt-only |
| WI-9 | Git and PR conventions | Global `CLAUDE.md:26-35`, `:395-441`, `:442-450`, `:457-467`; restated `staff-engineer.md:223-244`, `:2654-2695` | All four global sections are **protected floor**. The coordinator restatements may consolidate under SG2 only if the global copy is confirmed present | Gate 1.3 asserts every banned-phrasing entry, `--draft`, the prefix, and SHA-pinning by phrase | **Split** — hook-skip flags hook-enforced; draft-first, prefix, and phrasing rules prompt-only |
| WI-10 | Structured question protocol | `staff-engineer.md:1265-1332` plus ~20 restatements; `senior-staff-engineer.md:2708-2851` | Primary statement untouched. **Restatements are not consolidated** — that is CG2, out of scope | Gate 2.3 asserts all five component requirements individually | **No — prompt only. Highest care, tied with WI-7.** |
| WI-11 | Parallel execution and file-conflict scheduling | `staff-engineer.md:1130-1167`, `:829`, `:831`; `parallel-patterns.md`; `kanban.py:1818`, `:1848` | Prose may be reworded under G13 (2.4); the conflict half is code | The dangerous half is CLI-guarded; assert same-turn batch atomicity by phrase | **Mixed** — file-conflict half CLI-enforced |
| WI-12 | Worktree confinement | Global `CLAUDE.md:37-52`; `staff-engineer.md:1168-1199`; `senior-staff-engineer.md:337` | **Protected floor**, unshortened. Its `senior-staff-engineer.md:347` cross-reference into an absent file is a CG5 question | Gate 1.3 asserts **every enumerated prohibited-target category** individually, not the heading | **No — prompt only.** In G12's hookable subset; see § Out Of Scope |
| WI-13 | Improvement-note capture loop | `staff-engineer.md:388-473`, `:1589-1630`; `self-improvement.md` | Survives. **G3's MCP correction must not delete the four-tier order this loop's guidance sits beside** | Assert the five-field note format and the `claude-improvement` tag by phrase | **No — prompt only**, and dependent on a coordinator-only MCP capability |
| WI-14 | The 7-field return contract | `staff-engineer.md:1016-1078`, pasted per launch | Canonical site untouched; competing agent-side formats removed per SG6 | Gate 2.3 asserts the template verbatim; gate 3.4 asserts the off-limits block; gate 3.6 tests a live return | **No — prompt only.** See the resolution above |
| WI-15 | Exception-skill routing | `staff-engineer.md:370-387` | Table survives G14 relocation intact — it is coordinator behavior, not project knowledge | Assert every exception-skill name in the table | **No — prompt only** |
| WI-16 | Search-tool and shell discipline | Global `CLAUDE.md:343-371`, `:372-386`; `staff-engineer.md:1770`, `:1930` | **Protected floor.** The two coordinator extensions may consolidate under SG2 | Gate 1.3 asserts `rg`-not-`grep`, `fd`-not-`find`, the `rg -E` footnote, one-command-per-call, and the `sh -c` prohibition | **Mixed** — `cd`-compound half hook-enforced |
| WI-17 | Never Homebrew | Global `CLAUDE.md:7`, `:15`, `:144`, `:387-394`; project `CLAUDE.md:9-12` | **Protected floor** in both files. Its shape is VP7's model, so preserve the shape as well as the content | Gate 1.3 asserts the prohibition in both files | **No — prompt only** |
| WI-18 | Destructive-operation prohibitions and the ask-first set | Global `CLAUDE.md:26-36`, `:53-65`; project `CLAUDE.md:160-166`; `staff-engineer.md:143`; `anti-patterns.md:124` | **Protected floor.** SG3's positive-framing fix explicitly does not apply | Gate 1.3 asserts each of the four ask-first operations and `perm purge` by name | **No — prompt only**, except the hook-skip subset. In G12's hookable subset |
| WI-19 | Session bootstrap and post-compaction re-injection | `default.nix:1102-1148` | Untouched. **Do not re-implement in prose what is already mechanical** | Gate 1.5 exercises it incidentally | **Yes — hook, entirely** |

### What protects each prompt-only invariant during rewriting

Seven invariants are prompt-only with no mechanical backstop (WI-7, WI-10, WI-12, WI-13, WI-14, WI-17, WI-18) and four more have a prompt-only half (WI-5, WI-8, WI-9, WI-16, plus WI-11's judgment half). Five of those live wholly or partly in the two files Stage 1 shortens. Four mechanisms protect them, in decreasing order of reliability.

1. **The assertion script.** A committed `rg -q` pattern per invariant, keyed to its most distinctive phrase rather than to its heading, re-run at every stage gate. This catches deletion and gross rewording. It does **not** catch a rewording that preserves the phrase while changing the rule's scope — see § Verification Strategy.
2. **The protected-floor designation.** The sections enumerated in § Stage 1 are named in every card that touches their file, as off-limits, with the line span. An agent that reads its card cannot claim it did not know.
3. **The opus model tier on every unit that edits a file containing one.** Units 1.4, 1.5, 2.1, 2.5, 2.6, 2.8, 2.9, and 3.3 are all opus for this reason and no other.
4. **The owner soak.** The only detector for a scope change that preserves the phrase. This is weak, and § Verification Strategy says so.

---

## Verification Strategy

The hardest problem in this plan. Rewriting a prompt cannot be proven behavior-preserving, and a plan that claims otherwise is more dangerous than one that admits its blind spots.

### What can be checked mechanically

- **`hms` builds and completes.** Catches Nix evaluation errors and flake8 failures. `nix flake check` does not run flake8 and is not a substitute.
- **Line counts against committed targets.** `wc -l`.
- **Presence of every protected rule**, via the committed assertion script keyed to distinctive phrases. This is the plan's primary mechanical defense and it grows monotonically: Stage 1 writes it, Stages 2–4 extend it, and every gate re-runs all of it.
- **Absence assertions.** `mcp:` gone from 17 frontmatter blocks. Zero occurrences of `[MoV:` in `card-creation.md`. Zero D9-prohibited severity-gating phrasings, re-verifying `C-measurements` Measurement 3's clean negative after every stage.
- **Structural properties.** `❌` ≤ `✅` per file. Reference depth ≤ 1 from every `SKILL.md`. Every `§` anchor resolving to a real heading. `description` fields passing SG11's trigger regex.
- **Byte-identity of designated blocks.** `kanban-cli/SKILL.md:31-254`; the `Hard Rule: STOP on structurally broken MoV` block in all 17 agents. A hash comparison, not a judgment.
- **Hook compatibility.** Every hook in `default.nix` matches on tool name and input shape, not on prompt content, so prompt edits cannot break one — Document B's WI-19 and `C-verification`'s cleared negative both say so. Two exceptions must be checked anyway: the `SessionStart` `skill-autoload-hook` reads `kanban-cli/SKILL.md` and `crew-cli/SKILL.md` by path, so Stage 4 must not move or rename either file; and `kanban-pretool-hook.py` injects card XML into the sub-agent prompt independent of any agent definition, so Stage 3 must not add prompt text that contradicts the injected card.
- **Live functional tests.** A card authored per the fixed `card-creation.md` is accepted by `kanban`. Each touched agent type returns in the canonical shape and can run `kanban criteria check`. A sub-agent's leading `claudeMd` block still contains both Tier-1 files. These are the closest thing to integration tests available, and they are the only checks that exercise the injection path rather than the file contents.

### What requires the owner using the system

- **Whether a rule that is still present is still *followed*.** D33 ties file length to adherence, so Stage 1's whole premise is that adherence changes with length — and adherence is not measurable by grep. If shortening the global file improves adherence, nothing observable confirms it; if a relocation *reduces* adherence for a relocated rule, the only signal is Claude doing the wrong thing in front of the owner.
- **Whether a rewording narrowed a rule's scope while preserving its phrase.** This is the failure mode the assertion script cannot catch and the one most likely to occur, because narrowing is exactly what a well-meaning "make it more specific" edit does. G11 is a worked historical example: the rule was present in both files and its *exclusions* were not.
- **Whether relocated content still arrives when needed.** A rule moved from an always-injected file to an on-demand surface loads only when the model judges it relevant. `C-gap-analysis` G2 names the concrete case: the macOS Trash pitfall is absent exactly when a session stumbles into it unprepared. This is why that section is protected floor rather than a relocation candidate — but the same risk applies to every one of the 172 candidate lines, at lower stakes.
- **Whether the coordinator's judgment changed.** WI-5's delegate-rather-than-implement half, WI-11's parallel-versus-sequential judgment, and WI-7's review-triggering decisions are all judgment calls. No assertion detects a coordinator that has started making them slightly differently.

### Leading indicators that would reveal a regression early

Ranked by how early they appear and how unambiguous they are.

1. **A card that closes without a review.** WI-7 is prompt-only, and G11 proves this exact drift can happen silently. Cheaply observable: `kanban list` against the session's review cards.
2. **A sub-agent returning the wrong shape.** WI-14. Visible in the first delegated card of a session, and unambiguous.
3. **A malformed AskUserQuestion** — more than one question in a turn, a missing ELI5 preamble, no `(Recommended)` first option, no free-form escape. WI-10's five components, each individually observable in the first question the owner is asked.
4. **A `kanban` card-creation rejection the coordinator did not anticipate.** Signals that MoV-authoring guidance was weakened or relocated out of reach — the WI-2 / D32 risk.
5. **A sub-agent attempting an MCP call.** Signals G3's correction was incomplete or was reverted by a paraphrase.
6. **A `hms` failure on a file nobody touched this stage.** Signals a cross-file assumption broke.
7. **The owner re-typing a correction they typed before the migration.** D36 names this as the trigger for adding to a CLAUDE.md in the first place; its recurrence is the cleanest signal a relocation lost something.

Indicators 1–5 should be checked deliberately at each stage gate, not waited for.

### The rollback trigger

**Roll back the current stage — do not patch forward — when any one of these occurs:**

- Any assertion in the committed script fails and the cause is not a deliberate, documented change in that stage's plan.
- Any of leading indicators 1, 2, or 3 occurs once. These are prompt-only invariant failures with no mechanical backstop; one occurrence is the signal, not a trend.
- `hms` fails and the cause is not resolvable within the unit's scope.
- The owner reports any behavior during the soak period that surprised them and that traces to a file this stage touched.

Rollback means the stage's commits are reverted with `git revert`, `hms` is re-run, and the assertion script plus the stage's live functional tests pass again. Diagnose after reverting, not before — a prompt-only invariant that has already failed once is not a good environment for debugging.

**Not a rollback trigger:** indicators 4–7 alone, or a single subjective impression that output "feels different." Those open an investigation. Rolling back on them would make the plan unable to ship anything.

### What cannot be verified — the blind spots, named

- **No behavioral baseline exists.** Nobody has recorded what this configuration currently makes Claude do, so there is nothing to diff against. Every "did behavior change?" judgment is the owner's memory versus the owner's present experience. This is the single largest hole in this plan's verifiability and it cannot be closed retroactively.
- **Adherence is unmeasurable here.** D33's claim is the entire justification for Stage 1 and this plan has no instrument for it.
- **The assertion script tests presence, not meaning.** A rule can be present, in the right file, matching its pattern, and mean something narrower than before.
- **Anthropic's hooks documentation was never fetched.** Document A's D39 rests on the memory page's cross-reference. G12's hook work — the only Anthropic-endorsed route to the 200-line target — would be designed against uncovered documentation.
- **The Opus 5 and Sonnet 5 system cards were never read.** Roughly 145 pages of official behavioral characterization. Document A calls this *"the largest single gap in the corpus."*
- **`'opus[1m]'` may not be Opus 5.** It is a family alias with a context-window modifier, resolved by Claude Code at invocation time. The coordinator tier is confirmed Opus-*family*; every Opus-5-specific directive applied to it — including D1 and D2, which drive units 2.5 and 2.6 — rests on an inference this repository cannot verify statically.
- **Every duplication figure is a floor.** Document B audited redundancy exhaustively for no file. G7's ~208 lines, NA4's 18.7%, NA3's 250–300, G19's ~20 — all floors. Stage estimates built on them are lower bounds on the work, not measurements.
- **The narrow-audience percentages are upper bounds.** ~82% and ~30% are audience-breadth judgments, and `C-verification` found at least one misclassification inside the largest named block. Units 1.1 and 1.2 exist because of this, and if their re-derivation comes in materially below the ceiling, the project-root file's 200-line target fails too and **§ Q6's committed numbers must be reopened with the owner** before anything is edited. Q9(B) narrowed the global file's tolerance to a single line, so this blind spot now binds tighter than it did when 360 was a proposal.
- **Roughly 390 internal `§` anchors have never been validated.** An unknown number may already be dangling. This plan baselines the count before Stage 2's relocations rather than claiming to fix it.
- **One suspected drift is unmeasured.** `staff-engineer.md:1079`-onward versus `delegation-guide.md:7-118`, the two Permission Gate Recovery sections. Document B calls it the same structural setup that produced the `card-creation.md` defect. Diffing them is a precondition on unit 2.5, not a discovery this plan claims to have made.
- **No repo-wide staleness sweep exists.** One of 44 files has been checked and 2 of the 3 tools it documents had drifted. NA5 may be the visible part of a larger problem.

---

## Out Of Scope

### Contested gaps — all five now closed

Document C's five contested gaps. Two were closed by measurement before the owner saw them; the other three were the subject of Q3, Q4 and Q5 and are now closed by decision. **None remains open.** `C-gap-analysis` states they *"must not be resolved by a rewriter's preference"* — they were not; they were resolved by the owner, and § Decisions records each answer with its rationale.

- **CG1 — the absolute delegation rule** (`staff-engineer.md:122`, every work card MUST delegate) against Anthropic's *"Do not delegate work you can finish yourself in a handful of tool calls."* **Closed by § Q3(C): the rule is load-bearing and stays unchanged; its motivation is added.** Anthropic's concern is cost and time; this repository's is verification, and Anthropic does not address a harness where delegation *is* the verification boundary. Unit 2.10 records that in the prompt so the rule survives a future reader who meets Anthropic's example policy and concludes the rule is a mistake.
- **CG2 — restatement across workflow moments.** D30's density test against D11's per-site scope-statement literalism. Anthropic is silent on restatement, and that silence is load-bearing: it is why G12's restatement argument was demoted to NA8. **Closed by § Q4(A): preserve as D11-compliant per-site scope statement, revisit after Stage 4.** No unit consolidates anything.
- **CG5 — consolidating the two output styles.** **Closed by § Q5(B): keep both files, accept the duplication, add a mechanical sync check.** Unit 2.9 builds it. The consolidation option (A) is relocated below with its reasoning intact.
- **CG3 — severity gating. Resolved, no work item.** `C-measurements` Measurement 3 returned zero matches for every D9-prohibited phrasing across all searched review surfaces. What exists is severity-*labeling* guidance plus explicit anti-suppression clauses at `staff-engineer.md:1941-1956` and `senior-staff-engineer.md:2410` that push the opposite direction from D9's concern. Bounded: prompt text only; review logic in `kanban.py` or `prr.py` was not searched.
- **CG4 — the checklists. Unblocked, and planned.** The model mapping is measured, so D1/D2 govern the coordinator tier. Units 2.5 and 2.6 act on it. The agent tier is out of scope by INFERENCE 1.

### Everything else this plan deliberately does not touch

- **G12's hook work — the highest-value non-prompt outcome in the analysis.** Implementing `PreToolUse` enforcement for WI-18 and WI-12 is neither a rewording nor a restructuring of a prompt file, so forcing it into one of four prompt stages would mis-scope it. It is also the only Anthropic-endorsed route to the 200-line target on the global file. Track it as a separate effort, with the caveat that Document A never fetched the hooks documentation. **§ Q6(B) makes this the gating dependency for ever reaching 200** — see the tracked follow-on below.
- **NA1, NA2, NA3, NA4, NA6, NA7 and NA8.** Closed by § Q1(A) (and NA6 additionally adjudicated as cosmetic on evidence — § NA6 Reclassification). NA5 is the one exception and is *in* scope: `C-gap-analysis` reclassifies it as plain correctness and it is scheduled as Stage 4 units 4.8–4.10. NA9's provenance question is closed by § Q2(B). NA7 is additionally **refuted** on Anthropic's own text — no size threshold exists — so it would be out of scope even if Q1 had gone the other way. **Reasoning for each is relocated below, not deleted.**
- **Anything under `.kanban/`.** Managed exclusively by the `kanban` CLI.
- **`hms --purge`.** Never, under any circumstance, by any agent in any stage.
- **Code: `kanban.py`, `perm.py`, `prc.py`, `prr.py`, `crew.py`, `claude-inspect.py`, and every hook script.** This is a prompt migration. Where a gap's remedy is code, it leaves this plan. **Two narrow, enumerated amendments, and no others.** (i) Unit 2.11 adds **comment lines only** to `staff.bash` and `sstaff.bash` per § Q8(C). (ii) Unit 2.9 adds a check script and its wiring in `modules/claude/default.nix` per § Q5(B), because Q5(B)'s whole point is that the remedy must be a mechanism rather than prompt text. Neither amendment authorizes touching any file in the first sentence of this bullet, and neither authorizes changing behavior in `staff.bash` or `sstaff.bash`.
- **`--effort xhigh` and `--model 'opus[1m]'` in `staff.bash` / `sstaff.bash`.** Assessed in unit 2.7. **§ Q8(C) keeps both pinned**; unit 2.11 documents the `--effort` rationale and changes neither. `--model 'opus[1m]'` is documented nowhere and stays as-is — its alias-resolution uncertainty remains a named blind spot in § Verification Strategy.
- **The Opus 5 / Sonnet 5 system cards**, roughly 145 pages, unread. Not read for this plan either.
- **Fable 5, Mythos 5, and Haiku 4.5 guidance.** Uncovered in Document A. If any part of this configuration is ever pointed at Fable or Mythos, none of the model-specific directives above can be assumed to hold.
- **`TOOLS-DETAILED.md`'s delete-versus-rewrite decision.** Both Document B and Document C declined it as policy; unit 4.9 is blocked on it. Not one of the nine decided questions, and deliberately not promoted into one — it is a housekeeping call on a 341-line orphan, not a plan-shaping decision.

### Deferred pending post-Stage-4 review

**Why this subsection exists.** Q1, Q2 and Q4 removed roughly five work streams from the plan. The *reasoning* behind each cost real analysis, and Q1(A) and Q4(A) were both explicitly framed as *revisited after Stage 4* rather than as permanent verdicts. Deleting the reasoning would force a post-Stage-4 review to re-derive it from Documents B and C. So each item is relocated here with its decision reference, its measured figures, and the fact that made it interesting — enough that a later effort can pick it up cold.

**Read the boundary correctly.** Nothing in this subsection is authorized work. An item here is *deferred*, which means a later effort may reconsider it; it does not mean a Stage 1–4 card may do a small version of it opportunistically.

**D1 — Emoji sirens (NA1). Deferred by § Q1(A).** Roughly 58 `🚨` markers corpus-wide. Authority status: none — Document A's § Emphasis And Over-Steering opens *"Anthropic does not take a position on ALL-CAPS, emoji emphasis, or restating instructions."* The one argument that looked like evidence is **refuted**: the scar-tissue rationale (that each siren marks a real past incident) fails because Document B traced the marker's origin to commit `607de07`, a generic bulk-rewrite. What remains interesting is the *inconsistency* — the two coordinator tiers reach comparable rule strength with 20 sirens versus 2 — which is an internal-consistency argument, i.e. Q1's option (B), which the owner declined.

**D2 — ALL-CAPS and modal intensity (NA2). Deferred by § Q1(A).** `MUST` / `NEVER` / `MANDATORY` register across the corpus; `MANDATORY` appears ~60 times in one coordinator file and zero times in the other. Authority status: none, same sentence as D1 above. Counter-pressure worth carrying forward: Document A finding 7 records that **Anthropic itself uses ALL-CAPS negative framing in its own recommended prompt blocks**, and D25 (*"Use direct imperatives when you want action, not suggestions"*) is cross-model and cuts against softening. Any future de-escalation pass must clear both.

**D3 — Output-style length (NA3). Deferred by § Q1(A).** 5,979 lines across two files. Authority status: none — a **confirmed absence** from a full-page read of `code.claude.com/docs/en/output-styles`. Document A calls extending D33's 200-line CLAUDE.md target to output styles *"the single most likely overreach in the whole effort."* The measured reduction that was on the table: 250–300 restated lines in `senior-staff-engineer.md` (9–10% of the file). **Note the interaction with § Q5(B):** those are the same lines the sync check now polices. A future consolidation effort must retire or re-scope the check, not work around it.

**D4 — Agent-definition length (NA4). Deferred by § Q1(A).** 8,050 lines across 17 files, ~18.7% measured duplication (**a floor, not a measurement** — Document B audited redundancy exhaustively for no file). Authority status: none — a **confirmed absence** from a full-page read of `code.claude.com/docs/en/sub-agents`, which documents no length guidance for a sub-agent's markdown body and no content-splitting mechanism for it either. That second absence matters: even if a future effort wanted to shorten these files, Anthropic documents no supported way to split them.

**D5 — Sonnet sub-agent prompt bulk (NA7). Deferred by § Q1(A), and separately refuted.** The proposal was that long prompts steer Sonnet worse. Anthropic names **no size threshold**, and D17's prescribed remedy for steering problems *adds* text rather than cutting it — so the proposal's own remedy contradicts its premise. Two further blockers a later effort must clear: deduplicating the 13-line `.kanban/` block would remove the prompt half of **WI-3's deliberate double cover**, and INFERENCE 1 forbids importing Opus-5-scoped directives (D1, D2, D20) into this `model: sonnet` tier. **This item is the weakest of the deferred set** and a later review should expect to close it rather than schedule it.

**D6 — Restatement as a substitute for enforcement (NA8). Deferred by § Q1(A).** The observation: several rules are restated many times *in place of* being mechanically enforced. Authority status: none, and the silence is structurally load-bearing — Anthropic's silence on restatement is exactly why G12's restatement argument was demoted from a gap to NA8 in the first place. **Where this reasoning actually went:** § Q5(B) acts on the same underlying instinct through a citable route (D39, prefer a mechanism), and G12's hook work is the other. A post-Stage-4 review should ask whether NA8 has any residue left once those two land, rather than reopening it as stated.

**D7 — Decorative provenance removal (NA9's removable subset). Deferred by § Q2(B).** SG4's category 3: session names and dates in prose rules that already carry their mechanism. Authority status: none for removal; D13 protects only the mechanism sentence. The reduction was real but unmeasured. **The load-bearing constraint to carry forward:** SG4's test, and its worked example where the test says *keep* — project-root `CLAUDE.md:13-31`'s *"160 worktree folders silently routed to the freedesktop dir"* looks decorative and is evidentiary, because stripping it turns a report of damage into a preference between two packages. Same verdict for `kanban-cli/SKILL.md:180` (card #2457) and `:220` (PLA-3559 card #9), where provenance is what makes each ban credible and where removal compounds with **D32**.

**D8 — Restatement consolidation across workflow moments (CG2). Deferred by § Q4(A).** 120–165 measured lines: the AskUserQuestion protocol's ~21 citations and the backslash-pipe MoV rule's six sites. The genuine tension a later effort must resolve rather than pick a side of: D30's density test (*"Only add context Claude doesn't already have"*) against D11's literalism (*"It does not silently generalize an instruction from one item to another"*), which arguably endorses stating scope at each point of application. Document B's reading supports preservation: *"the restatements are positioned at successive points where the error could still be caught."* **The reason this is the most dangerous deferred item to reopen:** the two rules most affected are WI-7 and WI-10, the two highest-risk prompt-only invariants, and if a restatement was doing work, nothing detects its absence. Option (C) — consolidate only where the restatement is verbatim *and* the canonical statement is in the same context — is the tractable middle a later effort should evaluate first.

**D9 — Output-style consolidation into a Tier-3 doc (CG5 option A). Not chosen by § Q5(B).** Recorded because it was the option with the cleanest architecture and a specific, demonstrated hazard, and a later effort will meet both. The hazard: `senior-staff-engineer.md` already carries **sixteen cross-references into a file the `sstaff` context does not contain**, so pointing at a read-on-demand Tier-3 doc is a failure mode this repository has already produced. Q5(B) leaves those sixteen dangling references standing and merely baselined. **A future consolidation must fix the pointer-reliability problem first**, otherwise it converts silent duplication drift into silent content absence, which is worse.

**D10 — `allowed-tools` normalization (NA6). Closed on evidence, not deferred.** Recorded here separately because it is the one item in this subsection with a *verdict* rather than a deferral: **cosmetic**, and Document C's D39 framing of it is inverted. See § NA6 Reclassification for the three findings and the four pieces of evidence. A later effort should not reopen NA6 as a security item on the strength of `C-gap-analysis.md:427`, which this document refutes.

### The tracked follow-on to 200 (§ Q6(B))

**Status: tracked, not scheduled.** Q6(B) commits to 360 for the global `CLAUDE.md` now and opens this item to carry the target honestly as a target. It is a separate effort with its own gating dependency, and **no Stage 1–4 card may pull work out of it.**

**Both routes, and what each needs.**

| Route | What it would recover | What gates it | Gating status |
|---|---|---|---|
| **1 — user-scope path-scoped rules** | Up to the full 172-line relocation ceiling could move to a genuinely on-demand surface rather than a destination file that Tier-1 still pulls in | Two unestablished facts: whether a **user-scope** path-scoped rule directory exists at all (Document A records only `.claude/rules/`, project-scoped), and whether `paths:` gating survives into a **non-fork sub-agent**, whose documented context includes *"project rules"* without stating whether the gating holds | **Unit 1.0 investigates, read-only.** Its finding feeds this item. Nothing in Stages 1–4 is planned on the answer |
| **2 — G12's `PreToolUse` hook work** | WI-18's and WI-12's ~40 prompt lines stop being the sole guarantee and become a **double cover**, at which point they may be shortened without removing a guarantee, because the guarantee moved to the mechanism | Implementing the hooks. **This is the gating item, and the owner was explicitly told and accepted that it gates ever reaching 200** | **Not started.** And Document A **never fetched Anthropic's hooks documentation** — D39 rests on the memory page's cross-reference — so this work would be designed against uncovered documentation |

**The honest framing.** Route 2 is the only Anthropic-endorsed route, and it is not a prompt edit. Route 1 may not exist. So the accurate statement of the 158-line shortfall is: **it is a hooks-and-rules problem, not a prompt-editing problem**, and until route 2 lands, 360 is not a compromise — it is the floor. Any later card that treats 200 as reachable by editing prose is repeating the mistake R5 exists to catch.

**One precondition on route 2 that must not be skipped.** Fetch and read Anthropic's hooks documentation before designing anything. Shortening a protected prohibition on the strength of a hook that turns out not to fire the way D39 implies would delete a prompt-only invariant and replace it with nothing — the exact failure this whole document is built to prevent.

---

## Risks And Mitigations

**R1 — Behavioral drift that no mechanical check catches.** The plan's central risk. A rewording preserves every asserted phrase while narrowing a rule's scope; nothing fails; the owner notices weeks later, or never. G11 is the historical proof: the rule was present in both coordinator files and only its exclusions were missing. *Mitigation:* stage the rollout so at most one tier changes per soak period, keeping the search space for a regression small. Assert distinctive phrases rather than headings. Put opus on every unit that touches a file containing a prompt-only invariant. Check leading indicators 1–3 deliberately at each gate rather than waiting for them. **Residual risk: high, and unavoidable.** No mitigation makes this detectable; they only make it findable once suspected.

**R2 — A stage breaks a hook-enforced workflow.** *Assessment:* structurally unlikely. Hooks match on tool name and input shape, not prompt content, and `C-verification` explicitly cleared this. *But three concrete exposures exist and are not theoretical:* the `SessionStart` `skill-autoload-hook` reads `kanban-cli/SKILL.md` and `crew-cli/SKILL.md` **by path**, so a Stage 4 rename or move breaks session bootstrap for a whole coordinator tier; `kanban-pretool-hook.py` injects card XML independent of any agent definition, so Stage 3 text contradicting the injected card produces a conflict the hook cannot see; and WI-3's prompt half sits inside the block Stage 3 unit 3.3 is most likely to edit. *Mitigation:* gate check 4.5 asserts byte-identity of the D32-exempt block; gate check 3.4 asserts WI-3's block in all 17; no Stage 4 unit may rename or relocate either hook-injected skill file, stated as a hard constraint on 4.6.

**R3 — The repository sits in a stylistically split state between stages.** Guaranteed, not merely possible: staging by tier means for weeks the shared layer follows this style guide while the coordinator prompts do not. Two specific harms. Anthropic documents that contradictions resolve arbitrarily (D35), so a half-migrated corpus can hold a rule in two forms at once. And a card authored mid-migration may be executed against whichever style its author happened to read. *Mitigation:* SG2's one-rule-one-tier rule is the main protection — it removes cross-tier restatement, which is where a split state produces actual contradictions rather than mere inconsistency. Unit 3.4 is explicitly blocked on Stage 1 for this reason: deduplicating an agent definition against a CLAUDE.md section Stage 1 then relocates would leave the content nowhere. Every card cites this document by path so there is one style authority regardless of stage. **Accepted risk:** the owner's constraint is staged rollout, and a split state is its cost. Do not resolve it by touching two tiers at once.

**R4 — Document A's guidance is superseded during the migration.** Opus 6 or Sonnet 6 ships, or the memory / sub-agents / skills pages change, mid-effort. Anthropic's own documentation was reorganized once already: Document A C15 records that eight historic core-technique pages were consolidated and the reliability pages moved out of `prompt-engineering/` entirely. *Mitigation:* every style-guide rule carries its citation, so a superseded directive invalidates a named rule rather than the whole plan. At each stage gate, re-check the four artifact-class pages for changes to the two numbers this plan depends on — the 200-line CLAUDE.md target and the 500-line SKILL.md cap — since those two carry most of Stage 1 and Stage 4. **If either number moves, stop and re-run the affected stage's arithmetic before continuing.** If a new model ships, the model mapping in `C-measurements` Measurement 1 must be re-measured before any further Opus-5-scoped or Sonnet-5-scoped edit, because `'opus[1m]'` is an alias and its resolution can change without any change in this repository.

**R5 — Stage 1's committed target is overshot in the other direction and 200 is chased anyway.** A later card, or an agent reading `C-gap-analysis` rather than this document, sees "200 lines per file" and hunts the 158-line shortfall. With every narrow line already relocated, the only remaining sources are the protected floor and D36-endorsed conventions. *Mitigation:* 360/200 are stated as **committed decisions** in § Q6, in § Executive Summary, in § Stage 1's recomputed arithmetic, and in SG8's table, and must be restated in every Stage 1 card. Gate check 3 fails if a protected section's assertion breaks — which is precisely what happens if this risk materializes. **This is the one risk in the list with a genuinely reliable mechanical detector.** *Raised, not reduced, by the decisions:* Q6 turning 360 from a proposal into an approved number means a card that names 200 is now contradicting a decision rather than proposing a stretch goal — easier to adjudicate, but no less likely to be attempted by an agent that read the wrong document.

**R6 — Units 1.1 and 1.2 come in materially below their ceilings.** The ~82% and ~30% figures are upper bounds; the project-root file needs a 63% hit rate on its 298-line ceiling to reach 200. *Mitigation:* 1.1 and 1.2 are read-only and run before any edit, precisely so this is discovered before a target is committed. If either falls short, § Q6 must be reopened with revised numbers before anything is edited. **Q9(B) tightened this risk and the plan should not pretend otherwise:** the global file's threshold moved from 170 to **171 relocatable lines**, because the clarifying clause consumed one of the two lines of slack. A ledger returning 170 was survivable before the decisions and is not now.

**R7 — An over-narrowed `tools` grant silently disables an agent.** Sub-agents run in `dontAsk` mode, so a tool not granted is denied outright rather than queued for approval. *Mitigation:* unit 3.5 uses `researcher.md:5`'s method — confirm the body never calls the tool before removing it — and gate check 3.6 exercises every touched agent type live. Revert the batch rather than hand-patching a frontmatter line.

**R8 — SG4's provenance test is applied too aggressively.** *"Provenance is unprotected by D13"* is not *"provenance is removable everywhere."* Stripping the card numbers inside `kanban-cli/SKILL.md`'s banned-pattern catalogue removes the evidence that makes each ban credible, which compounds directly with D32. *Mitigation:* SG4 states three categories and a test with a restore step, and its worked example is a case where the test says **keep**. **§ Q2(B) largely dissolves this risk rather than mitigating it:** with all provenance retained, SG4 authorizes no deletion anywhere, so there is no aggressive application available to an over-eager rewriter. *Residual, and the reason the risk stays on the list rather than being struck:* a rewriter who reads SG4's three categories without reading the Q2 decision may still infer that category 3 is removable, because the category and its test are deliberately retained for post-Stage-4 use. SG4's rule paragraph now states the closure in its first sentence for exactly this reason, and SG12 carries it as an unconditional prohibition.

**R9 — The sync check becomes a new failure mode on the deploy path.** *New with § Q5(B).* Unit 2.9 puts a byte-identity assertion in `hms`, the one gate the owner cannot route around while still deploying. That is the property that makes it a mechanism — and it means a false positive blocks **every** configuration change, not just a prompt change, until it is resolved. *Mitigation:* byte-identity over explicitly delimited markers rather than any fuzzy or semantic comparison, so a failure is always a real difference and never a heuristic's opinion; a failure message that names the section and emits a `diff`; and **start with exactly one marked section** — WI-7's exclusions, the block that actually drifted — so the first false positive cannot be caused by legitimate per-tier divergence in a section that was never meant to be identical. *Residual risk: low, and worth paying.* Q5(B)'s rationale is that the alternative is an invariant that has already failed silently once.

**R10 — The sync check is built, never observed failing, and is believed to work.** *New with § Q5(B), and it is the composition-root problem applied to an assertion.* A check that is wired in, runs green, and has never been shown to catch anything is indistinguishable from a check that does nothing — the same failure shape as a dependency-injected feature whose real entry point never wires the adapter. *Mitigation:* unit 2.9's validation gate item 2 requires deliberately injecting a one-character drift into a marked block, observing `hms` fail and name the section, then reverting. **That item is not optional and not deferrable to a later stage.** *Residual risk: low, but only because the gate exists* — remove item 2 and this risk becomes indistinguishable from R1.

---

## Recomputed Numbers

Every figure the decisions touched, recomputed and shown. **The headline is counter-intuitive and is stated first so nobody has to hunt for it: the unit count goes UP by two while the plan's authorized change surface goes DOWN by five work streams.** Both are true, and manufacturing deletions to make them agree would be dishonest.

### Unit counts

| Stage | Rows before | Rows after | What moved |
|---|---|---|---|
| Stage 1 | 6 (1.0–1.5) | **6** | None added or removed. 1.3's stakes lowered and 1.4's G16 share became an addition, both by Q9(B) |
| Stage 2 | 9 (2.1–2.9) | **11** | 2.9 reshaped from undetermined into the sync check (Q5(B)); **2.10 added** (Q3(C)); **2.11 added** (Q8(C)) |
| Stage 3 | 11 (3.1a/b/c, 3.2–3.9) | **11** | None. 3.8's row still covers three collision pairs. A Q7(C) decision point added after 3.3 — a decision point, not a unit |
| Stage 4 | 10 (4.1–4.10) | **10** | None. 4.10's remedy narrowed to pointers-only; 4.9's blocker re-worded off Q9 |
| **Total** | **36** | **38** | **+2 units, 0 units deleted** |

**Why zero deletions, when Q1, Q2 and Q4 removed roughly five work streams.** None of the five was ever a numbered unit. They were carried as an owner-gated ambition in § Executive Summary (NA3's and NA4's length reduction), as conditional permissions in SG4, SG10 and SG12 (provenance removal, emphasis de-escalation), as an explicit non-item in Stage 3's *"Not planned here"* (NA4, NA7), and as an unresolved contested gap in § Out Of Scope (CG2). Their status changed from **gated to closed**, and their reasoning is relocated to § Out Of Scope → `### Deferred pending post-Stage-4 review`. The correct summary is: *five ambitions closed, zero units deleted, two units added.*

### The Stage 1 line budget, restated as committed

```
Global modules/claude/global/CLAUDE.md
  530  actual
 -172  relocation ceiling (unit 1.1 must confirm; upper bound, not a measurement)
 ─────
  358  pre-decision floor
   +1  Q9(B) ac-reviewer clarifying clause
 ─────
  359  post-decision floor
  360  COMMITTED TARGET (§ Q6(B))          slack: 1 line

Project-root CLAUDE.md
  387  actual
  -82  protected + D36-must-stay floor        →  305 theoretically removable
 -298  Document B's narrow ceiling, less the 19 protected Trash lines
 ─────
   89  ceiling-based estimate
  200  COMMITTED TARGET (§ Q6(B))          headroom: 111 lines
       required hit rate: 187 of 298 = 63%

Aggregate
  917  current
 -357  committed reduction
 ─────
  560  committed (360 + 200)
```

**Both targets are caps, and both are committed.** The reduction figure of 357 does not move, because the floors still sit under the caps. What moved is the *slack*: 2 lines to 1 on the global file.

### What the decisions changed about what is reachable

**Stage 1 — reachable, but with no margin.** Unchanged in target, tightened in tolerance. R6's threshold moved from 170 to 171 relocatable lines.

**Stage 2 — no longer a reduction stage at all. It is now net-additive.** This is the largest reachability change and it follows directly from three decisions:

- Q1(A) closes NA3, so `senior-staff-engineer.md`'s 250–300 restated lines stay.
- Q5(B) keeps both files, so none of the duplication is consolidated.
- Q4(A) keeps every restatement at every workflow moment.
- Against that, 2.9 adds marker lines, 2.10 adds a motivation passage, and 2.2/2.3/2.4 add paired `✅` bullets by SG3's additive-by-design rule.
- The only reductions left in the stage are 2.5 and 2.6's checklist collapses (three restating items in `staff-engineer.md`, plus whichever of `senior-staff-engineer.md`'s 25 items restate) and 2.8's G14 relocation.

**A newly sharpened conflict in Stage 2, surfaced rather than left to be discovered.** Unit 2.8 relocates the project-scoped subset out of `staff-engineer.md`, and Anthropic's prescribed destination for project knowledge is a CLAUDE.md. The global file now has **1 line of slack**, so it cannot receive that content — 2.8 would breach a committed cap the moment it landed anything there. **Constraint on 2.8, stated as a rule:** its destination is the **project-root `CLAUDE.md`**, which has 111 lines of headroom and is where project-scoped content belongs anyway, or a new supporting file. **Never the global file.** The original unit note said only *"Cannot begin until Stage 1's budget is committed"*; the budget is now committed, and this is what it implies.

**Stage 3 — reduction survives, but only the cited part.** Unit 3.4's G7 removes roughly 208 lines of shared-layer restatement on D31/D36/SG2 authority, and 3.1's `mcp:` removal takes a frontmatter line from each of 17 files. NA4's 18.7% duplication figure and NA7's bulk argument are closed, so **nothing beyond G7 is removable in this stage.** Note that 208 is a floor: Document B audited redundancy exhaustively for no file.

**Stage 4 — unaffected by every decision.** The 500-line `SKILL.md` cap is stated three times across two official hosts, so Q1(A) leaves Stage 4's length work entirely intact. Six over-cap files against a 500-line cap put roughly **1,573 lines** behind the supporting-file mechanism — and note this is genuine context reduction rather than D37's `@path` illusion, because Anthropic documents supporting files as read-on-demand with *"No context penalty for large files."* `kanban-cli/SKILL.md` keeps its D32 exemption.

### The additions ledger — counted, not omitted

Q3 and Q8 add text to files this plan is otherwise shortening, and Q9 adds a line to the tightest budget in the corpus. All three are D13-motivated and all three are correct. Here they are counted.

| Addition | File(s) | Estimate | Enters a line budget? |
|---|---|---|---|
| Q9(B)'s `ac-reviewer` clarifying clause (unit 1.4) | global `CLAUDE.md` | **+1 line** | **Yes — and it consumes half the remaining slack** |
| Q3(C)'s delegation motivation (unit 2.10) | `staff-engineer.md` | +4 to +8 lines | No — output styles have no target, and none may be created (SG8, Q1(A)) |
| Q8(C)'s effort rationale (unit 2.11) | `staff.bash`, `sstaff.bash` | +3 to +6 lines each, comments only | No — outside the 44-file prompt corpus |
| Q5(B)'s `SYNC:` markers (unit 2.9) | both output styles | +4 lines total for the first marked section | No — same reason |
| Q5(B)'s check script and wiring (unit 2.9) | new file, `default.nix` | n/a | No — not prompt text |

**Net effect of the decisions on line count: roughly +12 to +20 lines added across four files, one line of which lands inside the corpus's tightest cap.** Set against a committed 357-line Stage 1 reduction, ~208 cited lines in Stage 3, and ~1,573 lines relocated in Stage 4, the additions are small — but they are real, they are in the direction the plan is otherwise pushing against, and the plan's credibility depends on saying so rather than rounding them away.

---

## The One Remaining Open Question

**One question remains, and it is new.** It surfaced from the NA6 re-examination rather than from Document C, it runs in the opposite direction from NA6 as originally framed, and only the owner can answer it because it is a risk-appetite call rather than a defect.

### Q10 (new) — Narrow `manage-pr-comments`'s `Bash(gh *)` grant, or keep it?

**How this arose.** § NA6 Reclassification established from `code.claude.com/docs/en/skills` that `allowed-tools` is a **turn-scoped permission grant, not a restriction** — *"It does not restrict which tools are available: every tool remains callable."* That inverts NA6's premise: the sibling skill that *declares* the field is the one widening its own surface, not the one omitting it.

**The specific observation.** `manage-pr-comments/SKILL.md:5-7` declares `Bash(prc *)` and `Bash(gh *)`. The `Bash(gh *)` pattern's wildcard matches **every** `gh` subcommand, including destructive writes — `gh pr merge`, `gh release delete`, `gh repo delete`, `gh api --method DELETE` — and pre-approves all of them for the turn that invokes the skill. Meanwhile the skill's own Hard Prerequisites at `:20` name **only** `Bash(prc *)` as required, and its body describes a workflow that runs through `prc`. So the grant is materially broader than the skill's stated need, by the skill's own account of that need.

**Anthropic's caution on the same page**, which is what makes this citable rather than a preference: *"Review project skills before trusting a repository, since a skill can grant itself broad tool access."* And D43's principle — *"grant only necessary permissions for security and focus"* — though note D43 is scoped by Anthropic to sub-agents, not skills, so it corroborates rather than governs.

**Why this is the owner's call and not a defect.** Nothing is broken. The grant is turn-scoped and clears on the next message. The skill is user-scope, authored by the owner, so the untrusted-repository scenario Anthropic's caution addresses does not apply. What is at stake is whether the owner wants a turn-scoped auto-approval of `gh` writes in exchange for not being prompted during comment management.

- **(A) Narrow it to the subcommands the skill actually uses** — e.g. `Bash(prc *)` plus a small explicit `gh` set, or drop `Bash(gh *)` entirely since the Hard Prerequisites name only `prc`. Trade-off: a prompt appears the first time the skill needs a `gh` call nobody enumerated, and in `dontAsk` mode that is a denial rather than a prompt. Mitigated by the fact that narrowing `allowed-tools` cannot *block* anything — `permissions.allow` still governs, so the failure mode is a prompt, not a wall.
- **(B) Keep it, and record why.** Trade-off: no change and no churn, and the broad grant is documented rather than accidental. This is the Q8(C) shape applied to a permission instead of an effort setting.
- **(C) Add a deny-override instead**, the pattern `default.nix:937-941` already uses for `agent-browser`: keep `Bash(gh *)` and block the specific destructive subcommands in the permission block list, where block takes precedence over allow. Trade-off: defense at the mechanism layer rather than the grant layer, which is where D39 points — but it maintains a deny list that must be kept current as `gh` gains subcommands.

**Recommendation: (C).** The repository already uses this exact pattern for exactly this reason, the block list is the layer that actually holds regardless of what any skill grants itself, and it does not risk a `dontAsk` denial in a workflow the owner uses regularly. **This is admissible under Q1** — it cites the grant semantics and the review-before-trusting caution from `code.claude.com/docs/en/skills`, and the remedy shape cites D39. If the owner chooses (A) or (C), it becomes a Stage 4 unit; if (B), a one-line comment beside the frontmatter.

**Nothing else in this document awaits an owner answer.**

---

## Appendix — The Nine Questions As Put, With Their Options And Recommendations

**All nine are answered. This section is historical.** It is retained, not deleted, because the option analyses and trade-offs are the reasoning the owner decided against as well as the reasoning they decided with, and a post-Stage-4 review will need both. **For the decisions themselves and their consequences, read § Decisions — not this appendix.** Nothing here is an open question.

**Where the owner followed the recommendation, and where they did not.**

| Question | Recommended here | Owner's answer | Diverged? |
|---|---|---|---|
| Q1 — judgment-based changes | (A) | **(A)** | No |
| Q2 — incident provenance | (C) | **(B)** | **Yes** — the owner chose the stricter option, keeping *all* provenance rather than sweeping the two output styles |
| Q3 — absolute delegation rule | (C) | **(C)** | No |
| Q4 — restatement consolidation | (A) | **(A)** | No |
| Q5 — output-style consolidation | (B) | **(B)** | No |
| Q6 — 360-line target | (B) | **(B)** | No |
| Q7 — WI-14 `SubagentStop` check | (C) | **(C)** | No |
| Q8 — `--effort xhigh` | (C) | **(C)** | No |
| Q9 — `ac-reviewer` roster entry | (C) then (B) | **(C) then (B)** | No |

**The one divergence is worth reading closely.** On Q2 the owner chose (B) *keep all provenance* over the recommended (C) *remove decorative provenance in the two output styles only*, and gave the reason explicitly: consistency with Q1, since provenance removal has no citation. That is a stricter reading of Q1(A) than this document's own recommendation applied, and it is the correct one — (C) was a bounded-risk argument, not a citation. Later cards should take the Q2 answer as evidence of how strictly Q1(A) is meant to bind.

The nine subsections below are reproduced unchanged from the version put to the owner, so the record shows what was asked rather than a retrospective tidy-up.

### Q1 — Do you want changes that rest on our judgment rather than Anthropic's guidance, and on what basis?

Seven proposals share one property: Anthropic supplies **no authority in either direction**. Each carries an explicit *"Authority status: none"* line in `C-gap-analysis`. They collapse because the decision is identical for all seven — whether an aesthetic or maintainability preference is sufficient reason to change working prompt text — and answering them separately would ask you the same question seven times.

Sub-items: **NA1** emoji sirens (~58 corpus-wide; the scar-tissue rationale is refuted by commit `607de07`). **NA2** ALL-CAPS and `MUST`/`NEVER`/`MANDATORY` intensity. **NA3** output-style length (5,979 lines, no official ceiling). **NA4** agent-definition length (8,050 lines, no official ceiling). **NA6** `allowed-tools` normalization across skills. **NA7** Sonnet sub-agent prompt bulk (**refuted** as a gap — Anthropic names no size threshold, and its prescribed remedy *adds* text). **NA8** restatement treated as a substitute for enforcement.

- **(A) No — nothing without an Anthropic citation ships.** Trade-off: the corpus keeps its current emphasis register and both 3,000-line output styles. Zero risk of a change whose benefit we cannot demonstrate. Six of Document C's eighteen gaps still ship; only these seven do not.
- **(B) Yes, but only for internal consistency** — the strongest available non-Anthropic ground. The two coordinator tiers reach identical rule strength through different devices (20 sirens versus 2; `MANDATORY` 60 versus zero) with no declared convention. This normalizes rather than de-escalates. Trade-off: some churn with no measurable behavioral benefit, which cuts against the only-improvements constraint.
- **(C) Yes, on your stated preference, labelled as such.** Trade-off: honest and fast, but every such change is unfalsifiable, and R1's drift risk applies with no offsetting citable benefit.

**Recommendation: (A) for this effort, revisited after Stage 4.** Document C's own bias was measured as running *"mildly against change"* and it still found eighteen citable gaps. Spending the migration's risk budget on cited changes first, and asking again once the corpus's actual behavior under the new style is known, is the sequencing with the best information.

### Q2 — Incident provenance: remove the decorative instances, keep the evidentiary ones, or leave all of it?

Separated from Q1 because it has a load-bearing exception the other seven do not. D13 protects the **mechanism** sentence. Provenance — session names, card numbers, dates, incident counts — has no authority. But two sites inside `kanban-cli/SKILL.md`'s banned-pattern catalogue (`:180`, `:220`) function as *evidence the banned pattern is real*, which is what makes the ban credible to a reader inclined to argue with it. Removing provenance there is a behavioral change, not a simplification, and it compounds with D32.

- **(A) Apply SG4's three-category test per site.** Delete the provenance, re-read the rule; if it now reads as an arguable opinion, restore it. Trade-off: per-site judgment on dozens of sites, so slow and inconsistently applied across agents. But it is the only option that separates the two categories rather than guessing.
- **(B) Keep all provenance.** Zero risk. Trade-off: forgoes a real, if unmeasured, verbosity reduction.
- **(C) Remove all decorative provenance in the two output styles only**, leaving skills and agent definitions untouched. Trade-off: bounded and low-risk, since the catalogues with evidentiary provenance are all in skills — but the two output styles are the files with the most `Real incident` markers, so it captures most of the available reduction.

**Recommendation: (C).** It gets most of the benefit, stays entirely clear of the evidentiary sites by construction, and does not require a per-site judgment call to be made correctly dozens of times.

### Q3 — Is the absolute delegation rule load-bearing for the kanban verification chain, or a cost inefficiency? (CG1)

`staff-engineer.md:122` mandates that every work card MUST delegate, *"No exceptions for size, simplicity, or convenience."* Anthropic's example policy says the opposite: *"Do not delegate work you can finish yourself in a handful of tool calls."* But work done directly by the coordinator bypasses four mechanisms — `PreToolUse(Agent)` card injection (WI-6), `SubagentStop` AC review (WI-4), the `editFiles` conflict scheduler (WI-11), and the foreground-launch denial (WI-5's enforced half). Anthropic's concern is cost and time; yours appears to be verification. Anthropic does not address a harness where delegation *is* the verification boundary. Note it supplies **no numeric cap** — the only numbers (20 concurrent, 200 per session, 3 nesting layers) are product-enforced limits, not advice.

- **(A) Load-bearing — keep the absolute rule unchanged.** Trade-off: continues to pay a sub-agent's cost and latency for one-line cards, which is exactly what Anthropic says multiplies cost on small tasks.
- **(B) Relax for a defined trivial class**, e.g. single-file documentation edits already covered by a hook. Trade-off: any relaxation routes that work around all four mechanisms, and the class boundary becomes a new judgment call in the highest-risk prompt-only area.
- **(C) Keep the rule and add its motivation** — state that delegation is the verification boundary, not a cost preference. Pure D13 addition, no behavioral change, and it makes the rule survive future readers who encounter Anthropic's guidance and think the rule is a mistake.

**Recommendation: (C).** The rule appears genuinely load-bearing on the evidence, and the only gap is that its prompt text never says *why* — which is precisely what D13 asks for and what makes the rule robust against well-meaning future relaxation.

### Q4 — Restatement at successive workflow moments: consolidate, or preserve? (CG2)

The backslash-pipe MoV rule is fully re-explained at six sites; the AskUserQuestion protocol has roughly 21 citations. D30's density test argues for consolidation. D11's literalism — *"It does not silently generalize an instruction from one item to another"* — arguably endorses stating scope at each point of application, which is what these restatements do. Anthropic is silent on restatement, and that silence is structurally load-bearing in Document C: it is why G12's restatement argument was demoted to NA8. Roughly 120–165 measured lines, and the answer shapes the approach to WI-7 and WI-10, the two highest-risk prompt-only invariants.

- **(A) Preserve — treat restatement as D11-compliant per-site scope statement.** Trade-off: the corpus stays larger, and the pattern keeps growing. But Document B's own reading supports it: *"the restatements are positioned at successive points where the error could still be caught."*
- **(B) Consolidate to one canonical statement plus pointers.** Trade-off: ~120–165 lines saved, against the risk of removing a catch point on the two least mechanically protected rules in the corpus. If a restatement was doing work, nothing will detect its absence.
- **(C) Consolidate only where the restatement is verbatim and the canonical statement is in the same context**, preserving every restatement positioned at a distinct workflow moment. Trade-off: less reduction; requires distinguishing "same rule twice" from "same rule at two decision points," which is a judgment call but a tractable one.

**Recommendation: (A) for this effort.** The two rules most affected are WI-7 and WI-10, both rated highest rewrite risk, both prompt-only. Anthropic's silence means no benefit is citable, and the plan's risk budget is better spent on the eighteen cited gaps. Revisit after Stage 4, when the corpus is otherwise stable.

### Q5 — Consolidating the two coordinator output styles? (CG5)

250–300 lines of `senior-staff-engineer.md` (9–10%) restate content whose fuller version lives in `staff-engineer.md`; five sections share identical titles; sixteen cross-references point into a file the `sstaff` context does not contain; and the manual sync the design depends on **has already failed once, in a security-relevant way** (G11), despite an explicit sync reminder at `senior-staff-engineer.md:2379`. G11's fix shape depends on this answer.

- **(A) Move the shared content to a Tier-3 doc both point at.** Removes the drift source. Trade-off: a specific and demonstrated hazard — the existing sixteen dangling references show that pointing at a file the session lacks is already a failure mode here. A Tier-3 doc is read-on-demand, so the content arrives only if the pointer fires.
- **(B) Keep two files, accept the drift, add a mechanical sync check** — a CI or `hms`-time assertion that the shared sections are byte-identical across both files. Trade-off: keeps the duplication, but converts an invariant that has already failed silently into one that fails loudly. The strongest option on the actual observed failure.
- **(C) Status quo — copy the exclusions into `senior-staff-engineer.md` and move on.** Trade-off: a second copy that can drift again, in the exact place it already drifted.

**Recommendation: (B).** The observed failure was not that the content was duplicated; it was that the duplication drifted undetected. (B) fixes the detection and leaves the architecture — two genuinely different roles with opposite postures on the same tool, which D40 supports — intact. It also converts a prompt-only invariant into a mechanically checked one, which is the direction D39 points.

### Q6 — Do you accept a 360-line target for the global `CLAUDE.md` instead of 200?

The arithmetic in § Stage 1 shows the 200-line target is unreachable: after excluding 183 protected lines and relocating all 172 candidate narrow lines, the floor is ≈358 lines, 158 over target. The 158 could only come from a protected invariant section or from D36-endorsed conventions. D33's 200 is a **soft target**, not a cap — Anthropic states in the same breath that *"CLAUDE.md files are loaded in full regardless of length."*

- **(A) Accept 360 for the global file, 200 for the project-root file** (aggregate 560, a 357-line reduction). Trade-off: a documented, reasoned overshoot of the only Anthropic number tied to adherence — which is the whole justification for Stage 1. Recorded in this document with the subtraction shown, so it is auditable rather than quietly missed.
- **(B) Accept 360 now and open a follow-on effort for the two routes to 200** — user-scope path-scoped rules (unit 1.0 investigates whether they exist), and G12's `PreToolUse` hook work, which would let WI-18's and WI-12's 40 prompt lines become a double cover that can then be safely shortened. Trade-off: (A)'s outcome now plus a tracked path to the target, at the cost of carrying an open item.
- **(C) Insist on 200.** Trade-off: **not available without cutting protected content.** Recorded as an option only so its unavailability is on the record.

**Recommendation: (B).** It commits to the reachable number, keeps the target honest as a target, and correctly identifies that the remaining 158 lines are a hooks-and-rules problem rather than a prompt-editing problem. Note that (B) makes G12's hook work the gating item for ever reaching 200 — worth knowing before agreeing to it.

### Q7 — Add a `SubagentStop` structural check for the 7-field return contract (WI-14)?

`C-verification` contradicts itself on whether WI-14 is hookable. `B-current-configuration.md:806` classifies it as *"prompt only, and at the delegation-prompt level specifically"* and is silent on hookability, so this plan adopts prompt-only as the safe reading — over-protecting costs friction, under-protecting can silently delete an invariant. But the repository already runs four `SubagentStop` hooks, so a check for whether the seven field labels are *present* (not whether their content is good) is technically available.

- **(A) No — leave WI-14 prompt-only.** Trade-off: the contract stays protected by wording alone in a file whose alteration changes it corpus-wide instantly with no agent-side fallback. Document B rates this *"high and asymmetric."*
- **(B) Yes — add a presence-only structural check.** Trade-off: converts the corpus's most asymmetric prompt-only invariant into a double cover, and a malformed return would fail loudly instead of silently. Cost: new hook work, plus a real behavioral change — a sub-agent could be blocked from stopping over formatting, which is a new failure mode in a path that currently always succeeds.
- **(C) Defer until after Stage 3**, when unit 3.3 has removed the competing agent-side formats and the true failure rate is observable. Trade-off: carries (A)'s risk through the stage that touches the contract most.

**Recommendation: (C).** Unit 3.3 is the change most likely to disturb WI-14, and building a hook against three competing formats means specifying a check for a shape that is about to change. Observe the failure rate after 3.3, then decide with data.

### Q8 — Run a fresh effort sweep, or keep `--effort xhigh` pinned unconditionally?

Both coordinator tiers pin maximum effort (`staff.bash:12-16`, `sstaff.bash:12-16`). My assessment, from Document A: this is **defensible** — D14 says *"Start with `high`, the default … step up to `xhigh` for demanding coding and agentic work,"* and coordinator sessions are demanding agentic work. The residual finding is D16: *"If you carried effort settings over from an earlier model, run a fresh effort sweep on your evals rather than reusing them."* The pin is unconditional and applies to trivial sessions too. **Bound: no eval was run, and "demanding agentic work" is my judgment.** Unit 2.7 confirms or overturns it.

- **(A) Keep the pin.** Trade-off: within Anthropic's stated step-up condition, and simple. Pays maximum thinking cost on trivial sessions, and D16's sweep imperative goes unaddressed.
- **(B) Run a sweep** — compare `high` against `xhigh` on a set of representative real cards. Trade-off: the only option that satisfies D16, but it requires an eval harness this repository does not have, and "quality held" for a coordinator session is not a measurable quantity here.
- **(C) Keep `xhigh` and add a documented rationale** in `staff.bash` naming D14's step-up clause. Trade-off: no behavioral change and no measurement, but the choice stops looking like a carried-forward default and becomes a recorded decision.

**Recommendation: (C).** D16's target is settings *reused without thought*. Recording the reasoning addresses the substance without building an eval harness whose output would not be measurable.

### Q9 — `ac-reviewer`: correct the roster entry, or add the missing agent definition?

Global `CLAUDE.md:521` lists `ac-reviewer` in the Support row of the team roster and no `agents/ac-reviewer.md` exists. It appears in code only as a `KANBAN_AGENT` sentinel that short-circuits the sub-agent bootstrap (`default.nix:169-174`) and in a leftover cleanup line (`default.nix:1244`). Document B could not determine from static search whether it has an LLM prompt body defined dynamically elsewhere — which is why G16 says correct the entry *against that answer* rather than delete it on assumption. This is the highest impact-to-risk item in the whole document: one line, in the file every context reads, telling every coordinator a team member exists that cannot be delegated to.

- **(A) Remove the roster line.** Trade-off: correct if `ac-reviewer` is purely a sentinel. If it does have a dynamic prompt body, this deletes a real capability from the roster.
- **(B) Keep the line and add a clarifying clause** — that `ac-reviewer` is the automatic `SubagentStop` AC reviewer, not a delegation target. Trade-off: costs a line in the file Stage 1 is shortening, but it is accurate under either answer to the dynamic-body question and it prevents the failed delegation attempt.
- **(C) Determine the answer first** (unit 1.3, read-only), then apply (A) or (B). Trade-off: one extra read-only unit, which runs in parallel with everything else and blocks nothing.

**Recommendation: (C), then (B) if it is a sentinel.** The determination is cheap and already scheduled. (B) reads better than (A) even for a pure sentinel, because it tells the coordinator what the thing *is* — which is what stops the delegation attempt — rather than only that it is not there.

---

**One process note, for the reader six months from now.** During the writing of this document, harness-injected context reminders appeared between tool calls — a block of MCP-server instructions (Context7, Datadog, incident.io, Linear) arriving immediately after a `Read` call. These were part of this agent's context, not content of any file read. **No `file:line` can be cited for them, because they appear in no file** — not in `A-anthropic-v5-guidance.md`, `B-current-configuration.md`, `C-gap-analysis.md`, `.scratchpad/C-verification.md`, `.scratchpad/C-measurements.md`, this document, or any configuration file in the corpus. All five inputs record the same phenomenon and all five attributed it correctly. It is a harness artifact, not file content.

**The same thing happened during this amendment**, on card #2956: a `Read` of this document returned, in the same tool result, a block of MCP-server instructions and a copy of the global `CLAUDE.md`. Same attribution, same absence of any citable `file:line`, same conclusion. Recorded so the pattern is visible as recurring rather than as a one-off.

---

## Amendment Log

### Amendment 1 — 2026-07-27, session `stout-ember`, kanban card #2956

**Driver: owner decisions on all nine open questions.** The document as written on card #2947 was a proposal with nine questions attached. The owner answered all nine. This amendment records those answers and propagates their consequences. **Nothing in this amendment is a new proposal**, with one exception noted below.

**What changed.**

1. **`## Decisions` added**, placed before `## Style Guide For The Rewrite` so a reader meets the decisions before the work. One subsection per decision, each recording the question, the option chosen, the rationale as the owner gave it, and the consequence for the plan with units named.
2. **`## Executive Summary` rewritten** from proposal to approved plan. It now states the two decisions that shape everything else — cited-changes-only and the 360/200 commitment — in its opening, and it names the two additions Q3 and Q8 commission rather than omitting them.
3. **Five work streams closed and relocated, zero units deleted.** Q1(A) closed NA1, NA2, NA3, NA4, NA7, NA8; Q2(B) closed provenance removal; Q4(A) closed restatement consolidation; Q5(B) closed output-style consolidation. **None of them was ever a numbered unit** — each was a gated ambition, a conditional style-guide permission, or an unresolved contested gap. Their reasoning is relocated intact to `## Out Of Scope` → `### Deferred pending post-Stage-4 review`, ten labelled items with their measured figures and decision references. Saying five units were deleted would have been tidier and false.
4. **Two units added.** **2.10** (Q3(C)): the delegation-rule motivation passage. **2.11** (Q8(C)): the `--effort xhigh` rationale comment. Both add text, both are D13-motivated, both are counted in `## Recomputed Numbers` rather than netted away.
5. **Unit 2.9 reshaped into the mechanical sync check** (Q5(B)), with a full specification: an `hms`-time byte-identity assertion over `SYNC:`-delimited sections, recommended over CI with three reasons and its trade-off stated, starting with one section, plus a four-item validation gate whose second item is a deliberately injected drift.
6. **The tracked follow-on to 200 added** (Q6(B)), naming both routes and identifying G12's `PreToolUse` hook work as the gating dependency, with the precondition that Anthropic's hooks documentation must be fetched first.
7. **Every affected number recomputed** in a new `## Recomputed Numbers` section: unit counts 36 → 38, the Stage 1 budget re-subtracted with Q9(B)'s +1 line applied (floor 358 → 359 against a committed 360, slack 2 → 1), and a per-stage statement of what each decision changed about what is reachable.
8. **Style-guide rules updated where a decision closed a gate:** SG2's bound, SG4's three categories (now authorizing no deletion at all), SG8's table (no owner-judgment fallback for output-style or agent-definition length), SG10's second bucket, and SG12, which gained four unconditional entries.
9. **`## Open Questions For The Owner` replaced.** Retitled to `## Appendix — The Nine Questions As Put, With Their Options And Recommendations` and explicitly marked historical, with a table showing where the owner followed the recommendation and where they did not. The nine subsections are reproduced unchanged so the record shows what was asked. **No open question stands in the approved plan.**
10. **Risks extended, not weakened.** R5, R6 and R8 updated with the decisions' effects — R6's threshold tightened from 170 to 171 relocatable lines, R8 largely dissolved by Q2(B) but retained with its residual named. **R9 and R10 added**, both new consequences of Q5(B): the sync check as a new failure mode on the deploy path, and the sync check being believed to work without ever being observed to fail. `## Verification Strategy` was not weakened; Stage 2's gate gained three items.

**The Q1 audit, and its result.** Q1(A) is only real if the surviving units are walked against it. § The Q1 Audit does that walk and states **two admissible bases** — an Anthropic citation, or a factual defect where the prompt contradicts this repository's verifiable behavior — with the argument for why the second is in scope rather than smuggled in: `C-gap-analysis` itself reclassified NA5 as plain correctness, and the owner's own Q5 and Q9 answers commission work whose only justification is a factual defect.

**Result: no unit was removed. Two were close and are named rather than smoothed over.** Unit **4.7** (adding attribution to `review-citation-guide.md:11-14`) is the weakest surviving citation — nothing is currently false, so it is a drift-prevention argument; it survives on D31/SG2 plus G11 as precedent, and is now constrained to adding attribution only. Unit **4.10**'s remedy was narrowed from *"add pointers or fold the content in"* to **pointers only**, because folding would change an output style's length and NA3 is closed. Recording these two, rather than either quietly dropping them or rationalizing a weak citation into a strong one, is what the audit was for.

**The NA6 reclassification, and its verdict.** The coordinator required NA6 be re-examined on evidence rather than left out of scope by Q1's default. **Verdict: genuinely cosmetic. NA6 ships nothing.** The decisive evidence is that `allowed-tools` is a turn-scoped permission **grant**, not a restriction — *"It does not restrict which tools are available: every tool remains callable"* (`code.claude.com/docs/en/skills`, § Pre-approve tools for a skill, fetched 2026-07-27) — with `disallowed-tools` being the actual restriction field, which neither skill declares. Two in-repo corroborations, arrived at independently: `default.nix:937-941`'s deny-overrides for `agent-browser`, required precisely because the grant does not restrict, and `pr-review/SKILL.md:6-9`'s own note that it *"grants permissions."* Three findings follow: the omission cannot create a security hole; there is no behavioral consequence because `review-pr-comments/SKILL.md:17-30` already uses `permissions.allow`, which is the instrument the docs prescribe for a multi-turn workflow; and **Document C's D39 framing of NA6 at `C-gap-analysis.md:427` is inverted** — `permissions.allow` is the mechanism and `allowed-tools` is a convenience over it, so NA6 fails its own D39 argument.

**One new question, and it is the exception to item 9.** The NA6 verdict surfaced a question running the opposite way: because `allowed-tools` grants rather than restricts, the sibling that *declares* it is the one widening its surface, and `manage-pr-comments/SKILL.md:5-7`'s `Bash(gh *)` pre-approves every `gh` write while the skill's own Hard Prerequisites name only `Bash(prc *)`. That is **Q10**, stated alone in `## The One Remaining Open Question`, cited to the grant semantics and Anthropic's *"a skill can grant itself broad tool access"* caution, with (C) — a deny-override in the block list, the pattern this repository already uses — recommended. It is a risk-appetite call, not a defect, which is why only the owner can settle it.

**One conflict newly sharpened by the decisions, surfaced rather than left to be discovered.** With the global `CLAUDE.md` capped at 360 with **1 line of slack**, unit 2.8's G14 relocation can no longer land content there — Anthropic's prescribed destination for project knowledge is a CLAUDE.md, and the global one is now full. 2.8's destination is therefore constrained to the **project-root `CLAUDE.md`** (111 lines of headroom, and where project-scoped content belongs) or a new supporting file, never the global file. This follows from Q6(B) and was not visible while 360 was a proposal.

**What this amendment deliberately did not do.** No file under `modules/` was read for editing, edited, or drafted against — the two skills read for the NA6 verdict were read as evidence. No replacement prompt text is drafted anywhere in this document. The migration has not begun. `## Verification Strategy` and `## Risks And Mitigations` were extended and not weakened, and no self-critical passage — the blind-spot list, the honest negatives on D20 and CG3, the residual-risk statements, the *"no behavioral baseline exists"* admission — was softened or removed.
