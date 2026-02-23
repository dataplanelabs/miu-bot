"""Temporal client factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from temporalio.client import Client


async def create_temporal_client(
    server_url: str = "localhost:7233",
    namespace: str = "miubot",
) -> "Client":
    """Create and connect a Temporal client."""
    from temporalio.client import Client

    client = await Client.connect(server_url, namespace=namespace)
    logger.info(f"Temporal client connected: {server_url} ns={namespace}")
    return client
