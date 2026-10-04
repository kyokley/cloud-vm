#!/usr/bin/env bash
# Post a message as the bot.
#
# Usage:
#   post_reply.sh <channel_id> <message...>
#   post_reply.sh --root <root_post_id> <channel_id> <message...>
#
# The message is always taken verbatim as the remaining arguments, so
# multi-word messages need no quoting and can never be mistaken for options.
#
# Config: MM_BASE, MM_TOKEN
# Prints the new post id. Exits non-zero if the post failed.
#
# This script does NOT touch replied.txt -- see mark_replied.sh. The id that
# belongs in replied.txt is the *inbound* post being answered, which only the
# caller knows.

set -uo pipefail

# Load the private env file, but keep a caller-supplied MM_DIR (see monitor.sh).
_caller_dir="${MM_DIR:-}"

MM_ENV="${MM_ENV:-$HOME/.config/mattermost/mattermost.env}"
if [ -z "${MM_BASE:-}" ] && [ -f "$MM_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$MM_ENV"
  set +a
fi

[ -n "$_caller_dir" ] && MM_DIR="$_caller_dir"

: "${MM_BASE:?MM_BASE required}"
: "${MM_TOKEN:?MM_TOKEN required}"
MM_DIR="${MM_DIR:-$HOME/mm-monitor}"
PAYLOAD="$MM_DIR/payload.json"

ROOT_ID=""
if [ "${1:-}" = "--root" ]; then
  ROOT_ID="${2:-}"
  shift 2
fi

[ "$#" -ge 2 ] || {
  echo "usage: post_reply.sh [--root <root_post_id>] <channel_id> <message...>" >&2
  exit 2
}

CHANNEL_ID="$1"
shift
MESSAGE="$*"

mkdir -p "$MM_DIR"

python3 -c '
import json, sys
payload = {"channel_id": sys.argv[1], "message": sys.argv[2]}
if len(sys.argv) > 3 and sys.argv[3]:
    payload["root_id"] = sys.argv[3]
json.dump(payload, open(sys.argv[4], "w"))
' "$CHANNEL_ID" "$MESSAGE" "$ROOT_ID" "$PAYLOAD"

resp="$(curl -s -w '\n%{http_code}' -X POST "$MM_BASE/api/v4/posts" \
  -H "Authorization: Bearer $MM_TOKEN" \
  -H "Content-Type: application/json" \
  --data @"$PAYLOAD")"

code="$(printf '%s' "$resp" | tail -n1)"
body="$(printf '%s' "$resp" | sed '$d')"

if [ "$code" != "201" ]; then
  echo "post failed HTTP:$code" >&2
  printf '%s\n' "$body" >&2
  exit 1
fi

printf '%s' "$body" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("posted", d.get("id", ""), "->", d.get("channel_id", ""))
'