-- =============================================================================
-- AUTO-FORMAT FUNCTIONS
-- Language-agnostic formatting utilities
-- =============================================================================

-- -------------------------------------------------------------------------
-- ORGANIZE IMPORTS FUNCTION
-- Used by Go, TypeScript, and other languages that support code actions
-- Reference: https://github.com/golang/tools/blob/1f10767725e2be1265bef144f774dc1b59ead6dd/gopls/doc/vim.md#imports
-- Reference: https://github.com/typescript-language-server/typescript-language-server#code-actions-on-save
-- -------------------------------------------------------------------------
function OrgImports(code_action, wait_ms)
	local params = vim.lsp.util.make_range_params()
	params.context = { only = { code_action } }
	local result = vim.lsp.buf_request_sync(0, "textDocument/codeAction", params, wait_ms)

	for _, res in pairs(result or {}) do
		for _, r in pairs(res.result or {}) do
			if r.edit then
				vim.lsp.util.apply_workspace_edit(r.edit, "utf-8")
			else
				vim.lsp.buf.execute_command(r.command)
			end
		end
	end
end

-- Make globally accessible
_G.OrgImports = OrgImports
