{
  config,
  inputs,
  ...
}:
{
  perSystem =
    {
      pkgs,
      system,
      self',
      ...
    }:
    let
      projectRoot = config.fleet.projectRoot;
      target = config.fleet.baseTarget;
      source = pkgs.lib.cleanSourceWith {
        src = projectRoot;
        filter =
          path: type:
          let
            relative = pkgs.lib.removePrefix "${toString projectRoot}/" (toString path);
            segments = pkgs.lib.splitString "/" relative;
            topLevel = builtins.head segments;
            excluded = [
              ".git"
              ".jj"
              ".direnv"
              ".ruff_cache"
              "__pycache__"
            ];
          in
          path == projectRoot
          || (
            !(builtins.any (segment: builtins.elem segment excluded) segments)
            && !(pkgs.lib.hasSuffix ".pyc" relative)
            && (
              builtins.elem relative [
                "flake.nix"
                "flake.lock"
              ]
              || builtins.elem topLevel [
                "cloud_vm"
                "config"
                "modules"
                "scripts"
              ]
            )
          );
      };
      baseActivation = inputs.home-manager.lib.homeManagerConfiguration {
        inherit pkgs;
        modules = [
          (projectRoot + "/config/home/default.nix")
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
        ];
        extraSpecialArgs = { inherit inputs target; };
      };
      vm-script = pkgs.stdenv.mkDerivation {
        pname = "vm-script";
        version = "0.0.1";
        src = source;
        dontUnpack = true;
        installPhase = ''
          mkdir -p $out
          cp -r $src/* $out/
          chmod -R +x $out/scripts
        '';
      };
      ls-vm = pkgs.writeShellApplication {
        name = "ls-vm";
        runtimeInputs = [ pkgs.openssh ];
        text = "ssh exe.dev ls";
      };
      cloud-vm = pkgs.writeShellApplication {
        name = "cloud-vm";
        runtimeInputs = with pkgs; [
          openssh
          python3
          bash
          coreutils
          gnutar
          nix
          jq
          gawk
          gnugrep
          gnused
          findutils
        ];
        text = ''
          export PYTHONPATH="${source}''${PYTHONPATH:+:$PYTHONPATH}"
          has_project_root=0
          for arg in "$@"; do
            case "$arg" in
              --project-root|--project-root=*) has_project_root=1 ;;
            esac
          done
          if ((has_project_root)); then
            exec ${pkgs.python3}/bin/python -m cloud_vm "$@"
          fi
          exec ${pkgs.python3}/bin/python -m cloud_vm --project-root "${source}" "$@"
        '';
      };
      new-vm = pkgs.writeShellApplication {
        name = "new-vm";
        runtimeInputs = [ cloud-vm ];
        text = ''exec cloud-vm create "$@"'';
      };
      rm-vm = pkgs.writeShellApplication {
        name = "rm-vm";
        runtimeInputs = with pkgs; [
          jq
          fzf
          openssh
        ];
        text = builtins.readFile (projectRoot + "/scripts/rm-vm.sh");
      };
      ssh-vm = pkgs.writeShellApplication {
        name = "ssh-vm";
        runtimeInputs = with pkgs; [
          jq
          fzf
          openssh
        ];
        text = ''
          if [[ $# -eq 0 ]]; then
            vm=$(ssh exe.dev ls --json | jq '.vms[].ssh_host' | sed 's/"//g' | fzf)
          else
            vm="$*"
          fi
          if [[ -n "$vm" ]]; then
            TERM=xterm-256color ssh -o StrictHostKeyChecking=accept-new "$vm"
          fi
        '';
      };
    in
    {
      packages = {
        inherit
          cloud-vm
          new-vm
          vm-script
          rm-vm
          ssh-vm
          ls-vm
          ;
      }
      //
        inputs.nixpkgs.lib.optionalAttrs
          (builtins.elem system [
            "x86_64-linux"
            "aarch64-linux"
          ])
          {
            activationPackage = baseActivation.activationPackage;
          };
      apps.default = {
        type = "app";
        meta.description = "Inspect and manage exe.dev VMs";
        program = "${cloud-vm}/bin/cloud-vm";
      };
      devShells.default = pkgs.mkShell {
        packages =
          with pkgs;
          [
            bash
            bun
            python3
            shellcheck
            nixfmt
            cloud-vm
            new-vm
            vm-script
            rm-vm
            ssh-vm
            ls-vm
          ]
          ++
            pkgs.lib.optional (builtins.hasAttr system inputs.bun2nix.packages)
              inputs.bun2nix.packages.${system}.default;
      };
      formatter = pkgs.nixfmt;
    };
}
