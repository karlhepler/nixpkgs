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

---

## Cross-Cutting: Composition Wiring and Lifecycle

**Apply these checks regardless of domain whenever a new endpoint, handler, or feature is being added. The orchestrator MUST append this entire section to every specialist's prompt in addition to their domain-focus block — it is not a replacement for the domain-focus line, and it must not be omitted for any specialist.**

### Production Composition Wiring

When a new endpoint or handler introduces a dependency (service, client, repository, middleware), verify that the **production composition** — the actual app bootstrap, DI container, router registration, or wiring layer — connects that dependency to the handler.

A green unit test that injects a mock of that dependency is not evidence the feature works end-to-end. The unit test proves the handler logic is correct in isolation; it says nothing about whether production composition wires the real dependency. Look for:

- The handler registered in the router/server setup
- The real dependency (not a mock) injected or constructed in the production entry point
- Any initialization, middleware registration, or feature-flag gate required to activate the code path

**Note for IoC/DI-container ecosystems (Spring, .NET DI, NestJS):** Production composition may be auto-wired via a DI module, decorator, or annotation rather than a hand-written entry point. In these cases, confirm the real dependency is activated (e.g., the module is imported, the annotation is present, the provider is registered) — not just that a specific wiring file changed.

If no diff touches the production composition and you cannot confirm the wiring already exists in the current codebase, flag it: the feature may be dead on arrival in production.

### Cross-Cutting Lifecycle Interactions

Trace process-lifecycle wiring for any code that touches signal handling, graceful shutdown, teardown sequences, or process-group behavior. Unit-level reviews routinely miss these because the interactions only manifest at runtime across component boundaries. Check:

- Signal handlers (SIGTERM, SIGINT, SIGHUP) — does a scoped restart or shutdown affect the whole process or just the intended scope?
- Teardown order — are resources (connections, workers, timers) torn down in a safe sequence? (e.g., closing a DB connection before active workers have flushed is an unsafe sequence)
- Process-group behavior — does a signal propagate to child processes or subprocesses in ways the author may not have intended? Check how the process is started (are child processes in the same process group?) and whether the signal handler uses a process-group kill `os.kill(-pid, sig)` vs. a single-process kill `os.kill(pid, sig)`.

These are cross-cutting concerns that do not appear in any single domain's diff — they require tracing the wiring end-to-end.
