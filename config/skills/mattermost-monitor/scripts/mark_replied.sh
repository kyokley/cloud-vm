#!/usr/bin/env bash
# Record inbound post_ids as answered so triage never surfaces them again.
#
# Usage: mark_replied.sh <inbound_post_id> [inbound_post_id ...]
#
# Config: MM_DIR
#
# Call this with the id of the post you *responded to*, only after the reply
# actually posted. replied.txt is the durable idempotency key: it survives
# monitor restarts, event-log rewrites, and duplicate re-emits.

set -uo pipefail

# Keep a caller-supplied MM_DIR; the env file only fills gaps.
_caller_dir="${MM_DIR:-}"

MM_ENV="${MM_ENV:-$HOME/.config/mattermost/mattermost.env}"
if [ -z "${MM_DIR:-}" ] && [ -f "$MM_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$MM_ENV"
  set +a
fi

[ -n "$_caller_dir" ] && MM_DIR="$_caller_dir"
MM_DIR="${MM_DIR:-$HOME/mm-monitor}"
mkdir -p "$MM_DIR"

[ "$#" -ge 1 ] || { echo "usage: mark_replied.sh <post_id> [...]" >&2; exit 2; }

for pid in "$@"; do
  [ -n "$pid" ] && printf '%s\n' "$pid" >>"$MM_DIR/replied.txt"
done