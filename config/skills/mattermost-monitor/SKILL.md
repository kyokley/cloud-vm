---
name: mattermost-monitor
description: Use when asked to monitor, watch, poll, or auto-reply to Mattermost channels - e.g. "monitor mattermost", "watch for messages", "respond to mentions in the channel", "keep an eye on Town Square". Runs a background poller that captures new posts to a JSONL log and surfaces mentions or questions to the agent for replies. Also covers creating the bot account and personal access token.
---

# Mattermost monitor and auto-responder

Builds a **poller** that captures new posts to an append-only log, plus a
**triage** step that surfaces mentions and questions to the agent. The agent
writes the replies.

The split matters: the shell script does transport and filtering only. Reply
content needs model judgment, so it must not be generated inside the polling
loop.

## Architecture

```
monitor.sh        background, long-running. GETs new posts -> events.jsonl
                  (transport only: no reply text, no judgment)
wait_for_events.sh  blocks inside a turn, prints triage candidates as JSON
                  (kind = mention | question | skip)
   -> agent composes the reply
post_reply.sh     POSTs the message
mark_replied.sh   records the answered inbound post_id (idempotency)
```

Two independent duplicate guards:

| Guard | File | Stops |
|---|---|---|
| API-level | `seen.txt` | the same post being captured twice |
| Reply-level | `replied.txt` | the same post being answered twice |

## Setup

Prerequisites: `hostname`, `curl`, `python3`, `jq`-free (python does the JSON).
Create the bot account and token first, then fill in a config file:

```bash
S=$(date +%s | tail -c 5); U="bot-${S}"
ID=$(curl -s -X POST "$PROXY/api/v4/users" -H "Content-Type: application/json" \
  -d "{\"email\":\"${U}@example.com\",\"username\":\"${U}\",\"password\":\"<strong-pw>\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
TOK=$(curl -s -X POST "$PROXY/api/v4/users/${ID}/tokens" \
  -H "Content-Type: application/json" -d '{"description":"bot"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -X POST "$PROXY/api/v4/teams/$TEAM/members" -H "Content-Type: application/json" \
  -d "{\"team_id\":\"$TEAM\",\"user_id\":\"${ID}\"}"
```

The **proxied** base URL needs no credentials; the **unproxied** one requires
`Authorization: Bearer $TOKEN`.

**Keep credentials out of this skill directory.** Skills get copied, shared,
and pasted into docs. Write the env file somewhere private instead:

```bash
install -d -m 700 ~/.config/mattermost
install -m 600 scripts/mattermost.env.example ~/.config/mattermost/mattermost.env
$EDITOR ~/.config/mattermost/mattermost.env      # fill in MM_TOKEN, MM_SELF_ID, MM_ME, MM_CHANNELS
```

The scripts auto-load `$MM_ENV` (default
`~/.config/mattermost/mattermost.env`) when their required variables are unset,
so no manual `source` is needed. Override the file's location with `MM_ENV`.

Precedence: an already-exported variable suppresses the auto-load entirely (so
`MM_BASE=... cmd` wins), **except** `MM_DIR` and `MM_POLL`, which are always
taken from the caller. That exception is deliberate — see the trap below.
Verify the private file is unreadable by others:
`stat -c '%a %n' ~/.config/mattermost/mattermost.env` → `600`.

Discover the channel ids before filling in `MM_CHANNELS`:

```bash
curl -s -H "Authorization: Bearer $MM_TOKEN" \
  "$MM_BASE/api/v4/users/me/teams/$MM_TEAM_ID/channels" \
  | python3 -c "import sys,json;[print(c['id'],c['display_name']) for c in json.load(sys.stdin)]"
```

Format `MM_CHANNELS` as `id:Name,id:Name`. `$MM_SCRIPTS` in the examples below is
the skill's own `scripts/` directory; it is set in the env file so the commands
work regardless of where the skill is installed.

## Start

```bash
"$MM_SCRIPTS/monitor.sh" --start-over   # fresh: no history replay
setsid nohup "$MM_SCRIPTS/monitor.sh" >/dev/null 2>&1 </dev/null &
```

| Flag | Effect |
|---|---|
| *(none)* | resume from the existing watermark |
| `--seed-now` | watermark = now, then run. **Use on first start**, else every historical post is treated as new |
| `--start-over` | also wipe `seen.txt`, `events.jsonl`, `replied.txt`, `handled.offset` |

Shut down with `touch "$MM_DIR/stop.flag"` — the loop checks it each cycle and
exits cleanly. Do not `kill -9`; a half-written state file is annoying to
recover.

**`MM_DIR` must be exported or passed consistently.** The script resolves a
default, and its inline Python reads `MM_DIR` from the environment. If you
`unset MM_DIR` to "test the default" and also pass `--start-over`, the reset
hits your *real* state directory. Set `MM_DIR` explicitly and point tests at a
scratch dir.

## Respond

```bash
"$MM_SCRIPTS/wait_for_events.sh" 240     # exit 0 = candidates, 1 = timeout
```

Each candidate carries `post_id`, `channel`, `user`, `text`, `kind`. Then:

```bash
"$MM_SCRIPTS/post_reply.sh" "$CHANNEL_ID" "your reply"
"$MM_SCRIPTS/post_reply.sh" --root "$POST_ID" "$CHANNEL_ID" "threaded reply"
"$MM_SCRIPTS/mark_replied.sh" "$INBOUND_POST_ID"    # only after the post succeeded
```

Loop `wait_for_events.sh` for as long as the user asked. Use a bounded window
(a few minutes) per call — pass a `timeout` larger than the tool's own timeout
so the script, not the harness, decides when to give up.

### Reply etiquette

- Resolve the asker's username with `GET /api/v4/users/<id>` if `user` is an
  id, and address them by name.
- Thread the reply (`--root`) when someone asked you something specific.
- Mark answered posts only **after** `post_reply.sh` exits 0. Marking first
  loses the reply on failure, and the post is never retried.
- "Mentions + questions" beats "every message": reacting to all traffic gets
  noisy fast and can ping-pong.

## Traps

**`?since=` is inclusive at the boundary.** The newest post comes back on every
poll. A timestamp cursor alone therefore re-emits duplicates forever. Dedupe on
`post_id` via `seen.txt`; treat the watermark purely as a response-size
optimisation.

**A missing `state.json` means "new monitor".** It must seed to *now*, not
epoch 0, or the first poll returns the entire channel and the agent answers a
week of backlog.

**Never record your own posts as answered.** `replied.txt` holds the
**inbound** post id being answered. Writing your outgoing post id there is
useless — `monitor.sh` already drops your posts by `user_id`.

**A quoted heredoc does not expand variables.** `python3 - <<'PY'` leaves
`"$DIR/foo"` as a literal. Pass paths as `argv` (`python3 - "$DIR" <<'PY'`) or
the script will read a nonexistent path.

**`GET /posts` does not populate `post["user"]`.** `user` degrades to a raw
id. Resolve via `/users/<id>` once and cache in `usernames.txt`.

**`/tmp/opencode` is not writable here** (root-owned). Use `$HOME`.

**Never keep the PAT inside the skill directory.** Skill folders get copied,
synced, and pasted into issues. Only `scripts/mattermost.env.example` belongs
here. Audit with
`grep -rl "<your-token>" ~/.config/opencode/skills/ && echo LEAK`.

**Never point a test at the real `MM_DIR`.** Two ways this goes wrong, both hit
during development of this skill:

- The env file assigns `MM_DIR`, so sourcing it clobbers a scratch-dir
  override. The scripts now re-apply a caller-set `MM_DIR`/`MM_POLL` after the
  auto-load — do not "simplify" that away.
- `unset MM_DIR` does not mean "use the default safely". It means the next
  value comes from the env file, and `--start-over` then wipes your real
  watermark, seen-set, and event log.

Always `MM_DIR=/tmp/scratch` explicitly, and confirm the log line says
`dir=/tmp/scratch`. Hash the real `state.json` before and after if unsure.

**Keep only one copy of these scripts.** An ad-hoc copy in the state directory
plus the skill copy means two implementations with divergent bugs. The skill
owns the scripts; `MM_DIR` holds state only.

**Verify before trusting.** Create a throwaway probe user via the proxied
endpoint, have it post a mention, and confirm capture → triage → reply → mark
before declaring the monitor live. Create real test traffic during a quiet
window, and clean up the probe posts afterwards.

## Debugging

```bash
tail -20 "$MM_DIR/monitor.log"      # lifecycle + python stderr
pgrep -af monitor.sh                # is it alive?
wc -l < "$MM_DIR/events.jsonl"      # captured count; flat = no duplicates
cat  "$MM_DIR/state.json"           # per-channel watermark
```

No new events but messages exist: check the watermark is ahead of them, and
confirm `MM_TOKEN` still works against the **unproxied** base.

## Files

| Path | Purpose |
|---|---|
| `events.jsonl` | append-only capture log |
| `seen.txt` | `<channel_id> <post_id>` API dedupe |
| `state.json` | `{"ts": {channel_id: last_create_at}}` watermark |
| `replied.txt` | inbound post_ids already answered |
| `handled.offset` | line cursor into `events.jsonl` |
| `usernames.txt` | user_id → username cache |
| `stop.flag` | clean-shutdown signal |
| `monitor.log` | lifecycle log + stderr |

These are all inside `$MM_DIR`.

## Scripts

| Script | Purpose |
|---|---|
| `monitor.sh` | background poller → `events.jsonl` |
| `wait_for_events.sh` | blocks in-turn, emits triage candidates |
| `post_reply.sh` | posts, flat or `--root` threaded |
| `mark_replied.sh` | idempotency key |
| `mattermost.env.example` | secret-free template; copy to `~/.config/mattermost/` |