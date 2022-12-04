{ config, pkgs, ... }:

let

  shellapps = {
    commit = pkgs.writeShellApplication {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = ''
        git add "$(git rev-parse --show-toplevel)"
        git commit -nm "$*"
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
  # Home Manager needs a bit of information about you and the
  # paths it should manage.
  home.username = "karlhepler";
  home.homeDirectory = "/Users/karlhepler";

  # Home Packages
  # https://search.nixos.org/packages
  home.packages = with pkgs; [
    fd
    go_1_19
    gopls
    ripgrep
    tree
    comma
  ] ++ (builtins.attrValues shellapps);

  # This value determines the Home Manager release that your
  # configuration is compatible with. This helps avoid breakage
  # when a new Home Manager release introduces backwards
  # incompatible changes.
  #
  # You can update Home Manager without changing this value. See
  # the Home Manager release notes for a list of state version
  # changes in each release.
  home.stateVersion = "22.11";

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
      EDITOR = "nvim";
      VISUAL = "nvim";
      SHELL = "fish";
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
      shell = "fish --login --interactive";
      editor = "nvim";
      cursor_shape = "block";
      cursor_blink_interval = 0;
      shell_integration = "no-cursor";
      mouse_hide_wait = -1;
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
      hms = "home-manager switch --flake ~/.config/nixpkgs#karlhepler";
      hme = "vim ~/.config/nixpkgs/home.nix";
      hm = "cd ~/.config/nixpkgs";
      ll = "${pkgs.exa}/bin/exa --oneline --icons --sort=type";
    };
    interactiveShellInit = ''
      bind \cx\ce edit_command_buffer
    '';
  };

  programs.starship = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.fzf = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.nix-index = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.git = {
    enable = true;
    delta.enable = true;
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
        ]
      ))
    ];
    
    extraConfig = ''
      lua << EOF
      local lspconfig = require 'lspconfig'
      local treesitter_configs = require 'nvim-treesitter.configs'

      treesitter_configs.setup {
        ensure_installed = {'go'},
        highlight = {
          enable = true,
        },
        parser_install_dir = "${home.homeDirectory}/.vim/treesitter-parsers",
      }

      -- Mappings (adapted from https://github.com/neovim/nvim-lspconfig#suggested-configuration)
      -- See `:help vim.diagnostic.*` for documentation on any of the below functions
      local opts = { noremap=true, silent=true }
      vim.api.nvim_set_keymap('n', '<space>e', '<cmd>lua vim.diagnostic.open_float()<CR>', opts)
      vim.api.nvim_set_keymap('n', '[d', '<cmd>lua vim.diagnostic.goto_prev()<CR>', opts)
      vim.api.nvim_set_keymap('n', ']d', '<cmd>lua vim.diagnostic.goto_next()<CR>', opts)
      vim.api.nvim_set_keymap('n', '<space>q', '<cmd>lua vim.diagnostic.setloclist()<CR>', opts)

      -- Use an on_attach function to only map the following keys
      -- after the language server attaches to the current buffer
      local on_attach = function(client, bufnr)
        -- Enable completion triggered by <c-x><c-o>
        vim.api.nvim_buf_set_option(bufnr, 'omnifunc', 'v:lua.vim.lsp.omnifunc')

        -- Mappings.
        -- See `:help vim.lsp.*` for documentation on any of the below functions
        vim.api.nvim_buf_set_keymap(bufnr, 'n', 'gD', '<cmd>lua vim.lsp.buf.declaration()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', 'gd', '<cmd>lua vim.lsp.buf.definition()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', 'K', '<cmd>lua vim.lsp.buf.hover()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', 'gi', '<cmd>lua vim.lsp.buf.implementation()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', '<C-k>', '<cmd>lua vim.lsp.buf.signature_help()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', '<space>wa', '<cmd>lua vim.lsp.buf.add_workspace_folder()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', '<space>wr', '<cmd>lua vim.lsp.buf.remove_workspace_folder()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', '<space>wl', '<cmd>lua print(vim.inspect(vim.lsp.buf.list_workspace_folders()))<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', '<space>D', '<cmd>lua vim.lsp.buf.type_definition()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', '<space>rn', '<cmd>lua vim.lsp.buf.rename()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', '<space>ca', '<cmd>lua vim.lsp.buf.code_action()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', 'gr', '<cmd>lua vim.lsp.buf.references()<CR>', opts)
        vim.api.nvim_buf_set_keymap(bufnr, 'n', '<space>f', '<cmd>lua vim.lsp.buf.formatting()<CR>', opts)
      end

      lspconfig.gopls.setup {
        on_attach = on_attach,
      }

      -- https://github.com/golang/tools/blob/1f10767725e2be1265bef144f774dc1b59ead6dd/gopls/doc/vim.md#imports
      function OrgImports(wait_ms)
        local params = vim.lsp.util.make_range_params()
        params.context = {only = {"source.organizeImports"}}
        local result = vim.lsp.buf_request_sync(0, "textDocument/codeAction", params, wait_ms)
        for _, res in pairs(result or {}) do
          for _, r in pairs(res.result or {}) do
            if r.edit then
              vim.lsp.util.apply_workspace_edit(r.edit, "UTF-8")
            else
              vim.lsp.buf.execute_command(r.command)
            end
          end
        end
      end

      vim.api.nvim_create_autocmd("BufWritePre", {
        pattern = {'*.go'},
        callback = function()
            vim.lsp.buf.formatting_sync()
            OrgImports(1000)
        end,
        group = vim.api.nvim_create_augroup("lsp_document_format", {clear = true}),
      })
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

      " highlight current line (not supported in kitty)
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
      nmap <c-d> 5j5<c-e>
      vmap <c-d> 5j5<c-e>
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
