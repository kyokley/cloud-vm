#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bootstrap-nix.sh (--daemon | --no-daemon) --yes [--allow-sudo] [--installer-file PATH]

Run on the target Linux VM as its non-root account. --yes authorizes execution
of the Nix installer and runs it noninteractively. --allow-sudo separately authorizes sudo use. Without
--installer-file, download the official installer over HTTPS. A reviewed file
must already be on the guest. Single-user installation requires an administrator
to prepare an existing writable /nix directory before running this script; this
script never creates it or escalates automatically.
EOF
}
fail() { printf 'bootstrap-nix: %s\n' "$*" >&2; exit 1; }
mode='' consent=0 allow_sudo=0 installer_file=''
while (($#)); do
  case "$1" in
    --daemon|--no-daemon) [[ -z "$mode" ]] || fail 'select exactly one installation mode'; mode=$1 ;;
    --yes) consent=1 ;;
    --allow-sudo) allow_sudo=1 ;;
    --installer-file) (($# >= 2)) || fail '--installer-file needs a path'; installer_file=$2; shift ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
  shift
done
[[ -n "$mode" ]] || fail 'select --daemon or --no-daemon'
((consent)) || fail 'installer execution requires --yes'
[[ $(uname -s) == Linux ]] || fail 'only Linux is supported'
arch=$(uname -m)
case "$arch" in x86_64|aarch64) ;; *) fail "unsupported Linux architecture: $arch" ;; esac
[[ $(id -u) -ne 0 ]] || fail 'run as the non-root VM account'

nix_candidates() {
  local nix_user
  nix_user=$(id -un)
  printf '%s\n' \
    "$HOME/.nix-profile/bin/nix" \
    "$HOME/.local/state/nix/profile/bin/nix" \
    "/nix/var/nix/profiles/per-user/$nix_user/profile/bin/nix" \
    /nix/var/nix/profiles/default/bin/nix \
    /nix/var/nix/profiles/per-user/root/profile/bin/nix \
    "$(command -v nix || true)"
}
usable_nix() {
  local candidate
  while IFS= read -r candidate; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    if "$candidate" --version >/dev/null 2>&1 && \
      "$candidate" --experimental-features nix-command store ping --store "$nix_store" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(nix_candidates)
  return 1
}
nix_store=local
[[ $mode != --daemon ]] || nix_store=daemon
if nix_path=$(usable_nix); then
  printf 'Nix already usable: %s\n' "$nix_path"
  exit 0
fi
if [[ -d /nix/store ]] || [[ -d /nix/var/nix/profiles ]] || command -v nix >/dev/null 2>&1; then
  fail 'partial Nix installation detected; inspect and repair manually'
fi
if [[ -n "$installer_file" ]]; then
  [[ -f "$installer_file" && -r "$installer_file" && -s "$installer_file" ]] || fail 'reviewed installer must be a readable, non-empty regular file'
fi

if [[ $mode == --daemon ]]; then
  ((allow_sudo)) || fail 'daemon mode requires explicit --allow-sudo authorization'
  command -v sudo >/dev/null 2>&1 || fail 'daemon mode requires usable sudo'
  sudo -n true >/dev/null 2>&1 || fail 'sudo is unavailable without a password; configure privilege separately'
  sudo_path=$(command -v sudo)
  case "$sudo_path" in /*) ;; *) sudo_path="$PWD/$sudo_path" ;; esac
  [[ -d /run/systemd/system ]] || fail 'daemon mode requires usable systemd at /run/systemd/system'
  command -v systemctl >/dev/null 2>&1 || fail 'daemon mode requires systemctl'
  system_state=$(systemctl is-system-running 2>/dev/null || true)
  [[ $system_state == running || $system_state == degraded ]] || fail "daemon mode requires running systemd (status: ${system_state:-unknown})"
  if command -v getenforce >/dev/null 2>&1; then
    selinux=$(getenforce 2>/dev/null) || fail 'SELinux status is unknown; verify it is disabled'
    [[ $selinux == Disabled ]] || fail "daemon mode requires disabled SELinux (status: $selinux)"
  else
    fail 'getenforce is required to confirm SELinux is disabled; absent or unreadable interfaces do not prove disabled status'
  fi
else
  ((allow_sudo == 0)) || fail '--allow-sudo is not used for single-user mode'
  [[ -d /nix && -w /nix ]] || fail 'single-user mode requires an administrator-prepared writable /nix'
fi

if [[ -n "$installer_file" ]]; then
  installer=$installer_file
else
  command -v curl >/dev/null 2>&1 || fail 'curl is required to download the official installer'
  temp=$(mktemp) || fail 'cannot create installer temporary file'
  trap 'rm -f "$temp"' EXIT
  curl --fail --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 'https://nixos.org/nix/install' --output "$temp" || fail 'official installer download failed'
  [[ -s "$temp" ]] || fail 'official installer download was empty'
  installer=$temp
fi
if [[ $mode == --daemon ]]; then
  sudo_wrapper=$(mktemp -d) || fail 'cannot create noninteractive sudo wrapper'
  trap 'rm -rf "$sudo_wrapper"; [[ -z "${temp-}" ]] || rm -f "$temp"' EXIT
  printf '#!/bin/sh\nexec %q -n "$@"\n' "$sudo_path" >"$sudo_wrapper/sudo"
  chmod 700 "$sudo_wrapper/sudo"
  PATH="$sudo_wrapper:$PATH" NIX_BECOME="$sudo_wrapper/sudo" NIX_INSTALLER_YES=1 bash "$installer" "$mode" </dev/null
else
  NIX_INSTALLER_YES=1 bash "$installer" "$mode" </dev/null
fi
if nix_path=$(usable_nix); then
  printf 'Nix installation verified: %s\n' "$nix_path"
else
  fail 'installer returned success but no usable Nix store was found'
fi
