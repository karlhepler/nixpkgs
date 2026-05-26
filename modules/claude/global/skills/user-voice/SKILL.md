---
name: user-voice
description: Load user voice profile before drafting user-facing content. Use when drafting user-facing content: draft a Slack message, draft an email, draft a PR description, draft a Linear comment, draft a Linear card body or description, draft a ticket comment, draft a stakeholder update, write a status report, write release notes, write a changelog, draft a README, write API docs, write a runbook, draft GTM messaging, draft launch copy, draft an email campaign, write an async-handoff message, write a git commit message, write an async standup or progress update.
---

# User Voice Profile

This skill is a voice profile template. Load it when drafting any user-facing content and conform output to the profile below. The profile grows over time from explicit user corrections — this is a **living document**.

## When to Load

This skill defines three voice modes (three registers): DM/peer 1:1 (short paragraphs, polite-but-direct openers), Broadcast/channel-post (section headers, no greeting opener), and Non-technical peer / volunteer-org favor-ask (warm, humble, low-pressure; comma greeting `Hey [Name],`; `~ Karl` sign-off). Identify the audience type first; the modes are structurally different.

Step 0 (before drafting): identify the audience type — DM (peer 1:1), broadcast (channel/team post), reply (in-thread continuation), cold outreach (work-peer), or favor ask (non-technical peer / volunteer-org collaborator). The structural template depends on audience type. See § Verbatim Examples for the DM vs broadcast distinction. Note: broadcast voice has sub-shapes (milestone-announcement, progress-update) — see § Broadcast / Channel Post Template for shape selection before looking up examples. Note: fresh outreach to a NON-technical peer or volunteer-org contact (e.g., a club president, nonprofit collaborator) uses the favor-ask register (comma greeting, `~ Karl` sign-off, warm/deferential) — NOT the work-peer dash/no-sign-off form used for engineering cold outreach.

Load this skill whenever drafting:
- Slack messages or thread replies
- Emails (internal or external)
- PR descriptions
- Linear comments or ticket comments
- Linear card body / description (distinct from Linear comment)
- Stakeholder updates or status reports
- Release notes or changelogs
- READMEs, API docs, or runbooks
- GTM messaging, launch copy, or email campaigns
- Async-handoff messages
- Git commit messages
- Async standup or progress update

---

### Hard Avoids

Words, phrases, and idioms the user dislikes and never uses. Add entries over time from explicit corrections.

- `leverage` (use "use" or "apply" instead)
- `synergy` / `synergize` (avoid entirely)
- `circle back` (use "follow up" or "revisit" instead)
- `complementary` / `complements` (avoid)
- `carve out` / `carve-out` (internal jargon, not external-stakeholder vocabulary)
- `current thinking:` / `current thinking is` (preamble Karl doesn't use)
- `Fair point.` (used too freely; use softer or no acknowledgement)
- `team` (use `folks` instead — see Preferred Phrasings)
- `guys` (use `folks` instead — see Preferred Phrasings)
- `Hey` as opener on thread continuations (only for fresh messages, not replies)
- `genuinely` (overblown emphasis)
- `that's deliberate` (defensive)
- "Different angle than I said earlier" (use empathetic opener "That's what I thought at first" instead — see Preferred Phrasings)
- "the proximate cause" / "the deeper realization:" (too formal for casual Slack — use "BUT..." + "So really," instead)
- Closing a casual Slack reply with evidence framing (e.g., "the 10/10 green CI runs confirm...") — close with the upshot or a code-level outcome instead

Underlying anti-patterns: hedging closers, context-free closings, passive exit statements. The one-off entries below are captured examples — avoid the pattern broadly, not just the verbatim phrases.

- `in case any of it's useful`
- `leave it as fuel`
- `I'll move on with whatever I'm doing in my project` (vague)

**Broadcast / channel-post only:**

_(The shared list above also applies to broadcast posts — entries below are broadcast-specific additions.)_

- Opening a channel/broadcast post with `Hey -` (reserved for DMs only)
- Pasting full URLs with query parameters into channel posts when a soft invitational pointer works (`Take a look in [tool] if you want some more detail` is the pattern)
- Structured bulleted deliverable lists (e.g., 'Task (done): Description. PR #N merged date.') for status/progress broadcast posts — Karl uses flowing paragraph prose
- LogFrame internal vocabulary in broadcast prose: 'Success Measure 1', 'friction' as a category label, D-codes (D1, D2, D3...), formal 'deliverable' terminology
- PR numbers and merge dates in broadcast prose — Karl omits these from project updates
- Headlined intent framing ('Quick frame first: the Q2 intent was...') — Karl uses parenthetical attached to state-of-project sentence
- Tabular intent-to-deliverable mappings in broadcast posts

Note: "thread continuation" (existing Slack thread you're replying inside) and "channel reply" (replying in a broadcast thread) are distinct from "new channel post" (top-level broadcast). The Hey-opener avoid applies to all three — only work-peer DMs/cold outreach use `Hey -`; non-technical-peer favor-ask outreach uses `Hey [Name],` (comma form).

**DM / 1:1 only:**

_(No DM-specific hard avoids beyond the shared list above — all entries above apply to both modes unless labeled Broadcast-only.)_

_Add more from user corrections as they occur._

---

### Preferred Phrasings

Specific replacements and formulations the user reaches for:

- Prefers `ship` over `deploy` in informal contexts (`ship` as a verb; `deploy` as a noun or modifier, e.g., "deploy discussion", is fine)
- Prefers `folks` over `guys` or `team` in group address
- Prefers "let me know if..." closers over "please advise"

**Openers (matched to message type):**
- Replies / thread continuations: `Thanks!` to open a reply when acknowledging something
- Fresh outreach (work-peer / engineering Slack): `Hey -` (dash after Hey, NOT comma — this is the work-peer register only; see § Greeting / Sign-Off Conventions for the comma form used in the non-technical-peer / volunteer-org register)
- Fresh outreach (non-technical peer / volunteer-org collaborator): `Hey [Name],` (COMMA — warmer register)
- Peer requests: `Would you mind ... when you get a chance please?`
- Empathetic opener (when correcting a peer's read): "That's what I thought at first" / "Same here at first" / "Yeah I thought that too" — align with the listener before pivoting to the correction

**Causal-chain connectors (casual Slack):**
- "BUT..." (all-caps + ellipsis) as a one-line bridge from proximate cause to deeper insight — Slack-native, lighter than 'However,' or 'But more importantly,'
- "So really," to introduce the upshot after stating facts (equivalent to 'the deeper realization:' but lighter)
- Plain cause→consequence chains without hedges (no 'would', 'could', 'appears to') — state facts directly with concrete identifiers inline (numbers, identifiers, no ceremony)

**Action language:**
- `I went ahead and [did X]` — past action, casual ownership
- `I'm working on that now` — active status
- `I updated the [X] to [Y]` — direct action statement

**Tentative-commitment language:**
- `Leaning toward [X]`
- `I think it makes sense to [X]`
- `I don't think I'll [X] quite yet`
- `I want to at least get [X] working first`

**Timeline language:**
- `hope to have it done by [time]` — note: Karl is MORE conservative than AI-default estimates; `early next week` is more typical than `a day or two`
- `Feel free to [X] when you have a moment`

**Closing / next-step language:**
- `Feel free to take a look`
- `Curious what you think on [X]`
- `Let me know what you think`

**Non-technical peer / volunteer-org favor-ask phrasings:**
- Value-first framing: lead with the concrete upside ("a shot at a $10k per month Google Ads grant"), then the honest caveat ("which would have to be approved after the verification process")
- Explicit outs: "completely up to you," "if you still want to," "no pressure at all"
- Jargon gloss: parenthetical plain-language explanation for non-technical readers (e.g., "Goodstack (Google's third party provider for the grants)")
- Heavier hedging than work-peer default: "should be able to," "should hopefully be able to," "or something," "I think"
- Transparent reasoning about failed attempts: "which is what I figured would happen, but figured it was worth trying anyway so you didn't have to get involved"
- Humility close: "I'm sorry I couldn't do more" — acceptable here (opposite of work-peer no-deference rule)

---

### DM / 1:1 phrasings

_(See Openers, Action language, Tentative-commitment language, Timeline language, and Closing / next-step language above — those sections are DM-default.)_

---

### Broadcast / channel-post phrasings

- `Project Update` / `Up Next` as plain-text section headers in broadcast posts (no markdown — text label only)
- `Take a look in [tool] if you want some more detail` — soft invitational pointer to discoverable evidence (reader-controlled depth)
- `(reference)` — parens-reference placeholder for inline link typography; Karl writes `(reference)` in the message and applies the hyperlink to that parenthesized word
- Inline `@`-mentions of teammates throughout broadcast prose
- Ellipsis (`...`) for casual pauses and soft hedges in broadcasts
- 'I might wait...' / "I'm not 100% sure..." / "I'm not sure yet" — open future-uncertainty in updates
- 'a few things on my radar include...' — tentative-future framing
- 'some sort of X' / 'possibly X' / 'possibly X, and possibly Y' — tentative scope listings
- Feedback invitation close with emoji (e.g., "I'm happy to incorporate any thoughts and feedback before or during planning. Just let me know. :smile:")
- Intent framing in parenthetical attached to the state-of-the-project sentence, NOT as a separate header (see also: § Hard Avoids)

_Add more from user corrections as they occur._

---

### Tone Register

Mark the user's default register for each dimension. Update from corrections.

- **Directness:** direct (not deferential)
- **Contractions:** use them (sounds natural, not stiff)
- **Jargon tolerance:** moderate — technical terms OK, buzzwords avoided
- **Formality:** casual-professional (neither formal nor slangy)
- **Framing:** customer/user-impact first, then technical rationale

---

### Audience-Specific Tone Calibration

Adjust framing and detail level based on recipient. These are real named stakeholders — use their names and roles to pick the right register.

- **CTO (Aziz):** Lead with customer impact. He cares about outcomes and business-level signals, not implementation detail. Skip the technical rationale unless directly relevant to risk or scale.
- **Architecture DRI (Ross):** Lead with architectural trade-offs and system-design implications; assume deep platform familiarity; cite component names and integration seams directly.
- **Agentic Engineering DRI (Petr):** Scope-and-sequencing framing. Collaborative tone, peer level. Focus on what's in flight, what's next, and how pieces fit together.
- **Q&O DRI (Daniela):** Lead with quality/ops impact (test coverage, reliability, on-call burden); name the operational surface affected; assume domain ownership. <!-- TODO: confirm Q&O expansion — placeholder framing used here -->
- **Peer backend engineers (Matt, Tommy):** Technical detail with plain-language framing. Casual, direct. Use `would you mind` / `curious if` for requests. No need to justify decisions unless they're non-obvious.
- **Project channel broadcast (broader engineering audience):** Factual, evidence-led. Section-header structure (`Project Update` / `Up Next`). Soft invitational pointer to deeper evidence rather than pasting URLs. No `Hey` opener.
  - **Milestone announcement sub-shape:** Evidence-led with Before/After numbers. Use for single-merge-event posts announcing a completed fix or release.
  - **Progress update sub-shape:** Paragraph prose, inline `@`-mentions, no bullet lists, no LogFrame jargon, no PR numbers, hedged future-looking statements, feedback-invitation + emoji close. Use for mid-project multi-deliverable status summaries.
- **Non-technical peer / volunteer-org collaborator (favor ask)** (e.g., Tim Corbett, Barboursville Bloodhounds president; festival/nonprofit context): Warm, humble, low-pressure. This is the OPPOSITE of the work-peer "no deference" default. Key markers:
  - Give the recipient explicit outs: "completely up to you," "if you still want to," "no pressure at all"
  - Soften or omit confidence — heavier hedging is appropriate here ("should be able to," "should hopefully," "or something," "I think")
  - Lead with the concrete upside before the mechanics (value-first framing), then add an honest caveat
  - Gloss jargon with plain-language parentheticals for non-technical readers (e.g., "Goodstack (Google's third party provider for the grants)")
  - Be transparent about reasoning and failed attempts — "which is what I figured would happen, but figured it was worth trying anyway"
  - A light apology or humility close is acceptable here: "I'm sorry I couldn't do more" fits this register
  - Greeting: `Hey [Name],` with a COMMA (not the dash form — see § Greeting / Sign-Off Conventions)
  - Sign-off: `~ Karl` (tilde + first name)

---

### Greeting / Sign-Off Conventions

**Greeting rules are register-dependent** — the form changes based on audience type:

- **Work-peer / engineering Slack (fresh outreach):** `Hey -` (dash after Hey, no comma) — see Preferred Phrasings § Openers
- **Non-technical peer / volunteer-org collaborator (favor ask):** `Hey [Name],` (COMMA, not dash) — warmer register requires the softer comma form
- **Thread continuations (any register):** skip greeting entirely, jump straight to content
- **Short Slack messages (work context):** omit greeting

**Sign-off rules are also register-dependent:**

- **Work-peer Slack:** no sign-off (casual, peer-level)
- **Non-technical peer / volunteer-org collaborator (favor ask):** `~ Karl` (tilde + first name) — applies to any medium (Slack, email) when the register is favor-ask
- **Emails (work context):** close with first name only — note: the favor-ask `~ Karl` sign-off takes precedence when the medium is email but the register is non-work-peer / volunteer-org (favor ask)

_Update with user corrections._

---

### Domain-Specific Vocabulary

Preferred terms and terms to avoid in this user's domain:

| Preferred | Avoid |
|-----------|-------|
| `card` | `ticket` (in kanban context) |
| postgres (casual Slack) | PostgreSQL (formal/PR/code context only) |
| redis (casual Slack) | Redis (formal context only) |
| k8s (casual Slack) | Kubernetes (formal context only) |

---

### Verbatim Examples (Karl)

Real messages Karl has written. Use these to calibrate voice — not for content, for pattern.

> **Note:** This skill distinguishes three voice modes: **peer DM voice** (Tommy ping example below — short paragraphs, polite-but-direct opener), **broadcast voice** (Project Update example below — section headers, no greeting), and **favor-ask voice** (non-technical peer / volunteer-org collaborator — comma greeting, `~ Karl` sign-off, warm/humble/low-pressure). Before drafting, the coordinator MUST identify the audience type and apply the matching structural template.

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

### Structural Patterns (Karl)

- **Message length calibration.** Slack: brief (1-3 paragraphs max). Email: structured but compact. PR description: two paragraphs max (see global CLAUDE.md § PR Descriptions).
- **Short paragraphs.** Each does one thing. Karl prefers structure over single-block prose.
- **First-person ownership.** `I` not `we` for decisions Karl owns.
- **No prologue.** The first sentence is the request or the substantive content. Do not open with preamble like "I wanted to reach out to..." or "Just following up to say...".
- **Conservative timelines.** (See Timeline language under Preferred Phrasings above for examples.)
- **No closing question when Karl has made the call.** Just state what he's doing. Asking framing is reserved for genuine peer-input requests.
- **Internal project codes stay internal.** D1, D2, D3 etc. are for internal use. When messaging external stakeholders, use the actual deliverable name + Linear ID, not the internal code.

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

See also: § Verbatim Examples — Broadcast / Channel Post (Project Update — engineering channel, progress/status shape)

Note: broadcast posts open with the section header itself — not with `Hey`, `Thanks!`, or any greeting. Greetings are reserved for DMs.

---

### Examples

Worked examples showing "AI default" vs "user voice" for common message types.

These examples are illustrative seeds — they show the contrast pattern (AI default vs user voice) but do NOT reflect any specific user's actual voice. Replace each example with a real correction as the user provides tone feedback during sessions.

**Example 1 — Slack thread reply**

AI default:
> Hi team, just wanted to circle back on the deployment discussion. We should leverage our existing infrastructure to synergize our efforts here. Please advise on next steps.

User voice:
> Following up on the deploy discussion — I think we can reuse the existing setup here. What's the blocker?

**Example 2 — PR description (opening paragraph)**

AI default:
> This pull request introduces improvements to the authentication flow by implementing various enhancements that will leverage our existing token infrastructure.

User voice:
> Speeds up login by caching the token refresh response. Reduces p95 auth latency from ~600ms to ~80ms.

**Example 3 — Ticket comment (status update)**

AI default:
> I wanted to provide an update regarding the current status of this ticket. We have made significant progress and are working diligently to complete the remaining items.

User voice:
> Backend is done. Frontend wiring in progress — should be wrapped up today.

---

## Update Process

When the user provides an explicit tone correction (e.g., "don't say X, say Y"), the coordinator handling the session MUST:

1. **Update this skill directly** if the edit is a simple addition to an existing section (hard avoids, preferred phrasings, examples), OR
2. **File a `claude-improvement` note** (`mcp__notes__upsert_note` with tag `claude-improvement`) if the update requires structural changes or is best batched with other pending profile updates.

This is a **living document** — the profile grows from real corrections, not from initial guesses. Stale entries should be removed; new ones added promptly.

---

## Voice-Conformance Check

Before surfacing any user-facing draft, run a quick self-check:

0. **Audience-type check** — was the right structural template applied for the audience type (DM vs broadcast vs favor-ask)? Identify which of the three registers applies: work-peer DM/cold outreach, broadcast, or non-technical-peer / volunteer-org favor-ask. If broadcast, verify section-header shape and no-greeting opener. If favor-ask, verify comma greeting and `~ Karl` sign-off.
1. **Hard-avoid scan** — does the draft contain any word/phrase from the Hard Avoids section? Rewrite those phrases. (Note: some Hard Avoids are mode-specific — e.g., `Hey -` is valid in work-peer DMs but forbidden in broadcast posts and favor-ask outreach. Apply avoids relative to the audience type identified in step 0.)
2. **Length check** — is the draft proportional to the message type? (Slack: brief; email: structured; PR description: two paragraphs max.)
3. **Sign-off check** — does the closing match the Greeting / Sign-Off conventions for this register? Route by register (see § Greeting / Sign-Off Conventions): work-peer Slack → no sign-off; favor-ask (any medium) → `~ Karl`; work-context email → first name only.
4. **Framing check** — is customer/user impact mentioned before technical rationale (where applicable)?
5. **Domain vocabulary scan** — does the draft use any term from the Avoid column of the Domain-Specific Vocabulary table? Substitute with the Preferred column term.
6. **Broadcast-mode check (if channel/broadcast post):** First, identify which broadcast shape applies (milestone-announcement vs progress-update). Then verify the shape-specific constraints for that shape.
   - 6a. **Milestone-announcement shape verification:** Section-header opener present (no greeting)? State-change sentence present? Evidence block (Before/After inline numbers + dates)? Soft invitational pointer to evidence tool (not pasted URL)? `Up Next` block as its own section (not inline)? If any element missed, rewrite to match the milestone-announcement template.
   - 6b. **Progress-update shape verification:** Section-header opener present (no greeting)? Paragraph prose (not bullets)? Inline `@`-mentions for collaborators? Parenthetical intent framing attached to state-of-project sentence (not headlined as separate section)? No LogFrame jargon, no PR numbers, no merge dates? Hedged future-looking statements? Feedback-invitation + emoji close? If any element missed, rewrite to match the progress-update template.

Fix any failures before returning the draft.
