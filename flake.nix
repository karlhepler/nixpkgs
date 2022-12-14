{
  description = "Home Manager Configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-index-database.url = "github:Mic92/nix-index-database";
    nix-index-database.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nixpkgs, home-manager, nix-index-database, ... }:
    let
      homeConfig = username: system: {
        ${username} = home-manager.lib.homeManagerConfiguration {
          pkgs = nixpkgs.legacyPackages.${system};
          extraSpecialArgs = { inherit username; };
          modules = [
            ./home.nix
            {
              home = {
                inherit username;
                homeDirectory = "/Users/${username}";
              };
            }
            nix-index-database.hmModules.nix-index
          ];
        };
      };

    in {
      homeConfigurations =
        (homeConfig "karlhepler" "x86_64-darwin") //
        (homeConfig "karl" "aarch64-darwin");
    };
}
