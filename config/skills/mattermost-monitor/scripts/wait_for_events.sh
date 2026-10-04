#!/usr/bin/env bash
# Block until a post worth answering appears in events.jsonl, then print triage
# candidates as JSON lines. This is how the agent waits *inside a turn* without
# busy-polling by hand.
#
# Usage: wait_for_events.sh [timeout_seconds]        (default 180)
#   exit 0 -> candidates printed
#   exit 1 -> timed out with nothing to answer
#
# Config: MM_DIR, MM_SELF_ID, MM_ME (the bot's username)
#
# Classification per post:
#   "mention"  -- @bot or the bot's name appears in the text
#   "question" -- ends in '?' and no mention
#   "skip"     -- everything else
#
# Two independent duplicate guards:
#   handled.offset  line cursor into events.jsonl (this process's progress)
#   replied.txt     post_ids already answered (survives re-emits and restarts)

set -uo pipefail

# Load the private env file, but keep a caller-supplied MM_DIR (see monitor.sh).
_caller_dir="${MM_DIR:-}"

MM_ENV="${MM_ENV:-$HOME/.config/mattermost/mattermost.env}"
if [ -z "${MM_SELF_ID:-}" ] && [ -f "$MM_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$MM_ENV"
  set +a
fi

[ -n "$_caller_dir" ] && MM_DIR="$_caller_dir"

: "${MM_SELF_ID:?MM_SELF_ID required}"
: "${MM_ME:?MM_ME required, e.g. my-bot}"
MM_DIR="${MM_DIR:-$HOME/mm-monitor}"
TIMEOUT="${1:-180}"

EVENTS="$MM_DIR/events.jsonl"
OFFSET="$MM_DIR/handled.offset"
mkdir -p "$MM_DIR"
[ -f "$OFFSET" ] || echo 0 >"$OFFSET"

deadline=$(( $(date +%s) + TIMEOUT ))

while [ "$(date +%s)" -lt "$deadline" ]; do
  out="$(python3 - "$EVENTS" "$OFFSET" "$MM_SELF_ID" "$MM_ME" "$MM_DIR" <<'PY' 2>>"$MM_DIR/monitor.log"
import json, os, sys

events_path, offset_path, self_id, me, base_dir = sys.argv[1:6]
replied_path = os.path.join(base_dir, "replied.txt")

try:
    replied = {l.strip() for l in open(replied_path) if l.strip()}
except Exception:
    replied = set()

try:
    off = int(open(offset_path).read().strip() or 0)
except Exception:
    off = 0

try:
    lines = open(events_path).read().splitlines()
except Exception:
    lines = []

new = lines[off:]
if not new:
    sys.exit(0)

cands = []
handled = set()
me_l = me.lower()

for ln in new:
    ln = ln.strip()
    if not ln:
        continue
    try:
        e = json.loads(ln)
    except Exception:
        continue

    if e.get("user_id") == self_id:
        continue

    pid = e.get("post_id")
    if not pid or pid in handled or pid in replied:
        continue
    handled.add(pid)

    text = e.get("text", "")
    low = text.lower()
    if ("@" + me_l) in low or me_l in low:
        kind = "mention"
    elif text.rstrip().endswith("?"):
        kind = "question"
    else:
        kind = "skip"
    e["kind"] = kind
    cands.append(e)

# Advance the cursor past everything examined, replied or not.
with open(offset_path, "w") as f:
    f.write(str(len(lines)))

for c in cands:
    print(json.dumps(c))
PY
)"
  if [ -n "$out" ]; then
    printf '%s' "$out"
    exit 0
  fi
  sleep 3
done

exit 1