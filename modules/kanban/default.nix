{ config, pkgs, lib, ... }:

let
  kanbanScript = pkgs.writers.writePython3Bin "kanban" {
    flakeIgnore = [ "E265" "E501" "W503" ];  # Ignore shebang, line length, line break warnings
  } (builtins.readFile ./kanban.py);

in {
  # ============================================================================
  # Kanban CLI - File-based kanban board for agent coordination
  # ============================================================================
  # Cards are markdown files in column folders, numbered globally
  # Enables subagents to coordinate by reading/writing to shared filesystem
  # ============================================================================

  _module.args.kanbanShellapps = {
    kanban = kanbanScript // {
      meta = {
        description = "File-based kanban board CLI for agent coordination";
        mainProgram = "kanban";
        homepage = "${builtins.toString ./.}/kanban.py";
      };
    };
  };
}
