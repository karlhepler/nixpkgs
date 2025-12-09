# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This repository contains Nix Home Manager configuration for managing development environments using the Nix package manager with flakes. It creates reproducible and declarative system configurations including shell setups (zsh), text editors (Neovim), terminal emulators, git configuration, and developer tools.

**Critical Requirement**: This repository MUST be installed at `~/.config/nixpkgs` - other locations will cause errors.

## Quick Commands

- `hms`: Apply Home Manager changes (use `--expunge` for complete environment refresh)
- `hme`: Edit the `home.nix` file (main configuration)
- `hmu`: Edit the `user.nix` file (user-specific identity)
- `hmo`: Edit the `overconfig.nix` file (machine-specific customizations)
- `hm`: Change directory to Nix Packages configuration directory (`~/.config/nixpkgs`)

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
- `home.nix`: Main entry point that imports all modules and aggregates shellapps
- `user.nix`: User-specific identity (name, email, username, homeDirectory) - gitignored after sync
- `overconfig.nix`: Machine-specific customizations (gitignored after sync, manages its own git-ignore behavior)

### Module Architecture

**Complex Modules** (directories with default.nix):
- `modules/system/` - System-level shellapp (hms) + bash script
- `modules/git/` - Git configuration + 11 git shellapps + bash scripts (commit, pull, push, save, git-branches, git-kill, git-trunk, git-sync, git-resume, git-tmp, workout)
- `modules/claude/` - Claude Code activation hooks + 3 claude shellapps + bash scripts (notification-hook, complete-hook, csharp-format-hook)

**Simple Modules** (single .nix files):
- `modules/theme.nix` - Tokyo Night Storm color theme + font configuration (cross-cutting concern)
- `modules/packages.nix` - Package declarations + simple program configs (fzf, neovide, starship, zoxide, nix-index)
- `modules/zsh.nix` - Zsh shell configuration + precompileZshCompletions activation hook
- `modules/direnv.nix` - Direnv configuration + generateDirenvHook activation hook (performance optimization)
- `modules/alacritty.nix` - Alacritty terminal emulator with theme integration
- `modules/tmux.nix` - Tmux terminal multiplexer with plugins and theme integration

### Other Directories
- `neovim/` - Neovim configuration files (vimrc, lspconfig.lua, lsp/, plugins/)
- `claude-global/` - Global Claude Code settings (CLAUDE.md)

## Shellapp Pattern

This repository uses a **hybrid shellapp pattern** for managing custom bash scripts:

1. **Definition**: Shellapps are defined in each module's `default.nix` via `_module.args.{domain}Shellapps = rec { ... };`
2. **Aggregation**: home.nix dynamically merges all shellapps using `//` operator
3. **Distribution**: Aggregated shellapps passed to all modules via `_module.args`
4. **Package Integration**: All shellapps exposed to system via `modules/packages.nix`

**Adding New Shellapps**:
- Add bash script to appropriate module directory (e.g., `modules/git/new-script.bash`)
- Add shellapp definition to that module's `_module.args.{domain}Shellapps` rec block
- Automatically available system-wide (no changes needed in home.nix)

**Recursive Dependencies**: Use `rec` pattern in module shellapp definitions for intra-module dependencies (e.g., `save` depends on `commit` + `push` in git module)

## Home Manager Activation Process

When running `hms`, these activation hooks run automatically:
1. **gitIgnoreOverconfigChanges** (in overconfig.nix): Makes git ignore overconfig.nix changes
2. **claudeSettings** (modules/claude/): Symlinks Claude Code settings with configured hooks
3. **claudeGlobal** (modules/claude/): Copies global Claude settings
4. **precompileZshCompletions** (modules/zsh/): Compiles zsh completions for faster shell startup
5. **generateDirenvHook** (modules/direnv/): Creates static direnv hook for performance

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
- `userName`: Full name (used for git user.name)
- `userEmail`: Personal email (used for git user.email)
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
- Contains its own `home.activation.gitIgnoreOverconfigChanges` hook
- Made "invisible" to git using `git update-index --assume-unchanged`
- The `hms` command handles visibility automatically:
  1. Makes file visible: `git update-index --no-assume-unchanged overconfig.nix`
  2. Runs home-manager switch
  3. Makes file invisible again via activation hook
- **Automatic backups**: Created at `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix`
- Symlink `overconfig.latest.nix` points to most recent backup

**Local Git Configuration for This Repository:**

CRITICAL: `user.nix` values are automatically configured as local git settings by `hms`.

The `hms` command automatically runs:
```bash
git config --local user.name "<userName from user.nix>"
git config --local user.email "<userEmail from user.nix>"
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
- Global preferences defined in `claude-global/CLAUDE.md`
- Notification and completion hooks configured in `modules/claude/default.nix`
- Settings managed through `.claude/` directory (gitignored)

## GitHub Package Updates

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

## Critical Requirements

1. **Repository Location**: MUST be installed at `~/.config/nixpkgs`
2. **Use hms Command**: Always use `hms` for syncing to ensure proper git handling of overconfig.nix
3. **Backup Synchronization**: Sync `~/.backup` folder with cloud storage for machine-specific configuration safety
4. **No --expunge Flag**: Claude Code must never use the `--expunge` flag with `hms`

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
- Precompiled zsh completions (`.zcompdump.zwc`)
- Static direnv hook generation (avoids dynamic generation on every shell start)
- Async zsh autosuggestions
- Fast compinit without security checks (`compinit -C`)

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
