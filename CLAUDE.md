{ lib ? (import <nixpkgs> {}).lib, ... }:

# ============================================================================
# User Configuration
# ============================================================================
# This file defines user-specific information used throughout the Nix config.
# After first `hms` run, this file becomes git-ignored (via home.nix activation hook).
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

{
  user = {
    name = "CHANGE_ME";           # Example: "Chuck Norris"
    email = "CHANGE_ME";          # Example: "chuck.norris@example.org"
    username = "CHANGE_ME";       # Example: "chucknorris"
    homeDirectory = "/Users/CHANGE_ME";  # Example: "/Users/chucknorris"
  };
}
