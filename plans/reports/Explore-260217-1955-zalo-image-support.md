# Zalo Channel Image Support Research Report

**Date:** 2026-02-17  
**Research Scope:** Nanobot Zalo channel + ZCA CLI TypeScript bridge  
**Status:** Complete

---

## Executive Summary

**Current Status:** Image sending is NOT supported in Nanobot's Zalo channel, despite the underlying ZCA CLI (zca-js) having full image support.

**Key Finding:** The WebSocket bridge between nanobot and ZCA CLI only handles text messages. A gap exists between what the underlying API supports and what nanobot exposes.

---

## 1. Nanobot Zalo Channel - Image Support Analysis

### Current Implementation
**File:** `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/zalo.py`

#### Outbound Message Handling (Lines 124-154)
```python
async def send(self, msg: OutboundMessage) -> None:
    """Send a message through Zalo, splitting long content into multiple messages."""
    self._stop_typing(msg.chat_id)

    if not self._ws or not self._connected:
        logger.warning("Zalo bridge not connected")
        return

    try:
        # Use metadata thread_type, fall back to cached type from received messages
        if msg.metadata and msg.metadata.get("thread_type"):
            thread_type = msg.metadata["thread_type"]
        else:
            thread_type = self._thread_types.get(msg.chat_id, 1)
        chunks = self._split_message(msg.content, self.ZALO_MAX_CHARS)

        for chunk in chunks:
            payload = {
                "type": "send",
                "to": msg.chat_id,
                "text": chunk,  # <-- ONLY TEXT, NO MEDIA SUPPORT
                "threadType": thread_type,
            }
            await self._ws.send(json.dumps(payload))
```

**Issue:** The payload only includes `"text"` field. No media, image, or file fields are sent.

#### OutboundMessage Definition
**File:** `/Users/vanducng/git/personal/agents/nanobot/nanobot/bus/events.py`

```python
@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""
    
    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)  # <-- EXISTS BUT UNUSED
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Key Point:** The `media` field IS defined but is NEVER used in the Zalo channel's `send()` method.

#### InboundMessage Handling
The Zalo bridge only parses `content` from messages (line 203):
```python
content = normalize_content(data.get("content"))
```

No support for receiving images or attachments from Zalo.

### Other Channels for Comparison

**Telegram** (`telegram.py`, lines 181-217): 
- Has text message sending ✓
- NO implementation for sending `msg.media` to Telegram
- BUT can RECEIVE photos, voice, audio, documents (lines 272-283)
- Downloads incoming media to `~/.nanobot/media/`
- Never sends media back

**Discord** (`discord.py`, lines 75-107):
- Send method only handles text content via REST API
- No media support in send method

**Conclusion:** No channel currently implements outbound media sending. Nanobot's architecture defines media support for inbound only.

---

## 2. ZCA CLI Bridge - What's Available

### Bridge WebSocket Protocol
**File:** `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/src/commands/bridge.ts`

#### Current Bridge Implementation (Lines 54-68)
```typescript
ws.on('message', async (raw) => {
  try {
    const cmd = JSON.parse(raw.toString());
    if (cmd.type === 'send') {
      if (!cmd.to || !cmd.text) {
        ws.send(JSON.stringify({ type: 'error', error: 'Missing required fields: to, text' }));
        return;
      }
      const threadType = cmd.threadType === 2 ? ThreadType.Group : ThreadType.User;
      info(`Sending to ${cmd.to} (${cmd.threadType === 2 ? 'group' : 'user'})`);
      await api.sendMessage(cmd.text, cmd.to, threadType);  // <-- ONLY TEXT
      ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
    } else if (cmd.type === 'typing') {
      // ... typing indicator
    }
  } catch (err) {
    // ... error handling
  }
});
```

**Current Bridge Capabilities:**
- `type: 'send'` - text messages only
- `type: 'typing'` - typing indicator
- No support for images, files, or other media types

**CRITICAL GAP:** The bridge doesn't expose image sending, despite zca-js supporting it.

---

## 3. ZCA CLI Actual Capabilities

### Supported Commands
**File:** `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/src/commands/msg/index.ts`

The ZCA CLI has **FULL media support** via dedicated commands:

#### Image Command (Lines 160-187)
```typescript
msgCommands
  .command('image')
  .description('Send an image')
  .argument('<threadId>', 'User or group ID')
  .argument('[file]', 'Path to image file')
  .option('-g, --group', 'Send to group')
  .action(
    wrapAction(async (threadId: string, file: string | undefined, options: { group?: boolean }) => {
      if (!file) {
        error('Please provide a file path');
        return;
      }

      if (!fs.existsSync(file)) {
        error(`File not found: ${file}`);
        return;
      }

      const api = await getApi();
      const type = options.group ? ThreadType.Group : ThreadType.User;

      const spin = spinner('Sending image...');
      spin.start();

      await api.sendImage(file, threadId, type);  // <-- NATIVE SUPPORT
      spin.stop();
      success('Image sent!');
    })
  );
```

#### Video Command (Lines 130-157)
```typescript
.command('video')
.description('Send a video')
// ... uses api.sendVideo()
```

#### Voice/Audio Command (Lines 62-127)
```typescript
.command('voice')
.description('Send a voice message')
// ... uses api.sendVoice() or api.uploadAttachment()
```

#### File Upload Command (Lines 351-433)
```typescript
.command('upload')
.description('Send a file (PDF, document, image, etc.) as attachment')
// ... uses api.sendMessage({ msg, attachments: [file] })
```

### Underlying API Methods Available
The `api` object (from `zca-js` library) provides:
- `api.sendImage(file, threadId, type)` ✓
- `api.sendVideo(file, threadId, type)` ✓
- `api.sendVoice({ voiceUrl }, threadId, type)` ✓
- `api.uploadAttachment(file, threadId, type)` ✓
- `api.sendMessage({ msg, attachments: [...] }, threadId, type)` ✓

**Version:** `zca-js@2.0.4` (from package.json, line 44)

---

## 4. What's Needed for Zalo Image Support

### Option A: Extend Bridge Protocol (Recommended)

The WebSocket bridge needs new message types:

```
Current:  { type: "send", to: "threadId", text: "...", threadType: 1 }
New:      { type: "send-image", to: "threadId", file: "...", threadType: 1 }
New:      { type: "send-video", to: "threadId", file: "...", threadType: 1 }
New:      { type: "send-file", to: "threadId", file: "...", threadType: 1 }
```

**Bridge Changes Required:**
1. Update `bridge.ts` to handle new message types
2. Call appropriate `api.sendImage()`, `api.sendVideo()`, etc.
3. Handle file validation and error cases

**Nanobot Changes Required:**
1. Extend Zalo channel `send()` method to handle `msg.media` field
2. Detect media type (image, video, file) from URL or metadata
3. Send appropriate bridge command
4. Handle async file uploads if needed

### Option B: File Upload Service (More Complex)

Create an HTTP endpoint where nanobot uploads files, bridge downloads them, then sends.
- **Pro:** Handles large files better
- **Con:** Extra infrastructure complexity

### Option C: Direct File Paths (Simplest)

If files are already on the bridge server's filesystem:
```json
{ type: "send-image", to: "threadId", filePath: "/path/to/image.jpg", threadType: 1 }
```
- **Pro:** Simple, no file transfer needed
- **Con:** Limited to local files on bridge server

---

## 5. Detailed Implementation Checklist

### Phase 1: Bridge Protocol Extension
- [ ] Extend `bridge.ts` message handler for new types:
  - [ ] `send-image` type
  - [ ] `send-video` type  
  - [ ] `send-file` type
- [ ] Implement error handling for missing/invalid files
- [ ] Add response confirmation (success/failure feedback)
- [ ] Update bridge documentation

### Phase 2: Nanobot Zalo Channel Update
- [ ] Modify `zalo.py` `send()` method to check for `msg.media`
- [ ] Add media type detection (image, video, file based on file extension)
- [ ] Build appropriate bridge command based on media type
- [ ] Handle file validation (file exists, is readable)
- [ ] Implement async file transfer mechanism if needed
- [ ] Add error handling and logging

### Phase 3: Agent Loop Integration
- [ ] Ensure `AgentLoop` populates media field in `OutboundMessage`
- [ ] Add LLM tool support for "send image", "send video" actions
- [ ] Test end-to-end from LLM response to Zalo delivery

### Phase 4: Testing & Documentation
- [ ] Update setup-zalo-guide.md with image sending examples
- [ ] Add bridge protocol documentation
- [ ] Test with various file types (JPG, PNG, MP4, etc.)
- [ ] Test in both DM and group contexts

---

## 6. MCP Tool Considerations

**File:** `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/tools/mcp.py`

The MCP tool wrapper can expose external tools. For image sending:
- Could create MCP server for image handling (encode/decode, download, etc.)
- Agent could use MCP tools to fetch image URLs, then send to Zalo
- Not required for basic implementation, but useful for advanced features

---

## 7. Comparison Matrix

| Feature | ZCA CLI | Bridge | Nanobot Zalo |
|---------|---------|--------|-------------|
| Send Text | ✓ | ✓ | ✓ |
| Send Image | ✓ | ✗ | ✗ |
| Send Video | ✓ | ✗ | ✗ |
| Send File | ✓ | ✗ | ✗ |
| Receive Text | ✓ | ✓ | ✓ |
| Receive Image | ✓ | ✗ | ✗ |
| Typing Indicator | ✓ | ✓ | ✓ |
| Group Support | ✓ | ✓ | ✓ |
| DM Support | ✓ | ✓ | ✓ |

---

## 8. Key Code Locations

### Nanobot
- **Zalo Channel:** `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/zalo.py`
- **Message Types:** `/Users/vanducng/git/personal/agents/nanobot/nanobot/bus/events.py`
- **Agent Loop:** `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/loop.py` (line 398 shows media handling)
- **Setup Guide:** `/Users/vanducng/git/personal/agents/nanobot/docs/setup-zalo-guide.md`

### ZCA CLI
- **Bridge Server:** `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/src/commands/bridge.ts`
- **Message Commands:** `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/src/commands/msg/index.ts`
- **API Library:** `zca-js@2.0.4` (node_modules)

---

## 9. Unresolved Questions

1. **File Transfer Mechanism:** Should bridge accept base64-encoded files, local paths, or URLs?
2. **LLM Integration:** Should agent learn to call image sending tools, or should this be transparent?
3. **Image Generation:** Should nanobot integrate with image generation APIs (DALL-E, etc.)?
4. **File Size Limits:** What's the maximum file size for Zalo images/videos?
5. **Concurrent Uploads:** Should bridge handle multiple file uploads in parallel?

---

## Recommendations

1. **Start with Phase 1:** Extend bridge protocol to support image sending
   - Lowest risk, maximum compatibility with existing code
   - Re-uses zca-js capabilities directly
   
2. **Support Local Files First:** Image files from agent's workspace directory
   - No external dependencies
   - Fast implementation
   - Can upgrade to URLs/base64 later

3. **Add Telemetry:** Log all image sends for debugging
   - File size, format, duration
   - Success/failure rates

4. **Document Thoroughly:** Update setup guide with examples
   - How to trigger image sends via chat
   - Supported formats and size limits
