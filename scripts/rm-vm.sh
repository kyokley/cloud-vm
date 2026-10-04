#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'rm-vm: %s\n' "$*" >&2
  exit 1
}

validate_name() {
  [[ $1 =~ ^[a-z][a-z0-9-]{0,38}[a-z0-9]$ || $1 =~ ^[a-z]$ ]] || fail "invalid VM name: $1"
}

cleanup_guest() {
  local vm=$1 target="vm+$1@vm.exe.xyz"
  printf 'rm-vm: checking Mattermost users on %s\n' "$vm" >&2
  # Send only guest_main, not this local script or its packaged runtime wrapper.
  # shellcheck disable=SC2029
  {
    declare -f guest_main
    printf 'guest_main\n'
  } | ssh "$target" 'bash -s' || fail "SSH cleanup failed for $vm"
}

guest_main() {
  set -euo pipefail
  local vm_host page=0 page_size=200 body status user_id matched_ids count=0
  local -a user_ids=()
  fail_guest() {
    printf 'rm-vm guest: %s\n' "$*" >&2
    exit 1
  }
  vm_host=$(hostname) || fail_guest 'cannot determine remote hostname'
  [[ -n $vm_host && $vm_host != *$'\n'* ]] || fail_guest 'remote hostname is invalid'
  tmpdir=$(mktemp -d) || fail_guest 'cannot create temporary directory'
  trap 'rm -rf -- "$tmpdir"' EXIT
  body=$tmpdir/response

  while :; do
    status=$(curl --silent --show-error --connect-timeout 5 --max-time 20 \
      --output "$body" --write-out '%{http_code}' \
      --get 'https://mattermost.int.exe.xyz/api/v4/users' \
      --data-urlencode 'active=true' --data-urlencode "page=$page" \
      --data-urlencode "per_page=$page_size") || fail_guest "Mattermost user request failed on page $page"
    [[ $status == 200 ]] || fail_guest "Mattermost user request returned HTTP $status on page $page"
    jq -e 'type == "array" and all(.[]; type == "object" and (.username | type == "string"))' "$body" >/dev/null \
      || fail_guest "Mattermost user response is invalid on page $page"

    count=$(jq 'length' "$body") || fail_guest "cannot read Mattermost page $page"
    matched_ids=$(jq -r --arg prefix "$vm_host-" \
      '.[] | select(.username | startswith($prefix) and length > ($prefix | length)) | .id | if type == "string" and length == 26 and test("^[a-z0-9]{26}$") then . else error("unsafe matched user ID") end' \
      "$body") \
      || fail_guest "cannot match Mattermost users on page $page"
    while IFS= read -r user_id; do
      [[ -n $user_id ]] || continue
      user_ids+=("$user_id")
    done <<<"$matched_ids"
    ((count == 0)) && break
    ((page += 1))
  done

  for user_id in "${user_ids[@]}"; do
    status=$(curl --silent --show-error --connect-timeout 5 --max-time 20 \
      --output "$body" --write-out '%{http_code}' --request DELETE \
      "https://mattermost.int.exe.xyz/api/v4/users/$user_id") \
      || fail_guest "Mattermost deactivation failed for user $user_id"
    [[ $status == 200 ]] || fail_guest "Mattermost deactivation returned HTTP $status for user $user_id"
    printf 'rm-vm: deactivated Mattermost user %s on %s\n' "$user_id" "$vm_host" >&2
  done
}

declare -a vms=()
if (($# == 0)); then
  if selected=$(ssh exe.dev ls --json | jq -er '.vms | if type == "array" then .[] | .vm_name | strings else error("vms must be an array") end' | fzf -m --marker='>' --cycle); then
    :
  else
    status=$?
    # fzf cancellation is a no-op; failures listing VM data are not.
    [[ $status == 130 ]] && exit 0
    fail 'cannot list or select VMs'
  fi
  [[ -n $selected ]] || exit 0
  mapfile -t vms <<<"$selected"
else
  vms=("$@")
fi

for vm in "${vms[@]}"; do
  validate_name "$vm"
done

for vm in "${vms[@]}"; do
  cleanup_guest "$vm"
  printf 'rm-vm: deleting VM %s\n' "$vm" >&2
  # VM name passed as a distinct, validated SSH argument.
  # shellcheck disable=SC2029
  ssh exe.dev rm "$vm" || fail "VM deletion failed for $vm"
done
