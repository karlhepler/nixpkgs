# Repo-level feature switches. Plain literals — imported directly by home.nix and
# overconfig.nix, so it must NOT depend on `config` (that would be infinite recursion
# in the `imports` list).
{
  # false = hms installs no Claude Code configuration at all: no claude/kanban/claudit/
  # agent-browser modules, no ~/.claude deploy, no MCP servers. Sources stay in the repo.
  claude.enable = false;
}
