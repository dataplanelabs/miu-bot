"""Hatchet client initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from miu_bot.config.schema import HatchetConfig


def create_hatchet_client(config: "HatchetConfig"):
    """Create a Hatchet SDK client from config."""
    from hatchet_sdk import Hatchet
    from hatchet_sdk.config import ClientConfig, ClientTLSConfig

    kwargs = dict(
        server_url=config.api_url,
        token=config.token,
        namespace=config.namespace,
    )
    if config.grpc_host:
        kwargs["host_port"] = config.grpc_host
    if config.tls_strategy:
        kwargs["tls_config"] = ClientTLSConfig(strategy=config.tls_strategy)

    client_config = ClientConfig(**kwargs)
    return Hatchet(config=client_config)
