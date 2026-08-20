{ config, pkgs, lib, ... }:

let
  flags = import ../../flags.nix;

  # ==========================================================================
  # Managed Claude Code user settings
  # ==========================================================================
  # Source of truth for the ~/.claude/settings.json keys this repo owns. Keys not
  # listed here are left untouched — see the claudeCodeSettings activation below.
  managedSettings = {
    # Opus while planning, Sonnet for execution.
    model = "opusplan";

    # settings.json accepts low|medium|high|xhigh ("max"/"ultracode" are session-only).
    effortLevel = "xhigh";

    # Alt-screen renderer with virtualized scrollback: mouse-wheel scrolling,
    # scroll acceleration, page jumps, jump-to-bottom. Pinned explicitly so the
    # fullscreen upsell counter can't decide this for us.
    tui = "fullscreen";
  };

  # writeText rather than the runCommand+echo pattern used by the legacy module:
  # echo '${builtins.toJSON ...}' breaks on any single quote in a value.
  managedSettingsJson =
    pkgs.writeText "claude-code-settings.json" (builtins.toJSON managedSettings);
in {
  # claudeCodeSettings
  # Purpose: Assert this repo's owned keys in ~/.claude/settings.json
  # Why: Claude Code (/tui, /config, /plugin) and Maze tooling both write that file,
  #      so it must stay a real writable file — merge our keys in, never replace it
  # When: After writeBoundary, and after the legacy claudeSettings entry if that
  #       module is also enabled (it rm -f's the whole file, so it must run first)
  # Dependencies: pkgs.jq
  home.activation.claudeCodeSettings = lib.hm.dag.entryAfter
    ([ "writeBoundary" ] ++ lib.optional flags.claude.enable "claudeSettings") ''
      if [[ ! -f ~/.claude/settings.json ]]; then
        $DRY_RUN_CMD mkdir -p ~/.claude
        $DRY_RUN_CMD echo '{}' > ~/.claude/settings.json
      fi

      # Recursive merge; managed keys win, everything else is preserved
      $DRY_RUN_CMD ${pkgs.jq}/bin/jq -s '.[0] * .[1]' \
        ~/.claude/settings.json ${managedSettingsJson} > ~/.claude/settings.json.tmp

      $DRY_RUN_CMD mv ~/.claude/settings.json.tmp ~/.claude/settings.json
      $DRY_RUN_CMD chmod 644 ~/.claude/settings.json
    '';

  # ==========================================================================
  # Managed Claude Code user memory + skills
  # ==========================================================================
  # Plain home.file symlinks, not activation-copies — unlike settings.json, nothing
  # writes to these paths at runtime. Verified: Claude Code's old "#"-shortcut memory
  # append was removed upstream (replaced by auto-memory under
  # ~/.claude/projects/<project>/memory/, which is a different path entirely); the one
  # remaining writer, `/import --scope user`, resolves the symlink and fails loudly
  # (EROFS/EACCES) rather than silently replacing it. ~/.claude/skills/ has no writer
  # at all today. A read-only store symlink is therefore safe for both.
  home.file.".claude/CLAUDE.md".source = ./claude-memory.md;
  home.file.".claude/skills/decision-protocol/SKILL.md".source = ./decision-protocol-skill.md;
  home.file.".claude/skills/git-sync/SKILL.md".source = ./git-sync-skill.md;
}
