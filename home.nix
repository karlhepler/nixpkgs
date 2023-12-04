{ config, pkgs, specialArgs, ... }:

let
  inherit (specialArgs) username;

  shellapps = rec {
    commit = pkgs.writeShellApplication {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = ''
        git add "$(git rev-parse --show-toplevel)"
        git commit -m "$*"
      '';
    };
    save = pkgs.writeShellApplication {
      name = "save";
      runtimeInputs = [ pkgs.git commit ];
      text = ''
        commit "$*"
        git push
      '';
    };
    git-kill = pkgs.writeShellApplication {
      name = "git-kill";
      runtimeInputs = [ pkgs.git ];
      text = ''
        cd "$(git rev-parse --show-toplevel)"
        git reset --hard
        git clean -fd
      '';
    };
    git-remain = pkgs.writeShellApplication {
      name = "git-remain";
      runtimeInputs = [ pkgs.git ];
      text = ''
        git checkout main
        git pull
        git checkout -
        git rebase main
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
    fd
    go
    gopls
    nodePackages.pyright
    nodePackages.typescript
    nodePackages.typescript-language-server
    nodejs
    python3
    ripgrep
    yarn
    devbox
    htop
  ] ++ (builtins.attrValues shellapps);

  # This value determines the Home Manager release that your
  # configuration is compatible with. This helps avoid breakage
  # when a new Home Manager release introduces backwards
  # incompatible changes.
  #
  # You can update Home Manager without changing this value. See
  # the Home Manager release notes for a list of state version
  # changes in each release.
  home.stateVersion = "23.11";

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  # Program Modules
  # https://nix-community.github.io/home-manager/options.html

  programs.kitty = {
    enable = true;
    darwinLaunchOptions = [
      "--single-instance"
    ];
    environment = {
      EDITOR = "${pkgs.neovim}/bin/nvim";
      VISUAL = "${pkgs.neovim}/bin/nvim";
      SHELL = "${pkgs.fish}/bin/fish";
    };
    keybindings = {
      "cmd+enter" = "toggle_fullscreen";
      "cmd+n" = "new_os_window_with_cwd";
      "cmd+t" = "new_tab_with_cwd";
      "cmd+d" = "launch --cwd=current --location=vsplit";
      "cmd+shift+d" = "launch --cwd=current --location=hsplit";
    };
    settings = {
      enabled_layouts = "splits";
      macos_traditional_fullscreen = "yes";
      shell = "${pkgs.fish}/bin/fish --login --interactive";
      editor = "${pkgs.neovim}/bin/nvim";
      cursor_shape = "block";
      cursor_blink_interval = 0;
      shell_integration = "no-cursor";
      mouse_hide_wait = -1;
      enable_audio_bell = "no";
    };
    font = {
      package = (pkgs.nerdfonts.override { fonts = [ "SourceCodePro" ]; });
      name = "SauceCodePro Nerd Font";
      size = 18;
    };
    theme = "Tokyo Night Storm";
  };

  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };

  programs.fish = {
    enable = true;
    shellAliases = {
      desk = "cd ~/Desktop";
      down = "cd ~/Downloads";
      docs = "cd ~/Documents";
      pics = "cd ~/Pictures";
      hms = "home-manager switch --flake ~/.config/nixpkgs#${username}";
      hme = "vim ~/.config/nixpkgs/home.nix";
      hm = "cd ~/.config/nixpkgs";
      ll = "${pkgs.eza}/bin/eza --oneline --icons --sort=type";
      tree = "${pkgs.eza}/bin/eza --oneline --icons --sort=type --tree";
      github = "cd ~/github.com/karlhepler";
    };
    interactiveShellInit = ''
      bind \cx\ce edit_command_buffer
    '';
    shellInit = ''
      fish_add_path --prepend --global "/nix/var/nix/profiles/default/bin"
      fish_add_path --prepend --global "/Users/${username}/.nix-profile/bin"
    '';
  };

  programs.starship = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.fzf = {
    enable = true;
    enableFishIntegration = true;
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
    enableFishIntegration = true;
  };

  programs.git = {
    enable = true;
    ignores = [ ".DS_Store" ".tags*" ];
    userName = "Karl Hepler";
    userEmail = "karl.hepler@gmail.com";
    includes = [
      {
        contents = {
          core = { editor = "vim"; };
          diff = { tool = "vimdiff"; };
          merge = { tool = "vimdiff"; };
          difftool = { prompt = false; };
          push = { default = "current"; };
          init = { defaultBranch = "main"; };
          pull = { rebase = false; };
        };
      }
    ];
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
        plugin = vim-rooter;
        config = ''
          let g:rooter_silent_chdir = 1
          let g:rooter_patters = ['.git']
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
          imap <c-p> <esc>:GFiles<cr>
          vmap <c-p> <esc>:GFiles<cr>

          nmap <c-b> :BTags<cr>
          imap <c-b> <esc>:BTags<cr>
          vmap <c-b> <esc>:BTags<cr>
        '';
      }
      nvim-lspconfig
      (nvim-treesitter.withPlugins (
        plugins: with plugins; [
          tree-sitter-go
          tree-sitter-python
          tree-sitter-typescript
        ]
      ))
      {
        plugin = vim-prettier;
        config = ''
          let g:prettier#autoformat = 1
          let g:prettier#autoformat_require_pragma = 0
        '';
      }
      {
        plugin = emmet-vim;
        config = ''
          let g:user_emmet_leader_key='<c-e>'
        '';
      }
    ];
    
    extraConfig = ''
      lua << EOF
      ${builtins.readFile (pkgs.substituteAll {
        src = ./neovim/lspconfig.lua;
        typescript = "${pkgs.nodePackages.typescript}";
        typescriptLanguageServer = "${pkgs.nodePackages.typescript-language-server}";
      })}
      EOF

      set nocompatible

      let mapleader=','
      imap jk <esc>

      set background=dark
      colorscheme tokyonight-storm

      set shell=fish " use fish for :term
      set grepprg=rg\ --vimgrep " use ripgrep for :grep

      " no swap files or backup files
      set noswapfile
      set nobackup
      set nowritebackup

      " allow hidden buffers for easier multi-file editing
      set hidden

      " detect plugins and indentation per filetype
      filetype plugin indent on

      " sensible split defaults
      set splitbelow
      set splitright

      " no annoying bells
      set noerrorbells
      set visualbell

      " highlight current line (not supported by kitty, so need to do here)
      set cursorline

      " always show at least 1 line above/below cursor
      set scrolloff=1

      " disable word wrapping
      set nowrap
      set textwidth=0
      set wrapmargin=0
      set formatoptions-=t

      " ignore case when searching lowercase
      set ignorecase
      set smartcase

      " when a file has changed outside of vim, automatically read it again
      set autoread

      " always show sign column
      set signcolumn=yes

      " tame horizontal scroll
      set sidescroll=1

      " no double spaces after periods when joining lines
      set nojoinspaces

      " search highlighting off
      nmap <silent> <leader><space> :nohlsearch<cr>

      " reload current file
      nmap <silent> <leader>f :e!<cr>

      " comma + enter goes to insert mode
      nnoremap ,<cr> A,<cr>

      " highlight word without jump in normal mode
      nmap <c-w><c-w> :keepjumps normal! mi*`i<cr>

      " tame the half-page scroller
      nmap <c-d> 5<c-e>5j
      vmap <c-d> 5<c-e>5j
      nmap <c-u> 5k5<c-y>
      vmap <c-u> 5k5<c-y>

      " quickfix mappings
      nmap <up> :copen<cr>
      nmap <down> :cclose<cr>
      nmap <left> :cprevious<cr>
      nmap <right> :cnext<cr>

      " copy relative & absolute paths to system clipboard
      nmap <silent> <LEADER>cf :let @+ = expand("%")<CR>
      nmap <silent> <LEADER>cF :let @+ = expand("%:p")<CR>

      " horizontal center to cursor position
      nnoremap <silent> zm zszH

      " open terminal at current buffer path
      map <C-T> <ESC>:let $BUFPATH=expand('%:p:h')<CR>:terminal<CR>cd $BUFPATH && clear<CR>

      " helpful split views
      nmap <C-W>} =42>
      nmap <C-W>{ =42<
      nmap <C-W>O onH{l

      " not quite high and low
      noremap H 3H
      noremap L 3L

      " disable fancy cursor
      set guicursor=

      " vim fugitive mapping
      " this has to be done here because plugins are loaded before extraConfig
      nmap <leader>b :Buffers<cr>
      imap <leader>b <esc>:Buffers<cr>
      vmap <leader>b <esc>:Buffers<cr>

      " RestoreCursor restores the last cursor position.
      function! RestoreCursor()
          if line("'\"") <= line("$")
              normal! g`"
              return 1
          endif
      endfunction

      augroup config
        autocmd!

        " jump to last cursor position on file load
        autocmd BufWinEnter * silent! call RestoreCursor()

        " force quickfix to always open full width
        autocmd FileType qf wincmd J
      augroup end
    '';
  };
}
