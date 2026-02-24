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
  # Run `claudit` to start Grafana on http://localhost:3200
  # Press Ctrl+C to stop — no background service is created
  # ============================================================================

  _module.args.grafanaShellapps = {
    claudit = shellApp {
      name = "claudit";
      runtimeInputs = [ pkgs.grafana ];
      text = ''
        echo "Claudit metrics dashboard: http://localhost:3200"
        echo "Press Ctrl+C to stop."
        grafana server \
          --config ${grafanaIni} \
          --homepath ${pkgs.grafana}
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
