# Nix Home Manager Configuration

A reproducible and declarative development environment configuration using Nix Home Manager with flakes.

**Critical**: This repository MUST be installed at `~/.config/nixpkgs` - other locations will cause errors.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [First-Time Setup](#first-time-setup)
- [Daily Usage](#daily-usage)
- [Customization](#customization)
- [Helpful Commands](#helpful-commands)

---

## Prerequisites

- macOS (Darwin)
- Git installed
- GitHub SSH keys configured (for cloning private repos)

---

## First-Time Setup

### 1. Install Nix Package Manager

```bash
# Install Nix with official installer
sh <(curl -L https://nixos.org/nix/install)
```

### 2. Enable Nix Flakes

```bash
# Create Nix config directory
mkdir -p ~/.config/nix

# Enable experimental flakes feature
echo 'experimental-features = nix-command flakes' > ~/.config/nix/nix.conf
```

### 3. Clone This Repository

**Important**: Must be cloned to `~/.config/nixpkgs` (no other location will work)

```bash
# Clone to the required location
cd ~/.config
git clone <your-repo-url> nixpkgs
cd nixpkgs
```

### 4. Configure User Information

Edit `user.nix` to replace all `CHANGE_ME` placeholders with your information:

```bash
vim user.nix
```

Required fields:
- `name` - Your full name (for git user.name)
- `email` - Your personal email (for git user.email)
- `username` - Your system username (must match your macOS username)
- `homeDirectory` - Your home directory path (typically `/Users/YOUR_USERNAME`)

**Example**:
```nix
{
  user = {
    name = "Jane Smith";
    email = "jane.smith@personal.com";
    username = "janesmith";
    homeDirectory = "/Users/janesmith";
  };
}
```

### 5. Initial Home Manager Installation

Run the initial installation using the full nix command:

```bash
# Replace YOUR_USERNAME with the username you set in user.nix
nix run nixpkgs#home-manager -- switch --flake .#YOUR_USERNAME
```

**Note**: This is the ONLY time you need to run this long command. After this, use the `hms` command.

### 6. Reload Your Shell

```bash
# Restart your terminal or run:
exec zsh
```

### 7. Verify Installation

Applications will now be available in:
- `~/Applications/Home Manager Apps/`
- Searchable via Spotlight/Alfred

Check that commands work:
```bash
hms --help   # Should show home-manager help
hme          # Should open home.nix in vim
```

---

## Daily Usage

### Applying Configuration Changes

After editing any `.nix` files, apply changes with:

```bash
hms
```

This command automatically:
1. Validates `user.nix` has no placeholder values
2. Backs up `user.nix` and `overconfig.nix` with timestamps
3. Temporarily makes files visible to git
4. Runs home-manager switch
5. Configures local git settings for this repo
6. Makes files invisible to git again

**Backups** are stored in:
- `~/.backup/.config/nixpkgs/user.YYYYMMDD-HHMMSS.nix`
- `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix`

### Complete Environment Refresh

If you need to completely refresh your environment (kills tmux, rebuilds everything):

```bash
hms --expunge
```

**Warning**: This will kill your tmux server. Use sparingly.

---

## Customization

### User-Specific Configuration (`user.nix`)

Contains your personal identity information. Edit with:

```bash
hmu
```

After the first `hms` run, this file becomes git-ignored (your changes won't be tracked).

### Machine-Specific Configuration (`overconfig.nix`)

For per-machine customizations like work email overrides. Edit with:

```bash
hmo
```

**Example**: Override git email for work machine:
```nix
{ config, pkgs, lib, ... }:

{
  # Override git email for work
  programs.git.settings.user.email = lib.mkForce "jane.smith@work.com";
}
```

After the first `hms` run, this file also becomes git-ignored.

### Main Configuration (`home.nix`)

Edit the main configuration with:

```bash
hme
```

---

## Helpful Commands

### Configuration Management
- `hms` - Apply Home Manager changes (runs home-manager switch)
- `hme` - Edit `home.nix` (main configuration)
- `hmu` - Edit `user.nix` (user-specific identity)
- `hmo` - Edit `overconfig.nix` (machine-specific customizations)
- `hm` - Change directory to `~/.config/nixpkgs`

### Git Workflow (Custom Commands)
- `save "message"` - Stage all, commit, and push in one command
- `commit "message"` - Stage all and commit
- `push` - Push to remote
- `pull` - Pull from remote
- `git-sync` - Sync with remote (stash, pull, pop)
- `git-trunk` - Switch to main branch
- `git-branches` - List all branches
- `git-kill <branch>` - Delete a branch
- `git-resume` - Resume previous branch
- `git-tmp` - Create temporary branch
- `workout` - Interactive branch cleanup

### Nix Development
- `nix flake update` - Update all flake inputs
- `nix flake check` - Validate configuration
- `nix flake metadata` - Show flake information
- `nix search nixpkgs <package>` - Search for packages

---

## Local Git Configuration

The `hms` command automatically configures this repository's local git settings using values from `user.nix`. This ensures commits to this repository always use your personal credentials, even on work machines where `overconfig.nix` overrides global git settings.

Verify local git configuration:
```bash
cd ~/.config/nixpkgs
git config --local --get user.name
git config --local --get user.email
```

These should match the values in your `user.nix` file.

---

## Architecture

See `CLAUDE.md` for detailed documentation on:
- Module structure and organization
- Adding new modules and shell scripts
- Theme system
- Activation hooks
- Performance optimizations

---

## Included Tools

- **Shell**: Zsh with completions, syntax highlighting, autosuggestions
- **Editor**: Neovim with LSP support (TypeScript, Bash, C#, Nix, Go, Python, Haskell)
- **GUI Editor**: Neovide
- **Terminal**: Alacritty (Tokyo Night Storm theme)
- **Multiplexer**: Tmux (Tokyo Night Storm theme)
- **Version Control**: Git with custom workflows
- **Fuzzy Finder**: FZF integrated with Neovim
- **Directory Navigation**: Zoxide
- **Environment Management**: Direnv
- **Font**: SauceCodePro Nerd Font Mono
- **AI**: GitHub Copilot, Claude Code integration
