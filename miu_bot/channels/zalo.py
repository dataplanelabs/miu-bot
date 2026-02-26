"""Zalo channel implementation using ZCA-CLI WebSocket bridge."""

import asyncio
import hashlib
import json
import time

from loguru import logger

from miu_bot.bus.events import OutboundMessage
from miu_bot.bus.queue import MessageBus
from miu_bot.channels.base import BaseChannel
from miu_bot.channels.zalo_media import extract_media_markers, normalize_content, send_media
from miu_bot.config.schema import ZaloConfig


class ZaloChannel(BaseChannel):
    """
    Zalo channel that connects to a ZCA-CLI WebSocket bridge.

    The bridge uses zca-js to handle the Zalo protocol.
    Communication between Python and TypeScript is via WebSocket.
    """

    name = "zalo"

    def __init__(self, config: ZaloConfig, bus: MessageBus, bot_name: str = ""):
        super().__init__(config, bus, bot_name=bot_name)
        self.config: ZaloConfig = config
        self._ws = None
        self._connected = False
        self._typing_tasks: dict[str, asyncio.Task] = {}  # chat_id -> typing loop task
        self._thread_types: dict[str, int] = {}  # chat_id -> thread_type (1=user, 2=group)
        self._response_waiters: dict[str, asyncio.Future] = {}  # response_type -> future
        self._seen_msgs: dict[str, float] = {}  # dedup_key -> timestamp
        self._dedup_ttl = 300  # ignore duplicate messages within 5 min window

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

    def get_thread_type(self, chat_id: str) -> int:
        """Get cached thread type for a chat (1=user, 2=group)."""
        return self._thread_types.get(chat_id, 1)

    def _is_duplicate(self, key: str) -> bool:
        """Check if message was already seen; evict expired entries."""
        now = time.monotonic()
        # Evict stale entries periodically (when cache grows beyond 200)
        if len(self._seen_msgs) > 200:
            self._seen_msgs = {
                k: t for k, t in self._seen_msgs.items()
                if now - t < self._dedup_ttl
            }
        if key in self._seen_msgs and now - self._seen_msgs[key] < self._dedup_ttl:
            return True
        self._seen_msgs[key] = now
        return False

    async def send_and_wait(self, cmd: dict, expected_type: str) -> dict:
        """Send a WS command and wait for a matching response type."""
        if not self._ws or not self._connected:
            return {"type": "error", "error": "Bridge not connected"}

        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict] = loop.create_future()
        self._response_waiters[expected_type] = future

        try:
            await self._ws.send(json.dumps(cmd))
            return await asyncio.wait_for(future, timeout=10.0)
        except asyncio.TimeoutError:
            return {"type": "error", "error": f"Timeout waiting for {expected_type}"}
        finally:
            self._response_waiters.pop(expected_type, None)

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

    TYPING_MAX_DURATION = 300  # Safety net: auto-stop typing after 5 min

    async def _typing_loop(self, chat_id: str, thread_type: int) -> None:
        """Repeatedly send typing indicator until cancelled or max duration reached."""
        try:
            elapsed = 0
            while elapsed < self.TYPING_MAX_DURATION:
                if self._ws and self._connected:
                    await self._ws.send(json.dumps({
                        "type": "typing", "to": chat_id, "threadType": thread_type,
                    }))
                await asyncio.sleep(3)  # Zalo typing indicator lasts ~5s
                elapsed += 3
            logger.warning(f"Typing timeout for {chat_id} after {self.TYPING_MAX_DURATION}s")
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
            if msg.metadata and msg.metadata.get("thread_type"):
                thread_type = msg.metadata["thread_type"]
            else:
                thread_type = self._thread_types.get(msg.chat_id, 1)

            # Extract media markers and strip from content
            media_items, content = extract_media_markers(msg.content)

            # Send media first
            for i, item in enumerate(media_items):
                await send_media(self._ws, item, msg.chat_id, thread_type)
                if i < len(media_items) - 1:
                    await asyncio.sleep(0.5)

            # Send text chunks
            if content:
                chunks = self._split_message(content, self.ZALO_MAX_CHARS)
                for chunk in chunks:
                    payload = {
                        "type": "send",
                        "to": msg.chat_id,
                        "text": chunk,
                        "threadType": thread_type,
                    }
                    await self._ws.send(json.dumps(payload))
                    if len(chunks) > 1:
                        await asyncio.sleep(0.3)
                logger.info(
                    f"Zalo send: to={msg.chat_id} chunks={len(chunks)} "
                    f"media={len(media_items)} threadType={thread_type}"
                )
            elif media_items:
                logger.info(f"Zalo send: to={msg.chat_id} media={len(media_items)} threadType={thread_type} (no text)")

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
            content, media_urls = normalize_content(data.get("content"))
            is_group = data.get("threadType") == "group"
            thread_type = 2 if is_group else 1

            # Deduplicate: use msgId from bridge, fallback to content hash
            dedup_key = data.get("msgId") or hashlib.sha256(
                f"{sender_id}:{thread_id}:{content}".encode()
            ).hexdigest()[:16]
            if self._is_duplicate(dedup_key):
                logger.debug(f"Zalo: duplicate message skipped (key={dedup_key[:8]})")
                return

            # Cache thread type for outbound message routing
            self._thread_types[thread_id] = thread_type

            # In groups, only consume messages from allowed groups
            if is_group and self.config.respond_to_groups:
                if thread_id not in self.config.respond_to_groups:
                    return

            # In DMs, only consume messages from allowed users (empty = all)
            if not is_group and self.config.respond_to_users:
                if sender_id not in self.config.respond_to_users:
                    return

            # Check allow_from before starting typing to prevent stuck typing
            if not self.is_allowed(sender_id):
                logger.debug(f"Zalo: sender {sender_id} not in allowFrom, skipping")
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
                media=media_urls if media_urls else None,
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
            # Resolve any waiting futures with the error
            for key, future in list(self._response_waiters.items()):
                if not future.done():
                    future.set_result(data)
                    self._response_waiters.pop(key, None)

        # Route responses to waiters (reminder-created, reminders, reminder-removed)
        if msg_type in self._response_waiters:
            future = self._response_waiters.get(msg_type)
            if future and not future.done():
                future.set_result(data)
