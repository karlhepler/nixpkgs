{ pkgs, lib, moduleDir }:

# Helper to create shell application with metadata
# Used by all modules that define custom shell scripts (git, claude, system, tmux)
# moduleDir should be the calling module's directory (e.g., ./. from modules/git/default.nix)
{ name, runtimeInputs, text, description, mainProgram ? name, sourceFile ? null }:
  let
    homepage = if sourceFile != null
      then "${builtins.toString moduleDir}/${sourceFile}"
      else null;
  in (pkgs.writeShellApplication {
    inherit name runtimeInputs text;
  }) // {
    meta = {
      inherit description mainProgram;
    } // lib.optionalAttrs (homepage != null) { inherit homepage; };
  }
