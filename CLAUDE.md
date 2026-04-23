# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

Nix Home Manager configuration managing development environments with flakes. Creates reproducible system configurations (zsh, Neovim, terminal, git, dev tools).

**Required**: This repository must be installed at `~/.config/nixpkgs`.

## 🚨 NEVER HOMEBREW 🚨

**Homebrew is FORBIDDEN.** See global CLAUDE.md § PACKAGE INSTALLATION for details. Use Nix (`modules/packages.nix`), direct binary downloads, or language-specific managers ONLY.

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
- **Multi-file skills** (review) — Live in `skills/<name>/SKILL.md` instead of `agents/<name>.md` because they have supporting files (e.g., `skills/review/review-citation-guide.md`, `skills/review/review-domains.md`). Deployed via `default.nix` skill copy rules. Invoked via Skill tool directly.

**Important:** The "Adding a team member" process (agent definition) applies to standard delegatable team members only, not these exceptions. When updating or adding capabilities, distinguish between delegatable agents and exception/workflow skills.

## Quick Commands

### Configuration Management
- `hms`: Apply Home Manager changes (Claude Code must never use `--purge` flag)
- `hme`: Edit the `home.nix` file (main configuration)
- `hmu`: Edit the `user.nix` file (user-specific identity)
- `hmo`: Edit the `overconfig.nix` file (machine-specific customizations)
- `hm`: Change directory to `~/.config/nixpkgs`

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

### Tmux Session Management
- `tmux-restore`: Pick and restore a tmux-resurrect snapshot via fzf (shows sessions and window names in preview)

### Claude Code Helpers

> **These are shellapps defined in this repo.** To extend or modify them, edit their source in `modules/claude/` and run `hms`. Do NOT edit deployed copies directly.

- `q "question"`: Quick Claude question (haiku model - fastest)
- `qq "question"`: Claude question (sonnet model - balanced)
- `qqq "question"`: Complex Claude question (opus model - most capable)
- `burns "prompt"` or `burns file.md`: Run Ralph Orchestrator with Monty Burns coordinator hat (multi-hat YAML assembled at Nix build time) — source: `modules/claude/burns.py`
- `smithers` or `smithers <PR>`: Autonomous PR watcher (monitors checks, fixes issues, handles bot comments) — source: `modules/claude/smithers.py`
- `prc`: PR comment management tool (list, reply, resolve, collapse) — source: `modules/claude/prc.py`; see `/manage-pr-comments` skill for usage documentation

For kanban workflow and command reference, see global CLAUDE.md.

## Critical Requirements

1. **Repository Location**: MUST be installed at `~/.config/nixpkgs`
2. **Backup Synchronization**: Sync `~/.backup` folder with cloud storage for machine-specific configuration safety (human maintenance task — not Claude-actionable)
3. **--purge Flag**: Claude Code must NEVER use the `--purge` flag with `hms`
4. **macOS ARM Only**: This configuration is locked to `aarch64-darwin` (Apple Silicon Macs)

## Configuration Structure

Domain-centric module architecture - related functionality co-located.

**Core files:** flake.nix (inputs/outputs), home.nix (entry point), user.nix (identity), overconfig.nix (machine-specific).

For detailed architecture, see README.md and source files in modules/.

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

## Claude Code Integration

**Configuration deployment:**
- Global settings: `modules/claude/global/CLAUDE.md` → `~/.claude/CLAUDE.md`
- Agents: `modules/claude/global/agents/*.md` → `~/.claude/agents/`
- Hooks: notification-hook, complete-hook, csharp-format-hook (configured in `modules/claude/default.nix`)
- Commands: `~/.claude/TOOLS.md` auto-generated from shellapp metadata

**MCP integration:**
- Context7 MCP auto-configured if `CONTEXT7_API_KEY` set in overconfig.nix
- Config merged into `~/.claude.json` (preserves Claude's metadata)
- To disable: Remove `CONTEXT7_API_KEY`, run `hms`

**Analytics Dashboard (claudit):**
- Grafana-based dashboard for Claude Code usage analytics (user nickname: "claudit")
- Dashboard definition: `modules/claudit/dashboard.json`
- Metrics collection: `modules/claudit/claude-metrics-hook.py` (captures metrics via Claude Code metrics hook)
- Displays: Total cost (today/all-time), token breakdown (input/output/cache), cost by kanban session, turn statistics by agent type, tool usage heat map (by tool and agent)
- Access via Grafana interface (configured in Home Manager)

## Burns and Ralph Architecture

**Build-time Assembly:**
Burns uses a multi-hat YAML configuration assembled at Nix build time. The Ralph orchestrator invokes a composite YAML formed from:
- `modules/claude/global/hats/wrapper.yml.tmpl` - Ralph event-loop wrapper
- `modules/claude/global/hats/monty-burns.yml.tmpl` - Monty Burns coordinator hat
- 8 specialist skill hats (swe-backend, swe-frontend, swe-fullstack, swe-infra, swe-devex, swe-sre, swe-security, researcher)

The assembled YAML path is substituted at build time in `modules/claude/default.nix`.

**Tiered Review Protocol:**
The mandatory review protocol that determines when work requires review is defined in `modules/claude/global/hats/monty-burns.yml.tmpl` ("On work.done" event handler). Three tiers: Tier 1 (mandatory: auth/authz, financial, infra, PII DB, CI/CD), Tier 2 (high-risk: API endpoints, third-party, performance, migrations, deps, shell scripts), Tier 3 (recommended: UI, monitoring, large refactors). The protocol activates when a specialist emits 'work.done' event.

**Ralph vs. Kanban:**
Ralph is a self-contained event-loop orchestrator with its own memory system. Kanban is the human-facing coordination layer for staff engineers. These systems are separate. When burns runs, it sets `BURNS_SESSION=1` to suppress kanban session instructions — injecting kanban context would confuse the model. Ralph uses its internal memory system (`ralph tools memory`) instead of kanban cards.

**Available agents (delegatable team members):** (For the authoritative list, see `modules/claude/global/agents/` — this list may not include system/internal agents.)
- Engineering: swe-backend, swe-frontend, swe-fullstack, swe-devex, swe-infra, swe-security, swe-sre
- QA: qa-engineer
- Design: product-ux, visual-designer
- Support: researcher, scribe, ai-expert, ac-reviewer, debugger
- Business: finance, lawyer, marketing
- Exception Skills (invoked via Skill tool directly): project-planner, review-pr-comments, manage-pr-comments, review

## Your Team

See "Available agents" in the Burns and Ralph Architecture section above. For the full roster, see global CLAUDE.md.

## Reference Documentation

**User setup:** See README.md for installation and daily usage procedures.

**Command reference:** See `~/.claude/TOOLS.md` (auto-generated from shellapp metadata on `hms`).

**Nix development:**
- `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`: Get hash for GitHub packages
- `nix flake update`: Update dependencies
- `nix flake check`: Partial validation only — does NOT catch flake8 errors. Use `hms` as the real gate.
- `nix flake metadata`: Show flake info
- `nix search nixpkgs <package>`: Search packages

**Implementation details:** See source files in `modules/` directories for specific configurations (theme, LSP, activation hooks, etc).

**perm CLI mechanics (authoritative summary):**
- `perm allow <pattern> --session <id>` and `perm always <pattern> --session <id>` both write the permission pattern to `.claude/settings.local.json` — that file never contains a session ID.
- `--session` is an ownership key recorded only in `.claude/.perm-tracking.json`.
- The sole difference between `allow` and `always` is in `.perm-tracking.json`: `allow` creates a temporary, session-scoped claim (removable via cleanup); `always` creates a permanent entry that survives cleanup.
- Rule of thumb: `settings.local.json` = what is permitted; `.perm-tracking.json` = who owns it and for how long.

## External References

Supporting documentation for the staff engineer output style:

- [anti-patterns.md](modules/claude/global/docs/staff-engineer/anti-patterns.md) - Common coordination failure modes with concrete examples
- [delegation-guide.md](modules/claude/global/docs/staff-engineer/delegation-guide.md) - Permission handling, model selection patterns
- [parallel-patterns.md](modules/claude/global/docs/staff-engineer/parallel-patterns.md) - Parallel execution examples
- [edge-cases.md](modules/claude/global/docs/staff-engineer/edge-cases.md) - Interruptions, partial completion, review disagreements
- [review-protocol.md](modules/claude/global/docs/staff-engineer/review-protocol.md) - Mandatory reviews, approval criteria, conflict resolution
- [self-improvement.md](modules/claude/global/docs/staff-engineer/self-improvement.md) - Automate your own toil
