# Design: Nix configuration for exe.dev VMs

## Supported boundary

This project will configure an existing exe.dev VM account using standalone Home Manager and a locked Nix flake. It will not replace the guest operating system, kernel, network, or exe.dev SSH management. It is not a NixOS deployment template. System-wide services and account creation are outside the initial scope.

The official exe.dev documentation describes VMs created from container images with persistent disks and a constrained kernel choice. It does not establish the default SSH username, architecture, sudo permissions, or availability of systemd. The template must require explicit account, home directory, and architecture configuration rather than assuming those values.

## User workflow

1. Authenticate with exe.dev and create a VM using its documented CLI, for example `ssh exe.dev new --name=my-vm`.
2. Inspect the VM account, architecture, operating system, privilege availability, and init system.
3. Edit the project configuration to match that VM account and architecture.
4. Bootstrap Nix only after explicitly selecting an installation mode and acknowledging installer execution.
5. Transfer the project and activate its Home Manager configuration through the exe.dev SSH gateway.
6. Edit declarative configuration and repeat activation. Do not automatically recreate VMs or rerun installation.

## Configuration model

- A root `flake.nix` pins compatible nixpkgs and Home Manager inputs through `flake.lock`.
- A small editable configuration file declares Linux system, username, and absolute home directory. Example identity values are visibly placeholders, not claims about exe.dev defaults.
- Home Manager manages user packages and a small set of non-destructive user settings. It must not silently back up or overwrite conflicting files.
- A development shell supplies lint and test tooling. The supported VM systems are `x86_64-linux` and `aarch64-linux`; development tooling should also work on macOS where practical.
- Flake evaluation remains pure. Do not derive target identity from the workstation environment or use `--impure`.

## Helper boundaries

- `scripts/bootstrap-nix.sh` executes on the VM. It detects an existing usable Nix installation, validates prerequisites, and installs only through an explicit mode and execution acknowledgement. It never silently escalates or falls back between daemon and single-user mode.
- A separate SSH helper inspects, bootstraps, or applies configuration to a named existing VM using `vm+NAME@vm.exe.xyz`, the documented fallback routing form. It validates VM names and keeps remote shell commands fixed or safely quoted.
- Remote deployment uses a fixed user-owned project directory, excludes Git metadata and deepwork state, and activates a `path:` flake so the copied tree does not depend on Git tracking.
- No secrets belong in Nix expressions or installation arguments. Nix store contents are not secret storage.
- Downloaded installer execution requires explicit consent. HTTPS protects transport, but the upstream installer is a mutable supply-chain input. Support a locally reviewed installer file where practical; do not describe remote bootstrap as fully reproducible.

## Installer prerequisites

Official Nix documentation recommends multi-user installation where supported. Linux daemon mode requires systemd and disabled SELinux, and changes system users/services. Single-user mode still requires writable `/nix`, which usually needs an administrator to create. It is not an escape hatch for missing privilege. Detect root, partial installations, and unsupported prerequisites explicitly and provide actionable failures.

No live VM has been inspected or changed during project development. Runtime checks are required before installation; the project cannot promise that every custom exe.dev image is compatible.

## Gate 1 acceptance contracts

These contracts close the initial design review without changing its architecture or trust boundary.

### Identity and SSH

The gateway selects a VM, not an arbitrary account. Initial scope supports only the non-root account selected by the gateway. Deployment rejects unresolved example identity values and compares configured username, absolute home directory, and Linux architecture with the guest's observed identity before deployment writes. Any mismatch stops without account creation, `su`, or compensating `sudo`. Destination is exactly `vm+NAME@vm.exe.xyz`; normal SSH host-key verification remains enabled.

### Bootstrap

The caller must select `--daemon` or `--no-daemon`; available privilege never selects a mode. Both downloaded and reviewed-file installers require explicit execution consent. Sudo use requires separate explicit authorization; no script prompts or silently escalates. Daemon mode requires usable systemd and known-disabled SELinux. Unknown status fails with guidance. Single-user installation rejects root and requires an existing usable writable `/nix`; administrator preparation is a separate documented action. A usable existing Nix installation bypasses installation. Partial installations fail rather than being repaired, removed, or reinstalled.

The bootstrap helper must support `--installer-file PATH`. That file resides on the guest when invoked through SSH; the operator transfers a reviewed file separately. Reviewed-file mode makes no upstream installer request. Downloaded mode uses only the fixed official HTTPS URL, completes the download before execution, and fails on transport or file validation errors. Consent accepts arbitrary installer execution; `flake.lock` does not pin the bootstrap installer.

### Deployment and locked activation

Reserve `$HOME/.local/share/cloud-vm` on the verified guest account. Reject unsafe ownership and symlinks at the destination and relevant parent paths before copying. Transfer an explicit allowlist: `flake.nix`, `flake.lock`, and configuration files under `config/`; include additional local inputs only by deliberate allowlist changes. Never copy `.git`, deepwork files, unrelated working-tree files, or secrets. Do not delete outside the reserved directory. Transfer failure prevents activation. Apply never invokes bootstrap as a fallback.

Deployment requires a present, current lock and all local inputs. It uses an explicit `path:` flake reference and the explicit Home Manager activation output, with `nix-command flakes` enabled on each Nix command. Use `--no-update-lock-file` and `--no-write-lock-file` so deployment fails rather than resolving stale inputs or changing the lock. Build failure prevents activation. Activation failure propagates to the caller and may leave partial user changes; atomic rollback is outside this initial scope.

### Required focused evidence

Mocks must cover rejected placeholders, account/home/architecture mismatches, root target, invalid VM names, exact destination, and absence of writes on identity rejection. Bootstrap tests cover both modes, consent, authorized/unavailable privilege, unavailable systemd, SELinux enabled/unknown, unwritable store, partial installation, usable existing Nix, download failure, and invalid reviewed files. Deployment tests cover unsafe destination paths, allowlisted transfer, transfer failure, missing/stale lock or local inputs, unchanged lock, build failure, activation failure, and no implicit bootstrap. Real VM compatibility remains an explicitly untested boundary.

## Verification plan

The configuration lane owns flake locking, evaluation, formatting, and building the target activation package where host support allows. The script lane owns syntax and shell lint. An integrated test lane owns deterministic mocked SSH/installer/Nix behavior, including existing Nix, missing privileges, invalid names, transfer failure, and activation failure. The orchestrator owns evidence reconciliation and final repository checks.

Local mock tests establish command construction and failure behavior, not guest compatibility. Real VM creation, installation, activation, and restart persistence checks require an authenticated account and explicit permission. Report them as untested until performed.

## Sources and accepted facts

- [exe.dev CLI new](https://hub.exe.dev/docs/cli-new): `ssh exe.dev new [options]`; supports name, image, CPU, memory, disk, environment, and setup script. Setup scripts are first-boot-only and limited to 10 KiB.
- [exe.dev customization](https://hub.exe.dev/docs/customization): custom container images and `exe.dev/login-user` image label.
- [exe.dev SSH destination FAQ](https://hub.exe.dev/docs/faq/ssh-destination): hostname routing and `ssh vm+my-vm@vm.exe.xyz` fallback.
- [How exe.dev works](https://hub.exe.dev/docs/faq/how-exedev-works): container image on a block device, kernel constraints, no public VM IP, and proxy routing.
- [exe.dev persistent disks](https://hub.exe.dev/docs/serverful): persistent guest filesystems; Nix-specific restart behavior remains unverified.
- [exe.dev Docker FAQ](https://hub.exe.dev/docs/faq/docker): Docker works on exeuntu; this does not establish arbitrary init or privilege support.
- [Nix binary installation](https://nix.dev/manual/nix/2.34/installation/installing-binary.html): official installer at `https://nixos.org/nix/install`; explicit `--daemon` and `--no-daemon` modes.
- [Nix multi-user installation](https://nix.dev/manual/nix/2.34/installation/multi-user.html): privileged daemon, build users, system service, and trusted-user security boundary.
- [Nix single-user installation](https://nix.dev/manual/nix/2.34/installation/single-user.html): writable `/nix` requirement.
- [Nix flakes](https://nix.dev/manual/nix/stable/concepts/flakes.html): `nix-command flakes` experimental features.
- [Home Manager standalone flakes](https://nix-community.github.io/home-manager/usage/upgrading.html): compatible Home Manager/nixpkgs releases and standalone activation.
