{ config, pkgs, lib, unstable, ... }:

let
  homeDirectory = config.home.homeDirectory;

  # Import cross-cutting concerns
  user = (import ./user.nix { inherit lib; }).user;
  theme = (import ./modules/theme.nix { inherit lib; }).theme;

in {
  # Import all modules
  imports = [
    # Complex modules (with scripts)
    ./modules/system      # System tools (hms shellapp)
    ./modules/git         # Git config + 11 git shellapps
    ./modules/claude      # Claude hooks + 3 claude shellapps
    ./modules/neovim      # Neovim editor + 30+ plugins

    # Simple modules (no scripts)
    ./modules/packages.nix   # Packages + simple programs
    ./modules/zsh.nix        # Zsh configuration + activation
    ./modules/direnv.nix     # Direnv configuration + activation
    ./modules/alacritty.nix  # Alacritty terminal emulator
    ./modules/tmux.nix       # Tmux terminal multiplexer
  ];

  # Aggregate shellapps from modules and pass to all modules
  _module.args = let
    # Dynamically merge all shellapps from modules
    shellapps =
      (config._module.args.systemShellapps or {})
      // (config._module.args.gitShellapps or {})
      // (config._module.args.claudeShellapps or {})
      // (config._module.args.neovimShellapps or {});
  in { inherit user theme shellapps; };


  fonts.fontconfig.enable = true;


  # Automatically run the garbage collector weekly.
  nix.gc.automatic = true;

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  # Program Modules
  # https://nix-community.github.io/home-manager/options.html

}
