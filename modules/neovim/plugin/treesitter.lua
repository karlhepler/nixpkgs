-- =============================================================================
-- TREESITTER
-- Highlighting and indentation from treesitter parsers
-- =============================================================================
-- nvim-treesitter 26.05 is a full, incompatible rewrite: highlighting and
-- indentation are no longer enabled by a `setup()` call and must be wired up
-- per-buffer.

vim.api.nvim_create_autocmd('FileType', {
	pattern = '*',
	callback = function(args)
		-- start() errors when no parser is installed for the filetype
		if not pcall(vim.treesitter.start, args.buf) then
			return
		end

		-- Only use the treesitter indentexpr where an indents query exists; without
		-- one it returns -1 and would override the filetype's own indent rules.
		local lang = vim.treesitter.language.get_lang(vim.bo[args.buf].filetype)
		if lang and vim.treesitter.query.get(lang, 'indents') then
			vim.bo[args.buf].indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
		end
	end,
})
