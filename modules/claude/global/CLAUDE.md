# Claude Code Guidelines

> **Tools:** See [TOOLS.md](./TOOLS.md). Use `rg` not `grep`, `fd` not `find`, custom git utilities.

---

## Before EVERY Task

- [ ] **Scope**: One deliverable only - no "while I'm here" additions
- [ ] **Why**: Can I explain rationale and alternatives?
- [ ] **Check-In**: Got approval for complex/multi-file changes?
- [ ] **Git**: Using `karlhepler/` prefix for new branches?

**If ANY unchecked, STOP and address first.**

---

## Scope Discipline (CRITICAL)

**One task = one deliverable. NO EXCEPTIONS.**

❌ "I'll also optimize X while fixing the bug" / "While I'm here..."
✅ Implement ONLY what was asked. Mention improvements AFTER.

---

## Explain "Why" Before Non-Trivial Changes

For changes affecting >1 file, >20 lines, or behavior:
- Why this approach and trade-offs
- Alternatives considered

---

## Check-In Before Executing

**Required for:** 3+ files, architectural decisions, database/API changes.

**Format:**
```
Task: [What you're about to do]
Why: [Problem being solved]
Approach: [Your solution]
Changes: [Files affected]
Scope: This will ONLY change [X]. NOT [Y, Z].

Ready to proceed?
```

Wait for confirmation.

---

## Complex Requests

For multi-step/ambiguous requests, paraphrase understanding first.
Skip for simple commands ("Read file", "Run tests").

---

## Technology Selection

**Prefer boring, battle-tested solutions.** Search for existing solutions before building custom.
- Standard library first
- Well-maintained open-source libraries
- Build custom only when nothing else works

---

## PR Descriptions

**Focus on WHY and WHAT, not HOW.** Describe intent, not implementation.

❌ "Added function X, updated Y, fixed Z" (journey/implementation)
✅ "Enable users to filter data by date range" (intent/end state)

When updating, rewrite from scratch - never append.

---

## Git Branch Naming

**ALL branches MUST use `karlhepler/` prefix.**

✓ `karlhepler/feature-name`
✗ `feature-name` or `feature/name`

---

## PR Comment Replies

- Reply directly to threads (use `/replies` endpoint, NOT `gh pr comment`)
- Never reply if your reply is already last in thread
- Fix → commit → push → THEN reply (include commit SHA)
- End with: `---\n_💬 Written by [Claude Code](https://claude.ai/code)_`

See `/review-pr-comments` skill for full workflow.

---

## Programming Preferences

**Design:** SOLID, Clean Architecture, composition over inheritance, early returns

**Simplicity:** YAGNI (don't build until needed), KISS (simplest solution that works)

**Technology:** Prefer boring over novel, existing over custom

**DRY:** Eliminate meaningful duplication, but prefer duplication over wrong abstraction. Wait for 3+ repetitions before abstracting.

**Mindset:** Always Be Curious - investigate thoroughly, ask why, verify claims
