{ config, pkgs, lib, user, theme, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

in {
  # ============================================================================
  # Git Configuration & Shell Applications
  # ============================================================================
  # Everything git-related: program config + 11 git shellapp definitions
  # ============================================================================

  _module.args.gitShellapps = rec {
    commit = shellApp {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./commit.bash;
      description = "Interactive git commit with conventional commit type selection";
      sourceFile = "commit.bash";
    };
    pull = shellApp {
      name = "pull";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./pull.bash;
      description = "Git pull with automatic stash/unstash";
      sourceFile = "pull.bash";
    };
    push = shellApp {
      name = "push";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./push.bash;
      description = "Push current branch to origin";
      sourceFile = "push.bash";
    };
    save = shellApp {
      name = "save";
      runtimeInputs = [ commit push ];
      text = builtins.readFile ./save.bash;
      description = "Commit and push in one command";
      sourceFile = "save.bash";
    };
    git-branches = shellApp {
      name = "git-branches";
      runtimeInputs = [ pkgs.git pkgs.fzf ];
      text = builtins.readFile ./git-branches.bash;
      description = "Interactive branch selector with fzf preview";
      mainProgram = "git branches";
      sourceFile = "git-branches.bash";
    };
    git-kill = shellApp {
      name = "git-kill";
      runtimeInputs = [
        pkgs.git
        pkgs.git-lfs
        pkgs.coreutils
        pkgs.gnugrep
      ];
      text = builtins.readFile ./git-kill.bash;
      description = "Nuclear option - completely reset repository to clean state";
      mainProgram = "git kill";
      sourceFile = "git-kill.bash";
    };
    git-trunk = shellApp {
      name = "git-trunk";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = builtins.readFile ./git-trunk.bash;
      description = "Switch to trunk branch (auto-detects main or master)";
      mainProgram = "git trunk";
      sourceFile = "git-trunk.bash";
    };
    git-sync = shellApp {
      name = "git-sync";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = builtins.readFile ./git-sync.bash;
      description = "Merge trunk branch into current branch";
      mainProgram = "git sync";
      sourceFile = "git-sync.bash";
    };
    git-resume = shellApp {
      name = "git-resume";
      runtimeInputs = [ pkgs.git git-branches pkgs.coreutils ];
      text = builtins.readFile ./git-resume.bash;
      description = "Resume work on most recently used branch";
      mainProgram = "git resume";
      sourceFile = "git-resume.bash";
    };
    git-tmp = shellApp {
      name = "git-tmp";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./git-tmp.bash;
      description = "Create temporary branch for experiments";
      mainProgram = "git tmp";
      sourceFile = "git-tmp.bash";
    };
    groot = shellApp {
      name = "groot";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./groot.bash;
      description = "Navigate to git repository root directory";
      sourceFile = "groot.bash";
    };
    workout = shellApp {
      name = "workout";
      runtimeInputs = [ pkgs.git pkgs.coreutils pkgs.gnused pkgs.fzf ];
      text = builtins.readFile ./workout.bash;
      description = "Create and navigate git worktrees organized by org/repo/branch";
      sourceFile = "workout.bash";
    };
    workout-delete = shellApp {
      name = "workout-delete";
      runtimeInputs = [ pkgs.git pkgs.coreutils ];
      text = builtins.readFile ./workout-delete.bash;
      description = "Delete a git worktree";
      sourceFile = "workout-delete.bash";
    };
  };

  programs.git = {
    enable = true;
    ignores = [
      ".DS_Store"
      ".tags*"
      "**/.claude/settings.local.json"
      ".ralph"
      ".agent"
    ];
    settings = {
      user = {
        name = user.name;
        email = user.email;
      };
      core.editor = "vim";
      diff.tool = "vimdiff";
      merge.tool = "vimdiff";
      difftool.prompt = false;
      push.default = "current";
      init.defaultBranch = "main";
      pull.rebase = false;
      alias = {
        who = "blame -w -C -C -C";
        difft = "-c diff.external=difft diff";
        logt = "-c diff.external=difft log -p --ext-diff";
        showt = "-c diff.external=difft show --ext-diff";
      };
    };
  };
}
