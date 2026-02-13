# Claude Code Guidelines

> **Tools:** See [TOOLS.md](./TOOLS.md). Use `rg` not `grep`, `fd` not `find`, custom git utilities.

> **Context7 MCP:** Always use Context7 MCP when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.

> **🚨 NEVER HOMEBREW 🚨** STOP. Do NOT suggest, install, or mention Homebrew. Ever. Use Nix (nixpkgs/nixpkgs-unstable) or direct binary downloads ONLY.

---

## Before EVERY Task

- [ ] **Scope**: One deliverable only - no "while I'm here" additions
- [ ] **Why**: Can I explain rationale and alternatives?
- [ ] **Check-In**: Got approval for complex/multi-file changes?
- [ ] **Git**: Using `karlhepler/` prefix for new branches?
- [ ] **🚨 NO HOMEBREW**: Not suggesting OR mentioning brew install ANYWHERE?

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

## Research Priority Order

When researching, investigating, or looking up information, ALWAYS follow this priority order:

1. **CLAUDE.md files** - Global (`~/.claude/CLAUDE.md`) and project-specific (`./CLAUDE.md`)
   - Contains project conventions, tools, workflows, and preferences
   - Most authoritative for "how we do things here"

2. **Local docs/ folder** - Check for `docs/`, `doc/`, `documentation/` in the repo
   - Project-specific documentation
   - Architecture decisions, API references, setup guides

3. **Context7 MCP** - For library/API documentation, framework usage, setup steps
   - Authoritative, up-to-date documentation
   - Faster and more reliable than blog posts
   - Use for external library or framework questions
   - **🚨 WARNING**: External docs may suggest Homebrew - ALWAYS translate to Nix

4. **Web search** - ONLY when above sources don't have what you need
   - Triangulate with multiple sources
   - Verify credibility and recency
   - Last resort, not first option

**Why this order:** Start with the most specific, authoritative sources (project context) before reaching for general external sources. This ensures consistency with project conventions and reduces noise.

---

## Glossary

**Agent:** A Claude Code instance executing work (the AI itself)

**Sub-agent:** A background agent spawned via Task tool to handle delegated work

**Skill:** A specialized capability loaded via Skill tool (markdown file in `~/.claude/commands/`)

**Session ID:** 8-character hex identifier for Claude session (e.g., `08a88ad2`). Automatically injected at startup. Use with `--session` flag on kanban commands.

**Card:** Kanban board work item with action (what), intent (why), and acceptance criteria (definition of done)

**Work Card:** Card where AC verifies file changes (implementations, fixes, modifications)

**Review Card:** Card where AC verifies information returned (analysis, findings, recommendations)

## Skill Invocation

When skills are invoked, the `$ARGUMENTS` placeholder (commonly seen at line 8-9 of skill files) is replaced at runtime with the specific task prompt provided by the coordinator.

**Example:**
```
## Your Task

$ARGUMENTS

*This placeholder is replaced with your specific instructions when the skill is invoked.*
```

Skills receive the full task context through this mechanism, so they have all necessary information to complete their work.

---

## Model Selection

Choose the right Claude model for the task based on complexity and ambiguity:

| Model | When to Use | Cost | Speed | Capability | Examples |
|-------|-------------|------|-------|------------|----------|
| **Haiku** | Well-defined AND straightforward | $ | Fastest | Basic | Fix typo, add null check, update import, run simple command |
| **Sonnet** | Most work, any ambiguity | $$ | Medium | Strong | New features, refactoring, investigation, multi-step tasks |
| **Opus** | Novel/complex/highly ambiguous | $$$ | Slowest | Best | Architecture design, multi-domain coordination, complex debugging |

### Decision Rules

**Use Haiku when BOTH are true:**
- ✅ Requirements are crystal clear (no interpretation needed)
- ✅ Implementation is straightforward (no design decisions)

**Use Sonnet (default) when:**
- Any ambiguity in requirements OR implementation
- Multi-step tasks that require planning
- Code that requires understanding context
- Investigation or analysis work
- **When in doubt** → Always choose Sonnet

**Use Opus when:**
- Novel problems without established patterns
- Multiple valid approaches requiring architectural decisions
- High-stakes work requiring maximum capability
- Complex debugging across multiple systems

### Common Mistakes

❌ **"It's a small change, use Haiku"** - Size ≠ complexity. One-line IAM policy can grant root access.
❌ **"We need it fast, use Haiku"** - Rework from wrong approach takes longer than Sonnet.
❌ **"Save costs, use Haiku"** - Failed work costs more than the model difference.

### Examples

**Haiku:**
- Fix typo in README
- Add single null check to function
- Update import statement
- Simple git command (`git status`)

**Sonnet:**
- Add new API endpoint with validation
- Refactor authentication flow
- Investigate performance bottleneck
- Write tests for complex logic

**Opus:**
- Design new authentication architecture
- Coordinate work across frontend, backend, and infrastructure
- Debug subtle race condition in distributed system
- Evaluate multiple architectural approaches

### For Coordinators (Staff Engineer, Ralph)

When delegating work via Task tool:
- Specify `model: haiku` only when requirements are unambiguous AND implementation is trivial
- Use `model: sonnet` as default (safer choice)
- Use `model: opus` for architectural or highly complex work
- If unsure between Haiku and Sonnet → Choose Sonnet

---

## MCP Integration

**Context7 MCP** - Authoritative documentation lookup for libraries and frameworks.

**How to use:**
- For library/framework docs: "Use Context7 MCP to lookup React Server Components best practices"
- For API references: "Use Context7 MCP to lookup NextJS 15 app router API"

**When it fails:**
- Fall back to WebSearch for official documentation
- Prefer official docs over blog posts/tutorials
- Always verify information from multiple sources

**Configuration:**
- Automatically enabled if `CONTEXT7_API_KEY` set in `overconfig.nix`
- Check status: Context7 will be available if configured, no manual setup needed
- To disable: Remove `CONTEXT7_API_KEY` from overconfig.nix, run `hms`

**Available via:**
- `mcp__context7__resolve-library-id` - Find library ID
- `mcp__context7__query-docs` - Query documentation

---

## Technology Selection

**Prefer boring, battle-tested solutions.** Search for existing solutions before building custom.
- Standard library first
- Well-maintained open-source libraries
- Build custom only when nothing else works

---

## 🚨 PACKAGE INSTALLATION: NEVER HOMEBREW 🚨

**CRITICAL: This is a Nix-managed system. Homebrew is FORBIDDEN.**

### What NOT to Do

❌ **NEVER suggest:**
```bash
brew install colima
brew install docker
brew install anything
```

❌ **NEVER say:**
- "Install via Homebrew..."
- "You can use brew install..."
- "The easiest way is brew..."
- "Homebrew provides..."

❌ **NEVER suggest as fallback:**
- "If Nix doesn't work, try Homebrew..."
- "Alternatively, you could use brew..."
- "As a workaround, brew install..."

### What TO Do Instead

✅ **For system-wide tools** → Add to Nix:
```nix
# modules/packages.nix
home.packages = with pkgs; [
  colima  # Docker runtime
  jq      # JSON processor
];
```

✅ **For programmatic installation** → Direct binary download:
```bash
# In hms.bash or activation scripts
curl -fsSL "https://example.com/releases/latest/binary" -o "$HOME/.local/bin/tool"
chmod +x "$HOME/.local/bin/tool"
```

✅ **For language packages** → Language-specific managers:
```bash
npm install -g package-name  # Node packages
pip install package-name     # Python packages (within venvs)
```

### Why This Matters

Homebrew breaks Nix's reproducibility guarantees:
- Installs to `/opt/homebrew/` (outside Nix control)
- Version conflicts with Nix packages
- Not declared in configuration (invisible dependencies)
- Breaks when switching Nix generations

**If you catch yourself typing "brew" → STOP and use Nix instead.**

### Self-Check Before Responding

Before suggesting ANY package installation:
1. Does my response contain the word "brew" or "homebrew"? → REWRITE
2. Am I quoting external docs that mention Homebrew? → TRANSLATE to Nix
3. Am I suggesting a fallback? → STOP, suggest Nix or direct download only

---

## PR Descriptions

Two questions. That's all a PR description answers:

1. **Why does this exist?** — What goal, project, or problem does it serve?
2. **What happens when it merges?** — What effect does it have?

Reviewers read the code for everything else.

### Format

```
## Why

[One paragraph. What larger goal or project this contributes to. Why now. Include ticket refs naturally.]

## What This Does

[One paragraph. What the PR enables. What to expect after merge. High-level only.]

---
🤖 Generated with [Claude Code](https://claude.ai/claude-code)
```

*For trivial changes (typos, comment fixes, formatting), both sections still apply but compress into one short paragraph. Never omit the "Why"—even trivial changes have a reason.*

### Visual Rules

- **Scannable in 10 seconds** — A reviewer grasps the PR at a glance
- **Short paragraphs** — 2-4 sentences per section, never walls of text
- **Let it breathe** — Whitespace between sections, no visual clutter
- **No bullet hell** — If you have more than 3 bullets, you're over-explaining

### Do NOT Include

- "Changes" sections with file-by-file breakdowns
- Test plans or checklists
- Implementation details or code snippets
- Lists of files added/modified/deleted
- "Key deliverables" bullet lists
- Step-by-step "Next Steps" procedures

Reviewers have the diff. They don't need it narrated.

### Updating PR Descriptions

When updating a PR description, **rewrite from scratch**. The description reflects the end state of the PR as it exists now — not the history of how it got there.

- ❌ "Originally implemented X, then upgraded to Y"
- ❌ "Added Z after review feedback"
- ❌ Appending new paragraphs about recent changes

- ✅ Describe the PR as if it was written in one clean pass
- ✅ Reflect the current HEAD, not the commit history
- ✅ Every update is a full rewrite of both sections

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

**Design:** SOLID, Clean Architecture, composition over inheritance, early returns, avoid deeply nested if statements (use guard clauses for flat code structure)

**Function Quality:** Keep functions reasonably sized - not tiny, but not huge. Single responsibility per function. Extract helpers when logic gets complex.

**Simplicity:** YAGNI (don't build until needed), KISS (simplest solution that works)

**Technology:** Prefer boring over novel, existing over custom

**12 Factor App:** Follow [12factor.net](https://12factor.net) methodology for building robust, scalable applications

**DRY:** Eliminate meaningful duplication, but prefer duplication over wrong abstraction. Wait for 3+ repetitions before abstracting.

**Bash/Shell Conventions:**
- Environment variables: ALL_CAPS_WITH_UNDERSCORES (e.g., `KANBAN_SESSION`, `CONTEXT7_API_KEY`)
- Script-local variables: lowercase_with_underscores (e.g., `card_number`, `output_file`)
- **Error handling:** Use `set -euo pipefail` at script start for fail-fast behavior
  - `-e`: Exit immediately if any command returns non-zero status
  - `-u`: Treat unset variables as errors
  - `-o pipefail`: Pipeline fails if any command in the pipeline fails (not just the last one)

**Mindset:** Always Be Curious - investigate thoroughly, ask why, verify claims

---

## Dangerous Operations (Require User Permission)

**CRITICAL: Claude Code must NEVER run these commands without explicit user approval.**

These operations are destructive and cannot be undone. Always ask the user for permission BEFORE running them.

**Commands requiring permission:**
- `kanban clean` - Deletes cards from kanban board (prompts user for confirmation)
- `kanban clean --expunge` - Deletes cards AND scratchpad contents (prompts user for confirmation)
- `kanban clean <column>` - Deletes cards from specific column (prompts user for confirmation)
- `hms --expunge` - Removes stale Home Manager generations (dangerous)
- `git reset --hard` - Discards local changes permanently
- `git push --force` - Overwrites remote history
- `rm -rf` commands - Permanent file deletion

**When user requests these operations:**
1. Explain what the command will do
2. Ask for explicit confirmation
3. Only proceed after receiving approval
4. Include the command in your response for transparency
