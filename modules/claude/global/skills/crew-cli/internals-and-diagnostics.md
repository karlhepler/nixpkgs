# crew CLI — Tool Internals and Diagnostics

Descriptions of what the `crew` binary does internally, for reasoning about a `crew` invocation that behaved unexpectedly: the startup-modal poll loop behind `crew create --tell`, the `post-switch` worktree hook contract, the `crew status` XML schema and attribute reference, the window-scan behavior behind `crew sessions`, the nine-step `crew resume` algorithm, the path-mangling behavior behind `crew project-path`, and the spinner/loop pattern matching behind `crew active`. None of this is needed to invoke a `crew` subcommand correctly — every invocation, flag, exit code, and error code stays in `SKILL.md`. Read this file from `SKILL.md` (source: `modules/claude/global/skills/crew-cli/internals-and-diagnostics.md`) when a command produced output you did not expect, when a `--tell` brief was dropped, or when extending `crew` itself.

---

## `crew create` — startup modals and the worktree hook

**Modal auto-handling (startup modals):**
When `--tell` or `--tell-file` is used, `crew create` must wait for Claude Code to become ready before delivering the brief. During this wait, two categories of startup prompts are automatically dismissed so they do not block delivery:
- **Folder-trust prompt** (`Quick safety check: Is this a project you created or one you trust? 1. Yes, I trust this folder / 2. No, exit`) — this is Claude Code's ONE-TIME first-run check for a never-before-opened project directory (e.g. a freshly cloned repo). Answered per `--trust-folder` flag (`yes`→1/Enter, `no`→2/Down+Enter). Checked FIRST in the poll loop — it is the earliest prompt Claude Code can show, gating everything else including whether `.mcp.json` is even read.
- **MCP server trust modal** (`New MCP server found in .mcp.json: ...`) — answered per `--mcp-trust` flag (`all`→2/Down+Enter, `this`→1/Enter, `none`→3/Down+Down+Enter). Multiple MCP modals chain correctly — each is answered in sequence.
- **Unknown modals** — if a numbered-choice + `Enter to confirm` prompt appears but does not match either known signature, it is NOT auto-dismissed. A warning is emitted to stderr and the wait loop continues; the `--tell` delivery will time out and report `told="false"` if the modal is not manually cleared.

**Post-switch hook:**
After `git worktree add` and before launching the staff session, `crew create` automatically runs the repository's `.git/workout-hooks/post-switch` script if it exists and is executable. This mirrors the legacy `workout` CLI behavior so spawned worktrees are fully initialized (e.g., `mise trust`, `pnpm bootstrap`) before Staff starts work.

- **When it runs:** After worktree creation, before tmux window open. Skipped when `--no-worktree` is used.
- **Env vars passed:** `WORKTREE_PATH` (new worktree absolute path), `SOURCE_REPO` (source repo absolute path), `BRANCH` (branch checked out). Note: the reference implementation at `maze-monorepo/.git/workout-hooks/post-switch` currently uses only `cwd` (runs `mise trust --yes && pnpm bootstrap`) and does not consume these env vars. The vars are provided as a forward-looking contract for hooks that need them.
- **Absent hook:** Silent no-op — no error, no output. Proceed as normal.
- **Non-zero exit:** `crew create` emits `POST_SWITCH_HOOK_FAILED` error (exit 1) with the hook's exit code and last 20 lines of output. Staff session is NOT launched — worktree setup is incomplete.

---

## `crew status` — XML schema and attribute reference

**XML output schema** (default format — use this when parsing status programmatically):

Single-pane window (staff engineer only, no smithers split):
```xml
<status lines="20">
  <window name="feature-auth">
    <pane index="0" command="2.1.100" crew="feature-auth.0">...captured output...</pane>
  </window>
</status>
```

Multi-pane window (typical example — staff engineer in pane 0, smithers in pane 1; pane indices are not guaranteed):
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

## `crew sessions` — window scan behavior

**Behavior:**
- Default (no flags): scans all windows in the current tmux session, resolves each pane's working directory to a Claude project key (`~/.claude/projects/<key>/`), and lists `.jsonl` session files sorted by most-recently-modified first.
- With `--window <name>`: restricts to that single window. Window must exist in the current tmux session; exits 1 (`WINDOW_NOT_FOUND`) if not found.
- With `--worktree <path>`: bypasses tmux lookup entirely — scans the projects directory for the given path.
- Session files are sorted by mtime descending (most recent first).
- Output is buffered and emitted atomically after all windows are scanned.

---

## `crew resume` — resolution and launch algorithm

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

---

## `crew project-path` — resolution and path mangling

**Behavior:**
- Resolves `.` to `cwd` via `os.getcwd()`.
- Mangles the path to a project key: replaces every `/` with `-` (Claude Code's path mangling scheme).
- Checks if `~/.claude/projects/<key>/` exists.
- Lists any `.jsonl` session files in that directory, sorted by mtime descending.
- Does NOT modify any files — read-only diagnostic command.

**Path mangling:** Claude Code converts a worktree path to a project key by replacing every `/` with `-`. Example: `/Users/me/worktrees/pricing` → `-Users-me-worktrees-pricing`. The project directory is then `~/.claude/projects/-Users-me-worktrees-pricing/`.

---

## `crew active` — spinner and loop pattern matching

**Active detection (recent lines only — NOT scrollback):**
- `claude-thinking`: A Claude Code spinner verb (e.g. `Brewing`, `Architecting`, `Crystallizing`) appears alongside a spinner glyph (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏ · ✻ ✳ ✶`) on one of the last 2 visible pane lines.
- `smithers`: Smithers/Ralph loop-control output (`Cycle N/M`, `ITERATION N`, `Waiting for CI checks`) appears on a recent line.

Historical completion markers like `✻ Baked for 13m 13s` in scrollback do NOT trigger active classification — only the last 2 visible lines are examined for active-work indicators.

**Idle detection:**
- `claude-empty`: Claude pane at empty prompt (`❯` with nothing after it).
- `shell`: Shell prompt with no foreground command.
- `unknown`: Does not match any known pattern.

**`--names-only` output:**
```
results-rescue
deliver-carve
```
