-- =============================================================================
-- GO LSP CONFIGURATION
-- =============================================================================

-- Configure Go language server (gopls)
vim.lsp.config('gopls', {
	filetypes = { 'go', 'gomod', 'gowork', 'gotmpl' },
	root_markers = { 'go.work', 'go.mod', '.git' }
})

vim.lsp.enable('gopls')

-- -------------------------------------------------------------------------
-- AUTO-FORMAT ON SAVE
-- Formats code and organizes imports
-- Reference: https://github.com/golang/tools/blob/master/gopls/doc/vim.md#imports
-- -------------------------------------------------------------------------
vim.api.nvim_create_autocmd("BufWritePre", {
	pattern = { '*.go' },
	callback = function()
		vim.lsp.buf.format()
		OrgImports("source.organizeImports", 1000)
	end,
	group = vim.api.nvim_create_augroup("lsp_document_format_go", { clear = true }),
})
