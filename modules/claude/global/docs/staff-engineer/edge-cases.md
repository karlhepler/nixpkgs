# Edge Cases

Guidance for uncommon scenarios in staff engineer coordination.

---

## User Interruptions During Background Work

**Scenario:** User changes direction while agents are running.

**What to do:**
- **Acknowledge immediately** - User's new direction takes priority
- **Evaluate in-flight work** - Is it still valuable or now irrelevant?
- **If still valuable** - Let agent finish, apply what's useful
- **If now irrelevant** - Don't waste time reviewing, note it and move on
- **Cancel cards** for work that's no longer needed (`kanban cancel <card#>`)

**Example:**
```
User: "Actually, skip the dark mode feature. Focus on the payment bug instead."
You: "Got it. /swe-frontend is wrapping up dark mode (card #15) - I'll let them finish
since they're 90% done, then we'll shelf it. Spinning up /swe-backend for the payment
bug (card #16) right now."

[Dark mode agent returns]
You: "Dark mode complete but no longer needed. Canceling card #15. Payment bug investigation
underway (card #16)."
```

**Anti-pattern:**
- Blocking conversation to review irrelevant work ("Let me thoroughly review this dark mode work we're not using...")
- Wasting agent time on canceled directions without acknowledging to user

---

## Partially Complete Work

**Scenario:** Agent returns without finishing everything.

**What to do:**
- **Move card to review** - `kanban review <card#>` FIRST (always required)
- **Launch AC reviewer** - AC reviewer fetches card details (`kanban show`) and evaluates which criteria are satisfied
- **AC reviewer passes/fails criteria** - Only the AC reviewer calls `kanban criteria pass/fail` (sets `reviewer_met` column); sub-agents use `kanban criteria check/uncheck` (sets `agent_met` column); staff engineer never calls per-criterion mutation commands
- **For remaining items** - Two paths:
  - **Resume work**: `kanban redo <card#>`, new agent picks up remaining unverified AC
  - **Follow-up card**: If scope changed, create new card with remaining work
- **Never mark done with unverified AC** - The CLI enforces this

**Example:**
```
Agent returns: "Completed API endpoint and tests. Hit permission gate for deployment."

You:
1. kanban review 20          # Move to review (staff engineer's only kanban call here)
2. [Launch AC reviewer for card #20]

AC Reviewer:
1. kanban show 20              # Fetch card details and AC list
2. kanban criteria pass 20 1 # "API endpoint implemented" - satisfied
3. kanban criteria pass 20 2 # "Tests passing" - satisfied
4. Returns: "AC #3 'Deployed to staging' still unverified - deployment blocked"

You:
5. Execute deployment (handle permission gate)
6. [Launch AC reviewer again after deployment]

AC Reviewer:
7. kanban criteria pass 20 3 # Now satisfied
8. Returns: "All AC verified"

You:
9. kanban done 20 'JWT auth implemented, tested, deployed'
```

**Anti-pattern:**
- Moving directly from doing to done (skipping review)
- Staff engineer calling `kanban show` or `kanban criteria check/uncheck/pass/fail` directly
- AC reviewer using `kanban criteria check/uncheck` (those are for sub-agents only)
- Creating new card instead of resuming when AC are clear

---

## Review Disagreement Resolution

**Scenario:** Reviewer flags issues with the original agent's work.

**What to do:**
- **Reviewer documents concerns** in their review card summary
- **Staff engineer evaluates** - Is the concern valid?
- **If valid** - Send original work back with specific feedback
  - `kanban redo <original-card#>`
  - Include reviewer's feedback in new agent prompt
- **If debatable** - Escalate to user for decision
  - Present both perspectives
  - User decides direction
- **Never override security review** without user approval

**Example - Valid concern:**
```
Backend peer: "API endpoint works but no rate limiting - vulnerable to abuse"

You: "Valid concern. Sending back to /swe-backend (redo card #30) with requirement
to add rate limiting before approval."

[Agent implements rate limiting]
Backend peer (second review): "APPROVE - rate limiting added, 100 req/min per IP"
```

**Example - Debatable concern:**
```
Infra peer: "Use RDS for relational data"
Backend peer: "Use DynamoDB for flexibility"

You: "Two different approaches recommended. @user, what matters more - strong
consistency and complex queries (RDS) or flexibility and scale (DynamoDB)?"

User: "We need complex queries for reporting."

You: "Going with RDS. Thanks @infra-peer, implementing your recommendation."
```

**Anti-pattern:**
- Ignoring reviewer concerns without evaluation
- Immediately overriding security reviews (escalate to user instead)
- Not documenting resolution rationale

---

## Iterating on Work in Review

**Scenario:** Work needs refinement, not a full redo.

**What to do:**
- **For trivial remaining work** - Staff engineer may do it directly
  - Example: Typo fix, minor config tweak, documentation update
  - Faster than spawning agent for 30-second task
- **For substantive changes** - Send back to doing with new agent
  - Include reviewer's feedback in prompt
  - Add new AC items if refinements represent new requirements
- **Keep the same card** - Don't create new card for iterations on same work
- **When adding AC** - New criteria MUST fit the card's action/intent
  - If new work doesn't align, create separate card instead

**Example - Staff eng handles trivial:**
```
Reviewer: "APPROVE WITH MINOR FIX - Change error message line 45 from 'Failed' to
'Invalid credentials'"

You: [Makes the edit directly]
kanban criteria check 35 3  # Check off the AC
kanban done 35 'Auth implemented with reviewer feedback applied'
```

**Example - Send back for substantive:**
```
Reviewer: "CHANGES REQUIRED - Add retry logic for transient failures, implement
exponential backoff, add circuit breaker"

You: "Substantive changes needed. Sending back to /swe-backend (redo card #40) with
reviewer's feedback."

[Creates new agent with reviewer's specific feedback in prompt]
```

**Example - New AC fits card:**
```
User (mid-review): "Also add a dark mode toggle to that settings page"

You: [Settings page work already in review as card #25]
kanban criteria add 25 "Dark mode toggle added to Settings"
kanban redo 25  # Send back with new AC
```

**Example - New AC doesn't fit:**
```
User (mid-review): "Also fix that payment bug"

You: "Payment bug is separate from the settings page work (card #25). Creating new
card #26 for payment bug."

[Don't add payment bug AC to settings page card - different intent]
```

**Anti-pattern:**
- Spawning agent for 30-second typo fix (staff eng can handle trivial work)
- Creating new card instead of redo when iterating on same work
- Adding unrelated AC to existing card (create separate card instead)
- Removing AC without follow-up card (unless truly N/A)

---

## Work Blocked on External Dependency

**Scenario:** Agent needs something outside their control (API access, credentials, third-party approval).

**What to do:**
- **Move card to review** - Agent returns with "blocked on X"
- **Staff engineer handles coordination**
  - Reach out for API access, credentials, approvals
  - Document what's needed and why
- **Two paths**:
  - **Defer card** - `kanban defer <card#>` (moves to todo), resume when unblocked
  - **Parallel work** - Start other cards while waiting, resume later

**Example:**
```
Agent: "Need production API key to test Stripe integration. Blocked."

You:
1. kanban review 50  # Move to review
2. "@user, agent needs production Stripe API key to complete testing. Can you provide
   that or should we use test mode for now?"
3. User provides key
4. kanban start 50  # Pick up from todo
5. Resume agent with key in prompt
```

**Anti-pattern:**
- Leaving card in doing while blocked (moves to review, then defer if long wait)
- Not communicating blockage to user
- Agent trying to work around blockage instead of surfacing it

---

## Multiple Sessions Creating Conflicts

**Scenario:** Another session's work conflicts with yours.

**What to do:**
- **Check board before delegation** - `kanban list --output-style=xml` (mandatory)
- **Detect file conflicts** - Compare editFiles across in-flight cards
- **Call out proactively** - "Session X is working on same file - should I queue this or coordinate?"
- **Coordinate with user** - They decide: sequential, parallel (different parts), or merge into one card

**Example:**
```
You: [Checking board before delegation]
"I see session a11ddeba is editing src/auth/login.ts (card #24). Your request also
touches that file. Should I:
1. Queue after they finish (safer)
2. Work in parallel on different functions (riskier)
3. Add to their card (if related work)"

User: "Different functions, parallel is fine."

You: "Got it. Both sessions editing login.ts - I'll note the specific functions in
the card to minimize conflict risk."
```

**Anti-pattern:**
- Starting work without checking board first
- Not calling out conflicts proactively
- Assuming parallel is safe without user confirmation

---

## Agent Hits Unexpected Permission Gate

**Scenario:** Agent needs permission you didn't anticipate.

**What to do:**
- **Agent returns** with summary: "Need permission for X"
- **Evaluate the request** - Is it safe? Expected?
- **If safe** - Execute, resume agent
- **If unexpected/risky** - Ask user before executing
- **If wrong approach** - Resume agent with alternative direction

**Example - Safe, execute:**
```
Agent: "Need to run npm install to add date-fns dependency."

You: [Runs npm install]
Resume agent: "npm install complete, date-fns available. Continue implementation."
```

**Example - Unexpected, ask user:**
```
Agent: "Need to run git push --force to fix history."

You: "@user, agent is requesting git push --force to fix commit history. This is
destructive - is this expected?"

User: "No, we don't rewrite history. Tell them to create new commit."

You: Resume agent: "Don't use --force. Create new commit instead."
```

**Anti-pattern:**
- Blindly executing destructive operations without user confirmation
- Blocking on trivial permission gates you could approve
- Not providing alternative direction when rejecting approach

---

## Sub-Agent Alternative Discovery

**Scenario:** Agent discovers a different tool, library, or approach than what the card's `action` field specifies.

**Decision rule:** If the card's `action` field specifies a tool/approach and the agent discovers a different one, the agent stops and surfaces for approval. Sub-agents have autonomy within unspecified bounds but must surface alternatives that affect card deliverables.

### Autonomy vs Approval Boundaries

**Sub-agents have autonomy over:**
- Implementation details not specified in the card (e.g., which helper functions to extract, how to structure internal logic)
- Equivalent techniques that produce identical outcomes (e.g., using `Array.from()` vs spread syntax for array conversion)
- Minor tooling choices within the same ecosystem when the card doesn't specify (e.g., which testing assertion library to use when the card only says "write tests")
- Error handling patterns, logging verbosity, code organization within their delegated scope

**Sub-agents must surface and stop when:**
- The card's `action` specifies a named library/framework and a different one would be used (e.g., card says "use Passport.js" but agent wants NextAuth.js)
- The card's `action` specifies a named tool and a different one would be used (e.g., card says "use PostgreSQL" but agent discovers the app uses SQLite)
- The alternative changes the deliverable scope or external interface in a way the card doesn't anticipate
- Continuing with the discovery would require modifying files outside the card's `editFiles` scope

### Surfacing Workflow

When a sub-agent discovers an alternative that requires approval, it follows these 6 steps:

1. **Stop work** — Do not proceed with the alternative or the originally specified approach
2. **Document discovery** — Write a `kanban comment` explaining what was found and why it differs from the card's specification (include relevant context: what the card specifies, what was discovered, why they conflict)
3. **State choice clearly** — In the comment, explicitly state: "Discovered alternative: [X]. Card specifies: [Y]. Waiting for approval to proceed with [X] or confirmation to proceed with [Y]."
4. **Move to review** — Run `kanban review <card#>` so the staff engineer sees the card is blocked
5. **Return to staff engineer** — Return with a summary of the discovery and the comment number where full context is documented
6. **Wait for decision** — Do not attempt partial work or workarounds; the staff engineer decides and re-delegates with updated direction

### Examples

**Requires approval — named library swap:**
```
Card action: "Add authentication using Passport.js with JWT strategy"
Agent discovers: The codebase already has NextAuth.js configured with active sessions

Agent:
1. Stop work
2. kanban comment 55 "Discovered NextAuth.js already configured in the codebase (see
   src/auth/config.ts). Card specifies Passport.js. Adding Passport.js alongside
   NextAuth.js would create a second auth system. Waiting for approval to proceed
   with NextAuth.js JWT integration or confirmation to add Passport.js as specified."
3. kanban review 55
4. Returns: "Blocked — see card #55 comment. Auth library conflict found."
```

**Does not require approval — unspecified library choice:**
```
Card action: "Write unit tests for the UserService class"
Agent discovers: No testing library is installed yet

Agent: Selects Jest (standard for the stack), installs it, writes tests.
No surfacing needed — card didn't specify a testing library.
```

**Does not require approval — equivalent technique:**
```
Card action: "Implement date formatting for the invoice display"
Agent discovers: date-fns is installed; the card doesn't specify which date library to use

Agent: Uses date-fns since it's already available. No surfacing needed —
card didn't specify a library, and using an existing dependency is the correct choice.
```

### Detecting Undisclosed Alternatives During AC Review

When the AC reviewer evaluates completed work, they should flag silent approach swaps — cases where the agent used a different tool or library than specified without surfacing for approval.

**Signals to look for:**
- Card specifies a named library but imports show a different one
- Card specifies a named tool but the implementation uses an alternative
- Work is complete but the specified approach is nowhere in the diff

**What to do when detected:**
- Mark the relevant AC as failed (`kanban criteria fail <card#> <n>`)
- Add a comment: "Silent approach swap detected — card specified [X] but implementation uses [Y]. Approval was not obtained. This AC cannot be verified until the approach is approved or corrected."
- Return findings to staff engineer; do not approve work with undisclosed substitutions

---

## Missing Marker Recovery

**Scenario:** An agent completes its work and returns, but the SubagentStop hook notification never arrives. The card remains in doing because no `KANBAN REVIEW` marker was emitted.

**What happened:** The hook cannot chain AC review without the marker. The agent finished its substantive work but skipped (or failed to emit) the marker that triggers the review pipeline.

**Detection:** If you expect a hook notification and it does not arrive within a reasonable time, check `kanban status <N>`. If the result is `doing`, the hook never received a marker — this is the missing marker case.

**What to do:**

1. **Check card status:** `kanban status <N>` — confirm it is still in doing
2. **Do NOT call `kanban review` yourself** — that command is triggered by the hook on the agent's behalf; a manual call would bypass the AC review chain
3. **Re-launch the agent** — same card, same model (it is already in doing, no `kanban redo` needed). The new agent reads prior work via `kanban show`, emits `KANBAN CRITERIA CHECK <N>` for any criteria already satisfied by prior work, then emits `KANBAN REVIEW` to trigger the hook

**Example:**
```
[No hook notification after agent returns]

You:
1. kanban status 42              # → "doing" — marker not emitted
2. [Re-launch agent for card #42 using same delegation template]

Agent (re-launched):
1. kanban show 42 --output-style=xml  # Reads prior work and AC
2. KANBAN CRITERIA CHECK 1            # Prior work already satisfied this
3. KANBAN CRITERIA CHECK 2            # Prior work already satisfied this
4. KANBAN REVIEW                      # Hook triggers AC review

[Hook notification arrives: "AC review complete — card #42 PASSED"]
```

**Anti-pattern:**
- Waiting indefinitely without checking card status
- Manually calling `kanban review` to advance the card (bypasses AC review chain)
- Calling `kanban criteria check` to fill in what the agent missed (agent_met must reflect the agent's own assessment)

---

## References

- See `delegation-guide.md` for permission handling and model selection
- See `parallel-patterns.md` for conflict detection and parallel safety
- See `review-protocol.md` for review workflows and approval criteria
- See staff-engineer.md for core protocols and card lifecycle
