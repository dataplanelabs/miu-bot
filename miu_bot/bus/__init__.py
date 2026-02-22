"""Message bus module for decoupled channel-agent communication."""

from miu_bot.bus.events import InboundMessage, OutboundMessage
from miu_bot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
