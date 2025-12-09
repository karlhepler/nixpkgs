args:

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

  lib = args.lib or (import <nixpkgs> {}).lib;

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

in
# When imported as a module (has config and pkgs), return module configuration
if args ? config && args ? pkgs then {
  # Activation hook to make git ignore changes to this file
  home.activation.gitIgnoreUserChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${args.pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --assume-unchanged user.nix
  '';

  # Fail fast if placeholders not replaced
  assertions = [
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

  # Export user data via _module.args for modules to access
  _module.args.user = user;
}
# When imported directly (no config/pkgs), return just the data
else {
  user = user;
}
