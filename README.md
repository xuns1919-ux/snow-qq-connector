# Snow QQ Connector

Deploy SnowLuma as a OneBot v11 QQ connector and optionally add an authenticated
MCP gateway or an AI/Ombre memory bridge.

## What is included

- A Docker Compose deployment template for the externally supplied SnowLuma runtime image.
- An MCP HTTP gateway for controlled OneBot operations.
- An optional QQ AI bridge with owner-only Ombre MCP memory support.
- Nginx and systemd templates.

## What is not included

This repository does **not** redistribute SnowLuma's runtime image, QQ client,
or any code extracted from a container image. Use a SnowLuma image only if you
have independently verified that its licence and upstream terms allow your use.
No QQ accounts, tokens, chat records, SQLite databases, logs, or personal
identity prompts are included.

## Requirements

- Docker Engine with Docker Compose v2
- A QQ account and a SnowLuma-compatible runtime image you are authorized to use
- Optional: an OpenAI-compatible API for the AI bridge
- Optional: Nginx plus TLS for public MCP access

## Quick start

1. Copy `deploy/.env.example` to `deploy/.env` and adjust ports and image.
2. Start the base connector:

   ```bash
   docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
   ```

3. Complete the runtime's QQ login/setup using its documented interface.
4. Optional MCP gateway: copy `mcp-gateway/.env.example` to `mcp-gateway/.env`,
   set two fresh tokens, then start the `mcp` profile.
5. Optional AI bridge: copy `integrations/qq-ai-bridge/.env.example` to
   `integrations/qq-ai-bridge/.env`, configure it, then start the `ai` profile.

## Configuration notes

- `ONEBOT_TOKEN` protects OneBot HTTP and WebSocket access.
- `MCP_AUTH_TOKEN` protects the MCP endpoint; do not expose it in clients,
  screenshots, or Git history.
- The AI bridge's `OWNER_QQ` enables privileged behavior only for that account.
- Ombre is disabled unless both Ombre variables are set. It is owner-only and
  only persists memory after an explicit owner request.

## Common issues

- **Bridge cannot connect:** ensure the runtime exposes OneBot HTTP on port
  3000 and WebSocket on port 3001, and that its token matches the bridge.
- **MCP returns 401:** set `MCP_AUTH_TOKEN` and send it as a Bearer token.
- **QQ login is lost after restart:** retain the named Docker volumes; do not
  remove them unless you intend to reauthenticate.
- **Public deployment:** bind internal ports to `127.0.0.1` and publish only an
  HTTPS reverse proxy with authentication.

## Disclaimer

This is an independent deployment and integration repository for learning and
legitimate personal use. QQ, Tencent, SnowLuma, OneBot, and Ombre remain the
property of their respective owners. You are responsible for complying with
their licences, service terms, and applicable law. Do not use this project to
evade platform security controls or access accounts without authorization.
