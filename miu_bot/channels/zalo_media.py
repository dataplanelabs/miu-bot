"""Zalo media marker extraction and dispatch helpers."""

import json
import os
import re
import tempfile
from mimetypes import guess_extension
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

# Regex to match [send-image:…] and [send-file:…] markers in LLM output
_MEDIA_MARKER_RE = re.compile(r'\[(?P<kind>send-image|send-file):(?P<path>[^\]]+)\]')

_MAX_DOWNLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


def normalize_content(content: Any) -> str:
    """Normalize content payload to text string."""
    if isinstance(content, str):
        return content.strip()
    if content is None:
        return ""
    if isinstance(content, list):
        parts = [str(item).strip() for item in content if item]
        return "\n".join(parts).strip()
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)


def extract_media_markers(content: str) -> tuple[list[dict], str]:
    """Extract [send-image:…] and [send-file:…] markers from content.

    Returns (media_items, cleaned_content).
    Each item: {"kind": "send-image"|"send-file", "path": str, "caption": str}
    """
    items = []
    for m in _MEDIA_MARKER_RE.finditer(content):
        raw_path = m.group("path").strip()
        if "|" in raw_path:
            path, caption = raw_path.split("|", 1)
        else:
            path, caption = raw_path, ""
        items.append({"kind": m.group("kind"), "path": path.strip(), "caption": caption.strip()})
    cleaned = _MEDIA_MARKER_RE.sub("", content)
    cleaned = re.sub(r"  +", " ", cleaned).strip()
    return items, cleaned


def _ext_from_url(url: str) -> str:
    """Extract file extension from URL path, ignoring query params."""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext[:10] if ext else ".bin"


async def _resolve_media_path(path: str) -> str | None:
    """Download URL to temp file, or validate local file. Returns local path or None."""
    is_url = path.startswith("http://") or path.startswith("https://")

    if not is_url:
        if os.path.isfile(path):
            return path
        logger.warning(f"Media file not found: {path}")
        return None

    # Download URL to temp file
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(path)
            if resp.status_code >= 400:
                logger.warning(f"Media download failed ({resp.status_code}): {path}")
                return None
            if len(resp.content) > _MAX_DOWNLOAD_SIZE:
                logger.warning(f"Media too large ({len(resp.content)} bytes): {path}")
                return None
            # Determine extension from content-type or URL
            ct = resp.headers.get("content-type", "")
            ext = guess_extension(ct.split(";")[0].strip()) if ct else None
            if not ext:
                ext = _ext_from_url(path)
            suffix = ext if ext.startswith(".") else f".{ext}"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="zalo-media-")
            os.write(fd, resp.content)
            os.close(fd)
            logger.info(f"Media downloaded: {path} -> {tmp_path} ({len(resp.content)} bytes)")
            return tmp_path
    except Exception as e:
        logger.warning(f"Media download error: {path} ({e})")
        return None


async def send_media(ws: Any, item: dict, chat_id: str, thread_type: int) -> None:
    """Download URL (if needed), validate, then send local filePath to bridge."""
    raw_path = item["path"]
    kind = item["kind"]

    local_path = await _resolve_media_path(raw_path)
    if not local_path:
        return

    is_temp = local_path != raw_path  # True if we downloaded it

    payload: dict = {
        "type": kind,
        "to": chat_id,
        "threadType": thread_type,
        "filePath": local_path,
    }
    if kind == "send-file":
        payload["message"] = item.get("caption", "")

    try:
        await ws.send(json.dumps(payload))
        logger.info(f"Zalo media: kind={kind} to={chat_id} path={local_path!r}")
    except Exception as e:
        logger.error(f"Zalo media error: kind={kind} path={local_path!r} error={e}")
    finally:
        # Clean up temp files (downloaded URLs)
        if is_temp:
            try:
                os.unlink(local_path)
            except OSError:
                pass
