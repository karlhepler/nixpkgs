{ ... }:

{
  # ============================================================================
  # Direnv Configuration
  # ============================================================================
  # programs.direnv's zsh integration is the only direnv hook; do not add another.
  # ============================================================================

  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };
}
