#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bootstrap-nix.sh --yes [--allow-sudo] [--installer-file PATH]

Install supported default Determinate Nix on Linux with systemd. --yes is
required consent to run the privileged installer noninteractively. A non-root
user must separately authorize sudo with --allow-sudo. Root may run this helper
directly. A reviewed installer file must already be on this guest; without it,
the helper downloads the official HTTPS entry script. The entry script may fetch
a separate platform installer. Existing Nix state is never migrated or changed.
EOF
}
fail() { printf 'bootstrap-nix: %s\n' "$*" >&2; exit 1; }

consent=0
allow_sudo=0
installer_file=''
while (($#)); do
  case "$1" in
    --yes) consent=1 ;;
    --allow-sudo) allow_sudo=1 ;;
    --installer-file)
      (($# >= 2)) || fail '--installer-file needs a guest path'
      installer_file=$2
      shift
      ;;
    --daemon|--no-daemon)
      fail 'legacy --daemon/--no-daemon modes were removed; Determinate Nix installs its systemd service'
      ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
  shift
done
((consent)) || fail 'installer execution requires --yes'

[[ $(uname -s) == Linux ]] || fail 'only Linux is supported'
case "$(uname -m)" in
  x86_64|aarch64) ;;
  *) fail "unsupported Linux architecture: $(uname -m)" ;;
esac
systemd_dir=/run/systemd/system
[[ -d "$systemd_dir" ]] || fail 'Determinate Nix requires usable systemd at /run/systemd/system'
command -v systemctl >/dev/null 2>&1 || fail 'Determinate Nix requires systemctl'
system_state=$(systemctl is-system-running 2>/dev/null || true)
[[ $system_state == running || $system_state == degraded ]] || fail "systemd is not usable (status: ${system_state:-unknown})"

nix_root=/nix
uid=$(id -u)
if [[ $uid != 0 ]]; then
  ((allow_sudo)) || fail 'non-root installation requires explicit --allow-sudo authorization'
  command -v sudo >/dev/null 2>&1 || fail 'non-root installation requires usable sudo'
  sudo -n true >/dev/null 2>&1 || fail 'sudo is unavailable without a password; configure privilege separately'
elif ((allow_sudo)); then
  printf 'Running as root; --allow-sudo is not needed.\n' >&2
fi

if [[ -e "$nix_root" || -L "$nix_root" ]]; then
  fail 'existing /nix state detected; inspect and perform any required migration manually'
fi
for candidate in \
  "$nix_root/receipt.json" \
  "$nix_root/nix-installer" \
  "$HOME/.nix-profile/bin/nix" \
  "$HOME/.local/state/nix/profile/bin/nix" \
  "$HOME/.local/state/nix/profiles/profile/bin/nix"; do
  if [[ -e "$candidate" || -L "$candidate" ]]; then
    fail "existing Nix installation marker detected at $candidate; inspect and migrate manually"
  fi
done
if command -v nix >/dev/null 2>&1; then
  fail "Nix command already exists at $(command -v nix); inspect and migrate manually"
fi

if [[ -n "$installer_file" ]]; then
  [[ -f "$installer_file" && -r "$installer_file" && -s "$installer_file" ]] || fail 'reviewed installer must be a readable, non-empty regular file'
  installer=$installer_file
else
  command -v curl >/dev/null 2>&1 || fail 'curl is required to download the official installer'
  temp=$(mktemp) || fail 'cannot create temporary installer file'
  trap 'rm -f "$temp"' EXIT
  curl --fail --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
    'https://install.determinate.systems/nix' --output "$temp" || fail 'official installer download failed'
  [[ -s "$temp" ]] || fail 'official installer download was empty'
  installer=$temp
fi

# Do not inherit the previous upstream installer's controls into this installer.
unset NIX_BECOME NIX_INSTALLER_YES
if [[ $uid == 0 ]]; then
  sh "$installer" install --no-confirm --diagnostic-endpoint= </dev/null
else
  sudo -n -- sh "$installer" install --no-confirm --diagnostic-endpoint= </dev/null
fi

usable_nix() {
  local candidate
  for candidate in \
    "$HOME/.nix-profile/bin/nix" \
    "$HOME/.local/state/nix/profile/bin/nix" \
    "$HOME/.local/state/nix/profiles/profile/bin/nix" \
    "$nix_root/var/nix/profiles/per-user/$(id -un)/profile/bin/nix" \
    "$nix_root/var/nix/profiles/default/bin/nix" \
    "$nix_root/var/nix/profiles/per-user/root/profile/bin/nix" \
    "$(command -v nix || true)"; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    if "$candidate" --version >/dev/null 2>&1 && \
      "$candidate" --experimental-features nix-command store ping --store daemon >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}
if nix_path=$(usable_nix); then
  printf 'Determinate Nix installation verified: %s\n' "$nix_path"
else
  fail 'installer returned success but Nix daemon store verification failed'
fi
