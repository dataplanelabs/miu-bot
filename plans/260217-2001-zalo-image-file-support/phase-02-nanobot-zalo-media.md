# Phase 02 — Nanobot: Media Marker Extraction in zalo.py

## Context Links
- Zalo channel: `nanobot/channels/zalo.py` (257 lines)
- OutboundMessage: `nanobot/bus/events.py`
- Plan overview: [plan.md](./plan.md)
- Phase 01: [phase-01-bridge-media-handlers.md](./phase-01-bridge-media-handlers.md)

## Overview

- **Priority**: P2
- **Status**: complete
- **Effort**: 1h
- **Description**: Extend `ZaloChannel.send()` to extract `[send-image:…]` and `[send-file:…]` markers from message content, dispatch them via the bridge's new WS commands, then strip the markers from the text before sending.

## Key Insights

- `OutboundMessage.media` already exists but the agent loop never populates it — using content markers is simpler and requires zero loop changes
- Markers are embedded by the LLM in its final response text; `zalo.py` owns extraction logic
- Media should be sent **before** text chunks so the image/file appears first in chat
- ~~`_is_image()` removed~~ — marker type already distinguishes image vs file; LLM decides
<!-- Updated: Validation Session 1 - Removed _is_image() and _IMAGE_EXTENSIONS per validation -->
- URL vs local path is detected by `http://` / `https://` prefix — same logic used in both Python and the bridge

## Requirements

**Functional**
- Parse `msg.content` for zero or more `[send-image:<path_or_url>]` markers
- Parse `msg.content` for zero or more `[send-file:<path_or_url>]` markers
- For each marker: send the appropriate WS command to bridge
- Strip all markers from content before sending text chunks
- If content is empty after stripping, skip text send

**Non-functional**
- Marker extraction must not raise — log and continue on per-media errors
- No new dependencies; uses only stdlib `re` and existing `json`

## Architecture

```
ZaloChannel.send(msg)
  │
  ├── _stop_typing()
  ├── resolve thread_type
  │
  ├── _extract_media_markers(msg.content)
  │     returns: (media_list, cleaned_content)
  │     media_list: [{"marker_type": "send-image"|"send-file", "path": "..."}]
  │
  ├── for each media item:
  │     await _send_media(item, chat_id, thread_type)
  │       └── WS send: { type: "send-image"|"send-file", to, threadType, filePath|url }
  │
  └── if cleaned_content:
        for chunk in _split_message(cleaned_content):
          WS send: { type: "send", ... }
```

## Marker Format

```
[send-image:/absolute/path/to/image.png]
[send-image:https://example.com/photo.jpg]
[send-file:/tmp/report.pdf]
[send-file:https://example.com/doc.pdf]
[send-file:/tmp/doc.pdf|Optional caption text]
```

The optional `|caption` suffix for `send-file` is passed as `message` to the bridge.

## Related Code Files

**Modify**
- `nanobot/channels/zalo.py` — `send()`, new `_extract_media_markers()`, `_send_media()` helpers

**No changes**
- `nanobot/bus/events.py` — `OutboundMessage.media` field left as-is (unused)
- `nanobot/agent/loop.py` — no changes required

## Implementation Steps

### 1. Add `import re` at top of `zalo.py`

```python
import re
```

### 2. Add `_MEDIA_MARKER_RE` class constant

Inside `ZaloChannel` class, alongside `ZALO_MAX_CHARS`:

```python
_MEDIA_MARKER_RE = re.compile(
    r'\[(?P<kind>send-image|send-file):(?P<path>[^\]]+)\]'
)
```

### 3. Add `_extract_media_markers()` static method

```python
@staticmethod
def _extract_media_markers(content: str) -> tuple[list[dict], str]:
    """Extract [send-image:…] and [send-file:…] markers from content.

    Returns (media_items, cleaned_content).
    Each item: {"kind": "send-image"|"send-file", "path": str, "caption": str}
    """
    items = []
    for m in ZaloChannel._MEDIA_MARKER_RE.finditer(content):
        raw_path = m.group("path").strip()
        # Optional caption after | for send-file
        if "|" in raw_path:
            path, caption = raw_path.split("|", 1)
        else:
            path, caption = raw_path, ""
        items.append({"kind": m.group("kind"), "path": path.strip(), "caption": caption.strip()})
    cleaned = ZaloChannel._MEDIA_MARKER_RE.sub("", content).strip()
    return items, cleaned
```

### 4. Add `_send_media()` async method

```python
async def _send_media(self, item: dict, chat_id: str, thread_type: int) -> None:
    """Send a single media item via the bridge."""
    path = item["path"]
    kind = item["kind"]
    is_url = path.startswith("http://") or path.startswith("https://")

    if kind == "send-image":
        payload: dict = {"type": "send-image", "to": chat_id, "threadType": thread_type}
    else:
        payload = {
            "type": "send-file",
            "to": chat_id,
            "threadType": thread_type,
            "message": item.get("caption", ""),
        }

    if is_url:
        payload["url"] = path
    else:
        payload["filePath"] = path

    try:
        await self._ws.send(json.dumps(payload))
        logger.info(f"Zalo media send: kind={kind} to={chat_id} path={path!r}")
    except Exception as e:
        logger.error(f"Zalo media send error: kind={kind} path={path!r} error={e}")
```

### 5. Update `send()` to use the new helpers

Replace the body of `send()` (lines 124–154 in current file) with:

```python
async def send(self, msg: OutboundMessage) -> None:
    """Send a message through Zalo, splitting long content into multiple messages."""
    self._stop_typing(msg.chat_id)

    if not self._ws or not self._connected:
        logger.warning("Zalo bridge not connected")
        return

    try:
        # Resolve thread type
        if msg.metadata and msg.metadata.get("thread_type"):
            thread_type = msg.metadata["thread_type"]
        else:
            thread_type = self._thread_types.get(msg.chat_id, 1)

        # Extract media markers and strip from content
        media_items, content = self._extract_media_markers(msg.content)

        # Send media first (image/file before text)
        for item in media_items:
            await self._send_media(item, msg.chat_id, thread_type)
            if media_items.index(item) < len(media_items) - 1:
                await asyncio.sleep(0.5)  # brief gap between media items

        # Send text chunks (if any remain after stripping markers)
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
```

## Todo List

- [x] Add `import re` to `zalo.py`
- [x] Add `_MEDIA_MARKER_RE` class constant
- [x] Implement `_extract_media_markers()` static method
- [x] Implement `_send_media()` async method
- [x] Update `send()` to call extraction + media dispatch before text chunks
- [x] Verify file stays under 200 lines (split if needed)
- [x] Run `python -m py_compile nanobot/channels/zalo.py` to confirm no syntax errors

## Success Criteria

- `_extract_media_markers("[send-image:/tmp/a.png] hello")` returns `([{kind: 'send-image', path: '/tmp/a.png', caption: ''}], 'hello')`
- `send()` with a marker-containing response sends WS `send-image` command then the text
- Content with only markers sends media with no text message
- No marker → behavior identical to current (no regression)

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Regex too greedy (matches inside code blocks) | Low | Markers are explicit `[send-image:…]` format; unlikely collision |
| `_send_media` error silently drops media | Low | Logged at ERROR level; text still sent |
| File over 200 lines after changes | Medium | Split helpers into `nanobot/channels/zalo_media.py` and import |

## Security Considerations

- `filePath` in markers comes from LLM output; the LLM runs in the agent's trust boundary — acceptable risk for the current architecture
- No user-supplied paths are passed directly from Zalo messages; only from LLM-generated content

## Next Steps

- Phase 03: Document the marker convention for the LLM system prompt
