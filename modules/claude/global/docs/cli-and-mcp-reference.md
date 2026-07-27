# CLI And MCP Reference

Which command to reach for, and how the Context7 MCP server is wired. Read it when you need an entry point or need to know why an MCP call is unavailable.

Source of truth is `modules/claude/global/docs/cli-and-mcp-reference.md` in `~/.config/nixpkgs`. It deploys to `~/.claude/docs/cli-and-mcp-reference.md` on `hms` — edit the source, never the deployed copy.

## Reference Commands

For session analytics, run `claude-inspect --help`. For permission management, run `perm --help`.

- `tmux-restore`: Pick and restore a tmux-resurrect snapshot via fzf

## PR Comment Replies

See the `/review-pr-comments` skill for full workflow. For read-only fetching (listing, finding, filtering comments without replying), use `prc list <pr>` with optional flags (`--author`, `--bots-only`, `--inline-only`, `--resolved`, `--unresolved`, `--full`) — never `gh api` + `jq`.

## MCP Integration

**Context7 MCP** - Authoritative documentation lookup for libraries and frameworks. (Background sub-agent MCP constraints documented in global `CLAUDE.md` § Research Priority Order — that section stays in the always-injected file and is the authority on which tiers can reach an MCP server at all.)

- Tools: `mcp__context7__resolve-library-id` (find library), `mcp__context7__query-docs` (query documentation)
- When it fails: Fall back to WebSearch for official documentation
- Config: Automatically enabled if `CONTEXT7_API_KEY` set in `overconfig.nix`. To disable: Remove key, run `hms`.
