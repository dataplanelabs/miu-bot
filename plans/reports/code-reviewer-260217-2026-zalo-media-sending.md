# Code Review: Zalo Image/File Sending Feature

## Scope

- **Files reviewed**: 5 files across 2 repos (nanobot + zca-cli-ts)
  - `nanobot/channels/zalo_media.py` (NEW, 65 lines)
  - `nanobot/channels/zalo.py` (modified)
  - `nanobot/agent/context.py` (modified)
  - `nanobot/agent/loop.py` (modified)
  - `zca-cli-ts/src/commands/bridge.ts` (modified)
- **LOC changed**: ~150 (nanobot) + ~60 (bridge.ts)
- **Focus**: Media marker extraction, WS dispatch, graceful degradation, security

## Overall Assessment

Solid implementation. Clean separation of concerns between `zalo_media.py` (extraction/dispatch) and `zalo.py` (orchestration). The bridge.ts handlers use `ws.send()` correctly (not `broadcast()`), temp files are cleaned up in `finally` blocks, and text-only messages work unchanged. Two bonus improvements were included: `loop.py` graceful shutdown and `commands.py` resilient `asyncio.gather`.

---

## Critical Issues

None.

---

## High Priority

### 1. Path traversal -- no validation on `filePath` in bridge.ts (Security)

**Location**: `zca-cli-ts/src/commands/bridge.ts` lines 84, 100

The bridge accepts `filePath` from the WS client with zero validation. An attacker with WS access (or an LLM injecting a crafted marker) could read arbitrary files:

```typescript
// Current: no validation
const sendPath = url ? (tmpPath = await downloadToTemp(url)) : filePath;
```

The bridge binds to `127.0.0.1` and can require a token, which limits exposure. However, the LLM generates the paths from tool output, and prompt injection could produce `../../../etc/shadow`.

**Recommendation**: Validate `filePath` is absolute, exists, and optionally lives under an allowed directory:

```typescript
if (filePath && !path.isAbsolute(filePath)) throw new Error('filePath must be absolute');
```

**Risk**: Medium. Bridge is localhost-only with optional auth, and Zalo API may reject non-media files. Still worth hardening.

### 2. `downloadToTemp` has no file size limit (Resource)

**Location**: `bridge.ts` line 21

`Buffer.from(await res.arrayBuffer())` loads the entire response into memory. A URL pointing to a multi-GB file would exhaust memory.

**Recommendation**: Add a size check via `Content-Length` header or stream with a byte counter:

```typescript
const maxBytes = 50 * 1024 * 1024; // 50MB
const len = parseInt(res.headers.get('content-length') || '0', 10);
if (len > maxBytes) throw new Error(`File too large: ${len} bytes`);
```

### 3. No confirmation that media was successfully received before sending text

**Location**: `nanobot/channels/zalo.py` lines 126-128

`send_media()` catches errors and logs them but does not propagate failure. If image sending fails silently, the subsequent text message still sends, potentially confusing the user (they see text referencing an image that never arrived).

**Recommendation**: Consider returning a boolean from `send_media()` and optionally prepending a "failed to send image" note to the text. Current behavior (graceful degradation with logging) is acceptable for v1 but worth documenting as a known limitation.

---

## Medium Priority

### 4. Cleaned content has residual double spaces

**Location**: `zalo_media.py` line 42

```python
cleaned = _MEDIA_MARKER_RE.sub("", content).strip()
```

When a marker appears mid-sentence (`Hello [send-image:x.jpg] world`), the result is `Hello  world` with double space.

**Recommendation**: Replace with collapse:

```python
cleaned = re.sub(r"  +", " ", _MEDIA_MARKER_RE.sub("", content)).strip()
```

### 5. Pipe character in URLs causes ambiguous parsing

**Location**: `zalo_media.py` lines 37-40

URLs containing `|` (e.g., `https://example.com/img?filter=blur|sharpen`) are incorrectly split into path + caption. This is very rare in practice and the system prompt instructs the LLM to use a specific format, so risk is low.

**Recommendation**: Acceptable for now. If it becomes an issue, use a different delimiter (e.g., `||`) or only split on the last `|`.

### 6. `send-image` for non-image files has no guard

**Location**: `bridge.ts` line 90

`api.sendImage()` is called regardless of the actual file type. If the LLM mistakenly uses `[send-image:file.pdf]`, the Zalo API might reject it or behave unexpectedly.

**Recommendation**: The zca-js API likely validates this itself. If not, add a file extension check.

### 7. Missing `to` validation in send-image/send-file handlers

**Location**: `bridge.ts` lines 84, 100

Unlike the `send` handler which checks `if (!cmd.to || !cmd.text)`, the media handlers do not explicitly validate `cmd.to` before passing it to the API.

**Recommendation**: Add `if (!to) throw new Error('missing recipient');` at the start of each media handler.

---

## Low Priority

### 8. Outer catch in bridge.ts re-parses `raw` (Fragile)

**Location**: `bridge.ts` line 121

```typescript
warn(`Send failed to=${(JSON.parse(raw.toString())).to}: ${err}`);
```

If this line is reached because `JSON.parse(raw.toString())` originally threw (unlikely since it is already inside a `try` that parsed it), this would throw again. Safer to use a variable captured earlier.

### 9. `normalize_content` moved but not tested

`normalize_content` was moved from `zalo.py` to `zalo_media.py`. The function is identical, but there are no unit tests for this module. No tests exist for the Zalo channel at all (`tests/*zalo*` returns nothing).

---

## Bonus Changes (Not Requested but Included in Diff)

### loop.py -- Graceful shutdown with 30s grace period

The `run()` method now wraps the main loop in `try/finally` with a 30-second grace period for active session workers. This is a good reliability improvement. The logic is correct: `asyncio.wait` returns `(done, pending)`, pending tasks are cancelled.

### commands.py -- `return_exceptions=True` in asyncio.gather

Prevents a channel crash from killing the agent loop. Clean improvement. Error logging iterates results afterward.

Both bonus changes are well-implemented and do not introduce regressions.

---

## Positive Observations

- Clean module split: `zalo_media.py` is focused and under 65 lines
- `normalize_content` reused in both inbound (parsing) and available for future use
- `ws.send()` used correctly for media responses (not `broadcast()`) -- only the requesting client gets the ack
- Temp file cleanup in `finally` blocks prevents disk leaks
- 30s download timeout in `downloadToTemp` prevents hanging
- `[send-image:]` (empty path) correctly produces zero regex matches (the `+` quantifier in `[^\]]+` requires at least one character)
- Media sent before text, with 500ms delay between items -- reasonable ordering
- Text-only flow is unchanged: `extract_media_markers` returns `([], original_text)` for content with no markers
- System prompt clearly instructs the LLM on correct marker format and warns against fabricating paths

## Recommended Actions (Priority Order)

1. Add `to` validation in `send-image`/`send-file` bridge handlers
2. Add file size limit to `downloadToTemp`
3. Collapse double spaces in cleaned content
4. Consider path validation for `filePath` in bridge (at minimum require absolute paths)
5. Add unit tests for `zalo_media.py` (extract_media_markers, normalize_content, send_media)

## Metrics

- Type Coverage: N/A (Python untyped runtime, TypeScript compiles)
- Test Coverage: 0% for new code (no Zalo tests exist)
- Linting Issues: Not run (no Python version available in this environment)

## Unresolved Questions

1. Does `api.sendImage()` in zca-js validate file types, or will it silently fail on non-image files?
2. Is there a maximum file size enforced by the Zalo API itself? If so, `downloadToTemp` could check against that limit.
3. Should media send failures be surfaced to the user via text, or is silent logging sufficient for v1?
