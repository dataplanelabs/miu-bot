"""Zalo channel implementation using ZCA-CLI WebSocket bridge."""

import asyncio
import json
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import ZaloConfig


def normalize_content(content: Any) -> str:
    """Normalize content payload to text string."""
    if isinstance(content, str):
        return content.strip()
    if content is None:
        return ""
    if isinstance(content, list):
        # Join list items with newlines
        parts = [str(item).strip() for item in content if item]
        return "\n".join(parts).strip()
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)


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
        self._typing_tasks: dict[str, asyncio.Task] = {}  # chat_id -> typing loop task

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
        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)
        if self._ws:
            await self._ws.close()
            self._ws = None

    ZALO_MAX_CHARS = 2000

    def _start_typing(self, chat_id: str, thread_type: int = 1) -> None:
        """Start sending typing indicator for a chat."""
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id, thread_type))

    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task:
            task.cancel()

    async def _typing_loop(self, chat_id: str, thread_type: int) -> None:
        """Repeatedly send typing indicator until cancelled."""
        try:
            while True:
                if self._ws and self._connected:
                    await self._ws.send(json.dumps({
                        "type": "typing", "to": chat_id, "threadType": thread_type,
                    }))
                await asyncio.sleep(3)  # Zalo typing indicator lasts ~5s
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Zalo, splitting long content into multiple messages."""
        self._stop_typing(msg.chat_id)

        if not self._ws or not self._connected:
            logger.warning("Zalo bridge not connected")
            return

        try:
            thread_type = msg.metadata.get("thread_type", 1) if msg.metadata else 1
            chunks = self._split_message(msg.content, self.ZALO_MAX_CHARS)

            for chunk in chunks:
                payload = {
                    "type": "send",
                    "to": msg.chat_id,
                    "text": chunk,
                    "threadType": thread_type,
                }
                await self._ws.send(json.dumps(payload))
                # Small delay between chunks to preserve order
                if len(chunks) > 1:
                    await asyncio.sleep(0.3)

            logger.debug(f"Zalo send: to={msg.chat_id} chunks={len(chunks)} threadType={thread_type}")
        except Exception as e:
            logger.error(f"Error sending Zalo message: {e}")

    @staticmethod
    def _split_message(text: str, max_len: int) -> list[str]:
        """Split text into chunks at natural boundaries (paragraphs, then lines)."""
        if len(text) <= max_len:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= max_len:
                chunks.append(remaining)
                break

            # Try splitting at double newline (paragraph break)
            cut = remaining.rfind("\n\n", 0, max_len)
            if cut > 0:
                chunks.append(remaining[:cut].rstrip())
                remaining = remaining[cut:].lstrip("\n")
                continue

            # Try splitting at single newline
            cut = remaining.rfind("\n", 0, max_len)
            if cut > 0:
                chunks.append(remaining[:cut].rstrip())
                remaining = remaining[cut:].lstrip("\n")
                continue

            # Hard cut at max_len (last resort)
            chunks.append(remaining[:max_len])
            remaining = remaining[max_len:]

        return [c for c in chunks if c.strip()]

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
            content = normalize_content(data.get("content"))
            is_group = data.get("threadType") == "group"
            thread_type = 2 if is_group else 1

            # In groups, only consume messages from allowed groups
            if is_group and self.config.respond_to_groups:
                if thread_id not in self.config.respond_to_groups:
                    return

            # In groups, observe all messages but only reply when @mentioned
            is_mentioned = data.get("isMentioned", False)
            observe_only = is_group and self.config.require_mention_in_groups and not is_mentioned

            # Show typing indicator while processing (not for observe-only)
            if not observe_only:
                self._start_typing(thread_id, thread_type)

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
                },
                observe_only=observe_only,
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
