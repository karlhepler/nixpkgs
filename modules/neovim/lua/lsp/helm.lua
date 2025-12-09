-- =============================================================================
-- HELM LSP CONFIGURATION
-- =============================================================================

-- Configure Helm language server
vim.lsp.config('helm_ls', {
	filetypes = { 'helm' },
	root_markers = { 'Chart.yaml', '.git' },
	settings = {
		['helm-ls'] = {
			yamlls = {
				path = 'yaml-language-server'
			}
		}
	}
})

vim.lsp.enable('helm_ls')
