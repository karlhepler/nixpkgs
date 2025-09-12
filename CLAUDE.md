# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this Nix Home Manager repository.

## Repository Overview

This repository contains Nix Home Manager configuration for managing development environments using the Nix package manager with flakes. It creates reproducible and declarative system configurations including shell setups (zsh), text editors (Neovim), terminal emulators, git configuration, and developer tools.

## Quick Commands

- `hms`: Update Home Manager with latest changes (runs `home-manager switch --flake ~/.config/nixpkgs`)
  - **Safe tmux handling**: Prompts before killing tmux server - only kills if you explicitly type `y`/`Y`
  - **Never use with `yes`**: Command is designed to require manual confirmation for tmux restart
- `hme`: Edit the `home.nix` file (main configuration)
- `hmo`: Edit the `overconfig.nix` file (machine-specific customizations)
- `hm`: Change directory to Nix Packages configuration directory (`~/.config/nixpkgs`)

## Configuration Structure

- `flake.nix`: Defines inputs and outputs for the Nix flake
- `home.nix`: Main configuration file defining packages, programs, and configuration
- `overconfig.nix`: Machine-specific customizations (gitignored after sync)
- `claude-global.md`: Global Claude Code configuration and development preferences
- `.claude/`: Directory for Claude Code settings (gitignored)
- `neovim/`: Neovim configuration files
  - `vimrc`: Traditional Vim settings
  - `lspconfig.lua`: LSP (Language Server Protocol) configuration
- `scripts/`: Custom shell scripts and automation tools

## Making Changes

1. Modify appropriate files in `~/.config/nixpkgs/`
2. Run `hms` command which automatically:
   - Creates backup of `overconfig.nix` to `~/.backup/.config/nixpkgs/`
   - Makes git track `overconfig.nix` temporarily
   - Runs `home-manager switch` to apply configuration
   - Makes git ignore `overconfig.nix` changes again
   - Prompts to restart tmux server (requires explicit `y`/`Y` confirmation)

## Shell Applications (Custom Commands)

### Git Workflow
- `commit`: Enhanced git commit with automatic staging
- `pull`: Smart git pull with automatic upstream tracking
- `push`: Smart git push with automatic upstream setting
- `save`: Combines commit and push operations
- `git-branches`: Interactive branch selector with preview
- `git-kill`: Reset current branch to clean state
- `git-trunk`: Switch to and update main/master branch
- `git-sync`: Merge latest trunk changes into current branch
- `git-resume`: Checkout most recently used branch
- `git-tmp`: Create/switch to temporary branch (karlhepler/tmp)

### Claude Code Integration
- `claude-notification-hook`: Handles Claude Code notifications
- `claude-complete-hook`: Handles Claude Code completion events

## Custom Scripts

- `scripts/quicket.bash`: Create Jira tickets
- `scripts/quickpr.bash`: Create pull requests integrated with Jira
- `scripts/claude-notification-hook.bash`: Claude Code notification handler
- `scripts/claude-complete-hook.bash`: Claude Code completion handler
- `scripts/test-optimizations.bash`: Shell optimization testing
- `scripts/profile-shell.bash`: Shell performance profiling

## Important Git Handling

**overconfig.nix File Management:**
- Designed for per-machine customizations and secrets
- Made "invisible" to git using `git update-index --assume-unchanged`
- The `hms` command handles visibility automatically:
  1. Makes file visible: `git update-index --no-assume-unchanged overconfig.nix`
  2. Runs home-manager switch
  3. Makes file invisible again: `git update-index --assume-unchanged overconfig.nix`
- **Automatic backups**: Created at `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix`
- Symlink `overconfig.latest.nix` points to most recent backup

## Claude Code Configuration

This repository includes integrated Claude Code settings:
- Global preferences defined in `claude-global.md`
- Notification and completion hooks configured in `home.nix`
- Settings managed through `.claude/` directory (gitignored)

## GitHub Package Updates

For packages using `rev = "main"` with fixed hash:

1. Get latest hash: `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`
2. Update hash in `home.nix`
3. Apply changes: `hms`

## Critical Requirements

1. **Repository Location**: MUST be installed at `~/.config/nixpkgs` - other locations will cause errors
2. **Use hms Command**: Always use `hms` for syncing to ensure proper git handling of `overconfig.nix`
3. **Backup Synchronization**: Sync `~/.backup` folder with cloud storage for machine-specific configuration safety
4. **Shell Applications**: All custom commands are defined in `home.nix` under the `shellapps` section

## Automation Safety for Claude Code

When Claude Code runs `hms`, it must use: `echo 'n' | hms`

This ensures:
- Home Manager configuration is applied successfully
- tmux server is never killed automatically
- User retains full control over tmux restart timing
- All other hms functionality works normally (backup, git handling, etc.)