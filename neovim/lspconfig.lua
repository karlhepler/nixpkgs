-- TODO: Separate this file by language and use this guide.
-- https://rishabhrd.github.io/jekyll/update/2020/09/19/nvim_lsp_config.html
local lspconfig = require 'lspconfig'
local treesitter_configs = require 'nvim-treesitter.configs'

treesitter_configs.setup {
	highlight = { enable = true },
	incremental_selection = { enable = true },
	indent = { enable = true },
}

-- Mappings (adapted from https://github.com/neovim/nvim-lspconfig#suggested-configuration)
-- See `:help vim.diagnostic.*` for documentation on any of the below functions
local opts = { noremap=true, silent=true }
vim.api.nvim_set_keymap('n', '<space>e', '<cmd>lua vim.diagnostic.open_float()<CR>', opts)
vim.api.nvim_set_keymap('n', '[d', '<cmd>lua vim.diagnostic.goto_prev()<CR>', opts)
vim.api.nvim_set_keymap('n', ']d', '<cmd>lua vim.diagnostic.goto_next()<CR>', opts)
vim.api.nvim_set_keymap('n', '<space>q', '<cmd>lua vim.diagnostic.setloclist()<CR>', opts)

-- Define the function locally
local function fallback_or_omnifunc()
  -- Check if the popup menu is visible
  if vim.fn.pumvisible() == 1 then
    -- Use <C-n> to navigate the popup menu
    return vim.api.nvim_replace_termcodes('<C-n>', true, true, true)
  end

  -- Check if omnifunc is set and not empty
  local omnifunc = vim.api.nvim_buf_get_option(0, 'omnifunc')
  if omnifunc ~= '' then
    -- Trigger omnifunc completion
    return vim.api.nvim_replace_termcodes('<C-x><C-o>', true, true, true)
  else
    -- If no omnifunc and no popup menu, fallback to normal <C-n> behavior
    return vim.api.nvim_replace_termcodes('<C-n>', true, true, true)
  end
end

-- Map <C-n> to the local function in insert mode using vim.keymap.set
vim.keymap.set('i', '<C-n>', fallback_or_omnifunc, {expr = true, noremap = true})

-- Use an on_attach function to only map the following keys
-- after the language server attaches to the current buffer
local on_attach = function(client, bufnr)
	-- Enable omnifunc completion
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

lspconfig.ts_ls.setup {
	on_attach = on_attach,
	cmd = {
		"@typescriptLanguageServer@/bin/typescript-language-server",
		"--stdio"
	}
}

lspconfig.gopls.setup {
	on_attach = on_attach,
}

lspconfig.pyright.setup {
	on_attach = on_attach,
}

lspconfig.yamlls.setup {
	on_attach = on_attach,
	settings = {
		yaml = {
			schemaStore = {
				-- You must disable built-in schemaStore support if you want to use
        -- this plugin and its advanced options like `ignore`.
        enable = false,
        -- Avoid TypeError: Cannot read properties of undefined (reading 'length')
        url = "",
			},
			schemas = require('schemastore').yaml.schemas(),
		},
	},
}

lspconfig.helm_ls.setup {
	settings = {
		['helm-ls'] = {
			yamlls = {
				path = 'yaml-language-server'
			}
		}
	}
}

lspconfig.rust_analyzer.setup {
	on_attach = on_attach,
	settings = {
		['rust-analyzer'] = {
			imports = {
				granularity = {
					group = "module",
				},
				prefix = "self",
			},
			cargo = {
				buildScripts = {
					enable = true,
				},
			},
			procMacro = {
				enable = true
			},
		}
	}
}

-- https://github.com/golang/tools/blob/1f10767725e2be1265bef144f774dc1b59ead6dd/gopls/doc/vim.md#imports
-- https://github.com/typescript-language-server/typescript-language-server#code-actions-on-save
function OrgImports(code_action, wait_ms)
	local params = vim.lsp.util.make_range_params()
	params.context = {only = { code_action }}
	local result = vim.lsp.buf_request_sync(0, "textDocument/codeAction", params, wait_ms)
	for _, res in pairs(result or {}) do
		for _, r in pairs(res.result or {}) do
			if r.edit then
				vim.lsp.util.apply_workspace_edit(r.edit, "utf-8")
			else
				vim.lsp.buf.execute_command(r.command)
			end
		end
	end
end

vim.api.nvim_create_autocmd("BufWritePre", {
	pattern = {'*.go'},
	callback = function()
			vim.lsp.buf.format()
			OrgImports("source.organizeImports", 1000)
	end,
	group = vim.api.nvim_create_augroup("lsp_document_format_go", {clear = true}),
})

vim.api.nvim_create_autocmd("BufWritePre", {
	pattern = {'*.ts', '*.tsx'},
	callback = function()
			vim.lsp.buf.format()
			OrgImports("source.addMissingImports.ts", 1000)
			OrgImports("source.organizeImports.ts", 1000)
	end,
	group = vim.api.nvim_create_augroup("lsp_document_format_ts", {clear = true}),
})

vim.api.nvim_create_autocmd('FileType', {
  pattern = 'sh',
  callback = function()
    vim.lsp.start({
      name = 'bash-language-server',
      cmd = { '@bashLanguageServer@/bin/bash-language-server', 'start' },
    })
  end,
})
