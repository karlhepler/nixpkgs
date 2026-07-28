# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

Nix Home Manager configuration managing development environments with flakes. Creates reproducible system configurations (zsh, Neovim, terminal, git, dev tools).

**Required**: This repository must be installed at `~/.config/nixpkgs`.

## 🚨 NEVER HOMEBREW 🚨

**Homebrew is FORBIDDEN.** See global CLAUDE.md § PACKAGE INSTALLATION for details. Use Nix (`modules/packages.nix`), direct binary downloads, or language-specific managers ONLY.

## 🚨 macOS Trash CLI — Use `pkgs.darwin.trash`, NEVER `pkgs.trash-cli` 🚨

**When a shellapp needs the `trash` command, add `pkgs.darwin.trash` to `runtimeInputs` — never `pkgs.trash-cli`.**

Two nixpkgs packages both provide a binary named `trash` on `aarch64-darwin`:

- ✅ **`pkgs.darwin.trash`** — moves files to the macOS-native Trash (`~/.Trash/`); **visible in Finder**; recoverable via right-click → Put Back. This is what users expect when they hear "trash."
- ❌ **`pkgs.trash-cli`** — moves files to the freedesktop.org trash directory (`~/.local/share/Trash/files/`); **invisible to Finder**. Files are technically recoverable, but the user-facing semantics ("show me the trash bin") are broken.

This is a class of failure that has already caused real damage in this repo (160 worktree folders silently routed to the freedesktop dir instead of macOS Trash). Do not repeat it.

**General principle — verify package SEMANTICS, not just the binary name:**

When a Nix package supplies a binary that has multiple implementations across nixpkgs, the binary name is NOT sufficient to identify the right package. Before adding any `<package>` to `runtimeInputs`:

1. Check `pkgs.<package>.meta.description` via `nix eval --raw nixpkgs#<package>.meta.description`.
2. If multiple packages provide the same binary, compare their descriptions and verify which behavior matches user expectation on this platform.
3. When the system is macOS-only (this repo is locked to `aarch64-darwin`), prefer the `pkgs.darwin.*` namespace for any tool that interacts with macOS-specific surfaces (Trash, keychain, notifications, accessibility, etc.).

## 🚨 SOURCE OF TRUTH PRINCIPLE 🚨

**CRITICAL: When working in this repository, NEVER edit files outside of this repository.**

This repository (`~/.config/nixpkgs`) is the **single source of truth** for system configuration. All work must be done here. The `hms` command deploys this configuration to your system.

### What This Means

**✅ CORRECT workflow:**
1. Edit files in `~/.config/nixpkgs/` (the source)
2. Add new files to git: `git add <file>`
3. Run `hms` to deploy changes
4. Nix automatically copies/symlinks files to correct locations

**❌ WRONG workflow:**
- ❌ Manually editing `~/.claude/agents/swe-backend.md`
- ❌ Manually copying files to `~/.claude/commands/`
- ❌ Directly modifying files in `~/.nix-profile/`
- ❌ Editing anything in user directories that hms manages

**Why:** Files outside this repo are **managed by Nix**. Manual edits will be:
- Overwritten on the next `hms` run
- Lost when switching generations
- Not version controlled
- Not reproducible

**Rule:** If you're working in `~/.config/nixpkgs`, assume **everything** outside this directory is read-only and managed by hms.

**Exception:** The only files you should edit outside this repo are:
- Active development code in OTHER repositories (not this one)
- Temporary scratch files in `/tmp/` or `.scratchpad/` (project root)

### Common Mistakes to Avoid

1. **Skill not deploying?** → Add to git, then run hms (don't copy manually)
2. **Command not available?** → Add shellapp to the appropriate module's `default.nix`, run hms (don't create symlinks)
3. **Config not applying?** → Edit in source, run hms (don't edit deployed files)

**Remember:** This repository controls your computer. Work in the source, deploy with hms.

## Team Member Terminology

**Important:** When the user says "team member", "update a team member", "add a team member", or "remove a team member", they are referring to the agent definition file:

1. **The agent definition:** `modules/claude/global/agents/<name>.md` - The source of truth for delegatable team members. Contains the full skill body (system prompt, expertise, workflows) directly in the file body, with agent metadata in the frontmatter.

**Adding a team member** means:
- Create agent definition in `modules/claude/global/agents/<name>.md` with full skill content and agent frontmatter (name, description, model, tools, permissionMode, maxTurns, background, mcp)
- Add to git: `git add modules/claude/global/agents/<name>.md`
- Run `hms` to deploy to `~/.claude/agents/`
- Update staff-engineer team table if needed

**Updating a team member** means:
- Edit `modules/claude/global/agents/<name>.md` as needed
- If adding new files: `git add <new-files>`
- Run `hms` to deploy changes

**Removing a team member** means:
- Delete `modules/claude/global/agents/<name>.md`
- Run `hms` to remove from deployment
- Update staff-engineer team table

**Why agent definitions are self-contained:** The agent definition preloads all skill content directly into the sub-agent's context at startup (95%+ reliability vs 70% with separate skill files). No `skills:` frontmatter indirection needed.

### Exception Skills

Some capabilities intentionally have no agent definition because they run differently:

- **Exception skills** (project-planner) — Run via Skill tool directly, not delegated as background sub-agents. These are specialized capabilities invoked for specific use cases, not general-purpose team members.
- **Workflow skills** (manage-pr-comments, review-pr-comments) — Live at `skills/<name>/SKILL.md`. Run via Skill tool with specific CLI tooling integration. These coordinate external processes and don't fit the standard team member pattern.
- **Multi-file skills** (pr-review) — Live in `skills/<name>/SKILL.md` instead of `agents/<name>.md` because they have supporting files (e.g., `skills/pr-review/review-citation-guide.md`, `skills/pr-review/review-domains.md`). Deployed via `default.nix` skill copy rules. Invoked via Skill tool directly.

**Important:** The "Adding a team member" process (agent definition) applies to standard delegatable team members only, not these exceptions. When updating or adding capabilities, distinguish between delegatable agents and exception/workflow skills.

## Quick Commands

### Configuration Management
- `hms`: Apply Home Manager changes — validates user.nix, backs up user.nix and overconfig.nix (user.nix and overconfig.nix are git-invisible; see § File Management), temporarily un-hides them for the build, runs `home-manager switch --flake` (also runs flake8 — the real pre-commit gate; `nix flake check` is not sufficient), installs Claude Code if absent, sets local git identity. See `modules/system/HMS.md` for full reference.
- `hms --purge` (alias `--expunge`): Same as `hms`, but registers an EXIT trap that kills the tmux server unconditionally — even if the deploy fails mid-run (e.g., validation error at Step 4, Nix eval error at Step 7). Claude Code must NEVER run this flag — it will terminate the session it is running in.
- `hme`: Open `home.nix` in vim (zsh alias — not a standalone command; never invoke from Bash tool — opens interactive vim)
- `hmu`: Open `user.nix` in vim (zsh alias — not a standalone command; never invoke from Bash tool — opens interactive vim)
- `hmo`: Open `overconfig.nix` in vim (zsh alias — not a standalone command; never invoke from Bash tool — opens interactive vim)

### Git Workflow
- `commit "message"`: Stage all changes and commit
- `push`: Push current branch to origin
- `pull`: Pull with automatic stash/unstash
- `save "message"`: Commit and push in one command
- `git trunk`: Switch to main/master branch (auto-detects)
- `git sync`: Merge trunk into current branch
- `git branches`: Interactive branch selector with fzf
- `git resume`: Switch to most recently used branch
- `git tmp`: Create temporary experimental branch
- `workout`: Interactive worktree browser and manager (default with no args)
- `workout <branch>`: Create/navigate to git worktree (organized in ~/worktrees/)
- `workout .`: Create worktree for current branch
- `workout -`: Toggle to previous worktree location
- `groot`: Navigate to git repository root

**Every other command this repo defines** — the `hm` directory alias, `q`/`qq`/`qqq`, `prc`, `prr`, the coordination-tier CLIs (`staff`, `sstaff`, `crew`), the analytics and lifecycle CLIs (`claude-inspect`, `kanban`, `perm`), and `tmux-restore` — is listed in `~/.claude/docs/cli-and-mcp-reference.md` § Repository Command Reference (source: `modules/claude/global/docs/cli-and-mcp-reference.md`), with subcommands and a source path for the commands that have either — not every one does (see § Reference Documentation below for the auto-generated index of every shellapp instead). Read this one when you need a subcommand name you do not remember, or the source file to edit to change a command's behavior.

## Critical Requirements

1. **Repository Location**: MUST be installed at `~/.config/nixpkgs`
2. **Backup Synchronization**: Sync `~/.backup` folder with cloud storage for machine-specific configuration safety (human maintenance task — not Claude-actionable)
3. **--purge Flag**: Claude Code must NEVER use the `--purge` flag with `hms`. What `--purge` does: it registers an EXIT trap (hms.bash:79) that fires unconditionally when the script exits — whether hms completes successfully, aborts mid-run on validation failure (Step 4), fails during `home-manager switch` (Step 7), or exits for any other reason. There is no way to run `hms --purge` without killing the tmux server and closing every active tmux session, including the one Claude Code is running in. This is irreversible. The flag exists for the user to run deliberately after tmux config changes, not for automation. Full semantics: `modules/system/HMS.md`.
4. **macOS ARM Only**: This configuration is locked to `aarch64-darwin` (Apple Silicon Macs)

## Development Workflows

**🚨 Deployment Order: `git add` (if needed) → `hms` → `commit` → `push`**

Wait for `hms` to succeed before running `git commit`. The `hms` build is the validation step — a failing build means the change is broken, not just undeployed. Stage files with `git add` if needed before running `hms`, but only commit after the build passes.

**`hms` flake8 is stricter than `nix flake check` — `hms` is the real gate.** `nix flake check` does not build derivations and never runs flake8 — Python source files that `hms` rejects on flake8 lint (F541 unnecessary f-string, F841 unused variable observed in practice) will pass `nix flake check` silently. Do not treat `nix flake check` passing as a green light to commit. Always run `hms` as the final pre-commit gate.

**Add new package:**

🚨 **NEVER via Homebrew** - Use Nix or direct download ONLY

1. Add to `modules/packages.nix` under appropriate category
2. For LSP servers: Also update Neovim LSP config
3. Run `hms` to apply
4. Verify: `which <package-name>`

**Example (CORRECT):**
```nix
# modules/packages.nix
home.packages = with pkgs; [
  colima    # Docker runtime
  ripgrep   # Fast search
];
```

**Example (WRONG - NEVER DO THIS):**
```bash
brew install colima  # ❌ FORBIDDEN
```

**Add new shellapp:**
1. Create bash script in appropriate module directory (e.g., `modules/git/new-script.bash`)
2. Add shellapp definition to module's `_module.args.{domain}Shellapps` rec block
3. Add to git: `git add modules/git/new-script.bash`
4. Run `hms` to deploy
5. Command automatically available system-wide
6. Documentation auto-generated in `~/.claude/TOOLS.md`

**Add delegatable team member:**
1. Create `modules/claude/global/agents/your-agent.md` with full skill content and agent frontmatter
2. Add to git: `git add modules/claude/global/agents/your-agent.md`
3. Run `hms` to deploy
4. Agent automatically available in `~/.claude/agents/`

For exception/workflow skills (invoked via Skill tool), create at `modules/claude/global/skills/<name>/SKILL.md` instead. See § Team Member Terminology for the full distinction.

**Update Nix dependencies:**
1. `nix flake update` (updates flake.lock)
2. `hms` to apply
3. Test everything works
4. Commit flake.lock changes

## Scripting Principles

**Guaranteed Dependencies - No Fallbacks Needed:**

This is a Nix Home Manager environment. All dependencies are declaratively managed and guaranteed to be available at runtime. **NEVER write fallback logic in scripts.**

**❌ WRONG (defensive fallbacks):**
```bash
# Don't do this!
if command -v bat >/dev/null 2>&1; then
    bat file.txt
elif command -v less >/dev/null 2>&1; then
    less file.txt
else
    cat file.txt
fi
```

**✅ CORRECT (assume dependencies exist):**
```bash
# Just use it - Nix guarantees it's available
bat file.txt
```

**Why:**
- Dependencies are declared in `modules/packages.nix` or module-specific Nix files
- Nix ensures they're built and available before your script runs
- Fallback chains add complexity and can hide missing dependency declarations
- If a dependency is missing, the script SHOULD fail loudly (indicates Nix config needs updating)

**This applies to code review too.** Do not flag missing dependency handling (e.g., `FileNotFoundError` for a CLI, `command -v` checks) as a deficiency when the dependency is Nix-guaranteed via `runtimeInputs`, `wrapProgram`, or `modules/packages.nix`. Defensive checks for Nix-managed binaries are an anti-pattern, not a best practice.

**When adding external dependencies to scripts:**

**For shellapps (preferred):**
Declare dependencies directly in the script's Nix definition using `runtimeInputs`:

```nix
myScript = pkgs.writeShellApplication {
  name = "my-command";
  runtimeInputs = [ pkgs.bat pkgs.jq pkgs.fd ];  # Script-specific dependencies
  text = ''
    # These commands are guaranteed to exist - no fallbacks needed
    bat file.txt
    echo '{"key":"value"}' | jq .
    fd pattern
  '';
};
```

**For Python scripts:**
```nix
myPythonScript = pkgs.writers.writePython3Bin "my-script" {
  libraries = [ pkgs.python3Packages.requests pkgs.python3Packages.jinja2 ];
} ''
  import requests  # Guaranteed to exist
  import jinja2    # No try/except needed
'';
```

**For system-wide tools:**
Add to `modules/packages.nix` only when the tool should be available globally (not script-specific):
```nix
home.packages = with pkgs; [
  bat  # Available system-wide in all shells
  fd
  ripgrep
];
```

**The principle:**
- **Script-specific dependencies** → `runtimeInputs` in the script's Nix definition
- **System-wide tools** → `modules/packages.nix`
- **Never write fallbacks** → Nix guarantees availability

**Examples:**
- Shellapp needs bat → Add to `runtimeInputs`, use `bat` directly
- Python script needs requests → Add to `libraries`, `import requests` directly
- System needs global jq → Add to `modules/packages.nix`

**The only exception:** Checking for optional user configuration (e.g., checking if `~/.gitconfig` exists) is fine. But system commands should never have fallbacks.

## File Management

**home.nix:**
- Edit with `hme`
- Main configuration entry point
- Changes deployed via `hms`

**user.nix:**
- Edit with `hmu`
- Contains: name, email, username, homeDirectory
- Auto-backed up to `~/.backup/.config/nixpkgs/user.YYYYMMDD-HHMMSS.nix`
- Local git config for this repo uses these values

**overconfig.nix:**
- Edit with `hmo`
- Machine-specific customizations and secrets
- Auto-backed up to `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix`
- Example: `programs.git.settings.user.email = lib.mkForce "work@email.com";`

user.nix and overconfig.nix are made git-invisible by `hms` after first run. Backups linked via `*.latest.nix` symlinks.

## Your Team

For the full roster of delegatable agents — and the separate list of capabilities that run via Skill tool instead of being delegated — see `~/.claude/docs/coordination-reference.md` § Team Member Terminology (source: `modules/claude/global/docs/coordination-reference.md`). Read it before delegating, to confirm the agent you have in mind actually exists.

## Reference Documentation

**User setup:** See README.md for installation and daily usage procedures.

**hms deep reference:** See `modules/system/HMS.md` — covers every flag, every execution step, all side effects, backup mechanism, git-invisible behavior, failure modes, and a worked example of `hms --purge` with recovery.

**Command reference:** See `~/.claude/TOOLS.md` (auto-generated from shellapp metadata on `hms`) for the full index of every shellapp; see § Quick Commands above for the curated entry points with subcommands and sources.

**Repository architecture, the Claude Code deployment map, and the Nix command recipes:** See `~/.claude/docs/nixpkgs-repo-reference.md` (source: `modules/claude/global/docs/nixpkgs-repo-reference.md`) — the module layout and core files, what deploys from `modules/claude/global/` into `~/.claude/`, the hook and Context7 MCP wiring, the claudit analytics dashboard, and the `nix flake` / `nix-prefetch-github` invocations. Read it when you need to trace a deployed artifact back to its source, or when you need a `nix` command against this flake.

**perm CLI mechanics (authoritative summary):**
- `perm allow <pattern> --session <id>` and `perm always <pattern> --session <id>` both write the permission pattern to `.claude/settings.local.json` — that file never contains a session ID.
- `--session` is an ownership key recorded only in `.claude/.perm-tracking.json`.
- The sole difference between `allow` and `always` is in `.perm-tracking.json`: `allow` creates a temporary, session-scoped claim (removable via cleanup); `always` creates a permanent entry that survives cleanup.
- Rule of thumb: `settings.local.json` = what is permitted; `.perm-tracking.json` = who owns it and for how long.
