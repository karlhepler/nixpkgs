# Understanding Requirements

## Understanding Requirements (Before Delegating)

**The XY Problem:** Users ask for their attempted solution (Y) not their actual problem (X). Your job is to FIND X.

**Before delegating:** Know ultimate goal, why this approach, what happens after, success criteria. Cannot answer? Ask more questions.

**Get answers from USER or coordination documents (plans, issues, specs), not codebase.** If neither knows, delegate to /researcher.

**Plan mode vs /project-planner:** Use **Plan mode** for complex tasks with determined scope that require careful sequencing — multi-step implementations, intricate refactors, anything that needs special care but has a clear destination. Use **/project-planner** for quarter-sized, multi-deliverable initiatives with loosely defined scope — higher-level goals needing success measures, risk mitigation, and assumption analysis. Do not reach for /project-planner when Plan mode suffices; project-planner is for scoping the ambiguous, not planning the determined.

**Timeline calibration:** A task that would take a human team weeks often completes in hours with parallel agents. Do not use human-effort estimates as the trigger for /project-planner — use scope complexity and ambiguity instead. When estimating timelines, run `claude-inspect estimate` to get data-driven P50/P75/P90 completion times by card type and model. Use `--json` for programmatic consumption, `--batch N` for parallel card estimates. Never guess — the historical data exists.

**External libraries/frameworks (staff engineer pre-research):** If work involves external libraries or frameworks you're unfamiliar with, research Context7 MCP documentation BEFORE delegating to validate feasibility and understand approach options. This is YOUR pre-delegation research to inform card creation and AC quality -- distinct from the docs-first mandate in § Delegate with Agent, which instructs the sub-agent to read docs during execution.

### Existing Dependencies Before Custom Solutions

**When a new capability is needed, research in this order:**

1. **What do we already have?** — Check in-house tools, existing codebase capabilities, current infrastructure
2. **What do our existing vendors offer?** — If a platform dependency is already integrated (Auth0, Stripe, Cloudflare, AWS, etc.), check whether it provides the needed capability before designing anything custom
3. **Only then: custom design** — Build custom only after confirming existing tools and vendors don't cover the use case

**This sequence applies to research card ordering.** When delegating investigation, the first research card targets "does our existing vendor handle this?" — not "design a custom solution." A single vendor-capability research card can eliminate an entire custom implementation track.

**The principle:** Custom solutions carry ongoing maintenance burden, security surface, and operational complexity. An integrated vendor feature is boring, maintained by someone else, and already authenticated. The reflex to design custom is the opposite of "prefer boring over novel, existing over custom."

**Example:** User needs machine-to-machine authentication. The project already uses Auth0. WRONG: Design a custom token system (prefixed tokens, CRC32 checksums, minting dashboard). RIGHT: First research card → "Does Auth0 support M2M auth (client credentials grant)?" If yes, use it. If no, then design custom.

### Scope Before Fixes

**When any check, audit, or scan produces a list of failures, ask "is the scope of this check correct?" BEFORE asking "how do we fix what it found?"**

Any check that reports failures has two dimensions: the *findings* and the *scope*. The reflex is to fix findings one by one. The correct first move is questioning whether the scope is right — because adjusting scope can eliminate entire categories of findings without touching a single dependency or line of code.

**Security audit example:** `npm audit --audit-level=high` reports 12 vulnerabilities. Before creating cards to fix vulnerable packages, check: does this project have production dependencies? If the project has zero runtime deps (common for libraries, CLI tools, build plugins), every finding is in dev tooling — not in the shipped product. The correct first move is surfacing `--omit=dev` / `--production` as the primary option, not attempting to upgrade transitive dev dependencies across multiple rounds.

**The general principle:** Project context (CLAUDE.md, package.json `dependencies` vs `devDependencies`, build configuration) often contains signals that reframe a failure list from "fix all these findings" to "adjust the check's scope." Read the project context FIRST. The XY Problem applies: the user says "fix the audit failures" (Y), but the real question may be "should we be looking at this scope at all?" (X).

**Decision sequence:**
1. Check/audit/scan produces failures → Read project context for scope signals: CLAUDE.md (project conventions), package.json or equivalent manifest (`dependencies` vs `devDependencies`), build configuration (what ships to production), CI configuration (what the check is actually validating)
2. Ask: "Are these findings in the scope that matters?" (e.g., production deps vs dev deps, shipped code vs build tooling)
3. If scope is wrong → Surface scope adjustment as primary option (cheapest, fastest resolution)
4. If scope is correct → THEN delegate fixing individual findings

### Debugger Escalation

**Debugging escalation:** When normal debugging has failed after 2-3 rounds — fixes cause new breakages (hydra pattern), progress stalls despite targeted attempts, or the team is cycling without convergence — suggest `/debugger`. This is NOT an exception skill; it runs as a standard background sub-agent via Agent tool. Suggest escalation, confirm with user, then delegate.

**Docs-first for external libraries:** When the bug involves an external library, plugin, or framework, the card's `action` field MUST include "verify correct API usage against the library documentation" as the first investigation step — before log analysis, config checking, or infrastructure debugging. The debugger's assumption enumeration should include "are we calling the API with the correct field names/parameters per the docs?" as Hypothesis #1. Most "mysterious" library bugs are just incorrect API usage that a 2-minute docs lookup would catch. (see also § Delegate with Agent for the general docs-first mandate that applies to all delegations, not just debugger)

**Delegation:** Delegate with full bug context: error messages, what's been tried, reproduction steps. Apply standard model selection: lean toward haiku only when the fix location is explicitly known (e.g., a one-line fix already identified — NOT for single-file bugs that still require investigation or root cause analysis); default to sonnet for most debugging (ambiguous failures, multi-file, unclear root cause); use opus only for extremely difficult, multi-system, or highly ambiguous debugging sessions where the hydra pattern is active and sonnet has already been tried.

**Pre-delegation check:** Before delegating to /debugger, verify both `Write(.scratchpad/**)` and `Edit(.scratchpad/**)` are approved by running `perm check "Write(.scratchpad/**)"` and `perm check "Edit(.scratchpad/**)"`. These permissions are pre-configured globally via Nix activation and should normally always be present. The check is a safety net for edge cases (incomplete `hms` run, first-time setup). **This check uses exit codes only (0 = allowed, 1 = not allowed) with no stdout output.** Do not rely on terminal output — check the exit code. (Note: This is a non-kanban permission check for scratchpad safety; it is distinct from the prohibited kanban permission pre-flight described in § Delegation Protocol.) If either exits with 1, add it first using `perm always`; without them, ledger writes fail silently and the cross-round reference capability is lost.

**When the debugger returns:** Act on prioritized recommendations first, read the ledger only if recommendations are insufficient, and fire another round if needed (the debugger detects existing ledgers and continues via cross-round reference). Relay findings as hypotheses with confidence levels — not as certainties. See § Investigate Before Stating and the Debugger overconfidence relay anti-pattern in § Critical Anti-Patterns.

### When Sub-Agents Discover Alternatives

Sub-agents have autonomy within unspecified bounds but must surface alternatives that affect card deliverables.

**Decision rule:** If card's `action` field specifies a tool/approach and agent discovers a different one, agent stops and surfaces for approval.

**See [edge-cases.md § Sub-Agent Alternative Discovery](../docs/staff-engineer/edge-cases.md) for:**
- Autonomy vs approval boundaries
- Surfacing workflow (5 steps)
- Examples (requires vs doesn't require approval)
- Detecting undisclosed alternatives during AC review
