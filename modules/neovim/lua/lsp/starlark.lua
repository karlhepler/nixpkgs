-- =============================================================================
-- STARLARK/BAZEL LSP CONFIGURATION
-- =============================================================================

-- -------------------------------------------------------------------------
-- FILETYPE CONFIGURATION
-- Must be set early for proper LSP activation
-- -------------------------------------------------------------------------
vim.filetype.add({
	extension = {
		star = 'starlark',
		bzl = 'starlark',
	},
	filename = {
		['BUILD'] = 'starlark',
		['BUILD.bazel'] = 'starlark',
		['MODULE.bazel'] = 'starlark',
		['WORKSPACE'] = 'starlark',
		['WORKSPACE.bazel'] = 'starlark',
		['Tiltfile'] = 'starlark',
	},
})

-- -------------------------------------------------------------------------
-- LSP CONFIGURATION
-- -------------------------------------------------------------------------
vim.lsp.config('starpls', {
	filetypes = { "bzl", "bazel", "star", "starlark" },
	root_markers = { 'BUILD', 'BUILD.bazel', 'WORKSPACE', 'WORKSPACE.bazel', '.git' }
})

vim.lsp.enable('starpls')
