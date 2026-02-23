"""Custom OTel metrics for miu_bot."""

from __future__ import annotations

try:
    from opentelemetry import metrics

    _meter = metrics.get_meter("miu_bot")

    messages_received = _meter.create_counter(
        "miubot.messages.received",
        description="Total inbound messages",
    )
    llm_latency = _meter.create_histogram(
        "miubot.llm.latency_seconds",
        description="LLM call latency",
        unit="s",
    )
    llm_tokens = _meter.create_counter(
        "miubot.llm.tokens",
        description="LLM tokens used",
    )
    tool_latency = _meter.create_histogram(
        "miubot.tool.latency_seconds",
        description="Tool execution latency",
        unit="s",
    )
    consolidation_runs = _meter.create_counter(
        "miubot.consolidation.runs",
        description="Memory consolidation runs",
    )

except ImportError:

    class _Stub:
        def add(self, *a, **kw):
            pass

        def record(self, *a, **kw):
            pass

    messages_received = _Stub()  # type: ignore[assignment]
    llm_latency = _Stub()  # type: ignore[assignment]
    llm_tokens = _Stub()  # type: ignore[assignment]
    tool_latency = _Stub()  # type: ignore[assignment]
    consolidation_runs = _Stub()  # type: ignore[assignment]
