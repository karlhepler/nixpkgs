# Review Protocol

Detailed guidance for mandatory reviews, review workflows, and approval criteria.

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
# Agent moved card to review

# Staff Engineer: Check mandatory review table
# Match found: Infrastructure → Infra peer + Security required

# Step 1: Create review cards in TODO
kanban add "Review: IAM policy (Infrastructure peer)" \
  --persona "Infrastructure Engineer" \
  --status todo \
  --model sonnet

kanban add "Review: IAM policy (Security)" \
  --persona "Security Engineer" \
  --status todo \
  --model sonnet

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
# Agent completed migration, moved to review

# Staff Engineer: Check mandatory review table
# Match: Database schema (PII) → Peer backend + Security

# Create review cards, launch in parallel
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
# Agent completed implementation, moved to review

# Staff Engineer: Check mandatory review table
# Match: Auth/AuthZ → Security (MANDATORY) + Backend peer

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

---

## Approval Criteria by Domain

### Infrastructure Review Criteria

**Technical Correctness:**
- Valid syntax (Terraform, CloudFormation, K8s manifests)
- Resource references correct (no broken dependencies)
- Tested in non-prod environment

**Best Practices:**
- Least-privilege principle applied
- Resources tagged for cost tracking
- Idempotent (can run multiple times safely)

**Security:**
- No hardcoded credentials
- Encryption enabled (at rest, in transit)
- Network policies restrictive
- Audit logging enabled

**Maintainability:**
- Clear naming conventions
- Documented purpose (why this exists)
- Cleanup strategy (how to decommission)

### Database Review Criteria

**Schema Design:**
- Normalized appropriately (3NF where reasonable)
- Indexes on columns used in WHERE/JOIN
- Foreign keys enforce referential integrity
- Data types appropriate (not VARCHAR(255) for everything)

**Migration Safety:**
- Reversible (down migration provided)
- No data loss (backups taken)
- Performance tested (large tables handled)
- Zero-downtime if required (online schema change)

**PII Protection (if applicable):**
- Encryption at rest
- Access controls (least privilege)
- GDPR compliance (retention policy)
- Audit logging

### Security Review Criteria

**Authentication:**
- Strong credentials (hashed + salted passwords)
- Secure session management (httpOnly, secure flags)
- Token validation (signature, expiration)
- No credentials in code/logs

**Authorization:**
- Least-privilege principle
- Role-based access control
- No privilege escalation paths
- Default deny (whitelist, not blacklist)

**Data Protection:**
- PII encrypted (at rest, in transit)
- Input validation (prevent injection)
- Output encoding (prevent XSS)
- CSRF protection

**Attack Surface:**
- Rate limiting (prevent brute force)
- Audit logging (who, what, when)
- Error messages don't leak info
- Dependencies up-to-date (no known CVEs)

### Backend Review Criteria

**Code Quality:**
- Error handling comprehensive
- Tests cover happy path + edge cases
- No hardcoded values (use config)
- Logging appropriate (not too verbose, not too sparse)

**Performance:**
- Database queries efficient (no N+1)
- Caching where appropriate
- Async operations don't block
- Resource cleanup (connections closed)

**Integration:**
- API contracts clear (request/response schemas)
- Backwards compatibility maintained
- Versioning strategy followed
- Documentation updated

### Frontend Review Criteria

**User Experience:**
- Loading states (spinners, skeletons)
- Error messages helpful (not "Error 500")
- Accessibility (WCAG AA)
- Responsive (mobile, tablet, desktop)

**Code Quality:**
- Components reusable
- State management clear
- No prop drilling (use context if needed)
- Tests cover user interactions

**Performance:**
- Code splitting (lazy load routes)
- Images optimized
- Bundle size reasonable
- Lighthouse score acceptable

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

**Protocol:**
1. Skip reviews during exploration phase
2. Document that this is POC (not production-ready)
3. When transitioning to production → Full review required

**Rationale:** Reviews slow exploration. But production code needs rigor.

---

## Review Anti-Patterns

### ❌ Rubber Stamp Review

**Problem:** Reviewer approves without actually reviewing.

**Signs:**
- Review completed in seconds (complex change)
- Generic approval ("Looks good!")
- No specific feedback on what was verified

**Fix:** Require specific verification checklist in review result.

### ❌ Bikeshedding (Arguing Trivial Details)

**Problem:** Reviewers argue about style/naming while missing real issues.

**Signs:**
- Multiple rounds of review on variable names
- Functional issues not caught
- Review takes longer than implementation

**Fix:** Focus review on correctness, security, maintainability. Style is secondary.

### ❌ Review Purgatory (Never Completes)

**Problem:** Review drags on forever, work never ships.

**Signs:**
- Multiple review cycles with new issues each time
- Reviewer keeps finding "one more thing"
- Work is blocked for days/weeks

**Fix:** Set time limit for review (24-48 hours). If issues found, be specific. If work fundamentally wrong, reject early and restart.

### ❌ Missing the Forest for the Trees

**Problem:** Reviewer focuses on code style, misses security vulnerability.

**Signs:**
- Feedback on formatting, naming, comments
- No feedback on logic, security, edge cases
- Critical bug ships because review focused on trivia

**Fix:** Prioritize review checklist - correctness > security > performance > style.

---

## References

- See `delegation-guide.md` for permission handling and model selection
- See `parallel-patterns.md` for parallel review coordination
- See staff-engineer.md for mandatory review protocol table
