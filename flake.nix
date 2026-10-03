{
  description = "Standalone Home Manager configuration for an exe.dev Linux VM";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    caveman = {
      url = "github:JuliusBrussee/caveman";
      flake = false;
    };
  };

  outputs = inputs: let
    target = import ./config/target.nix;
    homeFor = {pkgs, ...}:
      inputs.home-manager.lib.homeManagerConfiguration {
        inherit pkgs;
        modules = [./config/home.nix];
        extraSpecialArgs = {inherit target inputs;};
      };
  in
    inputs.flake-parts.lib.mkFlake {inherit inputs;} {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      flake = {
        lib.target = target;
        homeConfigurations.vm = homeFor {
          pkgs = import inputs.nixpkgs {system = target.system;};
        };
      };

      perSystem = {
        pkgs,
        system,
        ...
      }: {
        packages = let
          new-vm = pkgs.writeShellApplication {
            name = "new-vm";
            text = ''
              ssh exe.dev new | grep ssh | awk '{print $NF}'
            '';
          };
        in {
        } //
          inputs.nixpkgs.lib.optionalAttrs
          (builtins.elem system [
            "x86_64-linux"
            "aarch64-linux"
          ])
          {
            inherit (homeFor {inherit pkgs;}) activationPackage;
          };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            bash
            python3
            shellcheck
            nixfmt
          ];
        };

        formatter = pkgs.nixfmt;
      };
    };
}
