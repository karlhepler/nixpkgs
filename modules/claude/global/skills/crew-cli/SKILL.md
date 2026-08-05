---
name: crew-cli
description: crew CLI full command reference. Auto-load when about to run any crew subcommand and need exact arguments, flag syntax, or error handling. Covers all subcommands: list, tell, read, dismiss, find, create, status, project-path, resume, sessions, active, smithers. Includes --format flag behavior, exit code table, pane targeting rules (window vs window.pane), multi-target comma syntax, and crew create vs crew tell sequencing discipline. This skill is the canonical source for all crew CLI syntax — every invocation, flag, and exit code is inline here; tool-internal behavior for diagnosing unexpected output lives in the companion internals-and-diagnostics.md.
---

# crew CLI — Full Command Reference

Exhaustive reference for all `crew` subcommands. Senior Staff uses these in production — no `--help` lookups, no permission asks, no syntax mistakes.

> **Drift warning:** This skill can drift from the installed binary. The installed `crew` binary is the source of truth — verify any subcommand exists via `crew --help` before asserting or relying on its behavior. Do not trust this skill's subcommand list blindly; run `crew --help` to confirm.

**Top-level syntax:**
```bash
crew [-h] [--format {xml,json,human}] {list,tell,read,dismiss,find,create,status,sessions,resume,project-path,active,smithers} ...
```

**Global flag:**
- `--format` / `-f` — Output format: `xml` (default), `json`, or `human`. Applies to subcommands that produce structured output. Default is `xml` (machine-parseable) — omit the flag in the common case. Only override with `--format json` when parsing requires JSON. Never use `--format human` for AI coordination — it breaks parseability.

---

## `crew create`
`crew create <name> [--repo <path>] [--branch <branch>] [--base <base-branch>] [--tell "<message>" | --tell-file PATH] [--no-worktree] [--mcp-trust {all|this|none}] [--trust-folder {yes|no}]`

End-to-end staff session creation — worktree, tmux window, and Claude instance in one command.

```bash
crew create <name> [--repo <path>] [--branch <branch>] [--base <base-branch>] [--tell "<message>" | --tell-file PATH] [--no-worktree] [--mcp-trust {all|this|none}] [--trust-folder {yes|no}]
```

**Arguments:**
- `name` (required) — Session name. Used for the tmux window name, worktree directory (`~/worktrees/<name>`), and branch name.
- `--repo <path>` — Path to the git repository. Default: current repo via `git rev-parse --show-toplevel`.
- `--branch <branch>` — Branch name for the new worktree. Default: `<name>`. Incompatible with `--no-worktree`.
- `--base <base-branch>` — Base branch to create the new branch from. Default: current branch of the repo. Incompatible with `--no-worktree`.
- `--tell "<message>"` — Initial brief delivered to the session immediately after spawn. Single-call create + brief. Use this instead of a separate `crew tell` call. Mutually exclusive with `--tell-file`.
- `--tell-file PATH` — Alternative to `--tell` — read tell message from file (UTF-8). File is auto-deleted on successful delivery (mirrors `kanban do --file`). Mutually exclusive with `--tell`.
- `--no-worktree` — Spawn a staff session directly in `<repo>` without creating a new worktree or branch. Use for "work directly on main" or existing-branch workflows. Incompatible with `--branch` and `--base`.
- `--cmd <command>` — Override the spawn command. Default: `staff --name <name>`. Use when the target session should run something other than `staff`.
- `--mcp-trust {all|this|none}` — How to respond to MCP server trust modals that appear during startup (default: `all`):
  - `all` — trust this and all future MCP servers in this project (option 2)
  - `this` — trust only this MCP server (option 1, pre-selected)
  - `none` — continue without using this MCP server (option 3)
  - Separate from `--trust-folder` below — these are two distinct startup prompts.
- `--trust-folder {yes|no}` — How to respond to Claude Code's one-time first-run folder-trust prompt (`Is this a project you created or one you trust?`) that appears the first time a project directory is ever opened — e.g. a freshly cloned repo (default: `yes`):
  - `yes` — trust this folder and proceed (option 1, pre-selected). The worktree was just created by `crew create`; trust is implicit.
  - `no` — decline and exit (Claude Code will not start). Escape hatch only — never use this as a default, it would auto-exit every freshly-created worktree.
  - **Caveat:** the default `yes` posture assumes the target repo path has already been vetted by the caller — `crew` has no clone/network path and only ever operates on a local path already on disk, but auto-trusting that path is only as safe as the caller's vetting of it.

**Behavior:**
- Default spawn command is `staff --name <name>`, NOT `claude --name <name>`. The created window is a Staff Engineer session.
- `--tell` delivers the initial brief in the same call — no separate `crew tell` needed.
- `--tell-file PATH` reads the brief from a file. The file is deleted automatically after successful delivery. If delivery fails (e.g., Claude Code didn't start), the file is preserved so you can retry.
- Use `--cmd <other>` to override the spawn command when not using `staff`.

**Recovery when `told="false"` and the folder-trust prompt is the blocker:**
This prompt can silently drop a `--tell` brief — the session never reaches the `auto mode on` ready sentinel. Once the poll thread detects the folder-trust prompt, `folder_trust_detected` is set unconditionally and the auto-answer attempt always fires — `--trust-folder` only selects which keystroke sequence is sent (`yes` vs `no`), not whether the attempt happens. So `told_reason` reads `folder-trust prompt detected and auto-answered (--trust-folder 'no')` (or `'yes'`) whenever the prompt was seen at all, including when `--trust-folder no` was passed. The generic `session never reported ready` reason only occurs when the folder-trust prompt was never detected before the wait ceiling — a fast race where the deadline is exceeded before the poll thread ever checks. To recover manually:
1. `crew read <name>` — confirm the pane shows the folder-trust prompt (`Is this a project you created or one you trust?`).
2. `crew tell <name> --keys "Enter"` — accept option 1 (Yes, I trust this folder).
3. Wait for the `auto mode on` status bar (poll with `crew read <name> --lines 5` or `crew active`).
4. Re-deliver the brief with a standalone `crew tell <name> "<brief>"` — the original `--tell` payload was dropped, not queued, so it must be resent.

**Examples:**
```bash
crew create pricing                                                     # Branch + worktree + window all named "pricing"
crew create pricing --tell "Implement tiered billing model."            # Create + deliver initial brief in one call
crew create pricing --tell-file /tmp/brief.txt                         # Create + deliver brief from file (file auto-deleted on success)
crew create auth --base main                                            # Create from main instead of current branch
crew create docs --repo ~/worktrees/other-project/main                 # Create in a different repo
crew create payment --branch payment-v2                                 # Window named "payment", branch "payment-v2"
crew create hotfix --no-worktree                                        # Work directly in repo without creating a worktree (post-switch hook skipped)
crew create pricing --tell "Build auth" --mcp-trust all                 # Trust all future MCPs (default)
crew create pricing --tell "Build auth" --mcp-trust this                # Trust only the prompting MCP
crew create pricing --tell "Build auth" --mcp-trust none                # Skip MCP server usage
crew create newrepo --repo ~/worktrees/never-opened --tell "Start"     # Freshly cloned repo: folder-trust prompt auto-dismissed (--trust-folder yes is the default)
```

**Error handling:**
- Duplicate tmux window name → exit 2 (check: `crew list`)
- Invalid name (spaces, slashes, shell chars) → exit 2
- Existing worktree at `~/worktrees/<name>` → exit 2
- Branch creation fails → exit 1, worktree not created
- Post-switch hook exits non-zero → exit 1 (`POST_SWITCH_HOOK_FAILED`), staff NOT launched, worktree left intact
- tmux window fails after worktree created → exit 1, worktree left intact (partial state — do NOT auto-remove)

---

## crew list

Enumerate tmux windows and panes. Scoped to the current tmux session only.

```bash
crew list [--all] [--format json|human]
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
crew list --format json      # Override default; useful when piping to a JSON parser
```

---

## crew tell

Send input to one or more specific pane(s).

```bash
crew tell <targets> "<message>" [--keys]
crew tell <targets> --tell-file PATH [--keys]
```

**Arguments:**
- `targets` (required) — Comma-separated targets. Bare window names are accepted and default to pane 0. `window.pane` format for explicit non-zero panes.
- `message` (optional) — Text to send (literal text + Enter by default), or space-separated tmux key tokens (with `--keys`). Required unless `--tell-file` is given.
- `--keys` — Interpret message as tmux key tokens instead of literal text. No Enter appended automatically.
- `--tell-file PATH` — Alternative to the positional message — read tell body from PATH (UTF-8). File is auto-deleted on successful delivery (mirrors `kanban do --file`). Mutually exclusive with the positional message argument.

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
crew tell pricing --tell-file /tmp/brief.txt   # Send from file; file auto-deleted on delivery
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
crew read pricing.1                              # Smithers pane in pricing
crew read pricing.0,pricing.1 --lines 50        # Correlate Claude + smithers
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

**Output:** XML by default. Every `<pane>` carries a `crew="window.pane"` address — use it verbatim as a `crew tell` / `crew read` target.

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

## crew sessions

List Claude session IDs for tmux windows in the current session. Used to find a session ID before `crew resume`.

```bash
crew sessions [--window <name>] [--worktree <path>] [--format xml|json|human]
```

**Arguments:**
- `--window <name>` — Restrict to sessions for this single tmux window name. Window must exist in current tmux session — exits 1 (`WINDOW_NOT_FOUND`) if not. If the window is found but has no Claude sessions, emits a warning (not an error).
- `--worktree <path>` — Use an explicit worktree path instead of tmux window lookup. Bypasses the window-to-path resolution step entirely.

**Output (XML default):**
```xml
<sessions>
  <session window="pricing" worktree="/Users/me/worktrees/pricing" id="<uuid>" modified="2026-04-22T10:00:00" />
  <session window="auth" worktree="/Users/me/worktrees/auth" id="<uuid>" modified="2026-04-21T14:30:00" />
</sessions>
```

**Examples:**
```bash
crew sessions                              # All windows in current session
crew sessions --window pricing             # Sessions for the pricing window only
crew sessions --window pricing --format json  # JSON output
crew sessions --worktree ~/worktrees/auth  # Explicit path bypass
```

**Error handling:**
- `--window <name>` window not found → exit 1, error code `WINDOW_NOT_FOUND`
- Window found but no `.jsonl` files → warning embedded in XML output as `<warning message='...'/>` element within `<sessions/>` root (not an error; other formats emit warning to stderr)
- Filesystem error reading sessions dir → exit 1

**When to use:** Run before `crew resume` when you need to list available session IDs for a window, or when you need to verify which session is the most recent.

---

## crew resume

Recreate a killed tmux window and resume its Claude session in one call.

```bash
crew resume <name> [--session <id>] [--format xml|json|human]
```

**Arguments:**
- `name` (required) — Window name. Must match a worktree in `~/worktrees/<name>` or an active tmux window with that name. Must be filesystem-safe (alphanumeric, hyphens, underscores only).
- `--session <id>` — Explicit session UUID to resume. Default: most recent `.jsonl` file by mtime. Use `crew sessions --window <name>` to list available IDs.

**Note:** Worktree resolution is intentionally cross-session (unlike other crew subcommands). On recovery, the originating tmux session may no longer exist — so `crew resume` scans all tmux windows first, then falls back to `~/worktrees/<name>`.

**Output (XML default):**
```xml
<resumed window="pricing" session="<uuid>" worktree="/Users/me/worktrees/pricing" command="staff --name pricing --resume <uuid>" />
```

**Examples:**
```bash
crew resume pricing                        # Infer most recent session
crew resume pricing --session <uuid>       # Explicit session ID
crew resume auth --format json             # JSON output
```

**Error handling:**
- Window already exists → exit 1, error code `WINDOW_EXISTS` (dismiss first or choose a different name)
- Worktree not found (no active window and no `~/worktrees/<name>`) → exit 1, error code `WORKTREE_NOT_FOUND`
- Explicit `--session <id>` file not found → exit 1, error code `NO_SESSION`
- No session files at all for the worktree → exit 1, error code `NO_SESSION`
- tmux window creation fails → exit 1, error code `TMUX_WINDOW_FAILED`
- Invalid name (spaces, slashes, etc.) → exit 1, error code `INVALID_NAME`

**Warning (non-fatal):** Multiple sessions found — most recent selected. Message printed to stderr in XML/JSON modes; includes list of other candidate IDs.

---

## crew project-path

Resolve a worktree path to its Claude Code project directory key. Shows the mangled key Claude uses to store session files and lists any `.jsonl` session files found there.

```bash
crew project-path <worktree> [--format json|human]
```

**Arguments:**
- `worktree` (required) — Path to the worktree directory. Use `.` for the current working directory. Accepts absolute paths or `~`-prefixed paths.

**Output (XML default):**
```xml
<project-path worktree="/Users/me/worktrees/pricing" key="-Users-me-worktrees-pricing" sessions_dir_exists="true">
  <session id="<uuid>" mtime="2026-04-22T10:00:00" />
  <session id="<uuid>" mtime="2026-04-21T08:00:00" />
</project-path>
```

**Examples:**
```bash
crew project-path .                              # Current directory
crew project-path ~/worktrees/pricing            # Explicit path
crew project-path ~/worktrees/pricing --format json  # JSON output
```

**Error handling:**
- Path does not exist → exit 1, error code `PATH_NOT_FOUND`
- Path exists but is not a directory → exit 1, error code `NOT_A_DIRECTORY`

**When to use:** Debugging session file locations when `crew sessions` doesn't find what you expect, or when manually locating session files for a given worktree.

---

## crew active

Classify each pane in the current tmux session as active or idle based on spinner-verb and loop-pattern detection. Reports which windows have at least one active pane.

```bash
crew active [--names-only] [--format xml|json|human]
```

**Arguments:**
- `--names-only` — Print just the names of windows with at least one active pane, one per line. Intended for shell-script consumers. `--names-only` takes precedence; if both are provided, `--format` is silently ignored.

**Window-level aggregation:** A window is reported as active if ANY of its panes is active.

**Output (XML default):** Only active windows are included in the `<active>` root element.

```xml
<active>
  <window name="results-rescue">
    <pane index="0" state="active" activity="claude-thinking" verb="Brewing" />
    <pane index="1" state="idle" prompt="shell" />
  </window>
  <window name="deliver-carve">
    <pane index="0" state="idle" prompt="claude-empty" />
    <pane index="1" state="active" activity="loop" detail="Cycle 3/10" />
  </window>
</active>
```

**Examples:**
```bash
crew active                          # XML: active windows and pane states
crew active --names-only             # Names of active windows, one per line
crew active --format json            # JSON output
crew active --format human           # Human-readable output
```

**When to use vs `crew list`:**
- `crew list` — shows all windows and panes that exist (presence).
- `crew active` — shows which of those windows currently have a pane doing work (activity).

**Common use cases:**
- Before CronDelete: run `crew active --names-only` to verify all panes are idle before deleting the pulse cron. If any output appears, leave the cron running.
- Post-dismiss verification: after `crew dismiss <name>`, run `crew active --names-only` to confirm the remaining sessions have no active panes before concluding the workstream is fully idle.

---

## crew smithers

Drop a smithers pane into a crew member's tmux window: a bottom split running the `smithers` loop, below the crew member's own Claude session pane.

```bash
crew smithers <name>
```

**Arguments:**
- `<name>` — Crew member window name (the tmux window where smithers should be launched).

**What it does:**
- Creates a 25% bottom split in the target window (`tmux split-window -v -l 25%`) — same geometry as the user's own `prefix+s` keybinding (`modules/tmux/default.nix`).
- The new pane's working directory is set with `-c "#{pane_current_path}"`, inheriting pane 0's cwd (the crew member's worktree). This is load-bearing: `smithers` auto-detects its target PR from the current working directory, so without path inheritance it would resolve the wrong PR or none at all.
- Sends bare `smithers` (no arguments) to the new pane — no PR needs to be passed explicitly.

**Idempotency contract (one smithers per window):**
- No split exists → create the split and start smithers.
- Split exists AND is running smithers → report already-running, exit `0` (no-op — safe to re-invoke).
- Split exists but NOT running smithers → refuse with an error (ambiguous state) rather than overwriting the foreign pane.
- Target window not found → error.

**Scope:** `crew smithers` is sstaff-only. Staff engineers do not invoke it directly — sstaff uses it after a staff session has created a draft pull request, to hand the pull request off to the smithers review/iterate loop.

**Examples:**
```bash
crew smithers pricing          # start smithers in the pricing window
crew smithers auth             # start smithers in the auth window
```

---

## Tool Internals and Diagnostics (Reference)

The startup-modal poll loop behind `crew create --tell`, the `post-switch` worktree-hook contract, the `crew status` XML schema and attribute reference, the window-scan behavior behind `crew sessions`, the nine-step `crew resume` algorithm, the path-mangling behavior behind `crew project-path`, and the spinner/loop pattern matching behind `crew active` describe what the binary does internally — not needed to invoke any subcommand, since every invocation, flag, exit code, and error code is inline above. Read `~/.claude/skills/crew-cli/internals-and-diagnostics.md` (source: `modules/claude/global/skills/crew-cli/internals-and-diagnostics.md`) when a command produced output you did not expect, when a `--tell` brief was dropped, or when extending `crew` itself.

---

## Format and Exit Codes

**Output format:** Applies to subcommands that produce structured output: `crew list`, `crew read`, `crew find`, `crew status`, `crew sessions`, `crew resume`, `crew project-path`, `crew active`. Default output is XML — omit `--format` in the common case. Override with `--format json` when downstream parsing requires JSON. Never use `--format human` for AI coordination — it breaks parseability.

**Exit codes:**
- `0` — Success
- `1` — Execution error (window/pane not found, worktree failure, partial state)
- `2` — Argument error (invalid name, duplicate window, missing required argument)

**Quirks and conventions:**
- `crew active` empty result: when no windows are active, `crew active` exits 0 with an empty `<active/>` element (not exit 1). Use `crew active --names-only` output presence (non-empty stdout) as the activity signal, not the exit code.
- `crew tell` default: bare window name targets pane 0. Explicit `window.pane` for non-zero panes.
- `crew create` default spawn: `staff --name <name>` (not `claude`). Override with `--cmd <other>`.
- `crew list` / `crew status` scope: current tmux session only — no cross-session visibility.
- `--format` is `crew`'s flag; `kanban` uses `--output-style` (not `--format`). Do not confuse them.
- No `--human` shorthand — use `--format human` if human-readable output is ever needed (not recommended for AI coordination).
- `--tell-file` auto-delete: the file at PATH is deleted **only after all targets receive successfully**. For `crew create`, delivery is verified by the tell-verification logic (`told=true`). For `crew tell`, delivery is verified by checking that every `tmux send-keys` subprocess exits 0. If any delivery fails, the file is **preserved** — you can retry without re-creating the file. This mirrors `kanban do --file` auto-delete semantics. If the file does not exist or is unreadable at invocation time, the command fails immediately with `TELL_FILE_ERROR` (exit code 1).
