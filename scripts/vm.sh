#!/usr/bin/env bash
set -euo pipefail

# Explicit allowlist of repository files transferred to guest VMs.
readonly guest_files=(
  flake.nix
  flake.lock
  config/target.nix
  config/home.nix
  config/powerlevel10k_config.zsh
  config/_bun.nix
  config/bun.lock
  config/package.json
  config/stacked-jj-prs.md
  config/skills/exe-dev/SKILL.md
  config/skills/mattermost-proxy-pat/SKILL.md
)

usage() {
  cat <<'EOF'
Usage:
  vm.sh inspect NAME
  vm.sh bootstrap NAME --yes --allow-sudo [--installer-file GUEST_PATH]
  vm.sh apply NAME

NAME is a lowercase VM name. SSH target is vm+NAME@vm.exe.xyz; normal host-key
checking remains enabled. --installer-file names a file already on the guest.
Apply transfers only flake.nix, flake.lock, config/target.nix, config/home.nix,
config/powerlevel10k_config.zsh, config/_bun.nix, config/package.json,
config/bun.lock, config/stacked-jj-prs.md, and config/skills/exe-dev/SKILL.md.
Add local inputs only by deliberate allowlist changes here.
Apply needs local nix, tar, ssh, and Python 3. Deployment does not bootstrap Nix.
EOF
}
fail() {
  printf 'vm.sh: %s\n' "$*" >&2
  exit 1
}
validate_bootstrap_options() {
  local consent=0 allow_sudo=0 installer_file=0
  while (($#)); do
    case "$1" in
    --yes)
      ((consent == 0)) || fail 'duplicate --yes'
      consent=1
      ;;
    --allow-sudo)
      ((allow_sudo == 0)) || fail 'duplicate --allow-sudo'
      allow_sudo=1
      ;;
    --installer-file)
      ((installer_file == 0 && $# >= 2)) || fail '--installer-file needs one guest path'
      [[ -n "$2" ]] || fail '--installer-file path must not be empty'
      installer_file=1
      shift
      ;;
    --daemon | --no-daemon) fail 'legacy --daemon/--no-daemon modes were removed; use Determinate Nix systemd installation' ;;
    *) fail "unknown bootstrap option: $1" ;;
    esac
    shift
  done
  ((consent)) || fail 'bootstrap requires explicit --yes consent'
  ((allow_sudo)) || fail 'VM bootstrap requires explicit --allow-sudo authorization'
}
# Guest entry point. This exact source is sent over SSH; no remote shell input is evaluated.
guest_main() {
  set -euo pipefail
  op=${1:?}
  shift
  fail_guest() {
    printf 'vm.sh guest: %s\n' "$*" >&2
    exit 1
  }
  check_directory() {
    local path=$1 mode
    [[ ! -L "$path" ]] || fail_guest "symlink path rejected: $path; replace it with a real directory"
    if [[ -e "$path" ]]; then
      [[ -d "$path" && $(stat -c %u "$path") == "$(id -u)" ]] || fail_guest "unsafe owner or non-directory path: $path; use a user-owned directory"
      mode=$(stat -c %a "$path") || fail_guest "cannot inspect permissions: $path; inspect and fix it manually"
      [[ $mode =~ ^[0-7]{3,4}$ ]] || fail_guest "unknown directory permissions: $path; inspect and fix it manually"
      (((8#$mode & 8#0022) == 0)) || fail_guest "group/other-writable directory rejected: $path; remove group/other write permission"
    fi
  }
  case "$op" in
  inspect)
    printf 'username=%s\nuid=%s\nhome=%s\nos=%s\narchitecture=%s\n' "$(id -un)" "$(id -u)" "$HOME" "$(uname -s)" "$(uname -m)"
    printf 'sudo='
    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      printf 'usable\n'
    else
      printf 'unavailable\n'
    fi
    printf 'systemd='
    if [[ -d /run/systemd/system ]]; then printf 'usable\n'; else printf 'unavailable\n'; fi
    ;;
  identity)
    printf '%s\n%s\n%s\n%s\n%s\n' "$(id -un)" "$(id -u)" "$HOME" "$(uname -s)" "$(uname -m)"
    ;;
  prepare)
    [[ $(id -u) -ne 0 ]] || fail_guest 'root target is not supported'
    dest="$HOME/.local/share/cloud-vm"
    [[ "$dest" == "$HOME"/* ]] || fail_guest 'unsafe home directory'
    for path in "$HOME" "$HOME/.local" "$HOME/.local/share" "$dest" "$dest/config" "$dest/config/skills" "$dest/config/skills/exe-dev"; do
      check_directory "$path"
    done
    umask 077
    mkdir -p "$dest/config/skills/exe-dev"
    for file in "${guest_files[@]}"; do
      path="$dest/$file"
      if [[ -e "$path" || -L "$path" ]]; then
        [[ -f "$path" && ! -L "$path" && $(stat -c %u "$path") == "$(id -u)" ]] || fail_guest "unsafe input destination: $path"
      fi
    done
    ;;
  nix-path)
    for candidate in "$HOME/.nix-profile/bin/nix" "$HOME/.local/state/nix/profile/bin/nix" "/nix/var/nix/profiles/per-user/$(id -un)/profile/bin/nix" /nix/var/nix/profiles/default/bin/nix /nix/var/nix/profiles/per-user/root/profile/bin/nix; do
      if [[ -x "$candidate" ]]; then
        if "$candidate" --version >/dev/null 2>&1 && "$candidate" --experimental-features nix-command store ping >/dev/null 2>&1; then
          printf '%s\n' "$candidate"
          exit 0
        fi
      fi
    done
    candidate=$(command -v nix) || fail_guest 'usable Nix not found in standard profiles or PATH'
    if ! "$candidate" --version >/dev/null 2>&1 || ! "$candidate" --experimental-features nix-command store ping >/dev/null 2>&1; then
      fail_guest 'Nix command cannot use its selected store'
    fi
    printf '%s\n' "$candidate"
    ;;
  build)
    nixbin=$1
    dest="$HOME/.local/share/cloud-vm"
    "$nixbin" --extra-experimental-features 'nix-command flakes' build --no-update-lock-file --no-write-lock-file --out-link "$dest/.activation" "path:$dest#homeConfigurations.vm.activationPackage"
    ;;
  activate)
    "$HOME/.local/share/cloud-vm/.activation/activate"
    ;;
  set-shell)
    zsh_path="$HOME/.nix-profile/bin/zsh"
    [[ -x "$zsh_path" ]] || fail_guest "Home Manager zsh is missing or not executable: $zsh_path"
    username=$(id -un) || fail_guest 'cannot identify current account'
    [[ -n "$username" && "$username" != *$'\n'* ]] || fail_guest 'current account name is invalid'
    passwd_entry=$(getent passwd "$username") || fail_guest "cannot look up passwd entry for $username"
    [[ -n "$passwd_entry" && "$passwd_entry" != *$'\n'* ]] || fail_guest "passwd lookup for $username is invalid"
    IFS=: read -r passwd_user _ _ _ _ _ login_shell extra <<<"$passwd_entry"
    [[ "$passwd_user" == "$username" && -n "$login_shell" && -z "${extra:-}" ]] || fail_guest "passwd lookup for $username is invalid"
    if ! grep -Fqx -- "$zsh_path" /etc/shells; then
      command -v sudo >/dev/null 2>&1 || fail_guest 'sudo is required to register zsh in /etc/shells'
      sudo -n tee -a /etc/shells <<<"$zsh_path" >/dev/null || fail_guest 'cannot register zsh in /etc/shells with noninteractive sudo'
    fi
    if [[ "$login_shell" != "$zsh_path" ]]; then
      command -v sudo >/dev/null 2>&1 || fail_guest 'sudo is required to change the login shell'
      sudo -n chsh -s "$zsh_path" "$username" || fail_guest "cannot change login shell for $username with noninteractive sudo"
    fi
    ;;
  *) fail_guest "unknown operation: $op" ;;
  esac
}

if [[ ${1-} == --help || ${1-} == -h ]]; then
  usage
  exit 0
fi
if [[ ${1-} == __guest ]]; then
  shift
  guest_main "$@"
  exit
fi
script_path=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/$(basename -- "${BASH_SOURCE[0]}")
root=$(CDPATH='' cd -- "$(dirname -- "$script_path")/.." && pwd -P)
[[ $# -ge 2 ]] || {
  usage >&2
  exit 2
}
action=$1 name=$2
shift 2
[[ $name =~ ^[a-z][a-z0-9-]{0,38}[a-z0-9]$ || $name =~ ^[a-z]$ ]] || fail 'invalid VM name'
target="vm+$name@vm.exe.xyz"
send_guest() { # Arguments are escaped for the remote shell by printf %q; SSH keeps host-key checking enabled.
  # shellcheck disable=SC2029
  ssh "$target" "bash -s -- $(printf '%q ' "$@")" <"$script_path"
}

case "$action" in
inspect)
  (($# == 0)) || fail 'inspect accepts only NAME'
  send_guest __guest inspect
  ;;
bootstrap)
  validate_bootstrap_options "$@"
  send_guest __guest identity >/dev/null || fail 'cannot inspect guest identity'
  # Bootstrap options remain separate SSH argv values and are shell-quoted by printf %q.
  # Options are escaped for the remote shell by printf %q; installer file path stays guest-side.
  # shellcheck disable=SC2029
  ssh "$target" "bash -s -- $(printf '%q ' "$@")" <"$root/scripts/bootstrap-nix.sh"
  ;;
apply)
  (($# == 0)) || fail 'apply accepts only NAME'
  for cmd in nix tar ssh python3; do command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required; see --help"; done
  [[ -d "$root/config" && ! -L "$root/config" ]] || fail 'required local input directory missing or unsafe: config'
  for file in "${guest_files[@]}"; do [[ -f "$root/$file" && ! -L "$root/$file" ]] || fail "required local input missing or unsafe: $file"; done
  target_json=$(nix --extra-experimental-features 'nix-command flakes' eval --json --no-update-lock-file --no-write-lock-file "path:$root#lib.target") || fail 'cannot evaluate lib.target'
  python3 -c 'import json,re,sys; x=json.load(sys.stdin); home=x.get("homeDirectory") if isinstance(x,dict) else None; ok=isinstance(x,dict) and set(x)=={"system","username","homeDirectory"} and x["system"] in ("x86_64-linux","aarch64-linux") and re.fullmatch(r"[a-z_][a-z0-9_-]*",x["username"]) and x["username"] not in ("root","example") and isinstance(home,str) and home.startswith("/") and not any(p in (".","..") for p in home.split("/")) and not any(ord(c)<32 for c in home); sys.exit(0 if ok else 1)' <<<"$target_json" || fail 'target identity is placeholder or unsafe'
  IFS=$'\t' read -r expected_username expected_home expected_system <<<"$(python3 -c 'import json,sys; x=json.load(sys.stdin); print("\t".join((x["username"],x["homeDirectory"],x["system"])))' <<<"$target_json")"
  identity=$(send_guest __guest identity) || fail 'cannot inspect guest identity'
  observed_username=$(printf '%s\n' "$identity" | awk 'NR == 1')
  observed_uid=$(printf '%s\n' "$identity" | awk 'NR == 2')
  observed_home=$(printf '%s\n' "$identity" | awk 'NR == 3')
  observed_os=$(printf '%s\n' "$identity" | awk 'NR == 4')
  guest_arch=$(printf '%s\n' "$identity" | awk 'NR == 5')
  [[ -n "$observed_username" && -n "$guest_arch" ]] || fail 'guest identity response invalid'
  [[ $observed_uid != 0 ]] || fail 'root target is not supported'
  [[ $observed_username == "$expected_username" && $observed_home == "$expected_home" && $observed_os == Linux ]] || fail 'configured username, home, or OS does not match guest'
  case "$expected_system:$guest_arch" in x86_64-linux:x86_64 | aarch64-linux:aarch64) ;; *) fail 'configured architecture does not match guest' ;; esac
  send_guest __guest prepare || fail 'guest destination is unsafe'
  tar -C "$root" -cf - "${guest_files[@]}" | ssh "$target" 'umask 077; tar -xf - -C "$HOME/.local/share/cloud-vm" --no-same-owner --no-same-permissions'
  nixbin=$(send_guest __guest nix-path) || fail 'guest has no usable Nix'
  send_guest __guest build "$nixbin"
  send_guest __guest activate "$nixbin"
  send_guest __guest set-shell
  ;;
--help | -h) usage ;;
*)
  usage >&2
  fail "unknown action: $action"
  ;;
esac
