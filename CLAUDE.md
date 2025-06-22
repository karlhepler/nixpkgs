# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This repository contains Nix Home Manager configuration for managing the user's development environment. It uses the Nix package manager with flakes to create a reproducible and declarative system configuration. The configuration includes shell setups (zsh), text editors (Neovim), terminal emulators, git configuration, and various developer tools.

## Common Commands

- `hms`: Update Home Manager with the latest changes (runs `home-manager switch --flake ~/.config/nixpkgs`)
- `hme`: Edit the `home.nix` file (main configuration file)
- `hmo`: Edit the `overconfig.nix` file (machine-specific customizations)
- `hm`: Change directory to Nix Packages configuration directory (`~/.config/nixpkgs`)

## Configuration Structure

- `flake.nix`: Defines the inputs and outputs for the Nix flake
- `home.nix`: Main configuration file that defines packages, programs, and configuration
- `overconfig.nix`: Machine-specific customizations (will be gitignored after sync)
- `neovim/`: Configuration files for Neovim
  - `vimrc`: Traditional Vim settings
  - `lspconfig.lua`: LSP (Language Server Protocol) configuration for Neovim

## Making Changes

1. When making changes to the configuration, modify the appropriate files in `~/.config/nixpkgs/`
2. To apply changes, run `hms` command which will:
   - Backup the current `overconfig.nix` file
   - Make git track changes to `overconfig.nix` temporarily
   - Run `home-manager switch` to apply the new configuration
   - Make git ignore changes to `overconfig.nix` again

## Important Notes

1. This repository **MUST** be installed at `~/.config/nixpkgs`. Installing it anywhere else will likely cause errors.
2. The `overconfig.nix` file is designed for per-machine customizations. Changes to this file are not tracked by git after a successful home-manager sync.
3. Use the `hms` command to sync changes, as it handles the git tracking of `overconfig.nix` appropriately.
4. The repository contains custom shell applications defined in `home.nix` under the `shellapps` section.
5. When updating GitHub packages using `rev = "main"`, always update the hash using the procedure in the "GitHub Package Updates" section.

## Custom Scripts

- `scripts/quicket.bash`: Script for creating Jira tickets
- `scripts/quickpr.bash`: Script for creating pull requests integrated with Jira tickets

## Useful Functions

The repository contains various Git shortcuts and utilities defined as shell applications:
- `commit`, `pull`, `push`, `save`: Enhanced git commands
- `git-branches`, `git-kill`, `git-trunk`, `git-sync`: Custom git workflow helpers

## GitHub Package Updates

When a package uses `rev = "main"` with a fixed hash in home.nix, use this procedure to update it:

1. Use `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main` to get the latest commit hash and SHA256
2. Update the hash in `home.nix`
3. Run `hms` to apply the changes
