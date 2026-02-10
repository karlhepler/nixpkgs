{ config, pkgs, lib, shellapps, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

in {
  # ============================================================================
  # Ralph Orchestrator Configuration & Shell Applications
  # ============================================================================
  # Docker-based Ralph execution with transparent CLI wrapper
  # ============================================================================

  _module.args.ralphShellapps = rec {
    ralph = shellApp {
      name = "ralph";
      runtimeInputs = [ pkgs.docker pkgs.coreutils ];
      text = builtins.readFile ./ralph-wrapper.bash;
      description = "Ralph Orchestrator (containerized) - multi-agent orchestration framework";
      sourceFile = "ralph-wrapper.bash";
    };
  };

  # Deploy Dockerfile via activation (copy, not symlink, for Docker build compatibility)
  home.activation.deployRalphDockerfile = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    echo "Deploying Ralph Dockerfile..."
    mkdir -p "$HOME/.local/share/ralph"
    cp -f "${./Dockerfile}" "$HOME/.local/share/ralph/Dockerfile"
  '';
}
