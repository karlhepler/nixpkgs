# My Mac setup

My development environment, described in code with [Nix](https://nixos.org) and
[Home Manager](https://nix-community.github.io/home-manager/): shell, editor, terminal,
git, and the tools I use every day. Run one command and any Apple Silicon Mac ends up
configured the same way.

- It must live at `~/.config/nixpkgs`. Several things refer to that path.
- It is for Apple Silicon Macs only (`aarch64-darwin`).
- My name, email and secrets are **not** in this repository. They live in two files that
  stay on each machine (see [Personal files](#personal-files)).

## Contents

- [Set up a new Mac](#set-up-a-new-mac)
- [Daily use](#daily-use)
- [Personal files](#personal-files)
- [Updating](#updating)
- [Upgrading a machine that was set up before the cleanup](#upgrading-a-machine-that-was-set-up-before-the-cleanup)
- [What's in it](#whats-in-it)
- [Commands](#commands)
- [Where things live](#where-things-live)
- [Troubleshooting](#troubleshooting)

---

## Set up a new Mac

You need an Apple Silicon Mac and a user account that is an administrator. Run these in
Terminal, in order.

### 1. Install the command line tools (this provides `git`)

```bash
xcode-select --install
```

Click through the installer, then continue.

### 2. Install Nix

```bash
curl --proto '=https' --tlsv1.2 -L https://nixos.org/nix/install | sh
```

This is the multi-user install from [nixos.org/download](https://nixos.org/download/).
It asks for your password. **Close the terminal and open a new one** so `nix` is on your
`PATH`.

### 3. Get this repository

```bash
git clone <this-repository-url> ~/.config/nixpkgs
cd ~/.config/nixpkgs
```

The location is not optional. For a private repository, sign in first (for example with
an SSH key added to your GitHub account) or use the HTTPS URL and a token.

### 4. Fill in `user.nix`

The repository ships `user.nix` as a template full of `CHANGE_ME`. Open it:

```bash
vim user.nix
```

and set all four values:

| Field | What to put | Example |
|---|---|---|
| `name` | Your full name (used for git commits) | `"Jane Smith"` |
| `email` | The email for git commits | `"jane@example.com"` |
| `username` | Your macOS short name. Check with `id -un` | `"janesmith"` |
| `homeDirectory` | Your home folder. Check with `echo $HOME` | `"/Users/janesmith"` |

`username` must match your macOS account exactly, or the next step finds no configuration
for you.

### 5. (Optional) Machine-specific settings in `overconfig.nix`

Leave it alone for a plain setup. This is where things that belong to one machine go:
a different git email for a work laptop, API keys, extra packages. See
[Personal files](#personal-files).

### 6. The first switch

```bash
NIX_CONFIG="experimental-features = nix-command flakes" \
  nix run home-manager/release-26.05 -- switch -b backup --flake ".#$(id -un)"
```

This builds everything and takes a while the first time (mostly downloading). Three
things about it:

- **`NIX_CONFIG=...`** turns on flakes for this one command only. The configuration then
  writes `~/.config/nix/nix.conf` itself, so flakes stay on afterwards. **Do not create
  that file by hand**: Home Manager would refuse to overwrite it.
- **`-b backup`** renames any file that is in the way (for example an existing `~/.zshrc`)
  to `<name>.backup` instead of stopping.
- **This long command is a one-off.** From now on you use `hms`.

### 7. Finish up

```bash
exec zsh      # load the new shell
hms           # first real run: installs Claude Code, sets this repo's git identity
```

Then open **Alacritty** (it is in `~/Applications/Home Manager Apps/`, and Spotlight finds
it). It starts tmux automatically. When macOS asks whether Alacritty may find devices on
the local network, allow it: SSH to machines on your network needs that.

### 8. Check that it worked

```bash
hms --help                          # prints hms's own help
which nvim tmux gh                  # all three resolve
git -C ~/.config/nixpkgs status     # clean: user.nix and overconfig.nix are hidden
git -C ~/.config/nixpkgs config --local user.email   # the email you put in user.nix
```

---

## Daily use

After changing anything in this repository:

```bash
git add <any new files>     # Nix only sees files git knows about
hms                         # build and activate
```

If `hms` succeeds, commit and push. If it fails, the change is broken; fix it first.

`hms` does this, in order: refuses to run as root; checks `user.nix` has no placeholders;
backs up `user.nix` and `overconfig.nix`; builds and activates the configuration; installs
Claude Code if missing; sets this repository's git identity. It always re-hides your two
personal files from git when it finishes, even if the build failed. Full details:
[`modules/system/HMS.md`](modules/system/HMS.md).

**`hms --purge`** also kills the tmux server when it finishes. Use it deliberately after
changing tmux settings, in a terminal where losing every session is fine.

| Alias | Opens |
|---|---|
| `hme` | `home.nix`, the list of what gets loaded |
| `hmu` | `user.nix`, who you are |
| `hmo` | `overconfig.nix`, this machine's own settings |
| `hm`  | goes to `~/.config/nixpkgs` |

A running terminal does not pick up changes. Open a new window, or run `reload-env`.

---

## Personal files

Two files hold things that belong to one machine, and git is told to ignore edits to them,
so changing them can never end up in a commit:

| File | Holds | Edit with |
|---|---|---|
| `user.nix` | your name, email, username, home folder | `hmu` |
| `overconfig.nix` | per-machine overrides and secrets | `hmo` |

The repository contains only blank templates of both. After the first `hms`, git stops
tracking your local changes to them.

`hms` copies both to `~/.backup/.config/nixpkgs/` with a timestamp every time it runs
(`user.latest.nix` and `overconfig.latest.nix` point at the newest). To restore one:

```bash
cp ~/.backup/.config/nixpkgs/user.latest.nix ~/.config/nixpkgs/user.nix
```

Keep `~/.backup` somewhere safe (cloud storage, Time Machine). It is the only copy of
your secrets.

**Never run `git add user.nix` or `git add overconfig.nix`.** A pre-commit hook blocks it
as a second line of defence.

Example `overconfig.nix` (a different email on a work laptop):

```nix
{ config, pkgs, lib, ... }:

{
  programs.git.settings.user.email = lib.mkForce "jane@work.example";

  home.sessionVariables = {
    SOME_API_KEY = "...";
  };
}
```

---

## Updating

**Packages and tools** (bring everything to the newest build of the current release):

```bash
cd ~/.config/nixpkgs
nix flake update     # rewrites flake.lock
hms
```

If it all works, commit `flake.lock`.

**A new Nixpkgs release** (for example 26.05 to 26.11): change the release in two places in
`flake.nix`, `nixpkgs.url` and `home-manager.url`, then run the steps above. **Never change
`stateVersion` in `flake.nix`.** It records the release this setup first started with, and
changing it quietly changes defaults.

---

## Upgrading a machine that was set up before the cleanup

If a Mac already had this configuration before the old Claude tooling was removed, the
first `hms` after pulling fails for two reasons. Fix both, then run `hms` again:

1. **`overconfig.nix` mentions `flags.claude.enable`.** That setting no longer exists. Delete
   any `flags` line at the top of the file and delete or switch off any block that uses
   `flags.claude.enable` (for example `lib.mkIf false`).
2. **`~/.config/nix/nix.conf` is a hand-written file.** Home Manager now owns it. Copy it
   somewhere safe and move it aside:
   ```bash
   cp ~/.config/nix/nix.conf ~/.backup/nix.conf.before-home-manager
   mv ~/.config/nix/nix.conf ~/.config/nix/nix.conf.old
   NIX_CONFIG="experimental-features = nix-command flakes" hms
   ```
   (Flakes are off for that one run, hence the `NIX_CONFIG`.) Afterwards you can delete
   `nix.conf.old`.

---

## What's in it

- **Shell**: zsh with autosuggestions, syntax highlighting and fast, precompiled
  completions. Starship prompt, zoxide (`cd` that learns), fzf, direnv with nix-direnv.
  Closing a shell with Ctrl-D asks first.
- **Terminal**: Alacritty (Tokyo Night Storm) running tmux, with session resurrection
  (resurrect and continuum) and a bell that marks a tab when a command finishes in a
  window you are not looking at.
- **Editor**: Neovim, and Neovide as its window.
  - Language servers for TypeScript/JavaScript, Go, Python, Rust, C#, Nix, Bash, YAML,
    JSON, Lua, Helm, Starlark and GDScript; autocomplete; inline errors.
  - Formatting on save where it was always on (Go, TypeScript and JavaScript, C#, Rust,
    and the prettier-style filetypes in projects that use prettier); `<space>f` formats
    anything else on demand.
  - Git hunks in the gutter (gitsigns), treesitter highlighting, fzf, GitHub Copilot, and
    a plugin that sends code to a running Claude Code.
- **Git**: custom commands (below), LFS configured, difftastic aliases, a daily job that
  clears out old worktrees.
- **Claude Code**: settings, my global instructions (`~/.claude/CLAUDE.md`) and two
  skills, all deployed from `modules/claude-code/`.
- **Tools**: `gh`, `jq`, `yq`, `ripgrep`, `fd`, `bat`, `htop`, `just`, `mkcert`, `devbox`,
  `kubectl`/`kubectx`, 1Password CLI, `nix-index` and `comma` (run a program you don't
  have), and the toolchains for Go, Node 24, Python (`uv`), .NET 10, Haskell and Ruby.
- **Font**: SauceCodePro Nerd Font.
- **Housekeeping**: a weekly Nix garbage collection that deletes generations older than
  30 days.

---

## Commands

**Configuration**

| Command | Does |
|---|---|
| `hms` | Apply this configuration |
| `hme` `hmu` `hmo` `hm` | Edit `home.nix` / `user.nix` / `overconfig.nix`; go to the repo |

**Git**

| Command | Does |
|---|---|
| `commit "msg"` | Stage everything and commit (`commit noop` makes an empty commit) |
| `push` | Push the current branch |
| `pull` | Pull; if the branch has no upstream, fetches and tracks `origin/<branch>` first |
| `save "msg"` | Commit and push |
| `git sync` | Merge the main branch into the current branch |
| `git trunk` | Switch to the trunk branch and pull (`git trunk --print` just prints its name) |
| `git branches` | Pick a branch with fzf |
| `git resume` | Switch to your most recently committed `<username>/*` branch |
| `git tmp` | Start a fresh throwaway branch |
| `git kill` | Destroy all local work and reset to the remote (stashes first as a safety net; keeps `.envrc`; `--nuclear` also deletes ignored files) |
| `groot` | Go to the root of the repository |
| `workout` | Create, browse and clean up git worktrees under `~/worktrees` |

**Other**

| Command | Does |
|---|---|
| `tmux-restore` | Pick a saved tmux session snapshot to restore |
| `lan-run <cmd>` | Run a command so it can reach the local network from inside tmux (macOS blocks it otherwise) |
| `coffee` | Keep the Mac awake until you stop it |

---

## Where things live

```
home.nix              what gets loaded, plus the weekly cleanup and nix.conf
flake.nix             the pinned inputs (Nixpkgs, Home Manager) and the release
flake.lock            the exact pinned versions
flags.nix             on/off switches (Claude Code configuration)
user.nix              YOU: name, email, username          (personal, ignored by git)
overconfig.nix        THIS MACHINE: overrides, secrets    (personal, ignored by git)
modules/
  packages.nix        the tools installed, plus fzf, starship, zoxide settings
  zsh.nix             the shell
  tmux/  alacritty.nix  neovim/  direnv.nix  environment.nix  theme.nix
  git/                git config and the git commands
  system/             hms, lan-run, coffee (and HMS.md, the reference for hms)
  claude-code/        Claude Code settings, instructions and skills
  nix-profile.nix     switches the Nix profile without a moment of missing tools
  lib/shellApp.nix    the helper that turns a script into a command
```

To add a package: put it in `modules/packages.nix`, then `hms`. To add a command: write
the script next to the others in a module, register it in that module's `default.nix`,
`git add` it, then `hms`. `CLAUDE.md` has the working rules for this repository.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| `experimental Nix feature 'nix-command' is disabled` | Prefix the command with `NIX_CONFIG="experimental-features = nix-command flakes"`. Normal after a fresh install, before the first switch. |
| `flake ... does not provide attribute ...homeConfigurations.<name>` | `username` in `user.nix` does not match `id -un`. |
| `user.nix contains CHANGE_ME placeholder values` | Fill in `user.nix` (`hmu`). |
| `Existing file '...' would be clobbered` | Move that file aside (copy it to `~/.backup` first) and run `hms` again. On the very first switch, `-b backup` already does this. |
| A new file isn't picked up | `git add` it. Nix ignores files git doesn't know about. |
| `hms` builds but a command is missing in a window that was already open | Open a new window, or run `reload-env`. |
| SSH to a machine on the local network fails with "No route to host" inside tmux | macOS Local Network privacy. Prefix the command with `lan-run`. |
| All tmux sessions vanished | You ran `hms --purge`. Open a terminal (it starts tmux), then `tmux-restore`. |
| `which tmux` fails right after `hms` | Open a new terminal; the profile switch is complete. |
