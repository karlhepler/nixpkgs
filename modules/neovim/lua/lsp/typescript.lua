-- =============================================================================
-- TYPESCRIPT/JAVASCRIPT LSP CONFIGURATION
-- =============================================================================

-- Configure TypeScript/JavaScript language server
vim.lsp.config('ts_ls', {
	cmd = {
		"@typescriptLanguageServer@/bin/typescript-language-server",
		"--stdio"
	},
	filetypes = { 'typescript', 'javascript', 'typescriptreact', 'javascriptreact' },
	root_markers = { 'package.json', 'tsconfig.json', 'jsconfig.json', '.git' }
})

vim.lsp.enable('ts_ls')

-- -------------------------------------------------------------------------
-- AUTO-FORMAT ON SAVE
-- Format code and organize imports on file save
-- Reference: https://github.com/typescript-language-server/typescript-language-server#code-actions-on-save
-- -------------------------------------------------------------------------
vim.api.nvim_create_autocmd("BufWritePre", {
	pattern = { '*.ts', '*.tsx' },
	callback = function()
		vim.lsp.buf.format()
		OrgImports("source.addMissingImports.ts", 1000)
		OrgImports("source.organizeImports.ts", 1000)
	end,
	group = vim.api.nvim_create_augroup("lsp_document_format_ts", { clear = true }),
})
