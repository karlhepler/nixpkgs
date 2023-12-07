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

Once that is done, run `~/Applications/Home Manager Apps/kitty.app` from Finder.

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


## Helpful Commands

- `hms`: Update Home Manager with latest changes.
- `hme`: Edit `home.nix` file.
- `hm`: Change directory to Nix Packages configuration directory.
