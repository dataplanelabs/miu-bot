"""Message bus module for decoupled channel-agent communication."""

from miubot.bus.events import InboundMessage, OutboundMessage
from miubot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
