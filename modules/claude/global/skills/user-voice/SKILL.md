---
name: user-voice
description: Load user voice profile before drafting user-facing content. Use when drafting user-facing content: draft a Slack message, draft an email, draft a PR description, draft a Linear comment, draft a Linear card body or description, draft a ticket comment, draft a stakeholder update, write a status report, write release notes, write a changelog, draft a README, write API docs, write a runbook, draft GTM messaging, draft launch copy, draft an email campaign, write an async-handoff message, write a git commit message, write an async standup or progress update.
---

# User Voice Profile

This skill is a voice profile template. Load it when drafting any user-facing content and conform output to the profile below. The profile grows over time from explicit user corrections — this is a **living document**.

## When to Load

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

Underlying anti-patterns: hedging closers, context-free closings, passive exit statements. The one-off entries below are captured examples — avoid the pattern broadly, not just the verbatim phrases.

- `in case any of it's useful`
- `leave it as fuel`
- `I'll move on with whatever I'm doing in my project` (vague)

_Add more from user corrections as they occur._

---

### Preferred Phrasings

Specific replacements and formulations the user reaches for:

- Prefers `ship` over `deploy` in informal contexts (`ship` as a verb; `deploy` as a noun or modifier, e.g., "deploy discussion", is fine)
- Prefers `folks` over `guys` or `team` in group address
- Prefers "let me know if..." closers over "please advise"

**Openers (matched to message type):**
- Replies / thread continuations: `Thanks!` to open a reply when acknowledging something
- Fresh outreach: `Hey -` (dash after Hey, not comma; only on new threads, not continuations)
- Peer requests: `Would you mind ... when you get a chance please?`

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

---

### Greeting / Sign-Off Conventions

- Greetings: omit in short Slack messages; include in emails
- Sign-offs: no formal sign-off in Slack; emails close with first name only
- Thread continuations: skip greeting, jump straight to content

_Update with user corrections._

---

### Domain-Specific Vocabulary

Preferred terms and terms to avoid in this user's domain:

| Preferred | Avoid |
|-----------|-------|
| `card` | `ticket` (in kanban context) |
| _(add domain-specific vocabulary corrections as they accumulate)_ | _(add more)_ |

---

### Verbatim Examples (Karl)

Real messages Karl has written. Use these to calibrate voice — not for content, for pattern.

**Tommy ping (peer review request):**

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

### Structural Patterns (Karl)

- **Message length calibration.** Slack: brief (1-3 paragraphs max). Email: structured but compact. PR description: two paragraphs max (see global CLAUDE.md § PR Descriptions).
- **Short paragraphs.** Each does one thing. Karl prefers structure over single-block prose.
- **First-person ownership.** `I` not `we` for decisions Karl owns.
- **No prologue.** The first sentence is the request or the substantive content. Do not open with preamble like "I wanted to reach out to..." or "Just following up to say...".
- **Conservative timelines.** (See Timeline language under Preferred Phrasings above for examples.)
- **No closing question when Karl has made the call.** Just state what he's doing. Asking framing is reserved for genuine peer-input requests.
- **Internal project codes stay internal.** D1, D2, D3 etc. are for internal use. When messaging external stakeholders, use the actual deliverable name + Linear ID, not the internal code.

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

1. **Hard-avoid scan** — does the draft contain any word/phrase from the Hard Avoids section? Rewrite those phrases.
2. **Length check** — is the draft proportional to the message type? (Slack: brief; email: structured; PR description: two paragraphs max.)
3. **Sign-off check** — does the closing match the Greeting / Sign-Off conventions for this message type?
4. **Framing check** — is customer/user impact mentioned before technical rationale (where applicable)?
5. **Domain vocabulary scan** — does the draft use any term from the Avoid column of the Domain-Specific Vocabulary table? Substitute with the Preferred column term.

Fix any failures before returning the draft.
