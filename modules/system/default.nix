{ config, pkgs, lib, user, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };
  flags = import ../../flags.nix;

in
{
  # ============================================================================
  # System Tools
  # ============================================================================
  # System-level tools and utilities for managing the Nix environment
  # ============================================================================

  _module.args.systemShellapps = rec {
    hms = shellApp {
      name = "hms";
      runtimeInputs = [ pkgs.git pkgs.home-manager ];
      text = ''
        # User configuration from user.nix (passed as env vars)
        export USER_NAME="${user.name}"
        export USER_EMAIL="${user.email}"
        export CLAUDE_ENABLED="${if flags.claude.enable then "1" else "0"}"

        ${builtins.readFile ./hms.bash}
      '';
      description = "Apply Home Manager configuration with git handling and backups";
      sourceFile = "hms.bash";
    };

    coffee = shellApp {
      name = "coffee";
      runtimeInputs = [ ];
      text = ''
        exec caffeinate -dimsu "$@"
      '';
      description = "Keep this Mac and its display awake until interrupted (caffeinate -dimsu)";
      sourceFile = "default.nix";
    };
  };
}
