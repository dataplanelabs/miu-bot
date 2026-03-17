# miu-bot Documentation

A fork of [HKUDS/nanobot](https://github.com/HKUDS/nanobot) with Postgres backend, Temporal workflows, multi-tenant architecture, Kubernetes deployment, and OpenTelemetry observability.

## Documentation Index

- **[Codebase Summary](./codebase-summary.md)** — Project overview, module structure, design patterns, technology stack, and quick start guide
- **[System Architecture](./system-architecture.md)** — High-level architecture diagrams, deployment modes (Combined/Gateway/Worker), data flows, multi-tenant design, and CI/CD pipeline
- **[Code Standards](./code-standards.md)** — Coding conventions, design patterns, testing strategies, security protocols, and error handling guidelines
- **[Development Roadmap](./development-roadmap.md)** — Completed features, planned features, and project timeline
- **[Project Changelog](./project-changelog.md)** — Release history, breaking changes, and major feature additions
- **[Data Model](./data-model.md)** — Entity-relationship diagrams, table schemas, constraints, and data flow documentation
- **[Setup Telegram Guide](./setup-telegram-guide.md)** — Instructions for deploying as a Telegram bot
- **[Setup Zalo Guide](./setup-zalo-guide.md)** — Instructions for connecting via Zalo WebSocket bridge

## Key Features

- **Multi-tenant workspace architecture** with Gateway/Worker separation for scaling
- **PostgreSQL backend** for durable, queryable storage
- **Temporal workflows** for distributed, deterministic orchestration
- **10 chat channel integrations** (Telegram, Discord, WhatsApp, Feishu, DingTalk, Slack, Zalo, Email, QQ, Mochat)
- **13+ LLM providers** (Anthropic, OpenAI, DeepSeek, Groq, Gemini, and more)
- **7 tool categories** (shell, filesystem, web search/fetch, messaging, spawning, cron, MCP)
- **BASB 3-tier memory system** (Active/Reference/Archive with daily/weekly/monthly consolidation)
- **OpenTelemetry observability** (distributed tracing, metrics, cost analytics)
- **Kubernetes-native** with Helm charts and horizontal pod autoscaling

## Quick Links

- **GitHub Repository**: https://github.com/dataplanelabs/miu-bot
- **PyPI Package**: https://pypi.org/project/miu-bot
- **Original Project**: https://github.com/HKUDS/nanobot
