-- =============================================================================
-- DIAGNOSTICS
-- How diagnostics are displayed, and the mappings for reading them
-- =============================================================================
-- [d / ]d (previous/next diagnostic) and <C-W>d (float) are Neovim defaults.

vim.diagnostic.config({
	virtual_text = { spacing = 2, source = 'if_many' },
	signs = true,
	underline = true,
	update_in_insert = false,
	severity_sort = true,
	float = { border = 'rounded', source = true },
})

local opts = { silent = true }
vim.keymap.set('n', '<space>e', vim.diagnostic.open_float, opts)
vim.keymap.set('n', '<space>q', vim.diagnostic.setloclist, opts)
