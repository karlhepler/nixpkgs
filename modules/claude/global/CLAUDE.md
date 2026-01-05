# Claude Code Guidelines

> **📦 Available Tools:** See [TOOLS.md](./TOOLS.md) for complete list of installed packages and custom utilities.

## Tool Preferences

**CRITICAL: Use the modern replacements documented in TOOLS.md:**
- Use `rg` (ripgrep) instead of `grep` for searching
- Use `fd` instead of `find` for finding files
- Use `bat` instead of `cat` when syntax highlighting would be helpful
- Use custom git utilities (`git-branches`, `workout`, `git-sync`, etc.) when working with git
- Note: `htop` is available for interactive process viewing (not for scripting)

See [TOOLS.md](./TOOLS.md) for complete documentation of all available tools and utilities.

---

## ⚡ Essential Checklist (Check Before EVERY Task)

**STOP. Check ALL items BEFORE starting:**

- [ ] **Scope**: One deliverable only, no "while I'm here" additions
- [ ] **Why**: Can I explain rationale, trade-offs, and alternatives?
- [ ] **Security**: Input validation, secure defaults, threat model (if applicable)
- [ ] **Verification**: Search for third-party solutions first, read code, verify claims
- [ ] **Check-In**: Got approval for complex/multi-file changes?
- [ ] **Git**: Using `karlhepler/` prefix for any new branches?

**If ANY box is unchecked, STOP and address it first.**

**Not sure if a rule applies?** See detailed guidance in TIER 1/TIER 2 sections below.

---

## 📖 How to Use This Document

**Simple workflow for every task:**
1. Check **Essential Checklist** above (all 6 items)
2. Consult **TIER 1** sections for detailed guidance on checked items
3. Reference **TIER 2** sections as needed for specific patterns
4. Execute with confidence

**TIER 1 = Critical protocols** - Always follow when applicable
**TIER 2 = Best practices** - Apply these patterns for better results

---

# TIER 1: CRITICAL RULES 🔴
*These rules MUST be followed for every task*

---

## 🔴 Scope Discipline (CRITICAL)

### S.C.O.P.E. Protocol

- **Specific** task only
- **Confirm** understanding first
- **Only** what's requested
- **Prevent** "while I'm here" additions
- **Exact** deliverable defined

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

**"Non-trivial" means**:
- Affects >1 file OR >20 lines OR changes behavior
- Introduces new patterns or approaches
- When in doubt: Explain anyway

Then implement.

---

## 🔴 Security-First Protocol

**Security is non-negotiable. Every decision must consider security implications.**

### Security Checklist:

**Input Validation:**
- **Validate** at system boundaries (user input, API requests, file uploads)
- **Use** allowlists over denylists when possible
- **Sanitize** data before use in commands, queries, or rendering

**Authentication & Authorization:**
- **Never** trust client-side validation alone
- **Implement** proper session management
- **Use** principle of least privilege
- **Validate** permissions for every sensitive operation

**Data Protection:**
- **Never** log passwords, tokens, or sensitive data
- **Use** secure credential storage (environment variables, secret managers)
- **Encrypt** sensitive data at rest and in transit
- **Be careful** with file permissions

**Common Vulnerabilities (OWASP Top 10):**
- **SQL Injection:** Use parameterized queries
- **XSS:** Escape output, use CSP headers
- **Command Injection:** Avoid shell execution with user input
- **Path Traversal:** Validate and sanitize file paths
- **Insecure Dependencies:** Keep dependencies updated

### Threat Modeling for Larger Initiatives:

For multi-file changes or new features, consider:

1. **Attack Surface:** What new entry points are being created?
2. **Trust Boundaries:** Where does untrusted data enter the system?
3. **Data Flow:** How does sensitive data move through the system?
4. **Impact Assessment:** What's the worst case if this is compromised?
5. **Mitigations:** What security controls are in place?

Document findings in check-in format before proceeding.

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

### What Counts as "Complex"?

A change is complex if it meets ANY of these:
- **Affects** 3+ files
- **Architectural** or design decisions required
- **Wide impact** (multiple features, many users)
- **Database** schema modifications
- **API** contract changes
- **When in doubt**: Check in anyway (better safe than sorry)

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

## 🔴 Verification Protocol

**Trust but verify everything.**

**Before Acting:**
- Verify user claims match reality (read files, check APIs)
- Check actual file locations, function names, signatures
- Read source code to understand real vs assumed behavior
- Search for existing solutions (see Technology Selection)
- Investigate ALL potential causes, not just obvious ones

**During Action:**
- Verify each change works as intended
- Check for unintended side effects
- Follow established patterns

**After Action:**
- Verify final result matches requirements
- Check all edge cases
- Confirm scope maintained (no additions crept in)

---

## 🔴 Git Branch Naming Convention

**CRITICAL: ALL branches created by Claude MUST use the `karlhepler/` prefix.**

### Branch Naming Rules:

- **ALWAYS** prefix branch names with `karlhepler/`
- **Examples:**
  - ✓ `karlhepler/add-feature`
  - ✓ `karlhepler/fix-bug`
  - ✓ `karlhepler/tmp`
  - ✗ `add-feature` (missing prefix)
  - ✗ `feature/add-feature` (wrong prefix)

### When Creating Branches:

```bash
# Correct
git checkout -b karlhepler/feature-name

# Wrong
git checkout -b feature-name
```

**No exceptions.** Every branch Claude creates must follow this convention.

---

## 🔴 Pull Request Comment Handling

**When responding to PR comments, ALWAYS reply directly to the comment thread.**

### Critical Rules: The Three Nevers

**❌ NEVER add PR-level comments:**
```bash
gh pr comment <number> -b "response"  # WRONG - adds comment to whole PR
```

**❌ NEVER edit original comments:**
```bash
gh api repos/{owner}/{repo}/pulls/comments/{id} --method PATCH  # WRONG - modifies original
```

**❌ NEVER reply without critical evaluation:**
- Bots lack full codebase context - you have more information
- Humans have domain expertise - respect but verify their suggestions
- Read relevant code before accepting any recommendation
- Trust but verify: Check claims against actual implementation

### ✅ CORRECT: Direct Comment Reply

**Always use this approach:**
```bash
gh api --method POST \
  repos/{owner}/{repo}/pulls/{pr}/comments/{comment_id}/replies \
  -f body='Your reply message'
```

This creates a proper threaded reply visible in GitHub UI.

### Reply Content Guidelines

**Tone: Positive, Curious, Thankful**
- Be concise - no fluff or unnecessary elaboration
- Express genuine curiosity about suggestions
- Thank reviewers for their feedback
- Focus on substance over politeness theater

**Examples:**

✅ **Good replies:**
- "Good catch! Fixed in abc123. The issue was X because Y."
- "Thanks for the suggestion. After checking Z, I think W is better here because [reason]. Thoughts?"
- "Interesting point. I investigated and found [X]. Updated approach in commit abc123."
- "You're right - this overlooks [edge case]. Fixed in abc123."

❌ **Bad replies (too verbose/fluffy):**
- "Thank you so much for taking the time to review this! I really appreciate your thorough feedback. You make an excellent point about..."
- "I completely agree with you! This is a great suggestion and I'll definitely implement it right away. Thanks again!"

### Critical Evaluation Process

**For bot comments:**
1. **Read the code** - Bots don't see full context
2. **Evaluate the claim** - Is it actually a problem?
3. **Check for false positives** - Bots misunderstand intent
4. **Make judgment call** - You have more context
5. **Reply with reasoning** - Explain why action taken or not

**For human comments:**
1. **Take seriously** - Humans have domain knowledge
2. **Verify the claim** - Read code, check behavior
3. **Consider edge cases** - They might know something you don't
4. **Discuss if uncertain** - Ask clarifying questions
5. **Reply with context** - Show you understood and investigated

### PR Comment Review Workflow

**When asked to review PR comments:**

1. **Fetch unreplied comments:**
```bash
# Get current PR info
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
PR_NUM=$(gh pr view --json number -q .number)

# List all comments user hasn't replied to
gh api repos/$REPO/pulls/$PR_NUM/comments --paginate > /tmp/pr_comments.json
cat /tmp/pr_comments.json | jq -r '
  [.[] | select(.in_reply_to_id == null) | select(.user.login == "USERNAME" | not)] as $top |
  [.[] | select(.in_reply_to_id != null and .user.login == "USERNAME") | .in_reply_to_id] as $replied |
  $top[] | select(.id as $id | $replied | index($id) | not) |
  {id, author: .user.login, path, line: (.line // .original_position), body_preview: (.body | split("\n")[0])}
'
```

2. **For each unreplied comment:**
   - Read the comment body and code location
   - Determine if bot or human (check `user.login`)
   - Read relevant code for context
   - Critically evaluate the suggestion
   - Decide: Fix, Defer, or Reject
   - If fixing: implement, commit, push
   - Reply to comment with reasoning

3. **Reply directly to comment:**
```bash
gh api --method POST \
  repos/$REPO/pulls/$PR_NUM/comments/COMMENT_ID/replies \
  -f body='Concise reply explaining action taken'
```

4. **Verify replies:**
   - Check GitHub UI to ensure replies are threaded correctly
   - Never batch replies - handle each comment individually

### Common Gotchas

1. **Comment Types:** Three types exist on GitHub
   - Issue comments (PR-level) - `/repos/{owner}/{repo}/issues/{pr}/comments`
   - Review comments (inline code) - `/repos/{owner}/{repo}/pulls/{pr}/comments` ← Use this
   - Commit comments - Different endpoint

2. **Bot Detection:**
   - Username ends with `bot` or `[bot]`
   - Common: `dependabot[bot]`, `github-actions[bot]`, `cursor[bot]`, `claude-maze[bot]`
   - Use: `jq 'select(.user.login | test("bot$|\\[bot\\]"))'`

3. **Filtering Logic:**
   - Top-level comments: `select(.in_reply_to_id == null)`
   - Exclude your own: `select(.user.login == "USERNAME" | not)`
   - Check if replied: Cross-reference with replies where `in_reply_to_id` matches comment ID

4. **Shell Quoting:**
   - Use `select(.user.login == "USERNAME" | not)` not `select(.user.login != "USERNAME")`
   - The `!=` operator causes shell quoting issues
   - The `| not` pattern is more reliable

---

# TIER 2: IMPORTANT GUIDELINES 🟡
*Follow these patterns for better results*

---

## 🟡 Multiple Issues Debugging

**Core Rule:** Software problems are rarely single-cause.

### Investigation Process:

1. **Identify** first issue
2. **Search** for knock-on effects
3. **Look** for related problems in same area
4. **Check** dependencies and calling code
5. **Verify** no additional issues exist
6. **Report** ALL findings together

### Language Pattern:

- ✓ Say: "I found AN issue..." / "Here's ONE problem..."
- ✗ Don't say: "I found THE issue..." / "Here's THE problem..."

Always continue investigating after finding the first problem.

---

## 🟡 Technology Selection

**Prefer boring, battle-tested solutions over novel ones.**

### The Boring Technology Principle:

- Choose mature, well-understood technologies with proven track records
- Avoid bleeding-edge tools unless absolutely necessary
- Value stability, documentation, and community support
- "Boring" doesn't mean outdated—it means reliable and well-tested

**Why boring technology:**
- Fewer surprises and edge cases
- Better documentation and Stack Overflow answers
- More libraries, tools, and integrations
- Easier to hire for and onboard new developers
- Predictable performance characteristics

### Always Search for Third-Party Solutions First:

**Before building anything custom, search for:**
1. Standard library solutions
2. Well-maintained open-source libraries
3. Framework built-ins or official plugins
4. Battle-tested community solutions

**Build custom only when:**
- No existing solution meets core requirements
- Existing solutions are unmaintained or insecure
- Business logic is truly unique to the domain
- Cost/complexity of integration exceeds custom build

**When evaluating third-party solutions:**
- Check maintenance status (recent commits, active issues)
- Review security track record
- Assess community size and support
- Consider license compatibility
- Verify production usage at scale

**Questions to ask:**
- "Has someone already solved this problem?"
- "Is this really unique to our use case?"
- "What's the maintenance burden of custom vs third-party?"

---

## 🟡 Parallel Tool Calling

**Use parallel tool calling when operations are independent:**

- Multiple file reads
- Multiple searches
- Multiple bash commands that don't depend on each other
- Any operations with no dependencies between them

Execute them in a single message for speed.

---

## 🟡 Pull Request Descriptions

**PR descriptions must be concise and focus on intent, not implementation details.**

### Core Principles:

1. **Intent Over Implementation**: Describe WHY and WHAT you're trying to accomplish, not HOW the code does it
2. **End State Only**: Describe the final state of the changes, never the iterative journey
3. **Brevity**: Keep descriptions short and to the point

### ❌ WRONG: Describing the Journey

```markdown
## Summary
- Added feature X
- Then fixed bug Y that appeared
- Then refactored Z for clarity
- Then updated tests
- Then fixed linting issues
```

This describes the iterative development process, which is NOT what PR descriptions should contain.

### ❌ WRONG: Describing What Code Does

```markdown
## Summary
- Added new function `processData()` that takes an array and filters it
- Updated component to call `processData()` in useEffect hook
- Modified tests to cover new function
```

People can read the code to see what it does. This is redundant.

### ❌ WRONG: Too Verbose

Long, detailed descriptions with multiple paragraphs explaining every nuance and decision.

### ✅ CORRECT: Intent-Focused, Concise, End State

```markdown
## Summary
Enable users to filter dashboard data by date range to improve data analysis workflow.

## Why
Users need to focus on specific time periods without manually scrolling through all historical data.
```

**This describes**:
- WHAT: Enable filtering by date range
- WHY: Improve workflow, avoid manual scrolling
- FOR WHOM: Users analyzing data

### When Updating Existing PR Descriptions:

**NEVER add iterative updates** like:
- "Updated to fix CI errors"
- "Now addressing review feedback"
- "Fixed the bug mentioned above"

**ALWAYS replace** the entire description to reflect the current end state.

### PR Description Template:

```markdown
## Summary
[1-3 sentences describing WHAT you're enabling/fixing and WHY it matters]

## Why
[Brief explanation of the intent - the problem being solved or need being addressed]

## Test Plan
[Bulleted checklist of how to verify the changes work]
```

### Key Questions to Ask Yourself:

Before writing a PR description, ask:
1. "Why does this change matter?" (Intent)
2. "What capability are we adding/fixing?" (What)
3. "Who benefits and how?" (Why)

Do NOT ask:
- "What did I do first, second, third?" (Journey)
- "What functions did I add?" (Implementation)
- "How does the code work?" (Implementation)

---

## 🟡 Code Design Principles

**Always follow these design principles:**

### YAGNI (You Aren't Gonna Need It)
- Don't build features or abstractions until they're needed
- Solve the problem at hand, not hypothetical future problems
- Add complexity only when current requirements demand it

### KISS (Keep It Simple, Stupid)
- Choose the simplest solution that works
- Avoid clever code that's hard to understand
- Prefer clarity over brevity

### SOLID Principles
- **Single Responsibility:** Each component does one thing well
- **Open/Closed:** Extend behavior without modifying existing code
- **Liskov Substitution:** Subtypes must be substitutable for their base types
- **Interface Segregation:** Many specific interfaces beat one general interface
- **Dependency Inversion:** Depend on abstractions, not concretions

### Composition Over Inheritance
- Prefer composing small, focused components
- Use interfaces and dependency injection
- Avoid deep inheritance hierarchies

### Clean Architecture
- Separate business logic from infrastructure
- Dependencies point inward (toward business logic)
- Keep boundaries clear between layers
- Business rules should not depend on frameworks or databases

### Early Returns & Control Flow
- Prefer early returns over nested conditionals
- Use `continue` in loops to reduce nesting
- Handle edge cases and errors first, then main logic
- Reduce cognitive load by minimizing indentation levels

### DRY (Don't Repeat Yourself) - Loose Interpretation
- Eliminate meaningful duplication, not all duplication
- Balance DRY with clarity and simplicity
- Don't create abstractions until pattern repeats 3+ times
- Duplication is acceptable when abstraction adds complexity
- Prefer duplication over wrong abstraction

**When to apply DRY:**
- Business logic that changes together
- Complex algorithms used in multiple places
- Configuration that needs consistency

**When duplication is fine:**
- Similar-looking code with different purposes
- Code that may evolve independently
- Simple operations where abstraction obscures intent
