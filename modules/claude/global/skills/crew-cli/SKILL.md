---
name: crew-cli
description: crew CLI full command reference. Auto-load when about to run any crew subcommand and need exact arguments, flag syntax, or error handling. Covers all subcommands: create, list, tell, read, find, status, dismiss, sessions, resume, project-path, smithers. Includes --format flag behavior, exit code table, pane targeting rules (window vs window.pane), multi-target comma syntax, and crew create vs crew tell sequencing discipline. This skill is the canonical source for all crew CLI syntax — no external pointer needed.
---

# crew CLI — Full Command Reference

Exhaustive reference for all `crew` subcommands. Senior Staff uses these in production — no `--help` lookups, no permission asks, no syntax mistakes.

**Top-level syntax:**
```bash
crew [-h] [--format {xml,json,human}] {list,tell,read,dismiss,find,create,status,sessions,resume,project-path,smithers} ...
```

**Global flag:**
- `--format` / `-f` — Output format: `xml` (default), `json`, or `human`. Applies to subcommands that produce structured output. Always use `xml` (machine-parseable); never `human`.

---

## `crew create`
`crew create <name> [--repo <path>] [--branch <branch>] [--base <base-branch>] [--tell "<message>" | --tell-file PATH] [--no-worktree] [--mcp-trust {all|this|none}]`

End-to-end staff session creation — worktree, tmux window, and Claude instance in one command.

```bash
crew create <name> [--repo <path>] [--branch <branch>] [--base <base-branch>] [--tell "<message>" | --tell-file PATH] [--no-worktree] [--mcp-trust {all|this|none}]
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
  - `all` — trust this and all future MCP servers in this project (option 1)
  - `this` — trust only this MCP server (option 2)
  - `none` — continue without using this MCP server (option 3)
  - Does NOT affect workspace-trust handling (always auto-accepted as 'Yes').

**Behavior:**
- Default spawn command is `staff --name <name>`, NOT `claude --name <name>`. The created window is a Staff Engineer session.
- `--tell` delivers the initial brief in the same call — no separate `crew tell` needed.
- `--tell-file PATH` reads the brief from a file. The file is deleted automatically after successful delivery. If delivery fails (e.g., Claude Code didn't start), the file is preserved so you can retry.
- Use `--cmd <other>` to override the spawn command when not using `staff`.

**Modal auto-handling (startup modals):**
When `--tell` or `--tell-file` is used, `crew create` must wait for Claude Code to become ready before delivering the brief. During this wait, two categories of startup modals are automatically dismissed so they do not block delivery:
- **Workspace-trust modal** (`Accessing workspace: ... Yes, I trust this folder`) — always answered with `1` (Yes, trust). The worktree was just created by `crew create`; trust is implicit.
- **MCP server trust modal** (`New MCP server found in .mcp.json: ...`) — answered per `--mcp-trust` flag (`all`→1, `this`→2, `none`→3). Multiple MCP modals chain correctly — each is answered in sequence.
- **Unknown modals** — if a numbered-choice + `Enter to confirm` prompt appears but does not match either known signature, it is NOT auto-dismissed. A warning is emitted to stderr and the wait loop continues; the `--tell` delivery will time out and report `told="false"` if the modal is not manually cleared.

**Post-switch hook:**
After `git worktree add` and before launching the staff session, `crew create` automatically runs the repository's `.git/workout-hooks/post-switch` script if it exists and is executable. This mirrors the legacy `workout` CLI behavior so spawned worktrees are fully initialized (e.g., `mise trust`, `pnpm bootstrap`) before Staff starts work.

- **When it runs:** After worktree creation, before tmux window open. Skipped when `--no-worktree` is used.
- **Env vars passed:** `WORKTREE_PATH` (new worktree absolute path), `SOURCE_REPO` (source repo absolute path), `BRANCH` (branch checked out). Note: the reference implementation at `maze-monorepo/.git/workout-hooks/post-switch` currently uses only `cwd` (runs `mise trust --yes && pnpm bootstrap`) and does not consume these env vars. The vars are provided as a forward-looking contract for hooks that need them.
- **Absent hook:** Silent no-op — no error, no output. Proceed as normal.
- **Non-zero exit:** `crew create` emits `POST_SWITCH_HOOK_FAILED` error (exit 1) with the hook's exit code and last 20 lines of output. Staff session is NOT launched — worktree setup is incomplete.

**Examples:**
```bash
crew create pricing                                                     # Branch + worktree + window all named "pricing"
crew create pricing --tell "Implement tiered billing model."            # Create + deliver initial brief in one call
crew create pricing --tell-file /tmp/brief.txt                         # Create + deliver brief from file (file auto-deleted on success)
crew create auth --base main                                            # Create from main instead of current branch
crew create docs --repo ~/worktrees/other-project/main                 # Create in a different repo
crew create payment --branch payment-v2                                 # Window named "payment", branch "payment-v2"
crew create hotfix --no-worktree                                        # Work directly in repo without creating a worktree (hook skipped)
crew create pricing --tell "Build auth" --mcp-trust all                 # Trust all future MCPs (default)
crew create pricing --tell "Build auth" --mcp-trust this                # Trust only the prompting MCP
crew create pricing --tell "Build auth" --mcp-trust none                # Skip MCP server usage
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

**XML output schema** (default format — use this when parsing status programmatically):

Single-pane window (staff engineer only, no smithers split):
```xml
<status lines="20">
  <window name="feature-auth">
    <pane index="0" command="2.1.100" crew="feature-auth.0">...captured output...</pane>
  </window>
</status>
```

Multi-pane window (staff engineer in pane 0, smithers in pane 1):
```xml
<status lines="20">
  <window name="pricing">
    <pane index="0" command="2.1.100" crew="pricing.0">...captured output...</pane>
    <pane index="1" command="smithers" crew="pricing.1">...captured output...</pane>
  </window>
</status>
```

Attribute reference:
- `<status lines="N">` — N is the `--lines` value passed to the command
- `<window name="...">` — bare window name (no session prefix); groups panes in the same window
- `<pane index="...">` — tmux pane index within the window (0-based string)
- `<pane command="...">` — `pane_current_command` as reported by tmux (e.g., `2.1.100`, `smithers`, `zsh`)
- `<pane crew="window.pane">` — crew address for use as a target in `crew tell`, `crew read`, etc.
- pane text content — last N lines of scrollback from that pane

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

**Behavior:**
- Default (no flags): scans all windows in the current tmux session, resolves each pane's working directory to a Claude project key (`~/.claude/projects/<key>/`), and lists `.jsonl` session files sorted by most-recently-modified first.
- With `--window <name>`: restricts to that single window. Window must exist in the current tmux session; exits 1 (`WINDOW_NOT_FOUND`) if not found.
- With `--worktree <path>`: bypasses tmux lookup entirely — scans the projects directory for the given path.
- Session files are sorted by mtime descending (most recent first).
- Output is buffered and emitted atomically after all windows are scanned.

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

**Behavior:**
1. Validates `name` against the filesystem-safe name regex.
2. Aborts if a tmux window named `<name>` already exists (error: `WINDOW_EXISTS`).
3. Resolves the worktree path: first checks active tmux windows (cross-session), then falls back to `~/worktrees/<name>`.
4. Scans `~/.claude/projects/<key>/` for `.jsonl` session files.
5. If `--session` not given, picks the most recent `.jsonl` by mtime.
6. Emits a warning if multiple sessions exist and the most recent was picked.
7. Creates a new tmux window: `tmux new-window -n <name> -c <worktree_path> -d`.
8. Launches: `staff --name <name> --resume <session_id>` via tmux send-keys.
9. Emits structured success output.

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
crew project-path <worktree> [--format xml|json|human]
```

**Arguments:**
- `worktree` (required) — Path to the worktree directory. Use `.` for the current working directory. Accepts absolute paths or `~`-prefixed paths.

**Behavior:**
- Resolves `.` to `cwd` via `os.getcwd()`.
- Mangles the path to a project key: replaces every `/` with `-` (Claude Code's path mangling scheme).
- Checks if `~/.claude/projects/<key>/` exists.
- Lists any `.jsonl` session files in that directory, sorted by mtime descending.
- Does NOT modify any files — read-only diagnostic command.

**Path mangling:** Claude Code converts a worktree path to a project key by replacing every `/` with `-`. Example: `/Users/me/worktrees/pricing` → `-Users-me-worktrees-pricing`. The project directory is then `~/.claude/projects/-Users-me-worktrees-pricing/`.

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

## crew smithers

Drop a smithers pane into a crew member's tmux window. **sstaff-only** — staff engineers do not invoke this command.

```bash
crew smithers <name> [--format xml|json|human]
```

**Arguments:**
- `name` (required) — Crew member window name (the tmux window where smithers should run).

**Behavior:**
1. Looks up the window by name.
2. Checks the window's current pane count:
   - **No split (pane 0 only):** Creates a 25% bottom split (`split-window -v -l 25%`) matching the `prefix+s` tmux keybinding, sets cwd to pane 0's working directory (the worktree), then runs `smithers` in the new pane. smithers auto-detects the PR from the worktree's current branch — no arguments needed.
   - **Split exists + smithers running:** Reports `smithers already running in pane <name>.<index>` and returns success (idempotent).
   - **Split exists but NOT running smithers:** Returns error with `AMBIGUOUS_PANE_STATE` — refuses to overwrite so the user can decide.
3. Emits structured output on success.

**When to use:** After a staff session creates a draft PR and the user says "run smithers on it". sstaff invokes `crew smithers <name>` to drop smithers into the staff session's window alongside the staff engineer.

**Output (XML default):**
```xml
<!-- started -->
<smithers status="started" window="pricing" pane="1" message="started smithers in pane pricing.1" />

<!-- already running -->
<smithers status="already-running" window="pricing" pane="1" message="smithers already running in pane pricing.1" />
```

**Examples:**
```bash
crew smithers pricing          # Drop smithers pane into the pricing window
crew smithers auth             # Drop smithers pane into the auth window
crew smithers pricing --format json  # JSON output
```

**Exit codes:**
- `0` — Success (started or already-running)
- `1` — Error (window not found, ambiguous pane state, split failed)

**Error codes:**
- `WINDOW_NOT_FOUND` — No tmux window with the given name exists
- `AMBIGUOUS_PANE_STATE` — Extra pane(s) exist but none are running smithers
- `SPLIT_FAILED` — tmux split-window failed
- `SEND_KEYS_FAILED` — Could not send the smithers command to the new pane

---

## Format and Exit Codes

**Output format:** Applies to subcommands that produce structured output: `crew list`, `crew read`, `crew find`, `crew status`, `crew sessions`, `crew resume`, `crew project-path`. These accept `--format xml` (default), `--format json`, or `--format human`. Always use `xml` for AI coordination — machine-parseable and unambiguous.

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
- `--tell-file` auto-delete: the file at PATH is deleted **only after all targets receive successfully**. For `crew create`, delivery is verified by the tell-verification logic (`told=true`). For `crew tell`, delivery is verified by checking that every `tmux send-keys` subprocess exits 0. If any delivery fails, the file is **preserved** — you can retry without re-creating the file. This mirrors `kanban do --file` auto-delete semantics. If the file does not exist or is unreadable at invocation time, the command fails immediately with `TELL_FILE_ERROR` (exit code 1).
