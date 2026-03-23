{ config, pkgs, lib, theme, shellapps, unstable, ... }:

let
  # typora - Markdown editor for macOS
  # NOTE: nixpkgs provides typora only for Linux (x86_64-linux).
  # macOS users require a custom derivation that downloads the DMG directly from Typora's servers.
  # Cannot be sourced from pkgs-unstable.typora due to platform limitations.
  # https://typora.io
  typora = pkgs.stdenv.mkDerivation rec {
    pname = "typora";
    version = "1.12.6";

    src = pkgs.fetchurl {
      url = "https://downloads.typora.io/mac/Typora-${version}.dmg";
      sha256 = "sha256-JJmW45QayMlia6rnOecW+JPfFPEijhOkqcgZFzaXS4g=";
    };

    sourceRoot = ".";

    nativeBuildInputs = [ pkgs.undmg ];

    installPhase = ''
      mkdir -p "$out/Applications"
      cp -R "Typora.app" "$out/Applications/Typora.app"
    '';

    meta = {
      description = "A minimal Markdown editor and reader";
      homepage = "https://typora.io";
      platforms = [ "aarch64-darwin" "x86_64-darwin" ];
      license = pkgs.lib.licenses.unfree;
    };
  };

  # pinact - GitHub Actions SHA-pinning CLI (not in nixpkgs)
  # https://github.com/suzuki-shunsuke/pinact
  pinact = pkgs.stdenv.mkDerivation {
    pname = "pinact";
    version = "3.9.0";

    src = pkgs.fetchurl {
      url = "https://github.com/suzuki-shunsuke/pinact/releases/download/v3.9.0/pinact_darwin_arm64.tar.gz";
      sha256 = "sha256-I8ik7aj9eUnIy7HP5vPQEnlAL+YgHpywqQRHpez974k=";
    };

    sourceRoot = ".";

    installPhase = ''
      mkdir -p $out/bin
      cp pinact $out/bin/pinact
      chmod +x $out/bin/pinact
    '';

    meta = {
      description = "CLI tool to pin GitHub Actions workflow references to immutable commit SHAs";
      homepage = "https://github.com/suzuki-shunsuke/pinact";
      mainProgram = "pinact";
      platforms = [ "aarch64-darwin" ];
    };
  };

in

{
  home.packages = with pkgs; [
    # === Core System Tools ===
    bash
    coreutils
    gnused

    # === Shell Enhancement ===
    bat
    difftastic
    fd
    htop
    ripgrep

    # === Development Tools ===
    devbox
    jq
    just
    mkcert
    typora  # Markdown editor
    yq-go

    # === Version Control ===
    codeowners
    git-lfs
    graphite-cli  # Stacked PR workflow CLI (gt command)
    unstable.gh  # GitHub CLI from unstable channel
    pinact  # Pin GitHub Actions workflow references to immutable commit SHAs

    # === Security & Secrets Management ===
    _1password-cli  # 1Password command-line tool

    # === Container & Kubernetes ===
    colima  # Docker runtime for Ralph Orchestrator
    kubectl
    kubectx
    helm-ls

    # === Programming Languages ===
    # Go
    go
    go-tools
    gopls

    # Node.js / JavaScript
    nodejs_24
    nodePackages.typescript
    nodePackages.typescript-language-server
    yarn

    # Python
    python3
    python3Packages.pip
    python3Packages.watchdog
    python3Packages.wcwidth
    pyright
    uv

    # .NET / C#
    dotnet-sdk_10
    omnisharp-roslyn
    csharpier  # Opinionated code formatter for C#

    # Haskell
    ghc  # Glasgow Haskell Compiler
    cabal-install  # Cabal installation tool for managing Haskell software
    haskell-language-server  # Haskell language server

    # Ruby
    ruby

    # Nix
    nil
    comma

    # Rust
    rust-analyzer

    # Starlark
    starpls  # Language server for Starlark

    # === Language Servers ===
    nodePackages.bash-language-server
    yaml-language-server

    # === Shell Tools ===
    shellcheck

    # === Fonts ===
    nerd-fonts.sauce-code-pro

    # === Shell Applications (from modules/) ===
  ] ++ lib.optionals pkgs.stdenv.isDarwin [
    # macOS-only utilities
    pkgs.darwin.trash
    pkgs.duti  # Set default app associations on macOS
] ++ (builtins.attrValues shellapps);

  # ============================================================================
  # Simple Program Configurations
  # ============================================================================
  # Programs with minimal configuration (too simple for their own module files)

  programs.fzf = {
    enable = true;
    enableZshIntegration = true;
    tmux.enableShellIntegration = true;
  };

  programs.neovide = {
    enable = true;
    package = unstable.neovide;
    settings = {
      fork = false;
      frame = "full";
      font = {
        normal = [theme.font.family];
        size = theme.font.sizeFloat;
      };
    };
  };

  programs.starship = {
    enable = true;
    enableZshIntegration = true;
    settings = {
      # Configure prompt format to place custom directory at the beginning
      format = "$custom$all";

      # Disable default directory module
      directory.disabled = true;

      # Custom directory module that shows brackets + yellow when in worktree
      custom.directory = {
        description = "Directory with worktree indicator";
        command = ''
          dir=$(basename "$PWD")
          if [ "$PWD" = "$HOME" ]; then
            dir="~"
          fi
          if test -f .git; then
            printf '\033[1;33m[%s]\033[0m' "$dir"
          else
            printf '\033[1;36m%s\033[0m' "$dir"
          fi
        '';
        when = true;
        format = "$output ";
      };
    };
  };

  programs.zoxide = {
    enable = true;
    enableZshIntegration = true;
    options = [ "--cmd" "cd" ];
  };

  programs.nix-index = {
    enable = true;
    enableZshIntegration = true;
  };
}
