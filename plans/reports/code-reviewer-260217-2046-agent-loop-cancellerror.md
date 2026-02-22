# Code Review: Agent Loop CancelledError Handling

**File:** `/Users/vanducng/git/personal/agents/nanobot/nanobot/agent/loop.py`
**Commit:** `6057a67` (fix: resolve Zalo typing stuck and add DM user filtering)
**Date:** 2026-02-17
**Reviewer:** code-reviewer

---

## Scope

- **Files reviewed:** `nanobot/agent/loop.py`, `nanobot/bus/queue.py`
- **LOC changed:** ~60 lines (net addition)
- **Focus:** asyncio correctness of CancelledError restructuring in `run()`, `_run_agent_loop()`, and `_session_worker()`

---

## Overall Assessment

The restructuring correctly fixes the root bug: the old code broke out of the `while` loop on any `CancelledError` from `consume_inbound`, which could be spurious (e.g., from a cancelled internal task's exception propagating into the event loop). The new design is architecturally sound — outer `try/except CancelledError` catches true shutdown, inner `except CancelledError` on `consume_inbound` is survivable. However, there are three concrete issues worth addressing before this is considered production-safe.

---

## Critical Issues

None. No data loss or security regressions introduced.

---

## High Priority

### 1. `asyncio.shield()` Does Not Prevent CancelledError Delivery to the Awaiter

**Location:** `_run_agent_loop()`, lines 226-231

```python
try:
    result = await asyncio.shield(
        self.tools.execute(tool_call.name, tool_call.arguments)
    )
except asyncio.CancelledError:
    logger.warning(f"Tool '{tool_call.name}' cancelled")
    raise  # Propagate so session worker can handle cleanup
```

`asyncio.shield()` protects the *inner coroutine* from being cancelled — the wrapped task continues running. However, the *awaiting coroutine* (the `await asyncio.shield(...)` expression itself) still raises `CancelledError` when the outer task is cancelled. The code correctly catches and re-raises it, so the propagation chain is fine. But the semantics are misleading: the tool keeps executing in the background as an orphaned task after cancellation. This can cause:

- **Resource leaks:** A long-running tool (e.g., shell exec, web fetch) continues consuming resources after the session worker has already broken out.
- **State corruption:** If the tool writes to shared state (e.g., `MessageTool`, `CronTool`), it may mutate context after the session moved on.
- **No handle to cancel it later:** The shielded inner task is not stored anywhere. If `run()` shuts down and collects session tasks, the shielded sub-tasks are invisible to the 30-second grace period.

**Recommendation:** Either remove `asyncio.shield()` (let the tool be cancelled cleanly, which is the simpler and safer approach given tool results are discarded on cancellation anyway), or store the inner task and cancel it explicitly in the cleanup path:

```python
# Simpler: no shield needed since result is discarded on CancelledError anyway
result = await self.tools.execute(tool_call.name, tool_call.arguments)
```

The `except Exception` handler already covers tool-internal failures. `asyncio.shield()` adds complexity without benefit here.

### 2. `_tool_context_lock` Leaked When CancelledError Propagates Mid-Loop

**Location:** `_run_agent_loop()`, lines 219-239

```python
async with self._tool_context_lock:
    self._set_tool_context(channel, chat_id)
    for tool_call in response.tool_calls:
        ...
        try:
            result = await asyncio.shield(...)
        except asyncio.CancelledError:
            raise  # raised WHILE STILL INSIDE async with block
```

When `CancelledError` is raised inside the `async with self._tool_context_lock:` block, Python's `async with` guarantees `__aexit__` is called — so the lock *is* released correctly in this case (it is not leaked). This is a non-issue structurally, but worth confirming explicitly since the concern was raised.

However, a subtler problem exists: the `for tool_call in response.tool_calls` loop is entirely within the lock scope. For multi-tool responses, each tool call awaits inside the lock. This is an existing design issue (not introduced by this PR) but the new `asyncio.shield()` makes it more visible: a long tool execution holds the lock for its entire duration, blocking all other concurrent sessions from their tool context setup. Under load with multiple active sessions and slow tools, this becomes a serialization bottleneck.

### 3. `publish_outbound` in the Cancellation Handler Can Be Silently Lost

**Location:** `_session_worker()`, lines 316-324

```python
except asyncio.CancelledError:
    logger.info(f"Session '{key}' processing cancelled")
    try:
        await self.bus.publish_outbound(OutboundMessage(...))
    except Exception:
        pass
    break
```

The cancellation notice `await self.bus.publish_outbound(...)` will itself raise `CancelledError` if the task is still in cancelled state, because `CancelledError` is a subclass of `BaseException`, not `Exception`. The `except Exception: pass` block does **not** catch `CancelledError`. So if the task is cancelled again during this `await`, the `CancelledError` propagates out of the `except asyncio.CancelledError` block and the `break` is never reached. The worker exits without ever sending the notice and without logging anything, which defeats the purpose.

**Fix:**

```python
except asyncio.CancelledError:
    logger.info(f"Session '{key}' processing cancelled")
    try:
        await asyncio.shield(self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content="Sorry, my previous processing was interrupted. Please send your message again.",
            metadata=msg.metadata or {},
        )))
    except (Exception, asyncio.CancelledError):
        pass
    break
```

`asyncio.shield()` is actually the right tool *here* (unlike issue #1) because `publish_outbound` is a simple queue put that completes near-instantly; we want it to complete even if the task is being torn down.

Alternatively, since `bus.publish_outbound` is just `await self.outbound.put(msg)` (a non-blocking queue put that completes immediately), the cancellation window is microseconds wide. But being explicit is safer than relying on implementation timing.

---

## Medium Priority

### 4. Inner `CancelledError` Handler in `run()` Can Mask True Shutdown Cancellation

**Location:** `run()`, lines 267-272

```python
except asyncio.CancelledError:
    # Only exit if explicitly told to stop; otherwise keep consuming
    if not self._running:
        break
    logger.warning("Agent loop consume interrupted, resuming...")
    continue
```

This inner handler catches a `CancelledError` from `asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)`. The condition `if not self._running` is checked, but `_running` is only set to `False` by `stop()` (which is a sync method called from outside) or by the `finally` block (after the loop has already exited). If the task is externally cancelled (i.e., someone calls `task.cancel()` without calling `stop()` first), `_running` will still be `True` at the time the inner handler fires, so it logs a warning and continues. The true shutdown cancellation is then lost — it will only be caught by the outer `except asyncio.CancelledError` on the *next* await point, which is the `asyncio.wait_for(consume_inbound)` call again.

In practice this means: when the task is cancelled, the loop executes one extra iteration (resuming `consume_inbound`) before the second `CancelledError` propagates to the outer handler. This is benign but subtle, and the extra iteration has a 1-second `wait_for` timeout before the next cancellation opportunity, meaning shutdown can be delayed up to 1 second.

This is acceptable given the 30-second grace window, but worth documenting.

### 5. `stop()` and `run()` Cleanup Are Inconsistent

**Location:** `stop()` method (lines 345-352) vs `run()` finally block (lines 284-295)

`stop()` calls `task.cancel()` and clears dicts immediately. The `run()` finally block waits 30 seconds, then cancels. If `stop()` is called while `run()` is still executing its finally block, the tasks are cancelled twice (harmless but noisy) and the dicts are cleared out from under `run()`'s finally — `asyncio.wait(active, ...)` received the snapshot before the clear, so this is safe, but the log messages become confusing.

`stop()` also does not await anything, so there is no way for a caller to know when shutdown is complete without awaiting the `run()` coroutine itself.

---

## Low Priority

### 6. Session Worker Idle Timeout Does Not Account for Shutdown

**Location:** `_session_worker()`, line 301

```python
while self._running:
    try:
        msg = await asyncio.wait_for(queue.get(), timeout=idle_timeout)
```

When `_running` becomes `False`, the loop condition is evaluated only after `queue.get()` completes or times out. With a 300-second idle timeout, a worker could remain alive for up to 5 minutes after `stop()` is called, even though `stop()` cancels all tasks. This is fine because `task.cancel()` is called on all tasks; just noting that the `while self._running` guard does not actually bound the shutdown time on its own.

### 7. `msg` Variable Scope in `_session_worker()` Cancellation Handler

**Location:** `_session_worker()`, lines 313-325

If `CancelledError` is raised at the `queue.get()` line (not at `_process_message`), `msg` is unbound and the cancellation handler at line 315 would raise `UnboundLocalError` when constructing `OutboundMessage`. In practice this cannot happen because the `CancelledError` from `queue.get()` is caught at lines 307-308 (which does a bare `break`), not at lines 313-325. But the exception handler at 313 is structured to appear to handle `CancelledError` from any point in the try block, which is misleading.

---

## Positive Observations

- The two-level try/except structure (`inner` for survivable interrupts, `outer` for true shutdown) is the canonical asyncio pattern and is correctly applied.
- The 30-second grace period in the finally block is a thoughtful addition — session workers get time to flush their current response before hard-cancel.
- Moving `TimeoutError` handling inside the inner loop and keeping `CancelledError` outside is clean and correct.
- The `finally` block setting `self._running = False` is defensive and correct — it handles the case where the loop exits via an unhandled exception that is neither `CancelledError` nor the while condition.
- Logging in all three handlers gives good operational visibility.
- The `_consolidate_and_cleanup` fire-and-forget task in `_process_message` correctly uses `asyncio.create_task()` so it outlives the current coroutine scope.

---

## Recommended Actions

1. **High - Remove `asyncio.shield()` from tool execution** (issue #1). The tool result is discarded on cancellation anyway. Shield creates orphaned tasks with no lifecycle management.
2. **High - Fix cancellation notice in `_session_worker`** (issue #3). Wrap `publish_outbound` with `asyncio.shield()` or catch `BaseException` (or both) to ensure the typing-stopped notice is actually delivered.
3. **Medium - Document the 1-second shutdown delay** (issue #4). A comment noting this behavior is acceptable reduces future confusion.
4. **Low - Add `msg` initialization guard** (issue #7). Initialize `msg = None` before the queue.get() call and add a guard in the cancellation handler.

---

## Unresolved Questions

1. Is there a scenario where `consume_inbound` raises `CancelledError` that is NOT caused by the `run()` task being cancelled? With the current `MessageBus` implementation (`asyncio.Queue.get()`), this would only happen if an external party cancels the `run()` task or if a nested `asyncio.wait_for` cancels the coroutine. The comment "Only exit if explicitly told to stop" suggests the author believes such spurious cancellations are possible — what is the actual source? Understanding this informs whether the inner handler is necessary at all or whether the `wait_for(timeout=1.0)` alone is sufficient protection.

2. `_tool_context_lock` is held across multiple sequential tool calls. Is this intentional serialization, or should each tool call acquire/release independently to reduce lock contention between sessions?
