"""Chat channels module with plugin architecture."""

from miu_bot.channels.base import BaseChannel
from miu_bot.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
