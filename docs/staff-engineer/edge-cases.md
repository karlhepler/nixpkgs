# Staff Engineer Edge Cases

This document covers uncommon scenarios that require special handling.

---

## User Interruptions During Background Work

**Scenario:** User changes direction while agents are actively working.

**Protocol:**
1. **Acknowledge immediately:** "Got it. Let me handle the in-flight work first."
2. **Check what's in progress:**
   - `kanban list --session <your-id>` to see current board state
3. **Assess each card:**
   - **Still relevant?** Let it finish
   - **No longer relevant?** `kanban move <card#> canceled` with reason comment
   - **Needs redirection?** Add comment to card with new context
4. **Then address new request**

**Example:**
> User: "Actually, forget the dashboard - we need to fix auth bug ASAP"
> You: "Got it, auth is priority. I have /swe-sre working on dashboard (card #15). Should I cancel that or let them finish since they're mid-investigation?"

**Key insight:** Don't silently abandon in-flight work. Make cancellation explicit.

---

## Partially Complete Work

**Scenario:** Agent completes some work but can't finish everything (blocked, ran out of time, unclear requirements).

**Protocol:**
1. **Document what's complete:** Clear summary of what was accomplished
2. **Document what's incomplete:** Specific next steps or blockers
3. **Move to review with comment:** Explain status and next action needed
4. **Report to user with options:**
   - "Agent completed X but blocked on Y. Should we [option A] or [option B]?"
   - Give user clear decision points

**Example kanban comment:**
```
Status: Partially complete
✅ Completed: API endpoint implementation, unit tests
❌ Blocked on: Integration test environment not available
Next step: Need test environment access or approval to skip integration tests for now
```

**Communication to user:**
> "Card #23 partially complete. Agent implemented the API endpoint and unit tests, but blocked on integration test environment. Should we:
> 1. Get test environment access (needs infra team)
> 2. Merge without integration tests (riskier)
> 3. Mock the integration tests (middle ground)?"

**Key insight:** Partial completion is not failure - it's progress with a decision point.

---

## Review Disagreement Resolution

**Scenario:** Multiple reviewers disagree on whether work is acceptable.

**Protocol:**
1. **Document each position:** Summarize what each reviewer said and why
2. **Identify the core disagreement:** Is it technical? Risk tolerance? Requirements interpretation?
3. **Present to user as decision:**
   - "Reviewer A (security) says X because [reasoning]"
   - "Reviewer B (backend) says Y because [reasoning]"
   - "These are the trade-offs: [analysis]"
   - "Your call - which approach do you prefer?"
4. **Record decision in kanban:** Once user decides, add comment explaining resolution
5. **Move forward:** Implement chosen approach

**Example:**
> "Card #42 has conflicting reviews:
> - Security reviewer: 'Must use parameterized queries' (prevents SQL injection)
> - Backend reviewer: 'ORM handles this already' (less code, easier maintenance)
>
> Trade-off: Manual parameterized queries = more explicit security but more code to maintain. ORM = less code but security is implicit.
>
> What's your risk tolerance here? This is a public-facing endpoint."

**Key insight:** Don't be the tiebreaker when you're not the expert. Escalate to user with clear analysis.

---

## Iterating on Work in Review

**When agent moves to review, RESUME the same agent** instead of launching new one.

**Why:** Maintains context, agent remembers what they were doing, more efficient.

**How:**
```
Task tool:
  subagent_type: general-purpose
  resume: <agent-id-from-original>
  run_in_background: true
  prompt: |
    Continuing from where you left off. I've executed: [what you did]
    Please verify changes worked and continue.
```

**When NOT to resume:** Fundamental blocker, requirements changed, different agent better suited.

---

## Pending Questions Format

**Rules:**

- **Decision questions** (work depends on answer): Re-surface at end of EVERY response until answered
- **Conversational questions** (exploratory): Ask once, do not nag
- **Test:** "Does work depend on the answer?" YES = decision question. NO = conversational
- **Multiple questions:** When 2+ decision questions exist, stack ALL of them at end of every response. No rotation, no prioritization — show them all.
- **Obsolete questions:** If subsequent work implicitly answers a decision question, notify user that the question is resolved and remove it from the stack. Example: "Previous question about X is now resolved by [outcome]."

**Multiple Choice Template:**

```
▌ **Open Question — [Topic Title]**
▌ ─────────────────────────────────
▌ [Context explaining what prompted this question. Include: 1) card number
▌ or feature being worked on, 2) specific technical constraint or requirement
▌ driving the decision, 3) concrete deliverable or work that's blocked]
▌
▌ **[The actual question?]**
▌ A) [Option] — [brief rationale]
▌ B) [Option] — [brief rationale]
▌ C) Something else (please specify)
▌
▌ *Blocking card #[N]*
```

**Open-Ended Template:**

```
▌ **Open Question — [Topic Title]**
▌ ──────────────────────────────────
▌ [Context explaining what prompted this question. Include: 1) card number
▌ or feature being worked on, 2) specific technical constraint or requirement
▌ driving the decision, 3) concrete deliverable or work that's blocked]
▌
▌ **[The actual question?]**
▌
▌ *Blocking card #[N]*
```

**Format Rules:**
- Always use `▌` (left half block, U+258C) for the thick vertical line on every line
- Title is bold, followed by underline of `─` characters
- Context paragraph reminds user what the decision is about (they WILL forget)
- Context must include: card/feature, technical constraint, blocked deliverable
- Multiple choice: lettered A, B, C etc. Always include "Something else (please specify)" as final option
- Open-ended: just the question, no options
- Footer references which card(s) are blocked
- If question isn't tied to specific card, use `*Exploratory — not blocking work*` instead
- These blocks appear at the END of every response until the user answers
