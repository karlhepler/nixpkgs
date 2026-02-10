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
- [ ] **🚨 NO HOMEBREW**: Not suggesting brew install ANYTHING?

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

4. **Web search** - ONLY when above sources don't have what you need
   - Triangulate with multiple sources
   - Verify credibility and recency
   - Last resort, not first option

**Why this order:** Start with the most specific, authoritative sources (project context) before reaching for general external sources. This ensures consistency with project conventions and reduces noise.

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

**12 Factor App:** Follow [12factor.net](https://12factor.net) methodology for building robust, scalable applications

**DRY:** Eliminate meaningful duplication, but prefer duplication over wrong abstraction. Wait for 3+ repetitions before abstracting.

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
