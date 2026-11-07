import json
import os
import secrets
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_coordinator import config

from paramesh import telemetry
from paramesh.coordinator import Coordinator
from paramesh.events import EventBus
from paramesh.monitor import ClusterView, EventSink, _endpoint
from paramesh.operations import EventLog
from paramesh.security import RpcSecurity
from paramesh.services import coordinator_server, shard_server
from paramesh.shard import ParameterShard
from paramesh.state import StateDB
from paramesh.workload import parameters


@pytest.fixture
def http_backend():
    state = {"bad": False, "posts": []}

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            if state["bad"]:
                payload = []
            elif self.path.startswith("/api/v1/query"):
                series = {"metric": {"component": "worker-0"}, "value": [time.time(), "1.25"]}
                if self.path.startswith("/api/v1/query_range"):
                    series["values"] = [[time.time(), "1.25"]]
                payload = {"status": "success", "data": {"result": [series]}}
            elif self.path.startswith("/api/search"):
                payload = {"traces": [{"traceID": "abc"}, {"traceID": "../invalid"}]}
            else:
                payload = {"batches": []}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_POST(self):
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            state["posts"].append(json.loads(payload))
            self.send_response(500 if state["bad"] else 204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    server.server_close()


def test_monitor_samples_authenticated_rpc_and_rejects_bad_backend_shapes(tmp_path, http_backend):
    endpoint, backend = http_backend
    settings = config()
    security = RpcSecurity.ephemeral()
    shard = ParameterShard(settings, parameters())
    server, port = shard_server(shard, "127.0.0.1:0", security=security)
    server.start()
    settings.shard_endpoints[:] = [f"127.0.0.1:{port}"]
    registry, port = coordinator_server(Coordinator(settings), "127.0.0.1:0", security=security)
    registry.start()
    database = StateDB(tmp_path / "operator.sqlite")
    log = EventLog(database)
    sink = EventSink(log, "", "", endpoint)
    view = ClusterView(
        settings,
        f"127.0.0.1:{port}",
        RpcSecurity(security.token),
        log,
        sink,
        endpoint,
        endpoint,
        tmp_path / "evidence",
    )
    try:
        deadline = time.monotonic() + 5
        while view.snapshot()["sampled_at"] is None and time.monotonic() < deadline:
            time.sleep(0.05)
        snapshot = view.snapshot()
        assert snapshot["coordinator"]["available"] and snapshot["shards"][0]["available"]
        assert snapshot["backends"]["prometheus"] and snapshot["backends"]["tempo"]
        assert snapshot["metrics"]["loss"][0]["value"][1] == "1.25"
        assert snapshot["traces"] == [{"traceID": "0" * 29 + "abc"}]
        assert security.token not in json.dumps(snapshot)
        snapshot["shards"].clear()
        assert view.snapshot()["shards"]
        assert view.trace("b" * 32) == {"batches": []}
        assert view.benchmarks() == []
        view.evidence.mkdir()
        (view.evidence / "sync-cpu.json").write_text('{"mode":"sync"}')
        assert view.benchmarks() == [{"mode": "sync"}]
        external = tmp_path / "external"
        external.mkdir()
        (external / "manifest.json").write_text('{"trials":[{"mode":"async","final_loss":0.5}]}')
        view.external_artifacts = external
        assert view.benchmarks()[-1]["evidence_source"] == "external workload"
        view.close()
        backend["bad"] = True
        registry.stop(0).wait()
        server.stop(0).wait()
        view.sample()
        snapshot = view.snapshot()
        assert not snapshot["coordinator"]["available"]
        assert not snapshot["shards"][0]["available"]
        assert not snapshot["backends"]["prometheus"]
        assert not snapshot["backends"]["tempo"]
        with pytest.raises(ValueError):
            _endpoint("http://credentials:secret@example.com")
    finally:
        view.close()
        sink.close()
        database.close()
        registry.stop(0).wait()
        server.stop(0).wait()


def test_actual_nats_events_persist_and_loki_outage_does_not_discard_local_history(
    tmp_path, http_backend, monkeypatch
):
    endpoint, backend = http_backend
    name = f"paramesh-sink-check-{uuid.uuid4().hex[:10]}"
    token = secrets.token_urlsafe(32)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--entrypoint",
            "/bin/sh",
            "-p",
            "127.0.0.1::4222",
            "-e",
            "PARAMESH_NATS_TOKEN",
            "nats:2.15.2-alpine",
            "-ec",
            'exec nats-server --auth "$PARAMESH_NATS_TOKEN"',
        ],
        env=os.environ | {"PARAMESH_NATS_TOKEN": token},
        capture_output=True,
        check=True,
        timeout=300,
    )
    database = StateDB(tmp_path / "operator.sqlite")
    sink = publisher = None
    signals = telemetry.Telemetry()
    monkeypatch.setattr(telemetry, "active", signals)
    try:
        binding = subprocess.check_output(["docker", "port", name, "4222"], text=True).strip()
        log = EventLog(database)
        sink = EventSink(log, f"nats://{binding}", token, endpoint)
        publisher = EventBus("coordinator", f"nats://{binding}", token)
        deadline = time.monotonic() + 10
        while not sink.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sink.connected
        publisher.emit("worker_joined", run_id="actual-bridge", worker_id="worker-0", generation=1)
        while not backend["posts"] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert log.snapshot()[0]["event"] == "worker_joined"
        assert backend["posts"][0]["streams"][0]["stream"] == {
            "app": "paramesh",
            "event": "worker_joined",
        }
        backend["bad"] = True
        publisher.emit(
            "worker_recovered", run_id="actual-bridge", worker_id="worker-0", generation=2
        )
        while len(backend["posts"]) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(log.snapshot()) == 2
        while (
            signals.registry.get_sample_value("paramesh_loki_errors_total") != 1
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        assert signals.registry.get_sample_value("paramesh_loki_errors_total") == 1
    finally:
        if sink:
            sink.close()
        if publisher:
            publisher.close()
        database.close()
        signals.close()
        subprocess.run(["docker", "rm", "-fv", name], capture_output=True, check=True, timeout=30)
