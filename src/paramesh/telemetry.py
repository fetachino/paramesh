"""Optional operational signals; disabled exporters leave the training protocol unchanged."""

import atexit
import os
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any, cast
from urllib.parse import urlsplit

import grpc

from paramesh import events

active: "Telemetry | None" = None
METHODS = frozenset(
    {
        "RegisterWorker",
        "Heartbeat",
        "GetStatus",
        "PullParameters",
        "PushGradients",
        "GetProgress",
        "FenceWorker",
    }
)


class Telemetry:
    def __init__(self) -> None:
        from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

        self.registry = CollectorRegistry()
        self.metrics: dict[str, Any] = {}
        gauges = {
            "global_step": (),
            "active_workers": (),
            "shard_version": (),
            "pending_workers": (),
            "worker_step": ("worker_id",),
            "worker_version": ("worker_id",),
            "worker_available": ("worker_id",),
            "worker_generation": ("worker_id",),
            "heartbeat_age_seconds": ("worker_id",),
            "loss": (),
            "staleness": ("worker_id",),
            "rpc_in_flight": ("direction", "method"),
            "event_consumer_connected": (),
            "last_checkpoint_duration_seconds": (),
            "last_checkpoint_step": (),
            "last_checkpoint_timestamp_seconds": (),
        }
        counters = {
            "worker_steps": (),
            "examples": (),
            "refreshes": (),
            "optimizer_updates": (),
            "rpc_bytes": ("direction", "method", "kind"),
            "rejected_updates": ("status",),
            "auth_denied": ("status",),
            "events_ingested": (),
            "events_invalid": (),
            "event_storage_errors": (),
            "loki_errors": (),
        }
        histograms = {
            "rpc_duration_seconds": ("direction", "method", "status"),
            "step_duration_seconds": (),
            "checkpoint_duration_seconds": (),
        }
        for constructor, definitions in (
            (Gauge, gauges),
            (Counter, counters),
            (Histogram, histograms),
        ):
            for name, labels in definitions.items():
                self.metrics[name] = constructor(
                    f"paramesh_{name}",
                    f"ParamMesh {name.replace('_', ' ')}",
                    labels,
                    registry=self.registry,
                )
        self.registry.register(EventCollector())
        for name in ("global_step", "active_workers", "shard_version", "pending_workers", "loss"):
            self.metrics[name].set(float("nan"))
        self.tracer: Any = None
        self.provider: Any = None
        self.http: Any = None
        self.probes: list[Callable[[], None]] = []
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None

    def serve(self, port: int, address: str = "127.0.0.1") -> None:
        from prometheus_client import start_http_server

        self.http, _ = start_http_server(port, addr=address, registry=self.registry)
        self.thread = threading.Thread(target=self._poll, name="state-metrics", daemon=True)
        self.thread.start()

    def _poll(self) -> None:
        while not self.stopped.is_set():
            for probe in self.probes:
                probe()
            self.stopped.wait(1)

    def trace(self, service: str, endpoint: str, sample_ratio: float) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not 0 <= sample_ratio <= 1
        ):
            raise ValueError("Invalid OTLP endpoint or trace sampling ratio")
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.grpc import (
            GrpcInstrumentorClient,
            GrpcInstrumentorServer,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        self.provider = TracerProvider(
            resource=Resource.create({"service.name": service}),
            sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
        )
        self.provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint, timeout=2),
                max_queue_size=1024,
                max_export_batch_size=64,
                schedule_delay_millis=500,
                export_timeout_millis=3000,
            )
        )
        self.tracer = self.provider.get_tracer("paramesh")
        GrpcInstrumentorClient().instrument(tracer_provider=self.provider)  # type: ignore[no-untyped-call]
        GrpcInstrumentorServer().instrument(tracer_provider=self.provider)  # type: ignore[no-untyped-call]

    def close(self) -> None:
        if self.stopped.is_set():
            return
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.http is not None:
            self.http.shutdown()
            self.http.server_close()
        if events.bus is not None:
            events.bus.close()
        if self.provider is not None:
            from opentelemetry.instrumentation.grpc import (
                GrpcInstrumentorClient,
                GrpcInstrumentorServer,
            )

            GrpcInstrumentorClient().uninstrument()  # type: ignore[no-untyped-call]
            GrpcInstrumentorServer().uninstrument()  # type: ignore[no-untyped-call]
            self.provider.shutdown()


class EventCollector:
    def collect(self) -> Any:
        from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

        bus = events.bus
        yield GaugeMetricFamily(
            "paramesh_event_enabled",
            "NATS publication configured",
            value=int(bool(bus and bus.url)),
        )
        yield GaugeMetricFamily(
            "paramesh_event_queue_depth",
            "Queued lifecycle events",
            value=bus.queue.qsize() if bus else 0,
        )
        yield GaugeMetricFamily(
            "paramesh_event_connected",
            "NATS publisher connected",
            value=int(bus.connected) if bus else 0,
        )
        yield CounterMetricFamily(
            "paramesh_events_published", "Events flushed to NATS", value=bus.published if bus else 0
        )
        yield CounterMetricFamily(
            "paramesh_events_dropped",
            "Events dropped by this process",
            value=bus.dropped if bus else 0,
        )
        yield CounterMetricFamily(
            "paramesh_event_log_failures",
            "Failed local lifecycle log writes",
            value=bus.log_failures if bus else 0,
        )


def start(service: str) -> None:
    global active
    events.bus = events.EventBus(
        service, os.environ.get("PARAMESH_NATS_URL", ""), os.environ.get("PARAMESH_NATS_TOKEN", "")
    )
    port = os.environ.get("PARAMESH_METRICS_PORT")
    endpoint = os.environ.get("PARAMESH_OTLP_ENDPOINT")
    if not port and not endpoint:
        atexit.register(events.bus.close)
        return
    active = Telemetry()
    if port:
        active.serve(int(port), os.environ.get("PARAMESH_METRICS_BIND", "127.0.0.1"))
    if endpoint:
        active.trace(service, endpoint, float(os.environ.get("PARAMESH_TRACE_SAMPLE_RATIO", "0.2")))
    atexit.register(active.close)


def _metric(name: str, labels: dict[str, str]) -> Any:
    assert active is not None
    value = active.metrics[name]
    return value.labels(**labels) if labels else value


def set_value(name: str, value: float, **labels: str) -> None:
    if active is not None:
        _metric(name, labels).set(value)


def add(name: str, value: float = 1, **labels: str) -> None:
    if active is not None:
        _metric(name, labels).inc(value)


def observe(name: str, value: float, **labels: str) -> None:
    if active is not None:
        _metric(name, labels).observe(value)


def span(name: str, **attributes: Any) -> AbstractContextManager[Any]:
    if active is not None and active.tracer is not None:
        return cast(
            AbstractContextManager[Any],
            active.tracer.start_as_current_span(name, attributes=attributes),
        )
    return nullcontext()


def correlation() -> dict[str, str]:
    if active is not None and active.tracer is not None:
        from opentelemetry.trace import get_current_span

        context = get_current_span().get_span_context()
        if context.is_valid:
            return {"trace_id": f"{context.trace_id:032x}", "span_id": f"{context.span_id:016x}"}
    return {}


def _method(path: str | bytes) -> str:
    method = (path.decode("ascii", errors="replace") if isinstance(path, bytes) else path).rsplit(
        "/", 1
    )[-1]
    return method if method in METHODS else "unknown"


def _size(message: Any) -> int:
    return len(message) if isinstance(message, bytes) else int(message.ByteSize())


def _finish(direction: str, method: str, code: Any, started: float) -> None:
    status = code.name if code is not None else "OK"
    add("rpc_in_flight", -1, direction=direction, method=method)
    observe(
        "rpc_duration_seconds",
        time.perf_counter() - started,
        direction=direction,
        method=method,
        status=status,
    )
    if direction == "server" and method == "PushGradients" and status != "OK":
        add("rejected_updates", status=status)


class ServerMetrics:
    def intercept_service(self, continuation: Any, details: Any) -> Any:
        handler = continuation(details)
        if handler is None or handler.unary_unary is None:
            return handler
        method = _method(details.method)

        def call(request: Any, context: Any) -> Any:
            started = time.perf_counter()
            add("rpc_in_flight", direction="server", method=method)
            add("rpc_bytes", _size(request), direction="server", method=method, kind="request")
            code = None
            try:
                response = handler.unary_unary(request, context)
                add(
                    "rpc_bytes", _size(response), direction="server", method=method, kind="response"
                )
                return response
            except Exception:
                code = context.code() or grpc.StatusCode.UNKNOWN
                raise
            finally:
                _finish("server", method, code or context.code(), started)

        return grpc.unary_unary_rpc_method_handler(
            call,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


class ClientMetrics(grpc.UnaryUnaryClientInterceptor):  # type: ignore[misc]
    def intercept_unary_unary(self, continuation: Any, details: Any, request: Any) -> Any:
        method, started = _method(details.method), time.perf_counter()
        add("rpc_in_flight", direction="client", method=method)
        add("rpc_bytes", _size(request), direction="client", method=method, kind="request")
        code = grpc.StatusCode.UNKNOWN
        try:
            call = continuation(details, request)
            response = call.result()
            code = call.code()
            add("rpc_bytes", _size(response), direction="client", method=method, kind="response")
            return call
        except grpc.RpcError as error:
            code = error.code()
            raise
        finally:
            _finish("client", method, code, started)
