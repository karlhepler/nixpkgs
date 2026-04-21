# Review Protocol

Detailed guidance for mandatory reviews, review workflows, and approval criteria.

---

## Mandatory Review Tiers (Detailed)

**Check BEFORE marking any card done.** If work matches → MUST create review cards.

### 🚨 Tier 1: ALWAYS MANDATORY - STOP AND CREATE REVIEWS

**IF card involves ANY of these, STOP IMMEDIATELY. CREATE review cards. DO NOT MARK DONE until reviews approve.**

- **Prompt files** (output-styles/\*.md, agents/\*.md, skills/\*\*/SKILL.md, CLAUDE.md, hooks/\*.md)
  → CREATE: AI Expert review card (two-part: delta + full prompt adherence)
  → **Model selection:** Sonnet by default for full-file audits; Opus only for large (20+ line) or architectural deltas. See [staff-engineer.md](../../output-styles/staff-engineer.md) for details.

- **Auth/AuthZ** (login, permissions, tokens, sessions, roles, access control)
  → CREATE: Security review + Backend peer review cards

- **Financial/billing** (payments, pricing, subscriptions, invoices, charges)
  → CREATE: Finance review + Security review cards

- **Legal docs** (ToS, privacy policy, contracts, GDPR, licensing)
  → CREATE: Lawyer review card

- **Infrastructure** (Kubernetes, Terraform, cloud resources, IaC)
  → CREATE: Infra peer review + Security review cards

- **Database with PII** (tables with emails, names, SSN, addresses, phone, payment info)
  → CREATE: Backend peer review + Security review cards

- **CI/CD changes** (GitHub Actions, build scripts, deployment pipelines, hooks)
  → CREATE: DevEx peer review + Security review cards

**After creating review cards, WAIT for approvals. Check review queue in next board check.**

### 🔒 Tier 2: HIGH-RISK INDICATORS - LIKELY MANDATORY

**IF card has ANY of these keywords/patterns, CREATE reviews (better safe than sorry):**

- **"API", "endpoint", "route", "REST", "GraphQL"**
  → CREATE: Backend peer review (add Security if work mentions PII/auth/payments)

- **"third-party", "integration", "webhook", "API key", "external service"**
  → CREATE: Backend review + Security review (add Legal if mentions PII/payments)

- **"performance", "optimization", "caching", "query", "N+1"**
  → CREATE: SRE review + Backend peer review

- **"migration", "ALTER TABLE", "schema change", "database"**
  → CREATE: Backend review + Security review (if work involves user data)

- **"npm update", "dependency", "package.json", "major version", "CVE"**
  → CREATE: DevEx review + Security review

- **"shellapp", "bash script", ".bash", "activation", "hook"**
  → CREATE: DevEx review (add Security if script handles credentials/tokens)

**Rule:** Match keywords → create reviews. User can cancel reviews if low-risk. Better over-review than miss critical issues.

### 💡 Tier 3: STRONGLY RECOMMENDED (NOT BLOCKING)
- Technical docs → Domain peer + Scribe
- UI components → UX + Visual + Frontend peer
- Monitoring/alerting → SRE peer
- Multi-file refactors → Domain peer

---

## Mandatory Review Deep Dive

### Why These Require Reviews

**Infrastructure:**
- **Risk:** Misconfigured IAM = privilege escalation, data breach
- **Why peer + security:** Peer validates technical correctness, Security validates security posture
- **Example failure:** Overly permissive S3 bucket policy exposed customer data

**Database Schema (PII):**
- **Risk:** PII exposed, GDPR violations, data breach
- **Why peer + security:** Peer validates schema design, Security validates PII protection
- **Example failure:** Unencrypted PII column, missing access controls

**Auth/AuthZ:**
- **Risk:** Authentication bypass, privilege escalation, session hijacking
- **Why security + peer:** Security validates attack surface, Peer validates implementation
- **Example failure:** JWT signature not verified, session fixation vulnerability

**API with PII:**
- **Risk:** PII leaked in responses, insufficient access controls
- **Why peer + security:** Peer validates API design, Security validates data exposure
- **Example failure:** API returned PII without authentication check

**CI/CD (credentials):**
- **Risk:** Credentials leaked in logs, insufficient secret rotation
- **Why peer + security:** Peer validates pipeline design, Security validates secret handling
- **Example failure:** API key committed to repo, exposed in build logs

**Financial/Billing:**
- **Risk:** Financial fraud, incorrect charges, compliance violations
- **Why finance + security:** Finance validates business logic, Security validates fraud prevention
- **Example failure:** Race condition allowed double-charging, no idempotency

---

## Review Workflow Examples

### Example 1: Infrastructure Change (Parallel Reviews)

**Setup:**
```bash
# Original work complete (Card #42: "Update IAM policy for S3 access")
# Agent returned with completion summary

# Staff Engineer: Check mandatory review table
# Match found: Infrastructure → Infra peer + Security required

# Step 1: Create review cards in TODO
kanban todo '{"action":"Review IAM policy (Infrastructure peer)","intent":"Validate technical correctness","persona":"Infrastructure Engineer","model":"sonnet","criteria":["Valid IAM syntax","Best practices followed","Tested in non-prod"]}'

kanban todo '{"action":"Review IAM policy (Security)","intent":"Validate security posture","persona":"Security Engineer","model":"sonnet","criteria":["No overly permissive wildcards","MFA enforced","Audit logging enabled"]}'

# Step 2: Launch BOTH reviewers in parallel (same message)
```

**Review Criteria - Infrastructure Peer:**
- Technical correctness (valid IAM syntax, resource references)
- Best practices (least privilege, condition enforcement)
- Maintainability (clear naming, documented purpose)
- Testing (validated in non-prod first)

**Review Criteria - Security:**
- No overly permissive wildcards (`*` scoped appropriately)
- Conditions enforce MFA where needed
- No privilege escalation paths
- Audit logging enabled (CloudTrail)

**Possible Outcomes:**

**Outcome A: Both Approve**
```
Infra Peer (Card #43): APPROVE - Policy follows least-privilege, tested in staging
Security (Card #44): APPROVE - Wildcards scoped to specific tags, MFA enforced

Staff Engineer: Moves Card #42 to done, notifies user
```

**Outcome B: One Requires Changes**
```
Infra Peer (Card #43): APPROVE WITH SUGGESTION - Consider adding resource tags for better tracking
Security (Card #44): CHANGES REQUIRED - Wildcard in line 15 too broad (s3:*/*), must scope to specific bucket

Staff Engineer: Addresses security concern (higher priority), then optional infra suggestion
```

**Outcome C: Conflicting Feedback**
```
Infra Peer (Card #43): APPROVE - Resource wildcards necessary for dynamic bucket creation
Security (Card #44): CHANGES REQUIRED - Wildcards too permissive, must scope tighter

Staff Engineer: Security concerns override. Explore alternative approaches:
- Option 1: Tag-based scoping (secure + flexible)
- Option 2: Explicit bucket list (secure but rigid)
- Consult with user on acceptable trade-off
```

---

### Example 2: Database Schema with PII (Sequential After Parallel Reviews)

**Setup:**
```bash
# Card #50: "Add customer_email column to orders table"
# Agent completed migration and returned summary

# Staff Engineer: Check mandatory review table
# Match: Database schema (PII) → Peer backend + Security

# Create review cards
kanban todo '{"action":"Review customer_email migration (Backend peer)","intent":"Validate schema design","persona":"Backend Engineer","model":"sonnet","criteria":["Schema design sound","Migration reversible","Performance acceptable"]}'

kanban todo '{"action":"Review customer_email migration (Security)","intent":"Validate PII protection","persona":"Security Engineer","model":"sonnet","criteria":["PII encrypted","Access controls correct","GDPR compliant"]}'

# Launch in parallel
```

**Review Criteria - Backend Peer:**
- Schema design (normalization, indexes, foreign keys)
- Migration safety (reversible, no data loss)
- Performance impact (index on new column if queried)
- Application code updated (ORM models, queries)

**Review Criteria - Security:**
- PII protection (encryption at rest, encryption in transit)
- Access controls (who can query this column)
- GDPR compliance (right to be forgotten, data retention)
- Audit logging (who accessed PII, when)

**Outcome: Changes Required, Then Second Review**
```
Backend Peer (Card #51): APPROVE WITH MINOR FIX - Add index on email for lookups
Security (Card #52): CHANGES REQUIRED - Email must be encrypted at rest (use pgcrypto or application-level encryption)

Staff Engineer: Addresses security concern, requests re-review
Agent: Implements encryption, updates migration, moves to review again
Staff Engineer: Creates second security review (Card #55)
Security (Card #55): APPROVE - Encryption implemented correctly, key management secure
Staff Engineer: Moves Card #50 to done
```

---

### Example 3: Auth Feature (Security Mandatory, Not Optional)

**Setup:**
```bash
# Card #60: "Implement JWT authentication"
# Agent completed implementation and returned summary

# Staff Engineer: Check mandatory review table
# Match: Auth/AuthZ → Security (MANDATORY) + Backend peer

# Create review cards
kanban todo '{"action":"Review JWT auth (Security)","intent":"Validate authentication security","persona":"Security Engineer","model":"sonnet","criteria":["Token generation secure","Signature verified","Session management secure"]}'

kanban todo '{"action":"Review JWT auth (Backend peer)","intent":"Validate code quality","persona":"Backend Engineer","model":"sonnet","criteria":["Error handling comprehensive","Tests cover edge cases","Integration sound"]}'

# CRITICAL: Security review is blocking, not optional
```

**Review Criteria - Security (MANDATORY):**
- Token generation (strong secret, sufficient entropy)
- Token validation (signature verified, expiration checked)
- Session management (secure storage, logout clears token)
- Attack surface (no JWT in URL, httpOnly cookies)
- Common vulnerabilities (OWASP Auth issues)

**Review Criteria - Backend Peer:**
- Code quality (error handling, tests)
- Integration (works with existing auth middleware)
- Performance (token validation efficient)

**Outcome: Security Blocks Until Fixed**
```
Security (Card #61): CHANGES REQUIRED (BLOCKING)
1. JWT secret in code (line 45) - MUST use environment variable
2. No signature verification (line 67) - CRITICAL vulnerability
3. Tokens never expire (line 30) - MUST set expiration

Backend Peer (Card #62): APPROVE WITH SUGGESTION - Add rate limiting to prevent brute force

Staff Engineer: Security issues are BLOCKING. Cannot ship until fixed.
Agent: Fixes critical issues, moves to review for re-review
Security (Card #65): APPROVE - Critical vulnerabilities fixed, ready to ship
Staff Engineer: Moves Card #60 to done
```

---

## Review Result Formats

### APPROVE (No Issues)
```
APPROVE - Work meets all requirements and review criteria.

Verified:
- [Specific aspect 1 checked]
- [Specific aspect 2 checked]
- [Specific aspect 3 checked]

No issues found. Ready to ship.
```

### APPROVE WITH SUGGESTIONS (Optional Improvements)
```
APPROVE WITH SUGGESTIONS - Work is acceptable as-is, but consider these improvements:

Verified: [What's good]

Suggestions (optional):
1. [Improvement 1] - Why: [Benefit]
2. [Improvement 2] - Why: [Benefit]

Decision: Can ship now or implement suggestions in follow-up work.
```

### APPROVE WITH MINOR FIX (Quick Fix Required)
```
APPROVE WITH MINOR FIX - Work is mostly good, one small issue to address:

Verified: [What's good]

Required Fix:
- [Specific issue] at [Location] - Change [X] to [Y]

Why: [Reason this matters]

After fix: No need for re-review, can complete immediately.
```

### CHANGES REQUIRED (Must Fix Before Approval)
```
CHANGES REQUIRED - Work has issues that must be addressed before approval.

Issues Found:
1. [Issue 1] at [Location]
   - Current: [What it does now]
   - Required: [What it should do]
   - Why: [Impact/risk]

2. [Issue 2] at [Location]
   - Current: [What it does now]
   - Required: [What it should do]
   - Why: [Impact/risk]

Next Steps: Address issues above, then request re-review.
```

### BLOCK (Critical Issues, Cannot Ship)
```
BLOCK (CRITICAL) - Work has critical security/safety issues. Must fix before proceeding.

🚨 CRITICAL ISSUES:
1. [Critical Issue 1]
   - Risk: [What could go wrong]
   - Impact: [Severity - data breach, downtime, etc.]
   - Fix: [Specific remediation]

2. [Critical Issue 2]
   - Risk: [What could go wrong]
   - Impact: [Severity]
   - Fix: [Specific remediation]

DO NOT SHIP until these are resolved. Requires re-review after fixes.
```

For domain-specific review criteria, rely on the specialist agent — each agent's skill covers its own domain criteria.

---

## Handling Review Conflicts

### Peer Approves, Cross-Cutting Concern Blocks

**Priority:** Cross-cutting concerns (Security, Finance) override peer approval.

**Example:**
```
Infra Peer: APPROVE - Terraform code is clean, tested, follows conventions
Security: BLOCK - Hardcoded AWS credentials in line 45, S3 bucket public

Resolution: Fix security issues FIRST, then re-review from security.
Infra peer approval still valid (code quality not affected by security fix).
```

### Multiple Reviewers Require Different Changes

**Priority:** Address blocking issues first, then suggestions.

**Example:**
```
Security: CHANGES REQUIRED - Add rate limiting to prevent abuse
Backend Peer: APPROVE WITH SUGGESTION - Consider caching to reduce load

Resolution:
1. Implement rate limiting (required for security approval)
2. Discuss caching with user (optional, can be follow-up work)
3. Re-review from security after rate limiting added
```

### Reviewers Disagree on Approach

**Resolution:** Staff engineer facilitates discussion, makes final call.

**Example:**
```
Infra Peer: "Use RDS for relational data"
Backend Peer: "Use DynamoDB for flexibility"

Staff Engineer:
1. Clarify use case with user (access patterns, scale, consistency needs)
2. Consult both reviewers on trade-offs
3. Make decision based on requirements
4. Document rationale for future reference
```

---

## When to Skip Reviews (Edge Cases)

### Hotfix in Production Emergency

**Scenario:** Critical bug in production, revenue impacted, need to ship NOW.

**Protocol:**
1. Ship fix immediately (prioritize availability)
2. Create review tickets AFTER fix deployed
3. Retroactive review validates fix, identifies improvements
4. Follow-up work addresses any issues found

**Rationale:** Availability > process in true emergencies. But still review afterward to prevent future issues.

### Trivial Changes (Documentation, Typos)

**Scenario:** Fix typo in README, update docs

**Protocol:**
1. Check if change could have security implications (e.g., typo in security docs = misleading guidance)
2. If truly trivial → Skip review, just verify correctness
3. If ANY doubt → Review as normal

**Rationale:** Don't slow down low-risk work. But when in doubt, review.

### Experimental/POC Work

**Scenario:** Building proof-of-concept, won't ship to production yet

**Exception: Tier 1 reviews (auth/authz, financial, infra, PII database, CI/CD, prompt files) are mandatory regardless of POC status — safety reviews don't wait for production.**

**Protocol:**
1. Skip reviews during exploration phase (except Tier 1 — see above)
2. Document that this is POC (not production-ready)
3. When transitioning to production → Full review required

**Rationale:** Reviews slow exploration. But production code needs rigor.

See anti-patterns.md for AC-review-specific failures.

---

## Prompt File Reviews

Prompt files (output-styles/\*.md, agents/\*.md, skills/\*\*/SKILL.md, CLAUDE.md, hooks/\*.md) require AI Expert review in two distinct parts. Both parts must complete before approving the work card.

### Part 1: Delta Review

Evaluate only the specific changes made. The goal is to verify the edits are sound in isolation before examining the whole.

**Audit checklist — Delta Quality:**

- [ ] **Clarity**: Are the new/changed instructions unambiguous? Could they be interpreted multiple ways?
- [ ] **Consistency**: Do changes use the same terminology, tone, and formatting as the rest of the file?
- [ ] **Integration**: Do changes fit naturally with surrounding content, or do they create friction?
- [ ] **Examples**: If examples were added/changed, are they concrete, accurate, and non-misleading?
- [ ] **Anti-patterns**: If anti-patterns were added, are they actually wrong (not just style preference)?
- [ ] **Decision trees / checklists**: Are conditions mutually exclusive and collectively exhaustive?
- [ ] **No new contradictions**: Do any new instructions conflict with existing instructions in the file?
- [ ] **Goal achieved**: Do the changes accomplish their stated purpose?

**Model selection — Part 1:**
- Haiku: delta is small and clearly bounded (a few lines, explicit location, no architectural changes)
- Sonnet: default for all other delta reviews

### Part 2: Full-File Quality Audit

Re-read the entire file and evaluate against current Claude best practices. Small deltas can mask accumulated technical debt — this audit catches issues that exist independent of the specific changes.

**Audit checklist — Full-File Best Practices:**

**Structure and organization:**
- [ ] Critical instructions are front-loaded (Claude weighs early content more heavily)
- [ ] Sections have clear, descriptive headers
- [ ] Logical flow: context → rules → examples → edge cases
- [ ] No orphaned sections that don't connect to the overall purpose

**Instruction quality:**
- [ ] Instructions describe outcomes (WHAT), not just implementation steps (HOW) where appropriate
- [ ] Language is precise and unambiguous throughout — no vague directives ("be better", "handle carefully")
- [ ] Active voice, present tense preferred
- [ ] No contradicting instructions anywhere in the file (e.g., "always do X" in one section, "avoid X" in another)

**Examples and anti-patterns:**
- [ ] Examples are concrete and representative of real scenarios
- [ ] Anti-pattern examples clearly illustrate why they fail
- [ ] Before/after comparisons are meaningfully different (not just cosmetic)
- [ ] Examples don't accidentally model bad behavior

**Claude 4.x compatibility:**
- [ ] Avoids instructing Claude to use `<thinking>` tags to trigger extended thinking (extended thinking is an API parameter, not XML markup)
- [ ] No "AI slop" patterns in example outputs (overly enthusiastic language, generic praise, emoji overuse)
- [ ] Communication style guidance reflects Claude 4.6 directness (concise, fact-based, active voice)

**Prompt hygiene:**
- [ ] No duplicate instructions across sections
- [ ] No stale content that references removed features or outdated workflows
- [ ] Decision criteria are unambiguous (no "use judgment" where a rule would work)
- [ ] Length is proportional to purpose — no over-documentation of trivial behaviors

**Model selection — Part 2:**
- Sonnet: default — most prompt files have been reviewed many times; a small delta audit is an iteration, not a fresh review
- Opus: only when the delta is large (20+ lines) or architectural — new sections added, major restructure, or core behavior changes

### Review Result Format for Prompt Files

Return findings from both parts together:

```
PART 1 — DELTA REVIEW: [APPROVE / CHANGES REQUIRED]

Delta assessment: [Specific analysis of the changes]

Issues (if any):
- [Issue] at [Location]: [Current] → [Required]. Why: [Impact]

PART 2 — FULL-FILE AUDIT: [APPROVE / CHANGES REQUIRED]

Overall assessment: [1-2 sentence summary]

Issues (if any):
- [Issue] at [Section/Line]: [What's wrong and why it matters]

Verdict: [APPROVE both parts / CHANGES REQUIRED — address before marking done]
```

---

## Post-Review Decision Flow

When review cards complete, the staff engineer must examine findings before proceeding. This is not optional — even non-blocking findings require a user decision.

### Step-by-Step Process

**Step 1: Collect all review outcomes**

Read every completed review card. Categorize each finding:
- **Blocking**: Cannot ship — security vulnerability, broken functionality, critical correctness issue
- **Non-blocking**: Can ship — suggestion, minor improvement, style preference
- **Approved clean**: No issues found

**Step 2: Determine overall status**

| Outcome | Action |
|---------|--------|
| All approved clean | Surface summary to user, proceed to commit/PR |
| Non-blocking findings only | Surface findings to user — "Fix now or proceed as-is?" |
| Any blocking finding | Surface findings to user — cannot proceed until addressed |

**Step 3: Surface findings to user**

Format the finding summary clearly:
- State the finding (what was found)
- State the severity (blocking or non-blocking)
- State the options (fix now, defer to follow-up, proceed as-is)
- Ask for a decision

Do NOT make the code quality decision yourself. Do NOT silently proceed past findings. Do NOT assume non-blocking means proceed.

**Step 4: Execute user decision**

| User decision | Staff engineer action |
|---------------|----------------------|
| Fix now | Create new work card for the fix, add review card if needed, complete before marking original done |
| Proceed as-is | Mark original card done, note findings in completion summary |
| Defer to follow-up | Create new todo card capturing the finding, mark original done |

**Step 5: Close the loop**

After the user decides, confirm action taken: "Proceeding as-is. Marked #42 done. Findings noted in summary." or "Created #47 to address the security finding before shipping."

### Example 1: All Reviews Approve (Clean Pass)

```
Work card #88: "Add --dry-run flag to deploy script"
Review cards:
  #89 (DevEx peer): APPROVE — Flag implemented correctly, help text clear, no side effects
  #90 (Security): APPROVE — No credential exposure, dry-run properly isolated from production

Staff engineer to user:
"Both reviews approved with no issues. Deploy script now has --dry-run support.
Ready to commit and push?"
```

User says yes → commit, push, mark #88 done.

### Example 2: Non-Blocking Finding (User Decides)

```
Work card #72: "Update kanban output-style prompt for compact XML"
Review cards:
  #73 (AI Expert - Delta): APPROVE — Changes are clear and consistent
  #74 (AI Expert - Full Audit): APPROVE WITH SUGGESTIONS
    - Section ordering puts examples before rules (suboptimal for Claude 4.x front-loading)
    - Duplicate instruction in §Output Format and §Board Check sections (minor)
    - No blocking issues

Staff engineer to user:
"Reviews complete. Card #74 flagged two non-blocking items:
1. Example placement: Examples appear before rules — Claude 4.x benefits from front-loading rules first
2. Duplicate instruction: Output format rules appear in two sections

Both are non-blocking — the prompt works as-is. Options:
A. Fix now (I'll create a card, ~15 min)
B. Proceed as-is (ship now, address later)
C. Defer (I'll create a todo card for cleanup)

Which do you prefer?"
```

User chooses B → Mark #72 done. Note findings in completion summary.
User chooses A → Create work card #77 for fixes, create review card #78, complete both before marking #72 done.
User chooses C → Create todo card #77 ("Clean up output-style prompt non-blocking findings from #74"), mark #72 done.

### Example 3: Blocking Finding (Cannot Proceed)

```
Work card #65: "Add OAuth token refresh to API client"
Review cards:
  #66 (Backend peer): APPROVE WITH SUGGESTION — Add retry backoff on 429 responses
  #67 (Security): CHANGES REQUIRED (BLOCKING)
    - Refresh tokens stored in localStorage (vulnerable to XSS)
    - No token expiry validation before use
    - CRITICAL: Must fix before shipping

Staff engineer to user:
"Security review (#67) flagged blocking issues that prevent shipping:
1. Token storage: Refresh tokens in localStorage are vulnerable to XSS — must use httpOnly cookies or secure server-side storage
2. Missing expiry check: Tokens used without validating expiry first — can send expired tokens to API

Backend peer (#66) approved with one non-blocking suggestion (retry backoff on 429s).

Security issues must be addressed before this ships. I'll create a work card to fix the blocking items.
Should I also include the retry backoff fix (non-blocking) in the same card, or handle it separately?"
```

Staff engineer creates work card for security fixes, security re-review card. After re-review approves, surfaces to user to confirm ship.

### Common Mistakes

**Silently ignoring non-blocking findings:**
Staff engineer must surface ALL findings — the user decides what to do, not the coordinator.

**Proceeding past blocking findings:**
A blocking finding is not a suggestion. It stops the current work until resolved or the user explicitly accepts the risk.

**Creating fix work without user approval:**
Even obvious fixes require user awareness. "I'll just fix it" is a scope decision that belongs to the user.

**Conflating reviewer suggestions with requirements:**
"APPROVE WITH SUGGESTIONS" means the work is shippable. Suggestions are optional improvements, not required changes.

---

## References

- See `delegation-guide.md` for permission handling and model selection
- See `parallel-patterns.md` for parallel review coordination
- See [`staff-engineer.md`](../../output-styles/staff-engineer.md) for quick-reference tier checklist
