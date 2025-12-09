{ config ? null, pkgs ? null, lib, ... }:

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
  # - name: Your full name (for git user.name)
  # - email: Your personal email (for git user.email)
  # - username: Your system username (for flake homeConfigurations, GitHub)
  # - homeDirectory: Your home directory path (derived from username)
  #
  # NOTE: Work email can still be overridden in overconfig.nix using:
  #   programs.git.settings.user.email = lib.mkForce "work@email.com";
  # ============================================================================

  user = {
    name = "CHANGE_ME";           # Example: "Chuck Norris"
    email = "CHANGE_ME";          # Example: "chuck.norris@example.org"
    username = "CHANGE_ME";       # Example: "chucknorris"
    homeDirectory = "/Users/CHANGE_ME";  # Example: "/Users/chucknorris"
  };

  # Validation helpers
  isPlaceholder = value: value == "CHANGE_ME" || value == "";
  hasPlaceholders =
    (isPlaceholder user.name) ||
    (isPlaceholder user.email) ||
    (isPlaceholder user.username) ||
    (lib.hasInfix "CHANGE_ME" user.homeDirectory);

in {
  # Export user for direct import (used by flake.nix)
  inherit user;

  # Activation hook to make git ignore changes to this file (only when used as module)
  home.activation.gitIgnoreUserChanges = lib.mkIf (config != null && pkgs != null) (
    lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --assume-unchanged user.nix
    ''
  );

  # Fail fast if placeholders not replaced (only when used as module)
  assertions = lib.mkIf (config != null) [
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

  # Export via _module.args for modules to access
  _module.args.user = user;
}
