{ config, pkgs, lib, user, theme, ... }:

let
  # Import shared shellApp helper
  shellApp = import ../lib/shellApp.nix { inherit pkgs lib; moduleDir = ./.; };

  # pre-commit hook for the nixpkgs repo — blocks commits of sensitive files
  nixpkgsPreCommitHook = pkgs.writeShellApplication {
    name = "nixpkgs-pre-commit";
    runtimeInputs = [ pkgs.git pkgs.gnugrep ];
    text = builtins.readFile ./pre-commit.bash;
  };

  # Bound in `let` (rather than only inline under `_module.args`) so this same
  # module can also reference the `workout-autoclean` derivation directly when
  # wiring the launchd agent below, without going through `config._module.args`.
  gitShellapps = rec {
    commit = shellApp {
      name = "commit";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./commit.bash;
      description = "Stage everything and commit with the given message; `commit noop` makes an empty commit";
      sourceFile = "commit.bash";
    };
    pull = shellApp {
      name = "pull";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./pull.bash;
      description = "Git pull that sets the upstream to origin/<branch> first when the branch has none";
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
      text = ''
        export BRANCH_PREFIX="${user.username}"

        ${builtins.readFile ./git-branches.bash}
      '';
      description = "Interactive branch selector with fzf preview";
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
      sourceFile = "git-kill.bash";
    };
    git-trunk = shellApp {
      name = "git-trunk";
      runtimeInputs = [ pkgs.git ];
      text = builtins.readFile ./git-trunk.bash;
      description = "Switch to trunk branch and pull; `git trunk --print` prints the trunk branch name";
      sourceFile = "git-trunk.bash";
    };
    git-sync = shellApp {
      name = "git-sync";
      runtimeInputs = [ pkgs.git git-trunk ];
      text = builtins.readFile ./git-sync.bash;
      description = "Merge trunk branch into current branch";
      sourceFile = "git-sync.bash";
    };
    git-resume = shellApp {
      name = "git-resume";
      runtimeInputs = [ pkgs.git git-branches pkgs.coreutils ];
      text = builtins.readFile ./git-resume.bash;
      description = "Check out your most recently committed <username>/* branch";
      sourceFile = "git-resume.bash";
    };
    git-tmp = shellApp {
      name = "git-tmp";
      runtimeInputs = [ pkgs.git ];
      text = ''
        export BRANCH_PREFIX="${user.username}"

        ${builtins.readFile ./git-tmp.bash}
      '';
      description = "Create temporary branch for experiments";
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
      runtimeInputs = [ pkgs.git pkgs.coreutils pkgs.fzf pkgs.darwin.trash git-trunk workout-delete ];
      text = builtins.readFile ./workout.bash;
      description = "Create, browse, navigate and clean up git worktrees organized by org/repo/branch";
      sourceFile = "workout.bash";
    };
    workout-delete = shellApp {
      name = "workout-delete";
      runtimeInputs = [ pkgs.git pkgs.coreutils pkgs.darwin.trash ];
      text = builtins.readFile ./workout-delete.bash;
      description = "Delete a git worktree";
      sourceFile = "workout-delete.bash";
    };
    workout-autoclean = shellApp {
      name = "workout-autoclean";
      runtimeInputs = [ pkgs.git pkgs.gh pkgs.coreutils pkgs.darwin.trash ];
      text = builtins.readFile ./workout-autoclean.bash;
      description = "Daily global reaper: trash not-in-use worktrees under ~/worktrees that are >=30 days old (by birth time, even if dirty), OR clean ones >=7 days old with nothing beyond origin's default branch, OR clean ones whose branch's PR merged (no open PR, no commits beyond the merge); skips primary repos, and dirty worktrees under 30 days";
      sourceFile = "workout-autoclean.bash";
    };
  };

in {
  # ============================================================================
  # Git Configuration & Shell Applications
  # ============================================================================
  # Everything git-related: program config + git shellapp definitions
  # ============================================================================

  _module.args.gitShellapps = gitShellapps;

  # ============================================================================
  # Daily worktree reaper (launchd agent)
  # ============================================================================
  # Runs `workout-autoclean` once a day at 5:00pm, unconditionally sweeping
  # every git worktree under ~/worktrees. Reaps worktrees no process is using
  # that are 30+ days old (even with uncommitted changes), OR clean ones 7+ days
  # old with no commits beyond origin's default branch, OR clean ones whose
  # branch's PR has merged (needs `gh` auth). This
  # is the ONLY trigger for workout-autoclean; `workout` does not call it.
  launchd.agents.workout-autoclean = {
    enable = true;
    config = {
      ProgramArguments = [ "${gitShellapps.workout-autoclean}/bin/workout-autoclean" ];
      StartCalendarInterval = { Hour = 17; Minute = 0; };
      # launchd does not source the interactive shell, so a customized
      # WORKTREE_ROOT would otherwise be silently ignored — set it explicitly
      # to match the tool's documented default.
      EnvironmentVariables = {
        WORKTREE_ROOT = "${config.home.homeDirectory}/worktrees";
      };
      # launchd discards stdout/stderr by default, so diagnostic output (skip
      # reasons, trash/prune failures) would otherwise be lost with no record.
      StandardOutPath = "${config.home.homeDirectory}/.local/state/workout-autoclean.launchd.out.log";
      StandardErrorPath = "${config.home.homeDirectory}/.local/state/workout-autoclean.launchd.err.log";
    };
  };

  # nixpkgsPreCommitHook
  # Purpose: Installs a pre-commit hook in the nixpkgs repo that blocks commits
  #          of overconfig.nix and user.nix (personal data / machine-specific secrets)
  # Why: These files are intentionally git-invisible but could still be force-staged
  #      by accident. The hook provides a hard safety net at commit time.
  # When: After writeBoundary (after files are written to disk)
  home.activation.nixpkgsPreCommitHook = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    hook_dir="$HOME/.config/nixpkgs/.git/hooks"
    run mkdir -p "$hook_dir"
    run install -m 755 ${nixpkgsPreCommitHook}/bin/nixpkgs-pre-commit "$hook_dir/pre-commit"
  '';

  programs.git = {
    enable = true;
    lfs.enable = true;
    ignores = [
      ".DS_Store"
      ".tags*"
      "**/.claude/settings.local.json"
      "**/.claude/.perm-tracking.json"
      "**/.claude/scheduled_tasks.lock"
      ".ralph"
      ".agent"
      ".kanban"
      ".scratchpad"
      ".smithers"
    ];
    settings = {
      user = {
        name = user.name;
        email = user.email;
      };
      core.editor = "nvim";
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
