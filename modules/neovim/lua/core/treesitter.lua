-- =============================================================================
-- TREESITTER CONFIGURATION
-- Provides enhanced syntax highlighting and code understanding
-- =============================================================================
-- nvim-treesitter 26.05 is a full, incompatible rewrite: highlighting and
-- indentation are no longer enabled by a `setup()` call and must be wired up
-- per-buffer. `vim.treesitter.start()` errors when no parser is installed for
-- the buffer's filetype, so it's wrapped in pcall to no-op the same way the
-- old `configs.setup({ highlight = { enable = true } })` silently did.

vim.api.nvim_create_autocmd('FileType', {
	pattern = '*',
	callback = function()
		pcall(vim.treesitter.start)
		vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
	end,
})
