# Code Review Summary: Zalo WebSocket Bridge Integration

## Scope
- **Files Reviewed:**
  - `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/src/commands/bridge.ts` (NEW - 144 LOC)
  - `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/zalo.py` (NEW - 130 LOC)
  - `/Users/vanducng/git/personal/agents/nanobot/nanobot/config/schema.py` (MODIFIED - ZaloConfig added)
  - `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/manager.py` (MODIFIED - zalo init added)
- **LOC:** ~280 new lines (TypeScript + Python)
- **Focus:** Protocol correctness, security, edge cases
- **Scout Findings:** 16 edge cases identified (2 critical, 3 high, 5 medium, 6 low)

## Overall Assessment

The Zalo WebSocket bridge integration follows the established WhatsApp bridge pattern closely but contains **several critical bugs** that will cause failures in production:

1. **Auth flow broken** - Python assumes success without waiting for bridge confirmation
2. **Missing input validation** - Bridge doesn't validate required fields before API calls
3. **Memory leak** - Zalo listener event handlers accumulate on reconnects
4. **Protocol inconsistency** - threadType uses mixed number/string types (works but fragile)

**Recommendation:** Fix critical/high issues before deployment. Code is structurally sound but needs defensive programming.

---

## Critical Issues

### 1. **Broken Authentication Flow** ⚠️
**File:** `nanobot/channels/zalo.py:42-45`

**Problem:**
```python
if self.config.bridge_token:
    await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
self._connected = True  # ❌ IMMEDIATELY sets True without waiting for response
logger.info("Connected to Zalo bridge")
```

**Impact:**
- Python marks itself connected before bridge validates auth
- If bridge rejects token (bridge.ts:80), connection closes but Python thinks it's connected
- Subsequent `send()` calls fail silently with "bridge not connected" warning

**Root Cause:** Missing await for auth acknowledgment message from bridge.

**Fix Required:**
```python
if self.config.bridge_token:
    await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
    # Wait for first message (should be status or auth response)
    auth_response = await asyncio.wait_for(ws.recv(), timeout=10.0)
    data = json.loads(auth_response)
    if data.get("type") == "error" or data.get("status") == "disconnected":
        raise Exception(f"Auth failed: {data.get('error', 'rejected')}")
self._connected = True
```

**Alternative:** Rely on "status: connected" message (line 124) and don't set `_connected` until received.

---

### 2. **Missing Input Validation in Bridge** ⚠️
**File:** `zca-cli-ts/src/commands/bridge.ts:46-50`

**Problem:**
```typescript
const cmd = JSON.parse(raw.toString());
if (cmd.type === 'send') {
    const threadType = cmd.threadType === 2 ? ThreadType.Group : ThreadType.User;
    await api.sendMessage(cmd.text, cmd.to, threadType);  // ❌ No validation
    ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
}
```

**Impact:**
- If Python sends `{"type": "send", "threadType": 1}` without `text` or `to`:
  - `cmd.text` = undefined → Zalo API throws error
  - `cmd.to` = undefined → API throws error
  - Error caught by outer try-catch (line 52) but sent to client as string
- No schema enforcement allows malformed messages

**Fix Required:**
```typescript
if (cmd.type === 'send') {
    if (!cmd.text || !cmd.to || typeof cmd.threadType !== 'number') {
        ws.send(JSON.stringify({
            type: 'error',
            error: 'Missing required fields: text, to, threadType'
        }));
        return;
    }
    const threadType = cmd.threadType === 2 ? ThreadType.Group : ThreadType.User;
    await api.sendMessage(cmd.text, cmd.to, threadType);
    ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
}
```

---

## High Priority

### 3. **Memory Leak: Listener Event Handlers Accumulate**
**File:** `bridge.ts:95-132`

**Problem:**
```typescript
const startListener = () => {
    const listener = api.listener;

    listener.on('message', async (msg: Message) => { ... });  // ❌ Adds handler
    listener.on('error', (err: unknown) => { ... });          // ❌ Adds handler
    listener.on('closed', () => { ... });                     // ❌ Adds handler

    listener.start();
};

const scheduleReconnect = () => {
    // ...
    setTimeout(startListener, delay);  // ❌ Calls startListener again without cleanup
};
```

**Impact:**
- Each reconnect adds 3 new event handlers
- After 10 reconnects: 30 handlers → each message triggers 10 duplicate broadcasts
- Memory leak grows unbounded

**Fix Required:**
```typescript
const startListener = () => {
    const listener = api.listener;

    // Remove old handlers before adding new ones
    listener.removeAllListeners('message');
    listener.removeAllListeners('error');
    listener.removeAllListeners('closed');

    listener.on('message', async (msg: Message) => { ... });
    listener.on('error', (err: unknown) => { ... });
    listener.on('closed', () => { ... });

    listener.start();
};
```

---

### 4. **Auth Timeout Too Aggressive**
**File:** `bridge.ts:71`

**Problem:**
```typescript
const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);  // 5 seconds
```

**Impact:**
- 5s timeout might be too short for:
  - Slow networks
  - Bridge under heavy load
  - Container cold starts
- Python has no retry mechanism if auth times out

**Recommendation:**
- Increase to 10-15 seconds for production
- Or make configurable via env var: `parseInt(process.env.AUTH_TIMEOUT_MS || '10000')`

---

### 5. **No Error Handling for API sendMessage**
**File:** `bridge.ts:49`

**Problem:**
```typescript
await api.sendMessage(cmd.text, cmd.to, threadType);  // ❌ No try-catch
```

**Impact:**
- If Zalo API throws (network error, rate limit, invalid recipient):
  - Outer try-catch (line 52) catches it
  - Sends generic error to client: `{ type: 'error', error: String(err) }`
  - No retry, no logging, no telemetry

**Current Behavior:** Actually caught by outer try-catch, so not a crash bug. But error response is poor quality.

**Improvement:**
```typescript
try {
    await api.sendMessage(cmd.text, cmd.to, threadType);
    ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
} catch (err) {
    error(`Failed to send message: ${err}`);
    ws.send(JSON.stringify({
        type: 'error',
        error: err instanceof Error ? err.message : String(err),
        code: 'SEND_FAILED'
    }));
}
```

---

## Medium Priority

### 6. **State Synchronization: Multiple Sources of Truth**
**File:** `zalo.py:44, 56, 66, 124-126`

**Problem:**
`_connected` flag updated in 4 different places:
1. Line 44: Optimistically set after sending auth
2. Line 56: Set False on exception
3. Line 66: Set False in stop()
4. Line 124-126: Set based on status message from bridge

**Issue:** Race condition if status message arrives during exception handling.

**Recommendation:** Use single source of truth:
```python
# Only set _connected based on status messages from bridge
# Remove line 44, keep exception handling and stop() cleanup
```

---

### 7. **threadType Protocol Inconsistency**
**Files:** `bridge.ts:48, 106` vs `zalo.py:84, 104-105`

**Current Protocol:**
- **Python → Bridge (send):** `"threadType": 2` (number)
- **Bridge → Python (message):** `"threadType": "group"` (string)
- **Python converts:** string → number for storage, number → number for send

**Issue:** Inconsistent but functional. String-to-number conversion fragile.

**Recommendation:** Standardize on numbers (1=User, 2=Group) in both directions:
```typescript
// bridge.ts:106 - Change to number
broadcast({
    type: 'message',
    threadType: isGroup ? 2 : 1,  // Send number instead of string
    // ...
});
```

```python
# zalo.py:104-105 - Simplify
thread_type = data.get("threadType", 1)  # Direct number
is_group = thread_type == 2
```

---

### 8. **No WebSocket Heartbeat/Ping-Pong**

**Problem:** Neither bridge nor Python implements WebSocket ping/pong frames.

**Impact:**
- Long-idle connections dropped by proxies/NAT gateways
- No detection of silent connection death
- Messages queued but never delivered until manual activity triggers reconnect

**Recommendation:**
```python
# zalo.py - Add ping task
async def _ping_loop(self, ws):
    while self._connected:
        await asyncio.sleep(30)
        try:
            await ws.ping()
        except Exception:
            break
```

```typescript
// bridge.ts - Enable ws server ping
const wss = new WebSocketServer({
    host: '127.0.0.1',
    port,
    clientTracking: true
});

// Ping clients every 30s
setInterval(() => {
    wss.clients.forEach(ws => {
        if (ws.readyState === WebSocket.OPEN) {
            ws.ping();
        }
    });
}, 30000);
```

---

### 9. **Unhandled WebSocket Send Failures**
**Files:** `bridge.ts:36`, `zalo.py:86`

**Bridge:**
```typescript
client.send(data);  // ❌ No error handling
```

**Python:**
```python
await self._ws.send(json.dumps(payload))  # Caught by outer try-catch but message lost
```

**Impact:** Messages silently dropped if socket closing or backpressure.

**Fix:**
```typescript
try {
    client.send(data);
} catch (err) {
    warn(`Failed to send to client: ${err}`);
    clients.delete(client);  // Remove dead client
}
```

---

### 10. **No Message Deduplication on Reconnect**

**Scenario:**
1. Python sends message → Bridge receives
2. Bridge calls `api.sendMessage()` (slow async operation)
3. Connection drops before bridge sends `{type: 'sent'}` response
4. Python reconnects, retries message (if implemented)
5. User receives duplicate message

**Current Behavior:** No retry in Python, so duplicates unlikely. But also means messages lost on disconnect.

**Recommendation:** Add message IDs for deduplication or accept "at most once" delivery semantics (current behavior).

---

## Low Priority

### 11. **Python Reconnect: No Exponential Backoff**
**File:** `zalo.py:60-61`

**Current:** Fixed 5-second delay
**Recommendation:** Match WhatsApp pattern or add exponential backoff:
```python
reconnect_delay = 5
while self._running:
    try:
        # ... connection logic ...
        reconnect_delay = 5  # Reset on success
    except Exception as e:
        self._connected = False
        if self._running:
            logger.info(f"Reconnecting in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)  # Cap at 60s
```

---

### 12. **Bridge Reconnect: No Jitter**
**File:** `bridge.ts:136`

**Current:**
```typescript
const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 60000);
```

**Issue:** All bridges restarting simultaneously reconnect at exact same time (thundering herd).

**Fix:**
```typescript
const baseDelay = Math.min(1000 * Math.pow(2, reconnectAttempts), 60000);
const delay = baseDelay * (0.5 + Math.random() * 0.5);  // +/- 25% jitter
```

---

### 13. **Auth Failure: Client Not Removed from Set**
**File:** `bridge.ts:80, 83`

**Issue:**
```typescript
ws.close(4003, 'Invalid token');  // Closes connection but clients.delete(ws) never called
```

**Impact:** Harmless (socket closes anyway) but inconsistent state.

**Fix:**
```typescript
ws.close(4003, 'Invalid token');
clients.delete(ws);  // Clean up explicitly
```

---

### 14. **No Logging for Env Var Token**
**File:** `bridge.ts:18`

**Issue:**
```typescript
const token = options.token || process.env.ZCA_BRIDGE_TOKEN;
```

If token read from env, no confirmation logged. Hard to debug typos.

**Fix:**
```typescript
const token = options.token || process.env.ZCA_BRIDGE_TOKEN;
if (token && !options.token) {
    info('Using token from ZCA_BRIDGE_TOKEN env var');
}
```

---

### 15. **Config: ZaloConfig Mirrors WhatsAppConfig Exactly**
**File:** `schema.py:16-22`

**Observation:** Perfect copy-paste of WhatsAppConfig (expected for consistency).

**Recommendation:** Consider shared base class to enforce consistency:
```python
class BridgeChannelConfig(BaseModel):
    """Base config for bridge-based channels (WhatsApp, Zalo, etc.)."""
    enabled: bool = False
    bridge_url: str
    bridge_token: str = ""
    allow_from: list[str] = Field(default_factory=list)

class WhatsAppConfig(BridgeChannelConfig):
    bridge_url: str = "ws://localhost:3001"

class ZaloConfig(BridgeChannelConfig):
    bridge_url: str = "ws://localhost:3002"
```

---

### 16. **Channel Manager: Zalo Init Identical to WhatsApp**
**File:** `manager.py:50-59`

**Code:**
```python
if self.config.channels.zalo.enabled:
    try:
        from nanobot.channels.zalo import ZaloChannel
        self.channels["zalo"] = ZaloChannel(
            self.config.channels.zalo, self.bus
        )
        logger.info("Zalo channel enabled")
    except ImportError as e:
        logger.warning(f"Zalo channel not available: {e}")
```

**Assessment:** Perfect. Follows established pattern. No issues.

---

## Edge Cases Found by Scout

*See full scout report: `/Users/vanducng/git/personal/agents/nanobot/plans/reports/scout-260216-0442-zalo-bridge-edge-cases.md`*

**Key Findings:**
1. Auth response not validated (Critical #1)
2. Missing field validation (Critical #2)
3. Listener memory leak (High #3)
4. Auth timeout race (High #4)
5. threadType inconsistency (Medium #7)
6. No heartbeat mechanism (Medium #8)
7. State sync issues (Medium #6)
8. Plus 9 lower-priority edge cases

---

## Positive Observations

✅ **Good Architecture:**
- Follows WhatsApp bridge pattern consistently
- Clean separation: TypeScript handles Zalo protocol, Python handles bot logic
- Proper use of WebSocket reconnection loops

✅ **Good Error Handling (mostly):**
- Python catches JSON parse errors (line 94)
- Bridge catches message handling errors (line 52)
- Proper cleanup in stop() methods

✅ **Good Defaults:**
- Python uses `.get()` with defaults for optional fields (line 101-114)
- Bridge uses optional chaining for `m.data?.content` (line 111)
- Localhost-only binding for security (bridge.ts:66)

✅ **Good Logging:**
- Informative log messages for connection state changes
- Warning for auth denials (inherited from BaseChannel)

---

## Recommended Actions

**Before Deployment (BLOCKING):**

1. **Fix Auth Flow** (Critical #1)
   - Python must wait for auth acknowledgment before setting `_connected = True`
   - Add 10s timeout with proper error handling

2. **Add Input Validation** (Critical #2)
   - Bridge must validate `cmd.text`, `cmd.to`, `cmd.threadType` before API call
   - Return proper error messages for missing fields

3. **Fix Listener Memory Leak** (High #3)
   - Call `listener.removeAllListeners()` before re-adding handlers
   - Test with multiple reconnects to verify fix

**After Deployment (HIGH):**

4. **Increase Auth Timeout** (High #4)
   - Change from 5s to 10-15s or make configurable

5. **Add WebSocket Heartbeat** (Medium #8)
   - Implement ping/pong to detect dead connections
   - 30-second interval recommended

6. **Standardize threadType Protocol** (Medium #7)
   - Use numbers (1/2) in both directions
   - Remove string conversion logic

**Nice to Have:**

7. Add exponential backoff to Python reconnect (Low #11)
8. Add jitter to bridge reconnect (Low #12)
9. Add message retry/deduplication (Medium #10)
10. Refactor config to shared base class (Low #15)

---

## Metrics

- **Type Coverage:** N/A (TypeScript fully typed, Python uses type hints)
- **Test Coverage:** 0% (no tests found)
- **Linting Issues:** 0 (Python syntax validated)
- **Security Issues:** 1 (localhost-only binding - acceptable for bridge architecture)
- **Protocol Bugs:** 2 critical, 3 high priority

---

## Unresolved Questions

1. **What is the expected behavior if `api.sendMessage()` fails?** Should bridge queue and retry, or just report error to client?

2. **Should auth timeout be configurable?** Different deployment environments (local dev vs cloud) need different values.

3. **Is "at most once" delivery acceptable?** Current design loses messages on disconnect. Should there be persistence/retry?

4. **How should concurrent sends be handled?** Multiple async tasks calling `send()` might interleave. Need mutex?

5. **What's the keepAlive flag behavior?** Bridge has `--keep-alive` option but it's not tested. Does it work correctly with listener cleanup?

6. **Should there be rate limiting?** Bridge broadcasts every Zalo message to all clients. High-volume chats could overwhelm clients.

---

## Conclusion

**Code Quality:** B- (structurally sound, follows patterns, but has critical bugs)

**Readiness:** NOT READY for production until Critical #1 and #2 are fixed.

The implementation correctly mirrors the WhatsApp bridge architecture but introduces bugs in the authentication flow and input validation. The memory leak in listener handlers will cause performance degradation over time.

**Estimated Fix Time:** 2-4 hours for critical issues, 1 day for all high-priority issues.

**Next Steps:**
1. Fix critical auth and validation bugs
2. Write integration tests for reconnection scenarios
3. Test with flaky network conditions (use `tc` or `toxiproxy`)
4. Deploy to staging with monitoring
