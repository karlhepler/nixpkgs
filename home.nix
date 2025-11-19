{ config, pkgs, lib, unstable, ... }:

let
  homeDirectory = config.home.homeDirectory;

  shellapps = rec {
    hms = pkgs.writeShellApplication {
      name = "hms";
      runtimeInputs = [ pkgs.git pkgs.home-manager ];
      text = builtins.readFile ./scripts/hms.bash;
    };
    commit = pkgs.writeShellApplication {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./scripts/commit.bash;
    };
    pull = pkgs.writeShellApplication {
      name = "pull";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./scripts/pull.bash;
    };
    push = pkgs.writeShellApplication {
      name = "push";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./scripts/push.bash;
    };
    save = pkgs.writeShellApplication {
      name = "save";
      runtimeInputs = [ commit push ];
      text = builtins.readFile ./scripts/save.bash;
    };
    git-branches = pkgs.writeShellApplication {
      name = "git-branches";
      runtimeInputs = [ pkgs.git pkgs.fzf ];
      text = builtins.readFile ./scripts/git-branches.bash;
    };
    git-kill = pkgs.writeShellApplication {
      name = "git-kill";
      runtimeInputs = [
        pkgs.git
        pkgs.git-lfs
        pkgs.coreutils
        pkgs.gnugrep
      ];
      text = builtins.readFile ./scripts/git-kill.bash;
    };
    git-trunk = pkgs.writeShellApplication {
      name = "git-trunk";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = builtins.readFile ./scripts/git-trunk.bash;
    };
    git-sync = pkgs.writeShellApplication {
      name = "git-sync";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = builtins.readFile ./scripts/git-sync.bash;
    };
    git-resume = pkgs.writeShellApplication {
      name = "git-resume";
      runtimeInputs = [ pkgs.git git-branches pkgs.coreutils ];
      text = builtins.readFile ./scripts/git-resume.bash;
    };
    git-tmp = pkgs.writeShellApplication {
      name = "git-tmp";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./scripts/git-tmp.bash;
    };
    workout = pkgs.writeShellApplication {
      name = "workout";
      runtimeInputs = [ pkgs.git pkgs.coreutils pkgs.gnused ];
      text = builtins.readFile ./scripts/workout.bash;
    };
    claude-notification-hook = pkgs.writeShellApplication {
      name = "claude-notification-hook";
      runtimeInputs = [ pkgs.terminal-notifier pkgs.python3 ];
      text = builtins.readFile ./scripts/claude-notification-hook.bash;
    };
    claude-complete-hook = pkgs.writeShellApplication {
      name = "claude-complete-hook";
      runtimeInputs = [ pkgs.terminal-notifier ];
      text = builtins.readFile ./scripts/claude-complete-hook.bash;
    };
    claude-csharp-format-hook = pkgs.writeShellApplication {
      name = "claude-csharp-format-hook";
      runtimeInputs = [ pkgs.csharpier pkgs.python3 ];
      text = builtins.readFile ./scripts/claude-csharp-format-hook.bash;
    };
  };

in {
  # Home Packages
  # https://search.nixos.org/packages
  home.packages = with pkgs; [
    bash
    bat
    cabal-install # Cabal installation tool for managing Haskell software
    comma
    csharpier # Opinionated code formatter for C#
    darwin.trash
    devbox
    difftastic
    dotnet-sdk_9
    fd
    ghc # Glasgow Haskell Compiler
    git-lfs
    github-copilot-cli
    gnused
    go
    go-tools
    gopls
    haskell-language-server # Haskell language server
    helm-ls
    htop
    just
    kubectl
    kubectx
    mkcert
    nerd-fonts.sauce-code-pro
    nil
    nodePackages.bash-language-server
    nodePackages.typescript
    nodePackages.typescript-language-server
    nodejs
    omnisharp-roslyn
    pyright
    python3
    python3Packages.pip
    ripgrep
    ruby
    shellcheck
    stack  # A cross-platform program for developing Haskell projects
    starpls # Language server for Starlark
    terminal-notifier # macOS notification tool
    tilt
    uv
    yaml-language-server
    yarn
    yq
  ] ++ (builtins.attrValues shellapps);

  fonts.fontconfig.enable = true;

  # Alias all Home Manager symlinks so that Spotlight and Alfred can find them.
  home.activation = {
    copyApplications = let
      apps = pkgs.buildEnv {
        name = "home-manager-applications";
        paths = config.home.packages;
        pathsToLink = "/Applications";
      };
    in lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      aliasdir="$HOME/Applications/Home Manager Aliases"

      $DRY_RUN_CMD rm -rf "$aliasdir"
      $DRY_RUN_CMD mkdir -p "$aliasdir"

      for appfile in ${apps}/Applications/*; do
        echo "appfile: $appfile"
        $DRY_RUN_CMD /usr/bin/osascript \
          -e "tell app \"Finder\"" \
          -e "make new alias file at POSIX file \"$aliasdir\" to POSIX file \"$appfile\"" \
          -e "set name of result to \"$(basename "$appfile")\"" \
          -e "end tell"
      done
    '';

    gitIgnoreOverconfigChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --assume-unchanged overconfig.nix
    '';

    claudeSettings = let
      settingsContent = {
        hooks = {
          Notification = [{
            hooks = [{
              type = "command";
              command = "${shellapps.claude-notification-hook}/bin/claude-notification-hook";
            }];
          }];
          Stop = [{
            hooks = [{
              type = "command";
              command = "${shellapps.claude-complete-hook}/bin/claude-complete-hook";
            }];
          }];
          PostToolUse = [{
            matcher = "Edit|MultiEdit|Write";
            hooks = [{
              type = "command";
              command = "${shellapps.claude-csharp-format-hook}/bin/claude-csharp-format-hook";
            }];
          }];
        };
      };
      claudeSettingsJson = pkgs.runCommand "claude-settings.json" {} ''
        echo '${builtins.toJSON settingsContent}' | ${pkgs.jq}/bin/jq . > $out
      '';
    in lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD mkdir -p ~/.claude
      $DRY_RUN_CMD ln -sf ${claudeSettingsJson} ~/.claude/settings.json
    '';

    claudeGlobal = let
      claudeGlobalDir = ./claude-global;
    in lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD mkdir -p ~/.claude
      $DRY_RUN_CMD cp -rf ${claudeGlobalDir}/* ~/.claude/
    '';

    precompileZshCompletions = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
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

    generateDirenvHook = let
      direnvHookFile = pkgs.writeText "direnv-hook.zsh" ''
        # Static direnv hook - pregenerated by Nix
        _direnv_hook() {
          trap -- "" SIGINT
          eval "$("${pkgs.direnv}/bin/direnv" export zsh)"
          trap - SIGINT
        }
        typeset -ag precmd_functions
        if (( ! ''${precmd_functions[(I)_direnv_hook]} )); then
          precmd_functions=(_direnv_hook $precmd_functions)
        fi
        typeset -ag chpwd_functions
        if (( ! ''${chpwd_functions[(I)_direnv_hook]} )); then
          chpwd_functions=(_direnv_hook $chpwd_functions)
        fi
      '';
    in lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD mkdir -p ${homeDirectory}/.config/zsh
      $DRY_RUN_CMD ln -sf ${direnvHookFile} ${homeDirectory}/.config/zsh/direnv-hook.zsh
    '';
  };

  # Automatically run the garbage collector weekly.
  nix.gc.automatic = true;

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  # Program Modules
  # https://nix-community.github.io/home-manager/options.html

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
          family = "SauceCodePro Nerd Font Mono";
          style = "Regular";
        };
        bold = {
          family = "SauceCodePro Nerd Font Mono";
          style = "Bold";
        };
        italic = {
          family = "SauceCodePro Nerd Font Mono";
          style = "Italic";
        };
        bold_italic = {
          family = "SauceCodePro Nerd Font Mono";
          style = "Bold Italic";
        };
        size = 20;
      };
      # Tokyo Night Storm
      # Reference: https://github.com/zatchheems/tokyo-night-alacritty-theme/blob/main/tokyo-night.yaml
      colors = {
        primary = {
          background = "#24283b";
          foreground = "#a9b1d6";
        };
        normal = {
          black = "#32344a";
          red = "#f7768e";
          green = "#9ece6a";
          yellow = "#e0af68";
          blue = "#7aa2f7";
          magenta = "#ad8ee6";
          cyan = "#449dab";
          white = "#9699a8";
        };
        bright = {
          black = "#444b6a";
          red = "#ff7a93";
          green = "#b9f27c";
          yellow = "#ff9e64";
          blue = "#7da6ff";
          magenta = "#bb9af7";
          cyan = "#0db9d7";
          white = "#acb0d0";
        };
      };
    };
  };

  programs.neovide = {
    enable = true;
    package = unstable.neovide;
    settings = {
      fork = false;
      frame = "full";
      font = {
        normal = ["SauceCodePro Nerd Font Mono"];
        size = 20.0;
      };
    };
  };

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
      
      # Initialize zoxide for all zsh contexts
      eval "$(${pkgs.zoxide}/bin/zoxide init --cmd cd zsh)"
    '';
    initContent = ''
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
      source <(${pkgs.kubectl}/bin/kubectl completion zsh)

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

      # Worktree wrapper function that auto-evals cd command
      workout() {
        local result
        result="$(${homeDirectory}/.nix-profile/bin/workout "$@")"
        local exit_code=$?
        if [ $exit_code -eq 0 ]; then
          eval "$result"
        fi
        return $exit_code
      }

      # kubectl wrapper with syntax highlighting for explain command
      k() {
        if [[ "$1" == "explain" ]]; then
          ${pkgs.kubectl}/bin/kubectl "$@" | ${pkgs.bat}/bin/bat --language md --paging auto --style plain
        else
          ${pkgs.kubectl}/bin/kubectl "$@"
        fi
      }

      # Start tmux if not started
      if [ -z "$TMUX" ]; then
        exec ${homeDirectory}/.nix-profile/bin/tmux
      fi
    '';
    shellAliases = {
      desk = "cd ~/Desktop";
      down = "cd ~/Downloads";
      docs = "cd ~/Documents";
      pics = "cd ~/Pictures";
      hme = "vim ~/.config/nixpkgs/home.nix";
      hmo = "vim ~/.config/nixpkgs/overconfig.nix";
      hm = "cd ~/.config/nixpkgs";
      ll = "${pkgs.eza}/bin/eza --oneline --icons --sort=type";
      tree = "${pkgs.eza}/bin/eza --oneline --icons --sort=type --tree";
      "??" = "${pkgs.github-copilot-cli}/bin/github-copilot-cli what-the-shell";
      "git?" = "${pkgs.github-copilot-cli}/bin/github-copilot-cli git-assist";
      "gh?" = "${pkgs.github-copilot-cli}/bin/github-copilot-cli gh-assist";
      kn = "${pkgs.kubectx}/bin/kubens";
      kx = "${pkgs.kubectx}/bin/kubectx";
    };
  };

  programs.bash = {
    enable = true;
    profileExtra = ''
      # Initialize zoxide for all bash contexts
      eval "$(${pkgs.zoxide}/bin/zoxide init --cmd cd bash)"
    '';
  };

  programs.starship = {
    enable = true;
    enableZshIntegration = true;
  };

  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };

  programs.fzf = {
    enable = true;
    enableZshIntegration = true;
    tmux.enableShellIntegration = true;
  };

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
          set -g @theme_variation 'storm'
          set -g @theme_plugins 'datetime'
          set -g @theme_plugin_datetime_format ' %a %b%e %l:%M%p'
          set -g @theme_plugin_datetime_icon '  '
          set -g @theme_left_separator ''
          set -g @theme_right_separator ''
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

  programs.nix-index = {
    enable = true;
    enableZshIntegration = true;
  };

  programs.git = {
    enable = true;
    ignores = [ ".DS_Store" ".tags*" ".claude/settings.local.json" ];
    userName = "Karl Hepler";
    userEmail = "karl.hepler@gmail.com";
    extraConfig = {
      core.editor = "vim";
      diff.tool = "vimdiff";
      merge.tool = "vimdiff";
      difftool.prompt = false;
      push.default = "current";
      init.defaultBranch = "main";
      pull.rebase = false;
    };
    aliases = {
      who = "blame -w -C -C -C";
      difft = "-c diff.external=difft diff";
      logt = "-c diff.external=difft log -p --ext-diff";
      showt = "-c diff.external=difft show --ext-diff";
    };
  };

  # https://github.com/nix-community/home-manager/blob/master/modules/programs/neovim.nix
  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    vimdiffAlias = true;

    plugins = with pkgs.vimPlugins; [
      copilot-vim
      vim-sensible
      vim-surround
      vim-signify
      vim-pasta
      auto-pairs
      vim-commentary
      {
        plugin = vim-vinegar;
        config = ''
          " hide hidden files by default
          let g:netrw_list_hide = '\(^\|\s\s\)\zs\.\S\+'
        '';
      }
      vim-repeat
      vim-fugitive
      {
        plugin = vim-polyglot;
        config = ''
          let g:vim_json_syntax_conceal = 0
          let g:vim_markdown_conceal = 0
        '';
      }
      tokyonight-nvim
      {
        plugin = tokyonight-nvim;
        type = "lua";
        config = ''
          vim.cmd[[colorscheme tokyonight-storm]]
        '';
      }
      # Use plugin from GitHub repository
      {
        plugin = pkgs.vimUtils.buildVimPlugin {
          pname = "claude-tmux-neovim";
          version = "1.0.0";
          src = pkgs.fetchFromGitHub {
            owner = "karlhepler";
            repo = "claude-tmux-neovim";
            rev = "2fdd8531add11cf300fde34e4127d18a5e753a16";
            hash = "sha256-aTtsPAepD+nGsYcCyZ895DiTSPVWObR6U38YHQ9ozzE=";
          };
        };
        type = "lua";
        config = ''
          -- Initialize claude-tmux-neovim plugin with debugging disabled
          require('claude-tmux-neovim').setup({
            debug = false,  -- Disable debug mode for silent operation
            claude_code_cmd = "claude"  -- Explicitly set the command name
          })
        '';
      }
      {
        plugin = lightline-vim;
        config = ''
          set laststatus=2    " Always show status line
          set noshowmode      " Hide -- INSERT --
          let g:lightline={
          \   'colorscheme': 'tokyonight',
          \   'active': {
          \       'left': [
          \           ['mode'],
          \           ['gitbranch'],
          \           ['filename']
          \       ],
          \       'right': [
          \           ['lineinfo'],
          \           ['percent']
          \       ]
          \   },
          \   'component_function': {
          \       'gitbranch': 'FugitiveHead',
          \       'filename': 'LightlineFilename',
          \   }
          \}

          function! LightlineFilename()
              let cmd = winwidth(0) > 70 ? '%:f' : '%:t'
              let filename = expand(cmd) !=# "" ? expand(cmd) : '[No Name]'
              let modified = &modified ? '+ ' : ""
              return modified . filename
          endfunction
        '';
      }
      {
        plugin = fzfWrapper;
        config = ''
          function! s:build_quickfix_list(lines)
            call setqflist(map(copy(a:lines), '{ "filename": v:val }'))
            copen
            cc
          endfunction

          let g:fzf_action = {
          \ 'ctrl-q': function('s:build_quickfix_list'),
          \ 'ctrl-t': 'tab split',
          \ 'ctrl-s': 'split',
          \ 'ctrl-v': 'vsplit'
          \}

          let $FZF_DEFAULT_OPTS = '--bind ctrl-a:select-all'
        '';
      }
      {
        plugin = fzf-vim;
        config = ''
          nmap <c-p> :GFiles<cr>
          vmap <c-p> <esc>:GFiles<cr>

          " Map <C-p> to either navigate the popup menu or trigger :GFiles
          inoremap <expr> <C-p> pumvisible() ? "''\<C-p>" : "''\<esc>:GFiles''\<cr>"
        '';
      }
      vim-helm
      nvim-lspconfig
      {
        plugin = goto-preview;
        type = "lua";
        config = ''
          require('goto-preview').setup {
            default_mappings = true,
          }
          require('lspconfig').nil_ls.setup({
            on_attach = function(client, bufnr)
              local opts = { noremap = true, silent = true, buffer = bufnr }
              vim.keymap.set('n', 'gd', vim.lsp.buf.definition, opts) -- Go to definition
              vim.keymap.set('n', 'K', vim.lsp.buf.hover, opts)       -- Floating hover window
            end,
          })
        '';
      }
      (nvim-treesitter.withPlugins (
        plugins: with plugins; [
          tree-sitter-bash
          tree-sitter-c_sharp
          tree-sitter-gdscript
          tree-sitter-go
          tree-sitter-helm
          tree-sitter-lua
          tree-sitter-markdown
          tree-sitter-nix
          tree-sitter-python
          tree-sitter-rust
          tree-sitter-starlark
          tree-sitter-typescript
          tree-sitter-yaml
        ]
      ))
      SchemaStore-nvim
      plenary-nvim
      {
        plugin = fzf-lsp-nvim;
        config = ''
          nmap <c-b> :lua vim.lsp.buf.document_symbol()<cr>
          imap <c-b> <esc>:lua vim.lsp.buf.document_symbol()<cr>
          vmap <c-b> <esc>:lua vim.lsp.buf.document_symbol()<cr>
        '';
      }
      {
        plugin = vim-prettier;
        config = ''
          let g:prettier#autoformat = 1
          let g:prettier#autoformat_require_pragma = 0
        '';
      }
      {
        plugin = vim-rooter;
        config = ''
          let g:rooter_silent_chdir = 1
          let g:rooter_patterns = [".git"]
          let g:rooter_cd_cmd = "lcd"
        '';
      }
      {
        plugin = indent-blankline-nvim;
        type = "lua";
        config = ''
          local hooks = require "ibl.hooks"
          hooks.register(
            hooks.type.ACTIVE,
            function(bufnum)
              local filetype = vim.api.nvim_buf_get_option(bufnum, "filetype")
              return filetype == "python"
                  or filetype == "helm"
                  or filetype == "yaml"
            end
          )
          require("ibl").setup()
        '';
      }
      {
        plugin = haskell-tools-nvim;
        type = "lua";
        config = ''
          local ht = require('haskell-tools')
        '';
      }
      {
        plugin = twilight-nvim;
        type = "lua";
        # NOTE: To make the highlighting better, run :InspectTree in the buffer to see which treesitter attributes to expand.
        config = ''
          require("twilight").setup {
            dimming = {
              alpha = 0.25, -- amount of dimming
                            -- we try to get the foreground from the highlight groups or fallback color
              color = { "Normal", "#ffffff" },
              term_bg = "#000000", -- if guibg=NONE, this will be used to calculate text color
              inactive = false, -- when true, other windows will be fully dimmed (unless they contain the same buffer)
            },
            context = 10, -- amount of lines we will try to show around the current line
            treesitter = true, -- use treesitter when available for the filetype
                               -- treesitter is used to automatically expand the visible text,
                               -- but you can further control the types of nodes that should always be fully expanded
            expand = { -- for treesitter, we we always try to expand to the top-most ancestor with these types
              "attribute_item",
              "binding",
              "const_declaration",
              "const_item",
              "enum_item",
              "function_declaration",
              "function_definition",
              "function_item",
              "impl_item",
              "import_declaration",
              "method_declaration",
              "mod_item",
              "package_clause",
              "struct_item",
              "trait_item",
              "type_declaration",
              "use_declaration",
              "var_declaration",
            },
            exclude = {}, -- exclude these filetypes
          }
        '';
      }
    ];
    
    extraConfig = builtins.readFile ./neovim/vimrc;

    extraLuaConfig = builtins.readFile (pkgs.replaceVars ./neovim/lspconfig.lua {
      typescriptLanguageServer = "${pkgs.nodePackages.typescript-language-server}";
      bashLanguageServer = "${pkgs.nodePackages.bash-language-server}";
      omnisharpRoslyn = "${pkgs.omnisharp-roslyn}";
    });
  };

  programs.zoxide = {
    enable = true;
    enableZshIntegration = true;
    options = [ "--cmd" "cd" ];
  };
}
