-- =============================================================================
-- GLOBAL LSP CONFIGURATION
-- Global LSP keymaps, completion, and attach handler
-- =============================================================================

-- -------------------------------------------------------------------------
-- DIAGNOSTIC MAPPINGS (Global, work without LSP)
-- -------------------------------------------------------------------------
local opts = { noremap = true, silent = true }
vim.api.nvim_set_keymap('n', '<space>e', '<cmd>lua vim.diagnostic.open_float()<CR>', opts)
vim.api.nvim_set_keymap('n', '[d', '<cmd>lua vim.diagnostic.goto_prev()<CR>', opts)
vim.api.nvim_set_keymap('n', ']d', '<cmd>lua vim.diagnostic.goto_next()<CR>', opts)
vim.api.nvim_set_keymap('n', '<space>q', '<cmd>lua vim.diagnostic.setloclist()<CR>', opts)

-- -------------------------------------------------------------------------
-- LSP COMPLETION WITH FALLBACK
-- -------------------------------------------------------------------------
local function lsp_or_keyword_complete()
	-- Check if the popup menu is visible
	if vim.fn.pumvisible() == 1 then
		-- Use <C-n> to navigate the popup menu
		return vim.api.nvim_replace_termcodes('<C-n>', true, true, true)
	end

	-- Check if omnifunc is set and not empty (LSP completion)
	local omnifunc = vim.api.nvim_buf_get_option(0, 'omnifunc')
	if omnifunc ~= '' then
		-- Trigger omnifunc completion
		return vim.api.nvim_replace_termcodes('<C-x><C-o>', true, true, true)
	else
		-- If no omnifunc, fallback to normal <C-n> keyword completion
		return vim.api.nvim_replace_termcodes('<C-n>', true, true, true)
	end
end

-- Map <C-n> to use LSP completion with fallback to keyword completion
vim.keymap.set('i', '<C-n>', lsp_or_keyword_complete, { expr = true, noremap = true })

-- -------------------------------------------------------------------------
-- GLOBAL LSP ATTACH HANDLER
-- Automatically called when any LSP client attaches to a buffer
-- -------------------------------------------------------------------------
vim.api.nvim_create_autocmd('LspAttach', {
	group = vim.api.nvim_create_augroup('user_lsp_config', { clear = true }),
	callback = function(ev)
		local bufnr = ev.buf

		-- Enable omnifunc completion
		vim.bo[bufnr].omnifunc = 'v:lua.vim.lsp.omnifunc'

		-- Buffer-local keymaps
		local opts = { noremap = true, silent = true, buffer = bufnr }
		vim.keymap.set('n', 'gD', vim.lsp.buf.declaration, opts)
		vim.keymap.set('n', 'gd', vim.lsp.buf.definition, opts)
		vim.keymap.set('n', 'K', vim.lsp.buf.hover, opts)
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
			vim.lsp.buf.format({ async = false })
		end, opts)
	end,
})
