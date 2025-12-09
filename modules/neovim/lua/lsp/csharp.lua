-- =============================================================================
-- C# LSP CONFIGURATION
-- Uses OmniSharp Roslyn for LSP + csharpier for formatting
-- =============================================================================

-- -------------------------------------------------------------------------
-- FILETYPE CONFIGURATION
-- -------------------------------------------------------------------------
vim.filetype.add({
	extension = {
		cs = 'cs',
	}
})

-- -------------------------------------------------------------------------
-- LSP CONFIGURATION (OmniSharp)
-- -------------------------------------------------------------------------
vim.lsp.config('omnisharp', {
	cmd = { "@omnisharpRoslyn@/bin/OmniSharp", "--languageserver", "--hostPID", tostring(vim.fn.getpid()) },
	filetypes = { 'cs' },
	root_markers = { "*.sln", "*.csproj", "omnisharp.json", "function.json", ".git" },
	settings = {
		FormattingOptions = {
			EnableEditorConfigSupport = true,
			OrganizeImports = true,
		},
		MsBuild = {
			LoadProjectsOnDemand = false,
		},
		RoslynExtensionsOptions = {
			EnableAnalyzersSupport = true,
			EnableImportCompletion = true,
		},
	},
})

vim.lsp.enable('omnisharp')

-- -------------------------------------------------------------------------
-- AUTO-FORMAT ON SAVE
-- LSP formats + csharpier for consistent code style
-- -------------------------------------------------------------------------
vim.api.nvim_create_autocmd("BufWritePre", {
	pattern = { '*.cs' },
	callback = function()
		vim.lsp.buf.format()
		-- Run csharpier for consistent formatting after LSP handles using statements
		local file = vim.fn.expand('%:p')
		vim.fn.system('csharpier "' .. file .. '"')
	end,
	group = vim.api.nvim_create_augroup("lsp_document_format_cs", { clear = true }),
})
