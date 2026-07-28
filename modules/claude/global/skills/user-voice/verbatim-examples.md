# User Voice Profile — Verbatim Examples and Structural Patterns

Real messages Karl has written — calibration examples for the four voice modes (peer DM, broadcast, cross-functional, and Slack technical explanation), their patterns and anti-pattern contrasts, and the structural patterns (message length, ownership, closers, broadcast template shapes) they exhibit. Read this file from `SKILL.md` (source: `modules/claude/global/skills/user-voice/verbatim-examples.md`) when drafting user-facing content and you want to calibrate against real examples rather than reasoning from the abstract rules alone — not needed for the hard-avoid / preferred-phrasing rules themselves, which stay resident in `SKILL.md`.

### Verbatim Examples (Karl)

Real messages Karl has written. Use these to calibrate voice — not for content, for pattern.

> **Note:** This skill distinguishes four voice modes: **peer DM voice** (Tommy ping example below — short paragraphs, polite-but-direct opener), **broadcast voice** (Project Update example below — section headers, no greeting), **favor-ask voice** (non-technical peer / volunteer-org — known collaborator — comma greeting, `~ Karl` sign-off, warm/humble/low-pressure), and **cold-outreach voice** (unknown organization/media outlet — confident, warm, grounded, not servile; see § Audience-Specific Tone Calibration in `SKILL.md`). Before drafting, the coordinator MUST identify the audience type and apply the matching structural template.

**Peer DM (Tommy ping — peer review request):**

> Would you mind taking another look when you get a chance please? I made some changes since your review.
>
> It turns out that the polling helper was looking in the wrong data store (maze-api/Neo4j). The test setup writes via graph-gateway/results-api/PostgreSQL.
>
> So I updated the poll to query mazeSessionByMazeAndTesterId through the graph-gateway instead.

Patterns visible in this example:
- Polite-but-direct opener: `Would you mind ... when you get a chance please?`
- Short paragraph structure — each paragraph does one thing
- `It turns out that...` for unexpected discoveries or corrections
- Plain-language technical framing — explains the problem in plain terms before naming the fix
- Inline parenthetical specifics: `(maze-api/Neo4j)`, `(graph-gateway/results-api/PostgreSQL)`
- Slash-separated path notation for related components: `graph-gateway/results-api/PostgreSQL`
- `So I updated...` — direct action statement following the explanation
- `instead` at the end — implicit contrast without over-explaining what was wrong
- No filler, no emojis, no excessive hedging

---

**Broadcast / Channel Post (Project Update — engineering channel):**

> Project Update
>
> I just merged a fix for customTemplates spec.
>
> It was quarantined via config.skipTests. I migrated it to the SetupOrgPlanUserSession builder, replaced module-level mutable state with proper test isolation, and proved 10 consecutive green CI runs before un-quarantining.
>
> Before (2 weeks pre-rescue, 2026-04-29 → 2026-05-13): 2.99% failure rate, 0.54% flake rate across 1,472 executions.
> After (fix + 10x checks, 2026-05-14 → 2026-05-15): 0% failure rate, 0% flake rate across 173 executions.
>
> Take a look in currents if you want some more detail.
>
> Up Next
> I am working on resultsFiltering now with the same methodology (reference).

Patterns visible in this example:
- Section headers (text labels, not markdown): `Project Update` opens; `Up Next` separates forward-look
- No `Hey` opener — section header is the opener for channel posts
- Forward-look `Up Next` as its own structural block (not folded into closing sentence)
- Soft invitational pointer to evidence tool: `Take a look in [tool] if you want some more detail` (avoids pasting full URLs)
- Parens-reference typography for inline links: `(reference)` as a placeholder Karl replaces with a hyperlinked word
- Before/After evidence inline: `Before (window, dates): X% rate, Y% flake rate across N executions.` Dense, factual, NOT a separate `Evidence:` section header

---

**Broadcast / Channel Post (Project Update — engineering channel, progress/status shape):**

> Project Update
>
> I'm getting close to the end of the Q2 project (reducing friction so that writing acceptance tests are a natural part of shipping). @ross is actually tackling a portion of it himself by helping to migrate away from lambdas.
>
> For my part, I migrated some single-dependency lambdas to services and validated using mirrordx to run tests. So there are now a few acceptance tests that can be run locally. I also fixed a couple of tests that were previously skipped and added some tagging to incident.io (from Aziz's runbook) to help us identify critical flows affected during incidents.
>
> One of the last things I'm working on right now is extending /deliver to support acceptance test planning. I parked that after getting some feedback from @Petr... I might wait until the next iteration of this project before I move that through. I'm not sure yet.
>
> I'm starting to look into what's next... and although I could technically consider it a Q3 project, I'm going to start looking into it today or tomorrow. I'm not 100% sure what the shape of the project will be, but a few things on my radar include some new acceptance tests for submit order coverage, seeing if there is anything I can contribute to the critical paths that @Daniela Matos de Carvalho is working on, some sort of codegen/scaffolding skill for acceptance tests, possibly isolated acceptance test environments, and possibly a test account pool.
>
> I'm happy to incorporate any thoughts and feedback before or during planning. Just let me know. :smile:

Patterns visible in this example:
- Section header opener (`Project Update`), no greeting
- Intent framing in parenthetical immediately after the state-of-the-project sentence — NOT headlined
- Collaborator credit by inline `@`-mention (@ross, @Petr, @Daniela Matos de Carvalho)
- Flowing paragraph prose summarizing multi-deliverable progress — NOT bulleted
- Plain-English verbs: 'migrated', 'validated', 'fixed', 'added', 'parked'
- NO LogFrame jargon (no 'Success Measure 1', no 'friction' as a category label, no D-codes)
- NO PR numbers or merge dates in prose
- Sources tools/conventions naturally inline ('validated using mirrordx', 'added some tagging to incident.io (from Aziz's runbook)')
- Ellipsis (`...`) for casual pauses and soft hedges
- Open future-uncertainty: 'I might wait until the next iteration', "I'm not 100% sure", 'a few things on my radar include...'
- Tentative scope listings with 'possibly X, and possibly Y' / 'some sort of X'
- Feedback invitation close: "I'm happy to incorporate any thoughts and feedback before or during planning."
- Emoji close (`:smile:`) — friendly, not formal

---

**Slack technical explanation (Tommy reply re polling fix):**

> That's what I thought at first. The polling helper was calling getTesterBlockResults through an unauthenticated graph-gateway client. That endpoint requires auth, so every poll came back 401 and it timed out.
>
> BUT... the results-api writes synchronously to postgres through graph-gateway. By the time completeMazeSession returns, all the block answers are already persisted. So really, there was nothing to wait for.
>
> The polling wasn't necessary at all.

Patterns visible in this example:
- Empathetic opener `That's what I thought at first` aligning with the listener before pivoting — meets them where they were, not where you are
- `BUT...` (all-caps + ellipsis) as a casual one-line bridge from proximate cause to deeper insight — Slack-native, lighter than 'However,' or 'But more importantly,'
- Plain causal chains with no hedges (no 'would', 'could', 'appears to') — state facts directly: "the row was there — postgres had committed it"
- `So really,` introducing the upshot after stating facts — equivalent to 'the deeper realization:' but lighter
- Slack-native formatting — no backticks for code identifiers, no bullets, prose paragraphs separated by blank lines
- Lowercase technical terms (`postgres` not `PostgreSQL`) in casual Slack
- Closing with short blunt restatement of the code-level outcome — NOT evidence framing

Anti-patterns (vs Karl's voice) — what NOT to do:

| AI tendency | Karl's voice |
|-------------|-------------|
| "Different angle than I said earlier" | "That's what I thought at first" |
| "the proximate cause / the deeper realization:" | "really, there was nothing to wait for" |
| Bullet lists for cause/effect | Paragraph prose with BUT... pivot |
| `Backticked code identifiers in Slack` | Bare-word identifiers |
| "PostgreSQL" in casual Slack | "postgres" |
| Closing with evidence framing | Closing with the upshot |

---

**Technical explanation to a cross-functional peer (Q&O DRI — Daniela):**

> resultsFiltering was a race condition. The helper, which was meant to wait for results to land in the results-api read model, was a noop. It returned immediately without waiting. So the results page would open before the data propagated and... well... yeah. So basically the fix was to make it wait.
>
> customTemplates used a deprecated helper that kept its state at module level and was used in the beforeEach part of the test. Sometimes setup would fail and the test would run anyway against old state. It also clicked into the custom-templates list without waiting for templates... so another instance of not waiting.
>
> Our tests are very impatient. I told them to chill out and sniff the flowers.

Patterns visible in this example:
- **No code-level identifiers** — 'a deprecated helper that kept its state at module level', NOT the symbol name. Identifier density is audience-dependent; Daniela is a Q&O DRI, not a peer backend engineer.
- **State the fix in the simplest terms**: 'the fix was to make it wait' — one plain clause, not a technical diff description
- **Casual trailing-off device**: `and... well... yeah` — trusts the reader to complete the obvious consequence without spelling it out
- **Shared-root-cause closer**: names the unifying theme ('very impatient') with a warm, playful, personifying one-liner ('I told them to chill out and sniff the flowers') — NOT evidence framing
- Plain causal chain, paragraph-per-issue structure, no bullets

Anti-pattern (coordinator draft — what NOT to do):

> Both resultsFiltering and customTemplates were quarantined due to flaky behavior. The resultsFiltering issue was caused by a polling stub that resolved immediately rather than awaiting the results-api read model, creating a race condition. The customTemplates issue was caused by module-level state in a deprecated helper used in beforeEach, which could leave stale state when setup failed. Both held 10 consecutive green CI runs before I un-quarantined them.

What makes this the wrong voice:
- Opens the cause explanation with formal label framing ('quarantined due to flaky behavior') rather than plain narrative
- Uses symbol-density appropriate for a peer engineer, not a cross-functional stakeholder
- Closes on evidence ('10 consecutive green CI runs') — the hard-avoid pattern; closes on proof rather than the human upshot
- Clinical, not warm; no personifying closer

---

### Structural Patterns (Karl)

- **Message length calibration.** Slack: brief (1-3 paragraphs max). Email: structured but compact. PR description: two paragraphs max (see global CLAUDE.md § PR Descriptions).
- **Short paragraphs.** Each does one thing. Karl prefers structure over single-block prose.
- **First-person ownership.** `I` not `we` for decisions Karl owns. See also § Spoken / Scripted First-Person Content, Rule 1 (in `SKILL.md`) for work-attribution specifics (including Claude-authorship hedging). **Extended to written peer content and possessives:** for any project, deliverable, or set of artifacts that Karl personally owns (solo work) — in Slack, email, PR descriptions, or any written peer content — use first-person singular possessive: `my X` / `my project's X`. Never `our X`. `Our` implies a team; if the work is Karl's alone, it is not a team possession. Scan trigger: find "our" + a project-artifact noun (measures, dashboards, notebooks, metrics, docs); if the project is Karl's solo, switch to "my". Exception: org/company Maze `our` (`our customers`, `our critical flows`) stays `our`; inclusive speaker+audience `we` (`let's take a look`) stays `we`. The correction is narrow — only solo-owned project artifacts switch to singular possessive.
- **No prologue.** The first sentence is the request or the substantive content. Do not open with preamble like "I wanted to reach out to..." or "Just following up to say...".
- **Conservative timelines.** (See Timeline language under Preferred Phrasings above for examples.)
- **No closing question when Karl has made the call.** Just state what he's doing. Asking framing is reserved for genuine peer-input requests.
- **Internal project codes stay internal.** D1, D2, D3 etc. are for internal use. When messaging external stakeholders, use the actual deliverable name + Linear ID, not the internal code.
- **Audience-knowledge check: cut what the recipient already knows.** Before including an explanatory sentence, ask whether the specific named recipient already has that context. If they already know it, cut the sentence entirely — sending information back to someone who gave it to you reads as padding. Karl's example: 'Atte knows that nothing creates tickets from quarantined tests yet. So I'm just telling him something he already knows.' The test: would this sentence teach this person something, or just re-state what they told you?
- **Audience-knowledge check (inverse): don't reference brand-new or in-progress work as if the recipient knows it.** Same discipline as the bullet above — calibrate to the recipient's actual knowledge state — applied in the opposite direction. When outreaching about something Karl just started or hasn't shipped yet, explain it from the recipient's frame with zero assumed knowledge of the new thing: lead with what the recipient already owns or recognizes (their service, their domain, the concrete artifact they know), and gloss any reference to the new work in plain terms — never by an internal name or PR number the recipient has never seen. Karl's correction, verbatim: '"The new SDL drift gate" - nobody knows what the hell this is. NOBODY. You are treating it as if someone knows what it is.' BAD: 'The new SDL drift gate (#33932) regenerates each subgraph...' GOOD: 'some tooling that regenerates these SDLs straight from the resolver code...'
- **Shared-root-cause closer: playful and personifying, NOT evidence framing.** When two or more details share a root cause, name the unifying theme and close with a warm, playful, personifying one-liner. This is an extension of the existing hard-avoid against closing a casual Slack reply on evidence framing (e.g., the anti-pattern: 'Both held 10 consecutive green CI runs before I un-quarantined them' — factual, closing on proof, not on the upshot). The correct closer names the character of the problem and humanizes it. Karl's model: 'Our tests are very impatient. I told them to chill out and sniff the flowers.' — personifying the tests as a character, landing on warmth rather than data.

#### Broadcast / Channel Post Template

Broadcast posts come in several shapes. Pick the shape that matches the post's purpose. All shapes share the section-header conventions and no-greeting opener.

**Milestone announcement shape** (use when announcing a completed merge, fix, or release):

1. Opening header (no markdown — text label only, e.g., `Project Update`)
2. State-change statement (one short paragraph: `I just merged X.`)
3. Mechanism summary (what was done, in one or two short paragraphs)
4. Evidence (Before/After inline — concrete numbers + N + dates). If no concrete before/after evidence is available, OMIT step 4 entirely (don't write an empty evidence block, don't apologize for missing numbers — just skip).
5. Soft pointer to deeper evidence tool (invitational, reader-controlled depth)
6. `Up Next` section (forward-look + reference link as separate block)

**Weekly update shape** (use for recurring team status posts):

1. Opening header (e.g., `Weekly Update` / `Week of YYYY-MM-DD`)
2. What landed this week (bullet list of completed items + links)
3. What's in flight (bullet list of active items + owners if relevant)
4. `Up Next` (forward-look — what's planned next week)
5. (Optional) Blockers or asks — only if present

**Blocker call-out shape** (use when asking the team for help or a decision):

1. Opening header (`Blocker` / `Help needed`)
2. State the blocker in one factual sentence
3. What was tried (one short paragraph)
4. What's needed (a specific ask — `@person can you look at X` or `we need a decision on Y`)
5. (Optional) Pointer to evidence/repro

**Decision broadcast shape** (use when announcing an architectural or process decision):

1. Opening header (`Decision` / `Architecture call`)
2. The decision in one sentence
3. Why (one paragraph: trade-offs considered, what tipped it)
4. Implications (what changes, who's affected)
5. `Up Next` (next steps, owners)

**Progress / status update shape** (use for mid-project multi-deliverable status posts where the goal is to summarize progress, name what's in flight, and signal forward intent — not announce a single merge):

1. Opening header (text label, e.g., `Project Update`)
2. State-of-the-project sentence with intent framing in parenthetical (NOT a separate header) — e.g., "I'm getting close to the end of the Q2 project (reducing friction so that writing acceptance tests are a natural part of shipping)."
3. Collaborator credit inline within the opening paragraph (NOT as a separate paragraph) by `@`-mention — e.g., "@ross is actually tackling a portion of it himself by helping to migrate away from lambdas."
4. What I did (paragraph prose, plain-English verbs, NO bullets, NO PR numbers, NO merge dates, NO LogFrame jargon)
5. What I'm working on right now (one short paragraph, casual, may reference collaborators by `@`-mention)
6. What's next (open hedging — "I might wait", "I'm not 100% sure", "a few things on my radar include...", "possibly X, and possibly Y")
7. Feedback invitation + emoji close — e.g., "I'm happy to incorporate any thoughts and feedback before or during planning. Just let me know. :smile:"

See also: § Verbatim Examples (above) — Broadcast / Channel Post (Project Update — engineering channel, progress/status shape)

Note: broadcast posts open with the section header itself — not with `Hey`, `Thanks!`, or any greeting. Greetings are reserved for DMs.
