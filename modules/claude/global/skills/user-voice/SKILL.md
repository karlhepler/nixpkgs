---
name: user-voice
description: Load user voice profile before drafting user-facing content. Use when drafting user-facing content: draft a Slack message, draft an email, draft a PR description, draft a Linear comment, draft a ticket comment, draft a stakeholder update, write a status report, write release notes, write a changelog, draft a README, write API docs, write a runbook, draft GTM messaging, draft launch copy, draft an email campaign, write an async-handoff message.
---

# User Voice Profile

This skill is a voice profile template. Load it when drafting any user-facing content and conform output to the profile below. The profile grows over time from explicit user corrections — this is a **living document**.

## When to Load

Load this skill whenever drafting:
- Slack messages or thread replies
- Emails (internal or external)
- PR descriptions
- Linear comments or ticket comments
- Stakeholder updates or status reports
- Release notes or changelogs
- READMEs, API docs, or runbooks
- GTM messaging, launch copy, or email campaigns
- Async-handoff messages

---

### Hard Avoids

Words, phrases, and idioms the user dislikes and never uses. Add entries over time from explicit corrections.

- `leverage` (use "use" or "apply" instead)
- `synergy` / `synergize` (avoid entirely)
- `circle back` (use "follow up" or "revisit" instead)

_Add more from user corrections as they occur._

---

### Preferred Phrasings

Specific replacements and formulations the user reaches for:

- Prefers `ship` over `deploy` in informal contexts
- Prefers `folks` over `guys` or `team` in group address
- Prefers "let me know if..." closers over "please advise"

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
