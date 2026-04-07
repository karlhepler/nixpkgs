{ config, pkgs, lib, shellapps, user, context7ApiKey ? null, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

  # Common hook library functions (inlined at build time)
  hookCommon = builtins.readFile ./claude-hook-common.bash;

  # Strip YAML frontmatter from a markdown file
  stripFrontmatter = raw:
    let
      parts = lib.splitString "---" raw;
      contentParts = lib.drop 2 parts;
    in lib.concatStringsSep "---" contentParts;

  # Indent each non-empty line of text by N spaces (for YAML embedding)
  # Empty lines are preserved as-is (no trailing spaces)
  indentLines = spaces: text:
    let
      prefix = lib.concatStrings (lib.genList (_: " ") spaces);
    in
    lib.concatMapStringsSep "\n"
      (line: if line == "" then "" else "${prefix}${line}")
      (lib.splitString "\n" text);

  # Read a hat template file and substitute INSTRUCTIONS_PLACEHOLDER with
  # the provided instructions content (already indented).
  processTemplate = templateFile: instructionsContent:
    builtins.replaceStrings
      [ "INSTRUCTIONS_PLACEHOLDER" ]
      [ instructionsContent ]
      (builtins.readFile templateFile);

  # Trim leading and trailing empty lines from a string
  trimLines = s:
    let
      lines = lib.splitString "\n" s;
      dropLeadingEmpty = lst:
        if lst == [] || builtins.head lst != ""
        then lst
        else dropLeadingEmpty (builtins.tail lst);
      dropTrailingEmpty = lst: lib.reverseList (dropLeadingEmpty (lib.reverseList lst));
      trimmed = dropTrailingEmpty (dropLeadingEmpty lines);
    in lib.concatStringsSep "\n" trimmed;

  # Process a skill file: strip frontmatter, replace $ARGUMENTS, trim empty lines, then indent
  # to 10 spaces for YAML block scalar embedding inside <behavior> tags.
  processSkillFile = filePath:
    let
      raw = builtins.readFile filePath;
      body = stripFrontmatter raw;
      withArgs = builtins.replaceStrings
        [ "$ARGUMENTS" ]
        [ "You receive your task from the event payload that triggered you and the session context.\nComplete the work described, then emit your completion event." ]
        body;
      trimmed = trimLines withArgs;
    in indentLines 10 trimmed;

  # Assemble all hat YAML blocks from templates
  hatYaml = lib.concatStrings [
    (builtins.readFile ./global/hats/monty-burns.yml.tmpl)
    (processTemplate ./global/hats/swe-backend.yml.tmpl  (processSkillFile ./global/commands/swe-backend.md))
    (processTemplate ./global/hats/swe-frontend.yml.tmpl (processSkillFile ./global/commands/swe-frontend.md))
    (processTemplate ./global/hats/swe-fullstack.yml.tmpl (processSkillFile ./global/commands/swe-fullstack.md))
    (processTemplate ./global/hats/swe-devex.yml.tmpl    (processSkillFile ./global/commands/swe-devex.md))
    (processTemplate ./global/hats/swe-infra.yml.tmpl    (processSkillFile ./global/commands/swe-infra.md))
    (processTemplate ./global/hats/swe-security.yml.tmpl (processSkillFile ./global/commands/swe-security.md))
    (processTemplate ./global/hats/swe-sre.yml.tmpl      (processSkillFile ./global/commands/swe-sre.md))
    (processTemplate ./global/hats/researcher.yml.tmpl   (processSkillFile ./global/commands/researcher.md))
  ];

  # Generate multi-hat Ralph YAML with Monty Burns coordinator + 8 specialists
  # Use builtins.readFile + replaceStrings to avoid Nix indented string indentation stripping,
  # which would misalign top-level YAML keys (event_loop:, cli:, hats:) if the string is
  # indented within the Nix expression.
  montyBurnsHatYaml = pkgs.writeText "monty-burns-hat.yml" (
    builtins.replaceStrings
      [ "HATS_PLACEHOLDER" ]
      [ hatYaml ]
      (builtins.readFile ./global/hats/wrapper.yml.tmpl)
  );

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
    ["${montyBurnsHatYaml}"]
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

  # PRR Python CLI (PR review submission using REST API)
  prrScript = pkgs.writers.writePython3Bin "prr" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];  # Ignore shebang, line length, line breaks
  } (builtins.readFile ./prr.py);

  # Kanban PreToolUse(Agent) hook — injects card content into sub-agent prompts
  kanbanPretoolHookScript = pkgs.writers.writePython3Bin "kanban-pretool-hook" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];  # Ignore shebang, line length, line breaks
  } (builtins.readFile ./kanban-pretool-hook.py);

  # Kanban SubagentStop hook — dual-loop AC review system
  kanbanSubagentStopHookScript = pkgs.writers.writePython3Bin "kanban-subagent-stop-hook" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];  # Ignore shebang, line length, line breaks
  } (builtins.readFile ./kanban-subagent-stop-hook.py);

  # Claude Inspect — CLI for introspecting Claude session metrics
  claudeInspectScript = pkgs.writers.writePython3Bin "claude-inspect" {
    flakeIgnore = [ "E226" "E265" "E501" "F541" "W503" "W504" ];
  } (builtins.readFile ./claude-inspect.py);

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
      runtimeInputs = [];
      text = builtins.readFile ./claude-complete-hook.bash;
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
    claude-kanban-transition-hook = shellApp {
      name = "claude-kanban-transition-hook";
      runtimeInputs = [ pkgs.python3 ];
      text = builtins.replaceStrings
        ["# @COMMON_FUNCTIONS@ - Will be replaced by Nix at build time"]
        [hookCommon]
        (builtins.readFile ./claude-kanban-transition-hook.bash);
      description = "PostToolUse(Bash) hook that sends macOS notifications on kanban state transitions (start, defer, cancel)";
      sourceFile = "claude-kanban-transition-hook.bash";
    };
    claude-session-start-hook = let
      extractKanbanName = pkgs.writeText "extract-kanban-name.py" ''
        import re, sys
        text = sys.stdin.read()
        m = re.search(r"Your kanban session is: ([a-z0-9-]+)", text)
        print(m.group(1) if m else "")
      '';
      findOrphanedCards = pkgs.writeText "find-orphaned-cards.py" ''
        import sys, xml.etree.ElementTree as ET
        xml_text = sys.stdin.read()
        if not xml_text.strip():
            sys.exit(0)
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            sys.exit(0)
        orphans = []
        board_session = root.get("session", "unknown")
        for group in root:
            group_session = board_session if group.tag == "mine" else None
            for card in group.iter("c"):
                status = card.get("s", "")
                if status not in ("doing", "review"):
                    continue
                num = card.get("n", "?")
                session = card.get("ses", group_session) if group_session is None else group_session
                action_el = card.find("a")
                action = (action_el.text or "").strip() if action_el is not None else ""
                truncated = action[:50] + "..." if len(action) > 50 else action
                orphans.append((num, status, session, truncated))
        if orphans:
            print("Warning: Orphaned cards detected:")
            for num, status, session, action in orphans:
                print(f"  - #{num} ({status}, session: {session}) -- {action}")
            print("Use kanban cancel or kanban redo to resolve.")
      '';
      toResultJson = pkgs.writeText "to-result-json.py" ''
        import json, sys
        content = sys.stdin.read()
        print(json.dumps({"result": content}))
      '';
    in shellApp {
      name = "claude-session-start-hook";
      runtimeInputs = [ pkgs.python3 ];
      text = ''
        # System agents (e.g. ac-reviewer) set KANBAN_AGENT to signal they do not
        # need kanban session registration, perm setup, board state injection, or
        # TOOLS.md context. Exit immediately with a minimal valid response.
        if [ "''${KANBAN_AGENT:-}" = "ac-reviewer" ]; then
          printf '{"result":""}'
          exit 0
        fi
        json=$(cat)
        mkdir -p .scratchpad
        kanban_output=$(echo "$json" | kanban session-hook)
        kanban_name=$(echo "$kanban_output" | python3 ${extractKanbanName})
        if [ -n "$kanban_name" ] && [ -n "''${CLAUDE_ENV_FILE:-}" ]; then
          echo "export KANBAN_SESSION=$kanban_name" >> "$CLAUDE_ENV_FILE"
        elif [ -n "$kanban_name" ] && [ -z "''${CLAUDE_ENV_FILE:-}" ]; then
          echo "Warning: CLAUDE_ENV_FILE is not set; KANBAN_SESSION=$kanban_name will not be exported to the shell environment" >&2
        fi
        ${perm}/bin/perm cleanup-stale 2>/dev/null || true
        echo "$json" | ${perm}/bin/perm session-hook 2>/dev/null || true
        output="$kanban_output"
        if [ -f ~/.claude/TOOLS.md ]; then
          tools_md=$(cat ~/.claude/TOOLS.md)
          output="$output
$tools_md"
        fi
        kanban_xml=$(kanban list --output-style=xml 2>/dev/null || true)
        if [ -n "$kanban_xml" ]; then
          orphan_warning=$(echo "$kanban_xml" | python3 ${findOrphanedCards} 2>/dev/null || true)
          if [ -n "$orphan_warning" ]; then
            output="$output
$orphan_warning"
          fi
        fi
        printf '%s' "$output" | python3 ${toResultJson}
      '';
      description = "Hook for Claude Code session start - injects kanban session identity and perm session UUID";
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

    prr = prrScript // {
      meta = {
        description = "Submit GitHub PR reviews with inline comments from a structured findings JSON file";
        mainProgram = "prr";
        homepage = "${builtins.toString ./.}/prr.py";
      };
    };

    perm = shellApp {
      name = "perm";
      runtimeInputs = [ pkgs.jq ];
      text = builtins.readFile ./perm.bash;
      description = "Manage Claude Code permissions in .claude/settings.local.json (allow, always, cleanup, list)";
      sourceFile = "perm.bash";
    };

    claude-inspect = claudeInspectScript // {
      meta = {
        description = "Introspect Claude session metrics from the SQLite metrics DB (token usage, cost, tool calls, card events)";
        mainProgram = "claude-inspect";
        homepage = "${builtins.toString ./.}/claude-inspect.py";
      };
    };

    kanban-pretool-hook = kanbanPretoolHookScript // {
      meta = {
        description = "PreToolUse(Agent) hook that injects kanban card content into sub-agent prompts";
        mainProgram = "kanban-pretool-hook";
        homepage = "${builtins.toString ./.}/kanban-pretool-hook.py";
      };
    };

    kanban-subagent-stop-hook = kanbanSubagentStopHookScript // {
      meta = {
        description = "SubagentStop hook that runs dual-loop AC review via haiku before allowing agent stop";
        mainProgram = "kanban-subagent-stop-hook";
        homepage = "${builtins.toString ./.}/kanban-subagent-stop-hook.py";
      };
    };

    kanban-permission-hook = shellApp {
      name = "kanban-permission-hook";
      runtimeInputs = [ pkgs.jq ];
      text = builtins.readFile ./kanban-permission-hook.bash;
      description = "PermissionRequest hook that auto-approves any Bash command starting with kanban";
      sourceFile = "kanban-permission-hook.bash";
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
        #   *  - Matches any characters (including spaces, newlines, paths, parameters)
        #        This means Bash(kanban *) covers multi-line heredoc commands too.
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
            "Bash(kanban:*)"

            # Perm CLI (permission lifecycle management)
            "Bash(perm)"
            "Bash(perm *)"

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
            "Write(//tmp/**)"
            "Edit(//tmp/**)"
            "Write(//private/tmp/**)"
            "Edit(//private/tmp/**)"

            # Project-local scratchpad - required for debugger ledger and project plan persistence across rounds
            "Write(.scratchpad/**)"
            "Edit(.scratchpad/**)"

            # Context7 MCP - Auto-approve all documentation queries
            "mcp__context7__*"

            # Notes MCP - Auto-approve all artifact tool usages
            "mcp__notes__*"

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

            # Category B - Git Read-Only Commands (-C <path> variants)
            "Bash(git -C * status *)"
            "Bash(git -C * log *)"
            "Bash(git -C * show *)"
            "Bash(git -C * diff *)"
            "Bash(git -C * blame *)"
            "Bash(git -C * who *)"
            "Bash(git -C * branch)"
            "Bash(git -C * branch -l *)"
            "Bash(git -C * branch --list *)"
            "Bash(git -C * ls-files *)"
            "Bash(git -C * ls-remote *)"
            "Bash(git -C * remote)"
            "Bash(git -C * remote -v)"
            "Bash(git -C * remote show *)"
            "Bash(git -C * config --get *)"
            "Bash(git -C * config --list *)"
            "Bash(git -C * rev-parse *)"
            "Bash(git -C * describe *)"
            "Bash(git -C * reflog *)"
            "Bash(git -C * tag)"
            "Bash(git -C * tag -l *)"
            "Bash(git -C * tag --list *)"
            "Bash(git -C * worktree list *)"
            "Bash(git -C * stash list *)"
            "Bash(git -C * stash show *)"
            "Bash(git -C * grep *)"
            "Bash(git -C * for-each-ref *)"
            "Bash(git -C * difft *)"
            "Bash(git -C * logt *)"
            "Bash(git -C * showt *)"

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

            # Category C - GitHub CLI (additional read-only subcommands)
            "Bash(gh auth status *)"
            "Bash(gh workflow view *)"
            "Bash(gh workflow list *)"
            "Bash(gh search repos *)"
            "Bash(gh search issues *)"
            "Bash(gh search prs *)"
            "Bash(gh search code *)"
            "Bash(gh search commits *)"
            "Bash(gh label list *)"
            "Bash(gh label view *)"
            "Bash(gh org list *)"
            "Bash(gh org view *)"
            "Bash(gh project list *)"
            "Bash(gh project view *)"
            "Bash(gh project item-list *)"
            "Bash(gh ruleset list *)"
            "Bash(gh ruleset view *)"
            "Bash(gh cache list *)"
            "Bash(gh variable list *)"
            "Bash(gh ssh-key list *)"
            "Bash(gh gpg-key list *)"
            "Bash(gh extension list *)"
            "Bash(gh config list *)"
            "Bash(gh config get *)"
            "Bash(gh attestation verify *)"
            "Bash(gh release download *)"
            "Bash(gh run watch *)"

            # Category C - AWS CLI (read-only)
            "Bash(aws sts get-caller-identity *)"
            "Bash(aws s3 ls *)"
            "Bash(aws s3api list-buckets *)"
            "Bash(aws s3api get-bucket-* *)"
            "Bash(aws s3api list-objects *)"
            "Bash(aws s3api list-objects-v2 *)"
            "Bash(aws ec2 describe-* *)"
            "Bash(aws iam list-* *)"
            "Bash(aws iam get-* *)"
            "Bash(aws eks describe-* *)"
            "Bash(aws eks list-* *)"
            "Bash(aws ecr describe-* *)"
            "Bash(aws ecr list-* *)"
            "Bash(aws ecr get-* *)"
            "Bash(aws logs describe-* *)"
            "Bash(aws logs get-* *)"
            "Bash(aws logs filter-log-events *)"
            "Bash(aws cloudwatch describe-* *)"
            "Bash(aws cloudwatch get-* *)"
            "Bash(aws cloudwatch list-* *)"
            "Bash(aws lambda list-* *)"
            "Bash(aws lambda get-* *)"
            "Bash(aws rds describe-* *)"
            "Bash(aws ssm describe-* *)"
            "Bash(aws ssm list-* *)"
            "Bash(aws secretsmanager describe-* *)"
            "Bash(aws secretsmanager list-* *)"
            "Bash(aws route53 list-* *)"
            "Bash(aws route53 get-* *)"
            "Bash(aws acm describe-* *)"
            "Bash(aws acm list-* *)"
            "Bash(aws elb describe-* *)"
            "Bash(aws elbv2 describe-* *)"
            "Bash(aws cloudformation describe-* *)"
            "Bash(aws cloudformation list-* *)"
            "Bash(aws cloudformation get-* *)"
            "Bash(aws sqs list-* *)"
            "Bash(aws sqs get-* *)"
            "Bash(aws sns list-* *)"
            "Bash(aws sns get-* *)"
            "Bash(aws dynamodb describe-* *)"
            "Bash(aws dynamodb list-* *)"
            "Bash(aws codecommit list-* *)"
            "Bash(aws codecommit get-* *)"

            # Category C - Helm (read-only)
            "Bash(helm list *)"
            "Bash(helm get *)"
            "Bash(helm status *)"
            "Bash(helm history *)"
            "Bash(helm show *)"
            "Bash(helm search *)"
            "Bash(helm repo list *)"
            "Bash(helm env *)"
            "Bash(helm version *)"
            "Bash(helm diff *)"

            # Category C - ArgoCD (read-only)
            "Bash(argocd app list *)"
            "Bash(argocd app get *)"
            "Bash(argocd app diff *)"
            "Bash(argocd app logs *)"
            "Bash(argocd app resources *)"
            "Bash(argocd app history *)"
            "Bash(argocd app manifests *)"
            "Bash(argocd project list *)"
            "Bash(argocd project get *)"
            "Bash(argocd cluster list *)"
            "Bash(argocd cluster get *)"
            "Bash(argocd repo list *)"
            "Bash(argocd version *)"
            "Bash(argocd account list *)"
            "Bash(argocd account get-user-info *)"

            # Category C - 1Password CLI (biometric-gated — safe to auto-approve)
            "Bash(op account list *)"
            "Bash(op account get *)"
            "Bash(op vault list *)"
            "Bash(op vault get *)"
            "Bash(op item list *)"
            "Bash(op item get *)"
            "Bash(op user list *)"
            "Bash(op user get *)"
            "Bash(op group list *)"
            "Bash(op group get *)"
            "Bash(op whoami *)"
            "Bash(op service-account list *)"
            "Bash(op read *)"
            "Bash(op inject *)"

            # Category C - Docker (read-only)
            "Bash(docker ps *)"
            "Bash(docker images *)"
            "Bash(docker inspect *)"
            "Bash(docker logs *)"
            "Bash(docker stats *)"
            "Bash(docker top *)"
            "Bash(docker diff *)"
            "Bash(docker history *)"
            "Bash(docker info *)"
            "Bash(docker version *)"
            "Bash(docker network ls *)"
            "Bash(docker network inspect *)"
            "Bash(docker volume ls *)"
            "Bash(docker volume inspect *)"
            "Bash(docker container ls *)"
            "Bash(docker image ls *)"
            "Bash(docker system df *)"

            # Category C - Nix (read-only; nix eval excluded)
            "Bash(nix flake metadata *)"
            "Bash(nix flake info *)"
            "Bash(nix flake show *)"
            "Bash(nix flake check *)"
            "Bash(nix search *)"
            "Bash(nix show-derivation *)"
            "Bash(nix path-info *)"
            "Bash(nix why-depends *)"
            "Bash(nix store verify *)"
            "Bash(nix store ls *)"
            "Bash(nix store cat *)"
            "Bash(nix store diff-closures *)"
            "Bash(nix doctor *)"

            # Category C - DevBox
            "Bash(devbox list *)"
            "Bash(devbox info *)"
            "Bash(devbox version *)"
            "Bash(devbox search *)"
            "Bash(devbox status *)"

            # Category C - Just (task runner, read-only inspection)
            "Bash(just --list *)"
            "Bash(just --summary *)"
            "Bash(just --show *)"
            "Bash(just --dry-run *)"
            "Bash(just --evaluate *)"

            # Category C - Go (read-only)
            "Bash(go version *)"
            "Bash(go env *)"
            "Bash(go list *)"
            "Bash(go doc *)"
            "Bash(go vet *)"

            # Category C - pnpm (read-only)
            "Bash(pnpm list *)"
            "Bash(pnpm ls *)"
            "Bash(pnpm view *)"
            "Bash(pnpm info *)"
            "Bash(pnpm outdated *)"
            "Bash(pnpm why *)"
            "Bash(pnpm audit *)"

            # pnpm test runner (global - run-only mode; watch/interactive excluded to reduce attack surface)
            "Bash(pnpm vitest run *)"

            # Category C - uv (Python tooling, read-only)
            "Bash(uv pip list *)"
            "Bash(uv pip show *)"
            "Bash(uv pip check *)"
            "Bash(uv tree *)"
            "Bash(uv version *)"
            "Bash(uv python list *)"
            "Bash(uv tool list *)"

            # Category C - mise (runtime version manager, read-only)
            "Bash(mise list *)"
            "Bash(mise current *)"
            "Bash(mise env *)"
            "Bash(mise where *)"
            "Bash(mise which *)"
            "Bash(mise doctor *)"
            "Bash(mise ls *)"

            # Category C - home-manager (read-only)
            "Bash(home-manager generations *)"
            "Bash(home-manager packages *)"
            "Bash(home-manager option *)"
            "Bash(home-manager news *)"

            # Category C - vcluster (read-only)
            "Bash(vcluster list *)"
            "Bash(vcluster describe *)"
            "Bash(vcluster version *)"

            # Category C - tilt (read-only)
            "Bash(tilt get *)"
            "Bash(tilt describe *)"
            "Bash(tilt logs *)"
            "Bash(tilt version *)"

            # Category C - bazelisk / bazel (read-only)
            "Bash(bazel query *)"
            "Bash(bazel info *)"
            "Bash(bazel version *)"
            "Bash(bazel aquery *)"
            "Bash(bazel cquery *)"
            "Bash(bazelisk query *)"
            "Bash(bazelisk info *)"
            "Bash(bazelisk version *)"

            # Category C - eza (directory listing)
            "Bash(eza *)"

            # Category C - node / python3 (version query only; -e/-p/-c excluded)
            "Bash(node --version *)"
            "Bash(python3 --version *)"

            # Claude Code metrics introspection CLI
            "Bash(claude-inspect *)"

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
            # AWS ECR credential commands (returns 12-hour auth tokens)
            "Bash(aws ecr get-login-password *)"

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
          Notification = [
            {
              hooks = [{
                type = "command";
                command = "${shellapps.claude-notification-hook}/bin/claude-notification-hook";
              }];
            }
          ];
          SubagentStop = [{
            hooks = [
              {
                type = "command";
                command = "${shellapps.claudit-hook}/bin/claudit-hook";
              }
              {
                type = "command";
                command = "${shellapps.kanban-subagent-stop-hook}/bin/kanban-subagent-stop-hook";
                timeout = 600000;
              }
              {
                type = "command";
                command = "${shellapps.claude-complete-hook}/bin/claude-complete-hook";
              }
            ];
          }];
          Stop = [{
            hooks = [
              {
                type = "command";
                command = "${shellapps.claude-complete-hook}/bin/claude-complete-hook";
              }
              {
                type = "command";
                command = "${shellapps.claudit-hook}/bin/claudit-hook";
              }
            ];
          }];
          PreToolUse = [
            {
              matcher = "Agent";
              hooks = [{
                type = "command";
                command = "${shellapps.kanban-pretool-hook}/bin/kanban-pretool-hook";
                timeout = 600000;
              }];
            }
          ];
          PostToolUse = [
            {
              matcher = "Edit|MultiEdit|Write";
              hooks = [{
                type = "command";
                command = "${shellapps.claude-csharp-format-hook}/bin/claude-csharp-format-hook";
              }];
            }
            {
              matcher = "Bash";
              hooks = [{
                type = "command";
                command = "${shellapps.claude-kanban-transition-hook}/bin/claude-kanban-transition-hook";
              }];
            }
          ];
          SessionStart = [{
            hooks = [{
              type = "command";
              command = "${shellapps.claude-session-start-hook}/bin/claude-session-start-hook";
            }];
          }];
          PostCompact = [{
            hooks = [{
              type = "command";
              command = pkgs.writeShellScript "claude-postcompact-hook" ''
                set -euo pipefail

                # Output the full kanban board state (re-inject after compaction)
                kanban_xml=$(kanban list --output-style=xml 2>/dev/null || true)
                if [ -n "$kanban_xml" ]; then
                  echo "$kanban_xml"
                fi

                # Check for deferred cards and append notification
                deferred=$(kanban list --column todo --output-style=simple 2>/dev/null || true)
                if [ -n "$deferred" ]; then
                  echo ""
                  echo "Deferred cards awaiting action:"
                  echo "$deferred"
                fi
              '';
            }];
          }];
          PermissionRequest = [
            {
              hooks = [{
                type = "command";
                command = "${shellapps.kanban-permission-hook}/bin/kanban-permission-hook";
              }];
            }
            {
              hooks = [{
                type = "command";
                command = "${shellapps.perm}/bin/perm hook";
              }];
            }
          ];
        };
      };
      claudeSettingsJson = pkgs.runCommand "claude-settings.json" {} ''
        echo '${builtins.toJSON settingsContent}' | ${pkgs.jq}/bin/jq . > $out
      '';
    in lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      $DRY_RUN_CMD mkdir -p ~/.claude
      $DRY_RUN_CMD rm -f ~/.claude/settings.json
      $DRY_RUN_CMD cp ${claudeSettingsJson} ~/.claude/settings.json
      $DRY_RUN_CMD chmod 644 ~/.claude/settings.json
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
      # EXCLUDE hats/ directory - contains build-time template files only
      $DRY_RUN_CMD mkdir -p ~/.claude

      # Make existing files writable BEFORE copying, so cp can overwrite read-only
      # files left by previous builds. Also removes stale hash-prefixed store-path
      # directories accumulated by earlier buggy activations (see below).
      $DRY_RUN_CMD chmod -R u+w ~/.claude/

      # Copy top-level files from the Nix store path into ~/.claude/
      $DRY_RUN_CMD find ${claudeGlobalDir} -maxdepth 1 -type f -exec cp {} ~/.claude/ \;

      # Copy subdirectories (commands, agents, etc.) into ~/.claude/
      # -mindepth 1: excludes the store path root itself (prevents creating
      #              ~/.claude/HASH-global/ directories on every hms run)
      # ! -name hats: excludes build-time template directory
      $DRY_RUN_CMD find ${claudeGlobalDir} -mindepth 1 -maxdepth 1 -type d ! -name hats -exec cp -rf {} ~/.claude/ \;

      # Ensure all subdirectories exist (in case cp didn't create them)
      $DRY_RUN_CMD mkdir -p ~/.claude/commands ~/.claude/output-styles ~/.claude/docs ~/.claude/agents

      # Make copied files writable (Nix store files are read-only by default)
      $DRY_RUN_CMD chmod -R u+w ~/.claude/

      # Remove stale files that have been migrated out of commands/ to skills/
      # These are no longer deployed by the cp above but won't be auto-deleted
      $DRY_RUN_CMD rm -f ~/.claude/commands/review.md
      $DRY_RUN_CMD rm -f ~/.claude/commands/review-domains.md
      $DRY_RUN_CMD rm -f ~/.claude/commands/review-citation-guide.md

      # Add generated TOOLS.md (use install to handle read-only destination from previous build)
      $DRY_RUN_CMD install -m 644 ${toolsMarkdown} ~/.claude/TOOLS.md
    '';

    # claudeMcp
    # Purpose: Merges Context7 and Notes MCP configuration into ~/.claude.json
    # Why: Enables Context7 MCP integration and Notes MCP while preserving Claude's metadata
    # When: After writeBoundary (after files are written to disk)
    # Note: Context7 only runs if context7ApiKey is provided (not null)
    #       Notes MCP is always configured
    #       Merges config into existing file instead of overwriting
    claudeMcp = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      # Create ~/.claude.json if it doesn't exist
      if [[ ! -f ~/.claude.json ]]; then
        $DRY_RUN_CMD echo '{}' > ~/.claude.json
      fi

      # Add Notes MCP server configuration (HTTP transport)
      $DRY_RUN_CMD ${pkgs.jq}/bin/jq '.mcpServers.notes = {
        "type": "http",
        "url": "https://notes.mctx.ai"
      }' ~/.claude.json > ~/.claude.json.tmp

      $DRY_RUN_CMD mv ~/.claude.json.tmp ~/.claude.json

      # Add Todos MCP server configuration (HTTP transport)
      $DRY_RUN_CMD ${pkgs.jq}/bin/jq '.mcpServers.todos = {
        "type": "http",
        "url": "https://todos.mctx.ai"
      }' ~/.claude.json > ~/.claude.json.tmp

      $DRY_RUN_CMD mv ~/.claude.json.tmp ~/.claude.json

      # Merge Context7 MCP configuration if API key is provided
      # Note: Claude Code supports ''${VARIABLE_NAME} syntax for runtime env var expansion
      # See: https://github.com/anthropics/claude-code/issues/2065
      ${if context7ApiKey != null then ''
        $DRY_RUN_CMD ${pkgs.jq}/bin/jq '.mcpServers.context7 = {
          "command": "npx",
          "args": ["-y", "@upstash/context7-mcp"],
          "env": {
            "CONTEXT7_API_KEY": "''${CONTEXT7_API_KEY}"
          }
        }' ~/.claude.json > ~/.claude.json.tmp

        # Replace original file with merged version
        $DRY_RUN_CMD mv ~/.claude.json.tmp ~/.claude.json
      '' else ''
        # Context7 not configured (context7ApiKey is null)
      ''}

      $DRY_RUN_CMD chmod 600 ~/.claude.json
    '';
  };
}
