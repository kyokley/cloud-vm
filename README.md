# exe.dev Linux VM Home Manager template

This project configures user packages and settings on an existing exe.dev Linux VM with standalone Home Manager. It does not install NixOS or manage the VM's operating system, SSH, or system services. It does not create accounts or VMs automatically.

## Files

- `flake.nix`, `flake.lock`: pinned nixpkgs/Home Manager configuration and development tools.
- `config/target.nix`: explicit Linux system, guest username, and absolute home directory. Example values are placeholders.
- `config/home.nix`: user packages and Home Manager settings.
- `scripts/vm.sh`: inspect, bootstrap, and apply commands.
- `scripts/bootstrap-nix.sh`: guest-side Nix installer checks and execution.
- `tests/`: mocked helper tests.
- `docs/design.md`: scope and safety contracts.

## Requirements and limits

Local tools: Nix with flakes enabled, Bash, Python 3, `tar`, and `ssh`. The development shell provides Bash, Python 3, ShellCheck, and `nixfmt`.

The guest must be an existing Linux VM with a non-root user selected by the exe.dev SSH gateway. Supported architectures are `x86_64-linux` and `aarch64-linux`. The gateway identity, username, home directory, and architecture must match `config/target.nix`; `apply` stops on mismatch and never creates or switches accounts. Root targets are not supported.

Nix installation requirements depend on the selected mode. Daemon mode requires usable systemd, `getenforce` reporting `Disabled`, and explicitly authorized usable sudo. Provide `getenforce` separately before bootstrap. The helper fails if `getenforce` is unavailable or cannot report status; it does not infer disabled SELinux from missing interfaces or install prerequisite tools. Single-user mode requires an administrator to prepare an existing empty, writable `/nix` directory. Neither mode is automatic. Some VM images may not meet these requirements. Inspect the guest before installing.

## Create, authenticate, and inspect

Authenticate with exe.dev using its documented CLI, then create a VM:

```sh
ssh exe.dev new --name=my-vm
```

See [exe.dev VM creation](https://hub.exe.dev/docs/cli-new) and [SSH destination guidance](https://hub.exe.dev/docs/faq/ssh-destination). Inspect the guest account, home directory, OS, architecture, sudo, and systemd:

```sh
scripts/vm.sh inspect my-vm
```

The helper connects to `vm+my-vm@vm.exe.xyz`. SSH host-key checking stays enabled; verify the host key as usual. Do not proceed if the inspected account is root or the VM does not meet the selected install mode's requirements.

## Bootstrap Nix

First edit `config/target.nix` to match the inspected guest exactly. Set `system` to `"x86_64-linux"` or `"aarch64-linux"`; replace the example username and home directory. Review all commands before running them.

Preferred mode, only when the guest has usable systemd and `getenforce` reports `Disabled`:

```sh
scripts/vm.sh bootstrap my-vm --daemon --yes --allow-sudo
```

**Warning:** `--yes` authorizes execution of the Nix installer and runs it noninteractively. `--allow-sudo` separately authorizes privileged operations that can change system users and services. Run only after reviewing the installer and confirming the guest prerequisites. The helper does not authorize interactive privilege prompts or switch install modes. It uses the official installer over HTTPS by default. `flake.lock` does not pin that installer.

For single-user mode, an administrator must first prepare an existing empty, writable `/nix` directory on the guest. This mode does not use sudo and is not a workaround for missing administrator access:

```sh
scripts/vm.sh bootstrap my-vm --no-daemon --yes
```

To use a separately reviewed installer, obtain it from the official [Nix installation source](https://nixos.org/nix/install), inspect it, then transfer it to the guest. The path passed to `--installer-file` is a guest path:

```sh
scp ./nix-install.sh "vm+my-vm@vm.exe.xyz:/tmp/nix-install.sh"
scripts/vm.sh bootstrap my-vm --daemon --yes --allow-sudo --installer-file /tmp/nix-install.sh
```

Use `--no-daemon` instead only after preparing `/nix` as described above. Reviewed-file mode skips fetching the bootstrap entry script. The reviewed installer may still download tarballs or additional scripts. Installer execution is a separate supply-chain risk; a flake lock does not make bootstrap reproducible.

## Configure and apply

Edit `config/target.nix` with the verified, non-root guest identity before deployment. Edit `config/home.nix` to change user settings or packages; the template includes `git`, `curl`, `jq`, `ripgrep`, and `tmux`.

Apply to the existing VM:

```sh
scripts/vm.sh apply my-vm
```

Apply requires usable local and guest Nix installations. It checks guest identity before writes, reserves `$HOME/.local/share/cloud-vm`, and transfers only `flake.nix`, `flake.lock`, `config/target.nix`, and `config/home.nix`. Do not store secrets in this project or Nix expressions; Nix store contents are not secret storage.

The deployment directory and its relevant parents must be user-owned directories without symlinks or group/other write permission. Existing home and parent directories are never chmodded; fix unsafe modes yourself before retrying. The helper creates missing reserved directories with mode `0700` and extracts managed files without group/other permissions. Apply replaces its four managed project files inside that reserved directory. Home Manager refuses conflicting unmanaged home files rather than silently backing them up or overwriting them. Resolve those conflicts deliberately before retrying. The helper never deletes outside the reserved directory and never bootstraps Nix as an apply fallback. A build failure prevents activation. Activation errors propagate, but activation can leave partial user changes; automatic rollback is not provided.

Keep `home.stateVersion = "26.05"` in `config/home.nix` after initial deployment. It selects Home Manager compatibility defaults; changing it does not migrate existing state.

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
nixfmt --check flake.nix config/*.nix
nix flake check --no-build path:.
```

The flake check evaluates outputs supported by the current host. Linux activation builds and real activation should be tested on a supported Linux host or VM. Local Darwin evaluation does not verify Linux builds, guest compatibility, or restart persistence.

## Manual VM smoke test

After authentication and explicit authorization, create or select a disposable existing VM, inspect it, configure the target, and bootstrap Nix using a mode whose prerequisites are met. Run `apply`, confirm it succeeds, then run `apply` again to check repeatability. Verify the installed packages and user settings on the guest, reconnect after a VM restart, and confirm the expected state persists. This project has not performed this real-VM test; do not treat local mocks or evaluation as guest validation.
