"""Download media URLs and prepare them for multimodal LLM input.

Supports images (base64 inline) and PDFs (text extraction).
Used by process_message to inject attachments directly into LLM messages
instead of relying on slow MCP tools like webReader.
"""

from __future__ import annotations

import base64
import mimetypes
from typing import Any

import httpx
from loguru import logger

_MAX_DOWNLOAD = 20 * 1024 * 1024  # 20 MB
_TIMEOUT = 30  # seconds
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_PDF_TYPE = "application/pdf"


async def resolve_media_urls(urls: list[str]) -> list[dict[str, Any]]:
    """Download media URLs and return LLM-ready content parts.

    Returns list of OpenAI-compatible content parts:
      - {"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}
      - {"type": "text", "text": "[PDF content extracted from filename.pdf]\\n..."}

    Silently skips URLs that fail to download or are unsupported types.
    """
    parts: list[dict[str, Any]] = []
    for url in urls:
        try:
            part = await _resolve_single(url)
            if part:
                parts.append(part)
        except Exception as e:
            logger.warning(f"Media resolve failed for {url[:80]}: {e}")
    return parts


async def _resolve_single(url: str) -> dict[str, Any] | None:
    """Download and convert a single URL to an LLM content part."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT) as client:
        resp = await client.get(url)
        if resp.status_code >= 400:
            logger.warning(f"Media download failed ({resp.status_code}): {url[:80]}")
            return None
        if len(resp.content) > _MAX_DOWNLOAD:
            logger.warning(f"Media too large ({len(resp.content)} bytes): {url[:80]}")
            return None

    content_type = resp.headers.get("content-type", "")
    mime = content_type.split(";")[0].strip().lower()

    # Fallback: guess from URL extension
    if not mime or mime == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(url.split("?")[0])
        if guessed:
            mime = guessed

    if mime in _IMAGE_TYPES:
        return _to_image_part(resp.content, mime)
    if mime == _PDF_TYPE:
        return _to_pdf_part(resp.content, url)

    logger.debug(f"Unsupported media type '{mime}' for {url[:80]}")
    return None


def _to_image_part(data: bytes, mime: str) -> dict[str, Any]:
    """Convert image bytes to base64 image_url content part."""
    b64 = base64.b64encode(data).decode()
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"},
    }


def _to_pdf_part(data: bytes, url: str) -> dict[str, Any]:
    """Extract text from PDF bytes and return as text content part."""
    text = _extract_pdf_text(data)
    if not text or len(text.strip()) < 10:
        # Fallback: return as base64 for models that support it
        b64 = base64.b64encode(data).decode()
        return {
            "type": "text",
            "text": f"[PDF file from {url.split('/')[-1].split('?')[0]}]\n"
                    f"Base64-encoded PDF ({len(data)} bytes): {b64[:200]}...\n"
                    f"(Use a tool to read the full content if needed)",
        }
    filename = url.split("/")[-1].split("?")[0] or "document.pdf"
    return {
        "type": "text",
        "text": f"[Content extracted from {filename}]\n{text}",
    }


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF bytes using pymupdf if available."""
    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=data, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                pages.append(f"--- Page {i + 1} ---\n{text.strip()}")
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        logger.debug("pymupdf not installed, PDF text extraction unavailable")
        return ""
    except Exception as e:
        logger.warning(f"PDF text extraction failed: {e}")
        return ""
