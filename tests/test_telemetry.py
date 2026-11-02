import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import grpc
import numpy as np
import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from prometheus_client import generate_latest
from test_coordinator import config

from paramesh import events, telemetry
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel
from paramesh.services import coordinator_server, managed_coordinator, shard_server
from paramesh.shard import ParameterShard
from paramesh.tensors import encode
from paramesh.worker import train_worker
from paramesh.workload import local_reference, parameters


def test_optional_raw_rpc_capture_is_bounded_and_contains_only_measurements(monkeypatch):
    with pytest.raises(ValueError):
        telemetry.Telemetry(capture_rpc_limit=100001)
    signals = telemetry.Telemetry(capture_rpc_limit=1)
    monkeypatch.setattr(telemetry, "active", signals)
    security = RpcSecurity.ephemeral()
    settings = config(worker_ids=["worker-0"])
    server, port = shard_server(
        ParameterShard(settings, parameters()), "127.0.0.1:0", security=security
    )
    server.start()
    request = pb.PullRequest(run_id=settings.run_id)
    try:
        with open_channel(f"127.0.0.1:{port}", security) as channel:
            client = rpc.ParameterShardStub(channel)
            response = client.PullParameters(request, timeout=3)
            client.PullParameters(request, timeout=3)
        record = signals.rpc_samples.get_nowait()
        assert record["method"] == "PullParameters" and record["status"] == "OK"
        assert record["duration_seconds"] > 0
        assert record["request_bytes"] == request.ByteSize()
        assert record["response_bytes"] == response.ByteSize()
        assert set(record) == {
            "method",
            "status",
            "duration_seconds",
            "request_bytes",
            "response_bytes",
        }
        assert signals.rpc_samples.empty() and signals.rpc_sample_drops == 1
    finally:
        server.stop(0).wait()
        signals.close()


def test_real_grpc_training_exports_correlated_otlp_spans_and_scrapable_metrics(monkeypatch):
    batches = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers["Content-Length"])
            assert 0 < size <= 8 * 1024 * 1024
            batch = ExportTraceServiceRequest()
            batch.ParseFromString(self.rfile.read(size))
            batches.append(batch)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    collector = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    receiver = threading.Thread(target=collector.serve_forever, daemon=True)
    receiver.start()
    monkeypatch.setattr(telemetry, "active", None)
    monkeypatch.setattr(events, "bus", None)
    monkeypatch.setenv("PARAMESH_METRICS_PORT", "0")
    monkeypatch.setenv("PARAMESH_NATS_URL", "")
    monkeypatch.setenv(
        "PARAMESH_OTLP_ENDPOINT", f"http://127.0.0.1:{collector.server_port}/v1/traces"
    )
    monkeypatch.setenv("PARAMESH_TRACE_SAMPLE_RATIO", "1")
    telemetry.start("integration-worker")
    signals = telemetry.active
    signals.probes.append(lambda: telemetry.set_value("global_step", 3))
    security = RpcSecurity.ephemeral()
    settings = config(worker_ids=["worker-0"], mode=pb.SYNCHRONOUS)
    shard = ParameterShard(settings, parameters())
    server, port = shard_server(shard, "127.0.0.1:0", security=security)
    server.start()
    settings.shard_endpoints[:] = [f"127.0.0.1:{port}"]
    coordinator = managed_coordinator(settings, security=security)
    registry, port = coordinator_server(coordinator, "127.0.0.1:0", security=security)
    registry.start()
    try:
        result = train_worker(
            f"127.0.0.1:{port}", "worker-0", 3, security=RpcSecurity(security.token)
        )
        assert result["steps"] == coordinator.status().global_step == 3
        for name, expected in local_reference(1, 3, settings.learning_rate).items():
            np.testing.assert_allclose(shard.parameters[name], expected, atol=1e-6, rtol=0)
        with open_channel(settings.shard_endpoints[0], security) as channel:
            with pytest.raises(grpc.RpcError) as rejected:
                rpc.ParameterShardStub(channel).PushGradients(
                    pb.GradientUpdate(
                        run_id=settings.run_id,
                        worker_id="worker-0",
                        generation=1,
                        tensors=[encode("wrong-name", np.ones(1, dtype=np.float32))],
                    ),
                    timeout=3,
                )
            assert rejected.value.code() == grpc.StatusCode.INVALID_ARGUMENT
            with pytest.raises(grpc.RpcError):
                channel.unary_unary("/untrusted/random-method")(b"bounded", timeout=3)
        assert signals.provider.force_flush(timeout_millis=3000)
        spans = [
            span
            for batch in batches
            for resource in batch.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
        ]
        training_steps = [span for span in spans if span.name == "worker.training_step"]
        assert len(training_steps) == 3
        training = training_steps[0]
        chain = [span for span in spans if span.trace_id == training.trace_id]
        assert any("PushGradients" in span.name for span in chain)
        assert any("PullParameters" in span.name for span in chain)
        commits = [span for span in chain if span.name == "shard.aggregate_sgd_commit"]
        assert len(commits) == 1
        assert all(span.parent_span_id for span in commits)
        assert len(training.events) == 1
        assert security.token not in str(spans) and security.admin_token not in str(spans)
        metrics = generate_latest(signals.registry).decode()
        assert "paramesh_worker_steps_total 3.0" in metrics
        assert "paramesh_optimizer_updates_total 3.0" in metrics
        assert "paramesh_examples_total 96.0" in metrics
        assert 'status="INVALID_ARGUMENT"' in metrics
        assert 'method="unknown"' in metrics
        assert "random-method" not in metrics and security.token not in metrics
        assert (
            signals.registry.get_sample_value(
                "paramesh_rpc_in_flight", {"direction": "client", "method": "PushGradients"}
            )
            == 0
        )
        connection = http.client.HTTPConnection("127.0.0.1", signals.http.server_port, timeout=3)
        connection.request("GET", "/metrics")
        response = connection.getresponse()
        assert response.status == 200 and b"paramesh_loss" in response.read()
        connection.close()
    finally:
        registry.stop(0).wait()
        server.stop(0).wait()
        signals.close()
        collector.shutdown()
        collector.server_close()


def test_telemetry_is_optional_and_rejects_secret_bearing_endpoints(monkeypatch):
    monkeypatch.setattr(telemetry, "active", None)
    telemetry.set_value("global_step", 2)
    telemetry.add("worker_steps")
    telemetry.observe("step_duration_seconds", 1)
    with telemetry.span("disabled") as span:
        assert span is None
    assert telemetry.correlation() == {}
    monkeypatch.setattr(events, "bus", None)
    monkeypatch.setenv("PARAMESH_METRICS_PORT", "")
    monkeypatch.setenv("PARAMESH_OTLP_ENDPOINT", "")
    monkeypatch.setenv("PARAMESH_NATS_URL", "")
    telemetry.start("plain")
    assert telemetry.active is None
    signals = telemetry.Telemetry()
    with pytest.raises(ValueError, match="Invalid OTLP"):
        signals.trace("test", "http://token:secret@example.com/v1/traces", 1)
    with pytest.raises(ValueError, match="sampling"):
        signals.trace("test", "http://127.0.0.1/v1/traces", float("nan"))
    signals.close()
    signals.close()
