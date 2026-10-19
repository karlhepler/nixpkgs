-- =============================================================================
-- FORMAT ON SAVE
-- Organize imports (Go, TypeScript) through the language server, then format
-- =============================================================================
-- One BufWritePre handler does both, in that order, so imports are organized first
-- and the result is formatted. conform.nvim itself is set up in plugins.nix, without
-- its own format_on_save, so there is a single place deciding what happens on save.
-- Reference: https://github.com/golang/tools/blob/master/gopls/doc/vim.md#imports
-- Reference: https://github.com/typescript-language-server/typescript-language-server#code-actions-on-save

-- Only filetypes that were already formatted on save before conform.
--   imports:    code actions to run first, through the language server
--   lsp_format: what conform does when no listed formatter ran: fall back to the
--               language server ('fallback') or leave the buffer alone ('never')
local format_on_save = {
	go = { imports = { 'source.organizeImports' }, lsp_format = 'fallback' },
	typescript = {
		imports = { 'source.addMissingImports.ts', 'source.organizeImports.ts' },
		lsp_format = 'fallback',
	},
	typescriptreact = {
		imports = { 'source.addMissingImports.ts', 'source.organizeImports.ts' },
		lsp_format = 'fallback',
	},
	cs = { lsp_format = 'fallback' },
	rust = { lsp_format = 'never' },
	javascript = { lsp_format = 'never' },
	javascriptreact = { lsp_format = 'never' },
	json = { lsp_format = 'never' },
	css = { lsp_format = 'never' },
	scss = { lsp_format = 'never' },
	html = { lsp_format = 'never' },
	yaml = { lsp_format = 'never' },
	markdown = { lsp_format = 'never' },
}

local function organize_imports(bufnr, code_action, wait_ms)
	-- Whole-buffer range, so this does not depend on which window shows the buffer
	local params = {
		textDocument = vim.lsp.util.make_text_document_params(bufnr),
		range = {
			start = { line = 0, character = 0 },
			['end'] = { line = vim.api.nvim_buf_line_count(bufnr), character = 0 },
		},
		context = { only = { code_action }, diagnostics = {} },
	}

	for _, client in ipairs(vim.lsp.get_clients({ bufnr = bufnr, method = 'textDocument/codeAction' })) do
		local response = client:request_sync('textDocument/codeAction', params, wait_ms, bufnr)

		for _, action in ipairs(response and response.result or {}) do
			if action.edit then
				vim.lsp.util.apply_workspace_edit(action.edit, client.offset_encoding)
			elseif action.command then
				client:exec_cmd(action.command, { bufnr = bufnr })
			end
		end
	end
end

vim.api.nvim_create_autocmd('BufWritePre', {
	group = vim.api.nvim_create_augroup('format_on_save', { clear = true }),
	callback = function(args)
		local rule = format_on_save[vim.bo[args.buf].filetype]
		if not rule then
			return
		end

		for _, code_action in ipairs(rule.imports or {}) do
			organize_imports(args.buf, code_action, 1000)
		end
		require('conform').format({ bufnr = args.buf, timeout_ms = 2000, lsp_format = rule.lsp_format })
	end,
})

-- Format the current buffer on demand, for any filetype that has a formatter or a
-- language server that can format
vim.keymap.set('n', '<space>f', function()
	require('conform').format({ async = false, lsp_format = 'fallback' })
end, { desc = 'Format buffer' })
