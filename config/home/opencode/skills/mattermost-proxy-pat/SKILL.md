---
name: mattermost-proxy-pat
description: Create a Mattermost user and personal access token via the proxied Mattermost URL to use when interacting with the unproxied Mattermost URL. Use when you need to generate credentials for this instance to authenticate against unproxied-mattermost.int.exe.xyz.
---

# mattermost-proxy-pat

Creates a new Mattermost user (named after the local hostname) via the proxied endpoint and generates a personal access token for that user. The token can then be used to authenticate API calls to the unproxied Mattermost URL.

## Prerequisites

- `hostname` command available to determine username
- `curl` available for API calls
- Access to proxied Mattermost URL: `https://mattermost.int.exe.xyz`
- Access to unproxied Mattermost URL: `https://unproxied-mattermost.int.exe.xyz`

## Workflow

1. Get the hostname to use as username: `hostname | tr -d '\n'`
2. Generate a unique suffix to avoid collisions (e.g., timestamp or random chars)
3. Create the new user via proxied URL (no credentials required on proxied endpoint):
   - `POST https://mattermost.int.exe.xyz/api/v4/users`
   - Body: `{"email":"<hostname>-<suffix>@example.com","username":"<hostname>-<suffix>","password":"<strong-password>"}`
4. Create a personal access token for the new user via proxied URL:
   - `POST https://mattermost.int.exe.xyz/api/v4/users/<user_id>/tokens`
   - Body: `{"description":"<hostname> token"}`
5. Verify the token works against the unproxied URL:
   - `GET https://unproxied-mattermost.int.exe.xyz/api/v4/users/me` with `Authorization: Bearer <token>`
6. Add the user to the team if needed (team `affjybmjkt8ytcxac63awb4i3e` exists in this environment):
   - `POST https://mattermost.int.exe.xyz/api/v4/teams/affjybmjkt8ytcxac63awb4i3e/members`
   - Body: `{"team_id":"affjybmjkt8ytcxac63awb4i3e","user_id":"<user_id>"}`
7. Output the created credentials and example usage
8. **Poll for new messages from unproxied Mattermost** (after obtaining token and user context):
   - Store state (last poll timestamp, username, user_id, token) for continuity across runs
   - Identify relevant channels: team channels, direct message channels involving this user, and any group channels
   - Poll for new posts since last poll time against unproxied URL: `GET https://unproxied-mattermost.int.exe.xyz/api/v4/channels/<channel_id>/posts?since=<epoch_ms>`
   - Assess each new post: is it **directed to this user** (contains `@<username>` mention, or posted in a direct message channel with this user)? Is it **related to work currently being done by this agent** (matches keywords from current working context: hostname, repo name, branch, CWD, task IDs, filenames, commands, or user-specified terms)?
   - Act on assessed messages as appropriate (summarize, extract actionable items, follow instructions) and update last poll timestamp
   - Repeat polling at reasonable intervals if long-running

## Polling Details

- **Track state**: Save last poll timestamp to a temp file (e.g., `/tmp/mattermost-pat-<username>-lastpoll`) to avoid reprocessing old messages
- **Get channels**: `GET https://unproxied-mattermost.int.exe.xyz/api/v4/users/me/channels` (with Bearer token) to discover channels the user belongs to
- **Get channel info for DMs**: For direct channels (`type="D"`), identify the other user(s); for group channels (`type="G"`) note participants
- **Poll for new posts**: Use `since=<milliseconds_since_epoch>` to fetch posts created after last poll. Example: `curl -s -H "Authorization: Bearer <token>" "https://unproxied-mattermost.int.exe.xyz/api/v4/channels/<channel_id>/posts?since=$((LAST_POLL*1000))"`
- **Detect directed messages**: Check if `post.message` contains `@<username>` or if channel is direct message (`channel.type == 'D'`). Also check if post mentions user via `post.mentions`/`post.metadata` if present
- **Detect work-related messages**: Compare against current agent context. Collect signals: `$(hostname)`, basename of `$PWD`, current git repo/branch (`git rev-parse --show-toplevel`, `git branch --show-current`), running task names/IDs, recent user commands, or explicit keywords from active work. Match case-insensitively on substrings
- **Update state**: After processing, set last poll time to `max(last_poll, latest_post_created_at / 1000)`

## Usage

Example commands:

```bash
HOST=$(hostname)
SUFFIX=$(date +%s%N | tail -c 6)
curl -s -X POST "https://mattermost.int.exe.xyz/api/v4/users" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${HOST}-${SUFFIX}@example.com\",\"username\":\"${HOST}-${SUFFIX}\",\"password\":\"ChangeMe123!\"}"
```

```bash
curl -s -X POST "https://mattermost.int.exe.xyz/api/v4/users/<user_id>/tokens" \
  -H "Content-Type: application/json" \
  -d "{\"description\":\"${HOST} token\"}"
```

```bash
curl -s -X POST "https://unproxied-mattermost.int.exe.xyz/api/v4/posts" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"channel_id\":\"<channel_id>\",\"message\":\"hello\"}"
```

Example polling (stateful):

```bash
USERNAME="<hostname>-<suffix>"
TOKEN="<token>"
LAST_POLL_FILE="/tmp/mattermost-pat-${USERNAME}-lastpoll"
LAST_POLL=$(cat "$LAST_POLL_FILE" 2>/dev/null || echo 0)
# Get channels
curl -s -H "Authorization: Bearer ${TOKEN}" "https://unproxied-mattermost.int.exe.xyz/api/v4/users/me/channels" > /tmp/channels.json
# Poll each channel since LAST_POLL
for cid in $(jq -r '.[].id' /tmp/channels.json); do
  curl -s -H "Authorization: Bearer ${TOKEN}" "https://unproxied-mattermost.int.exe.xyz/api/v4/channels/${cid}/posts?since=$((LAST_POLL*1000))"
done
# Update last poll
date +%s > "$LAST_POLL_FILE"
```

## Notes

- The proxied URL (`mattermost.int.exe.xyz`) automatically sets auth context; credentials are not required when calling it.
- The unproxied URL (`unproxied-mattermost.int.exe.xyz`) requires proper authentication via bearer token or session.
- Always add the new user to the relevant team before posting in team channels.
- Use a strong random password when creating the user.
- After registering the new user and obtaining the PAT, poll the unproxied Mattermost immediately to check for messages directed to this user and messages relevant to current work being done by this agent. Use a persisted last-poll timestamp to avoid reprocessing.
