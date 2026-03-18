# Claude Code Guidelines

> **Tools:** See [TOOLS.md](./TOOLS.md). **🚨 Use `rg` not `grep`, `fd` not `find`** (see § Use `rg` and `fd`). Custom git utilities available.

> **Context7 MCP:** When working with external libraries/frameworks, query Context7 MCP for authoritative documentation before implementing. See § Research Priority Order for full details, including background sub-agent constraints.

> **🚨 NEVER HOMEBREW 🚨** STOP. Do NOT suggest, install, or mention Homebrew. Ever. Use Nix (nixpkgs/nixpkgs-unstable) or direct binary downloads ONLY.

---

## Before EVERY Task

- [ ] **Scope**: One deliverable only - no "while I'm here" additions
- [ ] **Why**: Can I explain rationale and alternatives?
- [ ] **Check-In**: Got approval for complex/multi-file changes?
- [ ] **Git**: Using `karlhepler/` prefix for new branches?
- [ ] **🚨 NO HOMEBREW**: Not suggesting OR mentioning brew install ANYWHERE?
- [ ] **Context7**: Using external library/framework? Queried Context7 for authoritative docs BEFORE implementing?
- [ ] **🔍 Search tools**: Using built-in Grep/Glob tools (preferred) or `rg`/`fd` via Bash? NOT `grep`/`find`?

**If ANY unchecked, STOP and address first.**

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

3. **Context7 MCP** - MANDATORY for external library/framework work
   - **When triggered:** Any task involving external libraries, frameworks, or third-party APIs
   - **Requirement:** Query Context7 BEFORE implementing to get authoritative, up-to-date documentation from source
   - **What to query:** API usage, configuration steps, integration patterns, best practices
   - **Example:** Before adding Passport.js authentication middleware, query Context7 for session strategies, callback patterns, and error handling
   - **Tools:** Use `mcp__context7__resolve-library-id` (find library), then `mcp__context7__query-docs` (query documentation)
   - **🚨 WARNING**: External docs may suggest Homebrew - ALWAYS translate to Nix

**🚨 BACKGROUND SUB-AGENTS:** Cannot access MCP servers directly. Staff engineer must pre-fetch Context7 results and pass via card content or `.scratchpad/` files.

4. **Web search** - ONLY when above sources don't have what you need
   - Triangulate with multiple sources
   - Verify credibility and recency
   - Last resort, not first option

**Why this order:** Start with the most specific, authoritative sources (project context) before reaching for general external sources. Context7 is mandatory for external library work because it provides authoritative docs directly from maintainers, preventing outdated or incorrect implementation patterns.

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

## Kanban Command Reference

| Command | Purpose | Who Uses |
|---------|---------|----------|
| `kanban list --output-style=xml --session <id>` | Board check (compact XML) | Staff engineer |
| `kanban do '<json>' --session <id>` or `kanban do --file <path> --session <id>` | Create card(s) in doing | Staff engineer |
| `kanban todo '<json>' --session <id>` or `kanban todo --file <path> --session <id>` | Create card(s) in todo | Staff engineer |
| `kanban show <card> [--output-style=xml]` | Read card details (action, intent, AC) | AC reviewer, staff engineer |
| `kanban status <card>` | Print column name of card (lightweight check) | Staff engineer, sub-agents |
| `kanban start <card> [cards...]` | Pick up from todo | Staff engineer |
| `kanban review <card> [cards...]` | Move to review column | Staff engineer |
| `kanban redo <card>` | Send back from review | Staff engineer |
| `kanban defer <card> [cards...]` | Park in todo | Staff engineer |
| `kanban criteria add <card> "text"` | Add AC (mid-flight OK) | Staff engineer |
| `kanban criteria remove <card> <n> "reason"` | Remove AC with reason | Staff engineer |
| `kanban criteria check <card> <n>` | Self-check AC (agent_met column) | Sub-agents (own card) |
| `kanban criteria uncheck <card> <n>` | Undo self-check | Sub-agents (own card) |
| `kanban criteria pass <card> <n>` | Pass AC (reviewer_met column) | AC reviewer |
| `kanban criteria fail <card> <n>` | Fail AC (reviewer_met column) | AC reviewer |
| `kanban comment <card> "text"` | Add timestamped comment | Staff engineer |
| `kanban done <card> 'summary'` | Complete card (both columns enforced) | AC reviewer (staff engineer: last-resort fallback only — see ⚠️ note below) |
| `kanban cancel <card> [cards...]` | Cancel card(s) | Staff engineer |
| ~~`kanban clean`~~ | **PROHIBITED — never run** | Nobody |

**All commands accept `--session <id>` (required in multi-session contexts).**

**Sub-agents:** Prefer returning findings directly via the Agent return value rather than writing `kanban comment`. Comments are for the staff engineer to annotate cards — sub-agents should focus on completing work and calling `kanban review`.

**⚠️ `kanban done` is called by the AC reviewer, not the staff engineer. Staff engineer may only call it directly as a last-resort fallback after two consecutive failed AC reviewer attempts.**

---

## Session Introspection

`claude-inspect` provides analytics and diagnostics for kanban sessions. Use it to understand what agents did, how much work cost, and where tokens were spent — without writing ad-hoc scripts.

| Command | Description |
|---------|-------------|
| `claude-inspect list [N]` | List N most recent kanban sessions (default 10) |
| `claude-inspect session <kanban-session>` | Full session overview: agents, tokens, cost |
| `claude-inspect agents <kanban-session>` | Per-agent token and tool breakdown |
| `claude-inspect tools <kanban-session>` | Tool usage heatmap by agent role |
| `claude-inspect cards <kanban-session>` | Card event timeline with durations |
| `claude-inspect compare <session1> <session2>` | Before/after delta for optimization |
| `claude-inspect estimate [--type TYPE] [--model MODEL] [--batch N] [--json]` | Card completion time estimates (P50/P75/P90) from historical data |
| `claude-inspect throughput [kanban-session]` | Cards completed per hour (session or aggregate) |

---

## Terminal Utilities

- `tmux-restore`: Pick and restore a tmux-resurrect snapshot via fzf (shows sessions and window names in preview)

---

## Skill Invocation

When skills are invoked, the `$ARGUMENTS` placeholder is replaced at runtime with the specific task prompt provided by the coordinator. The placeholder appears in the skill file following a "## Your Task" section header.

**Example:**
```
## Your Task

$ARGUMENTS

*This placeholder is replaced with your specific instructions when the skill is invoked.*
```

Skills receive the full task context through this mechanism, so they have all necessary information to complete their work.

**Note:** When a skill is invoked via agent definition (`skills:` frontmatter), `$ARGUMENTS` is replaced at agent startup with the task prompt passed by the coordinator — the skill content is pre-loaded into the sub-agent's context before any tool use begins.

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

**Note on Ralph:** When Ralph invokes specialist agents via burns, model selection is determined by the specialist hat YAML configuration (`modules/claude/global/hats/*.yml.tmpl`), not by this guidance. Each specialist hat specifies its own model choice via the `cli.backend` field in the hat YAML.

---

## MCP Integration

**Context7 MCP** - Authoritative documentation lookup for libraries and frameworks. (Note: Background sub-agent MCP constraints are documented in § Research Priority Order.)

**How to use:**
- For library/framework docs: "Use Context7 MCP to lookup React Server Components best practices"
- For API references: "Use Context7 MCP to lookup NextJS 15 app router API"
- Tools: `mcp__context7__resolve-library-id` (find library), `mcp__context7__query-docs` (query documentation)

**When it fails:**
- Fall back to WebSearch for official documentation
- Prefer official docs over blog posts/tutorials
- Always verify information from multiple sources

**Configuration:**
- Automatically enabled if `CONTEXT7_API_KEY` set in `overconfig.nix`
- Check status: Context7 will be available if configured, no manual setup needed
- To disable: Remove `CONTEXT7_API_KEY` from overconfig.nix, run `hms`

---

## Technology Selection

**Prefer boring, battle-tested solutions.** Search for existing solutions before building custom.
- Standard library first
- Well-maintained open-source libraries
- Build custom only when nothing else works

---

## 🚨 Use `rg` and `fd` — NEVER `grep` or `find` 🚨

**CRITICAL: This system uses ripgrep (`rg`) and fd (`fd`). Both are Nix-guaranteed.**

**NEVER use `grep` or `find` in Bash.** When you need to search file contents or find files via the Bash tool, use `rg` and `fd` respectively. They are faster, have saner defaults, and are the standard tools in this environment.

> **Prefer built-in tools over Bash:** Claude Code's built-in **Grep** and **Glob** tools are preferred over running `rg`/`fd` via Bash for most search tasks. Reserve Bash `rg`/`fd` for cases where built-in tools can't do the job (e.g., complex pipelines, post-processing output).

❌ **NEVER run via Bash:**
```bash
grep -r "pattern" src/
grep -rn "TODO" .
find . -name "*.ts"
find . -type f -name "*.py"
```

✅ **ALWAYS use instead:**
```bash
rg "pattern" src/
rg -n "TODO" .
fd -e ts
fd -e py
```

### Quick Syntax Reference

**rg (ripgrep)** — replaces `grep`:
| grep | rg equivalent |
|------|---------------|
| `grep -r "pattern" dir/` | `rg "pattern" dir/` (recursive by default) |
| `grep -rn "pattern"` | `rg -n "pattern"` (line numbers) |
| `grep -ri "pattern"` | `rg -i "pattern"` (case insensitive) |
| `grep -rl "pattern"` | `rg -l "pattern"` (files only) |
| `grep -rw "word"` | `rg -w "word"` (word boundary) |
| `grep -c "pattern" file` | `rg -c "pattern" file` (count matches) |
| `grep -v "pattern"` | `rg -v "pattern"` (invert match) |
| `grep -A3 -B3 "pattern"` | `rg -C3 "pattern"` (context lines) |
| `grep --include="*.ts" -r "pattern"` | `rg -g '*.ts' "pattern"` (glob file filter) |
| `grep -E "regex\|pattern"` | `rg "regex\|pattern"` (extended regex by default) |

Key differences: `rg` is recursive by default, respects `.gitignore`, case-sensitive by default (use `-i` for case-insensitive, `-S` for smart case).

**fd** — replaces `find`:
| find | fd equivalent |
|------|---------------|
| `find . -name "*.ts"` | `fd -e ts` (extension filter) |
| `find . -name "foo*"` | `fd "^foo"` (anchored regex prefix match, recursive by default) |
| `find . -type f -name "*.py"` | `fd -e py` (files only is default) |
| `find . -type d -name "src"` | `fd -t d "src"` (directories only) |
| `find . -name "*.log" -delete` | `fd -e log -x rm {}` (execute command) |
| `find . -path "*/test/*" -name "*.ts"` | `fd -e ts --search-path test/` (restrict search to directory) |
| `find . -maxdepth 2 -name "*.md"` | `fd -d 2 -e md` (max depth) |
| `find . -mtime -1` | `fd --changed-within 1d` (files modified in last day) |

Key differences: `fd` is recursive by default, respects `.gitignore`, uses regex patterns (not globs), and has simpler syntax for common operations. `-x` executes commands in parallel by default (unlike `find -exec`); use `--threads=1` for sequential execution.

### Self-Check Before Running Bash

Before running ANY search or file-finding Bash command:
1. Does my command start with `grep`? → REWRITE with `rg`
2. Does my command start with `find`? → REWRITE with `fd`
3. Am I piping `find` into `grep`? → Likely one `rg` or `fd` command handles both

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

## PR Creation

**🚨 CRITICAL: All pull requests MUST ALWAYS be created in draft mode.**

**NEVER create a PR in ready mode.** Always use the `--draft` flag when creating pull requests:

```bash
gh pr create --draft --title "title" --body "description"
```

**Why:** Draft mode prevents accidental merges, gives you time to verify CI checks and add additional context, and signals to reviewers that work is still being finalized. Non-draft PRs risk merging incomplete work.

**No exceptions.** Every single PR — regardless of perceived completeness or urgency — must start as a draft. Promote to ready mode ONLY after:
- All CI checks pass
- You've reviewed the diff one final time
- Description is complete and accurate
- You're genuinely ready for merge approval

**If you catch yourself creating a non-draft PR → STOP and use `gh pr create --draft` instead.**

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
- **Configuration details visible in the diff:**
  - File paths and directory structures
  - Specific values (schedules, labels, environment variables)
  - Workflow step details (triggers, conditions, actions)
  - Resource configurations (timeouts, retries, quotas)
  - Technology stack listings

Reviewers have the diff. They don't need it narrated.

**Example of what NOT to do:**

❌ **WRONG - Verbose configuration details:**
```
## What This Does

Adds automated PR synchronization workflow that:
- Creates `.github/workflows/pr-sync.yml` with cron schedule
- Runs every 6 hours (`0 */6 * * *`) to check for stale PRs
- Adds `needs-rebase` label when PR is behind main by >10 commits
- Posts comment with rebase instructions when label added
- Uses `GITHUB_TOKEN` for authentication with repo scope
- Configures 30s timeout and 3 retry attempts on API failures
```

✅ **CORRECT - High-level outcome:**
```
## What This Does

Automatically detects PRs that have fallen behind main and notifies authors to rebase.
```

**Why this matters:** Configuration details create visual clutter, duplicate the diff, and obscure the actual purpose. Keep descriptions scannable.

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

✅ `karlhepler/feature-name`
❌ `feature-name` or `feature/name`

---

## PR Comment Replies

See the `/review-pr-comments` skill for full workflow.

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

**Bash Tool Usage — One Command Per Call:**
- **Do NOT chain multiple logical operations with `&&` in a single Bash tool call.** Each distinct operation must be its own Bash call. This enables granular permission approval — the user cannot selectively allow `npm run lint` but deny `npm run test` when they're chained into one call.
- ❌ `cd /path && npm run lint && npm run test`
- ✅ Three separate Bash calls: `cd /path`, `npm run lint`, `npm run test`
- **Exception:** Chain only when all commands form a single atomic git intent (stage + commit, fetch + rebase) or are purely informational (no side effects, writes, or network calls). When in doubt, use separate calls. (e.g., `git add file && git commit -m "..."` is fine — one is meaningless without the other).
- Piping output (`| tee`, `| jq`) counts as a separate logical operation if it could be omitted. If the pipe is integral to the command's purpose (e.g., `curl ... | jq .`), it's one operation.

**Mindset:** Always Be Curious - investigate thoroughly, ask why, verify claims, cite sources

---

## GitHub Actions Security

**CRITICAL: All GitHub Actions MUST be pinned to commit SHA with version comment.**

### Required Format

✅ **CORRECT - SHA-pinned with version comment:**
```yaml
- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1
- uses: actions/setup-node@60edb5dd545a775178f52524783378180af0d1f8 # v4.0.2
```

❌ **WRONG - Tag reference (mutable, security risk):**
```yaml
- uses: actions/checkout@v4
- uses: actions/checkout@v4.1.1
```

### Why SHA Pinning Matters

**Security:** Tags are mutable - action owners can change what `v4.1.1` points to. SHA commits are immutable.

**Supply chain attacks:** If an action repository is compromised, attackers can modify tagged releases to inject malicious code. SHA pinning prevents this.

**Reproducibility:** Same SHA always produces identical behavior. Tags can change behavior over time.

### Using pinact (Preferred)

`pinact` automates the entire SHA lookup and pinning process. Run it instead of manually constructing `git ls-remote` lookups.

**Install:** pinact is managed via Nix — it's declared in `modules/packages.nix` and available after running `hms`.

```bash
# Pin all unpinned actions in workflow files
pinact run

# Update already-pinned actions to the latest release (maintains SHA format)
pinact run -u         # or: pinact run -update

# Validate all actions are pinned without modifying files (CI enforcement)
pinact run --check
```

**Use `pinact run --check` in CI** to enforce the pinning policy — it exits non-zero if any action uses a mutable tag reference.

### How to Get the Correct SHA (Manual / Fallback)

**CRITICAL: Annotated tags have TWO SHAs:**
- **Tag object SHA** (wrong - points to tag metadata)
- **Commit SHA** (correct - points to actual commit)

You MUST dereference to the commit SHA.

✅ **CORRECT - Dereference to commit:**
```bash
# Method 1: Remote lookup with dereference (recommended)
git ls-remote https://github.com/actions/checkout.git refs/tags/v4.1.1^{}
# Returns: b4ffde65f46336ab88eb53be808477a3936bae11  refs/tags/v4.1.1^{}

# Method 2: Local lookup with dereference
git rev-list -1 v4.1.1
# Returns: b4ffde65f46336ab88eb53be808477a3936bae11

# Method 3: Local rev-parse with commit dereference
git rev-parse v4.1.1^{commit}
# Returns: b4ffde65f46336ab88eb53be808477a3936bae11
```

❌ **WRONG - Returns tag object SHA for annotated tags:**
```bash
git ls-remote https://github.com/actions/checkout.git refs/tags/v4.1.1  # Missing ^{}
git rev-parse v4.1.1  # Returns tag object SHA, not commit SHA
```

### Updating Actions

When updating to a new version:
1. *(Manual path only)* Find the new version tag (e.g., `v4.2.0`)
2. Run `pinact run -u` to update all pinned actions automatically, **or** get the commit SHA manually using `git ls-remote` (see above)
3. *(Manual path only)* Update both SHA and version comment
4. Test the workflow

**Example update:**
```yaml
# Before
- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1

# After
- uses: actions/checkout@a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0 # v4.2.0
```

---

## Scratchpad

`.scratchpad/` (at the project root, sibling to `.kanban/`) is the canonical location for temporary working files — debugger ledgers, project plans, cross-session context, anything that would otherwise end up in `/tmp` or the repo root. Background sub-agents write here because they cannot write outside the project tree. Agents can be told "write to the scratchpad" and they'll know where to go. Not git-tracked, persists across sessions.

---

## Dangerous Operations

This section covers two categories: operations that are outright prohibited (never run them) and operations that require user approval before running.

### Outright Prohibitions (Never Run)

Claude agents must NEVER run these commands under any circumstances. Do not ask for permission — the answer is always no.

- `kanban clean` - **PROHIBITED** — never run. Use `kanban cancel` instead.
- `kanban clean --expunge` - **PROHIBITED** — never run.
- `kanban clean <column>` - **PROHIBITED** — never run.
- `perm nuke` - **USER-ONLY — Claude agents must NEVER call this.** Nukes ALL entries from `permissions.allow`. Interactive only — reads confirmation from `/dev/tty` to prevent automated invocation. Run by the user directly when a full permission slate wipe is needed.

### Ask-First Operations (Require User Approval)

**CRITICAL: Claude Code must NEVER run these commands without explicit user approval.**

These operations are destructive and cannot be undone. Always ask the user for permission BEFORE running them.

- `hms --expunge` - Removes stale Home Manager generations (dangerous)
- `git reset --hard` - Discards local changes permanently
- `git push --force` - Overwrites remote history
- `rm -rf` commands - Permanent file deletion

**When user requests these operations:**
1. Explain what the command will do
2. Ask for explicit confirmation
3. Only proceed after receiving approval
4. Include the command in your response for transparency

