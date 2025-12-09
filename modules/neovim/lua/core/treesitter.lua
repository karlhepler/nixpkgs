-- =============================================================================
-- TREESITTER CONFIGURATION
-- Provides enhanced syntax highlighting and code understanding
-- =============================================================================

local treesitter_configs = require('nvim-treesitter.configs')

treesitter_configs.setup({
	highlight = { enable = true },
	incremental_selection = { enable = true },
	indent = { enable = true },
})
