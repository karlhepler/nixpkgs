-- =============================================================================
-- FILETYPES
-- Extra filetype detection (C# and GDScript are detected by Neovim itself)
-- =============================================================================

-- Starlark/Bazel. Set early so the starpls language server attaches.
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
