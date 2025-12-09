# Nix Home Manager Configuration

This configuration lives in `/Users/karlhepler/.config/nixpkgs`.

## Installation

```
# Install Nix (https://nixos.org/download#nix-install-macos)
$ sh <(curl -L https://nixos.org/nix/install)

# Set up flakes
$ mkdir -p ~/.config/nix
$ echo 'experimental-features = nix-command flakes' > ~/.config/nix/nix.conf

# Clone this repository
$ cd ~/.config
$ git clone git@github.com:karlhepler/nixpkgs.git
$ cd nixpkgs

# Install
$ nix run nixpkgs#home-manager -- switch --flake .#karlhepler
```

Once that is done, applications will be available in `~/Applications/Nix Apps/` and searchable via Spotlight.

## Additional Customization

Per-machine customizations can be made using `overconfig.nix`. Valid
customization keys are listed in this file and commented out. To enable
customization, uncomment the applicable lines in this file and update their
values as desired.

Each time home manager sync successfully completes, a git command will run
telling git to ignore changes to this file. In order to make permanent changes
to this file, like adding new customizable configs, first run

```
git -C ~/.config/nixpkgs update-index --no-assume-unchanged overconfig.nix
```

**NOTE:** Because of this customization, this repository **MUST** be installed
at `~/.config/nixpkgs`. Installing it anywhere else will likely cause an error.

**ANOTHER NOTE**: In order for this to work, `--no-assume-unchanged` **MUST**
be run prior to syncing home manager. To make this automatic, it runs first as
a part of running `hms`. So, as long as you always sync home manager using
`hms`, this will work properly.

## Local Git Configuration

**IMPORTANT**: If you use `overconfig.nix` to override global git settings (such as using a work email address), you must configure this repository locally to use your personal credentials.

The default git configuration in this repository uses:
- Email: `karl.hepler@gmail.com` (personal)

After cloning on a machine where `overconfig.nix` overrides the git email to a work email, run:

```bash
cd ~/.config/nixpkgs
git config --local user.email "karl.hepler@gmail.com"
```

Verify the local configuration:

```bash
git config --local --get user.email
# Should output: karl.hepler@gmail.com
```

This ensures all commits to this personal repository use personal credentials, regardless of global git configuration overrides.

## Helpful Commands

- `hms`: Update Home Manager with latest changes.
- `hme`: Edit `home.nix` file.
- `hmo`: Edit `overconfig.nix` file.
- `hm`: Change directory to Nix Packages configuration directory.
