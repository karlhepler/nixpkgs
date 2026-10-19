# Repo-level feature switches. Plain literals — imported directly by home.nix and
# overconfig.nix, so it must NOT depend on `config` (that would be infinite recursion
# in the `imports` list).
{
  # false = hms manages no Claude Code configuration: no keys in ~/.claude/settings.json
  # (model, effort, tui), no ~/.claude/CLAUDE.md or skills, and hms does not install
  # Claude Code.
  claudeCode.enable = true;
}
