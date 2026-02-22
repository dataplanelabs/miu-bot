"""CLI commands for miu_bot."""

import asyncio
import os
import signal
from pathlib import Path
import select
import sys
from typing import Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from miu_bot import __version__, __logo__

app = typer.Typer(
    name="miubot",
    help=f"{__logo__} miubot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios
        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    history_file = Path.home() / ".miu-bot" / "history" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,   # Enter submits (single line mode)
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} miu_bot[/cyan]")
    console.print(body)
    console.print()


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc



def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} miubot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """miubot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize miu_bot configuration and workspace."""
    from miu_bot.config.loader import get_config_path, load_config, save_config
    from miu_bot.config.schema import Config
    from miu_bot.utils.helpers import get_workspace_path
    
    config_path = get_config_path()
    
    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print("  [bold]N[/bold] = refresh config, keeping existing values and adding new fields")
        if typer.confirm("Overwrite?"):
            config = Config()
            save_config(config)
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = load_config()
            save_config(config)
            console.print(f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)")
    else:
        save_config(Config())
        console.print(f"[green]✓[/green] Created config at {config_path}")
    
    # Create workspace
    workspace = get_workspace_path()
    
    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace}")
    
    # Create default bootstrap files
    _create_workspace_templates(workspace)
    
    console.print(f"\n{__logo__} miubot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.miu-bot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]miubot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/dataplanelabs/miu-bot#-chat-apps[/dim]")




def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in memory/MEMORY.md; past events are logged in memory/HISTORY.md
""",
        "SOUL.md": """# Soul

I am miubot, a lightweight AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }
    
    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")
    
    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")
    
    history_file = memory_dir / "HISTORY.md"
    if not history_file.exists():
        history_file.write_text("")
        console.print("  [dim]Created memory/HISTORY.md[/dim]")

    # Create skills directory for custom user skills
    skills_dir = workspace / "skills"
    skills_dir.mkdir(exist_ok=True)


def _make_provider(config):
    """Create LiteLLMProvider from config. Exits if no API key found."""
    from miu_bot.providers.litellm_provider import LiteLLMProvider
    p = config.get_provider()
    model = config.agents.defaults.model
    if not (p and p.api_key) and not model.startswith("bedrock/"):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.miu-bot/config.json under providers section")
        raise typer.Exit(1)
    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=config.get_provider_name(),
    )


# ============================================================================
# Gateway / Server
# ============================================================================


def _setup_logging(verbose: bool):
    """Configure logging for serve modes."""
    from loguru import logger
    import sys as _sys
    logger.remove()
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
        logger.add(_sys.stderr, level="DEBUG", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>")
    else:
        logger.add(_sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <level>{message}</level>")


def _create_backend(config):
    """Create the appropriate MemoryBackend from config."""
    if config.backend.type == "postgres" and config.database.url:
        # Postgres backend requires pool — handled in async context
        return None  # Caller must create pool + backend in async
    from miu_bot.db.file_backend import FileBackend
    return FileBackend()


async def _ensure_workspaces(
    bots: dict[str, Any],
    workspace_service: Any,
) -> dict[str, str]:
    """Ensure workspaces exist for all bots. Returns {bot_name: workspace_id}."""
    from miu_bot.skills.loader import discover_local_skills, resolve_bot_skills
    from miu_bot.skills.schema import BotSkillRef
    from loguru import logger

    workspace_map: dict[str, str] = {}
    for bot_name, bot_cfg in bots.items():
        config_overrides: dict[str, Any] = {}

        # Provider config — store *_env references, NOT resolved secrets
        if bot_cfg.provider.model:
            config_overrides["provider"] = bot_cfg.provider.model_dump()

        # Tools/MCP config
        if bot_cfg.tools.mcp_servers:
            mcp_dict = {}
            for srv_name, srv_cfg in bot_cfg.tools.mcp_servers.items():
                mcp_dict[srv_name] = srv_cfg.model_dump(exclude_defaults=True)
            config_overrides["tools"] = {"mcp_servers": mcp_dict}

        # Skills (resolve from skill refs if present)
        if bot_cfg.skills:
            skill_refs = [BotSkillRef.model_validate(s) for s in bot_cfg.skills]
            resolved_skills = resolve_bot_skills(skill_refs, {}, {})
            if resolved_skills:
                config_overrides["skills"] = [
                    s.model_dump(exclude_defaults=True) for s in resolved_skills
                ]

        # Channel allowFrom (for reference)
        channels_cfg = {}
        for ch_type, ch_cfg in bot_cfg.channels.items():
            channels_cfg[ch_type] = {"allowFrom": ch_cfg.allow_from}
        if channels_cfg:
            config_overrides["channels"] = channels_cfg

        ws = await workspace_service.get_or_create(
            name=bot_name,
            identity_text=bot_cfg.identity,
            config_overrides=config_overrides,
        )
        workspace_map[bot_name] = ws.id
        logger.info(f"Workspace '{bot_name}' → {ws.id[:8]}")

    return workspace_map


def _serve_combined(port: int, verbose: bool):
    """Run in combined mode: gateway + agent loop (no Hatchet)."""
    from miu_bot.config.loader import load_config, get_data_dir
    from miu_bot.bus.queue import MessageBus
    from miu_bot.agent.loop import AgentLoop
    from miu_bot.channels.manager import ChannelManager
    from miu_bot.session.manager import SessionManager
    from miu_bot.cron.service import CronService
    from miu_bot.cron.types import CronJob
    from miu_bot.heartbeat.service import HeartbeatService
    from loguru import logger

    _setup_logging(verbose)
    console.print(f"{__logo__} Starting miubot serve (combined) on port {port}...")

    config = load_config()
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)
    backend = _create_backend(config)

    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    agent = AgentLoop(
        bus=bus, provider=provider, workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec, cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager, mcp_servers=config.tools.mcp_servers,
        claude_code_config=config.tools.claude_code,
        backend=backend,
    )

    async def on_cron_job(job: CronJob) -> str | None:
        response = await agent.process_direct(
            job.payload.message, session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli", chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
            from miu_bot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli", chat_id=job.payload.to, content=response or "",
            ))
        return response
    cron.on_job = on_cron_job

    async def on_heartbeat(prompt: str) -> str:
        return await agent.process_direct(prompt, session_key="heartbeat")

    heartbeat = HeartbeatService(
        workspace=config.workspace_path, on_heartbeat=on_heartbeat,
        interval_s=30 * 60, enabled=True,
    )

    channels = ChannelManager(config, bus)
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels: {', '.join(channels.enabled_channels)}")

    async def run():
        import uvicorn
        from miu_bot.gateway.app import create_app

        app = create_app(backend, bus)
        uvi_config = uvicorn.Config(app, host=config.gateway.host, port=port, log_level="warning")
        server = uvicorn.Server(uvi_config)

        try:
            await cron.start()
            await heartbeat.start()
            results = await asyncio.gather(
                agent.run(), channels.start_all(), server.serve(),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    logger.error(f"Task failed: {r}")
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
            server.should_exit = True

    asyncio.run(run())


def _serve_gateway(port: int, verbose: bool, bots_config_path: Path | None = None):
    """Run in gateway mode: channels + Hatchet event dispatch (no AgentLoop)."""
    from miu_bot.config.loader import load_config
    from miu_bot.config.bots import load_bots
    from miu_bot.bus.queue import MessageBus
    from miu_bot.channels.bot_manager import BotManager
    from miu_bot.workspace.service import WorkspaceService
    from loguru import logger

    _setup_logging(verbose)
    console.print(f"{__logo__} Starting miubot serve (gateway) on port {port}...")

    config = load_config()
    bus = MessageBus()
    bots = load_bots(bots_config_path)

    if not bots:
        console.print("[yellow]No bots configured — running empty gateway[/yellow]")

    async def run():
        import uvicorn
        from miu_bot.gateway.app import create_app

        # Setup backend
        pool = None
        backend = _create_backend(config)
        if not backend:
            from miu_bot.db.pool import create_pool, close_pool
            from miu_bot.db.postgres import PostgresBackend
            pool = await create_pool(
                config.database.url,
                config.database.min_pool_size,
                config.database.max_pool_size,
            )
            backend = PostgresBackend(pool)

        # Ensure workspaces exist for all bots
        workspace_service = WorkspaceService(backend)
        workspace_map: dict[str, str] = {}
        if bots:
            workspace_map = await _ensure_workspaces(bots, workspace_service)
            console.print(f"[green]✓[/green] {len(workspace_map)} workspace(s) synced")

        # Create bot manager with channel instances
        bot_mgr = BotManager(bots, bus, global_channels=config.channels)
        if bot_mgr.enabled_channels:
            console.print(f"[green]✓[/green] Channels: {', '.join(bot_mgr.enabled_channels)}")

        app = create_app(backend, bus)
        uvi_config = uvicorn.Config(
            app, host=config.gateway.host, port=port, log_level="warning"
        )
        server = uvicorn.Server(uvi_config)

        async def dispatch_to_hatchet():
            """Consume inbound messages and dispatch to Hatchet."""
            if not config.hatchet.enabled:
                logger.warning("Hatchet not enabled — gateway dispatch inactive")
                return
            from miu_bot.worker.client import create_hatchet_client
            hatchet = create_hatchet_client(config.hatchet)

            while True:
                try:
                    msg = await asyncio.wait_for(
                        bus.consume_inbound(), timeout=1.0
                    )

                    # Resolve workspace from bot_name (direct lookup)
                    if msg.bot_name and msg.bot_name in workspace_map:
                        workspace_id = workspace_map[msg.bot_name]
                    else:
                        # Fallback: old resolver for backward compat
                        from miu_bot.workspace.resolver import WorkspaceResolver
                        resolver = WorkspaceResolver(backend)
                        workspace_id = await resolver.resolve(
                            msg.channel, msg.chat_id
                        )
                    if not workspace_id:
                        logger.warning(
                            f"No workspace for bot={msg.bot_name} "
                            f"channel={msg.channel} chat={msg.chat_id}"
                        )
                        continue

                    session = await backend.get_or_create_session(
                        workspace_id, msg.channel, msg.chat_id
                    )

                    event_payload = {
                        "workspace_id": workspace_id,
                        "session_id": session.id,
                        "channel": msg.channel,
                        "chat_id": msg.chat_id,
                        "sender_id": msg.sender_id,
                        "content": msg.content,
                        "metadata": msg.metadata,
                        "bot_name": msg.bot_name,
                    }
                    logger.info(
                        f"Dispatching to Hatchet: bot={msg.bot_name} "
                        f"ws={workspace_id[:8]} session={session.id[:8]}"
                    )
                    hatchet.event.push("message:received", event_payload)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Hatchet dispatch failed: {e}", exc_info=True)

        try:
            await asyncio.gather(
                bot_mgr.start_all(),
                server.serve(),
                dispatch_to_hatchet(),
                return_exceptions=True,
            )
        finally:
            await bot_mgr.stop_all()
            server.should_exit = True
            if pool:
                from miu_bot.db.pool import close_pool
                await close_pool(pool)

    asyncio.run(run())


def _serve_worker(verbose: bool):
    """Run in worker mode: Hatchet workflow processing (no HTTP server)."""
    from datetime import timedelta
    from miu_bot.config.loader import load_config
    from miu_bot.worker.client import create_hatchet_client
    from loguru import logger

    _setup_logging(verbose)
    console.print(f"{__logo__} Starting miubot serve (worker)...")

    config = load_config()
    if not config.hatchet.enabled and not config.hatchet.token:
        console.print("[red]Worker mode requires Hatchet configuration[/red]")
        raise typer.Exit(1)

    hatchet = create_hatchet_client(config.hatchet)

    # Lifespan: async resource setup/cleanup (DB pool, provider)
    async def lifespan():
        from miu_bot.db.pool import create_pool, close_pool
        from miu_bot.db.postgres import PostgresBackend

        pool = await create_pool(
            config.database.url,
            config.database.min_pool_size,
            config.database.max_pool_size,
        )

        # Fallback provider config from global config (for bots without overrides)
        p = config.get_provider()
        yield {
            "backend": PostgresBackend(pool),
            "gateway_url": config.hatchet.gateway_url,
            "fallback_model": config.agents.defaults.model,
            "fallback_api_key": p.api_key if p else "",
            "fallback_api_base": config.get_api_base(),
            "max_tokens": config.agents.defaults.max_tokens,
            "temperature": config.agents.defaults.temperature,
            "max_iterations": config.agents.defaults.max_tool_iterations,
        }
        await close_pool(pool)
        logger.info("Connection pool closed")

    # Define workflows
    from hatchet_sdk.runnables.types import ConcurrencyExpression, ConcurrencyLimitStrategy

    process_msg_wf = hatchet.workflow(
        name="process-message",
        on_events=["message:received"],
        concurrency=ConcurrencyExpression(
            expression="input.session_id",
            max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
        ),
    )

    @process_msg_wf.task(execution_timeout=timedelta(minutes=5))
    async def process_message(input, context):
        from miu_bot.worker.workflows.process_message import ProcessMessageWorkflow
        deps = context.lifespan
        input_data = input.model_dump()
        logger.info(f"Processing message: workspace={input_data.get('workspace_id', '?')[:8]} "
                     f"bot={input_data.get('bot_name', '?')} channel={input_data.get('channel', '?')}")
        try:
            wf = ProcessMessageWorkflow(
                backend=deps["backend"],
                gateway_url=deps["gateway_url"],
                fallback_model=deps["fallback_model"],
                fallback_api_key=deps["fallback_api_key"],
                fallback_api_base=deps["fallback_api_base"],
                max_tokens=deps["max_tokens"],
                temperature=deps["temperature"],
                max_iterations=deps["max_iterations"],
            )
            result = await wf.process(input_data)
            logger.info(f"Message processed: status={result.get('status', '?')}")
            return result
        except Exception as e:
            logger.error(f"process_message failed: {type(e).__name__}: {e}", exc_info=True)
            raise

    # Start worker (blocking — creates own event loop)
    worker = hatchet.worker(
        "miubot-worker",
        workflows=[process_msg_wf],
        lifespan=lifespan,
    )
    logger.info("Starting Hatchet worker with workflows: [process-message]")
    worker.start()


@app.command()
def serve(
    role: str = typer.Option("combined", "--role", "-r", help="Role: combined | gateway | worker"),
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    bots_config: Path = typer.Option(None, "--bots-config", help="Path to bots.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the miubot server (combined, gateway, or worker mode)."""
    if role == "worker":
        _serve_worker(verbose)
    elif role == "gateway":
        _serve_gateway(port, verbose, bots_config_path=bots_config)
    else:
        _serve_combined(port, verbose)


@app.command(hidden=True)
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the miubot gateway (deprecated: use 'serve' instead)."""
    from miu_bot.config.loader import load_config, get_data_dir
    from miu_bot.bus.queue import MessageBus
    from miu_bot.agent.loop import AgentLoop
    from miu_bot.channels.manager import ChannelManager
    from miu_bot.session.manager import SessionManager
    from miu_bot.cron.service import CronService
    from miu_bot.cron.types import CronJob
    from miu_bot.heartbeat.service import HeartbeatService
    
    from loguru import logger
    import sys

    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
        # Configure loguru for verbose output
        logger.remove()
        logger.add(sys.stderr, level="DEBUG", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>")
    else:
        logger.remove()
        logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <level>{message}</level>")
    
    console.print(f"{__logo__} Starting miubot gateway on port {port}...")
    
    config = load_config()
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)
    
    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    
    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        claude_code_config=config.tools.claude_code,
    )
    
    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
            from miu_bot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response or ""
            ))
        return response
    cron.on_job = on_cron_job
    
    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")
    
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True
    )
    
    # Create channel manager
    channels = ChannelManager(config, bus)
    
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    
    console.print(f"[green]✓[/green] Heartbeat: every 30m")
    
    async def run():
        try:
            await cron.start()
            await heartbeat.start()
            # Run agent and channels independently — a channel crash shouldn't kill the agent loop
            results = await asyncio.gather(
                agent.run(),
                channels.start_all(),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    logger.error(f"Task failed: {r}")
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
    
    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show miubot runtime logs during chat"),
):
    """Interact with the agent directly."""
    from miu_bot.config.loader import load_config
    from miu_bot.bus.queue import MessageBus
    from miu_bot.agent.loop import AgentLoop
    from loguru import logger
    
    config = load_config()
    
    bus = MessageBus()
    provider = _make_provider(config)

    if logs:
        logger.enable("miu_bot")
    else:
        logger.disable("miu_bot")
    
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        claude_code_config=config.tools.claude_code,
    )
    
    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext
            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]miubot is thinking...[/dim]", spinner="dots")

    if message:
        # Single message mode
        async def run_once():
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id)
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()
        
        asyncio.run(run_once())
    else:
        # Interactive mode
        _init_prompt_session()
        console.print(f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n")

        def _exit_on_sigint(signum, frame):
            _restore_terminal()
            console.print("\nGoodbye!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)
        
        async def run_interactive():
            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break
                        
                        with _thinking_ctx():
                            response = await agent_loop.process_direct(user_input, session_id)
                        _print_agent_response(response, render_markdown=markdown)
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                await agent_loop.close_mcp()
        
        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from miu_bot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )

    dc = config.channels.discord
    table.add_row(
        "Discord",
        "✓" if dc.enabled else "✗",
        dc.gateway_url
    )

    # Feishu
    fs = config.channels.feishu
    fs_config = f"app_id: {fs.app_id[:10]}..." if fs.app_id else "[dim]not configured[/dim]"
    table.add_row(
        "Feishu",
        "✓" if fs.enabled else "✗",
        fs_config
    )

    # Mochat
    mc = config.channels.mochat
    mc_base = mc.base_url or "[dim]not configured[/dim]"
    table.add_row(
        "Mochat",
        "✓" if mc.enabled else "✗",
        mc_base
    )
    
    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        tg_config
    )

    # Slack
    slack = config.channels.slack
    slack_config = "socket" if slack.app_token and slack.bot_token else "[dim]not configured[/dim]"
    table.add_row(
        "Slack",
        "✓" if slack.enabled else "✗",
        slack_config
    )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess
    
    # User's bridge location
    user_bridge = Path.home() / ".miu-bot" / "bridge"
    
    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge
    
    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)
    
    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # miu_bot/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)
    
    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge
    
    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall miu-bot")
        raise typer.Exit(1)
    
    console.print(f"{__logo__} Setting up bridge...")
    
    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))
    
    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)
    
    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess
    from miu_bot.config.loader import load_config
    
    config = load_config()
    bridge_dir = _get_bridge_dir()
    
    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")
    
    env = {**os.environ}
    if config.channels.whatsapp.bridge_token:
        env["BRIDGE_TOKEN"] = config.channels.whatsapp.bridge_token
    
    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from miu_bot.config.loader import get_data_dir
    from miu_bot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    jobs = service.list_jobs(include_disabled=all)
    
    if not jobs:
        console.print("No scheduled jobs.")
        return
    
    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")
    
    import time
    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"
        
        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000))
            next_run = next_time
        
        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"
        
        table.add_row(job.id, job.name, sched, status, next_run)
    
    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
):
    """Add a scheduled job."""
    from miu_bot.config.loader import get_data_dir
    from miu_bot.cron.service import CronService
    from miu_bot.cron.types import CronSchedule
    
    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime
        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )
    
    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from miu_bot.config.loader import get_data_dir
    from miu_bot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from miu_bot.config.loader import get_data_dir
    from miu_bot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from miu_bot.config.loader import get_data_dir
    from miu_bot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    async def run():
        return await service.run_job(job_id, force=force)
    
    if asyncio.run(run()):
        console.print(f"[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Workspace Commands
# ============================================================================

workspace_app = typer.Typer(help="Manage workspaces")
app.add_typer(workspace_app, name="workspace")


def _make_backend(config):
    """Create the appropriate backend from config."""
    if config.backend.type == "postgres" and config.database.url:
        raise typer.Exit("Postgres backend requires async context. Use 'miubot serve' instead.")
    from miu_bot.db.file_backend import FileBackend
    return FileBackend()


@workspace_app.command("create")
def workspace_create(
    name: str = typer.Argument(..., help="Workspace name"),
    identity: Path = typer.Option(None, "--identity", "-i", help="Path to identity.md file"),
):
    """Create a new workspace."""
    from miu_bot.config.loader import load_config
    from miu_bot.workspace.service import WorkspaceService
    from miu_bot.db.file_backend import FileBackend

    config = load_config()
    backend = FileBackend()

    async def _run():
        svc = WorkspaceService(backend)
        ws = await svc.create(name, identity_path=identity)
        console.print(f"[green]✓[/green] Created workspace '{ws.name}' ({ws.id})")

    import asyncio
    asyncio.run(_run())


@workspace_app.command("list")
def workspace_list():
    """List all workspaces."""
    from miu_bot.config.loader import load_config
    from miu_bot.workspace.service import WorkspaceService
    from miu_bot.db.file_backend import FileBackend

    backend = FileBackend()

    async def _run():
        svc = WorkspaceService(backend)
        workspaces = await svc.list()
        if not workspaces:
            console.print("No workspaces found.")
            return
        table = Table(title="Workspaces")
        table.add_column("Name", style="cyan")
        table.add_column("Status")
        table.add_column("ID", style="dim")
        table.add_column("Created")
        for ws in workspaces:
            status_style = "green" if ws.status == "active" else "yellow"
            table.add_row(
                ws.name,
                f"[{status_style}]{ws.status}[/{status_style}]",
                ws.id[:8],
                ws.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)

    import asyncio
    asyncio.run(_run())


@workspace_app.command("config")
def workspace_config(
    name: str = typer.Argument(..., help="Workspace name"),
    set_val: str = typer.Option(None, "--set", "-s", help="Set config key=value (dot notation)"),
):
    """View or update workspace config overrides."""
    import json as _json
    from miu_bot.workspace.service import WorkspaceService
    from miu_bot.db.file_backend import FileBackend

    backend = FileBackend()

    async def _run():
        svc = WorkspaceService(backend)
        if set_val:
            key, _, value = set_val.partition("=")
            if not key or not value:
                console.print("[red]Format: --set key=value[/red]")
                raise typer.Exit(1)
            # Try to parse value as JSON, fall back to string
            try:
                parsed = _json.loads(value)
            except _json.JSONDecodeError:
                parsed = value
            ws = await svc.update_config(name, key.strip(), parsed)
            if ws:
                console.print(f"[green]✓[/green] Updated {key} for workspace '{name}'")
            else:
                console.print(f"[red]Workspace '{name}' not found[/red]")
        else:
            ws = await svc.get(name)
            if not ws:
                console.print(f"[red]Workspace '{name}' not found[/red]")
                raise typer.Exit(1)
            console.print(f"[cyan]{name}[/cyan] config overrides:")
            console.print(_json.dumps(ws.config_overrides, indent=2))

    import asyncio
    asyncio.run(_run())


@workspace_app.command("pause")
def workspace_pause(
    name: str = typer.Argument(..., help="Workspace name"),
):
    """Pause a workspace (stop processing messages)."""
    from miu_bot.workspace.service import WorkspaceService
    from miu_bot.db.file_backend import FileBackend

    backend = FileBackend()

    async def _run():
        svc = WorkspaceService(backend)
        ws = await svc.set_status(name, "paused")
        if ws:
            console.print(f"[green]✓[/green] Workspace '{name}' paused")
        else:
            console.print(f"[red]Workspace '{name}' not found[/red]")

    import asyncio
    asyncio.run(_run())


@workspace_app.command("delete")
def workspace_delete(
    name: str = typer.Argument(..., help="Workspace name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a workspace."""
    from miu_bot.workspace.service import WorkspaceService
    from miu_bot.db.file_backend import FileBackend

    if not force:
        if not typer.confirm(f"Delete workspace '{name}'?"):
            raise typer.Abort()

    backend = FileBackend()

    async def _run():
        svc = WorkspaceService(backend)
        if await svc.delete(name):
            console.print(f"[green]✓[/green] Deleted workspace '{name}'")
        else:
            console.print(f"[red]Workspace '{name}' not found[/red]")

    import asyncio
    asyncio.run(_run())


# ============================================================================
# Database Commands
# ============================================================================

db_app = typer.Typer(help="Database management")
app.add_typer(db_app, name="db")


@db_app.command("migrate")
def db_migrate(
    downgrade: int = typer.Option(None, "--downgrade", help="Rollback N revisions"),
):
    """Run database migrations."""
    from miu_bot.config.loader import load_config

    config = load_config()
    db_url = config.database.url
    if not db_url:
        console.print("[red]Error: database.url not configured[/red]")
        console.print("Set MIU_BOT_DATABASE__URL or add to config.json")
        raise typer.Exit(1)

    from alembic.config import Config as AlembicConfig
    from alembic import command
    from pathlib import Path as _Path

    migrations_dir = str(_Path(__file__).parent.parent / "db" / "migrations")
    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option("script_location", migrations_dir)
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    if downgrade:
        command.downgrade(alembic_cfg, f"-{downgrade}")
        console.print(f"[green]✓[/green] Rolled back {downgrade} revision(s)")
    else:
        command.upgrade(alembic_cfg, "head")
        console.print("[green]✓[/green] Migrations applied to head")


@db_app.command("import-legacy")
def db_import_legacy(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without importing"),
    data_dir: Path = typer.Option(None, "--data-dir", help="Override data directory (~/.miu-bot)"),
):
    """Import legacy file-based data into the database."""
    from miu_bot.config.loader import load_config

    config = load_config()
    db_url = config.database.url
    if not db_url:
        console.print("[red]Error: database.url not configured[/red]")
        raise typer.Exit(1)

    base_dir = data_dir or (Path.home() / ".miu-bot")
    if not base_dir.exists():
        console.print(f"[red]Data directory not found: {base_dir}[/red]")
        raise typer.Exit(1)

    async def _run():
        from miu_bot.db.pool import create_pool, close_pool
        from miu_bot.db.postgres import PostgresBackend
        from miu_bot.db.import_legacy import LegacyImporter

        pool = await create_pool(db_url, config.database.min_pool_size, config.database.max_pool_size)
        backend = PostgresBackend(pool)

        try:
            importer = LegacyImporter(backend, base_dir)
            result = await importer.import_all(dry_run=dry_run)

            suffix = " (dry run)" if dry_run else ""
            table = Table(title=f"Import Summary{suffix}")
            table.add_column("Item", style="cyan")
            table.add_column("Count", justify="right")
            table.add_row("Workspace", result.workspace_name or "-")
            table.add_row("Sessions", str(result.sessions_imported))
            table.add_row("Messages", str(result.messages_imported))
            table.add_row("Memories", str(result.memories_imported))
            table.add_row("Skipped", str(result.skipped))
            table.add_row("Errors", str(len(result.errors)))
            console.print(table)

            if result.errors:
                console.print("\n[yellow]Errors:[/yellow]")
                for err in result.errors:
                    console.print(f"  - {err}")
        finally:
            await close_pool(pool)

    import asyncio
    asyncio.run(_run())


@db_app.command("status")
def db_status():
    """Show migration status."""
    from miu_bot.config.loader import load_config

    config = load_config()
    db_url = config.database.url
    if not db_url:
        console.print("[red]database.url not configured[/red]")
        raise typer.Exit(1)

    from alembic.config import Config as AlembicConfig
    from alembic import command
    from pathlib import Path as _Path

    migrations_dir = str(_Path(__file__).parent.parent / "db" / "migrations")
    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option("script_location", migrations_dir)
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    console.print(f"Database: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    command.current(alembic_cfg, verbose=True)


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show miubot status."""
    from miu_bot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} miubot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from miu_bot.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")
        
        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")


if __name__ == "__main__":
    app()
