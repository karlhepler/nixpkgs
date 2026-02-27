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

        # --- Handle --expunge flag ---
        if [[ "''${1:-}" == "--expunge" ]]; then
          echo "This will permanently delete all claudit metrics data."
          printf "Continue? [y/N] "
          read -r answer
          if [[ "''${answer}" =~ ^[Yy]$ ]]; then
            if [[ -f "''${METRICS_DB}" ]]; then
              sqlite3 "''${METRICS_DB}" "DELETE FROM agent_metrics; DELETE FROM agent_tool_usage;"
              echo "All metrics data deleted."
            else
              echo "No database found at ''${METRICS_DB}. Nothing to delete."
            fi
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
