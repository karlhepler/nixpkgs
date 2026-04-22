{ pkgs, ... }:

let
  # Single source of truth for the agent-browser version.
  # Also imported by modules/claude/default.nix for the npx invocation in the
  # claudeAgentBrowserSkill activation hook. When bumping, update the hash below too.
  agentBrowserVersion = import ./version.nix;

  # agent-browser — hermetic binary derivation
  # (Strategy A: direct fetchurl with SRI hash. See .scratchpad/1097-researcher.md
  # for alternative strategies considered, including npx wrapper fallback.)
  #
  # Distribution: Raw executable released as GitHub Release artifact (no archive).
  # URL format: stable and predictable across releases.
  # Source: https://github.com/vercel-labs/agent-browser/releases/tag/v${agentBrowserVersion}
  #
  # Chromium: pkgs.chromium is Linux-only (meta.platforms does not include aarch64-darwin).
  # pkgs.google-chrome is the Nix-managed Chromium-engine browser available on aarch64-darwin
  # (requires allowUnfree = true, which is set in flake.nix).
  # On Darwin, google-chrome installs a wrapper at $out/bin/google-chrome-stable that
  # invokes $out/Applications/Google Chrome.app/Contents/MacOS/Google Chrome.
  # Source: nixpkgs/pkgs/by-name/go/google-chrome/package.nix lines 273-308.
  #
  # AGENT_BROWSER_EXECUTABLE_PATH is scoped to the wrapper script only — not set
  # in shell rc files.

  # pkgs.google-chrome is an unfree package; requires allowUnfree = true
  # (set in flake.nix via nixpkgs.config.allowUnfree)
  chromeBinaryPath = "${pkgs.google-chrome}/bin/google-chrome-stable";

  agentBrowserBin = pkgs.fetchurl {
    url = "https://github.com/vercel-labs/agent-browser/releases/download/v${agentBrowserVersion}/agent-browser-darwin-arm64";
    hash = "sha256-GPevfFerUivYD2QRK41/9D5jqY2YBkuhOpY2OqmuJlA=";
  };

  agentBrowserDrv = pkgs.runCommand "agent-browser-bin-${agentBrowserVersion}" {} ''
    mkdir -p $out/bin
    cp ${agentBrowserBin} $out/bin/agent-browser
    chmod +x $out/bin/agent-browser
  '';

  # Wrapper script that sets AGENT_BROWSER_EXECUTABLE_PATH scoped to agent-browser
  # so it never downloads Chrome on its own, using the system-installed Google Chrome.
  agentBrowser = pkgs.writeShellApplication {
    name = "agent-browser";
    runtimeInputs = [ agentBrowserDrv ];
    text = ''
      # AGENT_BROWSER_EXECUTABLE_PATH points agent-browser at a Nix-managed
      # google-chrome, which avoids the standalone `agent-browser install` step
      # (that step would download Chrome for Testing outside of Nix's control).
      export AGENT_BROWSER_EXECUTABLE_PATH="${chromeBinaryPath}"
      exec agent-browser "$@"
    '';
    meta = {
      description = "Vercel Labs agent-browser — browser automation CLI for agents";
      homepage = "https://github.com/vercel-labs/agent-browser";
    };
  };

in {
  home.packages = [ agentBrowser ];
}
