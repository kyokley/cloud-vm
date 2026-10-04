---
name: exe-dev
description: >
  Develop, run, test, or debug a project hosted or developed in an exe.dev VM.
  Use for exe.dev VM app setup, localhost:8000 listener and HTTPS proxy checks,
  VM-side project workflows, and exe.dev sharing or access diagnostics. Do not
  use for unrelated projects merely because exe.dev is mentioned.
---

# exe.dev VM project workflow

Use this workflow for projects hosted or developed in an exe.dev VM. Work in the project repository unless the user requests control-plane or VM administration. Preserve existing work and access settings.

## Establish context

1. Determine whether commands run on the authorized client/control-plane session or inside the guest VM. Do not assume guest SSH keys can access exe.dev control-plane commands.
2. In the guest, inspect the current directory, repository, `README`, `AGENTS.md`, and project instructions. Identify runtime, lockfiles, package manager, and documented development commands before changing anything.
3. Use the project's existing reproducible environment and lockfile. Do not install packages globally, use root, or run privileged commands unless required and authorized. Do not expose secrets in output or logs.
4. Do not create, restart, or delete VMs unless requested. Do not infer VM name from guest hostname. Use `ssh exe.dev help` or `ssh exe.dev help <command>` for documented control-plane command syntax.

## Use Jujutsu safely

Prefer Jujutsu (`jj`) for repository work. Check availability with `command -v jj`. A jj repository can have metadata in an ancestor; inspect `jj root` and `jj status` rather than checking only for `.jj` in the current directory. If it is already a jj repository, inspect `jj status`, `jj diff`, and `jj log` before editing.

For a Git-only repository, initialize colocated jj at the repository root only when `jj` is available and inspection shows this is safe. First inspect `git status --short`, active merge/rebase/cherry-pick state, submodules, and worktree complications. Preserve all dirty work. Then run `jj git init --colocate` at the repository root and verify with `jj status` and `jj diff`. If initialization is unavailable, incompatible, or unsafe, explain why and use Git inspection (`git status --short`, `git diff`) without changing Git configuration.

In colocated jj workflows, use `jj status`, `jj diff`, and `jj log`; jj snapshots working-copy edits automatically. Do not use `git add` or `git commit` in that workflow. Use `jj describe` or `jj new` only when the user requests recording changes. Use bookmarks only for requested named references. Run `jj git fetch` or `jj git push` only when the user requests network operations. Never commit, amend, push, create a PR, move bookmarks, rewrite history, or discard work unless requested.

## Run the app

Use the project's documented startup command and configure the primary HTTP application listener explicitly for loopback port `8000`: `localhost:8000` or `127.0.0.1:8000`. Never bind the app to `0.0.0.0` or `::`. Never silently change the host or port, enable automatic port fallback, or claim an alternate port satisfies this requirement. If the project cannot support this listener, explain the blocker and ask before taking a different approach.

Only the primary HTTP application needs port 8000. Supporting databases and internal services should use their configured internal ports; do not make them compete for 8000. For separate frontend and backend processes, serve them through one primary listener using the project's existing routing or proxy configuration. Do not assume additional services are publicly exposed. If the project requires a different topology, explain the limitation and ask before deviating.

Check whether port 8000 is occupied before startup. Inspect the process and do not kill an unknown process. Do not choose another port to work around a conflict; report it and ask how to proceed.

Examples, only when they match the project's stack:

```sh
uvicorn main:app --host 127.0.0.1 --port 8000
```

For Vite only, a typical command is `npm run dev -- --host 127.0.0.1 --port 8000 --strictPort`. Do not apply Vite flags to other tools. Use equivalent documented project options for other runtimes, keeping host and port explicit.

## Validate and diagnose

Run the project's defined tests, lint, and build checks that fit the change. Report checks not run and why. Verify listener binding, not only HTTP response. For example:

```sh
ss -ltnp
curl -fsS http://localhost:8000/
```

Use a documented health endpoint when `/` is not applicable. Confirm the process listens only on `127.0.0.1:8000` or the loopback address represented by `localhost:8000`, not a wildcard address. `curl` success alone does not prove the listener is correctly bound.

exe.dev may select proxy targets based on VM image `EXPOSE` metadata (port 80 first, then the smallest eligible port at or above 1024). Do not claim every VM proxies port 8000 automatically. Check the VM's documented sharing target if HTTPS access fails. From an authorized client/control-plane session, `ssh exe.dev share show <vm>` inspects sharing and `ssh exe.dev share port <vm> 8000` changes the target while preserving visibility. Change this configuration only when needed and within the user's request. Do not toggle public access.

exe.dev terminates TLS. The default web URL is `https://<vmname>.exe.xyz/`. Test the known HTTPS URL through an authorized session as well as the local endpoint; local success does not prove proxy routing works. The proxy forwards `X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-For` headers. Trust proxy headers only through the project's trusted-proxy configuration; do not trust arbitrary client-supplied identity headers.

Private sharing is the default. Preserve current authentication and visibility. A redirect or login page may be expected outside an authorized session; do not bypass it by making the VM public. Web sharing exposes web access; Root sharing grants full VM SSH, terminal, and agent access. Never grant Root to fix a web-access problem.

For control-plane inventory, `ssh exe.dev ls --json` reports VM information including ready-to-use `ssh_dest`. Connect to a guest with `ssh <vm>.exe.xyz`; if needed, use documented fallback `ssh vm+<vm>@vm.exe.xyz`. Keep host-key checking enabled. Do not guess destinations or disable host-key validation. These control-plane commands require the authorized client session.

## Processes and report

Use the process manager already present in the guest. Inspect the environment first; do not assume `systemd`, `sudo`, or one universal manager. Persistent disks preserve files, not running processes across reboot. Do not promise process survival without verifying supervision and restart behavior.

At completion, report changed paths, exact startup command, the loopback listener, known HTTPS URL, and checks with limitations. Note any jj initialization or fallback and process durability limitations when relevant. Keep HTTP success, HTTPS proxy routing, and authentication/access outcomes distinct.

## References

- [Migrating to exe.dev](https://exe.dev/docs/migrating-to-exe)
- [Proxy](https://exe.dev/docs/proxy)
- [CLI sharing](https://exe.dev/docs/cli-share)
- [Sharing](https://exe.dev/docs/sharing)
- [CLI/API](https://exe.dev/docs/api)
- [SSH destination FAQ](https://exe.dev/docs/faq/ssh-destination)
- [Serverful VMs](https://exe.dev/docs/serverful)
