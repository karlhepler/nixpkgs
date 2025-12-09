{ config, pkgs, lib, user, ... }:

{
  # ============================================================================
  # System Tools
  # ============================================================================
  # System-level tools and utilities for managing the Nix environment
  # ============================================================================

  _module.args.systemShellapps = rec {
    hms = pkgs.writeShellApplication {
      name = "hms";
      runtimeInputs = [ pkgs.git pkgs.home-manager ];
      text = ''
        # User configuration from user.nix (passed as env vars)
        export USER_NAME="${user.name}"
        export USER_EMAIL="${user.email}"

        ${builtins.readFile ./hms.bash}
      '';
    };
  };
}
