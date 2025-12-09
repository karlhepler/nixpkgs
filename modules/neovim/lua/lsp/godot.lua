-- =============================================================================
-- GODOT/GDSCRIPT LSP CONFIGURATION
-- Connects to Godot editor's built-in LSP server
-- =============================================================================

-- -------------------------------------------------------------------------
-- FILETYPE CONFIGURATION
-- -------------------------------------------------------------------------
vim.filetype.add({
	extension = {
		gd = 'gdscript',
	},
})

-- Fallback autocmd for stubborn cases
vim.api.nvim_create_autocmd({ "BufRead", "BufNewFile" }, {
	pattern = { "*.gd" },
	command = "set filetype=gdscript",
})

-- -------------------------------------------------------------------------
-- LSP CONFIGURATION
-- -------------------------------------------------------------------------
local godotLspGroup = vim.api.nvim_create_augroup("GodotLspConfig", { clear = true })

vim.api.nvim_create_autocmd("FileType", {
	group = godotLspGroup,
	pattern = "gdscript",
	callback = function()
		-- Check if already running to prevent multiple instances
		local clients = vim.lsp.get_active_clients({ name = "Godot", bufnr = 0 })
		if #clients > 0 then
			return
		end

		local port = os.getenv('GDScript_Port') or '6005'

		-- Attempt connection
		local ok, cmd_connect = pcall(vim.lsp.rpc.connect, '127.0.0.1', port)
		if not ok or not cmd_connect then
			vim.notify(
				"Failed to connect to Godot LSP on port " .. port .. ". Is Godot editor running with LSP enabled?",
				vim.log.levels.WARN
			)
			return
		end

		-- Determine root directory
		local root_dir_path = vim.fs.find(
			{ 'project.godot', '.git' },
			{ upward = true, stop = vim.loop.os_homedir(), type = 'file' }
		)
		local root_dir = nil
		if root_dir_path and #root_dir_path > 0 then
			root_dir = vim.fs.dirname(root_dir_path[1])
		end

		if not root_dir then
			vim.notify("Could not find 'project.godot' or '.git' to determine project root.", vim.log.levels.INFO)
		end

		-- Start LSP client
		vim.lsp.start({
			name = 'Godot',
			cmd = cmd_connect,
			filetypes = { 'gdscript' },
			root_dir = root_dir,
		})
	end,
})
