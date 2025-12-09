-- =============================================================================
-- YAML LSP CONFIGURATION
-- =============================================================================

-- Configure YAML language server with Kubernetes schema support
vim.lsp.config('yamlls', {
	filetypes = { 'yaml', 'yaml.docker-compose' },
	root_markers = { '.git' },
	settings = {
		yaml = {
			schemas = {
				kubernetes = "*.yaml"
			},
		},
	},
})

vim.lsp.enable('yamlls')
