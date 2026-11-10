# MCP Gateway

An HTTP MCP gateway for a SnowLuma OneBot v11 endpoint. It uses bearer-token
authentication and an explicit action allowlist by default.

Copy `.env.example` to `.env`, set fresh tokens, then run it with the `mcp`
Compose profile:

```bash
docker compose --env-file deploy/.env --profile mcp -f deploy/docker-compose.yml up -d --build
```

The default endpoint is `http://127.0.0.1:8766/mcp`. Put it behind TLS and a
reverse proxy before exposing it to the internet.
