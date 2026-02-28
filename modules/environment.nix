{ config, ... }:
let
  homeDirectory = config.home.homeDirectory;
in {
  home.sessionVariables = {
    GITHUB_REPOS_ROOT = "${homeDirectory}/github.com";
  };
}
