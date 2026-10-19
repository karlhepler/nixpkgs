{ config, pkgs, lib, theme, shellapps, ... }:

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
    yq-go

    # === Version Control ===
    codeowners
    gh
    pinact  # Pin GitHub Actions workflow references to immutable commit SHAs

    # === Security & Secrets Management ===
    _1password-cli  # 1Password command-line tool

    # === Container & Kubernetes ===
    kubectl
    kubectx

    # === Programming Languages ===
    # Go
    go
    go-tools

    # Node.js / JavaScript
    nodejs_24
    typescript
    yarn

    # Python
    python3
    python3Packages.pip
    python3Packages.pytest
    uv

    # .NET / C#
    dotnet-sdk_10
    csharpier  # Opinionated code formatter for C#

    # Haskell
    ghc  # Glasgow Haskell Compiler
    cabal-install  # Cabal installation tool for managing Haskell software

    # Ruby
    ruby

    # Nix
    comma

    # === Shell Tools ===
    fswatch  # File change monitor (macOS kqueue backend)
    shellcheck

    # === Fonts ===
    nerd-fonts.sauce-code-pro
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
