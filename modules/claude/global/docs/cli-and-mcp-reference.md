# CLI And MCP Reference

Which command to reach for, and how the Context7 MCP server is wired. Read it when you need an entry point or need to know why an MCP call is unavailable.

Source of truth is `modules/claude/global/docs/cli-and-mcp-reference.md` in `~/.config/nixpkgs`. It deploys to `~/.claude/docs/cli-and-mcp-reference.md` on `hms` — edit the source, never the deployed copy.

## Reference Commands

For session analytics, run `claude-inspect --help`. For permission management, run `perm --help`.

- `tmux-restore`: Pick and restore a tmux-resurrect snapshot via fzf (shows sessions and window names in preview)

## PR Comment Replies

See the `/review-pr-comments` skill for full workflow. For read-only fetching (listing, finding, filtering comments without replying), use `prc list <pr>` with optional flags (`--author`, `--bots-only`, `--inline-only`, `--resolved`, `--unresolved`, `--full`) — never `gh api` + `jq`.

## MCP Integration

**Context7 MCP** - Authoritative documentation lookup for libraries and frameworks. (Background sub-agent MCP constraints documented in global `CLAUDE.md` § Research Priority Order — that section stays in the always-injected file and is the authority on which tiers can reach an MCP server at all.)

- Tools: `mcp__context7__resolve-library-id` (find library), `mcp__context7__query-docs` (query documentation)
- When it fails: Fall back to WebSearch for official documentation
- Config: Automatically enabled if `CONTEXT7_API_KEY` set in `overconfig.nix`. To disable: Remove key, run `hms`.

## Repository Command Reference (`~/.config/nixpkgs`)

Relocated from project `CLAUDE.md` § Quick Commands, which keeps only the `hms` family and the Git Workflow aliases inline. Everything below is a shellapp defined in `~/.config/nixpkgs` — to extend or modify one, edit its source in the named module and run `hms`. Do NOT edit deployed copies directly.

- `hm`: Change directory to `~/.config/nixpkgs` (zsh alias — not a standalone command)
- For deep `hms` semantics (failure modes, backup mechanism, `--purge` EXIT trap, git-invisible cycle): see `modules/system/HMS.md`.

### Claude Code Helpers

- `q "question"`: Quick Claude question (haiku model - fastest)
- `qq "question"`: Claude question (sonnet model - balanced)
- `qqq "question"`: Complex Claude question (opus model - most capable)
- `prc`: PR comment management tool (list, reply, resolve, collapse) — source: `modules/claude/prc.py`; see `/manage-pr-comments` skill for usage documentation
- `prr`: PR Review submission CLI using GitHub REST API; submits structured PR reviews with inline comments from a findings JSON file — source: `modules/claude/prr.py`

### Coordination CLIs

**`staff`, `sstaff`, and `crew` are the coordination-tier CLIs** — they launch or interact with Claude sessions that operate as coordinators. All three are shellapps defined in `modules/claude/` and deployed via `hms`.

- `staff`: Launch Claude Code with the Staff Engineer output style (loads `~/.claude/output-styles/staff-engineer.md`) — source: `modules/claude/staff.bash`
- `sstaff`: Launch Claude Code with the Senior Staff Engineer output style (loads `~/.claude/output-styles/senior-staff-engineer.md`, coordinator-of-coordinators tier) — source: `modules/claude/sstaff.bash`
- `crew`: Pane-based session orchestrator — subcommands: `list`, `tell`, `read`, `dismiss`, `find`, `create`, `status`, `project-path`, `resume`, `sessions` — source: `modules/claude/crew.py`; see `crew-cli` skill for full reference

### Analytics and Lifecycle CLIs

- `claude-inspect`: Session and usage analytics CLI — subcommands: `session`, `agents`, `tools`, `cards`, `compare`, `list`, `estimate`, `throughput`, `criterion-rejections` (`ac-rejections`) — source: `modules/claude/claude-inspect.py`
- `kanban`: Project coordination-board CLI — subcommands: `do`, `todo`, `start`, `defer`, `done`, `cancel`; criteria management; inspection commands like `list`, `show`, `status` — source: `modules/kanban/kanban.py`
- `perm`: Permission management (subcommands: `allow`, `always`, `cleanup`, `cleanup-stale`, `list`, `check` — plus `session-hook`/`hook` which are internal hook handlers; `purge` is user-only) — source: `modules/claude/perm.py`; mechanics documented in project `CLAUDE.md` § Reference Documentation

### Tmux Session Management

`tmux-restore` is listed under § Reference Commands above. The project-root copy of this entry carried one extra detail — that the fzf picker shows sessions and window names in its preview — which is folded into that entry rather than duplicated here.
