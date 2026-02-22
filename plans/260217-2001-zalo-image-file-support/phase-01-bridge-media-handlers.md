# Phase 01 — ZCA Bridge: Image & File WebSocket Handlers

## Context Links
- Bridge source: `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/src/commands/bridge.ts`
- zca-js send methods: `src/commands/msg/index.ts`
- Plan overview: [plan.md](./plan.md)

## Overview

- **Priority**: P2
- **Status**: complete
- **Effort**: 1.5h
- **Description**: Extend `bridge.ts` to handle two new WebSocket command types — `send-image` and `send-file` — with support for both local file paths and remote URLs.

## Key Insights

- `bridge.ts` already has `api` (logged-in Zalo instance) and a running listener in scope
- `api.sendImage(filePath, threadId, threadType)` — no listener needed, simple call
- `api.sendMessage({ msg: '', attachments: [filePath] }, threadId, threadType)` — needs listener running; it IS running in bridge mode
- URL downloads must be temp-file based: fetch → write → send → delete
- Bridge's `setupClient()` handles incoming WS commands via a `switch`/`if` on `type`; new handlers add cases there

## Requirements

**Functional**
- Handle `{ type: "send-image", to, threadType, filePath? | url? }` — send image to Zalo
- Handle `{ type: "send-file", to, threadType, filePath? | url? , message? }` — send file attachment
- If `url` provided: download to OS temp dir, send, delete temp file
- Respond `{ type: "sent", to, mediaType }` on success — via `ws.send()` to requesting client only (NOT broadcast)
- Respond `{ type: "error", error: "..." }` on failure — via `ws.send()` to requesting client only (NOT broadcast)
<!-- Updated: Validation Session 1 - Changed broadcast() to ws.send() for sent/error responses -->

**Non-functional**
- URL download timeout: 30s
- Log all send attempts and outcomes
- Temp file cleanup must happen even on error (try/finally)

## Architecture

```
WS client (Python zalo.py)
  │  send-image / send-file JSON
  ▼
bridge.ts setupClient()
  ├── downloadToTemp(url) [if url given]
  ├── api.sendImage(path, to, type)   [images]
  │   OR
  ├── api.sendMessage({attachments}, to, type)  [files]
  └── broadcast { type: 'sent' | 'error' }
```

## Related Code Files

**Modify**
- `src/commands/bridge.ts` — add `downloadToTemp()` helper + two new `type` cases in `setupClient()`

**No changes**
- `src/commands/msg/index.ts` — API methods already exist
- `src/lib/api.ts` — imageMetadataGetter already configured

## Implementation Steps

### 1. Add `downloadToTemp` helper (above `setupClient`)

```typescript
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';

async function downloadToTemp(url: string): Promise<string> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status} fetching ${url}`);
    const ext = (url.split('?')[0].split('.').pop() ?? 'bin').slice(0, 10);
    const tmpPath = path.join(os.tmpdir(), `zca-${Date.now()}-${Math.random().toString(36).slice(2)}.${ext}`);
    const buffer = Buffer.from(await res.arrayBuffer());
    fs.writeFileSync(tmpPath, buffer);
    return tmpPath;
  } finally {
    clearTimeout(timeout);
  }
}
```

### 2. Add `send-image` case in `setupClient`

Inside the existing handler where `type === 'send'` is processed, add:

```typescript
} else if (data.type === 'send-image') {
  const { to, threadType = 1, filePath, url } = data;
  let tmpPath: string | null = null;
  try {
    const sendPath = url ? (tmpPath = await downloadToTemp(url)) : filePath;
    if (!sendPath) throw new Error('send-image requires filePath or url');
    await api.sendImage(sendPath, to, threadType);
    ws.send(JSON.stringify({ type: 'sent', to, mediaType: 'image' }));
    console.log(`[bridge] sent image to ${to}`);
  } catch (err: any) {
    console.error(`[bridge] send-image error:`, err.message);
    ws.send(JSON.stringify({ type: 'error', error: err.message }));
  } finally {
    if (tmpPath) fs.unlink(tmpPath, () => {});
  }
}
```

### 3. Add `send-file` case in `setupClient`

```typescript
} else if (data.type === 'send-file') {
  const { to, threadType = 1, filePath, url, message = '' } = data;
  let tmpPath: string | null = null;
  try {
    const sendPath = url ? (tmpPath = await downloadToTemp(url)) : filePath;
    if (!sendPath) throw new Error('send-file requires filePath or url');
    await api.sendMessage({ msg: message, attachments: [sendPath] }, to, threadType);
    ws.send(JSON.stringify({ type: 'sent', to, mediaType: 'file' }));
    console.log(`[bridge] sent file to ${to}`);
  } catch (err: any) {
    console.error(`[bridge] send-file error:`, err.message);
    ws.send(JSON.stringify({ type: 'error', error: err.message }));
  } finally {
    if (tmpPath) fs.unlink(tmpPath, () => {});
  }
}
```

### 4. Verify `fs` import

Ensure `import * as fs from 'fs'` is at the top of `bridge.ts` (add if missing; `os` and `path` similarly).

## Todo List

- [x] Add `os`, `path`, `fs` imports to `bridge.ts` if not already present
- [x] Implement `downloadToTemp()` helper above `setupClient()`
- [x] Add `send-image` handler branch in `setupClient()`
- [x] Add `send-file` handler branch in `setupClient()`
- [x] Manual test: send `{ type: "send-image", to: "...", url: "https://..." }` via wscat
- [x] Manual test: send `{ type: "send-file", to: "...", filePath: "/tmp/test.pdf" }` via wscat
- [x] Confirm temp file is deleted after send

## Success Criteria

- Bridge receives `send-image` WS command and image appears in Zalo chat
- Bridge receives `send-file` WS command and file attachment appears in Zalo chat
- URL downloads resolve to temp file, get cleaned up after send
- Errors produce `{ type: 'error' }` response, do not crash bridge

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `api.sendImage` fails silently on unsupported format | Medium | Log return value; test with jpg/png |
| File attachment upload callback not firing | Low | Listener is running; monitor console output |
| URL download timeout | Low | 30s abort controller; error response sent |
| Large file OOM in buffer | Low | Acceptable for MVP; add size check later if needed |

## Security Considerations

- `filePath` input is passed directly to OS; only the bridge process context can reach this (no external user input path injection concern since the Python side controls what paths are sent)
- Temp files written to OS temp dir, cleaned up immediately; no persistent secrets stored

## Next Steps

- Phase 02: Wire media markers in `nanobot/channels/zalo.py` to emit these WS commands
