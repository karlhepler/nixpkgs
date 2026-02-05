# Parallel Delegation Patterns

Detailed examples and coordination strategies for parallel delegation.

---

## Core Principle

**Multiple Task calls in SAME message = parallel execution**
**Sequential messages = sequential execution**

---

## Pattern 1: Multiple Reviewers on Same Work

**When:** Work complete and requires multiple perspectives (most common use case).

### Example 1: Infrastructure Change → Infra Peer + Security

**Scenario:** Updated IAM policy for S3 bucket access. Need technical validation + security validation.

**Steps:**
```bash
# Step 1: Create review cards in TODO
kanban add "Review: IAM policy (Infrastructure peer)" \
  --persona "Infrastructure Engineer" \
  --status todo \
  --model sonnet

kanban add "Review: IAM policy (Security)" \
  --persona "Security Engineer" \
  --status todo \
  --model sonnet

# Step 2: Launch BOTH reviewers in SAME message (parallel)
# First Task call (Infrastructure peer)
Task tool:
  subagent_type: general-purpose
  model: sonnet
  run_in_background: true
  prompt: |
    YOU MUST invoke the /swe-infra skill using the Skill tool.
    **Your kanban card is #51.**

    ## Task
    Review IAM policy changes (Card #50).

    [Full review instructions...]

# Second Task call (Security) - SAME MESSAGE
Task tool:
  subagent_type: general-purpose
  model: sonnet
  run_in_background: true
  prompt: |
    YOU MUST invoke the /swe-security skill using the Skill tool.
    **Your kanban card is #52.**

    ## Task
    Review IAM policy changes (Card #50).

    [Full review instructions...]

# Step 3: Move original card to REVIEW
kanban move 50 review

# Step 4: Wait for BOTH to approve, THEN move to done
```

**Why Parallel:** Reviews are independent - Security doesn't need to wait for Infra peer.

---

### Example 2: Database Migration with PII → Backend Peer + Security

**Scenario:** Adding customer_email column to orders table. Need schema validation + PII protection validation.

**Steps:**
```bash
# Create review cards
kanban add "Review: orders table migration (Backend peer)" \
  --persona "Backend Engineer" \
  --status todo \
  --model sonnet

kanban add "Review: orders table migration (Security)" \
  --persona "Security Engineer" \
  --status todo \
  --model sonnet

# Launch in parallel (same message)
# Backend peer reviews schema design, migration safety
# Security reviews PII protection, encryption, access controls

# Move original to review, wait for both approvals
```

**Why Parallel:** Both reviewers can work simultaneously - checking different aspects.

---

### Example 3: Auth Feature → Security + Backend Peer

**Scenario:** Implemented JWT authentication. Need security validation + code quality validation.

**Steps:**
```bash
# Create review cards
kanban add "Review: JWT auth (Security)" \
  --persona "Security Engineer" \
  --status todo \
  --model sonnet

kanban add "Review: JWT auth (Backend peer)" \
  --persona "Backend Engineer" \
  --status todo \
  --model sonnet

# Launch in parallel
# Security checks: token generation, validation, session management, attack surface
# Backend checks: code quality, error handling, tests, integration
```

**Why Parallel:** Security and code quality reviews are independent concerns.

---

## Pattern 2: Independent Implementation Tasks

**When:** Multiple features/changes that don't conflict (rare - usually not recommended for implementation).

### Example 1: Frontend Styling + Backend API (Different Files)

**Scenario:** User wants dark mode toggle AND new password reset endpoint.

**Conflict Analysis:**
- Dark mode: Touches src/components/Settings.tsx, src/context/ThemeContext.tsx
- Password reset: Touches src/api/auth.ts, src/services/email.ts
- Result: Different files, no overlap → Safe to parallelize

**Steps:**
```bash
# Create cards
kanban add "Dark mode toggle" --persona "Frontend Engineer" --status doing --model sonnet
kanban add "Password reset API" --persona "Backend Engineer" --status doing --model sonnet

# Launch in parallel (same message)
Task tool:
  subagent_type: general-purpose
  model: sonnet
  run_in_background: true
  prompt: |
    YOU MUST invoke the /swe-frontend skill.
    **Your kanban card is #60.**
    [Dark mode task...]

Task tool:
  subagent_type: general-purpose
  model: sonnet
  run_in_background: true
  prompt: |
    YOU MUST invoke the /swe-backend skill.
    **Your kanban card is #61.**
    [Password reset task...]
```

**Why Parallel:** Different domains, different files, no dependencies.

**Warning:** Most implementation should be sequential unless you're certain no conflicts exist.

---

### Example 2: Research + POC (Independent Work)

**Scenario:** User wants to explore caching strategies while building a POC feature.

**Conflict Analysis:**
- Research: No file changes, investigating options
- POC: Building experimental feature in separate branch
- Result: No conflicts → Safe to parallelize

**Steps:**
```bash
kanban add "Research caching strategies" --persona "Researcher" --status doing --model sonnet
kanban add "Build POC for feature X" --persona "Fullstack Engineer" --status doing --model sonnet

# Launch in parallel
# Researcher investigates Redis, Memcached, in-memory options
# Engineer builds POC with placeholder caching
# Results converge when research informs POC implementation
```

**Why Parallel:** Research and POC are independent until you need to apply findings.

---

## Pattern 3: Cross-Domain Reviews (High-Impact Work)

**When:** Work impacts multiple domains and needs validation from each.

### Example 1: Payment Processing → Backend + Security + Finance

**Scenario:** Implemented new payment processing flow with Stripe integration.

**Why Multiple Reviewers:**
- Backend peer: Technical correctness, error handling, integration
- Security: Payment data handling, PCI compliance, fraud prevention
- Finance: Business logic, refund handling, reconciliation

**Steps:**
```bash
# Create review cards
kanban add "Review: Payment flow (Backend)" --persona "Backend Engineer" --status todo --model sonnet
kanban add "Review: Payment flow (Security)" --persona "Security Engineer" --status todo --model sonnet
kanban add "Review: Payment flow (Finance)" --persona "Finance" --status todo --model sonnet

# Launch ALL THREE in parallel (same message)
# Each reviewer focuses on their domain expertise
# All must approve before moving to done
```

**Why Parallel:** Reviews are independent - Finance doesn't need to wait for Backend.

---

### Example 2: CI/CD Pipeline with Secrets → DevEx + Security

**Scenario:** Updated GitHub Actions workflow to deploy to production with AWS credentials.

**Why Multiple Reviewers:**
- DevEx peer: Pipeline design, testing strategy, deployment flow
- Security: Secret management, credential rotation, least privilege

**Steps:**
```bash
kanban add "Review: CI/CD pipeline (DevEx)" --persona "DevEx Engineer" --status todo --model sonnet
kanban add "Review: CI/CD pipeline (Security)" --persona "Security Engineer" --status todo --model sonnet

# Launch in parallel
# DevEx validates workflow efficiency and testing coverage
# Security validates secret handling and access controls
```

**Why Parallel:** Technical and security reviews are orthogonal concerns.

---

## Pattern 4: UI Review (Marketing + Visual + Frontend Peer)

**When:** Frontend work needs business perspective + design perspective + technical perspective.

### Example: Landing Page Redesign

**Why Multiple Reviewers:**
- Marketing: Messaging clarity, conversion optimization, brand alignment
- Visual Designer: Design consistency, visual hierarchy, accessibility
- Frontend Peer: Code quality, performance, responsive design

**Steps:**
```bash
# Create review cards
kanban add "Review: Landing page (Marketing)" --persona "Marketing" --status todo --model sonnet
kanban add "Review: Landing page (Visual Designer)" --persona "Visual Designer" --status todo --model sonnet
kanban add "Review: Landing page (Frontend peer)" --persona "Frontend Engineer" --status todo --model sonnet

# Launch ALL THREE in parallel
# Marketing checks: Clear value prop, compelling CTA, SEO considerations
# Visual Designer checks: Visual consistency, typography, color usage
# Frontend checks: Code quality, bundle size, Lighthouse score
```

**Why Parallel:** Business, design, and technical reviews are independent.

---

## Anti-Patterns (When NOT to Parallelize)

### ❌ Anti-Pattern 1: Sequential Dependencies

**Problem:** Feature B depends on Feature A's output.

**Example:**
```bash
# WRONG - Parallel when sequential needed
Task: "Backend: Change API to return user roles"
Task: "Frontend: Display user roles in UI"

# Problem: Frontend can't implement until API contract is clear
```

**Fix:**
```bash
# CORRECT - Sequential
Task: "Backend: Change API to return user roles"
# Wait for completion
# Then:
Task: "Frontend: Display user roles in UI"
```

---

### ❌ Anti-Pattern 2: Same File Edits

**Problem:** Two agents editing same file simultaneously.

**Example:**
```bash
# WRONG - Parallel edits to same file
Task: "Add validation to src/auth/login.ts"
Task: "Refactor error handling in src/auth/login.ts"

# Problem: Merge conflicts, one agent's work overwrites the other
```

**Fix:**
```bash
# CORRECT - Sequential or combine into one agent's work
Task: "Add validation AND refactor error handling in src/auth/login.ts"
# Or:
Task: "Add validation to src/auth/login.ts"
# Wait for completion
Task: "Refactor error handling in src/auth/login.ts"
```

---

### ❌ Anti-Pattern 3: Shared Configuration Files

**Problem:** Multiple agents modifying same config (package.json, .env, docker-compose.yml).

**Example:**
```bash
# WRONG - Both touching package.json
Task: "Add React Query dependency"
Task: "Add Jest testing framework"

# Problem: Both run npm install and modify package.json simultaneously
```

**Fix:**
```bash
# CORRECT - Sequential or combine
Task: "Add React Query AND Jest dependencies"
# Or:
Task: "Add React Query"
# Wait
Task: "Add Jest"
```

---

## Coordination Strategies

### Strategy 1: Review Board Before Delegating

**Check active work:**
```bash
kanban list --show-mine        # See all work across sessions
kanban doing --show-mine       # See in-progress work
```

**Analyze conflicts:**
- Same files being edited?
- Shared configuration files?
- One depends on other's output?
- Shared resources (database, API)?

**Decision:**
- **No conflicts** → Parallel (launch in same message)
- **Conflicts detected** → Sequential (wait for completion) or combine into one agent

---

### Strategy 2: Clear Contracts for Parallel Work

**If parallelizing, ensure contracts are clear:**

**Example: Backend API + Frontend UI in parallel**
```bash
# Step 1: Define API contract FIRST (with user)
User: "API should return { userId, roles: string[], permissions: string[] }"
Staff Engineer: "Got it. Backend will implement that exact contract, Frontend will consume it."

# Step 2: Launch in parallel with contract documented in BOTH tasks
Task (Backend):
  ## API Contract (MUST MATCH)
  GET /api/user/me
  Response: { userId: string, roles: string[], permissions: string[] }

Task (Frontend):
  ## API Contract (MUST MATCH)
  GET /api/user/me
  Response: { userId: string, roles: string[], permissions: string[] }

# Both agents implement their side of the contract independently
```

---

### Strategy 3: Conflict Detection Heuristics

**Ask these questions:**

1. **File overlap?** → If agents touch same files → Sequential
2. **Data dependency?** → If one needs other's output → Sequential
3. **Shared config?** → If both modify package.json/.env/etc → Sequential
4. **Resource contention?** → If both deploy to same environment → Sequential
5. **Independent domains?** → Different files, different systems → Parallel

**Decision tree:**
```
ANY YES above? → Sequential
ALL NO? → Parallel
```

---

## Parallel Review Checklist

Before launching parallel reviews, verify:

- [ ] **Original work is complete** - Agent finished, moved to review
- [ ] **Mandatory review table checked** - Know which reviewers are required
- [ ] **Review cards created in TODO** - One card per reviewer
- [ ] **Review prompts prepared** - Each reviewer knows what to check
- [ ] **All Task calls in SAME message** - Not sequential messages
- [ ] **Original card moved to review** - Waiting for reviews
- [ ] **User notified** - "Reviews running in parallel, will update when complete"

---

## Measuring Parallel Effectiveness

**Metrics to track:**

1. **Time saved:** Sequential reviews take 2x time, parallel cuts in half
2. **Conflict rate:** How often do parallel reviews disagree? (Low = good contracts)
3. **Rework rate:** How often does parallel work cause merge conflicts? (High = bad parallelization decisions)

**Example:**
```
Sequential (2 reviews):
  Review 1: 15 minutes
  Review 2: 15 minutes
  Total: 30 minutes

Parallel (2 reviews):
  Both reviews: max(15, 15) = 15 minutes
  Total: 15 minutes
  Time saved: 50%
```

---

## References

- See `delegation-guide.md` for permission handling and model selection
- See `review-protocol.md` for detailed review workflows and approval criteria
- See staff-engineer.md for core delegation protocol and kanban management
