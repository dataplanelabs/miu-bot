<div align="center">
  <img src="assets/logo.svg" alt="miu-bot" width="420">
  <p><strong>Durable, scalable AI assistant framework</strong></p>
  <p>
    <a href="https://pypi.org/project/miu-bot/"><img src="https://img.shields.io/pypi/v/miu-bot" alt="PyPI"></a>
    <img src="https://img.shields.io/badge/python-%E2%89%A53.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

> **Fork of [HKUDS/nanobot](https://github.com/HKUDS/nanobot)** — rebuilt for durability and scalability.

## Why miu-bot?

[nanobot](https://github.com/HKUDS/nanobot) is a great lightweight AI assistant, but it uses JSON file storage and lacks durable workflow orchestration — which breaks down at scale.

**miu-bot** extends nanobot with:

- **Postgres backend** — Replaces JSON files with a proper database for messages, sessions, memory, and usage tracking
- **Temporal workflows** — Deterministic, durable workflow orchestration with retry, timeout, and per-session state
- **Multi-tenant architecture** — Gateway/Worker separation, workspace isolation, per-bot identities
- **Production-ready** — Kubernetes Helm chart, OpenTelemetry observability, HPA autoscaling

It's designed to be a lighter, easier-to-manage alternative to heavier frameworks like [OpenClaw](https://github.com/openclaw).

## Features

| Category | Details |
|----------|---------|
| **Chat channels** | Telegram, Discord, WhatsApp, Feishu, DingTalk, Slack, Email, QQ, Zalo, Mochat |
| **LLM providers** | 13+ via LiteLLM — OpenRouter, Anthropic, OpenAI, DeepSeek, Groq, Gemini, and more |
| **Storage** | Postgres (pgvector for embeddings) or JSON files (dev) |
| **Workflows** | Temporal-based durable orchestration |
| **Tools** | MCP support (stdio + HTTP), compatible with Claude Desktop / Cursor configs |
| **Memory** | 3-tier consolidation (Active → Reference → Archive) |
| **Observability** | OpenTelemetry tracing, metrics, cost tracking |
| **Deployment** | Combined (dev), Gateway + Worker (prod), Docker, Kubernetes |

## Install

```bash
# From PyPI
pip install miu-bot

# With optional backends
pip install miu-bot[postgres,temporal,otel]

# From source
git clone https://github.com/dataplanelabs/miu-bot.git
cd miu-bot && pip install -e ".[postgres,temporal]"
```

## Quick Start

```bash
# 1. Initialize config
miubot onboard

# 2. Set your API key in ~/.miu-bot/config.json
# 3. Chat
miubot agent
```

See the [setup guides](docs/) for channel-specific configuration (Telegram, Discord, etc).

## Architecture

```
┌──────────────────────────────────────────────┐
│                Chat Channels                 │
│ Telegram · Discord · WhatsApp · Slack · ...  │
└───────────────────────┬──────────────────────┘
                        │
                        ▼
                 ┌────────────┐
                 │  Gateway   │
                 │  (FastAPI) │
                 └──────┬─────┘
                        │
                        ▼
                 ┌────────────┐
                 │  Temporal  │
                 │   Server   │
                 └──────┬─────┘
                        │
                        ▼
                 ┌────────────┐
                 │  Workers   │
                 │(N replicas)│
                 └──────┬─────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
 ┌────────────┐  ┌────────────┐  ┌────────────┐
 │  Postgres  │  │  LLM APIs  │  │ MCP Tools  │
 │ (pgvector) │  │  (LiteLLM) │  │(stdio/http)│
 └────────────┘  └────────────┘  └────────────┘
```

## Deployment

```bash
# Development (single process)
miubot serve --role combined

# Production (separate gateway + workers)
miubot serve --role gateway --bots-config bots.yaml
miubot serve --role worker --bots-config bots.yaml

# Docker
docker build -t miu-bot .
docker run -v ~/.miu-bot:/root/.miu-bot -p 18790:18790 miu-bot gateway

# Kubernetes (Helm)
helm install miu-bot charts/miu-bot/
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `miubot onboard` | Initialize config & workspace |
| `miubot agent` | Interactive chat mode |
| `miubot gateway` | Start channel gateway |
| `miubot serve --role <role>` | Start in combined/gateway/worker mode |
| `miubot status` | Show status |
| `miubot workspace <cmd>` | Manage workspaces |
| `miubot db migrate` | Run database migrations |
| `miubot cron <cmd>` | Manage scheduled tasks |

## Project Structure

```
miu_bot/
├── agent/          # Core agent logic (loop, context, memory, skills, tools)
├── channels/       # Chat platform integrations (10 platforms)
├── bus/            # Async message bus
├── providers/      # LLM provider registry (LiteLLM)
├── config/         # Pydantic config schema + bots.yaml loader
├── dispatch/       # Temporal workflows + schedules
├── gateway/        # FastAPI gateway (routing, admin API)
├── worker/         # Worker (task processing, per-bot context)
├── workspace/      # Multi-tenant workspace management
├── db/             # Postgres backend + migrations (Alembic)
├── memory/         # 3-tier memory consolidation
├── observability/  # OpenTelemetry tracing + metrics
├── skills/         # Extensible skills system
├── session/        # Conversation session storage
├── cron/           # Scheduled tasks
└── cli/            # CLI (Typer)
bridge/             # Node.js WhatsApp bridge
charts/             # Kubernetes Helm chart
```

## Acknowledgments

This project is a fork of [HKUDS/nanobot](https://github.com/HKUDS/nanobot). Thanks to the nanobot team for the excellent foundation.

## License

[MIT](LICENSE)
