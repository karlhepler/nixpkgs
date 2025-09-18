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
  };

  outputs = { nixpkgs, home-manager, nix-index-database, ... }:
    let
      system = "aarch64-darwin";  # Only macOS ARM
      username = "karlhepler";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };
    in {
      homeConfigurations.${username} = home-manager.lib.homeManagerConfiguration {
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
          nix-index-database.homeModules.nix-index
        ];
      };
    };
}
