{
  description = "Home Manager Configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-24.05";
    home-manager = {
      url = "github:nix-community/home-manager/release-24.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-index-database.url = "github:Mic92/nix-index-database";
    nix-index-database.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nixpkgs, home-manager, nix-index-database, ... }:
    let
      homeConfig = username: system: {
        ${username} = home-manager.lib.homeManagerConfiguration {
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
          extraSpecialArgs = { inherit username; };
          modules = [
            ./home.nix
            {
              home = {
                inherit username;
                homeDirectory = "/Users/${username}";
              };
            }
            ./overconfig.nix
            nix-index-database.hmModules.nix-index
          ];
        };
      };

    in {
      homeConfigurations =
        (homeConfig "karlhepler" "x86_64-darwin") //
        (homeConfig "karlhepler" "aarch64-darwin");
      # homeConfigurations = (homeConfig "karlhepler" "x86_64-darwin");
    };
}
