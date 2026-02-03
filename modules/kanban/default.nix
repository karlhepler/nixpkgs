{ config, pkgs, lib, ... }:

let
  homeDirectory = config.home.homeDirectory;

  # Python with watchdog package for file watching
  pythonWithPackages = pkgs.python3.withPackages (ps: with ps; [
    watchdog
  ]);

  # Create kanban package with completion file bundled
  kanbanPackage = pkgs.stdenv.mkDerivation {
    name = "kanban";
    version = "1.0.0";
    src = ./.;

    buildInputs = [ pythonWithPackages ];

    buildPhase = ''
      # Use python3 writer to create the script
      ${pythonWithPackages}/bin/python3 -m py_compile kanban.py
    '';

    installPhase = ''
      mkdir -p $out/bin
      mkdir -p $out/share/zsh/site-functions

      # Install the Python script
      cat > $out/bin/kanban << 'EOF'
      #!${pythonWithPackages}/bin/python3
      EOF
      cat kanban.py >> $out/bin/kanban
      chmod +x $out/bin/kanban

      # Install the completion file
      cp _kanban $out/share/zsh/site-functions/_kanban
    '';

    meta = {
      description = "File-based kanban board CLI for agent coordination";
      mainProgram = "kanban";
      homepage = "${builtins.toString ./.}/kanban.py";
    };
  };

in {
  # ============================================================================
  # Kanban CLI - File-based kanban board for agent coordination
  # ============================================================================
  # Cards are markdown files in column folders, numbered globally
  # Enables subagents to coordinate by reading/writing to shared filesystem
  # ============================================================================

  _module.args.kanbanShellapps = {
    kanban = kanbanPackage;
  };
}
