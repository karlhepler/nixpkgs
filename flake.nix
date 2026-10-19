{
  description = "Home Manager Configuration";

  # VERSION: 26.05 - to move to a new release, change nixpkgs.url and home-manager.url
  # below (not stateVersion; see the comment on it).
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nix-index-database = {
      url = "github:Mic92/nix-index-database";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, home-manager, nix-index-database, ... }:
    let
      system = "aarch64-darwin";  # Only macOS ARM

      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };

      # Import user configuration (provides username and homeDirectory)
      user = (import ./user.nix {}).user;
      username = user.username;
    in {
      homeConfigurations.${username} = home-manager.lib.homeManagerConfiguration {
        inherit pkgs;
        modules = [
          {
            home = {
              inherit username;
              # NEVER bump this when upgrading nixpkgs/home-manager. It records the
              # release this machine was first set up with, and changing it silently
              # changes Home Manager defaults. It is not a version to keep current.
              stateVersion = "26.05";
              homeDirectory = user.homeDirectory;
            };
            _module.args = {
              # hms runs this exact home-manager, so the CLI always matches the
              # home-manager modules the flake builds with.
              hmPackage = home-manager.packages.${system}.default;
            };
          }
          ./home.nix
          ./overconfig.nix
          nix-index-database.homeModules.nix-index
        ];
      };

      checks.${system} = {
        check-darwin-trash = pkgs.runCommand "check-darwin-trash" {
          src = ./.;
          nativeBuildInputs = [ pkgs.ripgrep pkgs.bash ];
        } ''
          cd "$src"
          bash modules/system/check-darwin-trash.bash
          touch $out
        '';
      };
    };
}
