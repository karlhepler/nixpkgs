{ config, pkgs, lib, shellapps, user, context7ApiKey ? null, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

  # Common hook library functions (inlined at build time)
  hookCommon = builtins.readFile ./claude-hook-common.bash;

  # Ralph Coordinator output style content (stripped of YAML frontmatter)
  ralphCoordinatorContent = let
    raw = builtins.readFile ./global/output-styles/ralph-coordinator.md;
    # Split on "---" and take everything after the second occurrence
    parts = lib.splitString "---" raw;
    # parts[0] = "", parts[1] = frontmatter, parts[2...] = content
    contentParts = lib.drop 2 parts;
  in lib.concatStringsSep "---" contentParts;

  # Generate Ralph hat YAML with embedded Ralph Coordinator instructions
  ralphCoordinatorHatYaml = pkgs.writeText "ralph-coordinator-hat.yml" ''
    # Ralph Hat Configuration: Ralph Coordinator
    # Generated from Home Manager - do not edit directly
    # Source: modules/claude/global/output-styles/ralph-coordinator.md
    #
    # Usage:
    #   cp $(ralph-coordinator-hat) ralph.yml
    #   ralph run --config $(ralph-coordinator-hat)

    event_loop:
      prompt_file: "PROMPT.md"
      completion_promise: "LOOP_COMPLETE"
      max_iterations: 50

    cli:
      backend: "claude"

    hats:
      ralph-coordinator:
        name: "Ralph Coordinator"
        description: "Sequential coordinator who executes work directly via Skill tool"
        triggers: ["loop.start", "work.review_needed", "task.blocked"]
        publishes: ["research.needed", "implementation.needed", "work.approved", "LOOP_COMPLETE"]
        default_publishes: "work.approved"
        instructions: |
    ${lib.concatMapStringsSep "\n" (line: "      ${line}") (lib.splitString "\n" ralphCoordinatorContent)}
  '';

  # Python environment for smithers with required packages
  smithersPython = pkgs.python3.withPackages (ps: with ps; [
    wcwidth   # Unicode display width calculation for terminal formatting
    requests  # HTTP requests for Slack webhook posting
  ]);

  # Burns Python CLI (Ralph with Ralph Coordinator output style)
  burnsScript = pkgs.writers.writePython3Bin "burns" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];  # Ignore shebang, line length, line breaks
  } (builtins.replaceStrings
    ["RALPH_COORDINATOR_HAT_YAML"]
    ["${ralphCoordinatorHatYaml}"]
    (builtins.readFile ./burns.py));

  # Smithers Python CLI (token-efficient PR watcher)
  smithersScript = pkgs.writeScriptBin "smithers" ''
    #!${smithersPython}/bin/python3
    ${builtins.readFile ./smithers.py}
  '';

  # PRC Python CLI (PR comment management using GraphQL)
  prcScript = pkgs.writers.writePython3Bin "prc" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];  # Ignore shebang, line length, line breaks
  } (builtins.readFile ./prc.py);

in {
  # ============================================================================
  # Claude Code Configuration & Shell Applications
  # ============================================================================
  # Everything Claude-related: activation hooks + 8 claude shellapp definitions
  # ============================================================================

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
    claude-session-start-hook = shellApp {
      name = "claude-session-start-hook";
      runtimeInputs = [ ];
      text = ''
        kanban session-hook
      '';
      description = "Hook for Claude Code session start - injects kanban session identity";
      sourceFile = "default.nix";
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

    staff = shellApp {
      name = "staff";
      runtimeInputs = [ ];
      text = builtins.readFile ./staff.bash;
      description = "Launch Claude Code with Staff Engineer output style (date-aware)";
      sourceFile = "staff.bash";
    };

    burns = burnsScript // {
      meta = {
        description = "Run Ralph Orchestrator with Ralph Coordinator output style (accepts prompt string or file path)";
        mainProgram = "burns";
        homepage = "${builtins.toString ./.}/burns.py";
      };
    };

    smithers = smithersScript // {
      meta = {
        description = "Token-efficient PR watcher (polls CI, invokes Ralph only when work needed)";
        mainProgram = "smithers";
        homepage = "${builtins.toString ./.}/smithers.py";
      };
    };

    prc = prcScript // {
      meta = {
        description = "PR comment management using GraphQL (list, reply, resolve, collapse)";
        mainProgram = "prc";
        homepage = "${builtins.toString ./.}/prc.py";
      };
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
        # No default output style - contexts choose explicitly
        # Use `staff` command to launch Claude with Staff Engineer output style

        # Auto-approve read-only commands (subagents can't prompt for approval)
        # Research: /private/tmp/claude-501/-Users-karlhepler--config-nixpkgs/tasks/ac5f27d.output
        # Total: ~100 command patterns across categories

        # ============================================================================
        # Permission Pattern Syntax
        # ============================================================================
        #
        # Claude Code uses pattern matching to control which commands can be executed.
        # Patterns use the format: Tool(pattern) where Tool is the tool name and
        # pattern matches against the command and its arguments.
        #
        # Pattern Syntax:
        #   Tool(command)           - Exact command match (no arguments)
        #   Tool(command *)         - Command with any arguments
        #   Tool(command -flag *)   - Specific flag with any arguments
        #   Tool(*)                 - Any command for this tool (use sparingly)
        #
        # Wildcard Rules:
        #   *  - Matches any characters (including spaces, paths, parameters)
        #   ** - Not used (single * is sufficient)
        #
        # Common Examples:
        #   Bash(git status)          - Only "git status" with no arguments
        #   Bash(git status *)        - "git status" with any arguments
        #   Bash(git *)               - Any git command
        #   Bash(kanban *)            - Any kanban command
        #   Bash(gh api /repos/*)     - gh api for any repo path
        #   Read(*)                   - Read any file (no restrictions)
        #   Edit(*.md)                - Edit only markdown files (extension match)
        #
        # Security Notes:
        #   - Be specific: Use "command *" instead of "*" when possible
        #   - Test patterns: Overly broad patterns can allow unintended commands
        #   - Block list overrides: Blocked patterns take precedence over allowed
        #
        # Pattern Matching Behavior:
        #   - Patterns are matched in order (first match wins)
        #   - Block list is checked before allow list
        #   - If no pattern matches, command is denied by default
        #
        # Debugging:
        #   - If a command is unexpectedly blocked, check both allow and block lists
        #   - Add specific patterns before broad wildcards for fine-grained control
        #
        # ============================================================================

        permissions = {
          allow = [
            # Kanban CLI (agent coordination)
            "Bash(kanban)"
            "Bash(kanban *)"

            # Claude Code Read-Only Tools (no parameters needed - approve all uses)
            "Read"
            "Glob"
            "Grep"
            "WebSearch"
            "WebFetch"
            "TaskOutput"
            "Task(subagent_type=Explore)"
            "Task(subagent_type=explore)"

            # /tmp directory - Auto-approve all file operations (safe scratch space)
            "Write(/tmp/*)"
            "Edit(/tmp/*)"

            # Context7 MCP - Auto-approve all documentation queries
            "mcp__context7__resolve-library-id"
            "mcp__context7__query-docs"

            # Category A - Purely Read-Only Tools (approve all uses)
            "Bash(rg *)"
            "Bash(fd *)"
            "Bash(bat *)"
            "Bash(htop *)"
            "Bash(less *)"
            "Bash(grep *)"
            "Bash(head *)"
            "Bash(tail *)"
            "Bash(cat *)"
            "Bash(tree *)"
            "Bash(ls *)"
            "Bash(ll *)"
            "Bash(difftastic *)"
            "Bash(shellcheck *)"
            "Bash(jq *)"
            "Bash(yq *)"
            "Bash(codeowners *)"

            # Category B - Git Read-Only Commands
            "Bash(git status *)"
            "Bash(git log *)"
            "Bash(git show *)"
            "Bash(git diff *)"
            "Bash(git blame *)"
            "Bash(git who *)"
            "Bash(git branch)"
            "Bash(git branch -l *)"
            "Bash(git branch --list *)"
            "Bash(git ls-files *)"
            "Bash(git ls-remote *)"
            "Bash(git remote)"
            "Bash(git remote -v)"
            "Bash(git remote show *)"
            "Bash(git config --get *)"
            "Bash(git config --list *)"
            "Bash(git rev-parse *)"
            "Bash(git describe *)"
            "Bash(git reflog *)"
            "Bash(git tag)"
            "Bash(git tag -l *)"
            "Bash(git tag --list *)"
            "Bash(git worktree list *)"
            "Bash(git stash list *)"
            "Bash(git stash show *)"
            "Bash(git grep *)"
            "Bash(git for-each-ref *)"
            "Bash(git difft *)"
            "Bash(git logt *)"
            "Bash(git showt *)"

            # Category B - GitHub CLI Read-Only Commands
            "Bash(gh pr view *)"
            "Bash(gh pr list *)"
            "Bash(gh pr status *)"
            "Bash(gh pr checks *)"
            "Bash(gh pr diff *)"
            "Bash(gh issue view *)"
            "Bash(gh issue list *)"
            "Bash(gh issue status *)"
            "Bash(gh repo view *)"
            "Bash(gh repo list *)"
            "Bash(gh run view *)"
            "Bash(gh run list *)"
            "Bash(gh release view *)"
            "Bash(gh release list *)"
            "Bash(gh gist view *)"
            "Bash(gh gist list *)"

            # Category B - GitHub API Read-Only Commands
            # Note: gh api defaults to GET when no method specified
            "Bash(gh api -X GET *)"
            "Bash(gh api --method GET *)"
            "Bash(gh api -XGET *)"
            "Bash(gh api --method=GET *)"
            # Allow common read-only API patterns (default method is GET)
            "Bash(gh api /repos/*)"
            "Bash(gh api /orgs/*)"
            "Bash(gh api /users/*)"
            "Bash(gh api /user/*)"
            "Bash(gh api /gists/*)"
            "Bash(gh api /search/*)"
            "Bash(gh api /rate_limit*)"
            "Bash(gh api /meta*)"

            # Category B - kubectl Read-Only Commands
            "Bash(kubectl get *)"
            "Bash(kubectl describe *)"
            "Bash(kubectl logs *)"
            "Bash(kubectl explain *)"
            "Bash(kubectl version *)"
            "Bash(kubectl cluster-info *)"
            "Bash(kubectl top *)"
            "Bash(kubectl api-resources *)"
            "Bash(kubectl api-versions *)"
            "Bash(kubectl config view *)"
            "Bash(kubectl config get-contexts *)"
            "Bash(kubectl config current-context *)"
            "Bash(kubectl config get-clusters *)"
            "Bash(kubectl config get-users *)"
            "Bash(kubectl diff *)"
            "Bash(kubectl auth can-i *)"
            "Bash(kubectl rollout status *)"
            "Bash(kubectl rollout history *)"
            "Bash(kubectl wait *)"

            # Category B - Other Tools
            "Bash(kubectx)"
            "Bash(kubens)"
            "Bash(npm list *)"
            "Bash(npm view *)"
            "Bash(npm search *)"
            "Bash(npm outdated *)"
            "Bash(npm ls *)"
            "Bash(yarn list *)"
            "Bash(yarn info *)"
            "Bash(tmux ls *)"
            "Bash(tmux list-sessions *)"
            "Bash(tmux list-windows *)"
            "Bash(tmux list-panes *)"
            "Bash(tmux display-message *)"
            "Bash(tmux show-options *)"
            "Bash(tmux show-environment *)"
          ];

          # ============================================================================
          # Permission Block List
          # ============================================================================
          #
          # Commands in the block list are explicitly denied, even if they match an
          # allow pattern. Block list takes precedence over allow list.
          #
          # Use blocking for:
          #   - Dangerous operations (rm -rf, destructive git commands)
          #   - Commands that should require explicit user approval
          #   - Operations that bypass intended workflows
          #
          # ============================================================================

          # Block kubectl write/destructive commands (admin permissions - never auto-approve)
          block = [
            # Kanban destructive commands (always prompt for confirmation)
            "Bash(kanban clean)"
            "Bash(kanban clean *)"

            "Bash(kubectl apply *)"
            "Bash(kubectl create *)"
            "Bash(kubectl delete *)"
            "Bash(kubectl edit *)"
            "Bash(kubectl patch *)"
            "Bash(kubectl replace *)"
            "Bash(kubectl scale *)"
            "Bash(kubectl set *)"
            "Bash(kubectl expose *)"
            "Bash(kubectl run *)"
            "Bash(kubectl exec *)"
            "Bash(kubectl cp *)"
            "Bash(kubectl drain *)"
            "Bash(kubectl cordon *)"
            "Bash(kubectl uncordon *)"
            "Bash(kubectl taint *)"
            "Bash(kubectl label *)"
            "Bash(kubectl annotate *)"
            "Bash(kubectl rollout restart *)"
            "Bash(kubectl rollout undo *)"
            "Bash(kubectl rollout resume *)"
            "Bash(kubectl rollout pause *)"
            "Bash(kubectl autoscale *)"
            "Bash(kubectl debug *)"
            "Bash(kubectl attach *)"
            "Bash(kubectl port-forward *)"
            "Bash(kubectl proxy *)"
            "Bash(kubectl config set *)"
            "Bash(kubectl config set-context *)"
            "Bash(kubectl config set-cluster *)"
            "Bash(kubectl config set-credentials *)"
            "Bash(kubectl config use-context *)"
            "Bash(kubectl config delete-context *)"
            "Bash(kubectl config delete-cluster *)"
            "Bash(kubectl config unset *)"
            "Bash(kubectl certificate approve *)"
            "Bash(kubectl certificate deny *)"
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
          SessionStart = [{
            hooks = [{
              type = "command";
              command = "${shellapps.claude-session-start-hook}/bin/claude-session-start-hook";
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

      # Ensure all subdirectories exist (in case cp didn't create them)
      $DRY_RUN_CMD mkdir -p ~/.claude/commands ~/.claude/output-styles ~/.claude/docs ~/.claude/agents

      # Make copied files writable (Nix store files are read-only by default)
      $DRY_RUN_CMD chmod -R u+w ~/.claude/commands ~/.claude/output-styles ~/.claude/docs ~/.claude/agents

      # Add generated TOOLS.md (force overwrite read-only file from previous build)
      $DRY_RUN_CMD cp -f ${toolsMarkdown} ~/.claude/TOOLS.md
    '';

    # claudeMcp
    # Purpose: Merges Context7 MCP configuration into ~/.claude.json
    # Why: Enables Context7 MCP integration while preserving Claude's metadata
    # When: After writeBoundary (after files are written to disk)
    # Note: Only runs if context7ApiKey is provided (not null)
    #       Merges config into existing file instead of overwriting
    claudeMcp = lib.mkIf (context7ApiKey != null) (
    lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      # Create ~/.claude.json if it doesn't exist
      if [[ ! -f ~/.claude.json ]]; then
        $DRY_RUN_CMD echo '{}' > ~/.claude.json
      fi

      # Merge MCP configuration into existing file (preserving all other fields)
      # Note: Claude Code supports ''${VARIABLE_NAME} syntax for runtime env var expansion
      # See: https://github.com/anthropics/claude-code/issues/2065
      $DRY_RUN_CMD ${pkgs.jq}/bin/jq '.mcpServers.context7 = {
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "env": {
          "CONTEXT7_API_KEY": "''${CONTEXT7_API_KEY}"
        }
      }' ~/.claude.json > ~/.claude.json.tmp

      # Replace original file with merged version
      $DRY_RUN_CMD mv ~/.claude.json.tmp ~/.claude.json
      $DRY_RUN_CMD chmod 600 ~/.claude.json
    '');
  };
}
