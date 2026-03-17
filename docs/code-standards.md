# Code Standards

## Language & Runtime

- **Python 3.11+** required
- **Async-first**: All I/O operations use `async`/`await`
- **Type hints**: Used throughout via Python typing module + Pydantic models

## Project Structure

```
miu_bot/
├── agent/          # Core agent logic (loop, context, memory, skills, tools)
├── channels/       # Chat platform integrations + BotManager (multi-bot orchestration)
├── bus/            # Message bus (async queues + event dataclasses)
├── providers/      # LLM provider abstraction (registry pattern)
├── config/         # Configuration schema (Pydantic) + bots.yaml loader
├── session/        # Conversation session storage (JSONL)
├── cron/           # Scheduled task service
├── skills/         # Skills system (loader, merger, schema for skill.yaml)
├── heartbeat/      # Proactive wake-up system
├── cli/            # CLI commands (Typer)
├── memory/         # BASB 3-tier memory consolidation
├── observability/  # OpenTelemetry tracing + metrics
├── gateway/        # FastAPI gateway (message routing, admin API, BotManager init)
├── dispatch/       # Temporal workflow orchestration
├── worker/         # Worker mode (task processing, per-bot context)
├── workspace/      # Multi-tenant workspace management
├── db/             # Storage backend (MemoryBackend protocol + implementations)
└── utils/          # Shared helpers
```

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Files | snake_case | `litellm_provider.py` |
| Classes | PascalCase | `AgentLoop`, `ToolRegistry` |
| Functions/methods | snake_case | `_process_message()`, `build_prompt()` |
| Constants | UPPER_SNAKE | `MAX_ITERATIONS`, `PROVIDERS` |
| Config fields | camelCase (JSON) | `apiKey`, `allowFrom`, `mcpServers` |
| Pydantic fields | snake_case (Python) | `api_key`, `allow_from` |

## Design Patterns

### Registry Pattern (Providers)

Single source of truth via `ProviderSpec` dataclass. No if-elif chains. Adding a provider = 2 steps:
1. Add `ProviderSpec` to `PROVIDERS` list in `registry.py`
2. Add field to `ProvidersConfig` in `schema.py`

### Tool Registry Pattern

Tools self-register with name, description, and JSON schema. Dynamic registration/unregistration at runtime. MCP tools registered alongside built-in tools.

### Event-Driven Decoupling

Channels and agent communicate only through `MessageBus`:
- `InboundMessage` — from channel to agent
- `OutboundMessage` — from agent to channel

No direct imports between channels and agent modules.

### Append-Only Sessions

JSONL format. One entry per line. Never modified — only appended. Memory consolidation reads but does not alter session files.

## Code Guidelines

### File Size

Target: under 200 lines per file. Current largest core file is `loop.py` at ~477 lines (acceptable for the main engine).

### Error Handling

- Use try/except with specific exceptions
- Log errors with `loguru.logger`
- Tool execution errors returned as tool results (not raised)
- Shell commands have safety guards for dangerous patterns

### Async Patterns

```python
# Good: async I/O
async def process_message(self, msg: InboundMessage):
    session = await self.session_manager.get(msg.session_key)
    response = await self.provider.chat(messages)

# Good: background tasks
asyncio.create_task(self._run_subagent(prompt, channel, chat_id))
```

### Configuration

- Pydantic models for validation (`config/schema.py`)
- JSON config file with camelCase keys
- Python fields use snake_case (Pydantic alias handles conversion)
- Environment variable fallback for API keys

### Skill Format (skill.yaml)

YAML files with identity fragments, tool rules, and MCP configs:

```yaml
---
description: Research and synthesis skill
identity_fragments:
  - "You are excellent at researching and synthesizing information."
  - "Always verify facts from multiple sources."
tool_rules:
  exec:
    enabled: true
    timeout: 120
  web_search:
    enabled: true
  read_file:
    enabled: true
mcp_servers:
  filesystem:
    url: "http://mcp-filesystem:3000"
  web:
    url: "http://mcp-web:3000"
    headers:
      Authorization: "Bearer token"
---

# Skill instructions in markdown...
# This content teaches the LLM how to use the skill.
```

**Key fields:**
- `identity_fragments` — Bot-specific personality instructions (merged with bot identity)
- `tool_rules` — Per-bot tool enable/disable + per-tool config
- `mcp_servers` — Bot-specific MCP server configs (HTTP transports)
- Body — Markdown instructions for LLM

### Temporal Workflow Pattern

Activities are thin wrappers around core logic (testable without Temporal):

```python
from temporalio import activity

@activity.defn
async def process_message_activity(input: MessageInput) -> MessageOutput:
    # Core logic lives in miu_bot/agent/loop.py — testable without Temporal
    agent = AgentLoop(...)
    return await agent.process(input.message)
```

Workflows orchestrate activities:

```python
from temporalio import workflow

@workflow.defn
class MessageWorkflow:
    @workflow.run
    async def run(self, input: MessageInput) -> None:
        result = await workflow.execute_activity(
            process_message_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5)
        )
        # Query-based streaming state (no extra HTTP endpoints)
```

**Key patterns:**
- Core logic stays in agent/, memory/, providers/ modules (testable in isolation)
- Temporal activities only handle orchestration concerns
- Per-session durable workflows with ContinueAsNew every 500 messages
- Streaming via Temporal queries (workflow.set_query_handler)

### LLM Streaming Pattern

Use `chat_stream()` in LiteLLMProvider for buffered streaming:

```python
# Provider returns async generator
async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncGenerator[str, None]:
    async with litellm.acompletion(..., stream=True) as response:
        buffer = ""
        last_send = time.time()
        async for chunk in response:
            buffer += chunk.get("content", "")
            if time.time() - last_send > debounce_interval:
                yield buffer
                buffer = ""
                last_send = time.time()
        if buffer:
            yield buffer

# Agent or channel handles stream output
async for chunk in provider.chat_stream(messages):
    await message.edit(text=accumulated_text + chunk)
```

**Key patterns:**
- Configurable debounce interval (default 1.5s) to avoid excessive channel edits
- Channels support message editing (Telegram, Discord)
- Tool execution pauses stream, resumes with fresh LLM call

### LLM Retry Pattern

Use tenacity for exponential backoff on transient errors:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from litellm import RateLimitError, APIConnectionError, ServiceUnavailableError

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError, ServiceUnavailableError, Timeout)),
)
async def call_llm(self, messages, **kwargs):
    return await litellm.acompletion(...)
```

**Key patterns:**
- 3 attempts, 2s-30s with jitter
- Retry on transient errors only (rate limit, connection, service unavailable, timeout)
- Fail fast on auth errors (no retries)
- Per-provider configurable retry parameters via config

### Observability Pattern

Instrument code with OpenTelemetry spans and loguru integration:

```python
from miu_bot.observability import setup_observability, get_tracer

# At startup
setup_observability(otlp_exporter_url="http://localhost:4317", sampling_rate=0.1)

# In handler
async def handle_message(self, msg: InboundMessage):
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("handle_message") as span:
        span.set_attribute("workspace_id", msg.workspace_id)
        logger.info(f"Processing message", extra={"trace_id": span.get_span_context().trace_id})

        # Metrics auto-recorded: messages.received, llm.latency_seconds, llm.tokens, cost
        agent = AgentLoop(...)
        await agent.process(msg)
```

**Key patterns:**
- Trace ID and span ID injected into loguru logs automatically
- Custom metrics via metrics.py (messages.received, llm.latency_seconds, tool.latency_seconds, consolidation.cost_usd)
- Cost estimation per model via cost.py
- OTLP exporter for Grafana Alloy, Jaeger, or any OTLP backend
- Configurable sampling rate and export interval

### Memory Consolidation Pattern

Daily/weekly/monthly consolidation via Temporal schedules (not APScheduler):

```python
# In miu_bot/dispatch/schedules.py
await client.create_schedule(
    id=f"consolidate-daily-{workspace_id}",
    schedule=Schedule(
        intervals=[ScheduleIntervalSpec(every=timedelta(days=1))],
        timezone_name=workspace.timezone,  # Per-workspace timezone
        start_at=datetime(..., hour=2),    # 2 AM workspace time
    ),
    action=ScheduleAction(
        start_workflow=StartWorkflowAction(
            workflow=ConsolidateMemoryWorkflow.run,
            args=[workspace_id],
        )
    ),
)
```

**Key patterns:**
- Daily at 2 AM: summarize conversation → MEMORY.md + HISTORY.md
- Weekly at 3 AM (Sunday): elevate stable facts, compress daily notes
- Monthly at 4 AM (1st): generate deep summaries, archive old memories
- Per-workspace timezone support from day one
- Activities delegate to memory/*.py modules (testable in isolation)

### Cron Job Scheduling Pattern

Cron jobs defined in bots.yaml are registered as Temporal schedules in ensure_job_schedules():

```yaml
# In bots.yaml
bots:
  bot1:
    jobs:
      morning_briefing:
        schedule: "0 8 * * *"            # Cron expression
        timezone: "America/New_York"
        enabled: true
        prompt: "Summarize top news"
        targets:
          - channel: telegram
            chat_id_env: CHAT_ID_ENV
          - channel: zalo
            chat_id_env: ZALO_GROUP_ENV
```

```python
# Activity in dispatch/activities.py
@activity.defn
async def run_cron_activity(task_info: dict[str, Any]) -> dict[str, Any]:
    processor = CronTaskProcessor(
        workspace_id=task_info["workspace_id"],
        bot_name=task_info["bot_name"],
        job_name=task_info["job_name"],
        job_config=task_info["job_config"],
    )
    return await processor.execute()
```

**Key patterns:**
- YAML-driven config (no code changes to add jobs)
- Temporal cron schedules trigger CronTaskWorkflow
- CronTaskProcessor loads bot context (identity, provider, skills)
- Multi-target delivery (send results to multiple channels)
- Environment variable resolution for sensitive IDs (chat_id_env)
- Per-job timezone support

### Dependencies

Core dependencies kept minimal (~25 packages including new v0.6.0 additions):
- `temporalio` — Durable workflows (replaces hatchet-sdk)
- `tenacity` — Retry logic with exponential backoff
- `opentelemetry-sdk` + `opentelemetry-exporter-otlp` — Distributed tracing and metrics
- Optional dependencies per channel (e.g., `discord.py` only needed if Discord enabled)

## CLI Commands

### Server Commands

**Serve (Unified Entry Point)**
```bash
miubot serve --role [combined|gateway|worker] [--bots-config /path/to/bots.yaml] [--port PORT] [--bot-filter BOT1,BOT2] [--verbose]
```

- **combined** — Single-process (development, single-tenant, requires Temporal)
- **gateway** — Message router (production multi-tenant, multi-bot orchestration)
  - Loads `bots.yaml` for channel setup and workspace auto-creation
  - Uses BotManager for multi-bot channel routing
  - Temporal client for message dispatch
- **worker** — Task executor (production multi-tenant, per-bot context)
  - Loads `bots.yaml` for per-bot identities, providers, skills
  - Creates per-workspace LLM provider + tools per workflow execution
  - Temporal worker with task queue polling
  - Optional `--bot-filter` for worker isolation (only process specific bot task queues)

**Multi-Bot Config:**
```bash
miubot serve --role gateway --bots-config /etc/miu-bot/bots.yaml
miubot serve --role worker --bots-config /etc/miu-bot/bots.yaml --bot-filter bot1,bot3
```

**Temporal Requirement:**
- Combined mode now requires Temporal (temporal-lite available for local dev)
- Gateway/Worker modes use Temporal for durable, distributed task orchestration
- See [system-architecture.md](./system-architecture.md) for Temporal configuration

### Workspace Commands

```bash
miubot workspace create <name>          # Create new workspace
miubot workspace list                    # List all workspaces
miubot workspace config <name> <key> <value>  # Set workspace config override
miubot workspace pause <name>            # Pause workspace (no new messages)
miubot workspace delete <name>           # Delete workspace (cascades all data)
```

### Database Commands

```bash
miubot db migrate                        # Run Alembic migrations (Postgres)
miubot db import-legacy                  # Migrate single-tenant to multi-tenant
miubot db status                         # Show migration status
```

## Testing

- Test files in `tests/` directory
- Use pytest with async support
- Mock external API calls (LLM, search, channels)
