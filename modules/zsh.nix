{ config, pkgs, lib, theme, ... }:

let
  homeDirectory = config.home.homeDirectory;
in {
  # ============================================================================
  # Zsh Configuration
  # ============================================================================
  # Everything related to Zsh: program configuration + activation hooks
  # ============================================================================

  programs.zsh = {
    enable = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    enableCompletion = false;  # We handle this ourselves for performance
    profileExtra = ''
      # Optimize zsh autosuggestions
      export ZSH_AUTOSUGGEST_USE_ASYNC=true
      export ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=20

      local_bin_path='${homeDirectory}/.local/bin'
      nix_path='/nix/var/nix/profiles/default/bin'
      nix_profile_path='${homeDirectory}/.nix-profile/bin'
      go_bin_path="$GOPATH/bin"
      npm_bin_path='${homeDirectory}/.npm-packages/bin'
      rd_bin_path='${homeDirectory}/.rd/bin'
      export PATH="$local_bin_path:$rd_bin_path:$go_bin_path:$npm_bin_path:$nix_profile_path:$nix_path:$PATH"
      export LANG="en_US.UTF-8"
      export LC_ALL="en_US.UTF-8"
      export LC_CTYPE="en_US.UTF-8"

      # Kanban CLI: Hide own session by default (show only other sessions)
      export KANBAN_HIDE_MINE=true

      # Initialize zoxide for all zsh contexts
      eval "$(${pkgs.zoxide}/bin/zoxide init --cmd cd zsh)"
    '';
    initContent = ''
      # Set up fpath to include completion directories
      fpath=(
        ${homeDirectory}/.nix-profile/share/zsh/site-functions
        ${homeDirectory}/.nix-profile/share/zsh/vendor-completions
        /nix/var/nix/profiles/default/share/zsh/site-functions
        /nix/var/nix/profiles/default/share/zsh/vendor-completions
        $fpath
      )

      # Fast compinit with precompiled dump
      autoload -Uz compinit
      if [[ -f ${homeDirectory}/.zcompdump.zwc ]]; then
        # Use precompiled dump without security checks
        compinit -C -d ${homeDirectory}/.zcompdump
      else
        # Fallback to fast compinit without security checks
        compinit -C
      fi

      # Load kubectl completions
      source <(kubectl completion zsh)

      # Tell completion system that k function uses kubectl completion
      compdef k=kubectl

      # Enhanced completion styling
      autoload -U colors && colors

      # Enable completion menu with selection
      zstyle ':completion:*' menu select

      # Use LS_COLORS for file completion
      eval "$(${pkgs.coreutils}/bin/dircolors -b)"
      zstyle ':completion:*' list-colors ''${(s.:.)LS_COLORS}

      # Highlight selected completion
      zstyle ':completion:*' menu select=2
      zmodload zsh/complist

      # Add file type suffixes
      zstyle ':completion:*' file-patterns \
        '%p:globbed-files' \
        '*(-/):directories' \
        '*:all-files'

      # Show descriptions for options
      zstyle ':completion:*' verbose yes
      zstyle ':completion:*:descriptions' format ' '
      zstyle ':completion:*:messages' format '%B%F{yellow}── %d ──%f%b'
      zstyle ':completion:*:warnings' format '%B%F{red}── no matches found ──%f%b'

      # Group completions by type
      zstyle ':completion:*' group-name '''
      zstyle ':completion:*:*:-command-:*' group-order builtins commands functions

      # Case insensitive completion
      zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}' 'r:|[._-]=* r:|=*' 'l:|=* r:|=*'

      # Better completion for cd
      zstyle ':completion:*:cd:*' tag-order local-directories directory-stack path-directories
      zstyle ':completion:*:cd:*' ignore-parents parent pwd

      # Process completion shows process IDs and names
      zstyle ':completion:*:*:kill:*:processes' list-colors '=(#b) #([0-9]#)*=0=01;31'
      zstyle ':completion:*:kill:*' command 'ps -u $USER -o pid,%cpu,tty,cputime,cmd'

      # Add indicators after filenames (/ for dirs, @ for symlinks, etc)
      setopt list_types

      # Enable menu navigation with arrow keys
      bindkey -M menuselect '^[[A' up-line-or-history
      bindkey -M menuselect '^[[B' down-line-or-history
      bindkey -M menuselect '^[[C' forward-char
      bindkey -M menuselect '^[[D' backward-char

      # Load add-zsh-hook for lazy loading
      autoload -Uz add-zsh-hook

      # Tmux attention alerting - ring bell when command completes in unfocused window
      # This makes the tmux tab turn red (via window_bell_flag) when you're not looking
      if [[ -n "$TMUX" ]]; then
        _tmux_attention_preexec() {
          _TMUX_COMMAND_STARTED=1
        }

        _tmux_attention_precmd() {
          if [[ -n "''${_TMUX_COMMAND_STARTED:-}" ]]; then
            unset _TMUX_COMMAND_STARTED
            # Ring bell if window is not active
            if [[ "$(tmux display-message -p '#{window_active}')" == "0" ]]; then
              printf '\a'
            fi
          fi
        }

        add-zsh-hook preexec _tmux_attention_preexec
        add-zsh-hook precmd _tmux_attention_precmd
      fi

      # Load static direnv hook if available
      if [[ -f ${homeDirectory}/.config/zsh/direnv-hook.zsh ]]; then
        source ${homeDirectory}/.config/zsh/direnv-hook.zsh
      else
        # Fallback to dynamic hook
        eval "$(${pkgs.direnv}/bin/direnv hook zsh)"
      fi

      # Key bindings (immediate - no lazy loading needed)
      bindkey -M viins 'jk' vi-cmd-mode

      function super_newline() {
        echo -e '\n\n\n\n\n'
        zle accept-line
      }
      zle -N super_newline
      bindkey '^J' super_newline
      bindkey -M viins '^A' beginning-of-line
      bindkey -M viins '^E' end-of-line

      autoload -U edit-command-line
      zle -N edit-command-line
      bindkey -M vicmd '^X^E' edit-command-line
      bindkey -M viins '^X^E' edit-command-line

      # Prevent Ctrl+D from immediately exiting (required for custom handler)
      setopt IGNOREEOF

      # Ctrl+D exit confirmation (default to no)
      function confirm_exit() {
        # Invalidate ZLE display to allow normal terminal I/O
        zle -I

        # Save terminal settings and enable echo
        local saved_tty=$(stty -F /dev/tty -g)
        stty -F /dev/tty echo

        # Prompt and read response (requires Enter key)
        print -n "\n👋 Exit shell? [y/N]: "
        local response
        read response </dev/tty

        # Restore terminal settings
        stty -F /dev/tty "$saved_tty"

        # Exit only on explicit yes
        if [[ $response == "y" || $response == "Y" ]]; then
          exit
        fi

        # Clear the confirmation prompt from screen
        # Move up 1 line (to prompt), clear it, move up 1 more (to blank line), clear it
        print -n "\033[1A\033[2K\033[1A\033[2K\r"

        # Redisplay the original command line
        zle redisplay
      }

      # Register as ZLE widget
      zle -N confirm_exit

      # Bind Ctrl+D to confirmation function
      bindkey '^D' confirm_exit

      # Worktree wrapper function that auto-evals cd command
      workout() {
        local result
        result="$(${homeDirectory}/.nix-profile/bin/workout "$@")"
        local exit_code=$?

        if [ $exit_code -eq 0 ]; then
          # Check if output starts with cd command
          if [[ "$result" == cd\ * ]]; then
            # Save current location before changing directories
            local worktree_root="''${WORKTREE_ROOT:-$HOME/worktrees}"
            mkdir -p "$worktree_root"
            echo "$PWD" > "$worktree_root/.workout_prev"

            # Execute all output (cd + optional hook path)
            eval "$result"
          else
            # Not a cd command, just print the output
            echo "$result"
          fi
        fi

        return $exit_code
      }

      # Groot wrapper function that auto-evals cd command to git root
      groot() {
        local result
        result="$(${homeDirectory}/.nix-profile/bin/groot "$@")"
        local exit_code=$?
        if [ $exit_code -eq 0 ]; then
          eval "$result"
        fi
        return $exit_code
      }

      # kubectl wrapper with syntax highlighting for explain command
      k() {
        if [[ "$1" == "explain" ]]; then
          kubectl "$@" | ${pkgs.bat}/bin/bat --language md --paging auto --style plain
        else
          kubectl "$@"
        fi
      }

      # Auto-create or reuse tmux sessions
      # - First window: attach to existing session if available, or create new one
      # - Subsequent windows (Cmd+N): always create NEW independent session
      # This ensures each Alacritty window has its own tmux session
      if [ -z "$TMUX" ]; then
        exec ${homeDirectory}/.nix-profile/bin/tmux new-session
      fi
    '';
    shellAliases = {
      desk = "cd ~/Desktop";
      down = "cd ~/Downloads";
      docs = "cd ~/Documents";
      pics = "cd ~/Pictures";
      hme = "vim ~/.config/nixpkgs/home.nix";
      hmu = "vim ~/.config/nixpkgs/user.nix";
      hmo = "vim ~/.config/nixpkgs/overconfig.nix";
      hm = "cd ~/.config/nixpkgs";
      ll = "${pkgs.eza}/bin/eza --oneline --icons --sort=type";
      tree = "${pkgs.eza}/bin/eza --oneline --icons --sort=type --tree";
      kn = "${pkgs.kubectx}/bin/kubens";
      kx = "${pkgs.kubectx}/bin/kubectx";
    };
  };

  # ============================================================================
  # Zsh Activation Hooks
  # ============================================================================

  home.activation.precompileZshCompletions = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    echo "Precompiling Zsh completions..."

    # Create a temporary file with the fpath setup
    $DRY_RUN_CMD cat > /tmp/zsh-compinit-setup <<'EOF'
    fpath=(
      ${homeDirectory}/.nix-profile/share/zsh/site-functions
      ${homeDirectory}/.nix-profile/share/zsh/vendor-completions
      /nix/var/nix/profiles/default/share/zsh/site-functions
      /nix/var/nix/profiles/default/share/zsh/vendor-completions
      $fpath
    )

    # Remove old dump files
    rm -f ${homeDirectory}/.zcompdump*

    # Generate new completion dump
    autoload -Uz compinit
    compinit -d ${homeDirectory}/.zcompdump

    # Compile the dump file for faster loading
    zcompile ${homeDirectory}/.zcompdump
    EOF

    # Run the setup
    $DRY_RUN_CMD ${pkgs.zsh}/bin/zsh /tmp/zsh-compinit-setup
    $DRY_RUN_CMD rm -f /tmp/zsh-compinit-setup

    echo "Zsh completions precompiled successfully"
  '';
}
