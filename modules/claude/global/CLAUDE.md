# Claude Code Guidelines

> **Tools:** See [TOOLS.md](./TOOLS.md). **🚨 Use `rg` not `grep`, `fd` not `find`** (see § Use `rg` and `fd`). Custom git utilities available.

> **Context7 MCP:** When working with external libraries/frameworks, query Context7 MCP for authoritative documentation before implementing. See § Research Priority Order for full details, including background sub-agent constraints.

> **🚨 NEVER HOMEBREW 🚨** STOP. Do NOT suggest, install, or mention Homebrew. Ever. Use Nix (nixpkgs/nixpkgs-unstable) or direct binary downloads ONLY.

> **Reference material is in `~/.claude/docs/`, not in this file — read the named file when its topic comes up:** `coordination-reference.md` holds the Agent / Sub-agent / Skill / Session ID glossary and the delegatable-agent roster (who exists, and which capabilities run via Skill tool instead of delegation). `cli-and-mcp-reference.md` holds the `claude-inspect`, `perm`, `tmux-restore`, and `prc` entry points, plus Context7 MCP config and its WebSearch fallback.
> `user-confirmation-protocols.md` holds the check-in template required before 3+-file, architectural, or database/API changes, and the paraphrase-first rule for ambiguous multi-step requests (skipped for simple commands like "Read file" or "Run tests") — both need an interactive user, so neither applies to a background sub-agent.

---

## Before EVERY Task

- [ ] **Scope**: One deliverable only - no "while I'm here" additions
- [ ] **Git**: About to branch? Confirm the repo uses branches first (§ Check the Repo's Branching Convention), then use the `karlhepler/` prefix.
- [ ] **🚨 NO HOMEBREW**: Not suggesting OR mentioning brew install ANYWHERE?
- [ ] **Context7**: Using external library/framework? Queried Context7 for authoritative docs BEFORE implementing? (see § Research Priority Order)
- [ ] **🔍 Search tools**: Using built-in Grep/Glob tools (preferred) or `rg`/`fd` via Bash? NOT `grep`/`find`?
- [ ] **Tool-First**: Integrating with external tool? Explored its `--help` and built-in validators BEFORE researching? (see § Tool-First Integration)

**If ANY unchecked, STOP and address first.**

---

## Dangerous Operations

### Outright Prohibitions (Never Run)

- `perm purge` — **USER-ONLY.** Claude agents must NEVER call this.
- **NEVER skip hooks** (`--no-verify`, `--no-gpg-sign`, `git commit -n`, `git push --no-verify`, husky bypass env vars like `HUSKY=0` or `HUSKY_SKIP_HOOKS=1`, or any equivalent). Hooks are part of the contract — they run, every time.

  When a hook fails: **diagnose the underlying cause** (read the failing test output, identify the missing mock, propose a fix), then **fix the underlying issue and retry the operation with hooks intact**. Do NOT propose `--no-verify` (or any equivalent) as an option, even when the failure is a pre-existing flake, even when the change is in unrelated code, even when CI is disabled, even when it's a draft PR. The AI does not have authority to bypass hooks. If the user wants to bypass a hook on their own machine, they will type the flag themselves without your suggestion.

  When using AskUserQuestion: hook-skip flags MUST NOT appear as one of the options. Even framing them as "one of three valid paths" trains the AI to consider them normal. The shape "(Recommended) Push with --no-verify ... | Fix the flake first | Run only relevant tests" is itself the bug — there should be no first option.

  **Human-delegated bypass is equally prohibited.** This applies to the coordinator AND all sub-agents. Routing the bypass to a different actor — offering "you push manually", "push it yourself", "confirm these are acceptable then push", or any variant that routes around the hook via another actor (including the human) — is the same violation. The only valid responses to a hook failure are: (a) diagnose and fix the root cause, or (b) escalate the root-cause fix (to the coordinator, for a sub-agent). Do not surface a human-delegated bypass as a path forward under any framing.

### Worktree Confinement

**An agent may only write within its assigned worktree / the active project tree. Mutating global or personal machine state outside it is prohibited.**

Prohibited targets include (but are not limited to):
- Global or per-user tool-manager configs (e.g. version manager configs in `~/.tool-versions`, `~/.config/<tool>/`, or equivalent — applies to the whole category, not any single tool)
- Shell rc files (`~/.bashrc`, `~/.zshrc`, `~/.profile`, etc.)
- Anything under `~/.config/` that belongs to the user's environment, not the repo
- Global or system-level package or tool installs

**When a tool is genuinely required for the work:**
- (a) Add it to the repository's own committed tool config (e.g. a repo-local `.mise.toml`, `.tool-versions`, etc.) included in the PR — so the whole team benefits; OR
- (b) Report the limitation as blocked and let the coordinator decide.

Convenience tooling that CI already provides should not be installed locally at all — the PR stands on CI's checks.

### Ask-First Operations (Require User Approval)

**NEVER run without explicit user approval:**

- `hms --purge` - Kills tmux server (closes ALL active tmux sessions)
- `git reset --hard` - Discards local changes permanently
- `git push --force` - Overwrites remote history
- `rm -rf` commands - Permanent file deletion

Explain what the command will do, ask for confirmation, only proceed after approval.

---

## Tool-Block Recovery

A denied, blocked, or errored tool call is never a silent turn-ending event — the agent always speaks. But not every denial calls for a retry: before reacting, classify it as a **mechanical denial** or a **prohibition denial**.

**Front-door test — apply this first, straight from the denial message, before any judgment call.** Two clauses, both required:

1. The message names a permitted alternative — a specific corrected form of the same action, not just "this is blocked."
2. **Self-authorization exclusion (non-negotiable):** a route that changes YOUR OWN AUTHORIZATION is never a permitted alternative, no matter how explicitly the message names it. Setting an environment variable that grants approval you didn't have, asking a human to run the blocked command instead, or editing config/settings to permit it — these change what you're allowed to do, not how you do it, so they are self-authorization, not correction. If the only named route is self-authorization, clause 1 does not count and the denial is a **prohibition** regardless of what else the message names.

If both clauses pass (an alternative is named, and it isn't self-authorization), treat it as mechanical. Checked against the two named examples plus the two mechanical examples below: `--no-verify`'s denial names `CLAUDE_NOVERIFY_AUTHORIZED=1` as its route — clause 2 excludes it, so despite naming something it is still a prohibition. `git stash`'s denial names no alternative form at all — clause 1 fails, prohibition. The `cd X && Y` and `-c`/`-e` wrapper denials each name a direct-invocation or subshell form that was already within your authority — clause 1 passes, clause 2 doesn't exclude it, so both are mechanical.

- **Mechanical denial** — the block message names the correct invocation form (wrong flag, a `cd X && Y` compound, a `-c`/`-e` inline-code wrapper, a wrong path-handling idiom). The ACTION was legitimate; only the FORM was wrong. Apply the correction stated in the message and re-issue the corrected call **in the same turn**, then continue the turn's remaining planned work.
- **Prohibition denial** — the block forbids the ACTION itself, in any form (`--no-verify` and every hook-skip variant, `perm purge`, a kanban subcommand a sub-agent may not run, `git restore`/`reset`/`clean`/`stash` from a sub-agent). Here **the denial is the answer**: report which command was denied and why, then stop the attempt — that report is how you **escalate the root-cause fix** to whoever can act on it (the coordinator, for a sub-agent — see § Dangerous Operations → NEVER skip hooks, which names this as the sub-agent's only valid response besides fixing the root cause directly). There is no corrected re-issue and no alternative route — searching for one is the exact route-around behavior § Dangerous Operations → **NEVER skip hooks** already forbids, human-delegated bypass included.
- **Discriminator — fallback, only when the front-door test above doesn't settle it:** ask whether the correction **accomplishes the same thing the denial blocked**, or a different, permitted thing. Passing a path as an argument instead of `cd`-ing to it reaches the same legitimate goal by a permitted route — mechanical, re-issue it. Committing without the hook, or having someone else run it instead, accomplishes the same thing the denial blocked — prohibition, do not do it under any framing.
- **Hook wording note:** hook source and this section can describe the same denial in different words without conflict. `kanban-subagent-cmd-hook.py` labels the same denial "PROHIBITION 2" for the `-c`/`-e` wrapper block — that label describes what the HOOK refuses outright, not this section's taxonomy, which turns on whether a permitted alternative form exists (here it does: "Use direct command invocation instead"), so this section still classifies it mechanical. Likewise `bash-cd-compound-hook.py`'s denial text ends "This is a hard block with no bypass — use the subshell form or remove the cd" — that sentence means the FLAG has no override, not that the action is forbidden; the same message supplies the corrected form in its own next clause, so it stays mechanical.
- Never leave a bare tool-block message as the last output of a turn. A blocked call is not a deliverable. Silence is never the correct terminal state, because the user cannot distinguish "blocked and gave up" from "still thinking" from "crashed." A prohibition denial ends the attempt, not the turn: the agent still names the block and stops there, in prose.
- This binds every agent tier — coordinators and specialist sub-agents alike — because every tier hits `PreToolUse` hooks and the failure mode is tier-independent.

**Recurrence signature:** a turn whose final output is a tool-block system message with no subsequent assistant prose and no retry call — **both prongs** (no prose, no retry) must be absent for the signature to match. A correctly-handled prohibition denial has prose (naming the block), even though it deliberately has no retry, so it satisfies the prose prong and does not match this signature; do not manufacture a retry-shaped action just to avoid resembling it. The user asking a variant of "why did you stop?" immediately after a hook block is the same failure.

---

## AWS Credentials (SSO Assume-Role Chains)

**When running IaC/CLI tooling locally against an SSO-based cloud org, understand the credential-assumption chain before overriding a profile env var — NEVER blind-set `AWS_PROFILE`.** Worked example below: AWS + Terraform.

**Detection heuristic (check BEFORE suggesting `AWS_PROFILE=...`):**
- The target profile in `~/.aws/config` has `role_arn` + `source_profile` (an assume-role chain)
- The `source_profile` chain resolves to an `sso_session`-based profile (modern SSO config — not the legacy flat `sso_start_url`/`sso_region` fields)

**Why blind-setting fails:** `AWS_PROFILE` cannot bypass the SSO `source_profile` dependency — the SDK resolves the source chain first and errors on the SSO root profile (commonly `default`), even though the exported profile itself is correctly configured.

**The robust fix — use whenever the detection heuristic matches, on ANY Terraform/provider version:** let AWS CLI v2 (which understands `sso_session`) resolve the chain and hand Terraform pre-assumed static creds:

```bash
aws sso login --profile <sso-root-profile>            # e.g. default
unset AWS_PROFILE                                     # so it can't shadow the exported creds — the hashicorp/aws provider (v4.x+) gives a configured profile PRECEDENCE over AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, inverting the AWS SDK's textbook order (hashicorp/terraform-provider-aws#25596)
eval "$(aws configure export-credentials --profile <target-profile> --format env)"
terraform init
terraform apply ...
```

Run each line as a separate Bash tool call — do not chain `terraform init`/`terraform apply` with `&&` (see § Bash/Shell Guidelines → One Command Per Call).

**Two independent version gates — do not conflate them:** Terraform **core** < 1.6 lacks `sso_session` support in its S3 state-backend credential resolver (backend-auth path). The `hashicorp/aws` **provider** < v4.0 (~May 2022) lacks `sso_session` support in its own resource/provider-auth path — independent of the Terraform core version. Either gate alone can cause the failure, so gating the workaround solely on `terraform -version` will misdiagnose a stale provider pin. The export-credentials fix above is safe and correct regardless of core/provider version — default to it whenever the detection heuristic matches.

**Self-Check:** About to `export AWS_PROFILE=<profile>` for local Terraform/IaC? First check `~/.aws/config` for a `role_arn`/`source_profile` chain rooted in an `sso_session` profile — if found, use `aws configure export-credentials` instead of blind-setting `AWS_PROFILE` (works on any Terraform core / `aws` provider version).

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

## Pagination Discipline

**When any `list_*` / search tool returns a next-page indicator (`hasNextPage`, `nextCursor`, `next`, a cursor, etc.), you MUST either:**
- (a) **Paginate to completion** — loop on the cursor until the indicator is false, accumulating all pages — before treating the collection as complete, OR
- (b) Switch to a **targeted query** (name/id filter) that avoids needing the full set.
- (c) If neither (a) nor (b) is feasible (e.g., the cursor API is rate-limited and no filter field exists), explicitly state that only a partial page was examined and results may be incomplete — never present partial results as complete.

**NEVER draw "this is the complete set" conclusions from a single partial page.** Partial pagination silently drops entities and corrupts every downstream decision that assumes completeness.

**Example:** `mcp__linear__list_projects` returned `hasNextPage: true` with a cursor, but a single 50-project page was treated as the complete set — never draining to `hasNextPage=false`. A project living beyond the fetched pages was silently missed, corrupting issue attribution until a human caught it.

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
   - **🚨 BACKGROUND SUB-AGENTS — NO MCP ACCESS, NOT JUST CONTEXT7:** No standard specialist sub-agent (swe-*, researcher, scribe, ai-expert, etc.) can access ANY MCP server directly — this constraint applies to Linear, Datadog, Notion, Slack, and every other MCP server, not just Context7, and it is unconditional: there is no per-agent exception. An `mcp:` field in agent frontmatter (e.g., `mcp: - context7`) would be informational only — no code in this repo wires it to real MCP tool access, so it would not grant runtime MCP access. No agent definition declares one, and none should be added. **Worked example (Context7):** the staff engineer must pre-fetch Context7 results and pass via card content or `.scratchpad/` files.

4. **Web search** - ONLY when above sources don't have what you need
   - Triangulate with multiple sources; verify credibility and recency

**Effort allocation across claims (a different dimension from the ordering above):** the priority order tells you which source to check first; it says nothing about where to spend the *most* effort. Before finalizing any section that the artifact — or the delegating card — labels as the most important, most load-bearing, central, or "the critical question," do ONE additional targeted search for the single most authoritative, mechanism-level source for that specific claim — even when adjacent sources already support a directionally correct conclusion. A directionally correct conclusion sourced only to a second-best document is a citation-completeness defect when a more authoritative source exists one hop away and was never fetched.

**Self-issued instruction:** if you write any of those labels about one of your own sections, treat that as a self-issued instruction to go back and exhaust sources for that specific claim before finalizing — not merely a description of the section.

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

## Initialisms

Applies to any text the user will read — messages an agent sends directly to the user, and content drafted in the user's voice. Expand obtuse or domain-specific initialisms to their full form the first time they appear in a given message or document; the bare initialism is fine after that. Common, widely-recognized acronyms (pronounced as words, or universally understood — e.g. `CI`, `PR`, `API`, `URL`) are exempt and stay as-is.

---

## Model Selection

| Model | When to Use | Examples |
|-------|-------------|----------|
| **Haiku** | Requirements crystal clear AND implementation straightforward | Fix typo, add null check, simple git command |
| **Sonnet** | Any ambiguity in requirements OR implementation (**default**) | New features, refactoring, investigation |
| **Opus** | Novel/complex/highly ambiguous | Architecture design, multi-domain coordination |

**When in doubt** → Always choose Sonnet. Size ≠ complexity. Failed Haiku work costs more than the model difference.

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

### YAGNI + KISS

- **You Aren't Gonna Need It** — don't build for speculative futures; build for what's actually needed NOW. Solve the problem at hand, not hypothetical future problems.
- **Keep It Simple, Stupid** — prefer boring, obvious solutions over clever ones. Clarity beats brevity.
- **LLM-specific trap:** DO NOT default to building abstractions for hypothetical future use cases. Concrete problem first; abstraction only after 3+ concrete uses prove it.
- Warning signs: abstractions with one caller, interfaces with one implementation, config flags that are never flipped.

See also: § Scope Discipline (one deliverable, no "while I'm here" additions).

### SOLID (minimal form)

- **SRP (Single Responsibility):** every function, class, and module does ONE thing. At function level: if you can't describe what it does without saying "and", split it.
- **OCP (Open/Closed):** prefer extending behavior via new code over modifying existing code — but only when extension is an actual pattern, not hypothetical (see YAGNI).
- **LSP (Liskov Substitution):** subtypes behave like their parent — no surprising exceptions, no stronger preconditions, no weaker postconditions.
- **ISP (Interface Segregation):** prefer many small interfaces over one large one. Clients shouldn't depend on methods they don't use.
- **DIP (Dependency Inversion):** already covered by Ports & Adapters above — depend on the `send` abstraction, not concrete consumers.

### DRY with nuance

- Default: avoid duplication WHEN the repeated code represents the same concept.
- **Prefer duplication over wrong abstraction.** If two pieces of code look similar but represent DIFFERENT concepts that happen to share syntax, duplicating is better than forcing them into a single abstraction.
- **Rule of three:** wait for 3+ repetitions of genuinely-same logic before abstracting. Premature DRY (2 repetitions) is the most common over-engineering mistake in LLM-generated code.
- Warning sign: "shared" helpers that multiple callers have to fight against ("pass this flag to make it work for my case").

**Additional ports & adapters rules:**
- **Handlers MUST NOT throw exceptions.** All outputs — success, failure, partial results, errors, domain violations — flow through `send`. A handler that throws is bypassing its output port. If a handler calls a function that might throw, catch the exception inside the handler and emit a typed failure message via `send`. Exception-throwing is an anti-pattern that defeats the purpose of the port abstraction.
- **`send` SHOULD be an interface, not a single function, when handlers emit multiple message categories.** The simple `(msg: Message) => void` signature works for handlers that emit one kind of thing. When a handler legitimately emits distinct message categories (e.g., progress updates, domain events, terminal results), model `send` as an object whose methods correspond to each category. Example: `send: { progress(pct: number): void; result(data: Result): void; failure(err: Error): void }`. The handler is still pure — it just has a richer output surface.
- **Constructor injection for capabilities.** Capabilities a handler needs (logging, clock, random, id generation) are provided by construction — either via class constructor parameters or higher-order function closures. Never access global/static instances for these. Injection makes handlers testable and keeps the port abstraction honest.
- **Composition-root testing corollary.** DI/ports-and-adapters makes handlers unit-testable with fakes, but leaves the composition root as the one seam a fake-injecting test cannot cover.
  - **The gap:** the composition root (main / cli / bootstrap — where real dependencies are constructed and wired) supplies its own fake wiring in tests instead of exercising the real one, so nothing ever proves the real wiring works.
  - **The failure signature:** a DI-wired feature can pass every unit test and still be dead in production if the real entry point never wires the adapter — "all unit tests green + feature does nothing in production" is a common signature of an unwired composition root (other bugs can produce the same symptom, so treat it as a strong hint, not a diagnosis).
  - **The fix:** require at least one test that exercises the real composition root or entry point — a smoke test that builds the app the way production does, or an integration test through the real entry — so an unwired dependency actually fails a test; green handler-with-injected-fake unit tests are necessary but not sufficient. One shared composition-root smoke test, extended incrementally as new wiring is added, satisfies this — not a new smoke test per handler.
  - **The trigger:** when injecting a new dependency into a handler/daemon/service, ask "does any test build this through the real composition root (main/cli/bootstrap), or do all tests inject their own fake?" If only the latter, extend the shared composition-root smoke/integration test before considering it done.

(Why `send` vs `response`: `send` is chosen over `response` because a handler does not always produce a single response — it may stream progress, emit multiple domain events, or bifurcate by outcome. `send` signals an output port, not a return value.)

### Allowlist over Blocklist

Prefer an allowlist over a blocklist wherever the failure directions are asymmetric: an over-narrow allowlist only rejects legitimate input, while an over-narrow blocklist can execute attacker-controlled code — the safe failure direction should be structural, not remembered. See `swe-security.md` § Allowlist over Blocklist for the review heuristic (what taxonomy was the exclusion list derived from, and what sits outside it) and the worked incident behind it.

---

## 12-Factor Configuration

All runtime configuration comes from environment variables, bound to typed constants in a single `config` file at the top of the source tree.

**File location:** `src/config.ts` / `config.go` / `config.py` / equivalent — as close to the top of the source tree as possible (typically right under `src/` or the equivalent package root).

**File contents:** exports of typed constants only. No logic, no conditionals beyond env-var fallbacks. Example in TypeScript:

```typescript
// src/config.ts
export const API_URL = process.env.API_URL ?? "https://api.default.com";
export const MAX_RETRIES = 3;
export const DEFAULT_TIMEOUT_MS = 5000;
export const DEBUG_MODE = process.env.DEBUG === "1";
```

And in Go:
```go
// config/config.go
package config

var (
    APIURL           = getenv("API_URL", "https://api.default.com")
    MaxRetries       = 3
    DefaultTimeoutMS = 5000
    DebugMode        = os.Getenv("DEBUG") == "1"
)
```

**Rules:**
- Every config constant that VARIES BY ENVIRONMENT is populated from an environment variable with a sensible default.
- Pure constants (do not vary by environment) are defined inline.
- All config surface is exported from this ONE file. Components import constants from `config` — never access `process.env` / `os.Getenv` / env-reading primitives directly elsewhere.
- Required env vars with no sensible default should fail fast on startup in production (simple assertion at config module load).

This matches 12-factor app principles: configuration lives in the environment, not the code.

---

## Epistemic Honesty

**The default posture is doubt, not confidence.** To assume is to make an ass out of you and me. Don't lean on assumptions — verify before claiming.

- **Before stating any technical claim, ask:** Have I actually verified this — run the command, read the file, checked the data? If no: say the words "I haven't verified this" or "I'm not 100% sure — let me double-check" and then do quick research. A quick web search, a one-line rg query, a file read, a CLI invocation — even a 30-second check beats confident wrongness.
- **Be self-skeptical.** The skepticism isn't about rejecting ideas — it's about being suspicious of your own confidence. The more fluently you can explain something, the more dangerous it is if unverified (fluency mimics expertise).
- **Cite sources.** Every technical claim should be backed by a specific citation: `file:line`, command output, web URL, doc page. "I think X typically works this way" is not a source. Actual evidence is.
- **WebFetch is not a verbatim source.** A WebFetch response is an LLM-generated answer to your prompt, not raw page text — never wrap it in quotation marks and present it as a verbatim document quote. When word-for-word accuracy is load-bearing, either explicitly prompt WebFetch to quote the exact sentence and treat the result as provisional and re-verifiable, or fetch raw content directly (e.g. `curl` via Bash); a quoted line that can't be located in the source's raw text is a fabricated citation, even if directionally correct. This generalizes beyond prose: when a claim is a structured, API-queryable fact (a GitHub issue/PR/commit's number, state, or resolution; any record a CLI or REST endpoint returns directly) — query that API (e.g. `gh issue view`, `gh api`) instead of WebFetch or WebSearch, and never treat two agreeing WebSearch summaries as independent corroboration of it — both are model-generated over the same index, so agreement is one source echoing itself.
- **Uncertainty is not a hedge — it's intellectual honesty.** Saying "I don't know — let me find out" is more useful than a plausible-sounding guess. Do not frame uncertainty apologetically.
- **Pressure doesn't justify guessing.** When production is broken and stress is high, the urge to give fast answers is strongest — and the cost of wrong answers is highest. Under pressure, slow down and verify; don't speed up and guess.

This applies across every level: coordinators, sub-agent specialists, and the human. When the user asks a factual question, the right answer is often "Let me check" followed by a quick check. Not "I believe X" without evidence.

---

## Bash/Shell Guidelines

**Bash/Shell Conventions:**
- Environment variables: ALL_CAPS_WITH_UNDERSCORES (e.g., `CONTEXT7_API_KEY`)
- Script-local variables: lowercase_with_underscores (e.g., `session_name`, `output_file`)
- **Error handling:** Use `set -euo pipefail` at script start for fail-fast behavior

**Bash Tool Usage — One Command Per Call:**
- **Do NOT chain multiple logical operations with `&&` in a single Bash tool call.** Each distinct operation must be its own Bash call.
- ❌ `cd /path && npm run lint && npm run test`
- ✅ Three separate Bash calls: `npm run lint`, `npm run test`, `npm run build` (ensure pwd is correct before the Bash calls, or pass paths via `--prefix`)
- **Exception:** Chain only when all commands form a single atomic git intent (stage + commit) or are purely informational.
- **Never issue a standalone `cd <dir>` call before another command** — whether chained (`cd /path && cmd`) or as a separate preceding Bash call (`cd /path` then `cmd`). Shell state persists between Bash tool calls, so git, ls, rg, etc. already operate in the current working directory. If you need a different directory, pass it as an argument or use a subshell (`cd /path && cmd`).
- **Never wrap commands in `sh -c '...'`.** The Bash tool already invokes a shell — wrapping `rg`, `fd`, or any other command in `sh -c '...'` adds a redundant shell layer that can obscure exit codes and mask failures. Invoke commands directly:

  ❌ `sh -c 'rg -n "pattern" file'`
  ✅ `rg -n 'pattern' file`

  If you genuinely need shell features (pipes, redirects, command substitution), use them in the Bash tool call directly — the tool is already a shell. Do not introduce a second `sh -c` layer to access those features.

  If you find yourself reaching for `sh -c` to handle complex quoting or escapes — stop. The Bash tool handles these directly; pass the command and arguments as you would to any normal CLI invocation.

**Save Output, Don't Re-Run:**
- When you plan to analyze the output of a command multiple times, **run it once and save to a file**, then analyze that file. Use a unique filename (e.g., card number) to avoid collisions with parallel agents.
- ❌ `npm test | rg 'FAIL'` → `npm test | rg 'Error'` → `npm test | rg 'snapshot'`
- ✅ `npm test > .scratchpad/test-output-42.txt 2>&1` → then `rg 'FAIL' .scratchpad/test-output-42.txt`, etc.

---

## 🚨 Use `rg` and `fd` — NEVER `grep` or `find` 🚨

**NEVER use `grep` or `find` in Bash.** Use `rg` and `fd` respectively. Both are Nix-guaranteed.

> **Prefer built-in tools over Bash:** Claude Code's built-in **Grep** and **Glob** tools are preferred over running `rg`/`fd` via Bash for most search tasks.

❌ `grep -r "pattern" src/` / `find . -name "*.ts"`
✅ `rg "pattern" src/` / `fd -e ts`

**Self-Check:** Before running ANY Bash search command: does it start with `grep` or `find`? → REWRITE with `rg` or `fd`.

> **Note:** `rg -E` means `--encoding`, not extended regex. Use `rg -qi 'pattern'` (regex is default) or `rg -qi -e 'pattern'` when the pattern starts with a dash.

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

**Anti-patterns (banned phrasing):**
- ❌ 'Placeholders are now guarded against duplicates' — narrates a fix
- ❌ 'Eliminating the brief gap where no loading indicator was shown' — narrates what changed
- ❌ 'Now correctly handles X' / 'No longer fails when Y' — narrates fixed-vs-broken state
- ❌ 'Updated to support Z' — narrates progression from prior version
- ✅ 'Loading placeholders remain visible until the service button is confirmed in the DOM.' — describes end state
- ✅ 'Handles X correctly.' — describes current behavior
- ✅ 'Supports Z.' — describes capability

**The principle:** The reader of a PR description is reviewing or using the FINAL CODE. They do not care what was broken before, what was fixed, or what was eliminated — only what the merged code does. Words like 'now', 'no longer', 'eliminated', 'fixed', 'updated to', 'changed from', 'previously', 'before', 'instead of', 'replaces', 'resolves' are red flags signaling commit-history narration. Split-sentence patterns like 'ensures ... no longer' are equally suspect. Rewrite as plain present-tense descriptions of behavior.

---

## Check the Repo's Branching Convention Before You Branch

The default "branch first if on the default branch" behavior assumes a pull-request flow. Not every repo has one. Before creating any branch, confirm the repo actually uses branches: check its CLAUDE.md for a documented workflow, and `git log --oneline -20` for whether commits land directly on the default branch. If a repo commits straight to its default branch with no PR flow, do not branch — the repo-local convention beats this global default. Worked example of a "no": `~/.config/nixpkgs` project-root `CLAUDE.md` § ALL WORK HAPPENS DIRECTLY ON `main`.

Treat branch creation as a **shared-state operation** wherever multiple sessions may share one checkout — see the worked example above for the mechanism and recovery.

---

## Git Branch Naming

**ALL branches MUST use `karlhepler/` prefix.**

✅ `karlhepler/feature-name`
❌ `feature-name` or `feature/name`

---

## GitHub Actions Security

**All GitHub Actions MUST be pinned to commit SHA with version comment.**

✅ `actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1`
❌ `actions/checkout@v4` or `actions/checkout@v4.1.1`

Use `pinact run` to pin, `pinact run -u` to update, `pinact run --check` in CI to enforce.

---

## Technology Selection

**Prefer boring, battle-tested solutions.** Standard library first, then well-maintained open-source, build custom only when nothing else works.

---

## Scratchpad

`.scratchpad/` (at the project root) is the canonical location for temporary working files. Not git-tracked, persists across sessions. The directory is guaranteed to exist — the SessionStart hook creates it automatically.

**Do NOT** run `ls .scratchpad` or `mkdir -p .scratchpad` before writing scratchpad files — just write.

**Scratch files are left in place and never deleted.** `rm`, `rm -rf`, and equivalent recursive deletes are not part of a sub-agent's vocabulary here — not on files you just created, not on your own probe scripts, not on anything else under `.scratchpad/`. Being told this in a card is not sufficient on its own — an agent that read an explicit no-`rm` instruction still ran it, because the instruction was a bare prohibition with no reason to act on. The reason: the directory is pruned automatically (entries older than 90 days), so cleanup buys nothing; and it is shared across concurrent sessions and cards, so the file a recursive delete targets may not be the file you think — it could be another card's in-flight findings, written incrementally so they survive a crash.

This prohibition is absolute for `.scratchpad/` and carries no approval exception under § Dangerous Operations → Ask-First Operations: that rule's approval step cures lack of authorization, not mis-targeting, and mis-targeting a file you didn't write — not lack of authorization — is the actual risk here.
