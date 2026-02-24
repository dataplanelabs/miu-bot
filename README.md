<div align="center">
  <img src="assets/logo.svg" alt="miu-bot" width="420">
  <p><strong>Lightweight personal AI assistant framework</strong></p>
  <p>
    <a href="https://pypi.org/project/miu-bot/"><img src="https://img.shields.io/pypi/v/miu-bot" alt="PyPI"></a>
    <img src="https://img.shields.io/badge/python-%E2%89%A53.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

## Overview

**miu-bot** is a lightweight, async-first AI assistant framework built with Python 3.11+. It supports multi-tenant deployments, 10 chat platforms, 13+ LLM providers, durable workflows via Temporal, and extensible tooling via MCP.

**Key highlights:**

- **Multi-tenant** — Workspaces, Postgres backend, per-bot identities/providers/skills
- **Three deployment modes** — Combined (dev), Gateway (routing), Worker (processing)
- **10 chat channels** — Telegram, Discord, WhatsApp, Feishu, DingTalk, Slack, Email, QQ, Zalo, Mochat
- **13+ LLM providers** — OpenRouter, Anthropic, OpenAI, DeepSeek, Groq, Gemini, and more
- **Durable workflows** — Temporal-based orchestration with per-session state
- **MCP support** — Connect external tool servers (stdio + HTTP)
- **3-tier memory** — Active/Reference/Archive with daily/weekly/monthly consolidation
- **Observability** — OpenTelemetry tracing, metrics, and cost tracking

## Install

**From PyPI** (stable)

```bash
pip install miu-bot
```

**With [uv](https://github.com/astral-sh/uv)** (fast)

```bash
uv tool install miu-bot
```

**From source** (latest)

```bash
git clone https://github.com/dataplanelabs/miu-bot.git
cd miu-bot
pip install -e .
```

## Quick Start

> [!TIP]
> Get API keys: [OpenRouter](https://openrouter.ai/keys) (recommended) or any [supported provider](#providers).

**1. Initialize**

```bash
miubot onboard
```

**2. Configure** (`~/.miu-bot/config.json`)

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5-20250929"
    }
  }
}
```

**3. Chat**

```bash
miubot agent
```

## Chat Channels

Connect miu-bot to your favorite chat platform:

| Channel | Transport | Public IP |
|---------|-----------|-----------|
| **Telegram** | Long polling | No |
| **Discord** | WebSocket gateway | No |
| **WhatsApp** | Node.js bridge (WebSocket) | No |
| **Feishu** | WebSocket long connection | No |
| **Mochat** | Socket.IO + msgpack | No |
| **DingTalk** | Stream mode | No |
| **Slack** | Socket mode | No |
| **Email** | IMAP polling + SMTP | No |
| **QQ** | botpy SDK (WebSocket) | No |
| **Zalo** | ZCA-CLI WebSocket bridge | No |

<details>
<summary><b>Telegram</b> (Recommended)</summary>

**1. Create a bot** — Open Telegram, search `@BotFather`, send `/newbot`, copy the token.

**2. Configure**

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**3. Run**

```bash
miubot gateway
```

</details>

<details>
<summary><b>Discord</b></summary>

**1.** Create app at [discord.com/developers](https://discord.com/developers/applications), add bot, enable **MESSAGE CONTENT INTENT**.

**2. Configure**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**3.** Invite bot (OAuth2 > `bot` scope > Send Messages + Read History), then run `miubot gateway`.

</details>

<details>
<summary><b>WhatsApp</b></summary>

Requires **Node.js >= 18**.

```bash
miubot channels login    # Scan QR with WhatsApp
miubot gateway           # Start gateway (separate terminal)
```

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

</details>

<details>
<summary><b>Feishu</b></summary>

WebSocket long connection — no public IP required.

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "allowFrom": []
    }
  }
}
```

</details>

<details>
<summary><b>DingTalk</b></summary>

Stream mode — no public IP required.

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": []
    }
  }
}
```

</details>

<details>
<summary><b>Slack</b></summary>

Socket mode — no public URL required.

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention"
    }
  }
}
```

</details>

<details>
<summary><b>Email</b></summary>

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-bot@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-bot@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-bot@gmail.com",
      "allowFrom": ["you@gmail.com"]
    }
  }
}
```

</details>

<details>
<summary><b>QQ</b></summary>

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "allowFrom": []
    }
  }
}
```

</details>

## Providers

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `openrouter` | LLM (all models, recommended) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM (Claude direct) | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM (GPT direct) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek direct) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + voice transcription (Whisper) | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM (Gemini direct) | [aistudio.google.com](https://aistudio.google.com) |
| `minimax` | LLM (MiniMax direct) | [platform.minimax.io](https://platform.minimax.io) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Moonshot/Kimi) | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM (Zhipu GLM) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `aihubmix` | LLM (API gateway) | [aihubmix.com](https://aihubmix.com) |
| `custom` | Any OpenAI-compatible endpoint | -- |
| `vllm` | Local LLM server | -- |

<details>
<summary><b>Custom / vLLM provider setup</b></summary>

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

</details>

<details>
<summary><b>Adding a new provider (developer guide)</b></summary>

Two steps:

**1.** Add a `ProviderSpec` to `PROVIDERS` in `miu_bot/providers/registry.py`:

```python
ProviderSpec(
    name="myprovider",
    keywords=("myprovider",),
    env_key="MYPROVIDER_API_KEY",
    display_name="My Provider",
    litellm_prefix="myprovider",
    skip_prefixes=("myprovider/",),
)
```

**2.** Add a field to `ProvidersConfig` in `miu_bot/config/schema.py`:

```python
myprovider: ProviderConfig = ProviderConfig()
```

Done. Environment variables, model prefixing, config matching, and `miubot status` all work automatically.

</details>

## MCP (Model Context Protocol)

> [!TIP]
> Config format is compatible with Claude Desktop / Cursor. Copy MCP server configs directly.

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      }
    }
  }
}
```

| Mode | Config | Example |
|------|--------|---------|
| **Stdio** | `command` + `args` | Local process via `npx` / `uvx` |
| **HTTP** | `url` | Remote endpoint |

MCP tools are automatically discovered and registered on startup.

## Deployment

### Single-Process (Development)

```bash
miubot serve --role combined
```

### Multi-Tenant (Production)

```bash
# Gateway — message routing + workspace resolution
miubot serve --role gateway --bots-config /path/to/bots.yaml

# Worker — task processing with optional bot filtering
miubot serve --role worker --bots-config /path/to/bots.yaml --bot-filter bot1,bot2
```

### Multi-Bot Workspace

Define multiple bots with separate identities, providers, and channels in `bots.yaml`:

```yaml
bots:
  assistant:
    soul: /path/to/soul.md
    provider:
      model: anthropic/claude-sonnet-4-5-20250929
      api_key_env: ANTHROPIC_API_KEY
    channels:
      telegram:
        token_env: ASSISTANT_TG_TOKEN
    jobs:
      morning_briefing:
        schedule: "0 8 * * *"
        timezone: "Asia/Saigon"
        prompt: "Summarize top news"
        targets:
          - channel: telegram
            chat_id_env: NEWS_CHAT_ID
```

### Docker

```bash
docker build -t miu-bot .
docker run -v ~/.miu-bot:/root/.miu-bot -p 18790:18790 miu-bot gateway
```

### Kubernetes

Helm chart at `charts/miu-bot/`:

```bash
helm install miu-bot oci://harbor.dataplanelabs.com/dataplanelabs/charts/miu-bot
```

## Security

| Option | Default | Description |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | Sandbox agent tools to workspace directory |
| `channels.*.allowFrom` | `[]` (all) | Whitelist of user IDs per channel |

## CLI Reference

| Command | Description |
|---------|-------------|
| `miubot onboard` | Initialize config & workspace |
| `miubot agent` | Interactive chat mode |
| `miubot agent -m "..."` | Single message |
| `miubot gateway` | Start channel gateway |
| `miubot serve --role [combined\|gateway\|worker]` | Start server in specified role |
| `miubot status` | Show status |
| `miubot channels login` | Link WhatsApp (scan QR) |
| `miubot channels status` | Show channel status |
| `miubot workspace [create\|list\|config\|pause\|delete]` | Manage workspaces |
| `miubot db [migrate\|import-legacy\|status]` | Database operations |

<details>
<summary><b>Scheduled Tasks (Cron)</b></summary>

```bash
miubot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
miubot cron add --name "hourly" --message "Check status" --every 3600
miubot cron list
miubot cron remove <job_id>
```

</details>

## Project Structure

```
miu_bot/
├── agent/          # Core agent logic (loop, context, memory, skills, tools)
├── channels/       # Chat platform integrations + BotManager
├── bus/            # Message bus (async queues + events)
├── providers/      # LLM provider abstraction (registry pattern)
├── config/         # Configuration schema (Pydantic) + bots.yaml loader
├── session/        # Conversation session storage (JSONL)
├── skills/         # Skills system (loader, merger, schema)
├── memory/         # BASB 3-tier memory consolidation
├── dispatch/       # Temporal workflows + schedules
├── gateway/        # FastAPI gateway (routing, admin API)
├── worker/         # Worker (task processing, per-bot context)
├── workspace/      # Multi-tenant workspace management
├── db/             # Storage backend (Postgres)
├── observability/  # OpenTelemetry tracing + metrics
├── cron/           # Scheduled task service
├── heartbeat/      # Proactive wake-up
├── cli/            # CLI commands (Typer)
└── utils/          # Shared helpers
```

## License

[MIT](LICENSE)
