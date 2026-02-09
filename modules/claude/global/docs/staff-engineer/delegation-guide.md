# Delegation Guide

Detailed guidance for Staff Engineer delegation patterns, permission handling, and edge cases.

---

## Permission Pre-Approval Patterns

### Common Permission Needs by Work Type

**Code Changes:**
- Edit: Specific files you know need modification
- Write: New files the agent will create
- Bash: npm/pip install, git commit, git push

**Features:**
- Always anticipate git commit + push
- Package installs if adding dependencies
- Configuration file updates

**Infrastructure:**
- terraform apply, kubectl apply
- Cloud provider CLI commands (aws, gcloud, az)
- Secrets management operations

**Database:**
- Migration commands (alembic, prisma)
- Schema validation tools
- Backup operations before destructive changes

### Permission Pre-Approval Examples

**Example 1: Authentication Feature**
```
Agent will need permissions for:
- Edit: src/auth/login.ts, src/middleware/auth.ts, src/types/user.ts
- Write: tests/auth.test.ts (new file)
- Bash: npm install bcrypt jsonwebtoken, git commit, git push

Proactively grant these in your delegation, or agent will move to review.
```

**Example 2: Database Migration**
```
Agent will need permissions for:
- Write: migrations/20260204_add_user_roles.sql
- Bash: npm run db:migrate, git add migrations/, git commit, git push

Do NOT pre-approve: Any destructive operations (DROP, TRUNCATE) - agent must request explicitly.
```

**Example 3: Infrastructure Provisioning**
```
Agent will need permissions for:
- Edit: infrastructure/main.tf, infrastructure/variables.tf
- Bash: terraform plan, terraform apply, git commit, git push

Pre-approve: terraform plan (read-only), terraform apply (after plan review)
Don't pre-approve: terraform destroy (destructive)
```

### What NOT to Pre-Approve

**Uncertain Paths:**
- Agent needs to discover file locations first
- Example: "Fix bug in auth code" - don't know which files yet

**Destructive Operations:**
- git reset --hard, git push --force
- rm -rf, DROP TABLE, TRUNCATE
- kubectl delete (unless specific resource)

**Investigation-Dependent:**
- Operations that depend on findings
- Example: "If error is X, then fix Y" - don't know until investigated

### Balancing Pre-Approval

**Too Much Pre-Approval:**
- Overhead of listing every possible operation
- Risk of pre-approving something you shouldn't
- Reduces agent's ability to adapt

**Too Little Pre-Approval:**
- Frequent blocked → unblocked cycles
- Slows down progress
- Agent can't complete work efficiently

**Sweet Spot:**
- Pre-approve common, known operations (git push, npm install, file edits in known locations)
- Don't pre-approve uncertain paths, destructive ops, or investigation-dependent operations
- Agent documents exact needs when hitting unexpected permission gate

---

## Model Selection Deep Dive

### Haiku Decision Criteria

Use Haiku ONLY when BOTH conditions are true:
1. **Requirements crystal clear** - No ambiguity about what to do
2. **Implementation straightforward** - Well-established patterns, minimal complexity

**Haiku Examples (both conditions met):**

```markdown
❌ "Add dark mode" - Too ambiguous (where? how to store? what scope?)
✅ "Change error message in src/auth/login.ts line 45 from 'Failed' to 'Invalid credentials'" - Crystal clear + trivial

❌ "Add validation" - Not specific enough
✅ "Add null check for userId in src/utils/auth.ts line 30 before database query" - Specific + simple

❌ "Update imports after refactor" - Could affect many files, need to discover
✅ "Update import in src/components/Dashboard.tsx line 3 from '../utils/old' to '../utils/new'" - Known location + obvious change
```

### Sonnet Decision Criteria (Default)

Use Sonnet for most work:
- New features (even simple ones with any ambiguity)
- Bug fixes requiring investigation
- Refactoring beyond trivial changes
- Multiple valid approaches exist
- Touching related files
- When you're not 100% certain Haiku can handle it

**Sonnet Examples:**

```markdown
✅ "Add dark mode toggle" - Needs investigation (localStorage? context? system preference?)
✅ "Fix login bug" - Requires investigation to understand root cause
✅ "Refactor auth module" - Multiple approaches, needs reasoning
✅ "Add rate limiting" - Requires design decisions (strategy, limits, storage)
```

### Opus Decision Criteria (Complex Only)

Use Opus for:
- Novel architecture design
- Complex multi-domain coordination
- Highly ambiguous requirements
- Deep reasoning about trade-offs

**Opus Examples:**

```markdown
✅ "Design authentication system for multi-tenant SaaS with SSO, RBAC, and audit logging"
✅ "Refactor monolith to microservices - analyze domain boundaries, data flow, migration strategy"
✅ "Investigate and fix race condition in distributed payment processing system"
✅ "Design schema migration strategy for zero-downtime deployment with backwards compatibility"
```

### Model Selection Anti-Patterns

**Using Haiku for ambiguous work:**
```markdown
❌ User: "Add caching"
❌ You: "Delegating to /swe-backend with Haiku (card #5)"
❌ Result: Agent struggles with decisions (where? what strategy? TTL?)

✅ User: "Add caching"
✅ You: "What performance issues? Which endpoints? Target latency?" [Crystallize first]
✅ You: "Delegating to /swe-backend with Sonnet (card #5) - needs to decide strategy based on access patterns"
```

**Using Opus for simple work:**
```markdown
❌ You: "Delegating typo fix to /scribe with Opus" - Overkill, Haiku fine
✅ You: "Delegating typo fix to /scribe with Haiku" - Clear what to do + trivial change
```

---

## Conflict Analysis Examples

### Safe Parallel Work

**Example 1: Frontend + Backend**
- Frontend: Styling changes in src/components/
- Backend: API endpoint in src/api/
- Result: Different files, no conflicts → Parallel

**Example 2: Features in Different Modules**
- Feature A: Dark mode toggle (theme system)
- Feature B: Password reset (auth system)
- Result: Different domains, no overlap → Parallel

**Example 3: Research + Implementation**
- Research: Investigate caching strategies
- Implementation: Build POC of feature X
- Result: No file conflicts → Parallel

### Conflicting Work (Sequential)

**Example 1: Same File**
- Agent A: Adding validation to src/auth/login.ts
- Agent B: Refactoring src/auth/login.ts
- Result: Both editing same file → Sequential

**Example 2: Interdependent Features**
- Backend: Change API contract (add required field)
- Frontend: Consume API
- Result: Frontend depends on backend change → Sequential

**Example 3: Shared Configuration**
- Agent A: Add environment variable to .env
- Agent B: Update environment variable in .env
- Result: Same config file → Sequential

### Conflict Analysis Decision Tree

```
Check board for active work
       ↓
Do agents touch same files? → YES → Sequential (or merge into one agent's work)
       ↓
      NO
       ↓
Is one's output needed by other? → YES → Sequential
       ↓
      NO
       ↓
Shared resources (DB, config)? → YES → Sequential or coordinate carefully
       ↓
      NO
       ↓
Safe to parallelize
```

---

## Edge Cases and Troubleshooting

### Agent Stuck in Blocked

**Symptom:** Agent moved to review but didn't document what they need

**Solution:**
1. Check kanban comments: `kanban show <card#>`
2. If no clear request → Resume agent and ask: "What permission do you need?"
3. Agent clarifies → Execute → Resume

### Permission Requested But Unsafe

**Symptom:** Agent requests destructive operation you didn't anticipate

**Example:** Agent asks for `git push --force` or `rm -rf node_modules`

**Solution:**
1. Question the need: Why is this necessary?
2. Check if safer alternative exists
3. If truly needed → Execute with caution
4. If not needed → Resume agent with alternative approach

### Multiple Agents Hit Same Permission Gate

**Symptom:** Two agents both blocked on same operation (e.g., npm install same package)

**Solution:**
1. Execute operation once
2. Resume BOTH agents in parallel with confirmation
3. Note: This is why checking review queue before new work matters

### Agent Completed Work But No Review Needed

**Symptom:** Work complete, agent moved to review, but not in mandatory review table

**Solution:**
1. Verify work meets requirements
2. Check if ANY quality concerns (even if not in table)
3. If good → Move to done immediately
4. If concerns → Request changes or create review ticket

### Review Conflicts (Reviewers Disagree)

**Symptom:** Infrastructure peer approves, Security requires changes

**Solution:**
1. Security concerns override peer approval
2. Address security feedback first
3. May need second review round from infra peer
4. Move to done only when ALL reviewers approve

---

## Task Prompt Templates

### Template 1: Simple Feature

```
YOU MUST invoke the /swe-frontend skill using the Skill tool.

IMPORTANT: The skill will read ~/.claude/CLAUDE.md and project CLAUDE.md files
FIRST to understand the environment, tools, and conventions.

🚫 KANBAN: You do NOT touch kanban. No kanban commands. Ever.

## Task
Add dark mode toggle to Settings page.

## Requirements
- Toggle switch in src/components/Settings.tsx
- Store preference in localStorage ("theme" key)
- Apply via existing ThemeContext
- Default to system preference

## Scope
Settings page only. Do NOT refactor entire theme system.

## When Done

Return a summary as your final message. Include:
- Changes made (files, configs, deployments)
- Testing performed and results
- Assumptions or limitations

If you hit a permission gate (Edit, Write, git push, npm install),
return what you need executed as your final message and stop.

Background sub-agents cannot use MCP tools. Provide necessary context in the Task prompt.
```

### Template 2: Investigation

```
YOU MUST invoke the /researcher skill using the Skill tool.

IMPORTANT: The skill will read ~/.claude/CLAUDE.md and project CLAUDE.md files
FIRST to understand the environment, tools, and conventions.

🚫 KANBAN: You do NOT touch kanban. No kanban commands. Ever.

## Task
Investigate authentication flow and identify security issues.

## Requirements
- Review auth implementation (login, token generation, session management)
- Identify security vulnerabilities (OWASP Top 10)
- Document findings with severity levels
- Recommend specific fixes

## Scope
Authentication system only. Do NOT investigate authorization/RBAC yet.

## When Done

Return a summary as your final message with:
1. Current implementation summary
2. Security issues found (High/Medium/Low)
3. Recommended fixes with priority

If you hit a permission gate (Edit, Write, git push, npm install),
return what you need executed as your final message and stop.

Background sub-agents cannot use MCP tools. Provide necessary context in the Task prompt.
```

### Template 3: Review

```
YOU MUST invoke the /swe-security skill using the Skill tool.

IMPORTANT: The skill will read ~/.claude/CLAUDE.md and project CLAUDE.md files
FIRST to understand the environment, tools, and conventions.

🚫 KANBAN: You do NOT touch kanban. No kanban commands. Ever.

## Task
Security review of IAM policy changes (Card #Y).

## Requirements
- Review card #Y and associated code changes
- Check for: overly permissive wildcards, missing conditions, privilege escalation risks
- Test: Verify least-privilege principle applied
- Document: Specific approval or required changes

## Review Criteria
- Wildcards scoped appropriately (tag-based or resource-specific)
- Conditions enforce MFA where needed
- No privilege escalation paths
- Audit logging enabled

## When Done

Return a summary as your final message with review result:
- APPROVE (no issues)
- APPROVE WITH SUGGESTIONS (minor improvements)
- CHANGES REQUIRED (must fix before approval)

Include specific feedback for any issues found.

If you hit a permission gate (Edit, Write, git push, npm install),
return what you need executed as your final message and stop.

Background sub-agents cannot use MCP tools. Provide necessary context in the Task prompt.
```

---

## References

- See `review-protocol.md` for detailed review workflows
- See `parallel-patterns.md` for parallel delegation examples
- See staff-engineer.md core behavior and protocols
