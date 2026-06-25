---
name: user-voice
description: Load user voice profile before drafting user-facing content. Use when drafting user-facing content: draft a Slack message, draft an email, draft a PR description, draft a Linear comment, draft a Linear card body or description, draft a ticket comment, draft a stakeholder update, write a status report, write release notes, write a changelog, draft a README, write API docs, write a runbook, draft GTM messaging, draft launch copy, draft an email campaign, write an async-handoff message, write a git commit message, write an async standup or progress update.
---

# User Voice Profile

This skill is a voice profile template. Load it when drafting any user-facing content and conform output to the profile below. The profile grows over time from explicit user corrections — this is a **living document**.

## When to Load

This skill defines four voice modes (four registers): DM/peer 1:1 (short paragraphs, polite-but-direct openers), Broadcast/channel-post (section headers, no greeting opener), Non-technical peer / volunteer-org favor-ask — known collaborator (warm, humble, low-pressure; comma greeting `Hey [Name],`; `~ Karl` sign-off), and Cold outreach to unknown organization / media outlet (warm, confident, grounded; NOT servile). Identify the audience type first; the modes are structurally different.

Step 0 (before drafting): identify the audience type — DM (peer 1:1), broadcast (channel/team post), reply (in-thread continuation), investigative-update (work-peer thread, real-time narration of an in-progress investigation), work-peer cold DM (fresh outreach to a known-org colleague you haven't messaged), unknown-organization cold outreach (publication, radio station, festival, or any recipient whose organization you don't have an established relationship with), or favor ask (non-technical peer / volunteer-org — known collaborator). The structural template depends on audience type. Work-peer cold DMs use the peer/DM template (`Hey -` dash opener, no sign-off). Unknown-organization cold outreach routes to the cold-outreach register (confident, warm, grounded, not servile) — a structurally distinct template; see § Audience-Specific Tone Calibration. See § Verbatim Examples for the DM vs broadcast distinction. Note: broadcast voice has sub-shapes (milestone-announcement, progress-update) — see § Broadcast / Channel Post Template for shape selection before looking up examples. Note: fresh outreach to a NON-technical peer or volunteer-org contact (e.g., a club president, nonprofit collaborator) uses the favor-ask register (comma greeting, `~ Karl` sign-off, warm/deferential) ONLY when that contact is a known collaborator. Cold outreach to an unknown-organization cold recipient (e.g., a bluegrass publication, radio station, festival) uses the cold-outreach register — see § Audience-Specific Tone Calibration.

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
- `good call` (reflexive acknowledgement opener Karl never uses — like `Fair point.`, a reflexive opener Karl avoids; use softer or no acknowledgement instead)
- `the piece that's missing` (Karl: 'I never say that either.' State what is absent plainly instead)
- `team` (use `folks` instead — see Preferred Phrasings)
- `guys` (use `folks` instead — see Preferred Phrasings)
- `Hey` as opener on thread continuations (only for fresh messages, not replies)
- `genuine` / `genuinely` (overblown emphasis — AI register tell)
- `that's deliberate` (defensive)
- "Different angle than I said earlier" (use empathetic opener "That's what I thought at first" instead — see Preferred Phrasings)
- "the proximate cause" / "the deeper realization:" (too formal for casual Slack — use "BUT..." + "So really," instead)
- Closing a casual Slack reply with evidence framing (e.g., "the 10/10 green CI runs confirm...") — close with the upshot or a code-level outcome instead
- `exactly` as an emphasis intensifier (e.g., 'exactly the kind of thing we need', 'exactly what we need', 'exactly the input I need') — reads forced; drop it and state the point plainly ('the kind of thing we need').
- `finish out the rest` / `finish out` / `wrap up the rest` / `knock out the rest` (when the remaining work is substantial — frames significant, often multi-quarter work as cleanup; use 'start working through the rest [together]' instead — see Preferred Phrasings → Closing / next-step language).
- `levers` / `native levers` (Karl: 'I would never say levers. I don't use the word levers.' Use `options`, name the actual things, or 'the [X] stuff' instead.)
- `front door` as a metaphor for an entry point or missing piece (Karl: 'I would never say the front door... it sounds like gibberish. I have never used that and I never will.' State the actual thing plainly — e.g., 'nothing creates the tickets yet' — never the 'front door' metaphor.)
- `lands` / `nothing lands unassigned` — avoid `lands` as a verb for where something ends up. Karl: 'I never say "nothing lands unassigned", I never say "lands".' Use 'gets assigned' / 'ends up' / plain phrasing instead.
- `feeds` / `feeds them in` as a routing verb (the sense of routing items into a system, pipeline, or queue). Karl: 'You're using the word feeds. I never use the word feeds... I never say "feeds them in".' Use 'go into', 'show up in', 'create X in Y', or just name the destination instead. Companion to `lands` and `front door` — continues this session's pattern of stripping pipeline/flow metaphor-verbs from Karl's voice.
- Redundant restate-the-point closer: a summarizing one-liner at the end of a casual reply that merely re-states the body's point (Karl's rejected example: 'So quarantined won't mean forgotten' — 'that's stupid and redundant'). End casual replies on substance, not a recap one-liner. IMPORTANT distinction: this ban is NOT the shared-root-cause playful closer (which names the unifying theme — see § Structural Patterns → Shared-root-cause closer); only the closer that is redundant because it merely repeats what the body already said is banned.

Underlying anti-patterns: hedging closers, context-free closings, passive exit statements. The one-off entries below are captured examples — avoid the pattern broadly, not just the verbatim phrases.

- `in case any of it's useful`
- `leave it as fuel`
- `I'll move on with whatever I'm doing in my project` (vague)

- Em dash ("—") and en dash ("–"): replace with a period, comma, colon, or parentheses. Includes spaced em dashes ( — ) and double hyphens ( -- ) used the same way. One of the most reliable AI-authorship tells; hard avoid, not a "use sparingly" preference.
- Negative parallelisms: "Not only/not just X, but Y" and "It's not just X, it's Y" constructions. Reflexive AI parallelism; state the point plainly instead.
- Reflexive rule-of-three triads: reflexive lists of exactly three items to appear comprehensive (e.g., "innovation, inspiration, and industry insights"). List only what is actually distinct.
- AI-vocabulary words (in addition to the existing leverage / genuine / synergy bans above): `delve`, `robust`, `seamless`, `vibrant`, `pivotal`, `showcase`, `tapestry` (abstract noun), `testament`, `underscore` (verb), `foster`/`fostering`, `crucial`. These cluster as post-2023 statistical tells.
- Persuasive-authority tropes: "at its core", "the real question is", "what really matters", "fundamentally", "the heart of the matter". Ceremonial depth-claiming that restates ordinary points with importance inflation.
- Stacked staccato drama: a run of short declarative fragments manufacturing importance (e.g., "Then X arrived. No Y. No Z. Everything changed."). Karl's organic short sentences are fine; the tell is the engineered run of fragments stacked for quotability.

**Cold outreach to unknown organization / media outlet only:**

_(The shared list above also applies to cold outreach — entries below are cold-outreach-specific additions.)_

- Stacked servile disclaimers — these read as AI filler and signal that the writer has no standing to make a request (which is false — a request is not an order regardless of who you're writing to): `'no pressure at all'`, `'no obligation at all'`, `'completely up to you'`, `'no worries either way'`, `'I'd be grateful'`
- Grovel-thanks pattern: `'thanks so much for what you do for the [X] community'` — over-the-top flattery that reads as insincere. Do not grovel at the open of a cold outreach.
- AI-tell meta-hedge: `'I don't want to assume, so I figured I'd ask directly rather than guessing'` — just ask the question. The meta-hedge signals self-consciousness and reads as AI.
- Repeating the recipient's name after the greeting (e.g., "Thanks for your time, Darin" in the close — name appears in greeting only).
- Timid undersell qualifiers (e.g., `'a pretty fun mix'`) — state distinctive value with grounded confidence instead.
- `unusual` (negative connotation — prefer "unique" / "unlike anything else")
- Declarative news-desk openers for press/coverage outreach: `'Story tip'`, `'FYI'`, `'Just letting you know'` — for press/media we are ASKING, not TELLING. We are not in charge of the outlet. A news-desk framing asserts authority we don't have; lead instead with a humble ask ("I wanted to ask whether it might be something [Outlet] would consider covering").
- Meta-framing devices in Karl's voice: `'the angle is'` / `'the hook is'` / similar marketing-coverage editorializing (e.g., "The setting is the angle"). Just describe the thing plainly and confidently — no meta-editorial layer.
- `'might be worth a mention'` — timid hedge; tighten to "could be" framing (see § Preferred Phrasings → Cold outreach).

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
- **State the fix in the simplest terms** — e.g. 'the fix was to make it wait', NOT 'a real poll instead of the stub plus proper test isolation'. One plain clause is enough; the reader doesn't need the full technical diff.
- **Casual trailing-off (infer-the-rest)** — the device `and... well... yeah` (ellipsis + 'well... yeah') trusts the reader to complete the obvious consequence themselves. Use after a causal chain where the outcome is self-evident; it reads as natural spoken cadence rather than spelled-out analysis.

**Action language:**
- `I went ahead and [did X]` — past action, casual ownership
- `I'm working on that now` — active status
- `I updated the [X] to [Y]` — direct action statement

**Epistemic hedge (when confirming something already present):**
- `it looks like we already have [X]` — preferred over flat assertions like 'we actually already have this' or 'we already have this'. Understated/tentative framing even when fairly sure; lowers the assertion register without being evasive. Apply only in this confirmation context (when you have already verified the thing exists) — do not hedge general assertions.

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
- `start working through the rest [together]` — honest framing of substantial remaining work as work to begin, NOT `finish out the rest` / `wrap up the rest` (which undersell significant or multi-quarter work as cleanup). When handing off or proposing collaboration on a large remaining scope, name it as work to start, not finish.

**Non-technical peer / volunteer-org favor-ask phrasings (known collaborator):**

_(These explicit-outs phrasings are favor-ask only — Hard Avoids for cold outreach (see § Hard Avoids → Cold outreach).)_

- Value-first framing: lead with the concrete upside ("a shot at a $10k per month Google Ads grant"), then the honest caveat ("which would have to be approved after the verification process")
- Explicit outs: "completely up to you," "if you still want to," "no pressure at all"
- Jargon gloss: parenthetical plain-language explanation for non-technical readers (e.g., "Goodstack (Google's third party provider for the grants)")
- Heavier hedging than work-peer default: "should be able to," "should hopefully be able to," "or something," "I think"
- Transparent reasoning about failed attempts: "which is what I figured would happen, but figured it was worth trying anyway so you didn't have to get involved"
- Humility close: "I'm sorry I couldn't do more" — acceptable here (opposite of work-peer no-deference rule)

**Cold outreach to unknown organization / media outlet phrasings:**
- Make the request plainly and stop — no stacked disclaimers, no apologies for asking.
- State distinctive value with grounded confidence rather than timid qualifiers ("a pretty fun mix" → name what's actually distinctive and let it speak for itself).
- Prefer `unique` / `unlike anything else` over `unusual` (negative connotation).
- Use `'I'm reaching out'` (full first-person subject) over bare `'Reaching out'` — Karl always leads with the first-person subject.
- Prefer `'could be a fit'` / `'could be [verb]ed'` over `'might be worth a mention'` / `'or shoutout'` / `'or be worth sharing with your community'` — confident framing over timid hedges.

**Work-peer thread / investigative-update phrasings:**
- `What I can say is that...` — frames a partial/honest finding when the overall result is inconclusive. Use when the investigation produced a narrow data point but not a conclusion.
- Plainly-inconclusive admissions: `didn't really help`, `Everything worked either way`, `both versions produced 200s for me locally` — state null/negative results flatly, no spin or qualification softening.
- Casual failure/risk phrasing: `screws something up`, `try it out for real`, `the only way to really test it out` — preferred over corporate-sanitized variants like 'validate in production', 'introduce regression risk', 'production validation'.
- Standalone `hmmm` as a real-time thinking-out-loud message — valid as a complete short message in a work-peer thread when narrating an in-progress investigation.
- Tentative pragmatic next-step phrasing: `So I think the only way to really test it out might be to try it out for real.` — pivots from inconclusive test result to a pragmatic next step without over-claiming confidence.

---

### DM / 1:1 phrasings

_(See Openers, Action language, Tentative-commitment language, Timeline language, and Closing / next-step language above — those sections are DM-default.)_

---

### Broadcast / channel-post phrasings

- `Project Update` / `Up Next` as plain-text section headers in broadcast posts (no markdown — text label only)
- `Take a look in [tool] if you want some more detail` — soft invitational pointer to discoverable evidence (reader-controlled depth)
- `(reference)` — parens-reference placeholder for inline link typography; Karl writes `(reference)` in the message and applies the hyperlink to that parenthesized word
- Inline `@`-mentions of teammates throughout broadcast prose
- Ellipsis (`...`) for casual pauses and soft hedges in broadcasts — also valid in DM/thread context as a real-time thinking pause within incremental thread updates (not broadcast-only)
- 'I might wait...' / "I'm not 100% sure..." / "I'm not sure yet" — open future-uncertainty in updates
- 'a few things on my radar include...' — tentative-future framing
- 'some sort of X' / 'possibly X' / 'possibly X, and possibly Y' — tentative scope listings
- Feedback invitation close with emoji (e.g., "I'm happy to incorporate any thoughts and feedback before or during planning. Just let me know. :smile:")
- Intent framing in parenthetical attached to the state-of-the-project sentence, NOT as a separate header (see also: § Hard Avoids)

_Add more from user corrections as they occur._

---

### Thread / Investigative-Update phrasings

Context: work-peer Slack thread, real-time narration of an in-progress investigation (e.g., incident post-mortem, version-upgrade investigation, local repro attempt). Cadence: incremental short messages sent minutes to hours apart — NOT one composed block. Tone: plainly honest about inconclusive/negative results; no spinning. Structural pattern: when an investigation is inconclusive, state that flatly, then pivot to a pragmatic next step. Avoid over-claiming confidence.

- Standalone `hmmm` is a valid complete message — real-time thinking-out-loud message for an in-progress investigation thread.
- Plainly-inconclusive admissions stated flat: `didn't really help`, `Everything worked either way`, `both versions produced 200s for me locally` — null/negative results get no softening or spin.
- `What I can say is that...` — frames a partial/honest finding when the overall result is inconclusive; names the narrow data point without claiming a conclusion.
- Tentative pragmatic pivot: `So I think the only way to really test it out might be to try it out for real.` — after inconclusive local testing, pivots to next pragmatic step without over-claiming confidence.
- Casual failure/risk phrasing (`screws something up`, `try it out for real`) over corporate variants (`validate in production`, `introduce regression risk`).

**Casual agreement / decision replies (understated iterative-step pattern):**

When replying to a decision or agreeing with a course of action in a casual Slack context, use an understated, iterative-step tone — not formal analysis. Key markers Karl actually uses:

- `looked it up` (NOT 'did my research', NOT 'reviewed the documentation')
- `probably just [X]` — low-stakes, iterative framing rather than confident declaration
- `see how it goes` / `see what happens` — signals iterative intent, not definitive commitment
- Treat the decision as a low-key iterative step ('it's like an iterative step') rather than a significant resolved conclusion

**Omit the success metric / goal in casual replies.** Do not explicitly reference the success metric or target in casual Slack agreement messages — leave it implicit. Karl: 'if it lets me hit the metrics target. And I don't mention that either.' The success metric is background context, not something to name in the reply itself.

**Length: keep it brief (1-3 lines).** Casual agreement replies should be short. Do NOT expand into formal analysis, evidence summaries, or structured breakdowns — that reads as 'too long and overblown' for this register.

_Add more from user corrections as they occur._

---

### Spoken / Scripted First-Person Content

Content type: video scripts, talk outlines, demo narration, spoken async updates. Load this section any time a draft of spoken/scripted content (video scripts, talk outlines, demo narration, spoken async updates) uses 'we' for work Karl did personally, lists deliverables where a narrative introduction is expected, or states a goal before its objective.

**Rule 1 — Work-attribution hierarchy.** When attributing work Karl personally did, apply this three-tier hierarchy:

- **PREFERRED — attribution-free outcome statements.** State the outcome with no narrator at all. Examples: 'So now there's a runner.' / 'There's a rule for this now.' / 'These things are now fixed.' Karl's refinement: "Even better than the word I in place of we: reword the sentence so it doesn't attribute to anybody. It just says these things are now fixed. That kind of flavor is even better."

- **ACCEPTABLE — first-person singular.** Use 'I built', 'I went after', 'what I learned' when an attribution-free version would be awkward or ambiguous. This is a valid fallback, not the first choice. Awkward case: 'I've been chasing this flake for two months' — stripping the narrator loses the effort signal. Attribution-free works fine when no effort/time signal is at stake: 'We've added a timeout mechanism.' → 'There's now a timeout.'

- **NEVER — 'we' for solo work or authorship hedging.** Never use 'we' for work Karl did personally. Do not hedge authorship with 'through Claude' / 'with Claude's help' qualifiers, even when Claude did the implementing. Karl's literal correction: "you keep saying we — it's I, it's me. I'm the one who did it, of course through Claude, but we don't have to mention that."

**Rule 2 — Allowed 'we' exceptions.** Two uses of 'we' are permitted and correct:
- Inclusive speaker + audience: 'we're going to go over', 'let's take a look at' — the 'we' includes the listener.
- Company / team Maze: 'our customers', 'our critical flows', 'we need better tooling' — 'we' as the organization.

Do NOT apply Rule 1 to these cases. The over-correction (replacing all 'we' with 'I') is the mistake to avoid.

**Rule 3 — Demo-video register traits.** Voice reference: Karl's dictated intro for the acceptance-tests demo video. Apply these register traits when writing spoken/scripted content:
- Plain conversational connectors: 'So...', 'Well...' to open transitions.
- Rhetorical-question pivots: 'Why do we want to do this? Well...' — state the question, then answer it. (The 'we' here is inclusive audience — Rule 2 exception; do not replace with 'I'.)
- Direct audience address: 'Are you ready? Let's get started.'
- Light self-deprecating humor: 'mere humans like ourselves' — warmth without self-mockery.
- 'Cool.' as a beat-separator between sections (standalone word, period).
- What before why — objective then goal: name what you're trying to accomplish before you state why it matters ('objective leads to goal').
- Preferred term: 'critical flows' — not 'the flows that matter most' or any paraphrase. Karl explicitly rejected the paraphrase.

**Rule 4 — Introductory, not inventory.** When presenting a project to an audience that doesn't know it, narrate phases and missions rather than listing deliverables. Example of the wrong register (inventory/listy): 'Part 1 is the friction work: [deliverable list].' Example of the correct register (narrative): 'In the first phase I went after the friction — the places where writing a test was harder than it needed to be.' (first-person here is tier-2 acceptable; attribution-free would also work: 'In the first phase, the friction was the target — the places where writing a test was harder than it needed to be.') Name what you were chasing, not what you shipped.

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
- **Non-technical peer / volunteer-org collaborator (favor ask — known collaborator)** (e.g., Tim Corbett, Barboursville Bloodhounds president; festival/nonprofit context): Warm, humble, low-pressure. This register is calibrated for a KNOWN collaborator — someone you have an established relationship with. It is NOT the right register for cold outreach to an unknown organization or media outlet (see Cold outreach subsection below). This is the OPPOSITE of the work-peer "no deference" default. Key markers:
  - Give the recipient explicit outs: "completely up to you," "if you still want to," "no pressure at all"
  - Soften or omit confidence — heavier hedging is appropriate here ("should be able to," "should hopefully," "or something," "I think")
  - Lead with the concrete upside before the mechanics (value-first framing), then add an honest caveat
  - Gloss jargon with plain-language parentheticals for non-technical readers (e.g., "Goodstack (Google's third party provider for the grants)")
  - Be transparent about reasoning and failed attempts — "which is what I figured would happen, but figured it was worth trying anyway"
  - A light apology or humility close is acceptable here: "I'm sorry I couldn't do more" fits this register
  - Greeting: `Hey [Name],` with a COMMA (not the dash form — see § Greeting / Sign-Off Conventions)
  - Sign-off: `~ Karl` (tilde + first name)

- **Cross-functional / non-engineer readers (Q&O, PM, ops, leadership):** When the reader is NOT a peer backend engineer, DROP implementation symbol names — specific function names, variable names, class/helper names — and explain the *concept* in plain language instead. Feature and spec names (the name of the test or feature under discussion, e.g. `resultsFiltering`, `customTemplates`) may stay because they name the thing being discussed; what you drop is implementation symbol names. Example: say 'a deprecated helper that kept its state at module level', NOT the symbol name. Contrast with the Tommy/peer-DM examples, which keep inline identifiers BECAUSE the reader is a peer backend engineer who has context for them. **Identifier density is audience-dependent**, not absolute: high-density identifiers are appropriate for technical peers; plain-language concept descriptions are appropriate for cross-functional stakeholders.

- **Cold outreach to an unknown organization / media outlet** (e.g., publicity emails to bluegrass publications, radio stations, press, festivals, associations — recipients who don't know you): Warm, confident, grounded — humble WITHOUT being servile. This is NOT the favor-ask register; the explicit-outs and humility-close calibrated for a known collaborator (e.g., Tim) produce servile AI-sounding copy when applied to cold outreach. Key markers:
  - Use the recipient's name ONCE in the greeting only — never repeat it in the body or close (no "Thanks for your time, Darin").
  - Lead strong: state distinctive value with grounded confidence; put the strongest / most-recognizable content first.
  - Warm and grounded, but not deferential — write peer-to-peer, not supplicant-to-gatekeeper.
  - Make the request plainly and stop. No stacked outs, no apologies for asking.
  - Do NOT offer to route the recipient to a third party unprompted.
  - **Drop the contact if the only honest framing is an unsure eligibility question.** If we aren't confident enough to make a direct ask (e.g., "does IBMA list non-member events?", "do you accept non-member listings?"), don't send the email. A cold-outreach email must make a confident ask for what we want. When the only honest framing is an unsure eligibility question, drop the contact rather than send a hesitant note.

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
- **Cold outreach (email):** greeting `Hi [First],` (comma, no tilde); sign-off: first name only (no `~ Karl` tilde)

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
| `critical flows` | 'the flows that matter most' or any paraphrase (Karl explicitly rejected the paraphrase — see § Spoken / Scripted First-Person Content, Rule 3) |
| `cron` | 'scheduled job' / 'scheduled GitHub Action' in casual contexts (Karl: 'I like to use the word cron.' Use the literal word `cron`.) |

---

### Verbatim Examples (Karl)

Real messages Karl has written. Use these to calibrate voice — not for content, for pattern.

> **Note:** This skill distinguishes four voice modes: **peer DM voice** (Tommy ping example below — short paragraphs, polite-but-direct opener), **broadcast voice** (Project Update example below — section headers, no greeting), **favor-ask voice** (non-technical peer / volunteer-org — known collaborator — comma greeting, `~ Karl` sign-off, warm/humble/low-pressure), and **cold-outreach voice** (unknown organization/media outlet — confident, warm, grounded, not servile; see § Audience-Specific Tone Calibration). Before drafting, the coordinator MUST identify the audience type and apply the matching structural template.

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
- **First-person ownership.** `I` not `we` for decisions Karl owns. See also § Spoken / Scripted First-Person Content, Rule 1 for work-attribution specifics (including Claude-authorship hedging).
- **No prologue.** The first sentence is the request or the substantive content. Do not open with preamble like "I wanted to reach out to..." or "Just following up to say...".
- **Conservative timelines.** (See Timeline language under Preferred Phrasings above for examples.)
- **No closing question when Karl has made the call.** Just state what he's doing. Asking framing is reserved for genuine peer-input requests.
- **Internal project codes stay internal.** D1, D2, D3 etc. are for internal use. When messaging external stakeholders, use the actual deliverable name + Linear ID, not the internal code.
- **Audience-knowledge check: cut what the recipient already knows.** Before including an explanatory sentence, ask whether the specific named recipient already has that context. If they already know it, cut the sentence entirely — sending information back to someone who gave it to you reads as padding. Karl's example: 'Atte knows that nothing creates tickets from quarantined tests yet. So I'm just telling him something he already knows.' The test: would this sentence teach this person something, or just re-state what they told you?
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

0. **Audience-type check** — was the right structural template applied for the audience type? Identify which of the four registers applies: work-peer DM/cold outreach, broadcast, non-technical-peer / volunteer-org favor-ask (known collaborator), or cold outreach to an unknown organization / media outlet. If broadcast, verify section-header shape and no-greeting opener. If favor-ask (known collaborator), verify comma greeting and `~ Karl` sign-off. If cold outreach to an unknown org/outlet, verify: confident and grounded tone (not servile), no stacked disclaimers, no grovel-thanks, no meta-hedge, name used in greeting only, no avoided word choices ("unusual", "genuine"/"genuinely"), no news-desk openers, no meta-framing editorializing, no "might be worth a mention"-style hedges (Round 3 Hard Avoids). Also apply the drop-the-contact gate: confirm a direct confident ask exists — if the only honest framing is an unsure eligibility question, drop the contact (see §Audience-Specific Tone Calibration → Cold outreach).
1. **Hard-avoid scan** — does the draft contain any word/phrase from the Hard Avoids section? Rewrite those phrases. (Note: some Hard Avoids are mode-specific — e.g., `Hey -` is valid in work-peer DMs but forbidden in broadcast posts and favor-ask outreach. Apply avoids relative to the audience type identified in step 0.)
1a. **Em-dash scan**: scan the draft for "—" (em dash) and "–" (en dash); replace every hit with a period, comma, colon, or parentheses before continuing.
2. **Length check** — is the draft proportional to the message type? (Slack: brief; email: structured; PR description: two paragraphs max.)
3. **Sign-off check** — does the closing match the Greeting / Sign-Off conventions for this register? Route by register (see § Greeting / Sign-Off Conventions): work-peer Slack → no sign-off; favor-ask (any medium) → `~ Karl`; work-context email → first name only; cold outreach (any medium) → first name only (no `~ Karl` tilde).
4. **Framing check** — is customer/user impact mentioned before technical rationale (where applicable)?
5. **Domain vocabulary scan** — does the draft use any term from the Avoid column of the Domain-Specific Vocabulary table? Substitute with the Preferred column term.
6. **Broadcast-mode check (if channel/broadcast post):** First, identify which broadcast shape applies (milestone-announcement vs progress-update). Then verify the shape-specific constraints for that shape.
   - 6a. **Milestone-announcement shape verification:** Section-header opener present (no greeting)? State-change sentence present? Evidence block (Before/After inline numbers + dates)? Soft invitational pointer to evidence tool (not pasted URL)? `Up Next` block as its own section (not inline)? If any element missed, rewrite to match the milestone-announcement template.
   - 6b. **Progress-update shape verification:** Section-header opener present (no greeting)? Paragraph prose (not bullets)? Inline `@`-mentions for collaborators? Parenthetical intent framing attached to state-of-project sentence (not headlined as separate section)? No LogFrame jargon, no PR numbers, no merge dates? Hedged future-looking statements? Feedback-invitation + emoji close? If any element missed, rewrite to match the progress-update template.
7. **Spoken/scripted check (if video script, talk outline, demo narration, or spoken async update):** Verify Rule 1 — work attribution follows the hierarchy: attribution-free outcome statements preferred ('So now there's a runner.'), first-person singular ('I built', 'I went after') as fallback when attribution-free would be awkward or ambiguous, never 'we' for solo work, never 'through Claude'/'with Claude's help' hedges. Verify Rule 2 — allowed 'we' exceptions (inclusive audience, company/team Maze) are preserved and not over-corrected to 'I'. Verify Rule 4 — project phases are introduced with narrative framing, not an inventory list of deliverables.

Fix any failures before returning the draft.
