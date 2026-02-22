"""Bot manager for multi-bot channel orchestration."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

from loguru import logger

from miu_bot.bus.events import OutboundMessage
from miu_bot.bus.queue import MessageBus
from miu_bot.channels.base import BaseChannel

# Registry: channel_type -> (module_path, class_name)
CHANNEL_REGISTRY: dict[str, tuple[str, str]] = {
    "telegram": ("miu_bot.channels.telegram", "TelegramChannel"),
    "zalo": ("miu_bot.channels.zalo", "ZaloChannel"),
    "whatsapp": ("miu_bot.channels.whatsapp", "WhatsAppChannel"),
    "discord": ("miu_bot.channels.discord", "DiscordChannel"),
    "feishu": ("miu_bot.channels.feishu", "FeishuChannel"),
    "mochat": ("miu_bot.channels.mochat", "MochatChannel"),
    "dingtalk": ("miu_bot.channels.dingtalk", "DingTalkChannel"),
    "email": ("miu_bot.channels.email", "EmailChannel"),
    "slack": ("miu_bot.channels.slack", "SlackChannel"),
    "qq": ("miu_bot.channels.qq", "QQChannel"),
}


def _build_channel_config(ch_type: str, ch_cfg: Any, global_channels: Any = None) -> Any:
    """Convert generic BotChannelConfig to channel-native config object.

    Uses global channel config as base, then overlays bot-specific fields.
    """
    from miu_bot.config import schema

    config_map: dict[str, type] = {
        "telegram": schema.TelegramConfig,
        "zalo": schema.ZaloConfig,
        "whatsapp": schema.WhatsAppConfig,
        "discord": schema.DiscordConfig,
        "feishu": schema.FeishuConfig,
        "mochat": schema.MochatConfig,
        "dingtalk": schema.DingTalkConfig,
        "email": schema.EmailConfig,
        "slack": schema.SlackConfig,
        "qq": schema.QQConfig,
    }

    config_cls = config_map.get(ch_type)
    if not config_cls:
        raise ValueError(f"Unknown channel type: {ch_type}")

    # Start from global channel config if available
    global_ch = getattr(global_channels, ch_type, None) if global_channels else None
    kwargs: dict[str, Any] = global_ch.model_dump() if global_ch else {}

    # Always enable (bot declared this channel)
    kwargs["enabled"] = True

    # Overlay bot-specific fields (non-empty only)
    if ch_cfg.token:
        kwargs["token"] = ch_cfg.token
    if ch_cfg.allow_from:
        kwargs["allow_from"] = ch_cfg.allow_from
    if ch_cfg.proxy:
        kwargs["proxy"] = ch_cfg.proxy

    return config_cls(**kwargs)


class BotManager:
    """Manages channel instances for multiple bots.

    Each bot from bots.yaml gets its own channel instances.
    Channels keyed by '{bot_name}:{channel_type}'.
    """

    def __init__(self, bots: dict[str, Any], bus: MessageBus, global_channels: Any = None):
        self.bus = bus
        self.global_channels = global_channels
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None

        for bot_name, bot_cfg in bots.items():
            self._init_bot_channels(bot_name, bot_cfg)

    def _init_bot_channels(self, bot_name: str, bot_cfg: Any) -> None:
        """Create channel instances for a single bot."""
        for ch_type, ch_cfg in bot_cfg.channels.items():
            if ch_type not in CHANNEL_REGISTRY:
                logger.warning(f"Unknown channel type '{ch_type}' for bot '{bot_name}'")
                continue
            try:
                mod_path, cls_name = CHANNEL_REGISTRY[ch_type]
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name)

                channel_config = _build_channel_config(ch_type, ch_cfg, self.global_channels)
                instance = cls(channel_config, self.bus, bot_name=bot_name)

                key = f"{bot_name}:{ch_type}"
                self.channels[key] = instance
                logger.info(f"Channel '{key}' initialized for bot '{bot_name}'")
            except ImportError as e:
                logger.warning(f"Channel '{ch_type}' not available for bot '{bot_name}': {e}")
            except Exception as e:
                logger.error(f"Failed to init channel '{ch_type}' for bot '{bot_name}': {e}")

    async def start_all(self) -> None:
        """Start all channel instances and outbound dispatcher."""
        if not self.channels:
            logger.warning("No bot channels configured")
            return

        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        tasks = []
        for key, channel in self.channels.items():
            logger.info(f"Starting channel {key}...")
            tasks.append(asyncio.create_task(self._start_channel(key, channel)))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _start_channel(self, key: str, channel: BaseChannel) -> None:
        try:
            await channel.start()
        except Exception as e:
            logger.error(f"Failed to start channel {key}: {e}")

    async def stop_all(self) -> None:
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        for key, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info(f"Stopped channel {key}")
            except Exception as e:
                logger.error(f"Error stopping {key}: {e}")

    async def _dispatch_outbound(self) -> None:
        """Route outbound messages to the correct bot's channel instance."""
        logger.info("Bot outbound dispatcher started")
        while True:
            try:
                msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
                if msg.bot_name:
                    key = f"{msg.bot_name}:{msg.channel}"
                else:
                    key = msg.channel  # Fallback for backward compat
                channel = self.channels.get(key)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error(f"Error sending to {key}: {e}")
                else:
                    logger.warning(f"No channel found for key: {key}")
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    @property
    def enabled_channels(self) -> list[str]:
        return list(self.channels.keys())
