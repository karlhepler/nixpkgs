---
name: crew-cli
description: crew CLI full command reference. Auto-load when about to run any crew subcommand and need exact arguments, flag syntax, or error handling. Covers all subcommands: create, list, tell, read, find, status, dismiss. Includes --format flag behavior, exit code table, pane targeting rules (window vs window.pane), multi-target comma syntax, and crew create vs crew tell sequencing discipline. Note: crew sessions, crew resume, and crew project-path are NOT covered here — see senior-staff-engineer.md Communication Primitives section.
---

# crew CLI — Full Command Reference

Exhaustive reference for all `crew` subcommands. Senior Staff uses these in production — no `--help` lookups, no permission asks, no syntax mistakes.

Note: `crew sessions`, `crew resume`, and `crew project-path` are covered in the Communication Primitives section of `senior-staff-engineer.md` and do not have dedicated reference sections in this skill.

**Top-level syntax:**
```bash
crew [-h] [--format {xml,json,human}] {list,tell,read,dismiss,find,create,status} ...
```

**Global flag:**
- `--format` / `-f` — Output format: `xml` (default), `json`, or `human`. Applies to subcommands that produce structured output. Always use `xml` (machine-parseable); never `human`.

---

## crew create

End-to-end staff session creation — worktree, tmux window, and Claude instance in one command.

```bash
crew create <name> [--repo <path>] [--branch <branch>] [--base <base-branch>] [--tell "<message>"] [--no-worktree]
```

**Arguments:**
- `name` (required) — Session name. Used for the tmux window name, worktree directory (`~/worktrees/<name>`), and branch name.
- `--repo <path>` — Path to the git repository. Default: current repo via `git rev-parse --show-toplevel`.
- `--branch <branch>` — Branch name for the new worktree. Default: `<name>`. Incompatible with `--no-worktree`.
- `--base <base-branch>` — Base branch to create the new branch from. Default: current branch of the repo. Incompatible with `--no-worktree`.
- `--tell "<message>"` — Initial brief delivered to the session immediately after spawn. Single-call create + brief. Use this instead of a separate `crew tell` call.
- `--no-worktree` — Spawn a staff session directly in `<repo>` without creating a new worktree or branch. Use for "work directly on main" or existing-branch workflows. Incompatible with `--branch` and `--base`.
- `--cmd <command>` — Override the spawn command. Default: `staff --name <name>`. Use when the target session should run something other than `staff`.

**Behavior:**
- Default spawn command is `staff --name <name>`, NOT `claude --name <name>`. The created window is a Staff Engineer session.
- `--tell` delivers the initial brief in the same call — no separate `crew tell` needed.
- Use `--cmd <other>` to override the spawn command when not using `staff`.

**Examples:**
```bash
crew create pricing                                            # Branch + worktree + window all named "pricing"
crew create pricing --tell "Implement tiered billing model."   # Create + deliver initial brief in one call
crew create auth --base main                                   # Create from main instead of current branch
crew create docs --repo ~/worktrees/other-project/main         # Create in a different repo
crew create payment --branch payment-v2                        # Window named "payment", branch "payment-v2"
crew create hotfix --no-worktree                               # Work directly in repo without creating a worktree
```

**Error handling:**
- Duplicate tmux window name → exit 2 (check: `crew list`)
- Invalid name (spaces, slashes, shell chars) → exit 2
- Existing worktree at `~/worktrees/<name>` → exit 2
- Branch creation fails → exit 1, worktree not created
- tmux window fails after worktree created → exit 1, worktree left intact (partial state — do NOT auto-remove)

---

## crew list

Enumerate tmux windows and panes. Scoped to the current tmux session only.

```bash
crew list [--all] [--format xml|json|human]
```

**Arguments:**
- `--all` / `-a` — Include all panes regardless of running command. Default: Claude panes only.

**Scope:** Results are confined to the current tmux session — `crew list` never returns windows from other sessions.

**Output (XML default, Claude-only):**
```xml
<crew>
  <window name="pricing">
    <pane index="0" command="2.1.116" />
  </window>
  <window name="auth">
    <pane index="0" command="2.1.116" />
  </window>
</crew>
```

Claude Code installs as a versioned binary (`~/.local/share/claude/versions/2.x.y`), so `command` shows the version string rather than "claude".

**Examples:**
```bash
crew list                    # Survey all Claude panes in current session
crew list --all              # Full fleet including shells, smithers, etc.
crew list --format xml       # Explicit XML (same as default)
```

---

## crew tell

Send input to one or more specific pane(s).

```bash
crew tell <targets> "<message>" [--keys]
```

**Arguments:**
- `targets` (required) — Comma-separated targets. Bare window names are accepted and default to pane 0. `window.pane` format for explicit non-zero panes.
- `message` (required) — Text to send (literal text + Enter by default), or space-separated tmux key tokens (with `--keys`).
- `--keys` — Interpret message as tmux key tokens instead of literal text. No Enter appended automatically.

**Pane 0 default:** `crew tell pricing "..."` targets pane 0 of the `pricing` window. Only use `crew tell pricing.1 "..."` when intentionally addressing a non-zero pane.

**Key token examples (`--keys`):**
```bash
crew tell pricing --keys "Enter"            # Bare Enter
crew tell pricing --keys "Down Down Enter"  # Arrow-navigate then confirm (for menus)
crew tell pricing --keys "Escape"           # Cancel dialog
crew tell pricing --keys "C-c"             # Interrupt
```

Supported tokens: `Enter`, `Return`, `Escape`, `Tab`, `Space`, `BSpace`, `Up`, `Down`, `Left`, `Right`, `PageUp`, `PageDown`, `Home`, `End`, `F1`-`F12`, `C-<letter>` (Ctrl), `M-<letter>` (Meta/Alt).

**Examples:**
```bash
crew tell pricing "Pause. Pivoting to usage-based billing."
crew tell auth "The OAuth2 provider changed — use Auth0 instead of Okta."
crew tell pricing,billing,docs "Product renamed from 'Acme' to 'Nova'. Update all references."
crew tell auth.1 "<message>"              # Target non-default pane explicitly
```

**Multi-target:** Comma-separated. Same message sent to each target. Use for cross-cutting relays.

**Delivery verification:** For load-bearing tells, schedule a 60-second self-wake-up and verify via `crew read <target> --lines 20` that the session processed the directive.

---

## crew read

Capture pane buffer content.

```bash
crew read <targets> [--lines N] [--from N]
```

**Arguments:**
- `targets` (required) — Comma-separated targets (`window.pane` format). Bare window names accepted, default to pane 0.
- `--lines` / `-n N` — Number of lines to return. Default: full buffer.
- `--from N` — 0-based line offset. Enables paginated mode: returns lines `[N .. N+lines-1]` with a position metadata header (`lines X-Y of Z`) per target.

**Display order:** Chronological — top is oldest, bottom is newest.

**Examples:**
```bash
crew read pricing.0                              # Full buffer from Claude in pricing
crew read pricing --lines 200                    # Last 200 lines (pane 0 default)
crew read pa-service.1                           # Smithers pane in pa-service
crew read pa-service.0,pa-service.1 --lines 50  # Correlate Claude + smithers
crew read pricing.0 --from 500 --lines 100       # Paginated: lines 500-599
```

**Error:** "window/pane not found" → reconciliation signal. Run `crew list` before retrying.

---

## crew find

Search pane content for a pattern across sessions.

```bash
crew find <pattern> [<targets>] [--lines N]
```

**Arguments:**
- `pattern` (required) — Regex pattern to search for.
- `targets` (optional) — Comma-separated targets. Default: all panes in current session.
- `--lines` / `-n N` — Limit search scope to last N lines per pane. Default: full scrollback.

**Output:** Results grouped by `window.pane`, matching lines indented. Panes with no matches omitted.

```xml
<crew>
  <pane target="pricing.0">
    <match>Running AI Expert Tier 1 review...</match>
  </pane>
</crew>
```

**When to use vs crew read:**
- "Did X happen anywhere?" → `crew find` (cross-session pattern match)
- "What is session Y doing right now?" → `crew read` (targeted deep read)

**Examples:**
```bash
crew find 'review'                           # Did any session run reviews?
crew find 'Tier 1' --lines 500               # Last 500 lines per pane
crew find 'kanban done'                      # Which sessions completed cards?
crew find 'error|Error|ERROR'                # Any errors across all sessions?
crew find 'merge conflict' pricing.0,auth.0  # Search specific panes only
```

---

## crew status

Composite overview: list + read N lines from every pane.

```bash
crew status [--lines N] [--all]
```

**Arguments:**
- `--lines` / `-n N` — Lines to read per pane. Default: 100.
- `--all` / `-a` — Include all panes (not just Claude panes).

**Usage:** 10-minute pulse check. Use `--lines 20` for the periodic poll to keep context cost low. Use higher line counts for targeted investigation.

**Examples:**
```bash
crew status                    # List Claude panes + last 100 lines each
crew status --lines 20         # Lightweight pulse check (periodic poll)
crew status --lines 50         # Moderate read per pane
crew status --all              # Include all panes
```

---

## crew dismiss

Kill target tmux window(s) or pane(s). Scoped to the current tmux session.

```bash
crew dismiss <targets>
```

**Arguments:**
- `targets` (required) — Comma-separated bare window names (e.g., `pricing`) or `window.pane` for individual panes. No `session:` prefix.

**Safety:**
- Scoped to current tmux session only — cannot dismiss windows in other sessions.
- Cannot dismiss the current window (sstaff's own window) — errors out.
- Uses stable `@<id>` window IDs internally — bulk dismissals work correctly.

**Trigger conditions (all three required before dismissing):**
1. Staff session reports work complete.
2. Outputs verified via `crew read` or hook state.
3. Any mandatory review cards for that session are done.

**Examples:**
```bash
crew dismiss pricing              # Dismiss single window after work verified
crew dismiss pricing,auth         # Bulk dismiss multiple completed sessions
```

---

## Format and Exit Codes

**Output format:** All subcommands that produce structured output accept `--format xml` (default), `--format json`, or `--format human`. Always use `xml` for AI coordination — machine-parseable and unambiguous.

**Exit codes:**
- `0` — Success
- `1` — Execution error (window/pane not found, worktree failure, partial state)
- `2` — Argument error (invalid name, duplicate window, missing required argument)

**Quirks and conventions:**
- `crew tell` default: bare window name targets pane 0. Explicit `window.pane` for non-zero panes.
- `crew create` default spawn: `staff --name <name>` (not `claude`). Override with `--cmd <other>`.
- `crew list` / `crew status` scope: current tmux session only — no cross-session visibility.
- `--format` is `crew`'s flag; `kanban` uses `--output-style` (not `--format`). Do not confuse them.
- No `--human` shorthand — use `--format human` if human-readable output is ever needed (not recommended for AI coordination).
