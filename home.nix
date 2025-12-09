{ config, pkgs, lib, unstable, ... }:

let
  # Import cross-cutting concerns
  user = (import ./user.nix {}).user;
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

  # Activation hooks to make git ignore changes to user.nix and overconfig.nix
  home.activation.gitIgnoreUserChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --assume-unchanged user.nix
  '';

  home.activation.gitIgnoreOverconfigChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --assume-unchanged overconfig.nix
  '';

  # Validate user.nix doesn't have placeholders
  assertions = let
    isPlaceholder = value: value == "CHANGE_ME" || value == "";
    hasPlaceholders =
      (isPlaceholder user.name) ||
      (isPlaceholder user.email) ||
      (isPlaceholder user.username) ||
      (lib.hasInfix "CHANGE_ME" user.homeDirectory);
  in [
    {
      assertion = !hasPlaceholders;
      message = ''
        user.nix contains placeholder values. Please edit user.nix and set:
        - name (for git user.name)
        - email (for git user.email)
        - username (for system username)
        - homeDirectory (derived from username)

        Run: hmu
      '';
    }
  ];

  fonts.fontconfig.enable = true;


  # Automatically run the garbage collector weekly.
  nix.gc.automatic = true;

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  # Program Modules
  # https://nix-community.github.io/home-manager/options.html

}
