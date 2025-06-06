{
  description = "Home Manager Configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-25.05";
    home-manager = {
      url = "github:nix-community/home-manager/release-25.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nix-index-database = {
      url = "github:Mic92/nix-index-database";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { nixpkgs, home-manager, nix-index-database, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        username = "karlhepler";
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
      in {
        packages.homeConfigurations.${username} = home-manager.lib.homeManagerConfiguration {
          inherit pkgs;
          modules = [
            {
              home = {
                inherit username;
                stateVersion = "25.05"; # This config is compatible with this Home Manager release.
                homeDirectory = "/Users/${username}";
              };
            }
            ./home.nix
            ./overconfig.nix
            nix-index-database.hmModules.nix-index
          ];
        };
      }
    );
}
