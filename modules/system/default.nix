{ config, pkgs, lib, ... }:

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
      text = builtins.readFile ./hms.bash;
    };
  };
}
