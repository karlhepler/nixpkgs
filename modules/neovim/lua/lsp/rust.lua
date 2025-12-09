-- =============================================================================
-- RUST LSP CONFIGURATION
-- Note: Formatting handled by vim-rust plugin (rustfmt_autosave in vimrc)
-- =============================================================================

-- Configure Rust Analyzer language server
vim.lsp.config('rust_analyzer', {
	filetypes = { 'rust' },
	root_markers = { 'Cargo.toml', 'Cargo.lock', '.git' },
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
})

vim.lsp.enable('rust_analyzer')
