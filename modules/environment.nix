{ config, ... }:
let
  homeDirectory = config.home.homeDirectory;
in {
  # Set here (not in Alacritty's env) so every zsh gets them — .zshenv sources
  # hm-session-vars.sh — including Neovide, ssh sessions and anything else that
  # does not start from Alacritty.
  home.sessionVariables = {
    GITHUB_REPOS_ROOT = "${homeDirectory}/github.com";
    EDITOR = "${homeDirectory}/.nix-profile/bin/nvim";
    VISUAL = "${homeDirectory}/.nix-profile/bin/nvim";
    PAGER = "less -RF";
    GOPATH = "${homeDirectory}/go";
    LANG = "en_US.UTF-8";
    LC_ALL = "en_US.UTF-8";
  };
}
