{ config, pkgs, lib, theme, ... }:

let
  homeDirectory = config.home.homeDirectory;
in {
  # ============================================================================
  # Alacritty Configuration
  # ============================================================================
  # Terminal emulator with theme integration
  # ============================================================================

  programs.alacritty = {
    enable = true;
    settings = {
      mouse.hide_when_typing = true;
      keyboard.bindings = [
        { key = "Enter"; mods = "Command"; action = "ToggleSimpleFullscreen";  }
      ];
      scrolling = {
        history = 10000;
        multiplier = 1;
      };
      env = {
        EDITOR = "${homeDirectory}/.nix-profile/bin/nvim";
        VISUAL = "${homeDirectory}/.nix-profile/bin/nvim";
        SHELL = "${homeDirectory}/.nix-profile/bin/zsh";
        GOPATH = "${homeDirectory}/go";
        LANG = "en_US.UTF-8";
        LC_ALL = "en_US.UTF-8";
        LC_CTYPE = "en_US.UTF-8";
        TERM = "xterm-256color";
        PAGER = "less -RF";
      };
      font = {
        normal = {
          family = theme.font.family;
          style = "Regular";
        };
        bold = {
          family = theme.font.family;
          style = "Bold";
        };
        italic = {
          family = theme.font.family;
          style = "Italic";
        };
        bold_italic = {
          family = theme.font.family;
          style = "Bold Italic";
        };
        size = theme.font.size;
      };
      # Tokyo Night Storm theme from centralized theme.nix
      colors = theme.colors;
    };
  };
}
