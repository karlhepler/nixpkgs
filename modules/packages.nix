{ config, pkgs, lib, theme, shellapps, unstable, ... }:

{
  home.packages = with pkgs; [
    # === Core System Tools ===
    bash
    gnused

    # === Shell Enhancement ===
    bat
    difftastic
    fd
    htop
    ripgrep

    # === Development Tools ===
    devbox
    just
    mkcert
    yq

    # === Version Control ===
    git-lfs
    github-copilot-cli

    # === Container & Kubernetes ===
    kubectl
    kubectx
    tilt
    helm-ls

    # === Programming Languages ===
    # Go
    go
    go-tools
    gopls

    # Node.js / JavaScript
    nodejs
    nodePackages.typescript
    nodePackages.typescript-language-server
    yarn

    # Python
    python3
    python3Packages.pip
    pyright
    uv

    # .NET / C#
    dotnet-sdk_9
    omnisharp-roslyn
    csharpier  # Opinionated code formatter for C#

    # Haskell
    ghc  # Glasgow Haskell Compiler
    cabal-install  # Cabal installation tool for managing Haskell software
    stack  # A cross-platform program for developing Haskell projects
    haskell-language-server  # Haskell language server

    # Ruby
    ruby

    # Nix
    nil
    comma

    # Starlark
    starpls  # Language server for Starlark

    # === Language Servers ===
    nodePackages.bash-language-server
    yaml-language-server

    # === Shell Tools ===
    shellcheck

    # === Fonts ===
    nerd-fonts.sauce-code-pro

    # === macOS Utilities ===
    darwin.trash

    # === Shell Applications (from modules/) ===
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
