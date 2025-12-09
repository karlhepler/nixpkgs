{ config, pkgs, lib, theme, shellapps, ... }:

{
  # ============================================================================
  # Neovim Configuration & Plugins
  # ============================================================================
  # Everything Neovim: editor config + 30+ plugins + LSP servers
  # ============================================================================

  imports = [
    ./plugins.nix
  ];

  _module.args.neovimShellapps = rec {
    # Future expansion for Neovim-related CLIs
    # Only add if genuinely useful (YAGNI)
  };

  # ============================================================================
  # Core Neovim Program Configuration
  # ============================================================================

  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    vimdiffAlias = true;

    # Load reorganized vimrc with clear sections
    extraConfig = builtins.readFile ./vimrc;

    # Load all Lua configs via concatenation (with variable substitution)
    # This ensures Nix can substitute paths in LSP configs before Neovim loads them
    extraLuaConfig = builtins.replaceStrings
      [
        "@typescriptLanguageServer@"
        "@bashLanguageServer@"
        "@omnisharpRoslyn@"
      ]
      [
        "${pkgs.nodePackages.typescript-language-server}"
        "${pkgs.nodePackages.bash-language-server}"
        "${pkgs.omnisharp-roslyn}"
      ]
      (builtins.concatStringsSep "\n" [
        (builtins.readFile ./lua/core/treesitter.lua)
        (builtins.readFile ./lua/core/lsp-global.lua)
        (builtins.readFile ./lua/core/formatters.lua)
        (builtins.readFile ./lua/lsp/typescript.lua)
        (builtins.readFile ./lua/lsp/go.lua)
        (builtins.readFile ./lua/lsp/python.lua)
        (builtins.readFile ./lua/lsp/yaml.lua)
        (builtins.readFile ./lua/lsp/helm.lua)
        (builtins.readFile ./lua/lsp/rust.lua)
        (builtins.readFile ./lua/lsp/starlark.lua)
        (builtins.readFile ./lua/lsp/csharp.lua)
        (builtins.readFile ./lua/lsp/bash.lua)
        (builtins.readFile ./lua/lsp/godot.lua)
        (builtins.readFile ./lua/lsp/haskell.lua)
        (builtins.readFile ./lua/lsp/nix.lua)
      ]);
  };
}
