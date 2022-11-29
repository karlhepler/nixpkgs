{ config, pkgs, ... }:

{
  # Home Manager needs a bit of information about you and the
  # paths it should manage.
  home.username = "karlhepler";
  home.homeDirectory = "/Users/karlhepler";

  # Home Packages
  # https://search.nixos.org/packages
  home.packages = with pkgs; [
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
    darwinLaunchOptions = [
      "--single-instance"
    ];
    keybindings = {
      "cmd+enter" = "toggle_fullscreen";
      "cmd+n" = "new_os_window_with_cwd";
      "cmd+t" = "new_tab_with_cwd";
      "cmd+d" = "launch --cwd=current --location=vsplit";
      "cmd+shift+d" = "launch --cwd=current --location=hsplit";
    };
    settings = {
      enabled_layouts = "splits";
      macos_traditional_fullscreen = "yes";
      shell = "fish --login --interactive";
      editor = "nvim";
      cursor_shape = "block";
      cursor_blink_interval = 0;
      shell_integration = "no-cursor";
    };
    font = {
      package = (pkgs.nerdfonts.override { fonts = [ "SourceCodePro" ]; });
      name = "SauceCodePro Nerd Font Mono";
      size = 18;
    };
    theme = "Tokyo Night Storm";
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

  programs.starship = {
    enable = true;
    enableFishIntegration = true;
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
      tokyonight-nvim
    ];
    
    extraConfig = ''
      set nocompatible

      let mapleader=','
      imap jk <esc>

      set background=dark
      colorscheme tokyonight-storm

      set shell=fish " use fish for :term
      set grepprg=rg\ --vimgrep " use ripgrep for :grep

      " no swap files or backup files
      set noswapfile
      set nobackup
      set nowritebackup

      " allow hidden buffers for easier multi-file editing
      set hidden

      " detect plugins and indentation per filetype
      filetype plugin indent on

      " sensible split defaults
      set splitbelow
      set splitright

      " no annoying bells
      set noerrorbells
      set visualbell

      " highlight current line (not supported in kitty)
      set cursorline

      " always show at least 1 line above/below cursor
      set scrolloff=1

      " disable word wrapping
      set nowrap
      set textwidth=0
      set wrapmargin=0
      set formatoptions-=t

      " show the ruler
      set ruler

      " ignore case when searching lowercase
      set ignorecase
      set smartcase

      " when a file has changed outside of vim, automatically read it again
      set autoread

      " always show sign column
      set signcolumn=yes

      " tame horizontal scroll
      set sidescroll=1

      " no double spaces after periods when joining lines
      set nojoinspaces

      " search highlighting off
      nmap <silent> <leader><space> :nohlsearch<cr>

      " reload current file
      nmap <silent> <leader>f :e!<cr>

      " comma + enter goes to insert mode
      nnoremap ,<cr> A,<cr>

      " highlight word without jump in normal mode
      nmap <c-w><c-w> :keepjumps normal! mi*`i<cr>

      " tame the half-page scroller
      nmap <c-d> 5j5<c-e>
      vmap <c-d> 5j5<c-e>
      nmap <c-u> 5k5<c-y>
      vmap <c-u> 5k5<c-y>

      " quickfix mappings
      nmap <up> :copen<cr>
      nmap <down> :cclose<cr>
      nmap <left> :cprevious<cr>
      nmap <right> :cnext<cr>

      " copy relative & absolute paths to system clipboard
      nmap <silent> <LEADER>cf :let @+ = expand("%")<CR>
      nmap <silent> <LEADER>cF :let @+ = expand("%:p")<CR>

      " horizontal center to cursor position
      nnoremap <silent> zm zszH

      " open terminal at current buffer path
      map <C-T> <ESC>:let $BUFPATH=expand('%:p:h')<CR>:terminal<CR>cd $BUFPATH && clear<CR>

      " helpful split views
      nmap <C-W>} =42>
      nmap <C-W>{ =42<
      nmap <C-W>O onH{l

      " not quite high and low
      noremap H 3H
      noremap L 3L

      " disable fancy cursor
      set guicursor=
    '';
  };
}
