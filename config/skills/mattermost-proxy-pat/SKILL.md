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

## Notes

- The proxied URL (`mattermost.int.exe.xyz`) automatically sets auth context; credentials are not required when calling it.
- The unproxied URL (`unproxied-mattermost.int.exe.xyz`) requires proper authentication via bearer token or session.
- Always add the new user to the relevant team before posting in team channels.
- Use a strong random password when creating the user.
