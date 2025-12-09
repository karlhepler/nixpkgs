{ config, pkgs, lib, unstable, ... }:

let
  homeDirectory = config.home.homeDirectory;

  # Import theme for use in modules
  theme = (import ./modules/theme.nix { inherit lib; }).theme;

  shellapps = rec {
    hms = pkgs.writeShellApplication {
      name = "hms";
      runtimeInputs = [ pkgs.git pkgs.home-manager ];
      text = builtins.readFile ./scripts/hms.bash;
    };
    commit = pkgs.writeShellApplication {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./scripts/git/commit.bash;
    };
    pull = pkgs.writeShellApplication {
      name = "pull";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./scripts/git/pull.bash;
    };
    push = pkgs.writeShellApplication {
      name = "push";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./scripts/git/push.bash;
    };
    save = pkgs.writeShellApplication {
      name = "save";
      runtimeInputs = [ commit push ];
      text = builtins.readFile ./scripts/git/save.bash;
    };
    git-branches = pkgs.writeShellApplication {
      name = "git-branches";
      runtimeInputs = [ pkgs.git pkgs.fzf ];
      text = builtins.readFile ./scripts/git/git-branches.bash;
    };
    git-kill = pkgs.writeShellApplication {
      name = "git-kill";
      runtimeInputs = [
        pkgs.git
        pkgs.git-lfs
        pkgs.coreutils
        pkgs.gnugrep
      ];
      text = builtins.readFile ./scripts/git/git-kill.bash;
    };
    git-trunk = pkgs.writeShellApplication {
      name = "git-trunk";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = builtins.readFile ./scripts/git/git-trunk.bash;
    };
    git-sync = pkgs.writeShellApplication {
      name = "git-sync";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = builtins.readFile ./scripts/git/git-sync.bash;
    };
    git-resume = pkgs.writeShellApplication {
      name = "git-resume";
      runtimeInputs = [ pkgs.git git-branches pkgs.coreutils ];
      text = builtins.readFile ./scripts/git/git-resume.bash;
    };
    git-tmp = pkgs.writeShellApplication {
      name = "git-tmp";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./scripts/git/git-tmp.bash;
    };
    workout = pkgs.writeShellApplication {
      name = "workout";
      runtimeInputs = [ pkgs.git pkgs.coreutils pkgs.gnused ];
      text = builtins.readFile ./scripts/git/workout.bash;
    };
    claude-notification-hook = pkgs.writeShellApplication {
      name = "claude-notification-hook";
      runtimeInputs = [ pkgs.python3 ];
      text = builtins.readFile ./scripts/claude/claude-notification-hook.bash;
    };
    claude-complete-hook = pkgs.writeShellApplication {
      name = "claude-complete-hook";
      runtimeInputs = [ ];
      text = builtins.readFile ./scripts/claude/claude-complete-hook.bash;
    };
    claude-csharp-format-hook = pkgs.writeShellApplication {
      name = "claude-csharp-format-hook";
      runtimeInputs = [ pkgs.csharpier pkgs.python3 ];
      text = builtins.readFile ./scripts/claude/claude-csharp-format-hook.bash;
    };
  };

in {
  # Import all modules
  imports = [
    ./modules/packages.nix   # Packages + simple programs (fzf, neovide, starship, zoxide, nix-index)
    ./modules/zsh.nix        # Zsh configuration + precompileZshCompletions activation
    ./modules/direnv.nix     # Direnv configuration + generateDirenvHook activation
    ./modules/alacritty.nix  # Alacritty terminal emulator
    ./modules/tmux.nix       # Tmux terminal multiplexer
    ./modules/git.nix        # Git configuration
    ./modules/claude.nix     # Claude Code activation hooks
  ];

  # Pass theme and shellapps to all modules
  _module.args = { inherit theme shellapps; };


  fonts.fontconfig.enable = true;


  # Automatically run the garbage collector weekly.
  nix.gc.automatic = true;

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  # Program Modules
  # https://nix-community.github.io/home-manager/options.html

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
          -- Nix LSP
          vim.lsp.config('nil_ls', {
            filetypes = { 'nix' },
            root_markers = { 'flake.nix', 'flake.lock', 'default.nix', '.git' }
          })
          vim.lsp.enable('nil_ls')
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

}
