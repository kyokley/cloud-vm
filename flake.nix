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
        self',
        pkgs,
        system,
        ...
      }: {
        packages = let
          # vm-script = builtins.readFile ./scripts/vm.sh
          vm-script = pkgs.stdenv.mkDerivation {
            pname = "vm-script";
            version = "0.0.1";
            src = ./.;
            dontUnpack = true;
            installPhase = ''
              # mkdir -p $out/bin
              # cp -r $src/config $out/config
              # cp -r $src/scripts $out/scripts
              mkdir $out
              cp -r $src/* $out/
              chmod -R +x $out/scripts
            '';
          };
          ls-vm = pkgs.writeShellApplication {
            name = "ls-vm";
            text = ''
              ssh exe.dev ls
            '';
          };
          new-vm = pkgs.writeShellApplication {
            name = "new-vm";
            text = ''
              domain=$(ssh exe.dev new | grep ssh | awk '{print $NF}')
              new_vm_name=$(echo "$domain" | awk -F. '{print $1}')
              echo "wait 5 secs for $new_vm_name to come up"
              sleep 5
              ${vm-script}/scripts/vm.sh bootstrap "$new_vm_name" --yes --allow-sudo
              ${vm-script}/scripts/vm.sh apply "$new_vm_name"

              echo
              echo "new machine created: $new_vm_name"
            '';
          };
          rm-vm = pkgs.writeShellApplication {
            name = "rm-vm";
            runtimeInputs = with pkgs; [
              jq
              fzf
            ];
            text = ''
              if [[ $# -eq 0 ]]; then
                vms=$(ssh exe.dev ls --json | ${pkgs.jq}/bin/jq '.vms[].vm_name' | sed 's/"//g' | ${pkgs.fzf}/bin/fzf -m)
              else
                vms="$*"
              fi

              echo "$vms" | xargs -r ssh exe.dev rm
            '';
          };
          ssh-vm = pkgs.writeShellApplication {
            name = "ssh-vm";
            runtimeInputs = with pkgs; [
              jq
              fzf
            ];
            text = ''
              if [[ $# -eq 0 ]]; then
                vm=$(ssh exe.dev ls --json | ${pkgs.jq}/bin/jq '.vms[].ssh_host' | sed 's/"//g' | ${pkgs.fzf}/bin/fzf)
              else
                vm="$*"
              fi

              if [[ -n "$vm" ]]; then
                TERM=xterm-256color ssh -o StrictHostKeyChecking=accept-new "$vm"
              fi
            '';
          };
        in {
          inherit new-vm vm-script rm-vm ssh-vm ls-vm;
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
            bun
            inputs.bun2nix.packages.${pkgs.stdenv.hostPlatform.system}.default
            python3
            shellcheck
            nixfmt
            self'.packages.new-vm
            self'.packages.vm-script
            self'.packages.rm-vm
            self'.packages.ssh-vm
            self'.packages.ls-vm
          ];
        };

        formatter = pkgs.nixfmt;
      };
    };
}
