{ config, pkgs, lib, theme, ... }:

let
  homeDirectory = config.home.homeDirectory;
in {
  # ============================================================================
  # Tmux Configuration
  # ============================================================================
  # Terminal multiplexer with plugins and theme integration
  # ============================================================================

  programs.tmux = {
    enable = true;
    keyMode = "vi";
    customPaneNavigationAndResize = true;
    mouse = true;
    shell = "${homeDirectory}/.nix-profile/bin/zsh";
    shortcut = "g";
    terminal = "tmux-256color";
    historyLimit = 50000;
    sensibleOnTop = true;
    plugins = with pkgs.tmuxPlugins; [
      {
        plugin = mkTmuxPlugin {
          pluginName = "tmux-tokyo-night";
          rtpFilePath = "tmux-tokyo-night.tmux";
          version = "1.10.0";
          src = pkgs.fetchFromGitHub {
            owner = "fabioluciano";
            repo = "tmux-tokyo-night";
            rev = "5ce373040f893c3a0d1cb93dc1e8b2a25c94d3da";
            hash = "sha256-9nDgiJptXIP+Hn9UY+QFMgoghw4HfTJ5TZq0f9KVOFg=";
          };
        };
        extraConfig = ''
          set -g @theme_variation '${theme.variant}'
          set -g @theme_plugins 'datetime'
          set -g @theme_plugin_datetime_format ' %a %b%e %l:%M%p'
          set -g @theme_plugin_datetime_icon '  '
          set -g @theme_left_separator '''
          set -g @theme_right_separator '''
        '';
      }
      {
        plugin = better-mouse-mode;
        extraConfig = ''
          set -g @scroll-speed-num-lines-per-scroll 1
          set -g @scroll-without-changing-pane on
          set -g @scroll-down-exit-copy-mode on
          set -g @prevent-scroll-for-fullscreen-alternate-buffer on
        '';
      }
    ];
    extraConfig = ''
      # Performance optimizations
      set-option -sg escape-time 10
      set-option -g focus-events on
      set-option -g aggressive-resize on

      # Smooth scrolling optimizations
      set -ga terminal-overrides ',*256color*:smcup@:rmcup@'
      set -ga terminal-overrides ',alacritty:Tc'
      set -g status-interval 1
      set -g renumber-windows on

      # vim mode with <shortcut>[
      set-window-option -g mode-keys vi
      bind-key -T copy-mode-vi 'v' send -X begin-selection
      bind-key -T copy-mode-vi 'y' send -X copy-selection-and-cancel

      # Custom mouse bindings to prevent jumping to bottom after selection
      bind-key -T copy-mode-vi MouseDragEnd1Pane send -X copy-selection
      bind-key -T copy-mode-vi Escape send -X cancel
      bind-key N new-window -c "#{pane_current_path}"
      bind-key v split -h -c "#{pane_current_path}"
      bind-key s split -v -c "#{pane_current_path}"

      # customize status bar ---------------------------------------------------
      set-option -g status-position top

      # set shell (both shell and command must be set) -------------------------
      set-option -g default-command ${homeDirectory}/.nix-profile/bin/zsh

      # fix colors -------------------------------------------------------------
      set -g terminal-overrides ",*256col*:Tc"
    '';
  };
}
