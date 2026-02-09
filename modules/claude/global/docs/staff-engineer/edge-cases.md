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
- **Check acceptance criteria** - `kanban show <card#>` to see which AC are satisfied
- **For satisfied AC** - Check them off: `kanban criteria check <card#> <n>`
- **For remaining items** - Two paths:
  - **Resume work**: `kanban redo <card#>`, new agent picks up remaining unchecked AC
  - **Follow-up card**: If scope changed, create new card with remaining work
- **Never mark done with unchecked AC** - The CLI enforces this

**Example:**
```
Agent returns: "Completed API endpoint and tests. Hit permission gate for deployment."

You:
1. kanban review 20  # Move to review
2. kanban show 20    # Check AC
3. kanban criteria check 20 1  # "API endpoint implemented"
4. kanban criteria check 20 2  # "Tests passing"
5. AC #3 "Deployed to staging" still unchecked
6. Execute deployment (permission gate)
7. kanban criteria check 20 3  # Now all AC checked
8. kanban done 20 'JWT auth implemented, tested, deployed'
```

**Anti-pattern:**
- Moving directly from doing to done (skipping review)
- Not checking off satisfied AC before redo
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

## References

- See `delegation-guide.md` for permission handling and model selection
- See `parallel-patterns.md` for conflict detection and parallel safety
- See `review-protocol.md` for review workflows and approval criteria
- See staff-engineer.md for core protocols and card lifecycle
