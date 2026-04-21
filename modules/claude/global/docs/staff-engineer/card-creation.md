# Card Creation

**Simple cards** (short action, no special characters): use inline JSON.

```bash
kanban do '{"type":"work","action":"...","intent":"...","criteria":["AC1","AC2","AC3"]}' --session <id>
```

**Complex cards** (long action, quotes, multi-field, or >2-3 lines): write JSON to `.scratchpad/kanban-card-<session>.json` using the Write tool, then pass `--file`.

```bash
# Step 1 (Write tool): write to .scratchpad/kanban-card-<session>.json
# Step 2 (Bash): kanban do --file .scratchpad/kanban-card-<session>.json --session <id>
```

**Threshold:** use file-based when the JSON contains single quotes/apostrophes or the card JSON spans more than 2-3 lines. Use inline for simple one-liners.

**Multiple complex cards:** write all cards as a JSON array to a single file and make one `kanban do/todo --file` call — not a separate file and invocation per card.

```bash
# Step 1 (Write tool): write to .scratchpad/kanban-cards-<session>.json as a JSON array: [card1, card2, ...]
# Step 2 (Bash): kanban do --file .scratchpad/kanban-cards-<session>.json --session <id>
```

**Note:** `kanban do --file` and `kanban todo --file` auto-delete the input file after reading — no manual cleanup needed.

**Why file-based for complex cards:** the Write tool is auto-approved and handles any content safely; the resulting Bash command (`kanban do --file *`) is a short, reviewable pattern that can be auto-approved independently. Inline is fine for simple cards because the full Bash command is short enough to review at a glance.

**🚨 NEVER use heredocs or `/dev/stdin` with kanban commands.** Do not pipe JSON via `<<EOF`, `<<'EOF'`, or `echo '...' |` into `kanban do`, `kanban todo`, or any other kanban subcommand. Heredocs and stdin redirects embed multi-line JSON directly in the Bash command, which triggers Claude Code's expansion obfuscation safety check — a built-in protection that flags Bash commands whose expanded content differs from what was reviewed. This causes an interactive permission prompt that cannot be auto-approved, breaking the automated kanban workflow. The correct pattern is always: Write tool to `.scratchpad/` file, then `kanban do --file`.

**AC quality and format:** `type` required: "work", "review", or "research". `AC` required: 3-5 specific, measurable items. `editFiles/readFiles`: Coordination metadata showing which files the agent intends to modify (e.g. `["src/auth/*.ts"]`). Displayed on card so staff engineers across sessions can see file overlap. Supports glob patterns.

**Research card example** (findings returned as agent output, not file changes):

```bash
kanban do '{"type":"research","action":"Investigate caching strategies for API responses","intent":"Understand options to inform architecture decision","model":"sonnet","criteria":["Options documented with tradeoffs [MoV: test -f .scratchpad/caching-findings.md]","Performance characteristics compared [MoV: rg tradeoff .scratchpad/caching-findings.md]","Recommendation provided with rationale [MoV: rg recommendation .scratchpad/caching-findings.md]"]}' --session <id>
```

Research cards use `readFiles` (not `editFiles`) and their AC verifies that findings are documented and returned — not that source files were changed.

> **⚠️ fnmatch glob behavior:** `*` matches path separators (`/`) — so `src/*.ts` matches files at any depth under `src/`, not just direct children. This is more permissive than shell glob behavior.

Be accurate — these are not placeholder guesses, they define the actual scope boundary. When editFiles is non-empty on a work card, the agent is required to produce file changes. Bulk: Pass JSON array.

**AC quality is the entire quality gate.** The AC reviewer is Haiku with no context beyond the kanban card. It runs `kanban show`, reads the AC, and mechanically verifies each criterion. If AC is vague ("code works correctly"), incomplete, or assumes context not on the card, the review will rubber-stamp bad work. Write AC as if a stranger with zero project context must verify the work using only what's on the card. Each criterion should be specific enough to verify and falsifiable enough to fail.

**AC items must be terse, falsifiable, and verifiable.** Each criterion has two parts: a short declarative statement + its means of verification (MoV). The MoV tells the Haiku AC reviewer exactly how to get the data — a command to run, a file to read, or a path to check. Without it, the reviewer wastes 10+ turns hunting.

**Format:** `"<statement> [MoV: <command or path>]"`

✅ ".gitignore contains a dist/ entry [MoV: rg 'dist' .gitignore]"
✅ "API returns 200 for valid input [MoV: curl -s localhost:3000/api/health]"
✅ "Error handler logs to stderr [MoV: read src/error.ts, check stderr usage]"
❌ ".gitignore still contains the dist/ entry — it was NOT removed because we need it for build artifacts (cat .gitignore | rg 'dist' returns a match)" — rationale is noise
❌ "Code works correctly" — no MoV, not falsifiable

**Grep MoV scoping — avoid false positives:** When a MoV uses `rg` to verify absence or presence of specific content, the pattern must be scoped tightly enough to match ONLY the change being verified — not unrelated content in the same file. A blanket pattern that matches other legitimate content will false-positive, burning retry cycles on correct work.

✅ "No stale 2-minute references in distribution section [MoV: rg -c 'distribution.*every 2 minute' docs/monitoring-runbook.md]"
❌ "No stale 2-minute references [MoV: rg -c '2.minute' docs/monitoring-runbook.md]" — matches unrelated "2 minute" references (circuit breaker, deploy queue)

**The test:** Before writing a grep MoV, ask: "Could this pattern match content unrelated to my change?" If yes, add surrounding context words to disambiguate, or use a different verification approach.

**Test-as-MoV (preferred for complex or multi-criterion work cards):** When the deliverable is complex enough that individual file inspections would burn many reviewer turns, write a test first that programmatically encodes the vision. The sub-agent's action includes "make this test pass." Every AC item then shares a single MoV: `[MoV: <test command>]`. The reviewer runs the test once and verifies all criteria in one shot.

✅ "User profile returns sanitized email [MoV: npm test -- user-profile.test.ts]"
✅ "Missing fields return 422 with error details [MoV: npm test -- user-profile.test.ts]"
✅ "Admin role bypasses rate limit [MoV: npm test -- user-profile.test.ts]"

This collapses N criteria into one reviewer action. Use when: 3+ behavioral criteria on a single feature, integration-level verification needed, or file inspection alone can't confirm correctness.

**Git/PR mechanics prohibition:** Never embed git/PR mechanics in card content or delegation prompts. This applies to the `action` field, AC criteria, AND SCOPED AUTHORIZATION lines in delegation prompts. Including "commit and push" steps or "create a PR" in the `action` field leads sub-agents to attempt git operations before AC review. Including "changes committed and pushed", "PR created", or "PR opened" in AC criteria structurally forces git operations to happen *before* the AC reviewer runs — inverting the quality gate. Authorizing `git commit`, `git push`, or `gh pr create` in SCOPED AUTHORIZATION lines has the same effect — the agent executes the authorized operation during its work, bypassing the AC review gate entirely. AC criteria must only verify the work itself (files changed, behavior correct, output produced). The `action` field describes file changes to make, not lifecycle management. Git operations are exclusively the staff engineer's responsibility, executed after `kanban done` succeeds.

**Decomposing "commit and push" requests:** When the user's request includes git operations ("commit and push this," "make a PR"), decompose: delegate only the code/file changes to the sub-agent. Handle git operations (commit, push, PR creation) personally after the AC reviewer confirms done. Never pass the user's git instructions through to the card or delegation prompt.

**Model selection reminder:** Specify the `model` field on every card. See § Model Selection for the evaluation flow — evaluate actively before creating each card, not reflexively.
