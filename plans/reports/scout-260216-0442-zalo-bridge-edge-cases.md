# Scout Report: Zalo WebSocket Bridge Edge Cases

## Critical Protocol Mismatches

### 1. **threadType Format Inconsistency (CRITICAL BUG)**
**Location:** bridge.ts:48 vs zalo.py:84

- **Bridge expects (incoming):** `cmd.threadType` as **number** (1 or 2)
  - Line 48: `const threadType = cmd.threadType === 2 ? ThreadType.Group : ThreadType.User;`
- **Python sends (outgoing):** `"threadType"` as **number** via `thread_type` variable
  - Line 84: `"threadType": thread_type,` (correctly sends number)
- **Bridge broadcasts (to Python):** `threadType` as **string** ('group' or 'user')
  - Line 106: `threadType: isGroup ? 'group' : 'user',`
- **Python receives:** Expects string, converts to number
  - Line 104-105: `is_group = data.get("threadType") == "group"` then `thread_type = 2 if is_group else 1`

**Verdict:** Protocol works but is inconsistent. Bridge sends string, Python converts to number for storage, sends number back. **Fragile but functional.**

### 2. **Missing Auth Response Validation (HIGH)**
**Location:** zalo.py:42-44

```python
if self.config.bridge_token:
    await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
self._connected = True  # IMMEDIATELY set to True without waiting for auth response!
```

**Issue:** Python client doesn't wait for auth confirmation. Bridge might close connection (line 71-80 in bridge.ts) but Python already marked itself as connected.

**Expected Flow:**
1. Client sends auth → 2. Bridge validates → 3. Bridge sends ack → 4. Client sets `_connected = True`

**Actual Flow:**
1. Client sends auth → 2. Client immediately sets `_connected = True` → 3. Bridge might reject

### 3. **Auth Timeout Race Condition (HIGH)**
**Location:** bridge.ts:71-85

```typescript
const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);
ws.once('message', (data) => {
    clearTimeout(timeout);
    // ...validate auth...
});
```

**Issue:** If Python client has network delay >5s, auth message arrives after timeout fires. Connection closes before `setupClient()` runs.

**Edge Case:** Slow network, bridge under load, or Python sleeping during reconnect attempt.

## Error Handling Gaps

### 4. **Unhandled WebSocket Send Failures (MEDIUM)**
**Location:** zalo.py:86, bridge.ts:36

- **Python:** Catches exception but doesn't retry or queue message
- **Bridge:** No try-catch around `client.send(data)` in broadcast (line 36)

**Impact:** Messages silently dropped if socket is closing or client disconnected mid-send.

### 5. **JSON Parsing Vulnerability (MEDIUM)**
**Location:** bridge.ts:46, 75, zalo.py:93

**Bridge:**
```typescript
const cmd = JSON.parse(raw.toString());  // No schema validation!
if (cmd.type === 'send') {
    await api.sendMessage(cmd.text, cmd.to, threadType);  // cmd.text/to could be undefined
}
```

**Python:**
```python
data = json.loads(raw)  # No schema validation
sender_id = data.get("senderId", "")  # Defaults to empty string - good
content = data.get("content", "")     # Defaults to empty string - good
```

**Issue:** Bridge doesn't validate required fields before using them. If Python sends malformed message, `cmd.text` or `cmd.to` could be undefined → API call fails.

## Resource Cleanup Issues

### 6. **Listener Not Stopped on Disconnect (HIGH)**
**Location:** bridge.ts:96-132

```typescript
const startListener = () => {
    const listener = api.listener;
    listener.on('message', async (msg: Message) => { ... });
    listener.start();
};
```

**Issue:** No `listener.stop()` or event handler cleanup when reconnecting. Each reconnect adds duplicate event handlers → memory leak.

**Expected:** Call `listener.removeAllListeners()` or `listener.stop()` before `scheduleReconnect()`.

### 7. **WebSocket Cleanup on Auth Failure (LOW)**
**Location:** bridge.ts:80, 83

```typescript
ws.close(4003, 'Invalid token');  // Closes connection
```

**Issue:** `clients.delete(ws)` never called for auth failures since `setupClient()` not reached. Harmless since WS closes, but inconsistent state.

## State Synchronization Issues

### 8. **_connected Flag Desync (MEDIUM)**
**Location:** zalo.py:44, 56, 124-126

```python
# Line 44: Set True immediately after sending auth (before validation)
self._connected = True

# Line 56: Set False on exception
self._connected = False

# Line 124-126: Set based on status message from bridge
if status == "connected":
    self._connected = True
```

**Issue:** Three different places update `_connected`:
1. After sending auth (optimistic)
2. On exception (reactive)
3. On status message (correct)

**Race Condition:** If status message arrives while handling exception, flag could be incorrect.

### 9. **Bridge Status Broadcasts to Disconnected Clients (LOW)**
**Location:** bridge.ts:32-39, 118, 124

```typescript
const broadcast = (msg: Record<string, unknown>) => {
    for (const client of clients) {
        if (client.readyState === WebSocket.OPEN) {  // Good: checks readyState
            client.send(data);
        }
    }
};
```

**Issue:** Actually handled correctly with `readyState` check. No bug here.

## Reconnection Logic Bugs

### 10. **Exponential Backoff Without Jitter (LOW)**
**Location:** bridge.ts:134-139

```typescript
reconnectAttempts++;
const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 60000);
```

**Issue:** No jitter. If multiple bridges restart simultaneously (e.g., server reboot), all reconnect at exact same time → thundering herd.

**Recommendation:** Add random jitter: `delay * (0.5 + Math.random() * 0.5)`

### 11. **Python Reconnect Delay Fixed at 5s (LOW)**
**Location:** zalo.py:60-61

```python
if self._running:
    logger.info("Reconnecting in 5 seconds...")
    await asyncio.sleep(5)
```

**Issue:** No exponential backoff. Bridge might be temporarily down → Python hammers it every 5 seconds.

## Missing Null/Undefined Checks

### 12. **Bridge: Undefined Field Access (HIGH)**
**Location:** bridge.ts:49, 101-102, 111

```typescript
// Line 49: No check if cmd.text/cmd.to exist
await api.sendMessage(cmd.text, cmd.to, threadType);

// Line 101-102: m.uidFrom could be undefined
const senderName = getFriendName(m.uidFrom) || m.uidFrom;
const threadName = isGroup ? (getGroupName(m.threadId) || m.threadId) : senderName;

// Line 111: m.data could be undefined
content: m.data?.content || '',  // Good: uses optional chaining
```

**Issue:** `cmd.text` and `cmd.to` not validated before use. Python could send `{"type": "send"}` without these fields → API throws.

### 13. **Python: Missing WebSocket Import Check (LOW)**
**Location:** zalo.py:32

```python
import websockets  # Inside async function - good for lazy import
```

**Issue:** If `websockets` not installed, error happens at runtime not import time. Actually acceptable pattern for optional dependencies.

## Additional Edge Cases

### 14. **No Heartbeat/Ping-Pong (MEDIUM)**
**Issue:** Neither bridge nor Python implements WebSocket ping/pong. Long-idle connections might be dropped by proxies/firewalls without detection.

**Impact:** Silent connection death → messages not received until manual reconnect.

### 15. **Concurrent Send Race (LOW)**
**Location:** zalo.py:86

```python
await self._ws.send(json.dumps(payload))
```

**Issue:** No locking. If multiple async tasks call `send()` simultaneously, messages might interleave (though unlikely with JSON framing).

### 16. **Bridge Token from Env Var Not Logged (LOW)**
**Location:** bridge.ts:18

```typescript
const token = options.token || process.env.ZCA_BRIDGE_TOKEN;
```

**Issue:** If token read from env, no confirmation logged. Debug nightmare if env var typo.

## Relevant Files
- `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/src/commands/bridge.ts` - TypeScript WS bridge server
- `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/zalo.py` - Python WS client channel
- `/Users/vanducng/git/personal/agents/nanobot/nanobot/config/schema.py` - ZaloConfig schema
- `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/manager.py` - Channel initialization
- `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/whatsapp.py` - Reference implementation
- `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/base.py` - Base channel interface

## Summary

**Critical Issues:** 2
- Missing auth response validation (Python assumes success)
- Bridge missing field validation (cmd.text/cmd.to undefined access)

**High Priority:** 3
- Auth timeout race condition (5s might be too short)
- Listener memory leak on reconnect
- Undefined field access in bridge

**Medium Priority:** 5
- State sync issues with `_connected` flag
- No heartbeat mechanism
- Unhandled send failures

**Low Priority:** 6
- Various minor issues (jitter, logging, etc.)

## Unresolved Questions
1. What happens if `api.sendMessage()` throws in bridge.ts:49? No try-catch wraps it.
2. Should Python wait for bridge's "status: connected" message before setting `_connected = True`?
3. Is 5-second auth timeout sufficient for production networks?
4. Should there be message deduplication if reconnect happens during send?
