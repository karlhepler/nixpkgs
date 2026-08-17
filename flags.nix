# Repo-level feature switches. Plain literals — imported directly by home.nix and
# overconfig.nix, so it must NOT depend on `config` (that would be infinite recursion
# in the `imports` list).
{
  # false = hms installs none of the legacy Claude cluster: no claude/kanban/claudit/
  # agent-browser modules, no ~/.claude deploy, no MCP servers. Sources stay in the repo.
  # Does NOT gate modules/claude-code (see claudeCode.enable below).
  claude.enable = false;

  # false = hms manages no keys in ~/.claude/settings.json (model, effort, tui).
  claudeCode.enable = true;
}
