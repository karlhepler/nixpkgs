{ config, lib, ... }:
let
  homeDirectory = config.home.homeDirectory;
  flags = import ../flags.nix;
in {
  home.sessionVariables = {
    GITHUB_REPOS_ROOT = "${homeDirectory}/github.com";
  } // lib.optionalAttrs flags.claude.enable {
    KANBAN_HIDE_MINE = "true";
  };
}
