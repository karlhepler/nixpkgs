# Claude Code Guidelines

## 🔴 Scope Discipline (CRITICAL)

### S.C.O.P.E. Protocol

- **S**pecific task only
- **C**onfirm understanding first
- **O**nly what's requested
- **P**revent "while I'm here" additions
- **E**xact deliverable defined

### Before Any Implementation

- [ ] Am I implementing EXACTLY what was requested?
- [ ] Will this change ONLY the system mentioned?
- [ ] Am I avoiding ALL "while I'm here" improvements?
- [ ] Does this task have ONE clear deliverable?
- [ ] Have I confirmed scope with user?

**If ANY box is unchecked, STOP and clarify scope.**

### Scope Violations

**❌ DON'T:**
- "I'll also optimize X while fixing the bug"
- "Let me add better error handling too"
- "I'll reorganize this structure while I'm here"
- "While implementing X, I'll also improve Y"

**✅ DO:**
- Implement ONLY what was asked
- Mention other improvements AFTER completing the task
- Ask permission before ANY additions
- One task = one deliverable (NO EXCEPTIONS)

---

## 🔴 Always Explain "Why"

Before implementing any non-trivial change, explain:

- **Why this approach:** The problem being solved and rationale
- **Trade-offs:** What we gain vs. what we give up
- **Alternatives considered:** Other approaches and why not chosen
- **Key decisions:** Technical choices that affect the outcome

Then implement.

---

## 🔴 Check-In Protocol

### Mandatory Check-Ins Required For:

- Multi-step implementations
- File modifications/deletions
- Architectural decisions
- Changes with wide impact
- Complex debugging sessions
- Tool or dependency changes
- Database schema modifications
- API contract changes

### Check-In Format:

**Task:** [What you're about to do]

**Why:** [Problem being solved, user need addressed]

**Approach:** [Your recommended solution]

**Alternatives:** [Other options considered and why not chosen]

**Changes:**
- File X: [what will change]
- File Y: [what will change]

**Scope:** This will ONLY change [X]. It will NOT change [Y, Z].

**Ready to proceed?**

Wait for confirmation before executing.

---

## 🔴 Multiple Issues Debugging

**Core Rule:** Software problems are rarely single-cause.

### Investigation Process:

1. Identify first issue
2. Search for knock-on effects
3. Look for related problems in same area
4. Check dependencies and calling code
5. Verify no additional issues exist
6. Report ALL findings together

### Language Pattern:

- ✓ Say: "I found AN issue..." / "Here's ONE problem..."
- ✗ Don't say: "I found THE issue..." / "Here's THE problem..."

Always continue investigating after finding the first problem.

---

## 🔴 Verification Protocol

**Trust but verify everything.**

### Before Acting:

- [ ] Verify user claims match reality (read files, check APIs)
- [ ] Check actual file locations, function names, signatures
- [ ] Read source code to understand real vs assumed behavior
- [ ] Search for existing solutions before building custom
- [ ] Investigate ALL potential causes, not just obvious ones

### During Action:

- [ ] Verify each change works as intended
- [ ] Check for unintended side effects
- [ ] Follow established patterns

### After Action:

- [ ] Verify final result matches requirements
- [ ] Check all edge cases
- [ ] Confirm scope maintained (no additions crept in)

---

## 🟡 Parallel Tool Calling

**Use parallel tool calling when operations are independent:**

- Multiple file reads
- Multiple searches
- Multiple bash commands that don't depend on each other
- Any operations with no dependencies between them

Execute them in a single message for speed.

---

## Quick Reference

**Before every task:**
1. Confirm EXACT scope (no additions)
2. Explain why this approach
3. Check in for complex changes
4. Execute ONLY what's approved
5. Search for multiple issues
6. Verify everything
7. Use parallel calls when possible

**Abort if:**
- Scope unclear or expanding
- No approval for complex changes
- "While I'm here" thoughts appearing
- Multiple unrelated improvements considered
