{
  description = "Karl's Home Manager Flake";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = inputs: {
    defaultPackage.x86_64-darwin = home-manager.defaultPackage.x86_64-darwin;

    homeConfigurations = {
      karlhepler = inputs.home-manager.lib.homeManagerConfiguration {
        system = "x86_64-darwin";
	homeDirectory = "/Users/karlhepler";
	username = "karlhepler";
	configuration.imports = [ ./home.nix ];
      };
    };
  };
}
