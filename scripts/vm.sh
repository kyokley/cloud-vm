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
  config/skills/stacked-jj-prs/SKILL.md
  config/skills/exe-dev/SKILL.md
  config/skills/mattermost-proxy-pat/SKILL.md
  config/skills/mattermost-monitor/SKILL.md
  config/skills/mattermost-monitor/scripts/mark_replied.sh
  config/skills/mattermost-monitor/scripts/mattermost.env.example
  config/skills/mattermost-monitor/scripts/monitor.sh
  config/skills/mattermost-monitor/scripts/post_reply.sh
  config/skills/mattermost-monitor/scripts/wait_for_events.sh
)

usage() {
  cat <<'EOF'
Usage:
  vm.sh inspect NAME
  vm.sh bootstrap NAME --yes --allow-sudo [--installer-file GUEST_PATH]
  vm.sh apply NAME --yes [--target KEY]

NAME is a lowercase VM name. SSH target is vm+NAME@vm.exe.xyz; normal host-key
checking remains enabled. Inspect reports guest identity, systemd, Nix, and
Home Manager detection. --installer-file names a file already on the guest.
Apply requires explicit --yes authorization. It selects a matching fleet target
or the base vm target; --target requires a registered key. The guest stages the
complete snapshot in ~/.local/share/cloud-vm/.incoming, publishes it as
~/.local/share/cloud-vm/source, and builds from that source; .activation stays
at the reserved project root.

Transfer includes flake.nix, flake.lock, the explicit guest_files allowlist
below, and only .nix files matching modules/**/*.nix and config/vms/**/*.nix. The explicit
allowlist includes config/target.nix, config/home.nix,
config/powerlevel10k_config.zsh, config/_bun.nix, config/bun.lock,
config/package.json, config/skills/stacked-jj-prs/SKILL.md,
config/skills/exe-dev/SKILL.md, config/skills/mattermost-proxy-pat/SKILL.md,
config/skills/mattermost-monitor/SKILL.md, and
config/skills/mattermost-monitor/scripts/{mark_replied.sh,
mattermost.env.example,monitor.sh,post_reply.sh,wait_for_events.sh}.
No other config files are transferred. Add local inputs only by deliberate
allowlist changes here. Apply needs local nix, tar, ssh, and Python 3.
Deployment does not bootstrap Nix.
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
    nix_detected=0
    for candidate in "$HOME/.nix-profile/bin/nix" "$HOME/.local/state/nix/profile/bin/nix" \
      "/nix/var/nix/profiles/per-user/$(id -un)/profile/bin/nix" /nix/var/nix/profiles/default/bin/nix; do
      if [[ -x "$candidate" ]] && "$candidate" --version >/dev/null 2>&1 && \
        "$candidate" --experimental-features nix-command store ping >/dev/null 2>&1; then nix_detected=1; break; fi
    done
    if ((nix_detected == 0)) && command -v nix >/dev/null 2>&1; then
      candidate=$(command -v nix)
      if "$candidate" --version >/dev/null 2>&1 && "$candidate" --experimental-features nix-command store ping >/dev/null 2>&1; then nix_detected=1; fi
    fi
    printf 'nix=%s\n' "$([[ $nix_detected == 1 ]] && printf installed || printf not-detected)"
    hm_detected=0
    for candidate in "$HOME/.nix-profile/bin/home-manager" "$HOME/.local/state/nix/profile/bin/home-manager"; do
      if [[ -x "$candidate" ]] && "$candidate" --version >/dev/null 2>&1; then hm_detected=1; break; fi
    done
    if ((hm_detected == 0)) && command -v home-manager >/dev/null 2>&1; then
      candidate=$(command -v home-manager)
      if "$candidate" --version >/dev/null 2>&1; then hm_detected=1; fi
    fi
    printf 'home_manager=%s\n' "$([[ $hm_detected == 1 ]] && printf installed || printf not-detected)"
    ;;
  identity)
    printf '%s\n%s\n%s\n%s\n%s\n' "$(id -un)" "$(id -u)" "$HOME" "$(uname -s)" "$(uname -m)"
    ;;
  prepare)
    [[ $(id -u) -ne 0 ]] || fail_guest 'root target is not supported'
    dest="$HOME/.local/share/cloud-vm"
    [[ "$dest" == "$HOME"/* ]] || fail_guest 'unsafe home directory'
    for path in "$HOME" "$HOME/.local" "$HOME/.local/share" "$dest"; do
      check_directory "$path"
    done
    umask 077
    mkdir -p "$dest"
    [[ ! -e "$dest/.incoming" && ! -L "$dest/.incoming" ]] || fail_guest 'stale transfer stage exists; inspect and remove it manually'
    mkdir -m 700 "$dest/.incoming"
    for path in "$dest/source" "$dest/source.previous"; do
      check_directory "$path"
    done
    for file in "${guest_files[@]}"; do
      path="$dest/source/$file"
      directory="$dest/source"
      check_directory "$directory"
      if [[ $file == */* ]]; then
        IFS=/ read -r -a input_parts <<<"${file%/*}"
        for part in "${input_parts[@]}"; do
          directory="$directory/$part"
          check_directory "$directory"
        done
      fi
      if [[ -e "$path" || -L "$path" ]]; then
        [[ -f "$path" && ! -L "$path" && $(stat -c %u "$path") == "$(id -u)" ]] || fail_guest "unsafe input destination: $path"
      fi
    done
    ;;
  publish)
    dest="$HOME/.local/share/cloud-vm"
    incoming="$dest/.incoming"
    source="$dest/source"
    previous="$dest/source.previous"
    check_directory "$dest"
    check_directory "$incoming"
    [[ -d "$incoming" && ! -L "$incoming" ]] || fail_guest 'transfer stage is unsafe'
    if [[ -e "$source" || -L "$source" ]]; then
      [[ -d "$source" && ! -L "$source" && $(stat -c %u "$source") == "$(id -u)" ]] || fail_guest 'existing source snapshot is unsafe'
      [[ ! -e "$previous" && ! -L "$previous" ]] || fail_guest 'previous source snapshot exists; inspect it manually'
      mv -- "$source" "$previous" || fail_guest 'cannot stage existing source snapshot'
    fi
    if ! mv -- "$incoming" "$source"; then
      [[ ! -e "$previous" || -e "$source" ]] || mv -- "$previous" "$source"
      fail_guest 'cannot publish transferred source snapshot'
    fi
    if [[ -e "$previous" ]]; then rm -rf -- "$previous" || fail_guest 'new source published but old snapshot cleanup failed'; fi
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
    nixbin=$1 target_key=$2
    dest="$HOME/.local/share/cloud-vm/source"
    "$nixbin" --extra-experimental-features 'nix-command flakes' build --no-update-lock-file --no-write-lock-file --out-link "$HOME/.local/share/cloud-vm/.activation" "path:$dest#homeConfigurations.$target_key.activationPackage"
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
  consent=0 explicit_target=''
  while (($#)); do
    case "$1" in
      --yes) ((consent == 0)) || fail 'duplicate --yes'; consent=1 ;;
      --target)
        (($# >= 2)) || fail '--target needs a key'
        [[ -n $2 ]] || fail '--target key must not be empty'
        [[ -z $explicit_target ]] || fail 'duplicate --target'
        explicit_target=$2
        shift
        ;;
      *) fail "unknown apply option: $1" ;;
    esac
    shift
  done
  ((consent)) || fail 'apply requires explicit --yes consent'
  if [[ -n $explicit_target ]]; then
    [[ $explicit_target =~ ^([a-z]|[a-z][a-z0-9-]{0,38}[a-z0-9])$ || $explicit_target == vm ]] || fail 'invalid target key'
  fi
  for cmd in nix tar ssh python3 find sort; do command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required; see --help"; done
  [[ -d "$root/config" && ! -L "$root/config" ]] || fail 'required local input directory missing or unsafe: config'
  transfer_files=("${guest_files[@]}")
  check_local_path() {
    local relative=$1 current=$root part
    IFS=/ read -r -a parts <<<"$relative"
    for ((i=0; i<${#parts[@]}; i++)); do
      part=${parts[i]}
      current="$current/$part"
      [[ ! -L "$current" ]] || fail "required local input missing or unsafe: $relative"
      if ((i < ${#parts[@]} - 1)); then [[ -d "$current" ]] || fail "required local input missing or unsafe: $relative"; fi
    done
    [[ -f "$current" ]] || fail "required local input missing or unsafe: $relative"
  }
  for file in "${guest_files[@]}"; do check_local_path "$file"; done
  for tree in modules config/vms; do
    [[ ! -L "$root/$tree" ]] || fail "required local input directory is unsafe: $tree"
    [[ -d "$root/$tree" ]] || continue
    symlink=$(find "$root/$tree" -type l -print -quit)
    [[ -z $symlink ]] || fail "symlinked deployment input rejected: $tree"
    while IFS= read -r -d '' file; do
      relative=${file#"$root/"}
      check_local_path "$relative"
      transfer_files+=("$relative")
    done < <(find "$root/$tree" -type f -name '*.nix' -print0 | sort -z)
  done
  targets_json=$(nix --extra-experimental-features 'nix-command flakes' eval --json --no-update-lock-file --no-write-lock-file "path:$root#lib.fleet.targets") || fail 'cannot evaluate lib.fleet.targets'
  base_json=$(nix --extra-experimental-features 'nix-command flakes' eval --json --no-update-lock-file --no-write-lock-file "path:$root#lib.target") || fail 'cannot evaluate lib.target'
  selected=$(python3 -c 'import json,re,sys
name,explicit=sys.argv[1:]
try:
 targets=json.loads(sys.stdin.readline()); base=json.loads(sys.stdin.readline())
except Exception: sys.exit(2)
if not isinstance(targets,dict): sys.exit(2)
key=explicit or (name if name != "vm" and name in targets else "vm")
if explicit and key != "vm" and key not in targets: sys.exit(3)
target=base if key == "vm" else targets[key]
home=target.get("homeDirectory") if isinstance(target,dict) else None
ok=isinstance(target,dict) and set(target)=={"system","username","homeDirectory"} and target["system"] in ("x86_64-linux","aarch64-linux") and isinstance(target["username"],str) and re.fullmatch(r"[a-z_][a-z0-9_-]*",target["username"]) and target["username"] not in ("root","example") and isinstance(home,str) and home.startswith("/") and not any(p in (".","..") for p in home.split("/")) and not any(ord(c)<32 for c in home)
if not ok: sys.exit(4)
print(key+"\t"+target["username"]+"\t"+target["homeDirectory"]+"\t"+target["system"])' "$name" "$explicit_target" <<<"$targets_json
$base_json") || {
    status=$?
    ((status != 3)) || fail "unknown explicit target: $explicit_target"
    fail 'target metadata is malformed or identity is placeholder or unsafe'
  }
  IFS=$'\t' read -r selected_target expected_username expected_home expected_system <<<"$selected"
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
  tar -C "$root" -cf - "${transfer_files[@]}" | ssh "$target" 'umask 077; tar -xf - -C "$HOME/.local/share/cloud-vm/.incoming" --no-same-owner --no-same-permissions' || fail 'source transfer failed; activation was not run'
  send_guest __guest publish || fail 'cannot publish complete source snapshot; activation was not run'
  nixbin=$(send_guest __guest nix-path) || fail 'guest has no usable Nix'
  send_guest __guest build "$nixbin" "$selected_target"
  send_guest __guest activate "$nixbin"
  send_guest __guest set-shell
  ;;
--help | -h) usage ;;
*)
  usage >&2
  fail "unknown action: $action"
  ;;
esac
