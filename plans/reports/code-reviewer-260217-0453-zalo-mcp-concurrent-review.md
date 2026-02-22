# Code Review: Zalo Channel, MCP Improvements, Concurrent Processing

**Reviewer**: code-reviewer
**Date**: 2026-02-17
**Commit range**: Uncommitted changes on `main`

---

## Scope

- **Files**: 11 modified + 1 new (`nanobot/channels/zalo.py`)
- **LOC changed**: ~327 added, ~65 removed
- **Focus**: Security, race conditions, resource leaks, error handling, edge cases

### Files Reviewed

| File | Summary |
|------|---------|
| `nanobot/agent/context.py` | Zalo formatting rules in system prompt |
| `nanobot/agent/loop.py` | Per-session concurrent workers, observe-only, group identity, LLM timeout, verbose logging |
| `nanobot/agent/tools/mcp.py` | HTTP headers, param filtering, timeout, CancelledError handling |
| `nanobot/bus/events.py` | `observe_only` field on InboundMessage |
| `nanobot/channels/base.py` | `observe_only` parameter passthrough |
| `nanobot/channels/manager.py` | Zalo channel registration |
| `nanobot/channels/telegram.py` | Message splitting at 4096 chars |
| `nanobot/channels/zalo.py` (NEW) | Full Zalo WS bridge channel |
| `nanobot/cli/commands.py` | Loguru verbose configuration |
| `nanobot/config/loader.py` | Passthrough keys for env/headers |
| `nanobot/config/schema.py` | ZaloConfig, MCP headers field |
| `nanobot/providers/litellm_provider.py` | Direct HTTP fallback for non-standard APIs |

---

## Overall Assessment

Solid, pragmatic changes. The per-session concurrent processing is a meaningful architecture improvement. The Zalo channel follows established patterns (mirrors WhatsApp bridge). The MCP and LiteLLM improvements add resilience. Most issues found are medium-severity edge cases rather than critical flaws.

---

## Critical Issues

### C1. MCP HTTP client resource leak

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/tools/mcp.py`, lines 82-85

```python
if cfg.headers:
    import httpx
    http_client = httpx.AsyncClient(headers=cfg.headers)
```

The `httpx.AsyncClient` is created but never explicitly closed. It is not entered into the `AsyncExitStack`. If the MCP connection is torn down, this client's connection pool and file descriptors leak.

**Impact**: Resource leak over time; file descriptor exhaustion on long-running gateways.

**Fix**: Register the client's lifecycle with the stack:

```python
if cfg.headers:
    import httpx
    http_client = httpx.AsyncClient(headers=cfg.headers)
    stack.push_async_close(http_client)
```

Or use `stack.enter_async_context(httpx.AsyncClient(...))`.

---

### C2. Shared tool context across concurrent sessions (race condition)

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/loop.py`, line 373

```python
self._set_tool_context(msg.channel, msg.chat_id)
```

`_set_tool_context` mutates shared, singleton tool instances (`MessageTool`, `SpawnTool`, `CronTool`) with the current channel/chat_id. With the new per-session concurrent workers, two sessions can race on this state:

1. Session A calls `_set_tool_context("telegram", "123")`
2. Session B calls `_set_tool_context("zalo", "456")` before A's LLM loop finishes
3. Session A's tool call now sends the response to Zalo:456 instead of Telegram:123

**Impact**: Messages routed to the wrong user/channel. Data leakage between sessions.

**Fix**: Either (a) make tool context per-session by cloning tools per worker, or (b) pass channel/chat_id through the tool execution call rather than mutating shared state. A minimal fix would be to store context as a `contextvars.ContextVar` or pass it as an argument to `execute()`.

---

## High Priority

### H1. Session/SessionManager not thread-safe for concurrent access

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/session/manager.py`

`SessionManager._cache` is a plain dict. With concurrent session workers, two workers for the same session key (possible if a worker times out and a new one is created before cleanup) could race on `get_or_create` / `save` / `add_message`. The `Session.messages` list is also mutated without synchronization.

Currently mitigated by the per-session sequential processing model (one worker per key), but if a worker exits (idle timeout) while a new message arrives for the same key, there is a brief window where two workers could exist for the same key.

**Impact**: Potential data corruption of session history.

**Mitigation**: The window is small because the `run()` method only creates a new worker if `key not in self._session_queues`, and cleanup only happens during `TimeoutError` ticks. However, there is a race: the idle worker exits and the cleanup tick has not yet run, so the old key is still in `_session_queues`, but the old `_session_tasks[key]` is `done()`. A new message for that key would be put into the old queue, which nobody is reading.

**Fix**: In `run()`, check if the task is done before deciding to reuse:

```python
if key not in self._session_queues or self._session_tasks[key].done():
    self._session_queues[key] = asyncio.Queue()
    self._session_tasks[key] = asyncio.create_task(
        self._session_worker(key)
    )
```

### H2. Telegram message splitting breaks mid-entity

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/telegram.py`, line 199

```python
chunks = [content[i:i + max_len] for i in range(0, len(content), max_len)]
```

This splits at hard character boundaries, potentially breaking markdown/HTML entities mid-tag (e.g., splitting `**bold text**` into `**bold te` and `xt**`). The `_markdown_to_telegram_html` conversion then runs on each broken fragment, producing invalid HTML that falls through to the plain-text fallback.

**Impact**: Formatting corruption for long messages. The fallback to plain text mitigates data loss but degrades UX.

**Fix**: Use the same boundary-aware splitting strategy from Zalo (`_split_message` with paragraph/newline boundaries). Consider extracting a shared `split_message()` utility.

### H3. Direct HTTP fallback leaks API key in error messages

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/providers/litellm_provider.py`, line 168

```python
logger.error(f"Direct HTTP fallback also failed: {fallback_err}")
```

If the HTTP request fails with a `httpx.HTTPStatusError`, the error includes the request URL and headers (including `Authorization: Bearer <key>`). This gets written to logs.

**Impact**: API key exposure in log files.

**Fix**: Catch and sanitize the error before logging:

```python
except Exception as fallback_err:
    err_msg = str(fallback_err).split('\n')[0][:200]
    logger.error(f"Direct HTTP fallback also failed: {type(fallback_err).__name__}: {err_msg}")
```

### H4. `_direct_chat` uses hardcoded `/chat/completions` path

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/providers/litellm_provider.py`, line 179

```python
url = f"{self.api_base.rstrip('/')}/chat/completions"
```

Some providers use api_base URLs that already include `/v1` or the full path (e.g., `https://api.example.com/v1`). Appending `/chat/completions` blindly could produce `https://api.example.com/v1/chat/completions` (correct) or `https://api.example.com/v1/chat/completions/chat/completions` (wrong, if api_base already includes the endpoint path).

**Impact**: Fallback silently fails for some provider configurations.

**Fix**: Check if api_base already ends with `/chat/completions` before appending.

---

## Medium Priority

### M1. Observe-only messages bypass content validation

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/loop.py`, lines 332-337

```python
if msg.observe_only:
    sender_name = (msg.metadata or {}).get("sender_name", msg.sender_id)
    session.add_message("user", f"[{sender_name} (userId: {msg.sender_id})]: {content}")
```

Observe-only messages are added directly to session history. If `sender_name` or `content` contain LLM injection patterns (e.g., "Ignore all previous instructions..."), they get injected into the conversation context without any sanitization.

**Impact**: Prompt injection via observed group messages. Any group member can influence the LLM's behavior for the entire session.

**Mitigation**: This is an inherent risk of observing group messages. Consider adding a disclaimer in the system prompt that observed messages come from untrusted third parties, or wrapping them in a clearly delineated block.

### M2. Zalo `_typing_loop` silently swallows all exceptions

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/zalo.py`, lines 102-114

```python
async def _typing_loop(self, chat_id: str, thread_type: int) -> None:
    try:
        while True:
            ...
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
```

All exceptions are silently caught, including WebSocket disconnection errors that should trigger reconnection logic. If the WebSocket dies, the typing loop will silently spin forever, sending to a dead socket.

**Fix**: Log the exception and break:

```python
except Exception as e:
    logger.debug(f"Typing loop for {chat_id} stopped: {e}")
```

### M3. Zalo `stop()` does not cancel typing tasks

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/zalo.py`, lines 81-87

```python
async def stop(self) -> None:
    self._running = False
    self._connected = False
    if self._ws:
        await self._ws.close()
        self._ws = None
```

Active typing indicator tasks in `self._typing_tasks` are not cancelled during shutdown. They will raise exceptions when trying to send on the closed WebSocket and eventually die, but not cleanly.

**Fix**: Cancel all typing tasks in `stop()`:

```python
for task in self._typing_tasks.values():
    task.cancel()
self._typing_tasks.clear()
```

### M4. Zalo bridge auth token sent in plaintext over WebSocket

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/channels/zalo.py`, lines 60-61

```python
await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
```

The bridge URL defaults to `ws://localhost:3002` (no TLS). The auth token is sent in plaintext. While this is local-only by default, if a user changes the bridge URL to a remote host without changing to `wss://`, the token is exposed.

**Impact**: Low for local use, high if misconfigured for remote.

**Mitigation**: Consider logging a warning if `bridge_url` starts with `ws://` and does not point to `localhost`/`127.0.0.1`.

### M5. `convert_keys` passthrough logic checks `parent_key` against `_PASSTHROUGH_KEYS` but `parent_key` is the *converted* snake_case key

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/config/loader.py`, lines 88-93

```python
new_key = camel_to_snake(k)
if new_key in _PASSTHROUGH_KEYS or parent_key in _PASSTHROUGH_KEYS:
    result[new_key] = v
```

The `parent_key` passed down is the `new_key` (snake_case). This works correctly because `_PASSTHROUGH_KEYS` contains snake_case values. However, `convert_to_camel` checks `if k in _PASSTHROUGH_KEYS or parent_key in _PASSTHROUGH_KEYS` where `k` is the original key and `parent_key` is also the original key. If someone uses the camelCase form `extraHeaders` as a key in the data dict, it would NOT match `extra_headers` in `_PASSTHROUGH_KEYS`.

**Impact**: `extraHeaders` values would get their sub-keys incorrectly converted in `convert_to_camel`. The `_PASSTHROUGH_KEYS` set does include `"extraHeaders"` which handles this case. Correct as-is, but the dual-casing in `_PASSTHROUGH_KEYS` is a maintenance burden.

### M6. No rate limiting on session worker creation

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/loop.py`, lines 241-248

A flood of messages from unique session keys (e.g., a spam attack across many Zalo group threads) creates an unbounded number of asyncio tasks and queues. Each worker holds resources for 5 minutes (idle timeout).

**Impact**: Memory exhaustion under spam/abuse.

**Fix**: Add a maximum concurrent sessions limit (e.g., 50), rejecting or queuing new sessions beyond the limit.

---

## Low Priority

### L1. Zalo channel not shown in `channels status` CLI command

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/cli/commands.py`, lines 541-603

The `channels_status()` command renders a table with WhatsApp, Discord, Feishu, Mochat, Telegram, and Slack -- but does not include Zalo.

**Fix**: Add Zalo to the status table.

### L2. `_parse_raw_response` does not handle missing `choices` gracefully

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/providers/litellm_provider.py`, line 207

```python
choice = data["choices"][0]
```

If the response is malformed (empty `choices` or no `choices` key), this raises `KeyError` or `IndexError`, which propagates as a fallback failure.

**Fix**: Add a guard:

```python
choices = data.get("choices") or []
if not choices:
    return LLMResponse(content="Error: empty response from provider", finish_reason="error")
choice = choices[0]
```

### L3. Verbose logging includes tool result previews that may contain sensitive data

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/loop.py`, line 218

```python
result_preview = result[:300] if result else "(empty)"
logger.debug(f"Tool result [{tool_call.name}]: {result_preview}")
```

Tool results from `read_file` or MCP tools could contain secrets or PII. These are logged at DEBUG level.

**Impact**: Low in production (DEBUG is not default), but worth noting for --verbose mode.

### L4. `LLM reasoning` log may contain model-internal content

**File**: `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/loop.py`, lines 192-193

```python
preview = response.reasoning_content[:500]
logger.debug(f"LLM reasoning: {preview}")
```

Reasoning content from models like Claude may contain internal chain-of-thought. Logging 500 chars at DEBUG level is fine for debugging but could surprise users if logs are shared.

---

## Edge Cases Found by Scout

1. **Dead-letter messages**: When a session worker exits due to idle timeout, any messages already in its queue are lost. The queue may still have items when the worker breaks out of its loop. These are silently dropped.

2. **Observe-only flood**: In a busy Zalo group, every single non-mentioned message creates an observe-only inbound message, each triggering session file I/O (save). High-traffic groups could create significant disk I/O pressure.

3. **MCP tool param filtering with empty schema**: If `self._parameters` has no `"properties"` key at all (some MCP tools use `$ref` or `allOf`), `allowed` becomes an empty set, and the `if allowed:` check skips filtering -- which is correct. But if `properties` exists but is empty `{}`, `allowed` is empty and filtering is skipped. This is also correct behavior.

4. **Telegram chunk splitting on empty content**: If `msg.content` is empty string, `chunks` becomes `['']`, which sends an empty message to Telegram. Telegram API rejects empty messages.

5. **Zalo reconnection loop on auth failure**: If `bridge_token` is wrong, the bridge may disconnect immediately. The 5-second reconnect loop will retry indefinitely, filling logs with connection errors.

---

## Positive Observations

1. **Per-session concurrency model** is well-designed. Sequential processing within a session prevents message ordering issues while allowing parallelism across sessions.

2. **Graceful degradation** throughout: LLM timeout returns user-friendly message, MCP tool errors return strings rather than raising, Telegram HTML falls back to plain text.

3. **Passthrough keys in config loader** is a clean solution to the env var / header key mangling problem.

4. **Message splitting in Zalo** uses intelligent boundary detection (paragraph, then line, then hard cut) -- better than the naive char-split in Telegram.

5. **Defensive content coercion** (`content = msg.content if isinstance(msg.content, str) else str(msg.content)`) prevents type errors from unexpected payloads.

6. **Brave API key guard** prevents registration of a broken WebSearchTool when no key is configured.

7. **Error truncation** (`short_error = str(e).split('\n')[0][:200]`) prevents leaking full stack traces to end users.

---

## Recommended Actions (Priority Order)

1. **[Critical]** Fix the shared tool context race condition (C2). This is a correctness bug that will cause wrong message routing under concurrent load.
2. **[Critical]** Close the httpx.AsyncClient for MCP HTTP connections (C1). Register it with the AsyncExitStack.
3. **[High]** Fix the stale session worker queue bug (H1). Check `task.done()` before reusing an existing queue.
4. **[High]** Sanitize error messages in direct HTTP fallback logging (H3).
5. **[High]** Use boundary-aware splitting for Telegram messages (H2).
6. **[Medium]** Cancel typing tasks in Zalo `stop()` (M3).
7. **[Medium]** Log exceptions in Zalo typing loop instead of silent swallow (M2).
8. **[Medium]** Add session worker count limit (M6).
9. **[Low]** Add Zalo to `channels status` command (L1).
10. **[Low]** Guard against empty `choices` in `_parse_raw_response` (L2).

---

## Metrics

- **Type Coverage**: N/A (Python, type hints present on new code)
- **Test Coverage**: Not measured (no test files in diff)
- **Linting Issues**: 0 syntax errors detected in diff
- **New Dependencies**: `websockets` (for Zalo channel, import-guarded), `httpx` (already in use)

---

## Unresolved Questions

1. Is there a maximum message rate from the Zalo bridge that should be enforced? The current implementation creates unbounded observe-only history.
2. Should the `_direct_chat` HTTP fallback be opt-in via config rather than automatic? It adds a second HTTP call on every LiteLLM failure.
3. The Zalo formatting rules in `context.py` are hardcoded. Should channel-specific system prompt fragments be configurable?
