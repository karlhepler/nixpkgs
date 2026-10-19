{ pkgs, theme, ... }:

{
  # ============================================================================
  # Neovim Plugins
  # ============================================================================
  # All plugin declarations organized by category with clear sections
  # ============================================================================

  programs.neovim.plugins = with pkgs.vimPlugins; [

    # ==========================================================================
    # CORE EDITING PLUGINS
    # Essential editing enhancements
    # ==========================================================================

    copilot-vim
    vim-surround
    vim-pasta
    auto-pairs
    vim-repeat
    vim-fugitive

    {
      plugin = gitsigns-nvim;
      type = "lua";
      config = ''
        require('gitsigns').setup {
          on_attach = function(bufnr)
            local gs = require('gitsigns')
            local function map(lhs, rhs, desc)
              vim.keymap.set('n', lhs, rhs, { buffer = bufnr, desc = desc })
            end

            -- Hunk navigation (diff mode keeps Vim's own ]c / [c)
            map(']c', function()
              if vim.wo.diff then vim.cmd.normal({ ']c', bang = true }) else gs.nav_hunk('next') end
            end, 'Next hunk')
            map('[c', function()
              if vim.wo.diff then vim.cmd.normal({ '[c', bang = true }) else gs.nav_hunk('prev') end
            end, 'Previous hunk')

            map('<leader>hs', gs.stage_hunk, 'Stage hunk')
            map('<leader>hr', gs.reset_hunk, 'Reset hunk')
            map('<leader>hS', gs.stage_buffer, 'Stage buffer')
            map('<leader>hp', gs.preview_hunk, 'Preview hunk')
            map('<leader>hb', function() gs.blame_line({ full = true }) end, 'Blame line')
            map('<leader>ht', gs.toggle_current_line_blame, 'Toggle inline blame')
          end,
        }
      '';
    }

    {
      # Format on save for the filetypes that were already formatted on save; <space>f
      # formats any buffer on demand. Formatter binaries are on Neovim's PATH (default.nix).
      plugin = conform-nvim;
      type = "lua";
      config = ''
        local prettier = { 'prettierd' }

        -- Only formatted on save where a formatter already ran on save before conform.
        -- The value is how to fall back when no listed formatter ran: to the language
        -- server ('fallback') or not at all ('never').
        local format_on_save = {
          go = 'fallback',
          typescript = 'fallback',
          typescriptreact = 'fallback',
          cs = 'fallback',
          rust = 'never',
          javascript = 'never',
          javascriptreact = 'never',
          json = 'never',
          css = 'never',
          scss = 'never',
          html = 'never',
          yaml = 'never',
          markdown = 'never',
        }

        require('conform').setup {
          -- A save in a project without a prettier config is not worth a message
          notify_no_formatters = false,
          formatters_by_ft = {
            lua = { 'stylua' },
            sh = { 'shfmt' },
            bash = { 'shfmt' },
            nix = { 'nixfmt' },
            rust = { 'rustfmt' },
            cs = { 'csharpier' },
            javascript = prettier,
            javascriptreact = prettier,
            typescript = prettier,
            typescriptreact = prettier,
            json = prettier,
            jsonc = prettier,
            yaml = prettier,
            markdown = prettier,
            css = prettier,
            scss = prettier,
            html = prettier,
          },
          formatters = {
            -- Only where the project has a prettier config, as vim-prettier did
            prettierd = { require_cwd = true },
          },
          format_on_save = function(bufnr)
            local lsp_format = format_on_save[vim.bo[bufnr].filetype]
            if lsp_format then
              return { timeout_ms = 2000, lsp_format = lsp_format }
            end
          end,
        }
      '';
    }

    {
      plugin = vim-vinegar;
      type = "viml";
      config = ''
        " hide hidden files by default
        let g:netrw_list_hide = '\(^\|\s\s\)\zs\.\S\+'
      '';
    }

    # ==========================================================================
    # LSP & CODE INTELLIGENCE
    # Server defaults, schemas, syntax trees. The Lua config is in plugin/.
    # ==========================================================================

    nvim-lspconfig
    SchemaStore-nvim

    {
      plugin = goto-preview;
      type = "lua";
      config = ''
        require('goto-preview').setup {
          default_mappings = true,
        }
      '';
    }

    (nvim-treesitter.withPlugins (
      plugins: with plugins; [
        tree-sitter-bash
        tree-sitter-c_sharp
        tree-sitter-css
        tree-sitter-diff
        tree-sitter-dockerfile
        tree-sitter-gdscript
        tree-sitter-go
        tree-sitter-gomod
        tree-sitter-gowork
        tree-sitter-hcl
        tree-sitter-helm
        tree-sitter-html
        tree-sitter-javascript
        tree-sitter-json
        tree-sitter-lua
        tree-sitter-make
        tree-sitter-markdown
        tree-sitter-markdown_inline
        tree-sitter-nix
        tree-sitter-python
        tree-sitter-regex
        tree-sitter-ruby
        tree-sitter-rust
        tree-sitter-sql
        tree-sitter-starlark
        tree-sitter-toml
        tree-sitter-tsx
        tree-sitter-typescript
        tree-sitter-vim
        tree-sitter-yaml
      ]
    ))

    # ==========================================================================
    # UI & THEME PLUGINS
    # Visual appearance and themes
    # ==========================================================================

    # CRITICAL: Theme integration using centralized theme.variant
    {
      plugin = tokyonight-nvim;
      type = "lua";
      config = ''
        vim.cmd[[colorscheme tokyonight-${theme.variant}]]
      '';
    }

    {
      plugin = lightline-vim;
      type = "viml";
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
      plugin = indent-blankline-nvim;
      type = "lua";
      config = ''
        local hooks = require "ibl.hooks"
        hooks.register(
          hooks.type.ACTIVE,
          function(bufnum)
            local filetype = vim.bo[bufnum].filetype
            return filetype == "python"
                or filetype == "helm"
                or filetype == "yaml"
          end
        )
        require("ibl").setup()
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

    # ==========================================================================
    # LANGUAGE-SPECIFIC PLUGINS
    # Syntax is treesitter plus Neovim's bundled runtime; vim-helm adds helm filetypes
    # ==========================================================================

    vim-helm

    # ==========================================================================
    # TOOL INTEGRATIONS
    # External tool plugins (FZF, Claude, project root, etc.)
    # ==========================================================================

    {
      plugin = pkgs.vimUtils.buildVimPlugin {
        pname = "claude-tmux-neovim";
        version = "2.0.0-local";
        src = ./claude-tmux-neovim-local;
      };
      type = "lua";
      config = ''
        -- Initialize claude-tmux-neovim plugin (local optimized version)
        require('claude-tmux-neovim').setup({
          debug = false,
          claude_code_cmd = "claude"
        })
      '';
    }

    {
      plugin = pkgs.vimUtils.buildVimPlugin {
        pname = "cathy";
        version = "0.1.0-local";
        src = ./cathy-local;
      };
      type = "lua";
      config = ''
        require('cathy').setup({})
      '';
    }

    {
      plugin = fzf-wrapper;
      type = "viml";
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
      type = "viml";
      config = ''
        nmap <c-p> :GFiles<cr>
        vmap <c-p> <esc>:GFiles<cr>

        " Map <C-p> to either navigate the popup menu or trigger :GFiles
        inoremap <expr> <C-p> pumvisible() ? "''\<C-p>" : "''\<esc>:GFiles''\<cr>"
      '';
    }

    {
      plugin = vim-rooter;
      type = "viml";
      config = ''
        let g:rooter_silent_chdir = 1
        let g:rooter_patterns = [".git"]
        let g:rooter_cd_cmd = "lcd"
      '';
    }
  ];
}
