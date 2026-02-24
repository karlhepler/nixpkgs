{ config, pkgs, lib, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

  homeDirectory = config.home.homeDirectory;

  # Plugin package
  sqlitePlugin = pkgs.grafanaPlugins.frser-sqlite-datasource;

  # Plugin directory: a single derivation that holds the plugin symlinked in
  # Grafana's expected layout: <pluginsDir>/<plugin-id>/
  pluginsDir = pkgs.runCommand "grafana-plugins" {} ''
    mkdir -p $out/${sqlitePlugin.pname}
    ln -s ${sqlitePlugin}/* $out/${sqlitePlugin.pname}/
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

in {
  # ============================================================================
  # Grafana - On-demand local metrics viewer
  # ============================================================================
  # Run `claudit` to start Grafana on http://claudit.local:3200
  # Press SPACE to reopen browser, Ctrl+C to stop.
  # ============================================================================

  _module.args.grafanaShellapps = {
    claudit = shellApp {
      name = "claudit";
      runtimeInputs = [ pkgs.grafana pkgs.curl ];
      text = ''
        GRAFANA_URL="http://claudit.local:3200"
        GRAFANA_HOMEPATH="${pkgs.grafana}/share/grafana"
        GRAFANA_PID=""

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
              GRAFANA_URL="http://localhost:3200"
            fi
          fi
        }

        # --- Clean shutdown on Ctrl+C ---
        cleanup() {
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

        echo "Starting Grafana..."
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
          open "''${GRAFANA_URL}"
        else
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
  };

  # Create Grafana data and log directories on activation
  home.activation.grafanaDirectories = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD mkdir -p ${homeDirectory}/.local/share/grafana/log
  '';
}
