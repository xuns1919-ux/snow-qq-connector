# Optional QQ AI Bridge

This module connects a OneBot v11-compatible SnowLuma endpoint to an
OpenAI-compatible chat-completions API. It stores its local conversational
state in SQLite inside the Docker volume.

Copy `.env.example` to `.env`, fill in the bot and owner QQ numbers, the
OneBot token, and your AI-provider settings. Copy `identity.example.md` to the
configured `IDENTITY_FILE` path if you want a custom owner prompt.

Start it with:

```bash
docker compose --env-file deploy/.env --profile ai -f deploy/docker-compose.yml up -d --build
```

## Optional Ombre memory

When both `OMBRE_MCP_URL` and `OMBRE_QQ_TOKEN` are set, the bridge enables
owner-only remote memory recall. It only writes remote memory for explicit
owner requests; ordinary QQ users never receive or write that memory. Leave
these settings empty to keep Ombre entirely disabled.

## Group whitelist

Group replies are off by default. To enable them, set `GROUP_CHAT_MODE=whitelist` and place the permitted QQ group IDs in `GROUP_WHITELIST` as a comma-separated list. The bridge ignores every other group.

Allowed groups require an explicit `@` mention by default (`GROUP_REPLY_REQUIRE_AT=true`). Set it to `false` only if the bot should answer all messages in those allowed groups. Group conversations use a separate per-group, per-user local history and never inherit owner privileges or private-chat history.

Never commit `.env`, `identity.md`, or `memory.sqlite3`.
