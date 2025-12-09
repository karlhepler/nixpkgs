{ config, pkgs, lib, ... }:

{
  # ============================================================================
  # Machine-Specific Configuration
  # ============================================================================
  # This file is for machine-specific overrides and settings.
  # After `hms` runs, this file becomes git-ignored via the activation hook below.
  #
  # Common uses:
  # - Machine-specific packages: home.packages = with pkgs; [ ... ];
  # - Override git email: programs.git.settings.user.email = lib.mkForce "work@email.com";
  # - Machine-specific shell aliases: programs.zsh.shellAliases = { ... };
  # - Environment variables: home.sessionVariables = { API_KEY = "..."; };
  # - Program enables: programs.gh.enable = true;
  # ============================================================================

  # Add your machine-specific configuration below:
  # (This template will be ignored by git after first `hms` run via home.nix activation hook)
}
