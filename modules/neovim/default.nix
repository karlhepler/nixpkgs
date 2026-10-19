{ pkgs, user, ... }:

{
  # ============================================================================
  # Neovim Configuration & Plugins
  # ============================================================================
  # Everything Neovim: editor config, plugins (plugins.nix), language servers and
  # formatters, and the Lua config under plugin/
  # ============================================================================

  imports = [
    ./plugins.nix
  ];

  # ============================================================================
  # Core Neovim Program Configuration
  # ============================================================================

  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    vimdiffAlias = true;

    # Load reorganized vimrc with clear sections
    extraConfig = builtins.replaceStrings [ "@username@" ] [ user.username ] (builtins.readFile ./vimrc);

    # Language servers and formatters. These are on Neovim's PATH only, not the shell's.
    # The language toolchains (go, node, python, dotnet, ...) stay in modules/packages.nix.
    extraPackages = with pkgs; [
      # Language servers
      bash-language-server
      gopls
      helm-ls
      lua-language-server
      nil
      omnisharp-roslyn
      pyright
      rust-analyzer
      starpls
      typescript-language-server
      vscode-langservers-extracted  # jsonls
      yaml-language-server

      # Formatters (conform.nvim; csharpier and rustfmt come from the shell's PATH)
      nixfmt
      prettierd
      shfmt
      stylua
    ];
  };

  # Lua config as native Neovim startup scripts. Each file in plugin/ is sourced
  # independently, so an error in one cannot stop the others from loading.
  xdg.configFile."nvim/plugin".source = ./plugin;
}
