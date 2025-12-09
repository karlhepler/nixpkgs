-- =============================================================================
-- BASH LSP CONFIGURATION
-- =============================================================================

-- Configure Bash language server
-- Uses FileType autocmd approach for compatibility
vim.api.nvim_create_autocmd('FileType', {
	pattern = 'sh',
	callback = function()
		vim.lsp.start({
			name = 'bash-language-server',
			cmd = { '@bashLanguageServer@/bin/bash-language-server', 'start' },
		})
	end,
})
