"""Direct response sending from workers to gateway."""

from __future__ import annotations

from typing import Any

from loguru import logger

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


async def send_response(
    gateway_url: str,
    channel: str,
    chat_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    bot_name: str = "",
) -> None:
    """Send a response via the gateway's /internal/send endpoint."""
    if httpx is None:
        raise ImportError("httpx required for worker response delivery")

    url = f"{gateway_url.rstrip('/')}/internal/send"
    payload = {
        "channel": channel,
        "chat_id": chat_id,
        "content": content,
        "metadata": metadata or {},
        "bot_name": bot_name,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.warning(f"Gateway response delivery failed: {resp.status_code} {resp.text}")
        else:
            logger.debug(f"Response delivered via gateway for {channel}:{chat_id}")
