"""Hatchet client initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from miu_bot.config.schema import HatchetConfig


def create_hatchet_client(config: "HatchetConfig"):
    """Create a Hatchet SDK client from config."""
    from hatchet_sdk import Hatchet

    return Hatchet(
        server_url=config.api_url,
        token=config.token,
        namespace=config.namespace,
    )
