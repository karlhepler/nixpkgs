# Claude Code Guidelines

> **Tools:** See [TOOLS.md](./TOOLS.md). **🚨 Use `rg` not `grep`, `fd` not `find`** (see § Use `rg` and `fd`). Custom git utilities available.

> **Context7 MCP:** When working with external libraries/frameworks, query Context7 MCP for authoritative documentation before implementing. See § Research Priority Order for full details, including background sub-agent constraints.

> **🚨 NEVER HOMEBREW 🚨** STOP. Do NOT suggest, install, or mention Homebrew. Ever. Use Nix (nixpkgs/nixpkgs-unstable) or direct binary downloads ONLY.

---

## Before EVERY Task

- [ ] **Scope**: One deliverable only - no "while I'm here" additions
- [ ] **Git**: Using `karlhepler/` prefix for new branches?
- [ ] **🚨 NO HOMEBREW**: Not suggesting OR mentioning brew install ANYWHERE?
- [ ] **Context7**: Using external library/framework? Queried Context7 for authoritative docs BEFORE implementing? (see § Research Priority Order)
- [ ] **🔍 Search tools**: Using built-in Grep/Glob tools (preferred) or `rg`/`fd` via Bash? NOT `grep`/`find`?
- [ ] **Tool-First**: Integrating with external tool? Explored its `--help` and built-in validators BEFORE researching? (see § Tool-First Integration)

**If ANY unchecked, STOP and address first.**

---

## Dangerous Operations

### Outright Prohibitions (Never Run)

- `kanban clean` / `kanban clean --expunge` / `kanban clean <column>` — **PROHIBITED**. Use `kanban cancel` instead.
- `perm nuke` — **USER-ONLY.** Claude agents must NEVER call this.

### Ask-First Operations (Require User Approval)

**NEVER run without explicit user approval:**

- `hms --expunge` - Removes stale Home Manager generations
- `git reset --hard` - Discards local changes permanently
- `git push --force` - Overwrites remote history
- `rm -rf` commands - Permanent file deletion

Explain what the command will do, ask for confirmation, only proceed after approval.

---

## Tool-First Integration

**When integrating with any external tool (CLI, API, framework), enumerate the tool's own capabilities FIRST — before docs, before web searches, before any indirect investigation.**

**Step 1: Explore the tool's CLI surface.**
- `<tool> --help`, `<tool> <subcommand> --help`
- Discover built-in validators, diagnostics, and inspection commands
- Look for `validate`, `check`, `lint`, `doctor`, `debug`, `inspect` subcommands

**Step 2: Use the tool's own diagnostics.**
- Run validators against your output/config before investigating why it doesn't work
- The tool is the authoritative source of truth for what it accepts

**Step 3: Only then reach for external research** (docs, Context7, web search — per § Research Priority Order)

**Why:** External tools often have built-in diagnostic commands that give you the exact answer in seconds. Researching docs, GitHub issues, and web pages to understand what a tool accepts is solving the wrong problem when the tool can tell you directly.

**Example:**
- ❌ Spent hours comparing JSON formats, reading GitHub issues, and fetching docs to debug why `marketplace.json` wasn't accepted
- ✅ `claude plugin validate marketplace.json` → immediately showed `Unrecognized key: "$schema"`

---

## Research Priority Order

**Note:** When integrating with an external tool, first explore the tool's own CLI surface before any of the steps below — see § Tool-First Integration.

When researching, investigating, or looking up information, ALWAYS follow this priority order:

1. **CLAUDE.md files** - Global (`~/.claude/CLAUDE.md`) and project-specific (`./CLAUDE.md`)
   - Most authoritative for "how we do things here"

2. **Local docs/ folder** - Check for `docs/`, `doc/`, `documentation/` in the repo

3. **Context7 MCP** - MANDATORY for external library/framework work
   - Query Context7 BEFORE implementing to get authoritative, up-to-date documentation from source
   - Tools: `mcp__context7__resolve-library-id` (find library), then `mcp__context7__query-docs` (query documentation)
   - **🚨 WARNING**: External docs may suggest Homebrew - ALWAYS translate to Nix

**🚨 BACKGROUND SUB-AGENTS:** Cannot access MCP servers directly. Staff engineer must pre-fetch Context7 results and pass via card content or `.scratchpad/` files.

4. **Web search** - ONLY when above sources don't have what you need
   - Triangulate with multiple sources; verify credibility and recency

---

## Scope Discipline

**One task = one deliverable.**

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

## Model Selection

| Model | When to Use | Examples |
|-------|-------------|----------|
| **Haiku** | Requirements crystal clear AND implementation straightforward | Fix typo, add null check, simple git command |
| **Sonnet** | Any ambiguity in requirements OR implementation (**default**) | New features, refactoring, investigation |
| **Opus** | Novel/complex/highly ambiguous | Architecture design, multi-domain coordination |

**When in doubt** → Always choose Sonnet. Size ≠ complexity. Failed Haiku work costs more than the model difference.

**For Coordinators (Staff Engineer, Ralph):** Use `model: haiku` only when unambiguous AND trivial. Default to `model: sonnet`. Use `model: opus` for architectural work.

**Note on Ralph:** Model selection for burns specialist agents is determined by hat YAML (`modules/claude/global/hats/*.yml.tmpl`), not this guidance.

---

## Programming Preferences

**🏆 Top Architecture Principle — Ports & Adapters (Request/Sender pattern):**

Every handler should follow this contract — typed input, plain-function output port, pure and testable handler:

```typescript
// TypeScript
function foo(req: Request, send: (msg: Message) => void): void | Promise<void>
```

```go
// Go
func Foo(req Request, send func(msg Message)) error
```

```python
# Python
def foo(req: Request, send: Callable[[Message], None]) -> None:
```

```rust
// Rust
fn foo(req: Request, send: impl Fn(Message))
```

```csharp
// C#
void Foo(Request req, Action<Message> send)
```

- **`req`** — everything the handler needs as input, typed explicitly at the call site
- **`send`** — the output port; a plain function the handler calls to emit results
- **`Message`** — a discriminated union or typed struct defined by the handler's layer (not the caller's)
- The caller wires up presenters by binding to `send` — terminal output, SSE stream, test spy, file logger, etc.
- Multiple presenters bind to one `send` via `fanOut`: `const send = fanOut([presenterA, presenterB])` // fanOut: simple utility — implement inline as: `const fanOut = (handlers) => (msg) => handlers.forEach(h => h(msg))`
- The handler is pure and testable — it never imports or knows about its consumers

Apply from the start on every new handler, service boundary, or core API. Do not reach for EventEmitter, global state, or tightly coupled I/O when this pattern fits.

---

**Bash/Shell Conventions:**
- Environment variables: ALL_CAPS_WITH_UNDERSCORES (e.g., `KANBAN_SESSION`, `CONTEXT7_API_KEY`)
- Script-local variables: lowercase_with_underscores (e.g., `card_number`, `output_file`)
- **Error handling:** Use `set -euo pipefail` at script start for fail-fast behavior

**Bash Tool Usage — One Command Per Call:**
- **Do NOT chain multiple logical operations with `&&` in a single Bash tool call.** Each distinct operation must be its own Bash call.
- ❌ `cd /path && npm run lint && npm run test`
- ✅ Three separate Bash calls: `cd /path`, `npm run lint`, `npm run test`
- **Exception:** Chain only when all commands form a single atomic git intent (stage + commit) or are purely informational.

**Save Output, Don't Re-Run:**
- When you plan to analyze the output of a command multiple times, **run it once and save to a file**, then analyze that file. Use a unique filename (e.g., card number) to avoid collisions with parallel agents.
- ❌ `npm test | rg 'FAIL'` → `npm test | rg 'Error'` → `npm test | rg 'snapshot'`
- ✅ `npm test > .scratchpad/test-output-42.txt 2>&1` → then `rg 'FAIL' .scratchpad/test-output-42.txt`, etc.

**Mindset:** Always Be Curious - investigate thoroughly, ask why, verify claims, cite sources

---

## 🚨 Use `rg` and `fd` — NEVER `grep` or `find` 🚨

**NEVER use `grep` or `find` in Bash.** Use `rg` and `fd` respectively. Both are Nix-guaranteed.

> **Prefer built-in tools over Bash:** Claude Code's built-in **Grep** and **Glob** tools are preferred over running `rg`/`fd` via Bash for most search tasks.

❌ `grep -r "pattern" src/` / `find . -name "*.ts"`
✅ `rg "pattern" src/` / `fd -e ts`

**Self-Check:** Before running ANY Bash search command: does it start with `grep` or `find`? → REWRITE with `rg` or `fd`.

---

## 🚨 PACKAGE INSTALLATION: NEVER HOMEBREW 🚨

**This is a Nix-managed system. Homebrew is FORBIDDEN.** Use Nix packages (`modules/packages.nix`), direct binary downloads, or language-specific managers (npm, pip).

**Self-Check:** Does my response contain "brew" or "homebrew"? → REWRITE. Quoting external docs that mention Homebrew? → TRANSLATE to Nix.

---

## PR Creation

**🚨 All pull requests MUST be created in draft mode.** Always use `--draft`:

```bash
gh pr create --draft --title "title" --body "description"
```

Promote to ready ONLY after all CI checks pass, diff reviewed, description complete.

---

## PR Descriptions

Two questions — that's all:

1. **Why does this exist?** — What goal, project, or problem does it serve?
2. **What happens when it merges?** — What effect does it have?

```
## Why

[One paragraph.]

## What This Does

[One paragraph.]

---
🤖 Generated with [Claude Code](https://claude.ai/claude-code)
```

**Rules:** Scannable in 10 seconds. No file-by-file breakdowns, no implementation details, no config details visible in the diff. When updating, rewrite from scratch — reflect current HEAD, not commit history.

---

## Git Branch Naming

**ALL branches MUST use `karlhepler/` prefix.**

✅ `karlhepler/feature-name`
❌ `feature-name` or `feature/name`

---

## PR Comment Replies

See the `/review-pr-comments` skill for full workflow.

---

## GitHub Actions Security

**All GitHub Actions MUST be pinned to commit SHA with version comment.**

✅ `actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1`
❌ `actions/checkout@v4` or `actions/checkout@v4.1.1`

Use `pinact run` to pin, `pinact run -u` to update, `pinact run --check` in CI to enforce.

---

## Glossary

**Agent:** A Claude Code instance executing work (the AI itself)

**Sub-agent:** A background agent spawned via Task tool to handle delegated work

**Skill:** A specialized capability loaded via Skill tool (markdown file in `~/.claude/commands/`)

**Session ID:** Friendly name identifier for Claude session (e.g., `clear-vale`, `swift-falcon`, `smart-bell`). Automatically injected at startup. Use with `--session` flag on kanban commands.

**Card:** Kanban board work item with action (what), intent (why), and acceptance criteria (definition of done)

**Work Card:** Card where AC verifies file changes (implementations, fixes, modifications)

**Review Card:** Card where AC verifies information returned (analysis, findings, recommendations)

**Open:** When the user says "open X", Claude runs the macOS `open` command via Bash (e.g., `open file.txt`, `open https://example.com`). "Open" means launch/display, not read or process in Claude.

---

## MCP Integration

**Context7 MCP** - Authoritative documentation lookup for libraries and frameworks. (Background sub-agent MCP constraints documented in § Research Priority Order.)

- Tools: `mcp__context7__resolve-library-id` (find library), `mcp__context7__query-docs` (query documentation)
- When it fails: Fall back to WebSearch for official documentation
- Config: Automatically enabled if `CONTEXT7_API_KEY` set in `overconfig.nix`. To disable: Remove key, run `hms`.

---

## Technology Selection

**Prefer boring, battle-tested solutions.** Standard library first, then well-maintained open-source, build custom only when nothing else works.

---

## Scratchpad

`.scratchpad/` (at the project root, sibling to `.kanban/`) is the canonical location for temporary working files. Not git-tracked, persists across sessions.

---

## Reference Commands

For kanban commands, run `kanban --help`. For session analytics, run `claude-inspect --help`.

- `tmux-restore`: Pick and restore a tmux-resurrect snapshot via fzf
