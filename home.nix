{ config, pkgs, ... }:

{
  # Home Manager needs a bit of information about you and the
  # paths it should manage.
  home.username = "karlhepler";
  home.homeDirectory = "/Users/karlhepler";

  # Home Packages
  # https://search.nixos.org/packages
  home.packages = with pkgs; [
    cowsay
    fd
    ripgrep
  ];

  # This value determines the Home Manager release that your
  # configuration is compatible with. This helps avoid breakage
  # when a new Home Manager release introduces backwards
  # incompatible changes.
  #
  # You can update Home Manager without changing this value. See
  # the Home Manager release notes for a list of state version
  # changes in each release.
  home.stateVersion = "22.05";

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  # Program Modules
  # https://nix-community.github.io/home-manager/options.html

  programs.kitty = {
    enable = true;
  };

  programs.fish = {
    enable = true;
    shellAliases = {
      desk = "cd ~/Desktop";
      down = "cd ~/Downloads";
      docs = "cd ~/Documents";
      pics = "cd ~/Pictures";
      hms = "home-manager switch --flake ~/.config/nixpkgs#karlhepler";
      hme = "vim ~/.config/nixpkgs/home.nix";
      hm = "cd ~/.config/nixpkgs";
    };
  };

  programs.fzf = {
    enable = true;
    enableFishIntegration = true;
  };

  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    vimdiffAlias = true;

    plugins = with pkgs.vimPlugins; [
      vim-sensible
      vim-surround
      vim-signify
      vim-pasta
      auto-pairs
      vim-commentary
      {
        plugin = vim-vinegar;
	      config = "let g:netrw_list_hide = '\(^\|\s\s\)\zs\.\S\+'";
      }
      vim-repeat
      vim-fugitive
      {
        plugin = vim-polyglot;
        config = ''
          let g:vim_json_syntax_conceal = 0
          let g:vim_markdown_conceal = 0
        '';
      }
    ];
    
    extraConfig = ''
      let mapleader = ','
      imap jk <esc>
    '';
  };
}
