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

  # Activation hook to make git ignore changes to this file
  home.activation.gitIgnoreOverconfigChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --assume-unchanged overconfig.nix
  '';

  # Add your machine-specific configuration below:
  # (This template will be ignored by git after first `hms` run)
}
