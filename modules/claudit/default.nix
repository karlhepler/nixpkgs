{ config, pkgs, lib, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

  # post-commit hook for the nixpkgs repo — records every commit as a Claudit annotation
  nixpkgsPostCommitHook = pkgs.writeShellApplication {
    name = "nixpkgs-post-commit";
    runtimeInputs = [ pkgs.git clauditAnnotateScript ];
    text = builtins.readFile ./commit-annotate.bash;
  };

  homeDirectory = config.home.homeDirectory;

  # Plugin package
  sqlitePlugin = pkgs.grafanaPlugins.frser-sqlite-datasource;

  # Plugin directory: a single derivation that holds the plugin copied in
  # Grafana's expected layout: <pluginsDir>/<plugin-id>/
  # We use `cp -rL` (copy, following symlinks) instead of `ln -s` because
  # Grafana's plugin loader rejects files whose resolved paths fall outside
  # the plugins directory. Symlinks into the Nix store fail this check.
  pluginsDir = pkgs.runCommand "grafana-plugins" {} ''
    mkdir -p $out/${sqlitePlugin.pname}
    cp -rL ${sqlitePlugin}/. $out/${sqlitePlugin.pname}/
  '';

  # Provisioning datasource YAML (single datasource, uid=claudit-sqlite)
  datasourceYaml = pkgs.writeText "datasource.yaml" ''
    apiVersion: 1
    datasources:
      - name: claudit
        type: frser-sqlite-datasource
        uid: claudit-sqlite
        access: proxy
        jsonData:
          path: ${homeDirectory}/.claude/metrics/claudit.db
          pathOptions: "_pragma=busy_timeout(5000)"
        editable: true
  '';

  # Dashboard provisioning YAML
  dashboardYaml = pkgs.writeText "dashboard.yaml" ''
    apiVersion: 1
    providers:
      - name: claudit
        type: file
        options:
          path: ${builtins.toString ./.}
          foldersFromFilesStructure: false
  '';

  # Provisioning directory layout:
  #   provisioning/datasources/datasource.yaml
  #   provisioning/dashboards/dashboard.yaml
  provisioningDir = pkgs.runCommand "grafana-provisioning" {} ''
    mkdir -p $out/datasources $out/dashboards
    ln -s ${datasourceYaml} $out/datasources/datasource.yaml
    ln -s ${dashboardYaml}  $out/dashboards/dashboard.yaml
  '';

  # grafana.ini configuration file
  grafanaIni = pkgs.writeText "grafana.ini" ''
    [server]
    http_port = 3201
    http_addr = 127.0.0.1
    domain = localhost
    root_url = http://localhost:3201/

    [auth.anonymous]
    enabled = true
    org_role = Admin

    [auth]
    disable_login_form = true

    [plugins]
    allow_loading_unsigned_plugins = frser-sqlite-datasource

    [paths]
    data = ${homeDirectory}/.local/share/claudit/data
    logs = ${homeDirectory}/.local/share/claudit/logs
    plugins = ${pluginsDir}
    provisioning = ${provisioningDir}
  '';

  # Claudit hook (captures agent metrics on stop events)
  clauditHookScript = pkgs.writers.writePython3Bin "claudit-hook" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];
  } (builtins.readFile ./claudit-hook.py);

  # Claudit annotate (records named change-marker annotations)
  clauditAnnotateScript = pkgs.writers.writePython3Bin "claudit-annotate" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];
  } (builtins.readFile ./claudit-annotate.py);

  # Claudit migrate (idempotent DB migration: purge stale events + backfill git-commit annotations)
  clauditMigrateScript = pkgs.writers.writePython3Bin "claudit-migrate" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];
  } (builtins.readFile ./claudit-migrate.py);

  # Wrapper that sets CLAUDIT_ROLE=claude-code as a default so the top-level
  # Claude Code Stop event gets a meaningful agent label instead of falling back
  # to the literal string 'claude'. If CLAUDIT_ROLE is already set (e.g. by a
  # future per-output-style launcher), the existing value is preserved.
  # SubagentStop is unaffected — that path reads payload.agent_type, not CLAUDIT_ROLE.
  clauditHookWrapper = pkgs.writeShellScriptBin "claudit-hook" ''
    export CLAUDIT_ROLE="''${CLAUDIT_ROLE:-claude-code}"
    exec ${clauditHookScript}/bin/claudit-hook "$@"
  '';

in {
  # ============================================================================
  # Claudit - Claude Code metrics dashboard + metrics collection hook
  # ============================================================================
  # Run `claudit` to start Grafana on http://localhost:3201
  # Press Ctrl+C to stop.
  # ============================================================================

  _module.args.clauditShellapps = {
    claudit = shellApp {
      name = "claudit";
      runtimeInputs = [ pkgs.grafana pkgs.curl clauditMigrateScript ];
      text = ''
        GRAFANA_URL="http://localhost:3201/d/claudit/claudit?orgId=1&from=now-7d&to=now&timezone=browser&refresh=30s"
        GRAFANA_HOMEPATH="${pkgs.grafana}/share/grafana"

        # --- Handle help flags ---
        if [[ "''${1:-}" == "--help" ]] || [[ "''${1:-}" == "-h" ]]; then
          cat <<'HELP_EOF'
Usage: claudit [subcommand]

Subcommands:
  migrate    Idempotent DB migration: purge stale kanban events + backfill git-commit annotations
             Options: --days N (default 30), --db PATH

Run claudit with no arguments to start the Grafana dashboard.
HELP_EOF
          exit 0
        fi

        # --- Handle migrate subcommand ---
        if [[ "''${1:-}" == "migrate" ]]; then
          shift
          exec claudit-migrate "$@"
        fi

        # --- Create data and log directories ---
        mkdir -p "''${HOME}/.local/share/claudit/data" "''${HOME}/.local/share/claudit/logs"

        # --- Start Grafana in background, output to terminal ---
        grafana server \
          --config ${grafanaIni} \
          --homepath "''${GRAFANA_HOMEPATH}" \
          2>&1 &
        grafana_pid=$!

        # --- Trap Ctrl+C for clean shutdown ---
        trap 'kill "''${grafana_pid}" 2>/dev/null; exit 0' INT TERM

        # --- Readiness check: up to 20 attempts, 0.5s sleep ---
        attempts=0
        while (( attempts < 20 )); do
          if curl -sf "http://127.0.0.1:3201/api/health" >/dev/null 2>&1; then
            break
          fi
          sleep 0.5
          (( attempts++ )) || true
        done

        open "''${GRAFANA_URL}"
        echo "Press Ctrl+C to stop."

        wait "''${grafana_pid}" 2>/dev/null || true
      '';
      description = "Start on-demand Grafana server for Claude Code agent metrics (port 3201)";
      sourceFile = "default.nix";
    };

    claudit-hook = clauditHookWrapper // {
      meta = {
        description = "Hook for tracking agent metrics on stop events";
        mainProgram = "claudit-hook";
        homepage = "${builtins.toString ./.}/claudit-hook.py";
      };
    };

    claudit-annotate = clauditAnnotateScript // {
      meta = {
        description = "Record a named change-marker annotation into the claudit metrics database";
        mainProgram = "claudit-annotate";
        homepage = "${builtins.toString ./.}/claudit-annotate.py";
      };
    };

    claudit-migrate = clauditMigrateScript // {
      meta = {
        description = "Idempotent claudit DB migration: purge stale kanban events + backfill git-commit annotations";
        mainProgram = "claudit-migrate";
        homepage = "${builtins.toString ./.}/claudit-migrate.py";
      };
    };
  };

  # Create Claudit data and log directories on activation
  home.activation.clauditDirectories = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD mkdir -p ${homeDirectory}/.local/share/claudit/data
    $DRY_RUN_CMD mkdir -p ${homeDirectory}/.local/share/claudit/logs
  '';

  # Install the post-commit hook into the nixpkgs repo so every commit is annotated
  # on the Claudit timeline. Mirrors the pattern used for nixpkgsPreCommitHook in
  # modules/git/default.nix.
  home.activation.nixpkgsPostCommitHook = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    hook_dir="${homeDirectory}/.config/nixpkgs/.git/hooks"
    $DRY_RUN_CMD mkdir -p "$hook_dir"
    $DRY_RUN_CMD install -m 755 ${nixpkgsPostCommitHook}/bin/nixpkgs-post-commit "$hook_dir/post-commit"
  '';
}
