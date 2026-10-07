{ config, pkgs, lib, unstable, ... }:

let
  # Import cross-cutting concerns
  user = (import ./user.nix {}).user;
  theme = (import ./modules/theme.nix { inherit lib; }).theme;
  flags = import ./flags.nix;

in {
  # Import all modules
  imports = [
    # Complex modules (with scripts)
    ./modules/system      # System tools (hms shellapp)
    ./modules/git         # Git config + 11 git shellapps
    ./modules/neovim      # Neovim editor + 30+ plugins

    # Simple modules (no scripts)
    ./modules/alacritty.nix  # Alacritty terminal emulator
    ./modules/direnv.nix     # Direnv configuration + activation
    ./modules/environment.nix # Environment variables
    ./modules/packages.nix   # Packages + simple programs
    ./modules/tmux           # Tmux terminal multiplexer
    ./modules/zsh.nix        # Zsh configuration + activation
  ] ++ lib.optionals flags.claudeCode.enable [
    # Claude Code user settings — gated by flags.nix claudeCode.enable
    ./modules/claude-code    # Managed keys in ~/.claude/settings.json
  ] ++ lib.optionals flags.claude.enable [
    # Claude Code configuration — gated by flags.nix claude.enable
    ./modules/claude        # Claude hooks + ~35 claude shellapps
    ./modules/kanban        # Kanban CLI for agent coordination
    ./modules/claudit       # On-demand metrics viewer + claudit shellapp + metrics hook
    ./modules/agent-browser # Agent browser (Vercel Labs AI web agent)
  ];

  # Aggregate shellapps from modules and pass to all modules
  _module.args = let
    # Dynamically merge all shellapps from modules
    shellapps =
      (config._module.args.systemShellapps or {})
      // (config._module.args.gitShellapps or {})
      // (config._module.args.claudeShellapps or {})
      // (config._module.args.neovimShellapps or {})
      // (config._module.args.tmuxShellapps or {})
      // (config._module.args.kanbanShellapps or {})
      // (config._module.args.clauditShellapps or {});

    # Context7 API key for Claude MCP configuration
    # Set in overconfig.nix via: home.sessionVariables.CONTEXT7_API_KEY = "...";
    context7ApiKey = config.home.sessionVariables.CONTEXT7_API_KEY or null;
  in { inherit user theme shellapps context7ApiKey; };

  # Activation hooks to make git ignore changes to user.nix and overconfig.nix
  home.activation.gitIgnoreUserChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --skip-worktree user.nix
  '';

  home.activation.gitIgnoreOverconfigChanges = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.git}/bin/git -C ~/.config/nixpkgs update-index --skip-worktree overconfig.nix
  '';

  # Validate user.nix doesn't have placeholders
  assertions = let
    isPlaceholder = value: value == "CHANGE_ME" || value == "";
    hasPlaceholders =
      (isPlaceholder user.name) ||
      (isPlaceholder user.email) ||
      (isPlaceholder user.username) ||
      (lib.hasInfix "CHANGE_ME" user.homeDirectory);
  in [
    {
      assertion = !hasPlaceholders;
      message = ''
        user.nix contains placeholder values. Please edit user.nix and set:
        - name (for git user.name)
        - email (for git user.email)
        - username (for system username)
        - homeDirectory (derived from username)

        Run: hmu
      '';
    }
  ];

  # Disable Home Manager news display (fixes flake attribute error)
  news.display = "silent";

  fonts.fontconfig.enable = true;


  # Automatically run the garbage collector weekly. Without --delete-older-than,
  # old Home Manager/profile generations are never removed and keep every store
  # path they reference alive, so the store grows without bound.
  nix.gc.automatic = true;
  launchd.agents.nix-gc.config = {
    # Not `nix.gc.options`: on Darwin, Home Manager passes that string as ONE
    # argv element, and nix-collect-garbage rejects '--delete-older-than 30d'
    # (and '--delete-older-than=30d') as an unrecognised flag.
    ProgramArguments = lib.mkForce [
      "${pkgs.nix}/bin/nix-collect-garbage"
      "--delete-older-than"
      "30d"
    ];
    # launchd discards stdout/stderr by default, so a failed run leaves no record.
    StandardOutPath = "${config.home.homeDirectory}/.local/state/nix-gc.launchd.out.log";
    StandardErrorPath = "${config.home.homeDirectory}/.local/state/nix-gc.launchd.err.log";
  };

  # Let Home Manager install and manage itself.
  programs.home-manager.enable = true;

  # Program Modules
  # https://nix-community.github.io/home-manager/options.html

}
