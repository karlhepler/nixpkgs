---
name: user-voice
description: Load user voice profile before drafting user-facing content. Use when drafting user-facing content: draft a Slack message, draft an email, draft a PR description, draft a Linear comment, draft a Linear card body or description, draft a ticket comment, draft a stakeholder update, write a status report, write release notes, write a changelog, draft a README, write API docs, write a runbook, draft GTM messaging, draft launch copy, draft an email campaign, write an async-handoff message, write a git commit message, write an async standup or progress update.
---

# User Voice Profile

This skill is a voice profile template. Load it when drafting any user-facing content and conform output to the profile below. The profile grows over time from explicit user corrections — this is a **living document**.

## Interpreting Dictated Corrections

A dictated correction is a strong signal for the DIRECTION to move, not a final specification. Karl has revised his own earlier dictation in three separate later rounds within a single feedback session — round 2 added a `likely` hedge to an in-progress finding he had already dictated (see § Preferred Phrasings → In-progress investigation findings), and round 3 and round 4 further revised the monitor-costs sentence into its final team-inclusive `we` form (see § Preferred Phrasings → Closing / next-step language). Treat a dictated phrasing as the direction to move, then apply the profile's general rules on top of it. Do not assume a sentence is final merely because he spoke it aloud.

**Corollary — check dictated phrasing against existing Hard Avoids.** If a dictated phrase itself contains a word that is already a Hard Avoid elsewhere in this profile — e.g. Karl dictated 'understand exactly where the token spend is going,' and `exactly` is a banned intensifier (see § Hard Avoids) — apply the existing avoid to the drafted output AND flag the omission back to him, rather than either silently keeping the banned word or silently dropping it without comment.

## When to Load

This skill defines four voice modes (four registers): DM/peer 1:1 (short paragraphs, polite-but-direct openers), Broadcast/channel-post (section headers, no greeting opener), Non-technical peer / volunteer-org favor-ask — known collaborator (warm, humble, low-pressure; comma greeting `Hey [Name],`; `~ Karl` sign-off), and Cold outreach to unknown organization / media outlet (warm, confident, grounded; NOT servile). Identify the audience type first; the modes are structurally different.

Step 0 (before drafting): identify the audience type — DM (peer 1:1), broadcast (channel/team post), reply (in-thread continuation), investigative-update (work-peer thread, real-time narration of an in-progress investigation), work-peer cold DM (fresh outreach to a known-org colleague you haven't messaged), unknown-organization cold outreach (publication, radio station, festival, or any recipient whose organization you don't have an established relationship with), or favor ask (non-technical peer / volunteer-org — known collaborator). The structural template depends on audience type. Work-peer cold DMs use the peer/DM template (`Hey -` dash opener, no sign-off). Unknown-organization cold outreach routes to the cold-outreach register (confident, warm, grounded, not servile) — a structurally distinct template; see § Audience-Specific Tone Calibration. See `verbatim-examples.md` for the DM vs broadcast distinction. Note: broadcast voice has sub-shapes (milestone-announcement, progress-update) — see `verbatim-examples.md` → Broadcast / Channel Post Template for shape selection before looking up examples. Note: fresh outreach to a NON-technical peer or volunteer-org contact (e.g., a club president, nonprofit collaborator) uses the favor-ask register (comma greeting, `~ Karl` sign-off, warm/deferential) ONLY when that contact is a known collaborator. Cold outreach to an unknown-organization cold recipient (e.g., a bluegrass publication, radio station, festival) uses the cold-outreach register — see § Audience-Specific Tone Calibration.

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

Words, phrases, and idioms the user dislikes and never uses. Add entries over time from explicit corrections. These bans apply to content drafted in the user's voice; a banned word may still appear in this skill file's own descriptive prose about tone qualities (e.g. describing a register as "plainly honest") — that is meta-documentation, not drafted output.

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
- `honest` / `honestly` / `honesty` (Karl: 'I NEVER SAY "HONEST"! I HATE IT!' — reads as defensive/self-justifying, the opposite of his register. Convey the idea with plain declaratives instead: "here's where we actually are", "the real result", never the word.)
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
- Redundant restate-the-point closer: a summarizing one-liner at the end of a casual reply that merely re-states the body's point (Karl's rejected example: 'So quarantined won't mean forgotten' — 'that's stupid and redundant'). End casual replies on substance, not a recap one-liner. IMPORTANT distinction: this ban is NOT the shared-root-cause playful closer (which names the unifying theme — see `verbatim-examples.md` → Structural Patterns → Shared-root-cause closer); only the closer that is redundant because it merely repeats what the body already said is banned.
- `So` opener on AI-DRAFTED action-statements: do NOT open a drafted action-announcement with `So` (e.g. 'So I'm going to drop...' / 'So I'll update...'). It reads forced and canned. Prefer `I'm planning on [X]` or `I'm going to [X]` as the opener. IMPORTANT RECONCILIATION: this is NOT a contradiction of the existing 'Plain conversational connectors: So..., Well...' preferred guidance (see § Spoken / Scripted First-Person Content, Rule 3 — line ~252). Karl uses 'So...' organically as an exploratory, reasoning-out-loud connector in his own stream-of-consciousness writing — that usage stays PREFERRED. The avoid is narrow: only an AI-drafted action-announcement opened with 'So' is banned. The organic connector 'So...' in Karl's own voice is untouched.
- `physically` / false-physicality framing: never use 'physically' (or constructions like 'physically can't') when no physical mechanism is involved — software, CI, workflow, and pipeline contexts have no physical component. Karl: 'there's nothing physical about any of this.' State it plainly instead. Example: 'that way it can't turn the release red' (not 'physically can't turn the release red').
- `our [project artifact]` when the project is Karl's alone: `our headline false-red number`, `the false-reds we're removing`, `our success measures`, `walk through ours` — all wrong when Karl owns the project solo. `Our` implies a team; solo work belongs to `my project`. Use `my X` / `my project's X` instead. Scan for "our" + a project-artifact noun (measures, dashboards, notebooks, metrics, docs); if the project is Karl's alone, switch to "my". Exceptions that stay `our`: org/company Maze (`our customers`, `our critical flows`); inclusive speaker+audience (`let's take a look`).
- **Flippant or overstated emphasis on importance in peer-facing drafts** (Slack, email, PR comments): avoid sassy, dismissive, or self-aggrandizing framings that inflate the importance of Karl's work at the expense of the reader. Bad-example patterns: `'kind of the whole point'`, `'that's the whole game'`, `'obviously'`, `'literally the only thing that matters'`, and similar overstated or dismissive phrasings. Replace with plain, respectful, understated framing: `'one of the main things I'm focused on'`, `'a big focus'`, `'what I'm targeting'`. This composes with the existing understated-register guidance (Karl prefers 'pretty good' over 'great', low-key iterative framing — see § Audience-Specific Tone Calibration) — the additional angle here is that emphasis must stay **respectful toward the reader**, not merely low-key. Scan trigger: scan peer-facing drafts for flippant or overstated emphasis on the importance of something; soften to understated, respectful framing.
- **Authoritative / commanding / imperative register in peer-directed review comments** — applies to PR-review findings, code-review comments, and structurally similar written peer-review feedback drafted in Karl's voice, on any repo, to any peer. Avoid imperative or directive phrasings that frame a finding as an instruction the peer must follow: `'do X'`, `'Worth doing X'`, `'Worth extending the [X] set to cover Y'`, `'Either do X, or do Y'`, `'make X a required check'`, or any wording that reads as ordering a colleague rather than raising a point for their consideration. Real correction: Karl reacted to a draft peer PR-review comment with 'The wording here is much too authoritative. We are telling my friend to do something... like ordering him. That's not cool.' These are colleagues, not subordinates. See § Preferred Phrasings → Peer review / collaborative feedback phrasings for the collaborative alternative, and § Audience-Specific Tone Calibration → Work-peer disagreement register for the related-but-distinct register that covers replying during a disagreement (this entry covers raising the initial finding).
- **Reflexive over-questioning (interrogation) in peer-directed review comments** — the opposite failure mode from the authoritative/imperative entry above, caught in the SAME review walkthrough right after that first correction landed. Having softened away from commands, do not swing the other way and turn nearly every finding into a question (`'Should we X?'`, `'Would it be worth tightening the ordering?'`, `'Would pinning that close the loop?'` on point after point) — a wall of questions reads as an interrogation, not a conversation. Real correction: Karl reacted to a question-heavy draft with 'you're using questions too much... it didn't have to be a question... I think we might want to try this or it might make sense to do this... you can have a light what do you think but going a little too far with the questions.' The fix is a hedged STATEMENT, not a question — see § Preferred Phrasings → Peer review / collaborative feedback phrasings for the preferred hedged-statement form and the occasional, sparing role of question forms. This is a FREQUENCY rule, not word choice: any question form, including the occasional-OK examples in § Preferred Phrasings, becomes reflexive over-questioning if it recurs on nearly every finding, and the bad-example phrasings above are illustrations of the overuse pattern, not a list of banned words.
- **Obtuse or domain-specific initialisms** (e.g., an unglossed project- or company-specific letter-string like `SMT`) — expand on first use; common acronyms (`CI`, `PR`, `API`) are fine (see global CLAUDE.md § Initialisms). Karl had to stop and ask what an initialism meant before he could relay it to his team; the expansion prevents that.
- `ship-to-learn` / `ship to learn` (Karl: 'That's not something I would ever say.' Use `We're going to try this out and see how it goes` instead.) **General caveat, and this is the more valuable half:** a phrase spoken by another participant in a source document — meeting transcript, thread, doc — is NOT thereby in Karl's voice. This exact phrase came from a transcript where a colleague said it. When drafting from a transcript, do not lift a colleague's idiom into Karl's own prose.
- Prohibition aimed at people, when announcing a config or policy change: `Nobody will be able to X` / `Nobody can X anymore` — Karl aims the sentence at the mechanism, not at colleagues. Use `This means that X will not be available after this config is enabled` instead.
- `we'll change it back` / `we'll revert it` as a promised response to feedback — over-commits to an outcome. Use `we can discuss and potentially adjust` instead (see § Preferred Phrasings → Closing / next-step language).
- Bare `we` as the subject when a specific internal team is the actor **and has not yet been named** — name the team instead: `The platform team has been digging into...`, not `We've been digging into...`. Distinct from the allowed-`we` exceptions (see § Spoken / Scripted First-Person Content, Rule 2) and from the solo-possessive `our [project artifact]` rule above. Once the team has been named, a later `we` referring back to it is fine; the rule targets an unattributed opening `we`. This does NOT mean converting ongoing team activity to `I` — see § Actor Attribution — I vs a Named Team vs We for the full reconciliation.
- An abstract noun paired with `happens` — configs, changes, migrations, deploys, and settings do not "happen." Karl: 'a config doesn't happen... configs don't quote-unquote happen.' Use a verb naming the actual mechanism instead: `after this config is enabled`, `after this config goes through`, `after this config is set`. Note `lands` is already banned above (see the `lands` / `nothing lands unassigned` entry) — do not offer it as a substitute here.
- An abstract metric-flavoured paraphrase standing in for concrete activity: `so we can see whether the trajectory actually moves`, `to validate the signal`, `so we can measure the impact` — Karl: 'that sentence doesn't really make any sense to me.' Name the actual activities plainly instead. When two distinct things are happening — one Karl is doing, one the team is doing — give them separate sentences rather than one compressed abstraction. Distinct from the persuasive-authority-tropes ban below, which bans ceremonial depth-claiming ("at its core", "what really matters"); this entry bans substituting a vague measurement abstraction for concrete content.

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

### Actor Attribution — I vs a Named Team vs We

This subsection reconciles two directions that pull apart on the surface and are not actually in conflict. The bare-`we` Hard Avoid above (see § Hard Avoids) pushes FROM an unattributed opening `we` TOWARD naming the specific team that did the work. The cost-monitoring Preferred Phrasing (see § Preferred Phrasings → Closing / next-step language) pushes FROM `I` TOWARD `we`. **The decision is about who actually does the thing, not about a default pronoun.**

Five cases:
- **The user personally does it** → `I`, or better, an attribution-free outcome statement (see § Spoken / Scripted First-Person Content, Rule 1).
- **A specific internal team does it, on first reference** → name the team. Do not open with an unattributed `we` (see § Hard Avoids → bare `we`).
- **That same team, on later references** → `we` is fine; the subject is already established.
- **A named individual does it** → name them with an at-mention.
- **Ongoing team activity the user participates in but does not solely own** — cost monitoring, telemetry work → `we`, NOT `I`. Karl: 'Don't attribute it to me specifically.'

This is a SEPARATE axis from the existing solo-possessive `our [project artifact]` rule (see § Hard Avoids) — that rule is unchanged. It governs possessives for solo-owned artifacts (`my project`'s X, not `our project`'s X); this subsection governs the SUBJECT of a sentence describing an activity. The two rules do not compete.

This is also a SEPARATE axis from Rule 2's org-wide/inclusive `we` exceptions (see § Spoken / Scripted First-Person Content, Rule 2): when the `we` names the org/audience rather than a specific doer of the activity (inclusive speaker+audience, or org/company Maze), Rule 2 governs and none of the five cases above apply.

This also means the existing § Spoken / Scripted First-Person Content, Rule 1 preference for de-attributed statements over first-person applies to written broadcast prose too, not only spoken/scripted content.

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
- `Cutting X in half is a quick and easy way to test whether Y is in fact the right thing to go after` — explicitly approved for framing a cheap experiment. `in fact` is the intensifier wanted here.
- `If it's getting in the way of how you work, let us know and we can discuss and potentially adjust` — the full approved shape for inviting feedback on a change affecting colleagues. Keep the conditional opener; end on discuss-and-potentially-adjust, never on a promised reversal (see § Hard Avoids → `we'll change it back` / `we'll revert it`).
- `We'll monitor costs over the next week or two to see if this change has made any significant impact.` — the shape for a forward-looking observation period on ongoing team activity Karl participates in but does not solely own; see § Actor Attribution — I vs a Named Team vs We. Karl rejected his own round-3 dictation of this sentence in round 4: 'Don't attribute it to me specifically, say we will monitor costs over the next week or two to see if this change has made any significant impact.' Plain verb, plain window, purpose stated as a plain question about impact rather than left implicit, no metric abstraction (see § Hard Avoids → abstract metric-flavoured paraphrase). Same preference for a rounded window over a precise one that shows up in the timeline habit: `a week or two`, not a specific date (see § Preferred Phrasings → Timeline language above).
- `so we can better understand at a higher granularity where X is going, which skills, that kind of thing` — the shape for describing telemetry or visibility work. `that kind of thing` as an open trailing enumerator, companion to the existing tentative-scope listings (see § Broadcast / channel-post phrasings → 'some sort of X' / 'possibly X').

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

**In-progress investigation findings (hedge confidence, likelihood, AND ranking):**

Karl's correction, verbatim: 'Not being so assertive as you are.' When stating what an investigation has turned up so far, hedge all three dimensions — confidence, likelihood, and ranking.

- **PREFERRED, the final approved form:** `So far it appears that X is likely one of the biggest cost drivers`
- TOO ASSERTIVE: `X is the biggest driver we've found so far` — drops `it appears that` and `likely`, and `the biggest` overclaims where `one of the biggest` is honest.
- **Three hedges stack deliberately and all are wanted.** `So far` bounds it in time, `it appears that` hedges confidence in the finding, `likely` hedges the claim itself. Karl added `likely` on a SECOND pass over a sentence he had already dictated himself — three stacked hedges is the target on an in-progress finding, not excessive.
- Name the dimension in the noun: `cost drivers`, not bare `drivers`.
- `we've found` is droppable and Karl dropped it. Do not treat it as required.
- **Tension with plain cause-and-consequence chains, recorded rather than resolved away:** this coexists with the existing casual-Slack guidance to state facts as plain cause-and-consequence chains with no hedges (see § Preferred Phrasings → Causal-chain connectors). The distinction is subject matter, not register. A MECHANICAL fact stays unhedged — "The bigger the context window, the longer a session runs before it compacts" — while an INVESTIGATION FINDING gets hedged. Both can sit in the same paragraph.

**Peer review / collaborative feedback phrasings (raising a finding — not the disagreement-reply register):**

_(Distinct from § Audience-Specific Tone Calibration → Work-peer disagreement register, which covers replying to a peer during a back-and-forth. This subsection covers the FIRST move: surfacing a review finding in the first place. The two compose — raise the finding collaboratively here, then if the peer pushes back, switch to the disagreement register.)_

- Observational + curious openers: `'One thing I noticed...'`, `'It looks like...'`, `'I might be missing context, but...'` — raise the point as an observation, not a directive.
- **PREFERRED — hedged statements, the sweet spot between the two failure modes:** `'I think it might make sense to...'`, `'It might be worth...'`, `'Could be this or that.'` — a hedged STATEMENT, not an order and not a question, is the default form for raising a finding. Gold-standard phrasing: `'it might make sense to...'`.
- **OCCASIONAL — light question forms:** `'Could we...?'`, `'What do you think about...?'` — fine SPARINGLY, e.g. a light closing `'what do you think?'` — but not the default replacement for commands. Do NOT turn nearly every finding into a question; that over-corrects into an interrogation (see § Hard Avoids → Reflexive over-questioning).
- Humility hedges that leave room for the author to know better: `'Could be I'm misreading the ordering'`, `'if that's intentional, ignore me.'` — this is a framing device for the body of a finding, not a closing hedge; it does not license the banned hedging-closer / passive-exit pattern (see § Hard Avoids → hedging closers, context-free closings, passive exit statements).
- **Not a general deference shift:** this softened delivery is a narrow exception scoped to raising a review finding — it does not change Karl's default direct/not-deferential register elsewhere (see § Tone Register). Only the framing of a FINDING (not a request, opinion, or general assertion) shifts from command-form to hedged-statement-form (occasionally question-form); the directness of the point itself stays intact.
- **The universal principle:** a review comment to a peer is a hedged observation inviting discussion — never an order, and never an interrogation. Surface the concern plus the reasoning behind it as a hedged statement, then let the author decide; reserve question forms for an occasional light touch, not a wall-to-wall interrogation of every point.

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

- **Casual technical back-and-forth (peer Slack thread — incremental replies, e.g. a live investigation or decision thread):** This is the **casual technical** register — distinct from the structured investigative-update cadence and from formal work-peer DMs. Markers: ellipsis-as-connector ('...') to carry a thought forward; reasoning-out-loud cadence; 'I mean...' as a mid-thought self-clarifier; tentative ownership ('I'm thinking', 'I could', 'I might'); hedges (ideally, possibly, might); concrete-example reasoning to justify a point ('won't post to slack, for instance'); understated positives ('pretty good idea', not 'great'); casual diction ('stuff'); terse when terse fits ('looking into it' is a complete message); states the WHY plainly, never pulls rank. Karl's gold-standard samples: 'looking into it' (complete message — no expansion needed); 'I'm thinking if I make it a non-gating check, it won't post to slack, for instance. so it won't interrupt anybody. That's kind of ideally what I want.' Note the lowercase 'so' mid-message here — this is Karl's organic connector, not an AI-drafted action opener (see § Hard Avoids on the `So`-opener distinction).

- **Work-peer disagreement register (e.g., PR-review back-and-forth):** When replying to a work peer during a disagreement, the register must be warm and collaborative, NOT corrective. Lead with validation — e.g., 'totally fair concern', 'you're right that...' — before stating any counter-point. Frame any correction as sharing what you found ('what I found was...'), never as pointing out where they are wrong. Do NOT quote the recipient's own words back at them pointedly; that reads as adversarial even when it isn't intended that way. This is a sub-register of the peer-DM template, not a separate mode — the same structural conventions (short paragraphs, no greeting on replies, first-person ownership) apply. Distinct from, and complementary to, § Preferred Phrasings → Peer review / collaborative feedback phrasings: that subsection covers raising the INITIAL finding (an invitation to a conversation, not an order); this entry covers what happens next, when the peer pushes back on it.
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

Real messages Karl has written — calibration examples for the four voice modes (peer DM, broadcast, cross-functional, and Slack technical explanation), their patterns and anti-pattern contrasts, and the structural patterns (message length, ownership, closers, broadcast template shapes, including the Broadcast / Channel Post Template shapes) they exhibit. Read `~/.claude/skills/user-voice/verbatim-examples.md` (source: `modules/claude/global/skills/user-voice/verbatim-examples.md`) before drafting user-facing content, to calibrate against real examples rather than reasoning from the abstract rules alone.

---

### Examples

Worked examples showing "AI default" vs "user voice" for common message types.

These examples are illustrative seeds — they show the contrast pattern (AI default vs user voice) but do NOT reflect any specific user's actual voice. Replace each example with a real correction as the user provides tone feedback during sessions.

**Example 1 — Slack thread reply**

AI default:
> Hi team, just wanted to circle back on the deployment discussion. We should leverage our existing infrastructure to synergize our efforts here. Please advise on next steps.

User voice:
> Following up on the deploy discussion. I think we can reuse the existing setup here. What's the blocker?

**Example 2 — PR description (opening paragraph)**

AI default:
> This pull request introduces improvements to the authentication flow by implementing various enhancements that will leverage our existing token infrastructure.

User voice:
> Speeds up login by caching the token refresh response. Reduces p95 auth latency from ~600ms to ~80ms.

**Example 3 — Ticket comment (status update)**

AI default:
> I wanted to provide an update regarding the current status of this ticket. We have made significant progress and are working diligently to complete the remaining items.

User voice:
> Backend is done. Frontend wiring in progress. Should be wrapped up today.

---

## Update Process

When the user provides an explicit tone correction during a session, file a `claude-improvement` note via `mcp__notes__upsert_note` to land the update through the Implementer loop. Never edit the skill file yourself in either tree: the deployed copy is regenerated by `hms` from its nixpkgs source, so a direct edit there is discarded on the next deploy and never version-controlled — and § Hard Rules item 15 makes the Implementer the only authorized writer for that source. The note is the only route, however small the addition.

This is a **living document** — the profile grows from real corrections, not from initial guesses. Stale entries should be removed; new ones added promptly.

---

## Voice-Conformance Check

Before surfacing any user-facing draft, run a quick self-check:

0. **Audience-type check** — was the right structural template applied for the audience type? Identify which of the four registers applies: work-peer DM/cold outreach, broadcast, non-technical-peer / volunteer-org favor-ask (known collaborator), or cold outreach to an unknown organization / media outlet. If broadcast, verify section-header shape and no-greeting opener. If favor-ask (known collaborator), verify comma greeting and `~ Karl` sign-off. If cold outreach to an unknown org/outlet, verify: confident and grounded tone (not servile), no stacked disclaimers, no grovel-thanks, no meta-hedge, name used in greeting only, no avoided word choices ("unusual", "genuine"/"genuinely"), no news-desk openers, no meta-framing editorializing, no "might be worth a mention"-style hedges (Round 3 Hard Avoids). Also apply the drop-the-contact gate: confirm a direct confident ask exists — if the only honest framing is an unsure eligibility question, drop the contact (see §Audience-Specific Tone Calibration → Cold outreach).
1. **Hard-avoid scan** — does the draft contain any word/phrase from the Hard Avoids section? Rewrite those phrases. (Note: some Hard Avoids are mode-specific — e.g., `Hey -` is valid in work-peer DMs but forbidden in broadcast posts and favor-ask outreach. Apply avoids relative to the audience type identified in step 0.)
1a. **Em-dash scan**: scan the draft for "—" (em dash) and "–" (en dash); replace every hit with a period, comma, colon, or parentheses before continuing.
1b. **Actor-attribution scan** — runs for every draft type, not only change-announcement broadcasts: does the draft misattribute an ongoing activity? Check for a bare `we` opening where a specific, not-yet-named internal team is the actor (see § Hard Avoids → bare `we`), and check for the opposite failure — ongoing team activity the user participates in but does not solely own, drafted as `I` instead of `we` (see § Actor Attribution — I vs a Named Team vs We, case 5).
2. **Length check** — is the draft proportional to the message type? (Slack: brief; email: structured; PR description: two paragraphs max.)
3. **Sign-off check** — does the closing match the Greeting / Sign-Off conventions for this register? Route by register (see § Greeting / Sign-Off Conventions): work-peer Slack → no sign-off; favor-ask (any medium) → `~ Karl`; work-context email → first name only; cold outreach (any medium) → first name only (no `~ Karl` tilde).
4. **Framing check** — is customer/user impact mentioned before technical rationale (where applicable)?
5. **Domain vocabulary scan** — does the draft use any term from the Avoid column of the Domain-Specific Vocabulary table? Substitute with the Preferred column term.
6. **Broadcast-mode check (if channel/broadcast post):** First, identify which broadcast shape applies (milestone-announcement vs progress-update). Then verify the shape-specific constraints for that shape.
   - 6a. **Milestone-announcement shape verification:** Section-header opener present (no greeting)? State-change sentence present? Evidence block (Before/After inline numbers + dates)? Soft invitational pointer to evidence tool (not pasted URL)? `Up Next` block as its own section (not inline)? If any element missed, rewrite to match the milestone-announcement template.
   - 6b. **Progress-update shape verification:** Section-header opener present (no greeting)? Paragraph prose (not bullets)? Inline `@`-mentions for collaborators? Parenthetical intent framing attached to state-of-project sentence (not headlined as separate section)? No LogFrame jargon, no PR numbers, no merge dates? Hedged future-looking statements? Feedback-invitation + emoji close? If any element missed, rewrite to match the progress-update template.
   - 6c. **Change-announcement scan (if the broadcast announces a config or policy change):** Bare `we` opening a sentence where a named team is the actor (see § Hard Avoids)? An under-hedged investigation finding — are all three of `So far` / `it appears that` / `likely` present when stating a finding (see § Preferred Phrasings → In-progress investigation findings)? Prohibition-aimed-at-people framing (`Nobody will be able to...` / `Nobody can X anymore`)? A promised reversal (`we'll change it back` / `we'll revert it`)? An abstract noun paired with `happens`? An abstract measurement paraphrase standing in for concrete activities? Also scan for idioms lifted from a source transcript that belong to another speaker, not Karl (see § Hard Avoids → `ship-to-learn`). (Actor-attribution is covered by step 1b above for every draft type, including this one.)
7. **Spoken/scripted check (if video script, talk outline, demo narration, or spoken async update):** Verify Rule 1 — work attribution follows the hierarchy: attribution-free outcome statements preferred ('So now there's a runner.'), first-person singular ('I built', 'I went after') as fallback when attribution-free would be awkward or ambiguous, never 'we' for solo work, never 'through Claude'/'with Claude's help' hedges. Verify Rule 2 — allowed 'we' exceptions (inclusive audience, company/team Maze) are preserved and not over-corrected to 'I'. Verify Rule 4 — project phases are introduced with narrative framing, not an inventory list of deliverables.

Fix any failures before returning the draft.
