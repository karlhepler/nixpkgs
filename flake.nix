{
  description = "Home Manager Configuration";

  # VERSION: 25.11 - Update nixpkgs.url and home-manager.url below to change version
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-25.11";
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager/release-25.11";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nix-index-database = {
      url = "github:Mic92/nix-index-database";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, nixpkgs-unstable, home-manager, nix-index-database, ... }:
    let
      # Release version - keep in sync with nixpkgs.url and home-manager.url above
      releaseVersion = "25.11";

      system = "aarch64-darwin";  # Only macOS ARM

      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };
      unstable = import nixpkgs-unstable {
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
              stateVersion = releaseVersion;
              homeDirectory = user.homeDirectory;
            };
            _module.args = { inherit unstable; };
          }
          ./home.nix
          ./user.nix
          ./overconfig.nix
          nix-index-database.homeModules.nix-index
        ];
      };
    };
}
