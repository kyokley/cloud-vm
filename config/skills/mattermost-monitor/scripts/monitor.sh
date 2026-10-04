#!/usr/bin/env bash
# Poll Mattermost channels for new posts and append unseen ones to events.jsonl.
#
# Transport only. This script deliberately does NOT decide what to reply to and
# does NOT generate replies -- that judgment belongs to the agent. See
# wait_for_events.sh for triage and post_reply.sh for sending.
#
# Config (env or sourced config file):
#   MM_BASE     unproxied base URL   e.g. https://unproxied-mattermost.int.exe.xyz
#   MM_TOKEN    bot PAT              (Authorization: Bearer)
#   MM_SELF_ID  the bot's own user id -- its posts are skipped (reply-loop guard)
#   MM_CHANNELS "channel_id:Name,channel_id:Name"
#   MM_DIR      state dir            default: $HOME/mm-monitor
#   MM_POLL     poll seconds         default: 5
#
# Files in $MM_DIR:
#   events.jsonl  append-only log of new posts (one JSON object per line)
#   seen.txt      "<channel_id> <post_id>" dedupe set  <-- see NOTE below
#   state.json    {"ts": {channel_id: last_create_at}} API watermark
#   stop.flag     touch to shut down cleanly
#   monitor.log   lifecycle + stderr

set -uo pipefail

# Load the private env file for credentials and channel config, but never let it
# override MM_DIR/MM_POLL that the caller already set. Without this guard a
# scratch-dir run silently targets the real state dir -- and `--start-over`
# then wipes it. (That bug bit twice; the guard is the fix.)
_caller_dir="${MM_DIR:-}"
_caller_poll="${MM_POLL:-}"

MM_ENV="${MM_ENV:-$HOME/.config/mattermost/mattermost.env}"
if [ -z "${MM_BASE:-}" ] && [ -f "$MM_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$MM_ENV"
  set +a
fi

[ -n "$_caller_dir" ]  && MM_DIR="$_caller_dir"
[ -n "$_caller_poll" ] && MM_POLL="$_caller_poll"

: "${MM_BASE:?MM_BASE required}"
: "${MM_TOKEN:?MM_TOKEN required}"
: "${MM_SELF_ID:?MM_SELF_ID required}"
: "${MM_CHANNELS:?MM_CHANNELS required, e.g. abc123:Town Square}"
MM_DIR="${MM_DIR:-$HOME/mm-monitor}"
MM_POLL="${MM_POLL:-5}"

export MM_BASE MM_TOKEN MM_SELF_ID MM_CHANNELS MM_DIR

# Usage: monitor.sh [--seed-now|--start-over]
#   (default)     resume from the existing watermark in $MM_DIR/state.json
#   --seed-now    set the watermark to now, then run. Use when starting a
#                 brand-new monitor so channel history is NOT replayed as if
#                 it were new activity.
#   --start-over  discard state, seen-set and event log, then run as new.

mkdir -p "$MM_DIR"
EVENTS="$MM_DIR/events.jsonl"
STATE="$MM_DIR/state.json"
SEEN="$MM_DIR/seen.txt"
NAMES="$MM_DIR/usernames.txt"
STOP="$MM_DIR/stop.flag"
LOG="$MM_DIR/monitor.log"

log() { printf '%s %s\n' "$(date -Is)" "$*" >>"$LOG"; }

# Reset the watermark to now so the first poll does not replay channel
# history. A missing state.json is treated as "brand new monitor".
seed_now() {
  python3 -c "
import json, sys, time
ts = {}
for c in sys.argv[1].split(','):
    cid = c.split(':')[0]
    if cid:
        ts[cid] = int(time.time() * 1000)
json.dump({'ts': ts}, open(sys.argv[2], 'w'))
" "$MM_CHANNELS" "$STATE"
  log "watermark seeded to now (history will not be replayed)"
}

case "${1:-}" in
  --seed-now)    seed_now ;;
  --start-over)
    seed_now
    : >"$SEEN"
    : >"$EVENTS"
    echo 0 >"$MM_DIR/handled.offset"
    : >"$MM_DIR/replied.txt"
    log "start-over: state, seen-set and event log reset"
    ;;
  "")            [ -f "$STATE" ] || seed_now ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

rm -f "$STOP"
[ -f "$SEEN" ]  || : >"$SEEN"
[ -f "$NAMES" ] || : >"$NAMES"

log "monitor start pid=$$ channels=$MM_CHANNELS dir=$MM_DIR"

while [ ! -f "$STOP" ]; do
  IFS=',' read -r -a chans <<<"$MM_CHANNELS"

  for entry in "${chans[@]}"; do
    cid="${entry%%:*}"
    cname="${entry##*:}"

    [ -n "$cid" ] || continue

    last="$(python3 -c "
import json
try: d=json.load(open('$STATE'))
except Exception: d={'ts':{}}
print(d.get('ts',{}).get('$cid',0))
" 2>/dev/null || echo 0)"

    body="$(curl -s --max-time 20 \
      -H "Authorization: Bearer $MM_TOKEN" \
      "$MM_BASE/api/v4/channels/$cid/posts?since=$last&per_page=200")"

    printf '%s' "$body" | MM_CID="$cid" MM_CNAME="$cname" \
    MM_SELF_ID="$MM_SELF_ID" MM_TOKEN="$MM_TOKEN" MM_BASE="$MM_BASE" \
    python3 -c '
import json, os, sys, urllib.request

cid       = os.environ["MM_CID"]
cname     = os.environ["MM_CNAME"]
self_id   = os.environ["MM_SELF_ID"]
token     = os.environ["MM_TOKEN"]
base      = os.environ["MM_BASE"]
DIR       = os.environ["MM_DIR"]

EVENTS = os.path.join(DIR, "events.jsonl")
STATE  = os.path.join(DIR, "state.json")
SEEN   = os.path.join(DIR, "seen.txt")
NAMES  = os.path.join(DIR, "usernames.txt")

def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

posts = data.get("posts") or {}
if not posts:
    sys.exit(0)

# Advance the API watermark to the newest create_at in this response.
newest = max(p.get("create_at", 0) for p in posts.values())
try:
    st = json.load(open(STATE))
except Exception:
    st = {"ts": {}}
st.setdefault("ts", {})[cid] = newest
atomic_write(STATE, json.dumps(st))

# ---- dedupe on post_id, NOT on the timestamp watermark ----
# GET /posts?since= is inclusive at the boundary: the newest post is returned
# again on every subsequent poll. A timestamp-only cursor therefore re-emits
# duplicates forever. seen.txt is the real dedupe.
seen = set()
try:
    with open(SEEN) as f:
        for ln in f:
            c, _, pid = ln.strip().partition(" ")
            if c == cid and pid:
                seen.add(pid)
except FileNotFoundError:
    pass

out, fresh = [], set()

for p in sorted(posts.values(), key=lambda x: x.get("create_at", 0)):
    pid = p.get("id")
    if not pid or pid in seen:
        continue
    seen.add(pid)
    fresh.add(pid)

    if p.get("delete_at", 0):
        continue
    if p.get("user_id") == self_id:
        continue
    if p.get("type", "") not in ("", "system"):
        continue

    out.append({
        "post_id":    pid,
        "channel_id": cid,
        "channel":    cname,
        "user_id":    p.get("user_id"),
        "create_at":  p.get("create_at"),
        "root_id":    p.get("root_id", ""),
        "text":       (p.get("message") or "").strip(),
    })

if fresh:
    with open(SEEN, "a") as f:
        for pid in fresh:
            f.write(cid + " " + pid + "\n")

# The /posts payload does not populate post["user"], so "user" would degrade to
# a raw user id. Resolve display names once and cache them.
need = sorted({r["user_id"] for r in out if r["user_id"]})
if need:
    known = {}
    try:
        with open(NAMES) as f:
            for ln in f:
                uid, _, name = ln.strip().partition(" ")
                if uid and name:
                    known[uid] = name
    except FileNotFoundError:
        pass

    added = []
    for uid in need:
        if uid in known:
            continue
        try:
            req = urllib.request.Request(
                base + "/api/v4/users/" + uid,
                headers={"Authorization": "Bearer " + token},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                name = (json.load(r).get("username") or uid)
        except Exception:
            name = uid
        known[uid] = name
        added.append(uid + " " + name + "\n")

    if added:
        with open(NAMES, "a") as f:
            f.writelines(added)

    for r in out:
        r["user"] = known.get(r["user_id"], r["user_id"])

if out:
    with open(EVENTS, "a") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
' 2>>"$LOG"
  done

  sleep "$MM_POLL"
done

log "monitor stop"