{ config, lib, ... }:

{
  # ============================================================================
  # Gap-free Nix profile switch
  # ============================================================================
  # Home Manager's own installPackages step (modules/home-environment.nix) runs
  # `nix profile remove home-manager-path` and only THEN `nix profile install`. Each is
  # its own profile generation, and the first leaves ~/.nix-profile/bin without any of
  # Home Manager's tools (tmux, nvim, git, ...) until the second lands, a fraction of a
  # second later. Anything that runs in that window fails with "No such file or
  # directory". Every `hms` hit it.
  #
  # This replaces that step with add-first, remove-second, so the profile always
  # contains the tools:
  #   1. add the new home-manager-path (the old one is still installed)
  #   2. remove the old one by store path
  #
  # The two entries provide the same files, and Nix refuses equal-priority entries that
  # collide. So the new entry takes a different priority from the one it replaces,
  # alternating 5 and 4 from run to run. While both are installed, either winning is
  # fine: step 2 leaves only the new one.
  #
  # Uses `nixProfileList` and `_iError` from Home Manager's activation library, the
  # same helpers the step it replaces uses.
  home.activation.installPackages = lib.mkForce (lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    new=${config.home.path}
    old="$(nixProfileList home-manager-path)"

    if [[ "$old" != "$new" ]]; then
      priority=5
      oldPriority="$(nix profile list --json \
        | jq -r '.elements[] | select(.storePaths | any(endswith("home-manager-path"))) | .priority')"
      if [[ "$oldPriority" == 5 ]]; then
        priority=4
      fi

      if ! run nix profile add --priority "$priority" "$new"; then
        _iError $'Nix failed to add the new Home Manager profile.\n\nIf a package installed with `nix profile` conflicts, list it with\n\n    nix profile list\n\nand remove it with `nix profile remove`, then activate again.'
        exit 1
      fi

      if [[ -n "$old" ]]; then
        run nix profile remove "$old"
      fi
    fi
  '');
}
