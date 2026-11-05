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
    nix-filter.url = "github:numtide/nix-filter";
    caveman = {
      url = "github:JuliusBrussee/caveman";
      flake = false;
    };
    bun2nix = {
      url = "github:nix-community/bun2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs:
    let
      discover =
        dir:
        let
          entries = builtins.readDir dir;
          names = builtins.attrNames entries;
          walk =
            name:
            let
              path = dir + "/${name}";
              kind = entries.${name};
            in
            if kind == "directory" then
              discover path
            else if kind == "regular" && builtins.match ".*\\.nix" name != null then
              [ path ]
            else
              [ ];
        in
        builtins.concatLists (map walk names);
      discoverIfPresent = dir: if builtins.pathExists dir then discover dir else [ ];
    in
    inputs.flake-parts.lib.mkFlake { inherit inputs; } {
      imports = discover (./. + "/modules") ++ discoverIfPresent (./. + "/config/vms");
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      fleet.projectRoot = ./.;
    };
}
