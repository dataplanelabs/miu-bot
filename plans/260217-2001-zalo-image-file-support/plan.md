---
title: "Zalo Image & File Sending Support"
description: "Add outbound image and file attachment support to Zalo channel via ZCA bridge"
status: complete
priority: P2
effort: 3h
branch: main
tags: [zalo, media, bridge, channel]
created: 2026-02-17
---

# Zalo Image & File Sending Support

## Overview

Extend the Zalo channel to send images and file attachments outbound. Changes span two repos:
- **ZCA bridge** (TypeScript): new WebSocket message types `send-image` / `send-file`
- **Nanobot** (Python): marker extraction in `zalo.py`, wire media through `send()`

No agent loop changes needed. The LLM signals media by embedding `[send-image:path]` or `[send-file:path]` markers in its text response; `zalo.py` extracts and dispatches them, then strips markers before sending the text.

## Phases

| # | File | Description | Effort | Status |
|---|------|-------------|--------|--------|
| 1 | [phase-01-bridge-media-handlers.md](./phase-01-bridge-media-handlers.md) | ZCA bridge: add `send-image` / `send-file` WS handlers + URL download helper | 1.5h | complete |
| 2 | [phase-02-nanobot-zalo-media.md](./phase-02-nanobot-zalo-media.md) | Nanobot: marker extraction + `_send_media()` in `zalo.py` | 1h | complete |
| 3 | [phase-03-agent-loop-media.md](./phase-03-agent-loop-media.md) | Nanobot: document marker convention; no loop code changes | 0.5h | complete |

## Key Dependencies

- `zca-js` API: `api.sendImage()` and `api.sendMessage({ attachments })` must be available in bridge scope (confirmed from research)
- Bridge listener already running in bridge mode — file attachment callbacks work without extra setup
- `OutboundMessage.media` field already exists but unused; approach bypasses it via content markers

## Success Criteria

1. Bridge handles `send-image` and `send-file` WS commands (URL + local path)
2. `zalo.py` extracts `[send-image:…]` / `[send-file:…]` markers, sends via bridge, strips from text
3. End-to-end: LLM response with marker → image/file arrives in Zalo chat

## Validation Log

### Session 1 — 2026-02-17
**Trigger:** Initial plan creation validation
**Questions asked:** 4

#### Questions & Answers

1. **[Architecture]** The plan bypasses OutboundMessage.media entirely in favor of content markers ([send-image:path]). The LLM must learn this convention and embed markers correctly. Alternative: populate OutboundMessage.media from tool results in the agent loop, no LLM convention needed. Which approach?
   - Options: Content markers (Recommended) | OutboundMessage.media | Both (dual support)
   - **Answer:** Content markers
   - **Rationale:** Zero agent loop changes. Simpler to implement. LLM convention approach is acceptable given the system prompt teaches it explicitly. Can evolve to OutboundMessage.media later if markers prove unreliable.

2. **[Bridge reply]** Phase 01 uses broadcast() (sends to ALL WS clients) for sent/error responses. If multiple nanobot instances connect, all get responses meant for one. Should responses go only to the requesting client?
   - Options: Direct ws.send() (Recommended) | Keep broadcast()
   - **Answer:** Direct ws.send()
   - **Rationale:** Correct multi-client behavior. Use `ws.send()` to reply only to the originating client. `broadcast()` should only be used for incoming Zalo messages that all clients need to see.

3. **[Detection]** The plan has _is_image() helper but the marker type already distinguishes images from files. Should the channel auto-detect image vs file from extension, or trust the LLM's marker choice?
   - Options: Trust LLM marker (Recommended) | Auto-detect from extension
   - **Answer:** Trust LLM marker
   - **Rationale:** Marker type is explicit. Remove unused `_is_image()` and `_IMAGE_EXTENSIONS` to keep code minimal. LLM decides send-image vs send-file.

4. **[Error handling]** What happens if the LLM hallucinates a file path (marker for non-existent file)? Bridge gets an error from zca-js.
   - Options: Log error, send text anyway (Recommended) | Log error + notify user | Fail entire message
   - **Answer:** Log error, send text anyway
   - **Rationale:** Silent degradation. User still gets the text response. Error logged for debugging. No user-facing error noise.

#### Confirmed Decisions
- **Content markers**: Use `[send-image:path]`/`[send-file:path]` markers in LLM output — no agent loop changes
- **Bridge replies**: Use `ws.send()` for sent/error responses, NOT `broadcast()`
- **No _is_image()**: Remove unused helper; trust LLM marker type
- **Graceful media errors**: Log and skip failed media, send text anyway

#### Action Items
- [ ] Phase 01: Change `broadcast()` to `ws.send()` for sent/error responses in bridge handlers
- [ ] Phase 02: Remove `_is_image()` and `_IMAGE_EXTENSIONS` — not needed
- [ ] Phase 02: Ensure `_send_media()` error handling doesn't block text sending

#### Impact on Phases
- Phase 01: Change `broadcast({ type: 'sent' })` and `broadcast({ type: 'error' })` to `ws.send(JSON.stringify(...))` in send-image and send-file handlers
- Phase 02: Remove `_is_image()` static method and `_IMAGE_EXTENSIONS` constant. Simplify code.
