# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This repository contains Nix Home Manager configuration for managing development environments using the Nix package manager with flakes. It creates reproducible and declarative system configurations including shell setups (zsh), text editors (Neovim), terminal emulators, git configuration, and developer tools.

**Critical Requirement**: This repository MUST be installed at `~/.config/nixpkgs` - other locations will cause errors.

## Quick Commands

### Configuration Management
- `hms`: Apply Home Manager changes (NEVER use `--expunge` flag)
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

## Nix Development Commands

- `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`: Get hash for GitHub packages
- `nix flake update`: Update flake dependencies
- `nix flake check`: Validate Nix syntax and configuration
- `nix flake metadata`: Show flake metadata
- `nix search nixpkgs <package>`: Search for available packages

## Configuration Structure

This repository uses a **domain-centric module architecture** where related functionality is co-located:

### Core Files
- `flake.nix`: Defines inputs/outputs, manages nixpkgs (25.11 stable) and nixpkgs-unstable
  - Version controlled in one place: Update `nixpkgs.url`, `home-manager.url`, and `releaseVersion` together
  - System locked to `aarch64-darwin` (macOS ARM)
- `home.nix`: Main entry point that imports all modules and aggregates shellapps
- `user.nix`: User-specific identity (name, email, username, homeDirectory) - gitignored after sync
- `overconfig.nix`: Machine-specific customizations (gitignored after sync, manages its own git-ignore behavior)

### Module Architecture

**Complex Modules** (directories with default.nix):
- `modules/system/` - System-level shellapp (hms) + bash script
- `modules/git/` - Git configuration + 11 git shellapps + bash scripts (commit, pull, push, save, git-branches, git-kill, git-trunk, git-sync, git-resume, git-tmp, workout)
- `modules/claude/` - Claude Code configuration with:
  - 7 claude shellapps + bash scripts (notification-hook, complete-hook, csharp-format-hook, claude-ask, q, qq, qqq)
  - `global/` directory containing Claude Code settings, output styles, and skills (mirrors ~/.claude/ structure)

**Simple Modules** (single .nix files):
- `modules/theme.nix` - Tokyo Night Storm color theme + font configuration (cross-cutting concern)
- `modules/packages.nix` - Package declarations + simple program configs (fzf, neovide, starship, zoxide, nix-index)
  - Most packages from stable `pkgs` (25.11)
  - Cutting-edge packages from `unstable` channel (like neovide)
  - Packages organized by category: Core Tools, Shell Enhancement, Development, Languages, etc.
- `modules/zsh.nix` - Zsh shell configuration + precompileZshCompletions activation hook
- `modules/direnv.nix` - Direnv configuration + generateDirenvHook activation hook (performance optimization)
- `modules/alacritty.nix` - Alacritty terminal emulator with theme integration
- `modules/tmux.nix` - Tmux terminal multiplexer with plugins and theme integration

### Other Directories
- `neovim/` - Neovim configuration files (vimrc, lspconfig.lua, lsp/, plugins/)
- `modules/claude/global/` - Global Claude Code settings and skills (mirrors ~/.claude/ structure)
  - `CLAUDE.md` - Global guidelines for Claude Code
  - `output-styles/` - Custom output styles (4qs-facilitator)
  - `commands/` - User-level skills and commands (try-again, review-pr-comments)

## Shellapp Pattern

This repository uses a **hybrid shellapp pattern** for managing custom bash scripts:

1. **Definition**: Shellapps are defined in each module's `default.nix` via `_module.args.{domain}Shellapps = rec { ... };`
2. **Aggregation**: home.nix dynamically merges all shellapps using `//` operator
3. **Distribution**: Aggregated shellapps passed to all modules via `_module.args`
4. **Package Integration**: All shellapps exposed to system via `modules/packages.nix`

**The shellApp Helper** (`modules/lib/shellApp.nix`):
- Creates shell applications with metadata (description, mainProgram, source file location)
- Automatically tracks source file locations for documentation generation
- Provides runtime dependency injection via `runtimeInputs`
- Generates TOOLS.md via `modules/claude/generate-tools-md.nix` during activation

**Adding New Shellapps**:
- Add bash script to appropriate module directory (e.g., `modules/git/new-script.bash`)
- Add shellapp definition to that module's `_module.args.{domain}Shellapps` rec block
- Automatically available system-wide (no changes needed in home.nix)

**Recursive Dependencies**: Use `rec` pattern in module shellapp definitions for intra-module dependencies (e.g., `save` depends on `commit` + `push` in git module)

**Shell Wrapper Pattern**: Some commands require shell wrappers for directory changes:
- `workout`: Wrapper in `modules/zsh.nix` evaluates cd commands from the script
- The script outputs shell commands to stdout, wrapper `eval`s them
- Enables changing parent shell's directory (impossible from subprocess)

## Home Manager Activation Process

When running `hms`, these activation hooks run automatically:
1. **gitIgnoreUserChanges** (in home.nix): Makes git ignore user.nix changes
2. **gitIgnoreOverconfigChanges** (in home.nix): Makes git ignore overconfig.nix changes
3. **claudeSettings** (modules/claude/): Symlinks Claude Code settings with configured hooks
4. **claudeGlobal** (modules/claude/): Deploys all Claude Code configuration:
   - Copies global settings (CLAUDE.md, output-styles/)
   - Generates TOOLS.md from package metadata
   - Deploys skills to ~/.claude/commands/
5. **precompileZshCompletions** (modules/zsh.nix): Compiles zsh completions for faster shell startup
6. **generateDirenvHook** (modules/direnv.nix): Creates static direnv hook for performance

Note: Application management is handled natively by home-manager 25.11+. Apps are automatically available in ~/Applications/Home Manager Apps for Spotlight/Alfred indexing.

## Theme System

Centralized theme configuration in `modules/theme.nix` provides:
- Tokyo Night Storm colors (variant = "storm")
- Font configuration (SauceCodePro Nerd Font Mono, size 20)
- Used by: Alacritty, Tmux, Neovim, Neovide

Theme is imported in home.nix and passed to all modules via `_module.args`.

## User Configuration

**user.nix File Management:**
- Contains user identity information used across all modules
- Made "invisible" to git using `git update-index --assume-unchanged`
- The `hms` command handles visibility automatically:
  1. Validates user.nix exists and has no placeholder values
  2. Makes file visible: `git update-index --no-assume-unchanged user.nix`
  3. Backs up to `~/.backup/.config/nixpkgs/user.YYYYMMDD-HHMMSS.nix`
  4. Runs home-manager switch
  5. Configures local git for this repo using user.nix values
  6. Makes file invisible again via activation hook
- **Automatic backups**: Created at `~/.backup/.config/nixpkgs/user.YYYYMMDD-HHMMSS.nix`
- Symlink `user.latest.nix` points to most recent backup

**Fields:**
- `name`: Full name (used for git user.name)
- `email`: Personal email (used for git user.email)
- `username`: System username (used for homeConfigurations, GitHub repos)
- `homeDirectory`: Home directory path

**Editing:** Use `hmu` to edit user.nix

**Work Email Override:** Still handled in overconfig.nix:
```nix
programs.git.settings.user.email = lib.mkForce "work@email.com";
```

## Important Git Handling

**overconfig.nix File Management:**
- Designed for per-machine customizations and secrets
- Made "invisible" to git using `git update-index --assume-unchanged`
- The `hms` command handles visibility automatically:
  1. Makes file visible: `git update-index --no-assume-unchanged overconfig.nix`
  2. Runs home-manager switch
  3. Makes file invisible again via `gitIgnoreOverconfigChanges` activation hook in home.nix
- **Automatic backups**: Created at `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix`
- Symlink `overconfig.latest.nix` points to most recent backup

**Local Git Configuration for This Repository:**

CRITICAL: `user.nix` values are automatically configured as local git settings by `hms`.

The `hms` command automatically runs:
```bash
git config --local user.name "<name from user.nix>"
git config --local user.email "<email from user.nix>"
```

This ensures commits to THIS repository always use personal credentials from user.nix,
even on work machines where overconfig.nix overrides global git config.

Verify with:
```bash
git config --local --get user.email
# Should output your personal email from user.nix
```

**Why**: This is a personal repository that should always use personal git credentials, even on work machines where global config is overridden for work projects.

## Claude Code Configuration

This repository includes integrated Claude Code settings:
- Global preferences and guidelines in `modules/claude/global/CLAUDE.md`
- User-level skills in `modules/claude/global/commands/`:
  - Engineering: `backend-engineer`, `frontend-engineer`, `fullstack-engineer`
  - Support: `researcher`, `facilitator`, `scribe`
  - Workflow: `review-pr-comments`
- Notification and completion hooks configured in `modules/claude/default.nix`
- Settings and skills automatically deployed to `~/.claude/` on `hms`
- Runtime state managed through `.claude/` directory (gitignored)

**Adding New Skills:**
1. Create `modules/claude/global/commands/your-skill.md` with frontmatter:
   ```markdown
   ---
   description: Trigger conditions for when Claude should use this skill
   ---
   ```
2. Run `hms` to deploy
3. Skill automatically discovered by Claude Code in `~/.claude/commands/`

**MCP (Model Context Protocol) Configuration:**

Context7 MCP integration is automatically configured when `CONTEXT7_API_KEY` is set in `overconfig.nix`:
- The activation hook merges MCP config into `~/.claude.json` (preserves Claude's metadata)
- Uses `$CONTEXT7_API_KEY` environment variable reference for runtime access
- Configuration is merged, not overwritten - Claude Code can still manage its own metadata
- The MCP server uses `npx -y @upstash/context7-mcp` for on-demand execution

To disable: Remove `CONTEXT7_API_KEY` from `overconfig.nix` and run `hms`

## Common Development Workflows

### Making Configuration Changes
1. Edit configuration files (`hme`, `hmu`, or `hmo`)
2. Apply changes: `hms` (backups created automatically)
3. Check activation hook output for any errors
4. Verify changes work as expected

### Adding a New Package
1. Add package to `modules/packages.nix` under appropriate category
2. For language servers: Add to LSP section and update Neovim LSP config if needed
3. Apply changes: `hms`
4. Verify package is available: `which <package-name>`

### Adding a New Shellapp
1. Create bash script in appropriate module directory
2. Add shellapp definition to module's `_module.args.{domain}Shellapps`
3. Apply changes: `hms`
4. New command automatically available system-wide
5. Documentation auto-generated in `~/.claude/TOOLS.md`

### Working with Worktrees
1. Navigate to any git repository
2. Run `workout feature-branch` to create/navigate to worktree
3. Work in isolated directory: `~/worktrees/org/repo/feature-branch/`
4. Use `workout -` to toggle back to previous location
5. Run `workout` (no args) to browse and manage all worktrees interactively

### Updating Nix Dependencies
1. Update flake inputs: `nix flake update`
2. Apply changes: `hms`
3. Test that everything still works
4. Commit flake.lock changes

### GitHub Package Updates
For packages using `rev = "main"` with fixed hash:
1. Get latest hash: `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`
2. Update hash in the appropriate module file
3. Apply changes: `hms`

## Architecture Principles

1. **Domain-Centric Organization**: Everything about a domain lives together (config + scripts + shellapps)
2. **Co-location**: Bash scripts physically near their shellapp definitions
3. **Complexity Threshold**: Only extract to own module if sufficiently complex (40+ lines OR important activation hooks)
4. **YAGNI**: Simple things stay simple (single .nix files), complex things get directories
5. **DRY**: Centralized theme eliminates duplication across terminal, editor, multiplexer

## Environment Variables

Configured in `modules/zsh.nix`:
- `PATH`: Includes `~/.local/bin`, `~/.nix-profile/bin`, Go bin, npm bin, Rancher Desktop bin
- `LANG`, `LC_ALL`, `LC_CTYPE`: Set to `en_US.UTF-8`
- `ZSH_AUTOSUGGEST_USE_ASYNC`: `true` (performance)
- `ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE`: `20` (performance)
- `WORKTREE_ROOT`: Defaults to `~/worktrees` (can be overridden for custom worktree location)

## Critical Requirements

1. **Repository Location**: MUST be installed at `~/.config/nixpkgs`
2. **Use hms Command**: Always use `hms` for syncing to ensure proper git handling of overconfig.nix
3. **Backup Synchronization**: Sync `~/.backup` folder with cloud storage for machine-specific configuration safety
4. **No --expunge Flag**: Claude Code must never use the `--expunge` flag with `hms`
5. **macOS ARM Only**: This configuration is locked to `aarch64-darwin` (Apple Silicon Macs)

## Adding New Modules

**For modules WITH scripts** (complex):
1. Create `modules/{domain}/` directory
2. Create `modules/{domain}/default.nix` with:
   - `_module.args.{domain}Shellapps = rec { ... };` for shellapp definitions
   - Program configuration (e.g., `programs.{tool} = { ... };`)
   - Activation hooks if needed
3. Add bash scripts to same directory
4. Add `// (config._module.args.{domain}Shellapps or {})` to shellapp aggregation in home.nix
5. Add `./modules/{domain}` to imports in home.nix

**For modules WITHOUT scripts** (simple):
1. Create `modules/{name}.nix` file
2. Add program configuration directly
3. Add `./modules/{name}.nix` to imports in home.nix

## Performance Optimizations

This config includes several shell performance optimizations:
- **Precompiled zsh completions**: `.zcompdump.zwc` compiled via activation hook
- **Static direnv hook**: Generated once, sourced on shell start (no dynamic generation)
- **Async zsh autosuggestions**: `ZSH_AUTOSUGGEST_USE_ASYNC=true`
- **Fast compinit**: Skips security checks with `compinit -C`
- **Completion caching**: Completions precompiled at configuration time, not runtime

## Tmux Integration

**Session Management**:
- Random emoji icons for sessions via `random-emoji` shellapp
- Random session names from Simpsons words via `random-session-name`
- Tokyo Night Storm theme integration

**Window Attention System**:
- Bell-based visual alerts when commands complete in background windows
- Claude Code notification hook triggers tmux bells
- Active window clears attention flag automatically
- Inactive windows change color when attention needed

**Theme Features**:
- Powerline separators for clean visual hierarchy
- Dynamic window icons (active vs inactive vs zoomed)
- Prefix indicator (yellow when prefix key pressed)
- Synchronized pane indicator (✵ when panes synced)

## Editors and Terminal

- **Primary Editor**: Neovim (vim/vi aliases enabled)
- **GUI Editor**: Neovide (unstable channel, for double-clicking files in macOS UI)
- **Terminal**: Alacritty (configured with Tokyo Night Storm theme)
- **Font**: SauceCodePro Nerd Font Mono, size 20
- **Color Scheme**: Tokyo Night Storm (consistent across tmux, Alacritty, Neovim)

## Neovim Integration

Key integrations:
- **LSP**: Configured for TypeScript, Bash, C#, Nix, Go, Python, Haskell
- **claude-tmux-neovim**: Special plugin for Claude Code integration (keybindings for sending selections)
- **FZF Integration**: `<C-p>` for file search, `<C-b>` for LSP symbols
- **Copilot**: GitHub Copilot enabled
- **Treesitter**: Parsers for bash, C#, gdscript, go, helm, lua, markdown, nix, python, rust, starlark, typescript, yaml

## Zsh Keybindings

**Vi Mode**:
- `jk` - Enter vi command mode from insert mode

**Line Navigation**:
- `^A` - Beginning of line (insert mode)
- `^E` - End of line (insert mode)
- `^X^E` - Edit command in Neovim (both insert and command mode)

**Special Commands**:
- `^J` - Super newline (adds 5 newlines and executes)
- `^D` - Exit with confirmation (defaults to No, requires explicit y/Y)

## Git Aliases

Configured in `modules/git/default.nix`:
- `git who` - Enhanced blame with whitespace/move detection (`-w -C -C -C`)
- `git difft` - Use difftastic for diff output
- `git logt` - Use difftastic for log with patches
- `git showt` - Use difftastic for show command

## Claude Code Hooks

Configured in `modules/claude/default.nix`, automatically deployed to `~/.claude/settings.json`:

**Notification Hook**:
- Triggered on: Every notification event
- Purpose: Desktop notifications with tmux integration
- Script: `claude-notification-hook.bash`

**Complete Hook**:
- Triggered on: Session stop/completion
- Purpose: Post-completion actions
- Script: `claude-complete-hook.bash`

**C# Format Hook**:
- Triggered on: After Edit/MultiEdit/Write tool use
- Purpose: Auto-format C# files with csharpier
- Script: `claude-csharp-format-hook.bash`
- Requires: `csharpier` package (included in packages.nix)
