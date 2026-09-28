{ config, pkgs, lib, theme, ... }:

let
  homeDirectory = config.home.homeDirectory;

  # Alacritty 0.17.0 ships without NSLocalNetworkUsageDescription, which macOS 26.7+
  # requires before an app can reach LAN devices (alacritty#9055). Without it, LAN
  # access can silently fail even with the Local Network toggle on. Wrap the package
  # to add just that one Info.plist key — everything else (including the executable
  # and its code signature) is symlinked through unchanged. Remove this wrapper once
  # upstream ships the fix (alacritty#9056).
  alacritty = pkgs.symlinkJoin {
    name = "alacritty-${pkgs.alacritty.version}";
    inherit (pkgs.alacritty) version meta;
    paths = [ pkgs.alacritty ];
    postBuild = ''
      plist=$out/Applications/Alacritty.app/Contents/Info.plist
      rm "$plist"
      sed 's#^</dict>$#  <key>NSLocalNetworkUsageDescription</key>\n  <string>An application in Alacritty would like to access the local network.</string>\n</dict>#' \
        ${pkgs.alacritty}/Applications/Alacritty.app/Contents/Info.plist > "$plist"
    '';
  };
in {
  # ============================================================================
  # Alacritty Configuration
  # ============================================================================
  # Terminal emulator with theme integration
  # ============================================================================

  programs.alacritty = {
    enable = true;
    package = alacritty;
    settings = {
      mouse.hide_when_typing = true;
      keyboard.bindings = [
        { key = "Enter"; mods = "Command"; action = "ToggleSimpleFullscreen"; }
        { key = "Return"; mods = "Control"; chars = "\\u001b[13;5u"; }
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
      # Enable bell - required for tmux bell detection
      bell = {
        animation = "EaseOutExpo";
        duration = 0;
        color = "#ffffff";
      };
    };
  };
}
