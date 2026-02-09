# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

Nix Home Manager configuration managing development environments with flakes. Creates reproducible system configurations (zsh, Neovim, terminal, git, dev tools).

**Critical**: This repository MUST be installed at `~/.config/nixpkgs`.

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
- ❌ Manually editing `~/.claude/commands/skill.md`
- ❌ Manually copying files to `~/.claude/`
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
- Temporary scratch files in `/tmp/` or scratchpad

### Common Mistakes to Avoid

1. **Skill not deploying?** → Add to git, then run hms (don't copy manually)
2. **Command not available?** → Add shellapp to `default.nix`, run hms (don't create symlinks)
3. **Config not applying?** → Edit in source, run hms (don't edit deployed files)

**Remember:** This repository controls your computer. Work in the source, deploy with hms.

## Quick Commands

### Configuration Management
- `hms`: Apply Home Manager changes (Claude Code must never use `--expunge` flag)
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

### Claude Code Helpers
- `q "question"`: Quick Claude question (haiku model - fastest)
- `qq "question"`: Claude question (sonnet model - balanced)
- `qqq "question"`: Complex Claude question (opus model - most capable)
- `burns "prompt"` or `burns file.md`: Run Ralph Orchestrator with Ralph Coordinator output style
- `smithers` or `smithers <PR>`: Autonomous PR watcher (monitors checks, fixes issues, handles bot comments)
- `prc`: PR comment management tool (list, reply, resolve, collapse)

### Kanban CLI (Agent Coordination)

**Card Creation:**
- `kanban do '{"action":"...","intent":"..."}'`: Create card directly in doing
- `kanban todo '{"action":"...","intent":"..."}'`: Create card in todo

**Card Transitions:**
- `kanban start <card#>`: Move card from todo to doing
- `kanban review <card#>`: Move card to review column
- `kanban redo <card#>`: Move card from review back to doing
- `kanban defer <card#>`: Move card from doing/review to todo
- `kanban done <card#> 'summary'`: Complete card with summary
- `kanban cancel <card#>`: Cancel card

**Card Details:**
- `kanban show <card#>`: Show full card details

**Acceptance Criteria (also aliased as `kanban ac`):**
- `kanban criteria add <card#> "text"`: Add acceptance criterion
- `kanban criteria remove <card#> <n> "reason"`: Remove criterion (with required reason)
- `kanban criteria check <card#> <n>`: Check off criterion
- `kanban criteria uncheck <card#> <n>`: Uncheck criterion

**Board View:**
- `kanban list --output-style=xml`: Board check (compact XML view for staff engineers)

**Session Management:**
- Session identity injected automatically via SessionStart hook (friendly names like `swift-falcon`)
- `--session <name>`: Pass session ID on commands (Claude does this automatically)
- `KANBAN_SESSION=custom-id`: Override session detection (for burns/smithers)
- Session mappings stored in `.kanban/sessions.json`

## Critical Requirements

1. **Repository Location**: MUST be installed at `~/.config/nixpkgs`
2. **Use hms Command**: Always use `hms` for syncing to ensure proper git handling
3. **Backup Synchronization**: Sync `~/.backup` folder with cloud storage for machine-specific configuration safety
4. **--expunge Flag**: Claude Code must never use the `--expunge` flag with `hms`
5. **macOS ARM Only**: This configuration is locked to `aarch64-darwin` (Apple Silicon Macs)
6. **NEVER USE HOMEBREW**: Do NOT suggest, recommend, or implement Homebrew. All packages MUST be managed through Nix (nixpkgs or nixpkgs-unstable).

## Configuration Structure

Domain-centric module architecture - related functionality co-located.

**Core files:** flake.nix (inputs/outputs), home.nix (entry point), user.nix (identity), overconfig.nix (machine-specific).

For detailed architecture, see README.md and source files in modules/.

## Development Workflows

**Add new package:**
1. Add to `modules/packages.nix` under appropriate category
2. For LSP servers: Also update Neovim LSP config
3. Run `hms` to apply
4. Verify: `which <package-name>`

**Add new shellapp:**
1. Create bash script in appropriate module directory (e.g., `modules/git/new-script.bash`)
2. Add shellapp definition to module's `_module.args.{domain}Shellapps` rec block
3. Add to git: `git add modules/git/new-script.bash`
4. Run `hms` to deploy
5. Command automatically available system-wide
6. Documentation auto-generated in `~/.claude/TOOLS.md`

**Add Claude Code skill:**
1. Create `modules/claude/global/commands/your-skill.md` with frontmatter
2. Add to git: `git add modules/claude/global/commands/your-skill.md`
3. Run `hms` to deploy
4. Skill automatically discovered in `~/.claude/commands/`

**Update Nix dependencies:**
1. `nix flake update` (updates flake.lock)
2. `hms` to apply
3. Test everything works
4. Commit flake.lock changes

## File Management

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

Both files made git-invisible by `hms` after first run. Backups linked via `*.latest.nix` symlinks.

## Claude Code Integration

**Configuration deployment:**
- Global settings: `modules/claude/global/CLAUDE.md` → `~/.claude/CLAUDE.md`
- Skills: `modules/claude/global/commands/*.md` → `~/.claude/commands/`
- Hooks: notification-hook, complete-hook, csharp-format-hook (configured in `modules/claude/default.nix`)
- Commands: `~/.claude/TOOLS.md` auto-generated from shellapp metadata

**MCP integration:**
- Context7 MCP auto-configured if `CONTEXT7_API_KEY` set in overconfig.nix
- Config merged into `~/.claude.json` (preserves Claude's metadata)
- To disable: Remove `CONTEXT7_API_KEY`, run `hms`

**Available skills:**
- Engineering: swe-backend, swe-frontend, swe-fullstack, swe-devex, swe-infra, swe-security, swe-sre
- Design: ux-designer, visual-designer
- Support: researcher, scribe, ai-expert
- Workflow: review-pr-comments
- Business: finance, lawyer, marketing

## Reference Documentation

**User setup:** See README.md for installation and daily usage procedures.

**Command reference:** See `~/.claude/TOOLS.md` (auto-generated from shellapp metadata on `hms`).

**Nix development:**
- `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`: Get hash for GitHub packages
- `nix flake update`: Update dependencies
- `nix flake check`: Validate syntax
- `nix flake metadata`: Show flake info
- `nix search nixpkgs <package>`: Search packages

**Implementation details:** See source files in `modules/` directories for specific configurations (theme, LSP, activation hooks, etc).
