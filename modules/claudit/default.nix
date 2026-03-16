{ config, pkgs, lib, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

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
      runtimeInputs = [ pkgs.grafana pkgs.curl pkgs.sqlite ];
      text = ''
        GRAFANA_URL="http://localhost:3201/d/claudit2/claudit2?orgId=1&from=now-7d&to=now&timezone=browser&refresh=30s"
        GRAFANA_HOMEPATH="${pkgs.grafana}/share/grafana"
        METRICS_DB="''${HOME}/.claude/metrics/claudit.db"

        # --- Handle help flags ---
        if [[ "''${1:-}" == "--help" ]] || [[ "''${1:-}" == "-h" ]]; then
          cat <<'HELP_EOF'
Usage: claudit [subcommand]

Subcommands:
  nuke       Delete the entire metrics database file (recreated fresh on next hook invocation)

Run claudit with no arguments to start the Grafana dashboard.
HELP_EOF
          exit 0
        fi

        # --- Handle nuke subcommand ---
        if [[ "''${1:-}" == "nuke" ]]; then
          echo "This will permanently delete the entire claudit metrics database."
          echo "The database will be recreated with the correct schema immediately."
          printf "Continue? [y/N] "
          read -r answer
          if [[ "''${answer}" =~ ^[Yy]$ ]]; then
            rm -f "''${METRICS_DB}"
            echo "Database deleted, recreating schema..."
            mkdir -p "$(dirname "''${METRICS_DB}")"
            sqlite3 "''${METRICS_DB}" <<'SQL_EOF'
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS agent_metrics (
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT "",
    agent TEXT NOT NULL DEFAULT "unknown",
    model TEXT NOT NULL DEFAULT "unknown",
    kanban_session TEXT NOT NULL DEFAULT "unknown",
    card_number INTEGER,
    git_repo TEXT NOT NULL DEFAULT "unknown",
    working_directory TEXT NOT NULL DEFAULT "",
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    total_turns INTEGER NOT NULL DEFAULT 0,
    avg_turn_latency_seconds REAL NOT NULL DEFAULT 0.0,
    cache_hit_ratio REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS agent_tool_usage (
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT "",
    tool_name TEXT NOT NULL,
    bash_command TEXT NOT NULL DEFAULT "",
    bash_subcommand TEXT NOT NULL DEFAULT "",
    call_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (session_id, agent_id, tool_name, bash_command, bash_subcommand)
);

CREATE TABLE IF NOT EXISTS kanban_card_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kanban_session TEXT NOT NULL,
    card_number INTEGER NOT NULL,
    event TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT "",
    model TEXT NOT NULL DEFAULT "",
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_am_session_id ON agent_metrics (session_id);
CREATE INDEX IF NOT EXISTS idx_am_kanban_session ON agent_metrics (kanban_session);
CREATE INDEX IF NOT EXISTS idx_am_recorded_at ON agent_metrics (recorded_at);
CREATE INDEX IF NOT EXISTS idx_am_last_seen_at ON agent_metrics (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_am_git_repo ON agent_metrics (git_repo);
CREATE INDEX IF NOT EXISTS idx_am_agent ON agent_metrics (agent);
CREATE INDEX IF NOT EXISTS idx_am_model ON agent_metrics (model);
CREATE INDEX IF NOT EXISTS idx_atu_session_id ON agent_tool_usage (session_id);
CREATE INDEX IF NOT EXISTS idx_atu_tool_name ON agent_tool_usage (tool_name);
CREATE INDEX IF NOT EXISTS idx_kce_kanban_session ON kanban_card_events (kanban_session);
CREATE INDEX IF NOT EXISTS idx_kce_card_number ON kanban_card_events (card_number);
CREATE INDEX IF NOT EXISTS idx_kce_occurred_at ON kanban_card_events (occurred_at);
SQL_EOF
            echo "Database recreated with correct schema."
          else
            echo "Aborted."
          fi
          exit 0
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

    claudit-hook = clauditHookScript // {
      meta = {
        description = "Hook for tracking agent metrics on stop events";
        mainProgram = "claudit-hook";
        homepage = "${builtins.toString ./.}/claudit-hook.py";
      };
    };
  };

  # Create Claudit data and log directories on activation
  home.activation.clauditDirectories = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD mkdir -p ${homeDirectory}/.local/share/claudit/data
    $DRY_RUN_CMD mkdir -p ${homeDirectory}/.local/share/claudit/logs
  '';
}
