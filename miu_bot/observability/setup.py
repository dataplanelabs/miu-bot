"""OpenTelemetry SDK initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from miu_bot.config.schema import OTelConfig

_initialized = False


def init_otel(config: "OTelConfig") -> None:
    """Initialize OpenTelemetry SDK with tracing + metrics."""
    global _initialized
    if _initialized or not config.enabled:
        return

    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({
            "service.name": config.service_name,
            "service.version": config.service_version or _get_version(),
            "deployment.environment": config.environment,
        })

        # Tracing
        if config.protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

        span_exporter = OTLPSpanExporter(
            endpoint=(
                config.endpoint
                if config.protocol == "grpc"
                else f"{config.endpoint}/v1/traces"
            )
        )

        sampler = None
        if config.sample_rate < 1.0:
            from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

            sampler = TraceIdRatioBased(config.sample_rate)

        tracer_provider = TracerProvider(resource=resource, sampler=sampler)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        # Metrics
        if config.protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

        metric_exporter = OTLPMetricExporter(
            endpoint=(
                config.endpoint
                if config.protocol == "grpc"
                else f"{config.endpoint}/v1/metrics"
            )
        )
        reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=config.export_interval_ms,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(meter_provider)

        # Inject trace context into loguru records
        logger.configure(patcher=_inject_trace_context)

        _initialized = True
        logger.info(f"OTel initialized: {config.endpoint} (sample={config.sample_rate})")

    except ImportError:
        logger.warning("OTel packages not installed — observability disabled")
    except Exception as e:
        logger.error(f"OTel init failed: {e}")


def _inject_trace_context(record: dict) -> None:
    """Add OTel trace_id and span_id to loguru records."""
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx.trace_id:
            record["extra"]["trace_id"] = format(ctx.trace_id, "032x")
            record["extra"]["span_id"] = format(ctx.span_id, "016x")
    except Exception:
        pass


def _get_version() -> str:
    try:
        from importlib.metadata import version

        return version("miu-bot")
    except Exception:
        return "0.0.0"


def shutdown_otel() -> None:
    """Flush and shutdown OTel providers."""
    try:
        from opentelemetry import trace, metrics

        tp = trace.get_tracer_provider()
        if hasattr(tp, "shutdown"):
            tp.shutdown()
        mp = metrics.get_meter_provider()
        if hasattr(mp, "shutdown"):
            mp.shutdown()
    except Exception:
        pass
