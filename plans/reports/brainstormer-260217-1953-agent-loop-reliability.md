# Brainstorm: Agent Loop Reliability Architecture

## Problem Statement

nanobot's agent loop has six production reliability issues spanning supervision, message delivery, typing indicators, tool context isolation, backpressure, and session worker lifecycle. The system needs incremental hardening without introducing external dependencies or over-engineering for what is fundamentally a personal/small-team chatbot.

## Current Architecture Summary

```
Channel -> InboundMessage -> MessageBus (asyncio.Queue) -> AgentLoop.run() dispatcher
                                                                |
                                                    per-session queues + workers
                                                                |
                                                    _process_message -> _run_agent_loop (LLM + tools)
                                                                |
                                                    OutboundMessage -> MessageBus -> ChannelManager._dispatch_outbound -> channel.send()
```

Key characteristics:
- Single inbound dispatcher (AgentLoop.run) -- single point of failure
- Per-session workers with 5-min idle timeout
- Shared singleton tools (MessageTool, SpawnTool, CronTool) with mutable routing state
- asyncio.Queue with no size limits, no acknowledgment, no retry
- Typing indicator lifecycle split between channel (start) and dispatcher (stop)
- Global asyncio.Lock serializing ALL tool execution across ALL sessions

---

## Issue-by-Issue Analysis and Recommendations

### 1. Supervision Model: Agent Loop as Single Point of Failure

**Root cause**: `AgentLoop.run()` is a single while-loop consuming from the inbound queue. If it dies, all new messages are orphaned. The `asyncio.gather(..., return_exceptions=True)` fix prevents channel crashes from killing the agent, but the dispatcher itself has no self-healing.

**Evaluated approaches:**

| Approach | Pros | Cons |
|----------|------|------|
| A. Auto-restart wrapper | Simple, covers the main failure mode | Does not address worker orphaning |
| B. Actor-model library (e.g. `dramatic`, `thespian`) | Proper supervision tree | Adds dependency, over-engineered for this scale |
| C. Watchdog task + restart | No dependencies, targeted fix | Slightly more code in commands.py |

**Recommendation: Approach C -- Watchdog wrapper in the gateway startup.**

The gateway `run()` function should wrap `agent.run()` in a restart loop rather than a bare `asyncio.gather` call. This is the simplest change that covers the real production failure:

```python
async def _supervised_agent(agent):
    """Auto-restart agent loop on crash with backoff."""
    backoff = 1
    while True:
        try:
            await agent.run()
            break  # clean exit
        except Exception as e:
            logger.error(f"Agent loop crashed: {e}, restarting in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
```

Then in `run()`:
```python
await asyncio.gather(
    _supervised_agent(agent),
    channels.start_all(),
    return_exceptions=True,
)
```

**Effort**: ~15 lines changed. **Impact**: High -- prevents the most catastrophic failure mode.

Additionally, `AgentLoop.run()` should explicitly handle `Exception` in its main while-loop (not just `TimeoutError` and `CancelledError`) so that a single bad message does not kill the entire dispatcher. Currently, an unexpected exception from `bus.consume_inbound()` or the session-task creation path would break the loop.

---

### 2. Message Delivery Guarantees

**Root cause**: `MessageTool.execute()` calls `self._send_callback(msg)` which is `bus.publish_outbound()` -- a queue put. It returns `"Message sent"` immediately. The actual delivery path is: queue -> `_dispatch_outbound` -> `channel.send()`. Any failure in that chain is silent.

**Evaluated approaches:**

| Approach | Pros | Cons |
|----------|------|------|
| A. End-to-end acknowledgment (MessageTool awaits actual delivery) | True delivery confirmation | Blocks LLM tool loop; adds latency; requires callback plumbing |
| B. Outbound retry with DLQ (dead letter queue) | Handles transient failures | More complexity in dispatch_outbound |
| C. Delivery status log + best-effort retry | Observable, low coupling | Does not give LLM confirmation |
| D. Direct send bypass (MessageTool calls channel.send directly) | Simplest guaranteed delivery | Breaks bus abstraction; channel may not be available |

**Recommendation: Approach B -- Retry in `_dispatch_outbound` with bounded attempts.**

The outbound dispatcher should retry failed sends with exponential backoff (3 attempts, 1s/2s/4s). Failed messages after retries get logged with full context. This covers the actual production failures (transient WebSocket disconnects on Zalo bridge) without blocking the LLM tool loop.

```python
async def _dispatch_outbound(self) -> None:
    while True:
        msg = await self.bus.consume_outbound()
        channel = self.channels.get(msg.channel)
        if not channel:
            logger.warning(f"Unknown channel: {msg.channel}")
            continue
        for attempt in range(3):
            try:
                await channel.send(msg)
                break
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(1 * (2 ** attempt))
                    logger.warning(f"Retry {attempt+1} for {msg.channel}:{msg.chat_id}")
                else:
                    logger.error(f"Message delivery failed after 3 attempts to {msg.channel}:{msg.chat_id}: {e}")
```

Why NOT approach A (awaiting delivery): The LLM tool loop is iterative -- it calls a tool, gets the result, and decides next steps. If MessageTool blocks for 5-10s waiting for actual Zalo delivery, it degrades the user experience for multi-step tool chains. The LLM's "message sent" acknowledgment is acceptable as "message queued" semantics. The real fix is making the queue-to-delivery path reliable.

**Effort**: ~20 lines in `manager.py`. **Impact**: Medium-high -- covers the most common delivery failures.

---

### 3. Typing Indicator Lifecycle

**Root cause**: Typing starts in `zalo.py._handle_bridge_message()` (line 231) and stops in `zalo.py.send()` (line 126). These are two completely separate code paths connected only by the hope that a response will eventually arrive. If agent processing fails, typing runs until the 5-min safety timeout.

**Evaluated approaches:**

| Approach | Pros | Cons |
|----------|------|------|
| A. Move typing to agent loop (start/stop via bus events) | Centralized lifecycle | Typing is channel-specific; agent loop shouldn't know about it |
| B. Typing context manager in channel | Clean lifecycle, guaranteed stop | Requires channel to own the full processing lifecycle |
| C. Processing-complete event on bus | Decoupled, channel reacts to completion | Adds a third event type |
| D. Timeout + guaranteed stop-on-next-message | Simple, already partially done | Still leaves gap for the current message |

**Recommendation: Approach C -- Add a lightweight "processing complete" signal.**

Add a `ProcessingEvent` to the bus (or piggyback on OutboundMessage metadata). When the session worker finishes processing a message (whether success, error, or no response), it publishes a signal. The channel subscribes to this signal and stops typing.

Concretely, the simplest version is: **the session worker always publishes an OutboundMessage on completion, even for errors**. It already does this in the `except` block (line 304). The remaining gap is when `_process_message` returns `None` (observe_only messages). But observe_only messages don't start typing, so that gap is already covered.

The real gap is: **what if the session worker itself crashes in an unexpected way?** The solution is to add a `finally` block in `_session_worker` that stops typing for the current session:

```python
async def _session_worker(self, key: str) -> None:
    queue = self._session_queues[key]
    current_msg = None
    try:
        while self._running:
            try:
                current_msg = await asyncio.wait_for(queue.get(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                break
            try:
                response = await self._process_message(current_msg)
                if response:
                    await self.bus.publish_outbound(response)
            except Exception as e:
                # ... existing error handling ...
                pass
            finally:
                # Signal processing complete (typing stop, etc.)
                if current_msg and not current_msg.observe_only:
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=current_msg.channel,
                        chat_id=current_msg.chat_id,
                        content="",  # empty = no-op for actual send
                        metadata={"_processing_complete": True},
                    ))
    finally:
        # Worker dying: stop typing for this session
        pass
```

Then in `ZaloChannel.send()`, check the metadata flag:

```python
async def send(self, msg: OutboundMessage) -> None:
    self._stop_typing(msg.chat_id)
    if msg.metadata.get("_processing_complete") and not msg.content:
        return  # Just a typing-stop signal, nothing to send
    # ... existing send logic ...
```

However, this is somewhat ugly. A cleaner alternative: **make typing management a concern of BaseChannel with a guaranteed timeout tied to session processing, not a fixed 5-min wall clock.**

Actually, the simplest effective fix is: **reduce the typing timeout from 300s to 60s**, and **add the `finally` block in `_session_worker`** to publish an empty outbound message that triggers `_stop_typing`. This covers 99% of cases without architectural changes.

**Effort**: ~15 lines. **Impact**: Medium -- eliminates the stuck-typing UX issue.

---

### 4. Tool Context Isolation

**Root cause**: `MessageTool`, `SpawnTool`, and `CronTool` are singletons with mutable `_default_channel` / `_default_chat_id` state. The current fix uses `self._tool_context_lock` (line 219) which serializes ALL tool execution across ALL sessions. Session A's `exec` (which might run for 30s) blocks Session B from running any tool.

**Evaluated approaches:**

| Approach | Pros | Cons |
|----------|------|------|
| A. Per-session tool instances (clone tools per session) | True isolation, no lock needed | Memory overhead; complex lifecycle for MCP tools |
| B. Pass context as tool parameters (not mutable state) | Stateless, no lock, simple | Requires LLM to pass channel/chat_id; unreliable |
| C. Thread-local style context (asyncio contextvars) | No lock, no cloning, transparent | Requires all context-dependent tools to read from contextvars |
| D. Narrow the lock to only context-dependent tools | Better concurrency | Still serializes message/spawn/cron calls |

**Recommendation: Approach C -- asyncio ContextVars.**

This is the cleanest solution and perfectly suited to asyncio. Python's `contextvars` module provides per-task context that is automatically inherited by child tasks. The pattern:

```python
# nanobot/agent/context_vars.py
from contextvars import ContextVar

current_channel: ContextVar[str] = ContextVar("current_channel", default="")
current_chat_id: ContextVar[str] = ContextVar("current_chat_id", default="")
```

In `_session_worker` or `_process_message`, set the context vars:
```python
current_channel.set(msg.channel)
current_chat_id.set(msg.chat_id)
```

In `MessageTool.execute()`:
```python
from nanobot.agent.context_vars import current_channel, current_chat_id

async def execute(self, content, channel=None, chat_id=None, **kwargs):
    channel = channel or current_channel.get()
    chat_id = chat_id or current_chat_id.get()
    ...
```

**This eliminates the lock entirely.** Each asyncio Task (session worker) has its own context var scope. No mutation of shared state. No serialization.

The only caveat: MCP tools and other tools that do not need routing context are unaffected. Only the three context-dependent tools (message, spawn, cron) need to read from contextvars.

**Remove `_set_tool_context()`, remove `_tool_context_lock`, remove the `async with` block.** The tool execution in `_run_agent_loop` becomes:

```python
for tool_call in response.tool_calls:
    result = await self.tools.execute(tool_call.name, tool_call.arguments)
    ...
```

No lock. No context setting. Clean.

**Effort**: ~30 lines changed across 4 files. **Impact**: High -- eliminates the concurrency bottleneck.

---

### 5. Backpressure and Overload Protection

**Root cause**: No limits on concurrent session workers, no queue size limits, no rate limiting. A message flood creates unbounded workers and queues.

**Evaluated approaches:**

| Approach | Pros | Cons |
|----------|------|------|
| A. Bounded queues + semaphore | Simple, effective | Needs backpressure signal to channels |
| B. Rate limiting per sender | Prevents abuse | Does not limit total load |
| C. Both A + B | Comprehensive | More code |

**Recommendation: Layered protection -- semaphore + bounded queues.**

Three specific changes, each independent:

**5a. Max concurrent sessions semaphore** (in `AgentLoop.__init__`):
```python
self._max_concurrent = asyncio.Semaphore(10)  # configurable
```
In `_session_worker`, wrap `_process_message`:
```python
async with self._max_concurrent:
    response = await self._process_message(msg)
```
This limits how many LLM calls happen concurrently. Messages still queue per-session; they just wait for a slot.

**5b. Bounded session queue** (in `run()` when creating a new session queue):
```python
self._session_queues[key] = asyncio.Queue(maxsize=10)
```
When the queue is full, `put()` blocks. This propagates backpressure to the inbound dispatcher, which is acceptable -- it means the dispatcher pauses briefly until the session has capacity. For a chatbot, 10 queued messages per session is generous.

**5c. Inbound queue size monitoring** (in `MessageBus`):
```python
self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=100)
```
With `maxsize=100`, channels will block on `publish_inbound` if the agent loop is overwhelmed. This is actually the right behavior -- it gives WebSocket-based channels a natural pause signal.

**Effort**: ~10 lines total. **Impact**: Medium -- prevents resource exhaustion under load.

---

### 6. Session Worker Lifecycle Race Condition

**Root cause**: Worker idle-timeout cleanup in the `TimeoutError` handler (lines 264-268) checks `task.done()` and deletes the entry. But between the moment the task completes and the next cleanup cycle, a new message could arrive for that session key. The current code at line 253 checks `self._session_tasks[key].done()` and recreates, which IS correct but has a subtle race: the `put()` on line 258 uses `self._session_queues[key]` which was just created, but the old worker might still be referencing the old queue object.

Wait -- actually, re-reading the code more carefully: when a session worker's task finishes (line 291 break), the cleanup at lines 264-268 deletes both the task AND the queue. Then when a new message arrives (line 253), it checks `done()`, creates a new queue AND a new task. The new task references the new queue. This is correct.

The actual race is narrower: between the worker exiting (task becomes `done()`) and the cleanup running (which only happens during `TimeoutError` iterations), a message arrives. At line 253, `self._session_tasks[key].done()` returns True, so it recreates. This is fine.

**But there IS a real race**: The worker breaks out of the while loop (line 291), but hasn't fully exited the coroutine yet (Python's task state may not be `done()` until the coroutine frame returns). During this tiny window, a message arrives, the dispatcher sees `not task.done()`, and puts the message on the OLD queue that the dying worker has already stopped reading from.

**Recommendation: Replace the "check done + recreate" pattern with explicit signaling.**

Use an `asyncio.Event` per session that the worker sets on exit, rather than checking `task.done()`:

```python
# In run():
if key not in self._session_queues or self._session_queues[key].is_dead:
    self._session_queues[key] = _SessionQueue()
    self._session_tasks[key] = asyncio.create_task(self._session_worker(key))
await self._session_queues[key].put(msg)
```

Where `_SessionQueue` is a thin wrapper:
```python
class _SessionQueue:
    def __init__(self, maxsize=10):
        self._queue = asyncio.Queue(maxsize=maxsize)
        self.is_dead = False

    async def put(self, msg):
        await self._queue.put(msg)

    async def get(self, timeout):
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    def mark_dead(self):
        self.is_dead = True
```

The worker calls `self._session_queues[key].mark_dead()` as its very last act (in a `finally` block). The dispatcher checks `is_dead` instead of `task.done()`. This eliminates the race because `mark_dead()` happens synchronously before the dispatcher's next iteration.

**Alternative (simpler)**: Just always recreate the queue AND check `task.done()`. If the message goes to the old queue, it is lost. But this is already the current behavior, and in practice the window is microseconds. The real fix is to ensure no message is lost by making the new worker drain any messages from the old queue. This is over-engineering. The current code is close enough.

**Practical recommendation**: The current code is 95% correct. The remaining 5% edge case is a microsecond race that is effectively impossible to hit in a chatbot workload. Skip this fix and focus on higher-impact items. If you want belt-and-suspenders, add the `_SessionQueue` wrapper (~15 lines).

**Effort**: 0 lines (skip) or ~20 lines (wrapper). **Impact**: Low -- theoretical race, not a practical problem at chatbot message rates.

---

## Implementation Priority Matrix

| Priority | Issue | Effort | Impact | Risk if Skipped |
|----------|-------|--------|--------|-----------------|
| P0 | #4 Tool Context (ContextVars) | ~30 lines | High | Active concurrency bottleneck |
| P0 | #1 Supervisor (restart wrapper) | ~15 lines | High | Agent loop death = total outage |
| P1 | #2 Delivery retry | ~20 lines | Med-High | Silent message loss on transient failures |
| P1 | #3 Typing lifecycle (finally block) | ~15 lines | Medium | Stuck typing indicator UX |
| P2 | #5 Backpressure (semaphore + bounds) | ~10 lines | Medium | Resource exhaustion under flood |
| P3 | #6 Session worker race | ~0-20 lines | Low | Theoretical microsecond race |

**Total estimated effort**: ~90-110 lines of changes across 5-6 files.

## Recommended Implementation Order

1. **Phase 1** (immediate, <1 hour): Issues #4 and #1
   - Add `context_vars.py` with `current_channel` and `current_chat_id`
   - Refactor MessageTool, SpawnTool, CronTool to read from contextvars
   - Remove `_tool_context_lock` and `_set_tool_context`
   - Add restart wrapper in `commands.py`
   - Remove `async with self._tool_context_lock` block

2. **Phase 2** (same day, <30 min): Issues #2 and #3
   - Add retry loop in `ChannelManager._dispatch_outbound`
   - Add `finally` block in `_session_worker` for typing cleanup
   - Reduce typing timeout from 300s to 60s

3. **Phase 3** (next day, <30 min): Issue #5
   - Add `asyncio.Semaphore` for concurrent session limit
   - Add `maxsize` to session queues and inbound queue

4. **Phase 4** (optional): Issue #6
   - Only if the race condition is observed in production

## Key Design Decisions

1. **No actor model library**: The system is fundamentally a single-process asyncio application. Actor frameworks add dependency weight and conceptual overhead that is not justified for 10-50 concurrent sessions.

2. **No external message broker**: Redis/RabbitMQ would solve delivery guarantees but violates the "keep it simple, in-process" constraint. The retry-in-dispatcher approach gives 90% of the benefit with 10% of the complexity.

3. **ContextVars over per-session tool cloning**: Cloning would require deep-copying tool instances including MCP connections, which is impractical. ContextVars are a zero-copy, zero-allocation solution that asyncio was designed for.

4. **Semaphore over explicit scheduler**: A semaphore is the simplest concurrency limiter. No need for a priority queue or fair scheduler at this scale.

5. **Typing lifecycle stays in channel**: Moving typing to the agent loop would create an abstraction leak. Channels should own their UI behaviors. The agent loop just needs to guarantee it always signals completion.

## Risks and Mitigations

- **ContextVars migration**: Ensure all three context-dependent tools (message, spawn, cron) are updated. Missing one would silently use the default empty context. **Mitigation**: Add a warning log when context vars are empty in production mode.
- **Retry in dispatcher**: Retrying a failed send 3 times adds up to 7s latency worst case. **Mitigation**: Only retry on transient exceptions (ConnectionError, WebSocket errors), not on permanent failures (invalid chat_id).
- **Bounded queues**: If the inbound queue fills up, channels will block. For WebSocket channels this is fine (natural backpressure). For webhook-based channels (Feishu, WhatsApp), this could cause HTTP timeouts. **Mitigation**: Use `put_nowait` with a try/except in webhook channels, logging dropped messages.

## Success Criteria

1. Agent loop automatically restarts after a crash (observable in logs)
2. No stuck typing indicators lasting more than 60s
3. Concurrent sessions do not block each other's tool execution
4. Transient channel disconnects do not cause silent message loss (retry logs visible)
5. System remains stable under 20+ concurrent session load

## Unresolved Questions

1. **MCP tool context**: Do MCP tools also need routing context (channel/chat_id)? If so, they would also need to read from contextvars. Need to check `mcp.py` implementation.
2. **Outbound message ordering**: With retry, messages might arrive out of order if a retry succeeds after a later message was already sent. Is ordering important per-session? If so, need a per-session outbound queue (which `_dispatch_outbound` currently does not have).
3. **Graceful degradation messaging**: When the system is overloaded (semaphore full, queue full), what message should the user see? Currently it would just be a long wait. Consider a "I'm busy, please wait" auto-response.
4. **Health check endpoint**: Should the gateway expose a `/health` endpoint that monitors agent loop status, queue depths, and active sessions? This would help with observability but is outside the current scope.
