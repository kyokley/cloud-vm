# Design: Nix configuration for exe.dev VMs

## Supported boundary

This project manages exe.dev VM inventory and lifecycle through a terminal UI, and configures VM accounts using standalone Home Manager and a locked Nix flake. It does not replace the guest operating system, kernel, network, or exe.dev SSH management. It is not a NixOS deployment template. Guest account creation and general system-service management are outside scope; explicitly authorized Nix installation and login-shell changes are supported.

The official exe.dev documentation describes VMs created from container images with persistent disks and a constrained kernel choice. It does not establish the default SSH username, architecture, sudo permissions, or availability of systemd. The template must require explicit account, home directory, and architecture configuration rather than assuming those values.

## User workflow

1. Authenticate with exe.dev and create a VM using its documented CLI, for example `ssh exe.dev new --name=my-vm`.
2. Inspect the VM account, architecture, operating system, privilege availability, and init system.
3. Edit the project configuration to match that VM account and architecture.
4. Bootstrap the supported Determinate Nix distribution only after authorizing installer execution and required privilege.
5. Transfer the project and activate its Home Manager configuration through the exe.dev SSH gateway.
6. Edit declarative configuration and repeat activation. Do not automatically recreate VMs or rerun installation.

The Python standard-library curses UI delegates to a subprocess backend. It uses a single worker for blocking inventory, inspection, and mutation operations; interactive SSH temporarily yields the terminal. Confirmations bind to an operation and VM snapshot. Backend mutation methods independently require explicit authorization, and noninteractive CLI commands require their documented consent flags. Creation does not implicitly install Nix or apply Home Manager. No mutation is automatically retried, including after timeout: the outcome may be unknown.

Deletion preserves `scripts/rm-vm.sh` cleanup behavior. It deactivates Mattermost accounts matching the guest hostname prefix, not an inferred exe.dev VM-name prefix. Cleanup failure prevents VM deletion, but partial cleanup is possible. A confirmation must disclose both effects.

## Configuration model

- A root `flake.nix` pins compatible nixpkgs and Home Manager inputs through `flake.lock`.
- A small editable configuration file declares Linux system, username, and absolute home directory. Example identity values are visibly placeholders, not claims about exe.dev defaults.
- Home Manager manages user packages and a small set of non-destructive user settings. It must not silently back up or overwrite conflicting files.
- A development shell supplies lint and test tooling. The supported VM systems are `x86_64-linux` and `aarch64-linux`; development tooling should also work on macOS where practical.
- Flake evaluation remains pure. Do not derive target identity from the workstation environment or use `--impure`.

Feature files are flake-parts modules, recursively composed using the dendritic pattern. The base Home Manager module remains `config/home.nix`. Fleet declarations add per-VM identity metadata and Home Manager modules. Named configurations inherit the base; Home Manager assertions prevent their effective account identity from diverging from metadata checked before deployment. `lib.target` and `homeConfigurations.vm` retain base compatibility; `lib.fleet.targets` and named `homeConfigurations` expose fleet entries. VM-name matching selects a named entry when present and otherwise deliberately selects the base. Explicit unknown configuration keys must fail rather than fall back.

## Helper boundaries

- `scripts/bootstrap-nix.sh` executes on the VM. It supports the Determinate Nix distribution with systemd on Linux x86_64 and aarch64. `--yes` acknowledges installer execution; non-root execution also requires `--allow-sudo` and noninteractive sudo. A standalone administrator may run the helper as root without sudo. The Home Manager account remains non-root. The removed upstream `--daemon`/`--no-daemon` and single-user interfaces are not supported.
- A separate SSH helper inspects, bootstraps, or applies configuration to a named existing VM using `vm+NAME@vm.exe.xyz`, the documented fallback routing form. It validates VM names and keeps remote shell commands fixed or safely quoted.
- Remote deployment uses a fixed user-owned project directory, excludes Git metadata and deepwork state, and activates a `path:` flake so the copied tree does not depend on Git tracking.
- No secrets belong in Nix expressions or installation arguments. Nix store contents are not secret storage.
- The installer entry point is the mutable HTTPS URL `https://install.determinate.systems/nix`. Download the complete entry script before execution. It may download a separate platform installer binary. `--installer-file` accepts a reviewed entry script already on the guest, but does not prevent secondary downloads. Installer execution and its root-level system changes require explicit operator authorization. The helper opts out of anonymous installer diagnostics with `--diagnostic-endpoint=`; this does not disable all telemetry or network access. `flake.lock` does not pin bootstrap artifacts, so bootstrap is not fully reproducible.

## Installer prerequisites

Determinate Nix installation requires Linux x86_64 or aarch64 with usable systemd. Determinate supports SELinux; bootstrap does not require `getenforce` or disabled SELinux. Installing as a non-root VM user requires explicit sudo authorization and noninteractive `sudo -n`. A local administrator can run the helper as root without sudo, but the Home Manager target remains the non-root gateway account. There is no single-user or no-init fallback. Any existing `/nix` directory or Nix installation state, including a command, receipt, installer, or profile, stops bootstrap for explicit manual review. Never force installation, uninstall, rename receipts, or automatically migrate existing state. Follow the [Determinate migration guide](https://docs.determinate.systems/guides/migrating-from-upstream-nix/) for migration planning; this template does not automate migration.

No live VM has been inspected or changed during project development. Runtime checks are required before installation; the project cannot promise that every custom exe.dev image is compatible.

## Current acceptance contracts

These contracts define the current configuration and deployment boundaries. The Phase 3 Determinate bootstrap contract supersedes the original installer-specific requirements.

### Identity and SSH

The gateway selects a VM, not an arbitrary account. Initial scope supports only the non-root account selected by the gateway. Deployment rejects unresolved example identity values and compares configured username, absolute home directory, and Linux architecture with the guest's observed identity before deployment writes. Any mismatch stops without account creation, `su`, or compensating `sudo`. Destination is exactly `vm+NAME@vm.exe.xyz`; normal SSH host-key verification remains enabled.

### Bootstrap

Current Phase 3 bootstrap contract supersedes the original upstream daemon/single-user contract. The supported default is Determinate Nix; selecting upstream Nix is unsupported. Install with systemd on Linux x86_64 or aarch64. The interface is `vm.sh bootstrap NAME --yes --allow-sudo [--installer-file GUEST_PATH]`; the guest-local interface is `bootstrap-nix.sh --yes [--allow-sudo] [--installer-file PATH]`. Non-root execution requires `--allow-sudo` and usable noninteractive `sudo -n`; direct standalone administrator/root execution does not require sudo. Home Manager still targets the non-root VM user. `--yes` explicitly authorizes execution.

The fixed mutable entry URL is `https://install.determinate.systems/nix`. The download path completes the entry script before execution; the wrapper may download a separate platform binary. Reviewed-file mode uses an entry script already on the guest and skips only the entry-script request. Both paths invoke `sh FILE install --no-confirm --diagnostic-endpoint=` with stdin closed. Installer diagnostics are disabled; this does not disable all telemetry or network downloads. `flake.lock` does not pin bootstrap artifacts.

Require usable systemd. Determinate supports SELinux; do not require `getenforce` or disabled SELinux. Remove `--daemon`, `--no-daemon`, and all single-user/no-init fallback documentation. Any existing `/nix` or Nix installation state (including command, receipt, installer, or profile) stops for explicit manual review. Never force installation, uninstall, rename receipts, or automatically migrate. Use the official migration guide; no migration procedure runs automatically. A successful installer exit is not success until Nix and the daemon store pass the documented post-install checks.

### Deployment and locked activation

Reserve `$HOME/.local/share/cloud-vm` on the verified guest account. Reject unsafe ownership, symlinks, and group/other-writable modes at the destination and relevant parent paths before copying. Do not chmod existing home or parent paths. Create missing reserved directories with restrictive permissions, and extract allowlisted files without group/other permissions regardless of source modes or umask. Transfer the explicit `guest_files` allowlist from `scripts/vm.sh` plus regular Nix files under `modules/` and `config/vms/`. Include additional local inputs only by deliberate manifest changes. Never copy `.git`, deepwork files, unrelated working-tree files, or secrets. Do not delete outside the reserved directory. Transfer into `.incoming`, publish as a replacement `source` snapshot only on transfer success, and build that snapshot with the selected configuration key. Keep `.activation` outside the replaceable snapshot. A stale stage requires manual review. Transfer failure prevents activation. Apply never invokes bootstrap as a fallback. Concurrent independent deployments to the same VM are not supported.

Deployment requires a present, current lock and all local inputs. It uses an explicit `path:` flake reference and the explicit Home Manager activation output, with `nix-command flakes` enabled on each Nix command. Use `--no-update-lock-file` and `--no-write-lock-file` so deployment fails rather than resolving stale inputs or changing the lock. Build failure prevents activation. Activation failure propagates to the caller and may leave partial user changes; atomic rollback is outside this initial scope.

The local working tree must remain unchanged throughout apply. Target metadata is evaluated before transfer reads local files; concurrent configuration edits or lock updates can invalidate the checked source. An immutable local snapshot and cross-process remote locking are future hardening, not current guarantees.

### Required focused evidence

Mocks must cover rejected placeholders, account/home/architecture mismatches, root target, invalid VM names, exact destination, and absence of writes on identity rejection. Bootstrap tests cover accepted and removed flags, consent, authorized/unavailable sudo and standalone root invocation, unavailable systemd, SELinux independence, existing Nix state, successful and failed installer paths, exact `install --no-confirm --diagnostic-endpoint=` arguments, closed stdin, and invalid reviewed files. Deployment tests cover unsafe ownership, symlinks, and writable modes; restrictive creation/extraction modes; exact allowlisted transfer; transfer failure; missing/stale lock or local inputs; unchanged lock; build failure; activation failure; and no implicit bootstrap. Real VM compatibility remains an explicitly untested boundary.

## Verification plan

The configuration lane owns flake locking, evaluation, formatting, and building the target activation package where host support allows. The script lane owns syntax and shell lint. An integrated test lane owns deterministic mocked SSH/installer/Nix behavior, including existing Nix, missing privileges, invalid names, transfer failure, and activation failure. The orchestrator owns evidence reconciliation and final repository checks.

Local mock tests establish command construction and failure behavior, not guest compatibility. Real VM creation, installation, activation, and restart persistence checks require an authenticated account and explicit permission. Report them as untested until performed.

## Sources and accepted facts

- [exe.dev API](https://exe.dev/docs/api.md): SSH is the control-plane API; inventory is an object containing `vms`, whose entries include `vm_name`, `status`, `ssh_dest`, and `ssh_host`. `new --json` is documented, but its success schema is not assumed. Registration and billing failures must be reported rather than treated as an empty fleet.
- [flake-parts](https://flake.parts/): top-level flake modules compose configuration and per-system outputs. Recursive feature imports implement the dendritic pattern; Home Manager submodules remain in their own module class.
- [exe.dev CLI new](https://hub.exe.dev/docs/cli-new): `ssh exe.dev new [options]`; supports name, image, CPU, memory, disk, environment, and setup script. Setup scripts are first-boot-only and limited to 10 KiB.
- [exe.dev customization](https://hub.exe.dev/docs/customization): custom container images and `exe.dev/login-user` image label.
- [exe.dev SSH destination FAQ](https://hub.exe.dev/docs/faq/ssh-destination): hostname routing and `ssh vm+my-vm@vm.exe.xyz` fallback.
- [How exe.dev works](https://hub.exe.dev/docs/faq/how-exedev-works): container image on a block device, kernel constraints, no public VM IP, and proxy routing.
- [exe.dev persistent disks](https://hub.exe.dev/docs/serverful): persistent guest filesystems; Nix-specific restart behavior remains unverified.
- [exe.dev Docker FAQ](https://hub.exe.dev/docs/faq/docker): Docker works on exeuntu; this does not establish arbitrary init or privilege support.
- [Determinate Nix documentation](https://docs.determinate.systems/determinate-nix/): supported Determinate distribution and installation behavior.
- [Determinate nix-installer](https://github.com/DeterminateSystems/nix-installer): installer implementation and command interface.
- [Determinate installer entry point](https://install.determinate.systems/nix): mutable shell wrapper that downloads the platform installer.
- [Migrating from upstream Nix](https://docs.determinate.systems/guides/migrating-from-upstream-nix/): manual migration guidance; this template does not automate migration.
- [Nix flakes](https://nix.dev/manual/nix/stable/concepts/flakes.html): `nix-command flakes` experimental features.
- [Home Manager standalone flakes](https://nix-community.github.io/home-manager/usage/upgrading.html): compatible Home Manager/nixpkgs releases and standalone activation.
