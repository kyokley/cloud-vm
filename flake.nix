{
  description = "Standalone Home Manager configuration for an exe.dev Linux VM";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
    }:
    let
      target = import ./config/target.nix;
      linuxSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      devSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forSystems = systems: function: nixpkgs.lib.genAttrs systems (system: function system);
      homeFor =
        system:
        home-manager.lib.homeManagerConfiguration {
          pkgs = import nixpkgs { inherit system; };
          modules = [ ./config/home.nix ];
          extraSpecialArgs = { inherit target; };
        };
      devShellFor =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        pkgs.mkShell {
          packages = with pkgs; [
            bash
            python3
            shellcheck
            nixfmt
          ];
        };
    in
    {
      lib.target = target;

      homeConfigurations.vm = homeFor target.system;

      packages = forSystems linuxSystems (system: {
        activationPackage = (homeFor system).activationPackage;
      });

      devShells = forSystems devSystems (system: {
        default = devShellFor system;
      });

      formatter = forSystems devSystems (system: (import nixpkgs { inherit system; }).nixfmt);
    };
}
