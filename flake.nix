{
  description = "Home Manager Configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, home-manager, ... }: {
    defaultPackage.x86_64-darwin = home-manager.defaultPackage.x86_64-darwin;

    homeConfigurations = {
      karlhepler = home-manager.lib.homeManagerConfiguration {
        system = "x86_64-darwin";
	homeDirectory = "/Users/karlhepler";
	username = "karlhepler";
	configuration.imports = [ ./home.nix ];
      };
    };
  };
}
