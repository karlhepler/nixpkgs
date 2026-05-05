# HMS — Home Manager Switch: Authoritative Reference

This document is written for Claude Code coordinators and staff engineers who need
an accurate semantic model of `hms` and its sibling shellapps. It is derived
entirely from reading the source files; every claim is traceable to a specific
file and line.

**Sources read:** `modules/system/hms.bash`, `modules/system/default.nix`,
`modules/zsh.nix`, `home.nix`, `user.nix`, `overconfig.nix`, `flake.nix`,
`modules/lib/shellApp.nix`.

---

## Purpose and One-Paragraph Behavior Summary

`hms` (Home Manager Switch) is the single deployment command for this Nix
configuration. When invoked, it: validates `user.nix` is present and free of
placeholder values; creates timestamped backups of `user.nix` and
`overconfig.nix`; temporarily un-hides those files from git so Home Manager can
read them; runs `home-manager switch --flake ~/.config/nixpkgs` to build and
activate the full configuration; installs or enforces pinned versions of
out-of-Nix tools (Claude Code, Ralph Orchestrator); configures local git identity
for this repository; and — as a post-switch side effect from the Home Manager
activation hooks — re-hides `user.nix` and `overconfig.nix` from git tracking.
The `--purge` flag adds one additional step: after all of the above (regardless of
success or failure), it kills the tmux server via an EXIT trap, closing every
active tmux session.

---

## Shellapp Construction

`hms` is **not** a raw bash script on `$PATH`. It is a Nix `writeShellApplication`
derivation assembled in `modules/system/default.nix`. The Nix wrapper:

- Prepends two environment variables before `hms.bash` content:
  - `USER_NAME` — taken from `user.nix`'s `user.name` at Nix build time
  - `USER_EMAIL` — taken from `user.nix`'s `user.email` at Nix build time
- Lists `pkgs.git` and `pkgs.home-manager` as `runtimeInputs`, making them
  available in the script's `PATH` without relying on system-level `git` or
  `home-manager` commands.

This means: `hms` always uses the Nix-managed `git` and `home-manager` binaries.
If those are not yet built, the script cannot run.

---

## Flags and Options

### No flag (default)

```
hms
```

Runs the full deployment sequence described below. No interactive prompts except
possibly the Ralph version upgrade prompt (only if stdin is a terminal and a newer
Ralph release is available).

### `--purge` (alias: `--expunge`)

```
hms --purge
hms --expunge
```

**What it does — exact source behavior (hms.bash lines 66–80):**

1. The flag sets `PURGE=true` in the argument-parsing loop.
2. Immediately after argument parsing, if `PURGE=true`, an EXIT trap is registered:
   ```bash
   trap 'echo "Purging tmux server for complete environment refresh..."; tmux kill-server 2>/dev/null || true' EXIT
   ```
3. The trap fires when the script exits — **regardless of whether the script
   succeeds, fails, or is interrupted by `set -e`**. The `|| true` ensures the
   trap itself never causes a non-zero exit.
4. `tmux kill-server` terminates the tmux server process and **closes all active
   tmux sessions and windows** — there is no selective session targeting.

**What it does NOT do:**
- It does not purge Home Manager generations.
- It does not delete Nix store paths.
- It does not remove backups.
- It does not wipe configuration.
- It does not affect any files in `~/.config/nixpkgs`.

**When to use it (per the hms help text):** When tmux-related settings change
(tmux config, tmux plugins, tmux keybindings) and you want the new config loaded
into a clean tmux server rather than having the old server re-read config.

**Why Claude Code must never run it:** `tmux kill-server` closes every active tmux
session. Claude Code coordinators run inside tmux sessions managed by the user.
Running `hms --purge` from inside a Claude Code session would kill the session
itself and all other active sessions. This is a destructive, irreversible operation
on the user's live environment. The user must run it themselves, deliberately, from
a context where losing all tmux sessions is acceptable.

### `-h` / `--help`

Prints usage information and exits. No side effects.

---

## Execution Sequence (Step by Step)

The following traces `hms` (no flags) from top to bottom. Line numbers reference
`modules/system/hms.bash`.

### Step 1: shell options (line 9)

```bash
set -eou pipefail
```

- `-e`: exit immediately if any command returns non-zero
- `-o`: treat unset variables as errors
- `-u`: same as above (redundant but explicit)
- `pipefail`: pipeline fails if any stage fails

Consequence: any failure in the following steps aborts the script before
completion. The EXIT trap (if `--purge` was passed) still fires.

### Step 2: argument parsing (lines 64–73)

Loops over all `$@`. Sets `PURGE=true` on `--purge`/`--expunge`. Calls
`show_help` and exits on `-h`/`--help`. Unknown flags are silently ignored.

### Step 3: `--purge` EXIT trap registration (lines 78–80)

If `PURGE=true`, registers the `tmux kill-server` EXIT trap. This runs even if the
script fails in a later step.

### Step 4: user.nix validation (lines 83–93)

Two checks:

1. `~/.config/nixpkgs/user.nix` must exist.
2. The file must not contain the string `= "CHANGE_ME"` (checked via `grep -q`
   — this is the one place in the entire codebase where `grep` is used, inside
   the script body; the rg/fd preference from CLAUDE.md applies to Claude Code
   sessions, not to installed shellapp scripts).

If either check fails: prints an error, exits non-zero. The `--purge` EXIT trap
fires at this point if it was registered, killing tmux.

### Step 5: backup creation (lines 96–102)

```bash
mkdir -p ~/.backup/.config/nixpkgs
timestamp=$(date +%Y%m%d-%H%M%S)

cp ~/.config/nixpkgs/user.nix     ~/.backup/.config/nixpkgs/user.$timestamp.nix
ln -sf user.$timestamp.nix        ~/.backup/.config/nixpkgs/user.latest.nix

cp ~/.config/nixpkgs/overconfig.nix     ~/.backup/.config/nixpkgs/overconfig.$timestamp.nix
ln -sf overconfig.$timestamp.nix        ~/.backup/.config/nixpkgs/overconfig.latest.nix
```

**Side effects:**
- Creates `~/.backup/.config/nixpkgs/` if it does not exist.
- Writes two new timestamped files on every successful `hms` run.
- Updates two `*.latest.nix` symlinks to point at the newest backup.

**Retention:** No automatic cleanup. Backups accumulate indefinitely. The
CLAUDE.md notes that syncing `~/.backup` to cloud storage is a human maintenance
task.

**What is backed up:** The live files at `~/.config/nixpkgs/user.nix` and
`~/.config/nixpkgs/overconfig.nix` — the actual content at backup time, not a
git-committed version.

### Step 6: temporarily un-hide user.nix and overconfig.nix from git (line 105)

```bash
git -C ~/.config/nixpkgs update-index --no-skip-worktree user.nix overconfig.nix
```

Under normal conditions, these files are marked `--skip-worktree` by the
`home.nix` activation hooks (see Git-Invisible Behavior section below). Home
Manager needs to read them as part of the flake evaluation. This step removes the
hiding so git and nix flake commands can see the files.

`--no-skip-worktree` is the exact inverse of `--skip-worktree` and is required
here. Using `--no-assume-unchanged` (a different git mechanism) would NOT clear
the skip-worktree bit, meaning hms would silently deploy the committed blank
template instead of the real file — this was the bug fixed in card #943.

### Step 7: home-manager switch (line 108)

```bash
home-manager switch --flake ~/.config/nixpkgs
```

This is the core operation. It:

1. Evaluates the flake at `~/.config/nixpkgs` using Nix.
2. Builds all derivations defined in `home.nix` and imported modules.
3. Activates the new generation: symlinks packages into `~/.nix-profile/`,
   writes config files (`.zshrc`, `.gitconfig`, etc.) to their target locations,
   runs Home Manager activation hooks.
4. Creates a new Home Manager generation entry (visible via
   `home-manager generations`).

**Activation hooks that run as part of this step (defined in home.nix lines 51–57):**

```nix
home.activation.gitIgnoreUserChanges =
  lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD git -C ~/.config/nixpkgs update-index --skip-worktree user.nix
  '';

home.activation.gitIgnoreOverconfigChanges =
  lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD git -C ~/.config/nixpkgs update-index --skip-worktree overconfig.nix
  '';
```

These hooks run after the `writeBoundary` phase (i.e., after config files are
written) and re-hide both files from git using `--skip-worktree`.

**What `home-manager switch` writes to the filesystem:**

- `~/.nix-profile/` — symlink farm updated to point at new generation
- `~/.zshrc`, `~/.zprofile`, `~/.zshenv` — zsh configuration (managed by
  `programs.zsh`)
- `~/.gitconfig` — git configuration (managed by `programs.git`)
- `~/.config/` subdirectories — various program configs
- `~/.claude/` — Claude Code configuration, agents, hooks (managed by
  `modules/claude/`)
- `~/.claude/TOOLS.md` — auto-generated shellapp documentation
- Any other files declared via `home.file.*` or program modules

The deployed `~/.zshrc` sources `~/.nix-profile/etc/profile.d/hm-session-vars.sh`
to load session variables. Shellapp aliases (hme, hmu, hmo, hm) are written into
the zsh configuration and available in all new shells after the switch.

**Flake8 linting:** The Nix build evaluates Python scripts (e.g., in
`modules/claude/`) through flake8 as part of `pkgs.writers.writePython3Bin`.
Errors like F541 (unnecessary f-string) or F841 (unused variable) fail the build
here, not during `nix flake check`. This is why `hms` is the real gate.

### Step 8: root user safety check (lines 118–121)

```bash
if [ "$EUID" -eq 0 ] || [ "$USER" = "root" ]; then
  echo "ERROR: hms should not be run as root. Run as your normal user."
  exit 1
fi
```

Exits immediately if running as root. This check runs after `home-manager switch`,
not before — so if somehow root ran `hms`, the switch would complete before this
guard fires. This is a post-hoc safety check, not a pre-flight guard.

### Step 9: Claude Code installation check (lines 124–127)

```bash
if ! command -v claude &>/dev/null; then
  echo "Installing Claude Code..."
  curl -fsSL https://claude.ai/install.sh | bash
fi
```

If `claude` is not on `PATH`, downloads and installs it via the official installer.
Skipped if `claude` is already present. No version pinning — Claude Code updates
itself via its own mechanism.

### Step 10: Ralph Orchestrator version enforcement (lines 130–166)

Reads `modules/claude/ralph.lock` (JSON with a `version` field). Then:

1. If the lock file is absent: warns and skips.
2. If the lock file has no `version` field: warns and skips.
3. If Ralph is not installed or the installed version differs from the locked
   version: installs the locked version via curl from GitHub releases.
4. If a newer Ralph version exists on GitHub: prompts the user (only if stdin is a
   terminal — i.e., interactive) whether to update the lock file. If the user
   responds `y`/`Y`, updates `ralph.lock` and installs the newer version.

**Side effects:** May modify `modules/claude/ralph.lock` in-place if the user
accepts an upgrade prompt.

### Step 11: local git configuration (lines 170–171)

```bash
git -C ~/.config/nixpkgs config --local user.name  "$USER_NAME"
git -C ~/.config/nixpkgs config --local user.email "$USER_EMAIL"
```

Sets git identity for commits made inside `~/.config/nixpkgs`. `USER_NAME` and
`USER_EMAIL` are injected by the Nix wrapper from `user.nix` at build time.
These commands are silent (stderr redirected to `/dev/null`) and idempotent.

### Step 12: EXIT trap fires (if `--purge`)

If `PURGE=true`, the trap registered in Step 3 runs now (after normal script
completion). `tmux kill-server` is called. All tmux sessions are terminated.

---

## Git-Invisible Behavior of user.nix and overconfig.nix

**Why they are hidden:** These files contain personal identity (name, email,
username, home directory path) and machine-specific secrets (API keys). They must
exist in the repository for Nix to evaluate the flake, but they must not appear in
`git status` or accidentally be staged and committed.

**Mechanism:** After every successful `hms` run, the Home Manager activation hooks
(in `home.nix` lines 51–57) run:

```bash
git -C ~/.config/nixpkgs update-index --skip-worktree user.nix
git -C ~/.config/nixpkgs update-index --skip-worktree overconfig.nix
```

`--skip-worktree` tells git to assume these files are unchanged and skip checking
them during `git status`, `git add .`, etc. The files still exist in git's object
database (from initial commit) but local changes are invisible to git operations.

**How hms un-hides them:** Step 6 uses `--no-skip-worktree`, which is the exact
inverse of `--skip-worktree`. The flags are symmetric — the mark and unmark
operations use the same mechanism.

**Consequence for Claude Code:** Never run `git add user.nix` or
`git add overconfig.nix` — these files contain secrets. The skip-worktree flag is
the guard against accidental commits.

---

## Auto-Backup Mechanism

**Backup directory:** `~/.backup/.config/nixpkgs/`

**Files backed up on every hms run:**
- `user.nix` → `~/.backup/.config/nixpkgs/user.YYYYMMDD-HHMMSS.nix`
- `overconfig.nix` → `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix`

**Latest symlinks (updated each run):**
- `~/.backup/.config/nixpkgs/user.latest.nix` → most recent user backup
- `~/.backup/.config/nixpkgs/overconfig.latest.nix` → most recent overconfig backup

**Retention:** No automatic pruning. Backups accumulate indefinitely. This is a
feature — you can recover any previous configuration from any prior `hms` run.

**Restore procedure:**

To recover `user.nix` from the latest backup:
```bash
cp ~/.backup/.config/nixpkgs/user.latest.nix ~/.config/nixpkgs/user.nix
```

To recover from a specific timestamp:
```bash
cp ~/.backup/.config/nixpkgs/user.20260505-143022.nix ~/.config/nixpkgs/user.nix
```

To list available backups:
```bash
ls -lt ~/.backup/.config/nixpkgs/
```

The symlinks (`user.latest.nix`, `overconfig.latest.nix`) always point at the
most recent backup and can be used when the exact timestamp is not known.

**Sync note (from CLAUDE.md):** The user is responsible for syncing `~/.backup`
to cloud storage. This is not Claude-actionable.

---

## Sibling Shellapps: hme, hmu, hmo, hm

These are **not** shellapps in the `pkgs.writeShellApplication` sense. They are
zsh shell aliases defined in `modules/zsh.nix` (lines 264–267):

```nix
shellAliases = {
  hme = "vim ~/.config/nixpkgs/home.nix";
  hmu = "vim ~/.config/nixpkgs/user.nix";
  hmo = "vim ~/.config/nixpkgs/overconfig.nix";
  hm  = "cd ~/.config/nixpkgs";
};
```

They are only available in zsh (not in other shells or as standalone commands).
They expand to simple vim or cd invocations — no scripts, no side effects beyond
what vim/cd do.

### hme — Edit home.nix

```
hme
```

Opens `~/.config/nixpkgs/home.nix` in vim.

**What home.nix is:** The top-level Home Manager module entrypoint. It imports all
domain modules, aggregates shellapps from each module, defines git-invisible
activation hooks for user.nix/overconfig.nix, sets global assertions (placeholder
validation), and configures Nix GC and Home Manager self-management. Editing
home.nix is how you add or remove module imports, change global assertions, or
modify cross-cutting configuration.

**Side effects of editing:** None until `hms` is run. Changes to home.nix are not
live until deployed.

### hmu — Edit user.nix

```
hmu
```

Opens `~/.config/nixpkgs/user.nix` in vim.

**What user.nix is:** A Nix file returning a single attribute set `{ user = { name,
email, username, homeDirectory }; }`. These four fields are used throughout the
entire configuration wherever user identity is needed (git config, flake username
resolution, path derivation). It is git-invisible after first `hms` run.

**Critical:** `user.nix` is backed up by every `hms` run. If you corrupt it, the
backup at `~/.backup/.config/nixpkgs/user.latest.nix` can restore it.

**Side effects of editing:** None until `hms` is run. A malformed `user.nix` will
fail the Nix assertion check during `hms` and abort before any changes are applied.

### hmo — Edit overconfig.nix

```
hmo
```

Opens `~/.config/nixpkgs/overconfig.nix` in vim.

**What overconfig.nix is:** A Nix Home Manager module for machine-specific
overrides that should not be committed. Loaded directly as a flake module in
`flake.nix` (line 51: `./overconfig.nix`). Common uses: machine-specific packages,
git email override (`lib.mkForce`), shell aliases, environment variables and secrets
(e.g., `CONTEXT7_API_KEY`). It is git-invisible after first `hms` run.

**Critical:** `overconfig.nix` is backed up by every `hms` run. Secrets like API
keys are preserved in backups. If you corrupt it or it is lost, restore from
`~/.backup/.config/nixpkgs/overconfig.latest.nix`.

**Side effects of editing:** None until `hms` is run. Syntax errors in
`overconfig.nix` will fail Nix evaluation during `hms` and abort before changes
are applied.

### hm — cd to repo root

```
hm
```

Changes the current shell directory to `~/.config/nixpkgs`. Equivalent to
`cd ~/.config/nixpkgs`. No other effects.

---

## Common Failure Modes and How to Recognize Them

### user.nix not found

**Symptom:**
```
ERROR: user.nix not found!
```

**Cause:** `~/.config/nixpkgs/user.nix` does not exist. This happens on a fresh
install before initial setup, or if the file was accidentally deleted.

**Recovery:** Create `user.nix` from the template in the repository (or restore
from backup: `cp ~/.backup/.config/nixpkgs/user.latest.nix ~/.config/nixpkgs/user.nix`).

### user.nix has placeholder values

**Symptom:**
```
ERROR: user.nix contains CHANGE_ME placeholder values
```

**Cause:** The string `= "CHANGE_ME"` appears in `user.nix`. This is the initial
state of the template before a user configures it.

**Recovery:** Run `hmu` and replace all `CHANGE_ME` values with real values.

### Nix assertion failure (placeholder in user fields)

**Symptom:** During `home-manager switch`, an assertion error about placeholder
values in name/email/username/homeDirectory.

**Cause:** The bash-level check (Step 4) only looks for the literal string
`= "CHANGE_ME"`. The Nix-level assertion (in `home.nix`) checks that the actual
field values are not empty strings or do not contain `CHANGE_ME`. Both must pass.

**Recovery:** Fix `user.nix` via `hmu`.

### Flake8 linting failure

**Symptom:** `home-manager switch` fails with a Python lint error (e.g.,
`F541 f-string is missing placeholders`, `F841 local variable ... is assigned
but never used`).

**Cause:** A Python script in `modules/claude/` has a flake8 violation. This does
NOT show up in `nix flake check`.

**Recovery:** Find and fix the lint error in the relevant Python source file in
`modules/`. Then re-run `hms`.

### home-manager switch fails mid-build

**Symptom:** Build error during `home-manager switch` (Nix evaluation error, hash
mismatch, network failure fetching dependencies, etc.).

**Cause:** Various — Nix syntax error, missing package, network issue, corrupted
Nix store.

**Recovery:**
- Nix syntax errors: fix the offending `.nix` file, re-run `hms`.
- Network issues: retry `hms` (transient).
- Corrupted store: `nix store verify --check-contents` (advanced, rarely needed).

The previous Home Manager generation remains active if `home-manager switch` fails.
No rollback is needed — the system stays on the last successful generation.

### Ralph version mismatch warning

**Symptom:**
```
Ralph version mismatch (installed: v2.7.0, locked: v2.6.0) — installing locked version...
```

**Cause:** Ralph was updated outside of `hms`, or the lock file was manually
changed. hms enforces the lock file version.

**Recovery:** None required — hms self-corrects by installing the locked version.

### tmux sessions killed unexpectedly

**Symptom:** After `hms --purge`, all tmux sessions are gone.

**Cause:** This is the designed behavior of `--purge`. The EXIT trap calls
`tmux kill-server` unconditionally.

**Recovery:** Start a new tmux session (`tmux new-session`). Previous session
content is not recoverable unless tmux-resurrect snapshots were taken before the
kill. The tmux-restore shellapp can restore from the most recent resurrect snapshot.

---

## Worked Example: hms --purge and Recovery

This is the scenario that prompted this documentation.

### Scenario

The user ran `hms --purge` from an active tmux session. All tmux sessions were
terminated. The coordinator (Claude Code) did not understand what `--purge` does.

### What Happened (traced from source)

1. hms started and set `PURGE=true`.
2. The EXIT trap was registered: `tmux kill-server 2>/dev/null || true` will run
   when the script exits.
3. Steps 4–11 ran normally (backup, git un-hide, home-manager switch, Claude/Ralph
   checks, git config).
4. The script exited normally (exit code 0).
5. The EXIT trap fired. `tmux kill-server` was called.
6. The tmux server process was terminated. All sessions — including the one the
   user was running the command from — were closed.

### Recovery Steps

After the tmux server is killed:

1. Open a new terminal window (Alacritty or any terminal).
2. The zsh `initContent` in `modules/zsh.nix` automatically runs
   `exec tmux new-session` when no `$TMUX` is set, so a new tmux session starts
   automatically on shell init.
3. If you want to restore a previous tmux session layout, run `tmux-restore` to
   pick a tmux-resurrect snapshot.
4. All processes that were running inside tmux (Claude Code sessions, builds, etc.)
   are gone. They cannot be recovered — only restarted.

### What the Coordinator Should Have Known

`hms --purge` is not a "deep clean" of Home Manager. It is `hms` (normal
deployment) followed by `tmux kill-server`. The flag affects only tmux. The
coordinator should have surfaced this to the user before the user ran it, or at
minimum not guessed at its behavior.

---

## Relationship Between hms, Home Manager Generations, and the Deployed Environment

### Generations

Each successful `home-manager switch` creates a new generation. Generations are
stored in `~/.local/state/home-manager/generations/` (or similar, depending on HM
version). You can list them with:

```bash
home-manager generations
```

And roll back to a previous generation with:

```bash
home-manager generations  # find the path
<generation-path>/activate
```

Rolling back re-activates the previous generation's activation scripts, including
re-running the git skip-worktree hooks. It does NOT restore user.nix or
overconfig.nix from backup — those are separate files, not part of a generation.

### The Deployed Profile

After a successful `hms`, `~/.nix-profile` is a symlink to the current Nix user
profile. All shellapps (including `hms` itself, `git` tools, `kanban`, etc.) are
available as symlinks under `~/.nix-profile/bin/`. The zsh config is written to
`~/.zshrc`, `~/.zprofile`, `~/.zshenv`. Opening a new shell reads these files
and picks up the new environment.

**Important:** A running shell (tmux pane, terminal window) does NOT automatically
pick up changes from a new `hms` run. You need to open a new shell or run:

```bash
reload-env  # alias: unset __HM_SESS_VARS_SOURCED && source ~/.nix-profile/etc/profile.d/hm-session-vars.sh
```

### Where Shell Aliases Live

`hme`, `hmu`, `hmo`, `hm` are zsh aliases. They exist in the deployed `~/.zshrc`
(written by `programs.zsh.shellAliases` in `modules/zsh.nix`). They are NOT
standalone commands — `which hme` will not find them. They are only available
inside a zsh interactive session.

### Nix GC

`home.nix` sets `nix.gc.automatic = true` (line 89), enabling weekly automatic
garbage collection. The GC removes unreachable store paths — including old Home
Manager generations' build artifacts — but does not remove the generation
activation scripts themselves unless the generation is explicitly deleted.

---

## What Claude Code Must Never Do

1. **Never run `hms --purge`** — kills all tmux sessions, including the one Claude
   Code is running in. This is irreversible.
2. **Never run `hms --expunge`** — same as `--purge`.
3. **Never run `hme`, `hmu`, `hmo`, `hm`** — these open files in vim interactively.
   Claude Code should not run interactive editor commands. Edit the files directly
   using Read/Edit/Write tools.
4. **Never `git add user.nix` or `git add overconfig.nix`** — these contain secrets
   and personal identity. The skip-worktree flag hides them for this reason.
5. **Never edit files outside `~/.config/nixpkgs/`** — they are managed by Nix and
   will be overwritten on the next `hms` run.

---

## Quick Reference

| Command | Type | What it does |
|---------|------|--------------|
| `hms` | shellapp (Nix) | Full deployment: validate, backup, home-manager switch, install tools, configure git |
| `hms --purge` | shellapp (Nix) | Same as hms, but kills tmux server unconditionally via EXIT trap (even on failed deploy) |
| `hms --expunge` | shellapp (Nix) | Alias for `hms --purge` |
| `hme` | zsh alias | `vim ~/.config/nixpkgs/home.nix` |
| `hmu` | zsh alias | `vim ~/.config/nixpkgs/user.nix` |
| `hmo` | zsh alias | `vim ~/.config/nixpkgs/overconfig.nix` |
| `hm` | zsh alias | `cd ~/.config/nixpkgs` |

| File | Backed up? | Git-visible? | Edit via |
|------|-----------|--------------|---------|
| `user.nix` | Yes (every hms) | No (skip-worktree after first hms) | hmu / direct edit |
| `overconfig.nix` | Yes (every hms) | No (skip-worktree after first hms) | hmo / direct edit |
| `home.nix` | No | Yes | hme / direct edit |
| `flake.nix` | No | Yes | direct edit |

| Backup path | Contents |
|-------------|---------|
| `~/.backup/.config/nixpkgs/user.YYYYMMDD-HHMMSS.nix` | user.nix snapshot |
| `~/.backup/.config/nixpkgs/user.latest.nix` | symlink to most recent user backup |
| `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix` | overconfig.nix snapshot |
| `~/.backup/.config/nixpkgs/overconfig.latest.nix` | symlink to most recent overconfig backup |
