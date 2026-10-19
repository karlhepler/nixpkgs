-- =============================================================================
-- ORGANIZE IMPORTS ON SAVE
-- Go and TypeScript organize imports through a language server code action
-- =============================================================================
-- Runs after conform's BufWritePre formatting (registered earlier, from init.lua), so
-- imports are organized on already-formatted code.
-- Reference: https://github.com/golang/tools/blob/master/gopls/doc/vim.md#imports
-- Reference: https://github.com/typescript-language-server/typescript-language-server#code-actions-on-save

local function organize_imports(code_action, wait_ms)
	local bufnr = vim.api.nvim_get_current_buf()
	for _, client in ipairs(vim.lsp.get_clients({ bufnr = bufnr, method = 'textDocument/codeAction' })) do
		local params = vim.lsp.util.make_range_params(0, client.offset_encoding)
		params.context = { only = { code_action }, diagnostics = {} }
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

local group = vim.api.nvim_create_augroup('lsp_organize_imports', { clear = true })

vim.api.nvim_create_autocmd('BufWritePre', {
	group = group,
	pattern = '*.go',
	callback = function()
		organize_imports('source.organizeImports', 1000)
	end,
})

vim.api.nvim_create_autocmd('BufWritePre', {
	group = group,
	pattern = { '*.ts', '*.tsx' },
	callback = function()
		organize_imports('source.addMissingImports.ts', 1000)
		organize_imports('source.organizeImports.ts', 1000)
	end,
})
