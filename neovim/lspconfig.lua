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

-- LSP completion with fallback to regular vim completion
local function lsp_or_keyword_complete()
  -- Check if the popup menu is visible
  if vim.fn.pumvisible() == 1 then
    -- Use <C-n> to navigate the popup menu
    return vim.api.nvim_replace_termcodes('<C-n>', true, true, true)
  end

  -- Check if omnifunc is set and not empty (LSP completion)
  local omnifunc = vim.api.nvim_buf_get_option(0, 'omnifunc')
  if omnifunc ~= '' then
    -- Trigger omnifunc completion
    return vim.api.nvim_replace_termcodes('<C-x><C-o>', true, true, true)
  else
    -- If no omnifunc, fallback to normal <C-n> keyword completion
    return vim.api.nvim_replace_termcodes('<C-n>', true, true, true)
  end
end

-- Map <C-n> to use LSP completion with fallback to keyword completion
vim.keymap.set('i', '<C-n>', lsp_or_keyword_complete, {expr = true, noremap = true})

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
			schemas = {
				kubernetes = "*.yaml"
			},
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

lspconfig.starpls.setup {
	on_attach = on_attach,
	filetypes = { "bzl", "bazel", "star", "starlark" },
}

-- Configure OmniSharp for C# LSP
lspconfig.omnisharp.setup({
	cmd = { "@omnisharpRoslyn@/bin/OmniSharp", "--languageserver", "--hostPID", tostring(vim.fn.getpid()) },
	on_attach = on_attach,
	capabilities = capabilities,
	root_dir = function(fname)
		return lspconfig.util.root_pattern("*.sln", "*.csproj", "omnisharp.json", "function.json")(fname)
			or lspconfig.util.find_git_ancestor(fname)
	end,
	settings = {
		FormattingOptions = {
			EnableEditorConfigSupport = true,
			OrganizeImports = true,
		},
		MsBuild = {
			LoadProjectsOnDemand = false,
		},
		RoslynExtensionsOptions = {
			EnableAnalyzersSupport = true,
			EnableImportCompletion = true,
		},
	},
})

-- Set up file associations for C#
vim.filetype.add({
	extension = {
		cs = 'cs',
	}
})

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

vim.api.nvim_create_autocmd("BufWritePre", {
	pattern = {'*.cs'},
	callback = function()
			vim.lsp.buf.format()
			-- Run csharpier for consistent code formatting after LSP handles using statements
			local file = vim.fn.expand('%:p')
			vim.fn.system('csharpier "' .. file .. '"')
	end,
	group = vim.api.nvim_create_augroup("lsp_document_format_cs", {clear = true}),
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

-- STARLARK CONFIGURATION ------------------------------------------------------

-- Early filetype configuration for Starlark
vim.filetype.add({
  extension = {
    star = 'starlark',
    bzl = 'starlark',
  },
  filename = {
    ['BUILD'] = 'starlark',
    ['BUILD.bazel'] = 'starlark',
    ['MODULE.bazel'] = 'starlark',
    ['WORKSPACE'] = 'starlark',
    ['WORKSPACE.bazel'] = 'starlark',
    ['Tiltfile'] = 'starlark',
  },
})

-- GODOT CONFIGURATION ---------------------------------------------------------

-- Early filetype configuration
vim.filetype.add({
  extension = {
    gd = 'gdscript',      -- GDScript files
  },
})

-- Fallback using autocmd for stubborn cases
vim.api.nvim_create_autocmd({"BufRead", "BufNewFile"}, {
  pattern = {"*.gd"},
  command = "set filetype=gdscript",
})

-- Autocmd group for Godot LSP setup
local godotLspGroup = vim.api.nvim_create_augroup("GodotLspConfig", { clear = true })

-- Autocmd to start the Godot LSP client only when a gdscript file is opened
vim.api.nvim_create_autocmd("FileType", {
  group = godotLspGroup,
  pattern = "gdscript", -- Trigger on the gdscript filetype
  callback = function()
    -- Check if the Godot client is already running for this buffer's project
    -- This prevents trying to start it multiple times for the same project
    local clients = vim.lsp.get_active_clients({ name = "Godot", bufnr = 0 })
    if #clients > 0 then
      -- print("Godot LSP already active for this project.") -- Keep commented or remove
      return
    end

    local port = os.getenv('GDScript_Port') or '6005'
    local cmd_connect -- Use a different name to avoid conflict with vim.cmd
    -- Use pcall for safety in case connection fails
    local ok, result = pcall(vim.lsp.rpc.connect, '127.0.0.1', port)
    if not ok or not result then
        vim.notify("Failed to connect to Godot LSP on port " .. port .. ". Is Godot editor running with LSP enabled?", vim.log.levels.WARN)
        return
    end
    cmd_connect = result -- Assign the connection object if successful

    -- Determine root directory
    local root_dir_path = vim.fs.find({ 'project.godot', '.git' }, { upward = true, stop = vim.loop.os_homedir(), type = 'file' })
    local root_dir = nil
    if root_dir_path and #root_dir_path > 0 then
        root_dir = vim.fs.dirname(root_dir_path[1])
    end

    if not root_dir then
        vim.notify("Could not find 'project.godot' or '.git' to determine project root.", vim.log.levels.INFO)
    end

    -- Start the LSP client configuration
    vim.lsp.start({
      name = 'Godot',
      cmd = cmd_connect, -- Pass the established connection
      -- autostart = false, -- Default is false, no need to explicitly set when using vim.lsp.start manually
      filetypes = { 'gdscript' },
      root_dir = root_dir,
      on_attach = on_attach -- Make sure 'on_attach' is defined and accessible
    })
  end,
})
