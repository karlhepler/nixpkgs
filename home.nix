{ config, pkgs, lib, ... }:

let
  homeDirectory = config.home.homeDirectory;

  shellapps = rec {
    commit = pkgs.writeShellApplication {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = ''
        msg="$*"
        if [ "$msg" == 'noop' ]; then
          git commit --allow-empty -m "$msg"
        else
          git add "$(git rev-parse --show-toplevel)"
          git commit -m "$msg"
        fi
      '';
    };
    pull = pkgs.writeShellApplication {
      name = "pull";
      runtimeInputs = [ pkgs.git ];
      text = ''
        set +e # keep going
        git pull 2> >(
          must_set_upstream=
          while IFS= read -r line; do
            if [[ $line == 'There is no tracking information for the current branch.' ]]; then
              must_set_upstream=true
              break
            fi
            echo "$line" >&2
          done

          git_pull_exit_code=$?
          if [[ $must_set_upstream != true ]]; then
            exit $git_pull_exit_code
          fi

          set -e # reset error handling
          branch="$(git symbolic-ref --short HEAD)"
          git branch --set-upstream-to="origin/$branch" "$branch"
          git pull
        )
      '';
    };
    push = pkgs.writeShellApplication {
      name = "push";
      runtimeInputs = [ pkgs.git ];
      text = ''
        git_push='git push'
        if ! git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
          git_push="$git_push --set-upstream"
        fi
        $git_push "$@"
      '';
    };
    save = pkgs.writeShellApplication {
      name = "save";
      runtimeInputs = [ commit push ];
      text = ''
        commit "$*"
        push
      '';
    };
    git-branches = pkgs.writeShellApplication {
      name = "git-branches";
      runtimeInputs = [ pkgs.git pkgs.fzf ];
      text = ''
        branch="''${1:-karlhepler/}"
        output="$(git for-each-ref --sort=-committerdate --format='%(refname:short)' "refs/heads/''${branch}*" "refs/remotes/''${branch}*")"
        
        # check if the script's output is connected to a terminal
        if [ -t 1 ]; then
          echo "$output" | fzf --preview 'git log --color {} -p -n 3' --bind 'enter:execute(git checkout {})+abort'
        else
          echo "$output"
        fi
      '';
    };
    git-kill = pkgs.writeShellApplication {
      name = "git-kill";
      runtimeInputs = [ pkgs.git ];
      text = ''
        # Navigate to the top-level directory of the git repository
        cd "$(git rev-parse --show-toplevel)"

        # Get the current branch name
        current_branch="$(git symbolic-ref --short HEAD)"

        # Check if the branch exists remotely
        if git ls-remote --exit-code --heads origin "$current_branch" &> /dev/null; then
            # If the branch exists remotely, reset the local branch to match the remote branch
            git reset --hard "origin/$current_branch"
        else
            # If the branch does not exist remotely, perform the local reset and clean operations
            git reset --hard
        fi

        # Clean untracked files and directories
        git clean -fd
      '';
    };
    git-trunk = pkgs.writeShellApplication {
      name = "git-trunk";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = ''
        git remote set-head origin -a # make sure there is an origin/HEAD
        trunk="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"
        git checkout "$trunk"
        git pull
      '';
    };
    git-sync = pkgs.writeShellApplication {
      name = "git-sync";
      runtimeInputs = [ pkgs.git git-trunk ];
      text = ''
        git trunk
        git checkout -
        git merge "$(git rev-parse --abbrev-ref '@{-1}')"
      '';
    };
    git-resume = pkgs.writeShellApplication {
      name = "git-resume";
      runtimeInputs = [ pkgs.git git-branches pkgs.coreutils ];
      text = ''
        git checkout "$(git branches | head -1)"
      '';
    };
    git-tmp = pkgs.writeShellApplication {
      name = "git-tmp";
      runtimeInputs = [ pkgs.git ];
      text = ''
        git branch -D karlhepler/tmp || true
        git checkout -b karlhepler/tmp
      '';
    };
  };

in {
  # Home Packages
  # https://search.nixos.org/packages
  home.packages = with pkgs; [
    bash
    cabal-install # Cabal installation tool for managing Haskell software
    comma
    darwin.trash
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
    mkcert
    nerd-fonts.sauce-code-pro
    nil
    nodePackages.bash-language-server
    nodePackages.typescript
    nodePackages.typescript-language-server
    nodejs
    pyright
    python3
    ripgrep
    shellcheck
    stack  # A cross-platform program for developing Haskell projects
    tilt
    yaml-language-server
    yarn
    yq
    zsh-fzf-tab
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
      env = {
        EDITOR = "${homeDirectory}/.nix-profile/bin/nvim";
        VISUAL = "${homeDirectory}/.nix-profile/bin/nvim";
        SHELL = "${homeDirectory}/.nix-profile/bin/zsh";
        GOPATH = "${homeDirectory}/go";
      };
      font = {
        normal = {
          family = "SauceCodePro Nerd Font Mono";
          style = "Regular";
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

  programs.zsh = {
    enable = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    profileExtra = ''
      nix_path='/nix/var/nix/profiles/default/bin'
      nix_profile_path='${homeDirectory}/.nix-profile/bin'
      go_bin_path="$GOPATH/bin"
      export PATH="$go_bin_path:$nix_profile_path:$nix_path:$PATH"
    '';
    initContent = ''
      eval "$(${pkgs.zoxide}/bin/zoxide init --cmd cd zsh)"
      source '${pkgs.zsh-fzf-tab}/share/fzf-tab/fzf-tab.plugin.zsh'
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

      # start tmux if not started
      if [ -z "$TMUX" ]; then
        exec ${homeDirectory}/.nix-profile/bin/tmux
      fi
    '';
    shellAliases = {
      desk = "cd ~/Desktop";
      down = "cd ~/Downloads";
      docs = "cd ~/Documents";
      pics = "cd ~/Pictures";
      hms = lib.strings.concatStringsSep "&&" [
        "mkdir -p ~/.backup/.config/nixpkgs"
        "cp ~/.config/nixpkgs/overconfig.nix ~/.backup/.config/nixpkgs/overconfig.nix"
        "${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --no-assume-unchanged overconfig.nix"
        "${pkgs.home-manager}/bin/home-manager switch --flake ~/.config/nixpkgs"
      ];
      hme = "vim ~/.config/nixpkgs/home.nix";
      hmo = "vim ~/.config/nixpkgs/overconfig.nix";
      hm = "cd ~/.config/nixpkgs";
      ll = "${pkgs.eza}/bin/eza --oneline --icons --sort=type";
      tree = "${pkgs.eza}/bin/eza --oneline --icons --sort=type --tree";
      "??" = "${pkgs.github-copilot-cli}/bin/github-copilot-cli what-the-shell";
      "git?" = "${pkgs.github-copilot-cli}/bin/github-copilot-cli git-assist";
      "gh?" = "${pkgs.github-copilot-cli}/bin/github-copilot-cli gh-assist";
    };
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
    historyLimit = 5000;
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
    ];
    extraConfig = ''
      # vim mode with <shortcut>[
      set-window-option -g mode-keys vi
      bind-key -T copy-mode-vi 'v' send -X begin-selection
      bind-key -T copy-mode-vi 'y' send -X copy-selection-and-cancel
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
    ignores = [ ".DS_Store" ".tags*" ];
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
            rev = "main"; 
            hash = "sha256-uZ/Aol/wCcyowgrvIy6NyLnVj42O8mHAzKt32FNcmLs=";
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
          tree-sitter-gdscript
          tree-sitter-go
          tree-sitter-helm
          tree-sitter-lua
          tree-sitter-markdown
          tree-sitter-nix
          tree-sitter-python
          tree-sitter-rust
          tree-sitter-typescript
          tree-sitter-yaml
        ]
      ))
      SchemaStore-nvim
      plenary-nvim
      {
        plugin = fzf-lsp-nvim;
        config = ''
          nmap <c-b> :DocumentSymbols<cr>
          imap <c-b> <esc>:DocumentSymbols<cr>
          vmap <c-b> <esc>:DocumentSymbols<cr>
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
    });
  };

  programs.zoxide = {
    enable = true;
    enableZshIntegration = true;
  };
}
