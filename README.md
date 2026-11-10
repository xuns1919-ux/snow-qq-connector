# Snow QQ Connector

> SnowLuma 部署模板 + MCP 网关 + AI 对话桥接 — 一站式集成方案

---

## 这是什么

本仓库提供一套围绕 [SnowLuma](https://github.com/user/snowluma)（基于 OneBot 协议的 QQ 连接器）的 **部署与扩展集成方案**，包括：

- **Docker 部署模板** — 一键拉起 SnowLuma 容器
- **MCP HTTP 网关** — 将 OneBot 能力以标准 MCP 服务暴露，供 AI 客户端安全调用
- **AI 对话桥接** — 监听 QQ 消息，调用 OpenAI 兼容接口生成回复，内置 SQLite 对话记忆
- **Ombre 记忆集成**（可选）— 为主人 QQ 接入远程长期记忆系统

**本仓库不包含 SnowLuma 核心源码、QQ 客户端二进制或任何上游受保护文件。** 所有代码均为作者自行编写的部署配置与集成逻辑。

---

## 目录结构

```text
snow-qq-connector/
├─ deploy/                      # SnowLuma Docker 部署
│  ├─ docker-compose.yml        # Compose 模板
│  └─ .env.example              # 镜像名、端口、Token 占位
├─ mcp-gateway/                 # MCP HTTP 网关
│  ├─ server.py
│  ├─ requirements.txt
│  ├─ Dockerfile
│  └─ .env.example
├─ integrations/
│  └─ qq-ai-bridge/             # AI 对话桥接
│     ├─ bridge.py
│     ├─ requirements.txt
│     ├─ Dockerfile
│     ├─ .env.example
│     └─ identity.example.md    # AI 人格模板
├─ nginx/
│  └─ snowluma-mcp.conf         # 反向代理配置模板
├─ systemd/
│  └─ snowluma-mcp.service      # systemd 服务模板
├─ .gitignore
└─ LICENSE                      # MIT
```

---

## 环境要求

| 依赖 | 版本 |
|------|------|
| Docker + Docker Compose | v2+ |
| Python | 3.10+ |
| Nginx（可选，公网部署用） | 1.18+ |
| 一个 QQ 账号 | 用于机器人登录 |

---

## 快速开始

部署分为三个独立模块，按需启用。

### 第一步：部署 SnowLuma（基础，必须）

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env，填入要使用的 SnowLuma 镜像名和 OneBot Token

docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
```

启动后访问 `http://localhost:5099` 进入 Web UI，扫码登录 QQ。

**端口说明：**

| 端口 | 用途 |
|------|------|
| 3000 | OneBot HTTP API |
| 3001 | OneBot WebSocket |
| 5099 | SnowLuma Web UI |

> ⚠️ OneBot 端口默认仅绑定 `127.0.0.1`。如需公网访问，请配合 Nginx + HTTPS，**不要**直接暴露裸端口。

### 第二步：启用 MCP 网关（可选）

MCP 网关将 OneBot 能力封装为受 Bearer Token 保护的 HTTP 服务，供 MCP 客户端调用。

```bash
cp mcp-gateway/.env.example mcp-gateway/.env
# 编辑 mcp-gateway/.env，配置 OneBot 地址和 MCP 鉴权 Token

docker compose --env-file deploy/.env --profile mcp -f deploy/docker-compose.yml up -d --build
```

也可在 `mcp-gateway/` 中安装依赖后直接运行 `python server.py`。

**安全说明：**

- MCP 网关默认关闭泛化动作转发，仅白名单内的 OneBot 动作可被调用
- `MCP_AUTH_TOKEN` 必须设置为强随机字符串
- 生产环境建议使用 `nginx/snowluma-mcp.conf` 配置 HTTPS 反向代理

### 第三步：启用 AI 对话桥接（可选）

让 QQ 机器人接入 AI 大模型，实现智能对话。

```bash
cp integrations/qq-ai-bridge/.env.example integrations/qq-ai-bridge/.env
cp integrations/qq-ai-bridge/identity.example.md integrations/qq-ai-bridge/identity.md
# 编辑 integrations/qq-ai-bridge/.env，配置 OneBot、AI 和主人 QQ 信息

docker compose --env-file deploy/.env --profile ai -f deploy/docker-compose.yml up -d --build
```

也可在 `integrations/qq-ai-bridge/` 中安装依赖后直接运行 `python bridge.py`。

**群白名单：**

AI Bridge 默认不处理群消息。若要启用，请在其 `.env` 中设置：

```env
GROUP_CHAT_MODE=whitelist
GROUP_WHITELIST=123456789,987654321
GROUP_REPLY_REQUIRE_AT=true
```

只有白名单中的群会被处理；默认还需要 `@` 机器人。群聊会话与私聊隔离，且不具备主人权限。

**Ombre 记忆集成（可选）：**

```env
OMBRE_MCP_URL=https://your-ombre-endpoint
OMBRE_QQ_TOKEN=your-ombre-token
```

启用后，仅主人 QQ 的对话会读写 Ombre 记忆，普通用户与群聊不会触及该记忆系统。

---

## 配置项速查

| 配置项 | 位置 | 说明 |
|--------|------|------|
| `SNOWLUMA_IMAGE` | `deploy/.env` | SnowLuma Docker 镜像名 |
| `ONEBOT_TOKEN` | `deploy/.env` | OneBot API 鉴权 Token |
| `MCP_AUTH_TOKEN` | `mcp-gateway/.env` | MCP 网关鉴权 Token |
| `SNOWLUMA_ALLOWED_ACTIONS` | `mcp-gateway/.env` | 允许的 OneBot 动作白名单 |
| `AI_BASE_URL` | `qq-ai-bridge/.env` | AI 接口地址（OpenAI 兼容） |
| `AI_API_KEY` | `qq-ai-bridge/.env` | AI 接口密钥 |
| `OWNER_QQ` | `qq-ai-bridge/.env` | 主人 QQ 号 |
| `GROUP_WHITELIST` | `qq-ai-bridge/.env` | 允许响应的群号列表 |
| `OMBRE_MCP_URL` | `qq-ai-bridge/.env` | Ombre 记忆端点（可选） |

---

## 常见问题

**Q: SnowLuma 镜像从哪里获取？**

A: 本仓库不提供也不托管 SnowLuma 镜像。请自行从可信渠道获取，并确认其使用条款。

**Q: 支持哪些 AI 模型？**

A: 任何兼容 OpenAI Chat Completions API 格式的模型均可接入，包括 GPT 系列、开源模型，以及通过兼容层提供该接口的模型。

**Q: 登录状态会丢失吗？**

A: Docker 部署使用 volume 持久化 QQ 登录状态。除非手动删除 volume，否则重启容器不需要重新扫码。

**Q: 可以同时接入多个群吗？**

A: 可以。在 `GROUP_WHITELIST` 填入多个逗号分隔的群号，并设置 `GROUP_CHAT_MODE=whitelist`。

---

## 安全须知

- **绝对不要**将 `.env`、`identity.md`、SQLite 数据库或日志文件提交到 Git
- 公网部署**必须**使用 HTTPS + 强 Bearer Token
- SnowLuma 端口（3000/3001/5099）默认仅绑定本机，不要直接暴露
- 定期更换 Token，尤其在泄露可能发生后

---

## 免责声明

1. 本仓库仅包含作者自行编写的部署配置与集成代码，**不包含**任何第三方核心源码、QQ 客户端组件或受保护的知识产权内容。
2. 使用者需自行确认所使用的 SnowLuma 镜像、QQ/腾讯服务条款及所有上游依赖的许可证合规性。
3. 本项目仅供**学习、研究与个人非商业用途**。作者不对任何因使用本项目产生的法律责任、账号风险或数据损失承担责任。
4. 如有任何版权方认为本仓库内容侵犯其权益，请通过 Issue 联系，将在确认后及时处理。

---

## 许可证

本仓库中的部署配置与集成代码采用 [MIT License](./LICENSE) 发布。

此许可证仅覆盖本仓库内作者原创的代码和配置文件，不延伸至 SnowLuma、QQ 或任何第三方组件。

---

## 致谢

感谢 SnowLuma 原作者及开源社区的贡献。本项目站在前人的肩膀上，致力于让 QQ 生态的 AI 集成更加便捷。