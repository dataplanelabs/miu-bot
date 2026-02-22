---
phase: 2
title: "Nanobot Zalo Channel"
status: complete
priority: P1
---

# Phase 2: Nanobot Zalo Channel (Python)

## Context

- Parent plan: [plan.md](./plan.md)
- nanobot repo: `/Users/vanducng/git/personal/agents/nanobot/`
- Reference: `nanobot/channels/whatsapp.py` (identical pattern)
- Reference: `nanobot/config/schema.py` (WhatsAppConfig)
- Reference: `nanobot/channels/manager.py` (channel registration)

## Overview

Add ZaloChannel to nanobot — a WebSocket client that connects to the ZCA bridge server, receives Zalo messages, and sends replies. Follows the exact same pattern as WhatsAppChannel.

## Key Insights

- WhatsAppChannel is ~149 lines — ZaloChannel will be nearly identical
- Only difference: send payload includes `threadType` field (1=User, 2=Group)
- Config matches WhatsApp: `enabled`, `bridge_url`, `bridge_token`, `allow_from`
- Default bridge port: 3002 (WhatsApp uses 3001)
- `sender_id` = Zalo uidFrom (numeric string)
- `chat_id` = threadId (thread identifier for replies)

## Requirements

- Connect to ZCA bridge WS server
- Auth handshake if token configured
- Parse incoming messages, forward to MessageBus via `_handle_message()`
- Send outbound messages with correct threadType
- Auto-reconnect on disconnect (5s delay, same as WhatsApp)
- ZaloConfig in schema with `bridge_url`, `bridge_token`, `allow_from`
- Register in ChannelManager

## Related Code Files

**Create:**
- `nanobot/channels/zalo.py` — ZaloChannel class

**Modify:**
- `nanobot/config/schema.py` — Add ZaloConfig + register in ChannelsConfig
- `nanobot/channels/manager.py` — Add zalo channel init block
- `~/.nanobot/config.json` — Add zalo config section

## Implementation Steps

### Step 1: Add ZaloConfig to schema.py

After `WhatsAppConfig` class (~line 13), add:

```python
class ZaloConfig(BaseModel):
    """Zalo channel configuration."""
    enabled: bool = False
    bridge_url: str = "ws://localhost:3002"
    bridge_token: str = ""
    allow_from: list[str] = Field(default_factory=list)  # Allowed Zalo user IDs
```

In `ChannelsConfig` class, add field:
```python
zalo: ZaloConfig = Field(default_factory=ZaloConfig)
```

### Step 2: Create nanobot/channels/zalo.py

```python
"""Zalo channel implementation using ZCA-CLI WebSocket bridge."""

import asyncio
import json
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import ZaloConfig


class ZaloChannel(BaseChannel):
    """
    Zalo channel that connects to a ZCA-CLI WebSocket bridge.

    The bridge uses zca-js to handle the Zalo protocol.
    Communication between Python and TypeScript is via WebSocket.
    """

    name = "zalo"

    def __init__(self, config: ZaloConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: ZaloConfig = config
        self._ws = None
        self._connected = False

    async def start(self) -> None:
        """Start the Zalo channel by connecting to the bridge."""
        import websockets

        bridge_url = self.config.bridge_url
        logger.info(f"Connecting to Zalo bridge at {bridge_url}...")
        self._running = True

        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    if self.config.bridge_token:
                        await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
                    self._connected = True
                    logger.info("Connected to Zalo bridge")

                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception as e:
                            logger.error(f"Error handling bridge message: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning(f"Zalo bridge connection error: {e}")
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the Zalo channel."""
        self._running = False
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Zalo."""
        if not self._ws or not self._connected:
            logger.warning("Zalo bridge not connected")
            return

        try:
            # Determine thread type from metadata or default to User (1)
            thread_type = msg.metadata.get("thread_type", 1) if msg.metadata else 1
            payload = {
                "type": "send",
                "to": msg.chat_id,
                "text": msg.content,
                "threadType": thread_type,
            }
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.error(f"Error sending Zalo message: {e}")

    async def _handle_bridge_message(self, raw: str) -> None:
        """Handle a message from the bridge."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from bridge: {raw[:100]}")
            return

        msg_type = data.get("type")

        if msg_type == "message":
            sender_id = data.get("senderId", "")
            thread_id = data.get("threadId", "")
            content = data.get("content", "")
            is_group = data.get("threadType") == "group"
            thread_type = 2 if is_group else 1

            await self._handle_message(
                sender_id=sender_id,
                chat_id=thread_id,
                content=content,
                metadata={
                    "sender_name": data.get("senderName"),
                    "thread_name": data.get("threadName"),
                    "timestamp": data.get("timestamp"),
                    "is_group": is_group,
                    "thread_type": thread_type,
                }
            )

        elif msg_type == "status":
            status = data.get("status")
            logger.info(f"Zalo status: {status}")
            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False

        elif msg_type == "error":
            logger.error(f"Zalo bridge error: {data.get('error')}")
```

### Step 3: Register in manager.py

After the WhatsApp channel block (~line 59), add:

```python
# Zalo channel
if self.config.channels.zalo.enabled:
    try:
        from nanobot.channels.zalo import ZaloChannel
        self.channels["zalo"] = ZaloChannel(
            self.config.channels.zalo, self.bus
        )
        logger.info("Zalo channel enabled")
    except ImportError as e:
        logger.warning(f"Zalo channel not available: {e}")
```

### Step 4: Update config.json

Add zalo section to `~/.nanobot/config.json` channels:

```json
"zalo": {
    "enabled": false,
    "bridgeUrl": "ws://localhost:3002",
    "bridgeToken": "",
    "allowFrom": []
}
```

## Todo

- [x] Add ZaloConfig to `nanobot/config/schema.py`
- [x] Add `zalo` field to ChannelsConfig
- [x] Create `nanobot/channels/zalo.py`
- [x] Register ZaloChannel in `nanobot/channels/manager.py`
- [x] Add zalo section to `~/.nanobot/config.json`
- [x] Test end-to-end: bridge + nanobot

## Success Criteria

- `nanobot gateway` connects to ZCA bridge when zalo channel enabled
- Incoming Zalo messages routed through MessageBus to AgentLoop
- Agent responses sent back through bridge to Zalo
- Auto-reconnect on bridge disconnect
- `allow_from` filtering works with Zalo user IDs

## Risk Assessment

- **Bridge must be running first**: ZaloChannel will retry connection every 5s until bridge is available
- **threadType mapping**: Must correctly pass User(1)/Group(2) for replies; wrong type = message delivery failure

## Security

- WS connection localhost only (bridge + channel on same machine)
- Optional token auth between bridge and channel
- `allow_from` filters unauthorized Zalo users
