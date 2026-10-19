{ config, pkgs, lib, theme, user, ... }:

let
  homeDirectory = config.home.homeDirectory;

  # Alacritty 0.17.0 ships without NSLocalNetworkUsageDescription, which macOS 26.7+
  # requires before an app can reach LAN devices (alacritty#9055). Without it, LAN
  # access can silently fail even with the Local Network toggle on. Remove this key
  # once upstream ships the fix (alacritty#9056).
  #
  # Separately, macOS's Local Network policy database (/Library/Preferences/
  # com.apple.networkextension.plist) got into a corrupted state for the
  # "org.alacritty" identity — confirmed via `log stream`: every connection
  # attempt failed with "Local network prohibited" while the resolver logged
  # BOTH "alacritty" (by PID, a stale record from a long-gone nix store path)
  # and "org.alacritty" (by UUID) for the same process. macOS provides no
  # supported way to reset a single app's Local Network policy record (tccutil
  # doesn't cover this category; only a full Recovery-mode wipe of the whole
  # file resets it, which resets every app, not just this one).
  # Rather than fight that corrupted record, give Alacritty a private bundle
  # identifier macOS has never seen, so it gets a clean permission history with
  # no other app affected. (Cosmetic tradeoff: Spotlight/Launch Services will
  # show a second, separate Alacritty entry alongside the old org.alacritty
  # one — harmless clutter, not a bug.)
  #
  # Everything else, including the executable and its code signature, is
  # symlinked through unchanged.
  alacritty = pkgs.symlinkJoin {
    name = "alacritty-${pkgs.alacritty.version}";
    inherit (pkgs.alacritty) version meta;
    paths = [ pkgs.alacritty ];
    postBuild = ''
      plist=$out/Applications/Alacritty.app/Contents/Info.plist
      rm "$plist"
      sed \
        -e 's#^</dict>$#  <key>NSLocalNetworkUsageDescription</key>\n  <string>An application in Alacritty would like to access the local network.</string>\n</dict>#' \
        -e 's#<string>org.alacritty</string>#<string>com.${user.username}.alacritty</string>#' \
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
        SHELL = "${homeDirectory}/.nix-profile/bin/zsh";
        TERM = "xterm-256color";
      };
      # Every window starts tmux directly. -l makes it a login shell, so .zprofile
      # builds PATH as usual; panes then run the interactive zsh from tmux's
      # default-command. Shells opened any other way (Terminal.app, ssh) stay plain.
      terminal.shell = {
        program = "${homeDirectory}/.nix-profile/bin/zsh";
        args = [ "-l" "-c" "exec ${homeDirectory}/.nix-profile/bin/tmux new-session" ];
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
      # Alacritty's own visual bell stays off (duration = 0); tmux still sees the bell
      # character and flags the window (window_bell_flag), which is what the status
      # bar uses.
      bell.duration = 0;
    };
  };
}
