{ config, pkgs, lib, ... }:

let
  username = config.home.username;
  homeDirectory = config.home.homeDirectory;

  shellapps = rec {
    commit = pkgs.writeShellApplication {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = ''
        git add "$(git rev-parse --show-toplevel)"
        git commit -m "$*"
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
        trunk="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"
        git checkout "$trunk"
        git pull
      '';
    };
    git-remix = pkgs.writeShellApplication {
      name = "git-remix";
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

in rec {
  # Home Packages
  # https://search.nixos.org/packages
  home.packages = with pkgs; [
    comma
    darwin.trash
    fd
    gnused
    go
    gopls
    htop
    nodePackages.bash-language-server
    nodePackages.pyright
    nodePackages.typescript
    nodePackages.typescript-language-server
    nodejs
    python3
    ripgrep
    shellcheck
    yaml-language-server
    yarn
    zsh-fzf-tab
  ] ++ [
    (pkgs.nerdfonts.override { fonts = [ "SourceCodePro" ]; })
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
          -e "set name of result to \"$(basename $appfile)\"" \
          -e "end tell"
      done
    '';

    gitIgnoreOverconfigChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --assume-unchanged overconfig.nix
    '';
  };

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
        EDITOR = "${pkgs.neovim}/bin/nvim";
        VISUAL = "${pkgs.neovim}/bin/nvim";
        SHELL = "${pkgs.zsh}/bin/zsh";
        GOPATH = "${homeDirectory}/go";
      };
      font = {
        normal = {
          family = "SauceCodePro Nerd Font Mono";
          style = "Regular";
        };
        size = 18;
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
      export PATH="$nix_profile_path:$nix_path:$PATH"
    '';
    initExtra = ''
      eval "$(${pkgs.zoxide}/bin/zoxide init --cmd cd zsh)"
      source '${pkgs.zsh-fzf-tab}/share/fzf-tab/fzf-tab.plugin.zsh'
      bindkey -M viins 'jk' vi-cmd-mode
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
    extraConfig = ''
      # customize status bar
      set-option -g status-position top
      set-option -g status-style bg=color8,fg=white
      set-option -g status-right "%a %b %d %l:%M %p"

      # vim mode with <C-b>[]
      set-window-option -g mode-keys vi
      bind-key -T copy-mode-vi 'v' send -X begin-selection
      bind-key -T copy-mode-vi 'y' send -X copy-selection-and-cancel
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

  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    vimdiffAlias = true;

    plugins = with pkgs.vimPlugins; [
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
      nvim-lspconfig
      (nvim-treesitter.withPlugins (
        plugins: with plugins; [
          tree-sitter-bash
          tree-sitter-go
          tree-sitter-lua
          tree-sitter-nix
          tree-sitter-python
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
    ];
    
    extraConfig = builtins.readFile ./neovim/vimrc;

    extraLuaConfig = builtins.readFile (pkgs.substituteAll {
      src = ./neovim/lspconfig.lua;
      typescript = "${pkgs.nodePackages.typescript}";
      typescriptLanguageServer = "${pkgs.nodePackages.typescript-language-server}";
      bashLanguageServer = "${pkgs.nodePackages.bash-language-server}";
    });
  };

  programs.zoxide = {
    enable = true;
    enableZshIntegration = true;
  };
}
