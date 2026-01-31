{ config, pkgs, lib, shellapps, user, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

  # Common hook library functions (inlined at build time)
  hookCommon = builtins.readFile ./claude-hook-common.bash;

  # Staff Engineer output style content (stripped of YAML frontmatter)
  staffEngineerContent = let
    raw = builtins.readFile ./global/output-styles/staff-engineer.md;
    # Split on "---" and take everything after the second occurrence
    parts = lib.splitString "---" raw;
    # parts[0] = "", parts[1] = frontmatter, parts[2...] = content
    contentParts = lib.drop 2 parts;
  in lib.concatStringsSep "---" contentParts;

  # Generate Ralph hat YAML with embedded Staff Engineer instructions
  staffEngineerHatYaml = pkgs.writeText "staff-engineer-hat.yml" ''
    # Ralph Hat Configuration: Staff Engineer
    # Generated from Home Manager - do not edit directly
    # Source: modules/claude/global/output-styles/staff-engineer.md
    #
    # Usage:
    #   cp $(staff-engineer-hat) ralph.yml
    #   ralph run --config $(staff-engineer-hat)

    event_loop:
      prompt_file: "PROMPT.md"
      completion_promise: "LOOP_COMPLETE"
      max_iterations: 50

    cli:
      backend: "claude"

    hats:
      staff-engineer:
        name: "Staff Engineer"
        description: "Wise, curious team lead who delegates to specialist skills"
        triggers: ["loop.start", "work.review_needed", "task.blocked"]
        publishes: ["research.needed", "implementation.needed", "work.approved", "LOOP_COMPLETE"]
        default_publishes: "work.approved"
        instructions: |
    ${lib.concatMapStringsSep "\n" (line: "      ${line}") (lib.splitString "\n" staffEngineerContent)}
  '';

in {
  # ============================================================================
  # Claude Code Configuration & Shell Applications
  # ============================================================================
  # Everything Claude-related: activation hooks + 7 claude shellapp definitions
  # ============================================================================

  # Export Ralph hat path for use in zsh.nix
  _module.args.staffEngineerHat = staffEngineerHatYaml;

  _module.args.claudeShellapps = rec {
    claude-notification-hook = shellApp {
      name = "claude-notification-hook";
      runtimeInputs = [ pkgs.python3 ];
      text = builtins.replaceStrings
        ["# @COMMON_FUNCTIONS@ - Will be replaced by Nix at build time"]
        [hookCommon]
        (builtins.readFile ./claude-notification-hook.bash);
      description = "Hook for Claude Code desktop notifications with tmux integration";
      sourceFile = "claude-notification-hook.bash";
    };
    claude-complete-hook = shellApp {
      name = "claude-complete-hook";
      runtimeInputs = [ ];
      text = builtins.replaceStrings
        ["# @COMMON_FUNCTIONS@ - Will be replaced by Nix at build time"]
        [hookCommon]
        (builtins.readFile ./claude-complete-hook.bash);
      description = "Hook for Claude Code completion events";
      sourceFile = "claude-complete-hook.bash";
    };
    claude-csharp-format-hook = shellApp {
      name = "claude-csharp-format-hook";
      runtimeInputs = [ pkgs.csharpier pkgs.python3 ];
      text = builtins.readFile ./claude-csharp-format-hook.bash;
      description = "Hook for automatic C# code formatting with csharpier";
      sourceFile = "claude-csharp-format-hook.bash";
    };

    # Claude question assistants
    claude-ask = shellApp {
      name = "claude-ask";
      runtimeInputs = [ ];
      text = builtins.replaceStrings
        ["@USER_NAME@"]
        [user.name]
        (builtins.readFile ./claude-ask.bash);
      description = "Ask Claude quick questions without interactive TUI";
      sourceFile = "claude-ask.bash";
    };

    q = shellApp {
      name = "q";
      runtimeInputs = [ ];
      text = ''
        ${claude-ask}/bin/claude-ask haiku "$@"
      '';
      description = "Quick Claude question using haiku model (fastest)";
      sourceFile = "default.nix";
    };

    qq = shellApp {
      name = "qq";
      runtimeInputs = [ ];
      text = ''
        ${claude-ask}/bin/claude-ask sonnet "$@"
      '';
      description = "Claude question using sonnet model (balanced)";
      sourceFile = "default.nix";
    };

    qqq = shellApp {
      name = "qqq";
      runtimeInputs = [ ];
      text = ''
        ${claude-ask}/bin/claude-ask opus "$@"
      '';
      description = "Complex Claude question using opus model (most capable)";
      sourceFile = "default.nix";
    };
  };

  home.activation = {
    # claudeSettings
    # Purpose: Creates Claude Code settings.json with configured hooks
    # Why: Integrates Claude Code with notification, completion, and formatting hooks
    # When: After writeBoundary (after files are written to disk)
    # Dependencies: Requires shellapps for hook commands
    claudeSettings = let
      settingsContent = {
        # Auto-allow kanban CLI commands without prompting
        permissions = {
          allow = [
            "Bash(kanban *)"
          ];
        };
        hooks = {
          Notification = [{
            hooks = [{
              type = "command";
              command = "${shellapps.claude-notification-hook}/bin/claude-notification-hook";
            }];
          }];
          Stop = [{
            hooks = [{
              type = "command";
              command = "${shellapps.claude-complete-hook}/bin/claude-complete-hook";
            }];
          }];
          PostToolUse = [{
            matcher = "Edit|MultiEdit|Write";
            hooks = [{
              type = "command";
              command = "${shellapps.claude-csharp-format-hook}/bin/claude-csharp-format-hook";
            }];
          }];
        };
      };
      claudeSettingsJson = pkgs.runCommand "claude-settings.json" {} ''
        echo '${builtins.toJSON settingsContent}' | ${pkgs.jq}/bin/jq . > $out
      '';
    in lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD mkdir -p ~/.claude
      $DRY_RUN_CMD ln -sf ${claudeSettingsJson} ~/.claude/settings.json
    '';

    # claudeGlobal
    # Purpose: Deploys all Claude Code configuration files to ~/.claude
    # Why: Provides global settings, tool documentation, and custom skills for Claude Code
    # When: After writeBoundary (after files are written to disk)
    # Note: Source structure in global/ mirrors destination structure in ~/.claude/
    # Skills: facilitator, researcher, scribe, frontend-engineer, backend-engineer, fullstack-engineer
    claudeGlobal = let
      claudeGlobalDir = ./global;

      # Generate TOOLS.md from package metadata
      generateToolsMarkdown = import ./generate-tools-md.nix { inherit lib; };

      toolsMarkdown = pkgs.runCommand "TOOLS.md" {} ''
        cat > $out << 'EOF'
${generateToolsMarkdown {
  packages = config.home.packages;
}}
EOF
      '';
    in lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      # Copy all global configuration (mirrors global/ -> ~/.claude/ structure)
      $DRY_RUN_CMD mkdir -p ~/.claude
      $DRY_RUN_CMD cp -rf ${claudeGlobalDir}/* ~/.claude/

      # Add generated TOOLS.md (force overwrite read-only file from previous build)
      $DRY_RUN_CMD cp -f ${toolsMarkdown} ~/.claude/TOOLS.md
    '';
  };
}
