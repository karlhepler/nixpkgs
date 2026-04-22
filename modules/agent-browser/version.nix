# Single source of truth for the agent-browser version.
# Imported by:
#   - modules/agent-browser/default.nix  (fetchurl URL + derivation name)
#   - modules/claude/default.nix         (npx invocation in claudeAgentBrowserSkill hook)
# When bumping the version, update the hash in modules/agent-browser/default.nix as well.
"0.26.0"
