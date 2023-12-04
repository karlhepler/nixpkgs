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


## Helpful Commands

- `hms`: Update Home Manager with latest changes.
- `hme`: Edit `home.nix` file.
- `hm`: Change directory to Nix Packages configuration directory.
