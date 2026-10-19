-- =============================================================================
-- LSP SERVER SETTINGS
-- Per-server overrides on top of nvim-lspconfig's defaults
-- =============================================================================
-- These are vim.lsp.config() calls on purpose. A file in a 'runtimepath' lsp/ directory
-- would lose to nvim-lspconfig's own file for any key both of them set (lspconfig is
-- later in 'runtimepath'), so e.g. a filetypes or cmd override would be silently
-- ignored. vim.lsp.config() always wins. Servers not listed here use the defaults.

-- Rust
vim.lsp.config('rust_analyzer', {
	settings = {
		['rust-analyzer'] = {
			imports = {
				granularity = {
					group = 'module',
				},
				prefix = 'self',
			},
			cargo = {
				buildScripts = {
					enable = true,
				},
			},
			procMacro = {
				enable = true,
			},
		},
	},
})

-- YAML: schemas come from SchemaStore.nvim (bundled, so no network lookup), and the
-- Kubernetes schema applies only to the usual manifest locations. It used to apply to
-- every *.yaml, which flagged workflows, compose files and the like as errors.
vim.lsp.config('yamlls', {
	settings = {
		yaml = {
			schemaStore = { enable = false, url = '' },
			schemas = vim.tbl_extend('force', require('schemastore').yaml.schemas(), {
				kubernetes = {
					'**/k8s/**/*.y*ml',
					'**/kubernetes/**/*.y*ml',
					'**/manifests/**/*.y*ml',
					'*.k8s.y*ml',
				},
			}),
		},
	},
})

-- JSON: schemas from SchemaStore.nvim (jsonls has no catalog of its own)
vim.lsp.config('jsonls', {
	settings = {
		json = {
			schemas = require('schemastore').json.schemas(),
			validate = { enable = true },
		},
	},
})

-- C#: OmniSharp Roslyn. Formatting is csharpier through conform.
vim.lsp.config('omnisharp', {
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

-- Starlark/Bazel: attach to both the bzl and starlark filetypes (see filetypes.lua)
vim.lsp.config('starpls', {
	filetypes = { 'bzl', 'starlark' },
})

-- Lua: aware of the Neovim runtime, so editing this config gets real completions
vim.lsp.config('lua_ls', {
	settings = {
		Lua = {
			runtime = { version = 'LuaJIT' },
			diagnostics = { globals = { 'vim' } },
			workspace = {
				checkThirdParty = false,
				library = { vim.env.VIMRUNTIME },
			},
			telemetry = { enable = false },
		},
	},
})
