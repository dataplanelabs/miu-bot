"""Span helper decorators and context managers."""

from __future__ import annotations

from functools import wraps
from typing import Any

try:
    from opentelemetry import trace
except ImportError:
    trace = None  # type: ignore[assignment]


def traced(name: str, attributes: dict[str, Any] | None = None):
    """Decorator to wrap an async function in an OTel span."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()
            if not tracer:
                return await func(*args, **kwargs)
            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def get_tracer():
    """Get the miu_bot tracer (or None if OTel not installed).

    Dynamic accessor — always returns a tracer from the current provider,
    so it works regardless of whether init_otel() has been called yet.
    """
    if trace is None:
        return None
    return trace.get_tracer("miu_bot")
