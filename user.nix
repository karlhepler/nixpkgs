{ config, pkgs, lib, ... }:

let
  # ============================================================================
  # User Configuration
  # ============================================================================
  # This file defines user-specific information used throughout the Nix config.
  # After first `hms` run, this file becomes git-ignored (like overconfig.nix).
  #
  # CRITICAL: Replace all "CHANGE_ME" values below with your information.
  #
  # Field Usage:
  # - userName: Your full name (for git user.name)
  # - userEmail: Your personal email (for git user.email)
  # - username: Your system username (for flake homeConfigurations, GitHub)
  # - homeDirectory: Your home directory path (derived from username)
  #
  # NOTE: Work email can still be overridden in overconfig.nix using:
  #   programs.git.settings.user.email = lib.mkForce "work@email.com";
  # ============================================================================

  user = {
    userName = "CHANGE_ME";       # Example: "Karl Hepler"
    userEmail = "CHANGE_ME";      # Example: "karl.hepler@gmail.com"
    username = "CHANGE_ME";       # Example: "karlhepler"
    homeDirectory = "/Users/CHANGE_ME";  # Example: "/Users/karlhepler"
  };

  # Validation helpers
  isPlaceholder = value: value == "CHANGE_ME" || value == "";
  hasPlaceholders =
    (isPlaceholder user.userName) ||
    (isPlaceholder user.userEmail) ||
    (isPlaceholder user.username) ||
    (lib.hasInfix "CHANGE_ME" user.homeDirectory);

in {
  # Activation hook to make git ignore changes to this file
  home.activation.gitIgnoreUserChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --assume-unchanged user.nix
  '';

  # Fail fast if placeholders not replaced
  assertions = [
    {
      assertion = !hasPlaceholders;
      message = ''
        user.nix contains placeholder values. Please edit user.nix and set:
        - userName (for git user.name)
        - userEmail (for git user.email)
        - username (for system username)
        - homeDirectory (derived from username)

        Run: hmu
      '';
    }
  ];

  _module.args.user = user;
}
