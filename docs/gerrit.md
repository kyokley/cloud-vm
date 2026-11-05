# Gerrit on rocker-frost

`config/vms/rocker-frost.nix` adds Gerrit only to `homeConfigurations.rocker-frost`. It inherits the shared target identity and Home Manager configuration. Other VMs do not enable Podman or these services.

The override defines two rootless Podman containers:

- `gerrit`: official Gerrit 3.14.5 image, pinned by a multi-architecture digest. It has no published HTTP or SSH ports.
- `gerrit-proxy`: official Nginx 1.30.6 Alpine image, also digest-pinned. It requires Basic Auth for every request and publishes only `127.0.0.1:8000`.

Both containers use the dedicated `gerrit` Podman network. Nginx forwards validated Basic credentials to Gerrit, which trusts that authentication boundary. Do not attach untrusted containers to this network, publish Gerrit directly, or replace the proxy with an unauthenticated forwarder. Gerrit's HTTP authentication mode does not independently verify proxy passwords.

Images do not auto-update. Review version, digest, upgrade instructions, and backups before changing either image. Gerrit updates may require data migrations; rolling back the image is not a data rollback.

## Host prerequisites

No VM has been changed or container image pulled as part of defining this configuration. Before deploying:

1. Run `scripts/vm.sh inspect rocker-frost` locally. Verify its account, home, and architecture match the inherited `config/target.nix` values.
2. Ensure the VM supports rootless Podman: usable user namespaces, unique subordinate UID/GID ranges for the target account in `/etc/subuid` and `/etc/subgid`, and working host-provided `newuidmap`/`newgidmap` helpers. Installing Podman through Home Manager does not configure these privileged host prerequisites. Do not make Nix-store binaries setuid.
3. Ensure the account has a working systemd user manager. For startup after reboot without an SSH login, an administrator must enable user lingering, for example `sudo loginctl enable-linger exedev` if `exedev` is the verified account. Home Manager does not enable lingering.
4. Reserve loopback port 8000. Do not stop an unrelated listener or move the service to an arbitrary public port.

Apply the configuration after meeting those requirements:

```sh
scripts/vm.sh apply rocker-frost --yes
```

The override preserves the existing Home Manager service-start policy. Prepare credentials before the first manual service start. Boot autostart requires lingering and the same persistent runtime secret. Missing credentials prevent proxy startup; there is no default password or unauthenticated fallback.

## Provision the administrator password

Run these commands as the verified VM account, not root. Home Manager provides `podman` and Apache's `htpasswd` utility.

```sh
set -o pipefail
htpasswd -nB admin | podman secret create gerrit-htpasswd -
```

`htpasswd` prompts interactively and produces a bcrypt hash. Podman stores that password-file content outside Nix and the repository, then mounts it at `/run/secrets/gerrit.htpasswd` inside Nginx. The mounted mode permits Nginx's worker to read it; it is not a public host file. Do not put passwords, hashes, or secret files in Nix expressions or this repository.

Provision only the intended administrator initially. On a fresh Gerrit site, the first successfully registered account normally receives administrator privileges. Complete that first login before adding other users. Adding users requires both an updated runtime password file and appropriate Gerrit permissions; possessing a proxy password does not itself grant Gerrit administrator rights.

## Start and verify

On the VM:

```sh
systemctl --user daemon-reload
systemctl --user start podman-gerrit-proxy.service
systemctl --user status podman-gerrit.service podman-gerrit-proxy.service
journalctl --user -u podman-gerrit.service -u podman-gerrit-proxy.service -f
```

The proxy requires Gerrit and the managed network. First startup can take time while images are pulled and Gerrit initializes/reindexes. Ordering is not a readiness check: temporary upstream errors are possible before Gerrit finishes starting.

Check the local authentication boundary before routing HTTPS traffic:

```sh
curl -i http://127.0.0.1:8000/
curl -i -u admin http://127.0.0.1:8000/
podman port gerrit
```

The unauthenticated request must return `401`. For the second command, deliberately enter an incorrect password when prompted; it must also return `401`. `podman port gerrit` should show no published ports. Never send Basic credentials over an untrusted plaintext connection.

From the authenticated local client, inspect existing exe.dev sharing before changing the proxy target:

```sh
ssh exe.dev share show rocker-frost
# After checking authentication and preserving private visibility:
ssh exe.dev share port rocker-frost 8000
```

This configuration does not change exe.dev visibility or routing. Keep the VM private; do not make it public to bypass login or routing problems. Access Gerrit through `https://rocker-frost.exe.xyz/`, the configured canonical URL. exe.dev terminates TLS; the Nginx-to-Gerrit hop stays on the dedicated container network. There is no published Gerrit SSH port; use authenticated Git-over-HTTPS unless separately designing and authorizing SSH access.

Open `https://rocker-frost.exe.xyz/login/` in the browser, authenticate as the intended administrator, and complete the first Gerrit login before inviting other users. Valid proxy credentials alone do not create the Gerrit account used by authenticated REST requests. After that browser login, verify REST authentication on the VM:

```sh
curl -i -u admin http://127.0.0.1:8000/a/accounts/self
```

Enter the correct password when prompted. The response should identify the registered account. A `401` before completing browser registration is not proof that the proxy password is invalid; do not disable authentication to work around it.

## Persistence, rotation, and recovery

The preserved named volumes are `gerrit-git`, `gerrit-index`, `gerrit-cache`, `gerrit-db`, `gerrit-etc`, `gerrit-data`, and `gerrit-logs`. They cover repositories, indexes, cache, database state, configuration/SSH keys, plugin data, and logs. Removing a container or this Home Manager definition must not be treated as deleting those volumes. Do not use volume pruning as a reset or upgrade procedure.

The startup wrapper accepts the image's initial configuration template, records completed initialization, and refuses unmarked repository/runtime data or generated secret state rather than guessing that `All-Projects.git` proves success. Investigate logs and take backups before recovering or migrating such a site. It never automatically removes repositories, configuration, or secrets to retry initialization.

Take consistent backups of all named volumes and maintain a separate recovery procedure for the runtime password secret. Stop writes before backups; preserve `etc` because it contains generated secrets and host keys. Named-volume ownership/population, initialization, real authentication, and reboot persistence still require a separately authorized VM smoke test.

For password rotation, update the complete runtime password file/secret and **recreate** the proxy container. Existing containers can retain the old secret contents; a process restart alone is not a rotation guarantee. Stop `podman-gerrit-proxy.service`, replace the Podman secret securely, ensure the old proxy container has been removed, then start the unit again and verify both old-password rejection and new-password acceptance. Do not delete Gerrit volumes or rebuild its site to rotate proxy credentials.

## Sources

- [Official Gerrit container](https://hub.docker.com/r/gerritcodereview/gerrit) and [image source](https://gerrit.googlesource.com/docker-gerrit/).
- [Gerrit image tag metadata](https://hub.docker.com/v2/repositories/gerritcodereview/gerrit/tags/3.14.5) and [Nginx image tag metadata](https://hub.docker.com/v2/repositories/library/nginx/tags/1.30.6-alpine).
- [Gerrit HTTP authentication](https://gerrit-review.googlesource.com/Documentation/config-sso.html).
- [Nginx Basic Auth](https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html) and [proxy configuration](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).
- [Podman secrets](https://docs.podman.io/en/latest/markdown/podman-secret-create.1.html).
