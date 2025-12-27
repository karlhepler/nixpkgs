{ config, pkgs, lib, theme, shellapps, ... }:

let
  homeDirectory = config.home.homeDirectory;
  # Powerline separator character (U+E0B0) as separate derivations to avoid Nix escaping issues
  separatorsConf = pkgs.writeText "separators.conf" ''
    set -g @theme_left_separator ""
    set -g @theme_right_separator ""
  '';
  bellFormatConf = pkgs.writeText "bell-format.conf" ''
    # Inactive window format with bell-aware conditional
    set -g window-status-format "#{?#{||:#{window_bell_flag},#{==:#{@claude_attention},1}},#[bg=#f7768e fg=#292e42]#{@theme_left_separator}#[none],#[bg=#737aa2 fg=#292e42]#{@theme_left_separator}#[none]}#[fg=#ffffff] #I #{?#{||:#{window_bell_flag},#{==:#{@claude_attention},1}},#[bg=#db4b5e fg=#f7768e]#{@theme_left_separator}#[none],#[bg=#545c7e fg=#737aa2]#{@theme_left_separator}#[none]}#[fg=#ffffff] #{?window_zoomed_flag,#{@theme_plugin_zoomed_window_icon} ,#{@theme_plugin_inactive_window_icon} }#W #[bg=#292e42]#{?#{||:#{window_bell_flag},#{==:#{@claude_attention},1}},#[fg=#db4b5e]#{@theme_left_separator}#[none],#[fg=#545c7e]#{@theme_left_separator}#[none]}"

    # Active window format with dynamic icon variable
    set -g window-status-current-format "#[bg=#bb9af7,fg=#292e42]#{@theme_left_separator}#[none]#[fg=#ffffff] #I #[bg=#9d7cd8,fg=#bb9af7]#{@theme_left_separator}#[none]#[fg=#ffffff] #{?window_zoomed_flag,#{@theme_plugin_zoomed_window_icon} ,#{@theme_plugin_active_window_icon} }#W #{?pane_synchronized,✵,}#[bg=#292e42,fg=#9d7cd8]#{@theme_left_separator}#[none]#[none]"

    # Clear attention flag when window becomes active
    set-hook -g after-select-window "set-window-option @claude_attention 0"
  '';
  sessionIconConf = pkgs.writeText "session-icon.conf" ''
    # Override status-left to use session-specific icon
    # Replace hardcoded ⋅ with #{@session_icon}, fallback to ⋅ if not set
    set -g status-left "#[fg=#3b4261,bold]#{?client_prefix,#[bg=#e0af68],#[bg=#9ece6a]} #{?@session_icon,#{@session_icon},⋅} #S #[bg=#292e42]#{?client_prefix,#[fg=#e0af68],#[fg=#9ece6a]}#{@theme_left_separator}#[none]"
  '';
in {
  # ============================================================================
  # Tmux Configuration & Shell Applications
  # ============================================================================
  # Terminal multiplexer with plugins, theme integration, and bell-based alerts
  # ============================================================================

  _module.args.tmuxShellapps = let
    # Read shared arrays once
    emojisContent = builtins.readFile ./emojis.bash;
    simpsonsContent = builtins.readFile ./simpsons-words.bash;
  in {
    random-emoji = pkgs.writeShellApplication {
      name = "random-emoji";
      runtimeInputs = [ pkgs.tmux ];
      text = ''
        ${emojisContent}
        ${builtins.readFile ./random-emoji.bash}
      '';
    };
    random-session-name = pkgs.writeShellApplication {
      name = "random-session-name";
      runtimeInputs = [ pkgs.tmux ];
      text = ''
        ${simpsonsContent}
        ${builtins.readFile ./random-session-name.bash}
      '';
    };
    random-session-icon = pkgs.writeShellApplication {
      name = "random-session-icon";
      runtimeInputs = [ pkgs.tmux ];
      text = ''
        ${emojisContent}
        ${builtins.readFile ./random-session-icon.bash}
      '';
    };
  };

  # Link config files to home directory (using writeText to avoid Nix escaping issues with powerline chars)
  home.file.".config/tmux/separators.conf".source = separatorsConf;
  home.file.".config/tmux/bell-format.conf".source = bellFormatConf;
  home.file.".config/tmux/session-icon.conf".source = sessionIconConf;

  programs.tmux = {
    enable = true;
    keyMode = "vi";
    customPaneNavigationAndResize = false;
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
          set -g @theme_plugin_datetime_format '%a %b %d %I:%M%p'
          set -g @theme_plugin_datetime_icon ' '

          # Source separator config (avoids Nix escaping issues)
          source-file ${homeDirectory}/.config/tmux/separators.conf

          # Bell-based attention alerting
          # When a bell rings in a non-active window, that window's tab turns red
          # The flag is automatically cleared when the window becomes active
          set -g monitor-bell on
          set -g bell-action other
          set -g visual-bell off
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
      {
        plugin = resurrect;
        extraConfig = ''
          # Restore pane contents
          set -g @resurrect-capture-pane-contents 'on'
          # Restore Neovim sessions
          set -g @resurrect-strategy-nvim 'session'
        '';
      }
      {
        plugin = continuum;
        extraConfig = ''
          # Disable automatic restore (use prefix+Ctrl-r to manually restore if needed)
          set -g @continuum-restore 'off'
          # Save interval in minutes (default: 15)
          set -g @continuum-save-interval '15'
        '';
      }
    ];
    extraConfig = ''
      # Pane navigation (hjkl)
      bind-key -N "Select pane to the left" h select-pane -L
      bind-key -N "Select pane below" j select-pane -D
      bind-key -N "Select pane above" k select-pane -U
      bind-key -N "Select pane to the right" l select-pane -R

      # Swap panes (vim-like behavior) - override default kill-pane
      unbind-key x
      bind-key -N "Swap pane with next" x swap-pane -D

      # Pane resizing (HJKL) - repeatable with -r flag
      # Note: L is intentionally omitted and remapped to session chooser below
      bind-key -r -N "Resize pane left by 5" H resize-pane -L 5
      bind-key -r -N "Resize pane down by 5" J resize-pane -D 5
      bind-key -r -N "Resize pane up by 5" K resize-pane -U 5

      # Performance optimizations
      set-option -sg escape-time 10
      set-option -g focus-events on
      set-option -g aggressive-resize on

      # Session switching on close
      # When a session is destroyed (Ctrl+D in all panes), switch to the most recently
      # active session instead of detaching and closing the terminal. This improves
      # workflow continuity when working across multiple sessions.
      set-option -g detach-on-destroy off

      # Random emoji for each new window
      set-hook -ga after-new-window "run-shell '${shellapps.random-emoji}/bin/random-emoji'"

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

      # Remap last-window from 'b' to '-' (override delete-buffer)
      unbind-key b
      unbind-key -
      bind-key - last-window

      # Create new session on prefix+S (will get random Simpsons name)
      bind-key S new-session

      # customize status bar ---------------------------------------------------
      set-option -g status-position top

      # set shell (both shell and command must be set) -------------------------
      set-option -g default-command ${homeDirectory}/.nix-profile/bin/zsh

      # fix colors -------------------------------------------------------------
      set -g terminal-overrides ",*256col*:Tc"

      # ========================================================================
      # Override window-status-format with bell-aware conditional
      # Source multiple times to ensure it runs after async plugin completes
      # ========================================================================
      source-file ${homeDirectory}/.config/tmux/bell-format.conf
      run-shell -b "tmux source-file ${homeDirectory}/.config/tmux/bell-format.conf"
      set-hook -g after-new-session "source-file ${homeDirectory}/.config/tmux/bell-format.conf"
      set-hook -ga after-new-session "run-shell '${shellapps.random-emoji}/bin/random-emoji'"
      set-hook -ga after-new-session "run-shell '${shellapps.random-session-name}/bin/random-session-name'"
      set-hook -ga after-new-session "run-shell '${shellapps.random-session-icon}/bin/random-session-icon'"

      # ========================================================================
      # Override status-left with session-specific icon
      # Source multiple times to ensure it runs after async plugin completes
      # ========================================================================
      source-file ${homeDirectory}/.config/tmux/session-icon.conf
      run-shell -b "tmux source-file ${homeDirectory}/.config/tmux/session-icon.conf"

      # ========================================================================
      # Session chooser on prefix+L
      # We intentionally don't use L for resize-pane-right like the other resize bindings
      # ========================================================================
      bind-key -N "Choose session" L choose-tree -s
    '';
  };
}
