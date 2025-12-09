-- =============================================================================
-- PYTHON LSP CONFIGURATION
-- =============================================================================

-- Configure Pyright language server
vim.lsp.config('pyright', {
	filetypes = { 'python' },
	root_markers = { 'pyproject.toml', 'setup.py', 'requirements.txt', 'Pipfile', '.git' }
})

vim.lsp.enable('pyright')
