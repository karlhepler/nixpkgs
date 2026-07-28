# Nixpkgs Repo Reference — Architecture, Deployment Map, And Nix Recipes

Lookup material for the `~/.config/nixpkgs` repository itself: where the repo's pieces live, where a deployed artifact came from, and which `nix` invocation to use. Read it when you need to trace a file in `~/.claude/` back to its source, or when you need a Nix command against this flake. Nothing here is a rule — the rules stay in project `CLAUDE.md`, which is auto-injected.

Source of truth is `modules/claude/global/docs/nixpkgs-repo-reference.md` in `~/.config/nixpkgs`. It deploys to `~/.claude/docs/nixpkgs-repo-reference.md` on `hms` — edit the source, never the deployed copy.

## Configuration Structure

Domain-centric module architecture - related functionality co-located.

**Core files:** flake.nix (inputs/outputs), home.nix (entry point), user.nix (identity), overconfig.nix (machine-specific).

For detailed architecture, see README.md and source files in modules/.

## Claude Code Integration

**Configuration deployment:**
- Global settings: `modules/claude/global/CLAUDE.md` → `~/.claude/CLAUDE.md`
- Agents: `modules/claude/global/agents/*.md` → `~/.claude/agents/`
- Hooks: notification-hook, complete-hook, csharp-format-hook (configured in `modules/claude/default.nix`)
- Commands: `~/.claude/TOOLS.md` auto-generated from shellapp metadata

**MCP integration:**
- Context7 MCP auto-configured if `CONTEXT7_API_KEY` set in overconfig.nix
- Config merged into `~/.claude.json` (preserves Claude's metadata)
- To disable: Remove `CONTEXT7_API_KEY`, run `hms`

**Analytics Dashboard (claudit):**
- Grafana-based dashboard for Claude Code usage analytics (user nickname: "claudit")
- Dashboard definition: `modules/claudit/dashboard.json`
- Metrics collection: `modules/claudit/claude-metrics-hook.py` (captures metrics via Claude Code metrics hook)
- Displays: Total cost (today/all-time), token breakdown (input/output/cache), cost by session, turn statistics by agent type, tool usage heat map (by tool and agent)
- Access via Grafana interface (configured in Home Manager)

## Declaring Script Dependencies

Worked Nix examples for declaring script dependencies. The routing rule (script-specific →
`runtimeInputs`; system-wide → `modules/packages.nix`) and the "never write fallbacks" rule live
in project `CLAUDE.md` § Scripting Principles — read that section for the why; this section is
reference only.

**For shellapps (preferred):**
Declare dependencies directly in the script's Nix definition using `runtimeInputs`:

```nix
myScript = pkgs.writeShellApplication {
  name = "my-command";
  runtimeInputs = [ pkgs.bat pkgs.jq pkgs.fd ];  # Script-specific dependencies
  text = ''
    # These commands are guaranteed to exist - no fallbacks needed
    bat file.txt
    echo '{"key":"value"}' | jq .
    fd pattern
  '';
};
```

**For Python scripts:**
```nix
myPythonScript = pkgs.writers.writePython3Bin "my-script" {
  libraries = [ pkgs.python3Packages.requests pkgs.python3Packages.jinja2 ];
} ''
  import requests  # Guaranteed to exist
  import jinja2    # No try/except needed
'';
```

**For system-wide tools:**
Add to `modules/packages.nix` only when the tool should be available globally (not script-specific):
```nix
home.packages = with pkgs; [
  bat  # Available system-wide in all shells
  fd
  ripgrep
];
```

## Nix Development

- `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`: Get hash for GitHub packages
- `nix flake update`: Update dependencies
- `nix flake check`: Partial validation only — does NOT catch flake8 errors. Use `hms` as the real gate.
- `nix flake metadata`: Show flake info
- `nix search nixpkgs <package>`: Search packages

**Implementation details:** See source files in `modules/` directories for specific configurations (theme, LSP, activation hooks, etc).
