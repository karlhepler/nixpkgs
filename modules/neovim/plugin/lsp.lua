-- =============================================================================
-- LSP: SERVERS, KEYMAPS AND COMPLETION
-- =============================================================================
-- Server commands, filetypes and root detection come from nvim-lspconfig; overrides
-- are in lsp-servers.lua. The server binaries are on Neovim's PATH
-- (programs.neovim.extraPackages).

vim.lsp.enable({
	'bashls',
	'gdscript',
	'gopls',
	'helm_ls',
	'jsonls',
	'lua_ls',
	'nil_ls',
	'omnisharp',
	'pyright',
	'rust_analyzer',
	'starpls',
	'ts_ls',
	'yamlls',
})

vim.o.completeopt = 'menu,menuone,noinsert,fuzzy,popup'

-- -------------------------------------------------------------------------
-- <C-n>: LSP completion with fallback to keyword completion
-- -------------------------------------------------------------------------
local function lsp_or_keyword_complete()
	-- Navigate the popup menu if it is already open
	if vim.fn.pumvisible() == 1 then
		return vim.api.nvim_replace_termcodes('<C-n>', true, true, true)
	end

	-- omnifunc is set to the LSP one when a server attaches; otherwise keywords
	if vim.bo.omnifunc ~= '' then
		return vim.api.nvim_replace_termcodes('<C-x><C-o>', true, true, true)
	end
	return vim.api.nvim_replace_termcodes('<C-n>', true, true, true)
end

vim.keymap.set('i', '<C-n>', lsp_or_keyword_complete, { expr = true })

-- Neovim 0.11 maps grn/gra/grr/gri/grt/grx. They would make the `gr` (references)
-- mapping below wait out 'timeoutlen' every time, and each has an equivalent here.
for _, lhs in ipairs({ 'grn', 'grr', 'gri', 'grt', 'grx' }) do
	pcall(vim.keymap.del, 'n', lhs)
end
pcall(vim.keymap.del, 'n', 'gra')
pcall(vim.keymap.del, 'x', 'gra')

-- -------------------------------------------------------------------------
-- GLOBAL LSP ATTACH HANDLER
-- Called when any LSP client attaches to a buffer
-- -------------------------------------------------------------------------
vim.api.nvim_create_autocmd('LspAttach', {
	group = vim.api.nvim_create_augroup('user_lsp_config', { clear = true }),
	callback = function(ev)
		local bufnr = ev.buf
		local client = vim.lsp.get_client_by_id(ev.data.client_id)

		-- Popup completion, triggered by the server's trigger characters
		if client and client:supports_method('textDocument/completion') then
			vim.lsp.completion.enable(true, client.id, bufnr, { autotrigger = true })
		end

		-- Buffer-local keymaps (K is Neovim's default hover mapping)
		local opts = { silent = true, buffer = bufnr }
		vim.keymap.set('n', 'gD', vim.lsp.buf.declaration, opts)
		vim.keymap.set('n', 'gd', vim.lsp.buf.definition, opts)
		vim.keymap.set('n', 'gi', vim.lsp.buf.implementation, opts)
		vim.keymap.set('n', '<C-k>', vim.lsp.buf.signature_help, opts)
		vim.keymap.set('n', '<space>wa', vim.lsp.buf.add_workspace_folder, opts)
		vim.keymap.set('n', '<space>wr', vim.lsp.buf.remove_workspace_folder, opts)
		vim.keymap.set('n', '<space>wl', function()
			print(vim.inspect(vim.lsp.buf.list_workspace_folders()))
		end, opts)
		vim.keymap.set('n', '<space>D', vim.lsp.buf.type_definition, opts)
		vim.keymap.set('n', '<space>rn', vim.lsp.buf.rename, opts)
		vim.keymap.set('n', '<space>ca', vim.lsp.buf.code_action, opts)
		vim.keymap.set('n', 'gr', vim.lsp.buf.references, opts)
		vim.keymap.set('n', '<space>f', function()
			require('conform').format({ async = false, lsp_format = 'fallback' })
		end, opts)
		vim.keymap.set({ 'n', 'v' }, '<C-b>', vim.lsp.buf.document_symbol, opts)
		vim.keymap.set('i', '<C-b>', function()
			vim.cmd.stopinsert()
			vim.lsp.buf.document_symbol()
		end, opts)
		vim.keymap.set('n', '<space>ih', function()
			vim.lsp.inlay_hint.enable(not vim.lsp.inlay_hint.is_enabled({ bufnr = bufnr }), { bufnr = bufnr })
		end, opts)
	end,
})
