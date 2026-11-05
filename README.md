# exe.dev VM fleet manager

Manage an exe.dev VM fleet from a terminal UI, then configure each VM with Nix and standalone Home Manager. Shared settings live in `config/home/`; per-VM Nix modules extend or override that base through flake-parts and the dendritic pattern.

This project does not install NixOS, replace the guest operating system, or create guest accounts. VM creation, privileged Nix bootstrap, Home Manager activation, and deletion remain separate, explicitly authorized operations.

## Fleet TUI

From this repository:

```sh
python3 -m cloud_vm --project-root "$PWD"
# Or use the Nix-packaged command:
nix run path:.#cloud-vm -- --project-root "$PWD"
```

Authenticate your SSH key with exe.dev first. The TUI uses the documented SSH control-plane interface, including `ssh exe.dev ls --json`. Normal SSH host-key verification remains enabled. First connections may require accepting verified host keys outside the TUI.

The interface lists VM state and supports guest inspection, creation, SSH, bootstrap, apply, and deletion. Inventory state comes from exe.dev; a running VM is not proof that Nix or Home Manager is installed. Inspect and provision deliberately. Creating a VM does not automatically execute an installer.

Keys: arrows or `j`/`k` select; `r` refreshes; `i` inspects; `n` creates; `s` opens SSH; `b` bootstraps Nix; `a` applies Home Manager; `d` deletes; `[`/`]` scroll output; `?` shows help; `q` quits. Press Escape to cancel a confirmation. Deletion requires typing the exact VM name. Resize if the terminal cannot show the complete warning.

Creation can incur charges. Bootstrap runs a mutable installer with root privileges. Apply can change user files and the login shell through sudo. Deletion first deactivates matching Mattermost users and then permanently removes the VM. Read each confirmation. Failed or timed-out operations may already have changed remote state; inspect before retrying.

For automation, `python3 -m cloud_vm --help` lists one-shot commands. Mutations require `--yes`; bootstrap also requires `--allow-sudo`. Use `python3 -m cloud_vm create --yes` to let exe.dev choose the VM name, or `python3 -m cloud_vm create my-vm --yes` to set it explicitly. In the TUI, leave the name blank to use exe.dev's default. The packaged `new-vm` command delegates to that create-only flow; its name argument is optional and `--yes` is required.

## Files

- `flake.nix`, `flake.lock`: pinned nixpkgs/Home Manager configuration and development tools.
- `config/target.nix`: explicit Linux system, guest username, and absolute home directory. Example values are placeholders.
- `config/home/default.nix`: shared account settings, user packages, and imports for the Home Manager modules below.
- `config/home/shell/`: shell settings and the Powerlevel10k prompt configuration.
- `config/home/opencode/`: OpenCode settings, skills, and its Bun dependency manifests. Run dependency maintenance commands from this directory.
- `config/vms/*.nix`: per-VM flake-parts declarations and overrides.
- `modules/`: shared flake-parts features for fleet composition and command packaging.
- `cloud_vm/`: terminal interface, consent-gated backend, and CLI entry point.
- `scripts/vm.sh`: inspect, bootstrap, and apply commands.
- `scripts/rm-vm.sh`: deactivate VM-matched Mattermost users and remove VMs.
- `scripts/bootstrap-nix.sh`: guest-side Nix installer checks and execution.
- `tests/`: mocked helper tests.
- `services/mattermost/`: independent Mattermost Compose deployment, with its own documentation and scripts. Run its commands from that directory; it is not part of the VM configuration transfer.
- `docs/design.md`: scope and safety contracts.

Keep Home Manager modules under `config/home/`, not `modules/`: the latter is recursively imported into the separate flake-parts module system. Python and shell entry points remain at their existing paths.

## Requirements and limits

Local tools: Nix with flakes enabled, Bash, Python 3, `tar`, and `ssh`. The development shell provides Bash, Python 3, ShellCheck, and `nixfmt`.

The guest must be an existing Linux VM with a non-root user selected by the exe.dev SSH gateway. Supported architectures are `x86_64-linux` and `aarch64-linux`. The gateway identity, username, home directory, and architecture must match `config/target.nix`; `apply` stops on mismatch and never creates or switches accounts. Root targets are not supported.

Bootstrap supports Linux `x86_64` and `aarch64` guests with usable systemd. The selected Determinate Nix distribution supports SELinux; bootstrap does not require `getenforce`. A non-root SSH user needs explicitly authorized, noninteractive sudo. An administrator can also run the guest-local helper as root without sudo; the Home Manager target account must still be non-root. Some VM images may not meet these requirements. Inspect the guest before installing.

## Create, authenticate, and inspect

Authenticate with exe.dev using its documented CLI, then create a VM:

```sh
ssh exe.dev new --name=my-vm
```

See [exe.dev VM creation](https://hub.exe.dev/docs/cli-new) and [SSH destination guidance](https://hub.exe.dev/docs/faq/ssh-destination). Inspect the guest account, home directory, OS, architecture, sudo, and systemd:

```sh
scripts/vm.sh inspect my-vm
```

The helper connects to `vm+my-vm@vm.exe.xyz`. SSH host-key checking stays enabled; verify the host key as usual. Do not proceed if the inspected account is root, the VM lacks usable systemd, or its Linux architecture is unsupported.

## Remove VMs

`rm-vm` keeps its interactive multi-select flow when called without VM names. Pass one or more VM names to select them directly. Before each VM deletion, it SSHes into that VM and deactivates active Mattermost users whose usernames start with the remote hostname plus `-` and have a nonempty suffix. Users such as `bot-*` are not selected unless they match that exact hostname prefix. Mattermost deactivation uses `DELETE /api/v4/users/{id}` without `permanent=true`; this archives the account and revokes sessions, but does not permanently delete the account. Cleanup or API errors stop processing and prevent deletion of that VM and later VMs. No extra confirmation is requested.

```sh
rm-vm
rm-vm my-vm another-vm
```

The Mattermost API must be reachable through the VM's network proxy. This operation has no retries for deactivation requests. Review selected names before running; VM removal is destructive.

## Bootstrap Nix

First edit `config/target.nix` to match the inspected guest exactly. Set `system` to `"x86_64-linux"` or `"aarch64-linux"`; replace the example username and home directory. Review all commands before running them.

The supported default is Determinate Nix with systemd. Selecting upstream Nix is unsupported:

```sh
scripts/vm.sh bootstrap my-vm --yes --allow-sudo
```

**Warning:** `--yes` authorizes execution of a mutable installer downloaded from `https://install.determinate.systems/nix`. `--allow-sudo` separately authorizes privileged installation. The installer runs as root and can add system users and services. Review the installer source and authorize these system changes before proceeding. The helper uses `sudo -n`; it does not request a password interactively. The downloaded entry script is fully fetched before execution, but it may download a platform-specific installer binary. `flake.lock` does not pin either installer artifact.

The old `--daemon` and `--no-daemon` options are removed. There is no single-user or no-init fallback. Do not run bootstrap on a guest with existing Nix state. An existing `/nix` directory, Nix command, receipt, installer, or profile requires explicit manual review and migration first. Bootstrap never forces installation, uninstalls Nix, renames a receipt, or migrates existing state. See the [Determinate migration guide](https://docs.determinate.systems/guides/migrating-from-upstream-nix/) before planning a migration; this project does not automate it.

To opt out of the installer's anonymous diagnostics, bootstrap passes `--diagnostic-endpoint=`. This does not disable all telemetry or network downloads.

For a separately reviewed entry script, obtain it from the official [Determinate installer](https://install.determinate.systems/nix), inspect it, then transfer it to the guest. The path passed to `--installer-file` is a guest path. The file is run as a shell wrapper and may still download the secondary installer binary:

```sh
scp ./determinate-nix-installer "vm+my-vm@vm.exe.xyz:/tmp/determinate-nix-installer"
scripts/vm.sh bootstrap my-vm --yes --allow-sudo --installer-file /tmp/determinate-nix-installer
```

On the guest, the equivalent local interface is `bootstrap-nix.sh --yes [--allow-sudo] [--installer-file PATH]`. Run it as the non-root VM user with `--allow-sudo` to authorize `sudo -n`, or run it directly as a root administrator without `--allow-sudo`. Do not use root as the Home Manager target account. Reviewed-file mode skips downloading the entry script only; the wrapper may download the secondary binary. Installer execution and downloads remain supply-chain risks, and a flake lock does not make bootstrap reproducible.

## Configure and apply

Edit `config/target.nix` with the verified, non-root guest identity before deployment. Edit `config/home/default.nix` to change shared user settings or packages; the template includes `git`, `curl`, `jq`, `ripgrep`, and `tmux`. Shell and OpenCode settings live in their respective subdirectories.

### Shared base and per-VM overrides

`flake.nix` recursively imports flake-parts feature modules under `modules/` and `config/vms/`. Each imported file belongs to the flake module system: this is the dendritic pattern. The fleet feature composes standalone Home Manager configurations from the shared `config/home/default.nix` plus each VM's Home Manager modules.

For a VM named `my-vm`, add `config/vms/my-vm.nix`:

```nix
{
  fleet.vms.my-vm = {
    # Omit target fields that should inherit config/target.nix.
    # Set these only after inspecting the guest.
    target = {
      system = "x86_64-linux";
      username = "exedev";
      homeDirectory = "/home/exedev";
    };
    modules = [
      ({ lib, pkgs, ... }: {
        home.packages = [ pkgs.htop ];
        home.sessionVariables.FLEET_ROLE = "worker";
        programs.tmux.enable = lib.mkForce false;
      })
    ];
  };
}
```

Use separate feature files for other VMs. Home Manager merges package lists and module definitions normally; use `lib.mkForce` when intentionally replacing a base value. Identity assertions prevent Home Manager overrides from changing the account independently of validated target metadata. VM names must use the same lowercase naming rules as the management helpers; `vm` is reserved for the base configuration.

`homeConfigurations.vm` and `lib.target` expose the base. Named entries appear in `homeConfigurations.<name>` and `lib.fleet.targets.<name>`. Applying to a registered VM selects its matching configuration; other VM names deliberately use the base. The shared target must still match every guest that uses it. Configuration files are trusted executable Nix expressions, not secret storage.

Apply to the existing VM:

```sh
scripts/vm.sh apply my-vm --yes
```

Apply requires usable local and guest Nix installations. It checks guest identity before writes and reserves `$HOME/.local/share/cloud-vm`. The transfer contains the explicit `guest_files` allowlist in `scripts/vm.sh`, plus regular `.nix` files under `modules/` and `config/vms/`. Other configuration files are not copied automatically: declare additional inputs deliberately in the transfer manifest. Symlinked input paths are rejected. Do not store secrets in this project or Nix expressions; Nix store contents are not secret storage.

The deployment directory and its relevant parents must be user-owned directories without symlinks or group/other write permission. Existing home and parent directories are never chmodded; fix unsafe modes yourself before retrying. The helper creates missing reserved directories with mode `0700` and extracts managed files without group/other permissions. It transfers into `.incoming`, then replaces the managed `source` snapshot only after transfer succeeds; removed feature files cannot linger in the active source. The `.activation` output link stays outside that source snapshot. An interrupted transfer can leave `.incoming`; inspect that exact reserved directory before manually removing a stale stage and retrying. Do not run concurrent deployments to the same VM.

Home Manager refuses conflicting unmanaged home files rather than silently backing them up or overwriting them. Resolve those conflicts deliberately before retrying. The helper never deletes outside the reserved directory and never bootstraps Nix as an apply fallback. A build failure prevents activation. After successful activation, apply uses noninteractive `sudo -n` to register the stable Home Manager zsh path in `/etc/shells` when missing, then changes only the current user's login shell. Ensure sudo authorization is available when either change is needed; apply never prompts or installs fallback packages. If the shell step fails, Home Manager activation may already have changed user files and settings; rerun apply after resolving the reported issue. Reconnect for the new login shell to take effect. Activation and shell changes do not have automatic rollback.

Select a configuration explicitly with `scripts/vm.sh apply my-vm --yes --target my-vm`; unknown explicit keys fail before guest writes. `--target vm` selects the shared base.

Keep the local project unchanged while apply runs. Metadata evaluation and file transfer read the working tree at different times; concurrent edits can invalidate the checked configuration. Wait for apply to finish before editing configuration or updating the lock file.

Keep `home.stateVersion = "26.05"` in `config/home/default.nix` after initial deployment. It selects Home Manager compatibility defaults; changing it does not migrate existing state.

## Lock updates and evaluation

To resolve current versions from the configured release branches and update the committed lock file, run:

```sh
nix --extra-experimental-features 'nix-command flakes' flake update --flake path:.
```

Review and retain the resulting `flake.lock` change. For validation, use explicit local `path:` references and immutable lock flags. No `--impure` option is needed:

```sh
nix --extra-experimental-features 'nix-command flakes' eval --json --no-update-lock-file --no-write-lock-file path:.#lib.target
nix --extra-experimental-features 'nix-command flakes' flake check --no-build --no-update-lock-file --no-write-lock-file path:.
nix --extra-experimental-features 'nix-command flakes' eval --raw --no-update-lock-file --no-write-lock-file path:.#packages.x86_64-linux.activationPackage.drvPath
nix --extra-experimental-features 'nix-command flakes' eval --raw --no-update-lock-file --no-write-lock-file path:.#packages.aarch64-linux.activationPackage.drvPath
```

Deployment also uses the current lock without updating or writing it. A missing or stale lock fails rather than resolving inputs during apply.

## Development verification

Enter the development shell, then run the helper checks:

```sh
nix develop path:.#default
shellcheck scripts/*.sh
for script in scripts/*.sh; do bash -n "$script"; done
python3 -m unittest discover -s tests
nixfmt --check flake.nix config/target.nix config/home/default.nix config/home/shell/default.nix config/home/opencode/default.nix modules/fleet/*.nix modules/packages/*.nix
nix flake check --no-build --no-update-lock-file --no-write-lock-file path:.
```

The flake check evaluates outputs supported by the current host. Linux activation builds and real activation should be tested on a supported Linux host or VM. Local Darwin evaluation does not verify Linux builds, guest compatibility, or restart persistence.

## Manual VM smoke test

After authentication and explicit authorization, create or select a disposable existing VM, inspect it, configure the target, and bootstrap Determinate Nix after confirming prerequisites. Run `apply`, confirm it succeeds, then run `apply` again to check repeatability. Verify the installed packages and user settings on the guest, reconnect after a VM restart, and confirm the expected state persists. This project has not performed this real-VM test; do not treat local mocks or evaluation as guest validation.
