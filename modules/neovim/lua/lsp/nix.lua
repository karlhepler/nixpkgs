-- =============================================================================
-- NIX LSP CONFIGURATION
-- Uses nil_ls language server
-- =============================================================================

-- Note: This was previously configured in the goto-preview plugin config
-- Moved here for consistency with other language configs

vim.lsp.config('nil_ls', {
	filetypes = { 'nix' },
	root_markers = { 'flake.nix', 'flake.lock', 'default.nix', '.git' }
})

vim.lsp.enable('nil_ls')
