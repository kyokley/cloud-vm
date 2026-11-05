{
  config,
  inputs,
  lib,
  ...
}:
let
  projectRoot = config.fleet.projectRoot;
  baseTarget = import (projectRoot + "/config/target.nix");
  validName = name: builtins.match "[a-z]([a-z0-9-]{0,38}[a-z0-9])?" name != null;
  validTarget =
    target:
    builtins.isAttrs target
    && builtins.isString (target.system or null)
    && builtins.elem target.system [
      "x86_64-linux"
      "aarch64-linux"
    ]
    && builtins.isString (target.username or null)
    && builtins.match "[a-z_][a-z0-9_-]*" target.username != null
    && !builtins.elem target.username [
      "root"
      "example"
    ]
    && builtins.isString (target.homeDirectory or null)
    && builtins.match "/[^[:cntrl:]]*" target.homeDirectory != null
    && builtins.all (part: part != "." && part != "..") (lib.splitString "/" target.homeDirectory);
  targetType = lib.types.submodule {
    options = {
      system = lib.mkOption {
        type = lib.types.enum [
          "x86_64-linux"
          "aarch64-linux"
        ];
        default = baseTarget.system;
      };
      username = lib.mkOption {
        type = lib.types.str;
        default = baseTarget.username;
      };
      homeDirectory = lib.mkOption {
        type = lib.types.str;
        default = baseTarget.homeDirectory;
      };
    };
  };
  vmType = lib.types.submodule {
    options = {
      target = lib.mkOption {
        type = targetType;
        default = { };
      };
      modules = lib.mkOption {
        type = lib.types.listOf lib.types.deferredModule;
        default = [ ];
      };
    };
  };
  vms = config.fleet.vms;
  targets = builtins.mapAttrs (_: feature: feature.target) vms;
  checkedBaseTarget =
    if !validTarget baseTarget then
      throw "base target metadata requires a Linux system, safe username, and absolute homeDirectory"
    else
      baseTarget;
  checkedTargets =
    if builtins.any (name: name == "vm" || !validName name) (builtins.attrNames vms) then
      throw "fleet VM names must match [a-z][a-z0-9-]{0,38}[a-z0-9] or be one lowercase letter; 'vm' is reserved"
    else if builtins.any (name: !validTarget targets.${name}) (builtins.attrNames targets) then
      throw "fleet target metadata requires a Linux system, safe username, and absolute homeDirectory"
    else
      targets;
  homeFor =
    {
      pkgs,
      target,
      extraModules ? [ ],
    }:
    inputs.home-manager.lib.homeManagerConfiguration {
      inherit pkgs;
      modules = [
        (projectRoot + "/config/home.nix")
        ({ config, ... }: {
          assertions = [
            {
              assertion = config.home.username == target.username;
              message = "home.username must match fleet target metadata";
            }
            {
              assertion = config.home.homeDirectory == target.homeDirectory;
              message = "home.homeDirectory must match fleet target metadata";
            }
          ];
        })
      ]
      ++ extraModules;
      extraSpecialArgs = { inherit target inputs; };
    };
in
{
  options.fleet.projectRoot = lib.mkOption {
    type = lib.types.path;
    readOnly = true;
  };
  options.fleet.baseTarget = lib.mkOption {
    type = lib.types.attrs;
    readOnly = true;
  };
  options.fleet.vms = lib.mkOption {
    type = lib.types.attrsOf vmType;
    default = { };
    description = "Per-VM target metadata and Home Manager feature modules.";
  };

  # Add config/vms/workstation.nix as a flake-parts module:
  # { ... }: { fleet.vms.workstation = {
  #   target = { username = "alice"; homeDirectory = "/home/alice"; };
  #   modules = [ ({ lib, ... }: { programs.git.enable = lib.mkForce false; }) ];
  # }; }
  config = {
    fleet.baseTarget = baseTarget;
    flake =
      let
        base = homeFor {
          pkgs = import inputs.nixpkgs { system = checkedBaseTarget.system; };
          target = checkedBaseTarget;
        };
      in
      {
        lib.target = checkedBaseTarget;
        lib.fleet.targets = checkedTargets;
        homeConfigurations = {
          vm = base;
        }
        // builtins.mapAttrs (
          name: feature:
          homeFor {
            pkgs = import inputs.nixpkgs { system = checkedTargets.${name}.system; };
            target = checkedTargets.${name};
            extraModules = feature.modules;
          }
        ) vms;
      };
  };
}
