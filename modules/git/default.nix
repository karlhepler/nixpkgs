{ config, pkgs, lib, user, theme, ... }:

{
  # ============================================================================
  # Git Configuration & Shell Applications
  # ============================================================================
  # Everything git-related: program config + 11 git shellapp definitions
  # ============================================================================

  _module.args.gitShellapps = rec {
    commit = pkgs.writeShellApplication {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./commit.bash;
    };
    pull = pkgs.writeShellApplication {
      name = "pull";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./pull.bash;
    };
    push = pkgs.writeShellApplication {
      name = "push";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./push.bash;
    };
    save = pkgs.writeShellApplication {
      name = "save";
      runtimeInputs = [ commit push ];
      text = builtins.readFile ./save.bash;
    };
    git-branches = pkgs.writeShellApplication {
      name = "git-branches";
      runtimeInputs = [ pkgs.git pkgs.fzf ];
      text = builtins.readFile ./git-branches.bash;
    };
    git-kill = pkgs.writeShellApplication {
      name = "git-kill";
      runtimeInputs = [
        pkgs.git
        pkgs.git-lfs
        pkgs.coreutils
        pkgs.gnugrep
      ];
      text = builtins.readFile ./git-kill.bash;
    };
    git-trunk = pkgs.writeShellApplication {
      name = "git-trunk";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = builtins.readFile ./git-trunk.bash;
    };
    git-sync = pkgs.writeShellApplication {
      name = "git-sync";
      runtimeInputs = [ pkgs.git pkgs.gnused ];
      text = builtins.readFile ./git-sync.bash;
    };
    git-resume = pkgs.writeShellApplication {
      name = "git-resume";
      runtimeInputs = [ pkgs.git git-branches pkgs.coreutils ];
      text = builtins.readFile ./git-resume.bash;
    };
    git-tmp = pkgs.writeShellApplication {
      name = "git-tmp";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./git-tmp.bash;
    };
    groot = pkgs.writeShellApplication {
      name = "groot";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./groot.bash;
    };
    workout = pkgs.writeShellApplication {
      name = "workout";
      runtimeInputs = [ pkgs.git pkgs.coreutils pkgs.gnused pkgs.fzf ];
      text = builtins.readFile ./workout.bash;
    };
  };

  programs.git = {
    enable = true;
    ignores = [ ".DS_Store" ".tags*" ".claude/settings.local.json" ];
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
