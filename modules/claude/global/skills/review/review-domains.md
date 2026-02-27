---
name: review-domains
description: Domain-specific focus instructions for specialist reviewers. Referenced by the /review skill. Not intended for direct invocation.
user-invocable: false
---

# Review Domain Focus Instructions

Include the appropriate block in each specialist's prompt under **Your Domain Focus ({domain}):**

**swe-backend:**
> N+1 queries, error handling patterns, input validation, API contract consistency, race conditions, data modeling soundness, transaction boundaries

**swe-frontend:**
> Accessibility (WCAG 2.1 AA), React performance (unnecessary re-renders, missing memo), bundle size impact, error boundaries, mobile responsiveness, keyboard navigation

**swe-security:**
> Auth/authz gaps, injection vectors (XSS, SQLi, path traversal), PII exposure, credential handling, OWASP Top 10, privilege escalation, SSRF

**swe-sre:**
> Timeout/retry/circuit-breaker patterns, observability gaps (logging/metrics/tracing), resource leaks, graceful degradation, health check coverage

**swe-devex:**
> CI/CD correctness and security (pinned actions), test coverage adequacy, dependency pinning, build safety, documentation accuracy

**swe-infra:**
> IAM least-privilege, resource sizing, HA considerations, secret management (no hardcoded secrets), idempotency of provisioning

**ai-expert:**
> Prompt injection risk, model selection justification, context window efficiency, output validation, token cost implications, prompt file structure quality
