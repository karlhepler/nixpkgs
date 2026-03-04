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

  # Provisioning datasource YAML
  datasourceYaml = pkgs.writeText "datasource.yaml" ''
    apiVersion: 1
    datasources:
      - name: claude-metrics-sqlite
        type: frser-sqlite-datasource
        uid: claude-metrics-sqlite
        access: proxy
        jsonData:
          path: ${homeDirectory}/.claude/metrics/claude-metrics.db
          pathOptions: "_pragma=busy_timeout(5000)"
        editable: true
  '';

  # Dashboard provisioning YAML
  dashboardYaml = pkgs.writeText "dashboard.yaml" ''
    apiVersion: 1
    providers:
      - name: claude-metrics
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
    http_port = 3200
    http_addr = 127.0.0.1
    domain = claudit.local
    root_url = http://claudit.local:3200/

    [auth.anonymous]
    enabled = true
    org_role = Admin

    [auth]
    disable_login_form = true

    [plugins]
    allow_loading_unsigned_plugins = frser-sqlite-datasource

    [paths]
    data = ${homeDirectory}/.local/share/grafana
    logs = ${homeDirectory}/.local/share/grafana/log
    plugins = ${pluginsDir}
    provisioning = ${provisioningDir}
  '';

  # Claude Metrics Hook (tracks agent metrics on stop events)
  claudeMetricsHookScript = pkgs.writers.writePython3Bin "claude-metrics-hook" {
    flakeIgnore = [ "E265" "E501" "W503" "W504" ];  # Ignore shebang, line length, line breaks
  } (builtins.readFile ./claude-metrics-hook.py);

in {
  # ============================================================================
  # Claudit - Claude Code metrics dashboard + metrics collection hook
  # ============================================================================
  # Run `claudit` to start Grafana on http://claudit.local:3200
  # Press SPACE to reopen browser, Ctrl+C to stop.
  # ============================================================================

  _module.args.clauditShellapps = {
    claudit = shellApp {
      name = "claudit";
      runtimeInputs = [ pkgs.grafana pkgs.curl pkgs.sqlite ];
      text = ''
        GRAFANA_URL="http://claudit.local:3200/d/claudit-dashboard/claudit-claude-code-agent-metrics?orgId=1&from=now-7d&to=now&timezone=browser&refresh=30s"
        GRAFANA_HOMEPATH="${pkgs.grafana}/share/grafana"
        GRAFANA_PID=""
        METRICS_DB="''${HOME}/.claude/metrics/claude-metrics.db"

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
            # Recreate the database schema immediately via direct sqlite3 (no hook invocation)
            mkdir -p "$(dirname "''${METRICS_DB}")"
            sqlite3 "''${METRICS_DB}" <<'SQL_EOF'
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS agent_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT "",
    role TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime("%Y-%m-%dT%H:%M:%SZ", "now")),
    working_directory TEXT,
    kanban_session TEXT,
    git_branch TEXT,
    model TEXT NOT NULL,
    model_family TEXT NOT NULL,
    turns INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_5m_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_1h_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    duration_seconds REAL DEFAULT 0.0,
    avg_turn_latency_seconds REAL DEFAULT 0.0,
    cache_hit_ratio REAL DEFAULT 0.0,
    tool_calls INTEGER DEFAULT 0,
    tool_errors INTEGER DEFAULT 0,
    is_sidechain INTEGER NOT NULL DEFAULT 0,
    last_seen_at TIMESTAMP,
    UNIQUE(session_id, agent_id, role, model)
);

CREATE TABLE IF NOT EXISTS agent_tool_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT "",
    role TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime("%Y-%m-%dT%H:%M:%SZ", "now")),
    tool_name TEXT NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, agent_id, role, tool_name)
);

CREATE TABLE IF NOT EXISTS permission_denials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT "",
    role TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime("%Y-%m-%dT%H:%M:%SZ", "now")),
    tool_name TEXT NOT NULL,
    tool_input TEXT,
    tool_use_id TEXT,
    kanban_session TEXT,
    UNIQUE(session_id, tool_use_id)
);

CREATE TABLE IF NOT EXISTS kanban_card_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_number TEXT NOT NULL,
    event_type TEXT NOT NULL,
    agent TEXT,
    model TEXT,
    kanban_session TEXT,
    recorded_at TEXT NOT NULL DEFAULT (strftime("%Y-%m-%dT%H:%M:%SZ", "now")),
    card_created_at TEXT,
    card_completed_at TEXT,
    card_type TEXT,
    ac_count INTEGER,
    git_project TEXT,
    from_column TEXT,
    to_column TEXT,
    persona TEXT
);

CREATE INDEX IF NOT EXISTS idx_kanban_card_events_event_type ON kanban_card_events (event_type);
CREATE INDEX IF NOT EXISTS idx_kanban_card_events_agent ON kanban_card_events (agent);
CREATE INDEX IF NOT EXISTS idx_kanban_card_events_recorded_at ON kanban_card_events (recorded_at);

CREATE INDEX IF NOT EXISTS idx_agent_metrics_session_id ON agent_metrics (session_id);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_recorded_at ON agent_metrics (recorded_at);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_role ON agent_metrics (role);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_model_family ON agent_metrics (model_family);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_kanban_session ON agent_metrics (kanban_session);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_git_branch ON agent_metrics (git_branch);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_is_sidechain ON agent_metrics (is_sidechain);
CREATE INDEX IF NOT EXISTS idx_tool_usage_session_id ON agent_tool_usage (session_id);
CREATE INDEX IF NOT EXISTS idx_tool_usage_tool_name ON agent_tool_usage (tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_usage_role ON agent_tool_usage (role);
CREATE INDEX IF NOT EXISTS idx_permission_denials_session_id ON permission_denials (session_id);
CREATE INDEX IF NOT EXISTS idx_permission_denials_tool_name ON permission_denials (tool_name);
CREATE INDEX IF NOT EXISTS idx_permission_denials_kanban_session ON permission_denials (kanban_session);
SQL_EOF
            echo "Database recreated with correct schema."
          else
            echo "Aborted."
          fi
          exit 0
        fi

        # --- /etc/hosts check ---
        check_hosts() {
          if ! dscacheutil -q host -a name claudit.local 2>/dev/null | grep -q '127.0.0.1'; then
            echo "claudit.local is not in /etc/hosts."
            echo ""
            echo "To add it, run:"
            echo "  sudo sh -c 'echo \"127.0.0.1 claudit.local\" >> /etc/hosts'"
            echo ""
            printf "Want me to add it now? [y/N] "
            read -r answer
            if [[ "''${answer}" =~ ^[Yy]$ ]]; then
              sudo sh -c 'echo "127.0.0.1 claudit.local" >> /etc/hosts'
              echo "Added! Continuing..."
            else
              echo "Skipping. Falling back to http://localhost:3200"
              GRAFANA_URL="http://localhost:3200/d/claudit-dashboard/claudit-claude-code-agent-metrics?orgId=1&from=now-7d&to=now&timezone=browser&refresh=30s"
            fi
          fi
        }

        # --- Loading animation ---
        LOADING_PID=""
        start_loading() {
          (
            while true; do
              printf "\rLoading.  "
              sleep 0.3
              printf "\rLoading.. "
              sleep 0.3
              printf "\rLoading..."
              sleep 0.3
            done
          ) &
          LOADING_PID=$!
        }

        stop_loading() {
          if [[ -n "''${LOADING_PID}" ]]; then
            kill "''${LOADING_PID}" 2>/dev/null || true
            wait "''${LOADING_PID}" 2>/dev/null || true
            printf "\r             \r"  # Clear the line
          fi
        }

        # --- Clean shutdown on Ctrl+C ---
        cleanup() {
          stop_loading
          echo ""
          echo "Stopping Grafana..."
          if [[ -n "''${GRAFANA_PID}" ]]; then
            kill "''${GRAFANA_PID}" 2>/dev/null || true
            wait "''${GRAFANA_PID}" 2>/dev/null || true
          fi
          exit 0
        }
        trap cleanup INT TERM

        # --- Wait for Grafana to accept connections ---
        wait_for_grafana() {
          local attempts=0
          while (( attempts < 20 )); do
            if curl -sf "http://127.0.0.1:3200/api/health" >/dev/null 2>&1; then
              return 0
            fi
            sleep 0.5
            (( attempts++ )) || true
          done
          return 1
        }

        # --- Start ---
        check_hosts

        start_loading
        sleep 0.1  # Brief delay to ensure animation starts cleanly

        grafana server \
          --config ${grafanaIni} \
          --homepath "''${GRAFANA_HOMEPATH}" \
          >"''${HOME}/.local/share/grafana/log/claudit.log" 2>&1 &
        GRAFANA_PID="$!"

        # Verify process started
        sleep 0.5
        if ! kill -0 "''${GRAFANA_PID}" 2>/dev/null; then
          echo "ERROR: Grafana failed to start. Check log:"
          echo "  ''${HOME}/.local/share/grafana/log/claudit.log"
          exit 1
        fi

        # Wait until HTTP is ready, then open browser
        if wait_for_grafana; then
          stop_loading
          echo "Starting Grafana... Done!"
          open "''${GRAFANA_URL}"
        else
          stop_loading
          echo "WARNING: Grafana did not respond within 10s. Opening browser anyway..."
          open "''${GRAFANA_URL}"
        fi

        echo "Claudit metrics dashboard: ''${GRAFANA_URL}"
        echo "Press SPACE to open browser, Ctrl+C to stop."

        # --- Foreground keypress loop ---
        while true; do
          # Read one character without requiring Enter (-n 1), silent (-s)
          if read -r -s -n 1 key 2>/dev/null; then
            # SPACE (empty after trimming) or Enter (\n becomes empty string)
            if [[ "''${key}" == " " || "''${key}" == "" ]]; then
              open "''${GRAFANA_URL}"
            fi
          fi
          # Check if Grafana process is still alive
          if ! kill -0 "''${GRAFANA_PID}" 2>/dev/null; then
            echo "Grafana exited unexpectedly. Check log:"
            echo "  ''${HOME}/.local/share/grafana/log/claudit.log"
            exit 1
          fi
        done
      '';
      description = "Start on-demand Grafana server for Claude Code agent metrics (port 3200)";
      sourceFile = "default.nix";
    };

    claude-metrics-hook = claudeMetricsHookScript // {
      meta = {
        description = "Hook for tracking agent metrics on stop events";
        mainProgram = "claude-metrics-hook";
        homepage = "${builtins.toString ./.}/claude-metrics-hook.py";
      };
    };
  };

  # Create Grafana data and log directories on activation
  home.activation.grafanaDirectories = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD mkdir -p ${homeDirectory}/.local/share/grafana/log
  '';
}
