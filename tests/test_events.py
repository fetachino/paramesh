import asyncio
import json
import os
import secrets
import ssl
import subprocess
import time
import uuid

import nats
import numpy as np
import pytest
from nats.errors import Error
from test_coordinator import config

import paramesh.events as events
from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
from paramesh.services import coordinator_server, managed_coordinator, shard_server
from paramesh.shard import ParameterShard
from paramesh.worker import train_worker
from paramesh.workload import local_reference, parameters


def test_broker_outage_and_full_event_queue_do_not_interrupt_real_training(monkeypatch, capsys):
    bus = events.EventBus("test", "nats://127.0.0.1:1", "test-token" * 4, capacity=1)
    monkeypatch.setattr(events, "bus", bus)
    settings = config(worker_ids=["worker-0"], mode=pb.SYNCHRONOUS)
    shard = ParameterShard(settings, parameters())
    server, port = shard_server(shard, "127.0.0.1:0")
    server.start()
    settings.shard_endpoints[:] = [f"127.0.0.1:{port}"]
    coordinator = managed_coordinator(settings)
    registry, port = coordinator_server(coordinator, "127.0.0.1:0")
    registry.start()
    try:
        result = train_worker(f"127.0.0.1:{port}", "worker-0", 4)
        assert result["steps"] == coordinator.status().global_step == 4
        for name, expected in local_reference(1, 4, settings.learning_rate).items():
            np.testing.assert_allclose(shard.parameters[name], expected, rtol=0, atol=1e-6)
        assert bus.queue.qsize() == 1 and bus.dropped >= 2
    finally:
        registry.stop(0).wait()
        server.stop(0).wait()
        bus.close()
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [item["event"] for item in records] == [
        "training_started",
        "worker_joined",
        "training_completed",
    ]


def test_lease_loss_and_recovery_events_have_stable_fields(monkeypatch, capsys):
    bus = events.EventBus("coordinator")
    monkeypatch.setattr(events, "bus", bus)
    clock = [100.0]
    coordinator = Coordinator(config(), clock=lambda: clock[0])
    coordinator.register("worker-0", 1)
    clock[0] += 15
    coordinator.status()
    coordinator.status()
    session = coordinator.register("worker-0", 1)
    assert session.generation == 2
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [item["event"] for item in records].count("worker_lost") == 1
    assert records[-1]["event"] == "worker_recovered"
    assert records[-1]["generation"] == 2
    assert all(item["event_id"] and item["entry_point"] == "cli" for item in records)
    with pytest.raises(ValueError, match="Unknown"):
        bus.emit("worker_joined", token="must-not-leak")
    with pytest.raises(ValueError, match="size limit"):
        bus.emit("worker_joined", run_id="x" * 5000)
    with pytest.raises(ValueError, match="separate token"):
        events.EventBus("test", "nats://secret:password@example.com")
    with pytest.raises(ValueError, match="capacity"):
        events.EventBus("test", capacity=0)
    bus.close()
    bus.close()


def test_nats_tls_requires_tls_url_and_loads_configured_trust(monkeypatch, tmp_path):
    class Context:
        def __init__(self):
            self.ca = None

        def load_verify_locations(self, *, cafile):
            self.ca = cafile

        def load_cert_chain(self, certfile, keyfile):
            self.identity = (certfile, keyfile)

    context = Context()
    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    ca, certificate, key = (str(tmp_path / name) for name in ("ca.pem", "host.pem", "host.key"))
    monkeypatch.setenv("PARAMESH_NATS_TLS_CA", ca)
    monkeypatch.setenv("PARAMESH_NATS_TLS_CERT", certificate)
    monkeypatch.setenv("PARAMESH_NATS_TLS_KEY", key)
    assert events.nats_tls_options("tls://nats.private.example:4222") == {"tls": context}
    assert context.ca == ca and context.identity == (certificate, key)
    assert events.nats_tls_options("") == {}
    with pytest.raises(ValueError, match="tls://"):
        events.nats_tls_options("nats://nats.private.example:4222")
    monkeypatch.delenv("PARAMESH_NATS_TLS_KEY")
    with pytest.raises(ValueError, match="configured together"):
        events.nats_tls_options("tls://nats.private.example:4222")


def test_actual_authenticated_nats_delivery():
    name = f"paramesh-nats-check-{uuid.uuid4().hex[:10]}"
    token = secrets.token_urlsafe(32)
    environment = os.environ | {"PARAMESH_NATS_TOKEN": token}
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
        env=environment,
        capture_output=True,
        check=True,
        timeout=300,
    )
    try:
        binding = subprocess.check_output(["docker", "port", name, "4222"], text=True).strip()

        async def scenario():
            deadline = time.monotonic() + 30
            while True:
                try:
                    subscriber = await nats.connect(
                        f"nats://{binding}", token=token, max_reconnect_attempts=0
                    )
                    break
                except Error:
                    if time.monotonic() > deadline:
                        raise
                    await asyncio.sleep(0.1)
            bus = events.EventBus("coordinator", f"nats://{binding}", token)
            try:
                subscription = await subscriber.subscribe("paramesh.lifecycle")
                await subscriber.flush()
                bus.emit("worker_joined", run_id="actual-nats", worker_id="worker-0", generation=1)
                message = await subscription.next_msg(timeout=5)
                record = json.loads(message.data)
                assert record["event"] == "worker_joined" and record["run_id"] == "actual-nats"
                assert token not in message.data.decode()
                assert "tensors" not in record
            finally:
                await subscriber.close()
                bus.close()

        asyncio.run(scenario())
    finally:
        subprocess.run(["docker", "rm", "-fv", name], capture_output=True, check=True, timeout=30)


@pytest.mark.parametrize("error", [OSError, ValueError])
def test_failed_local_log_sink_does_not_fail_event_emission(monkeypatch, error):
    def unavailable(*args, **kwargs):
        raise error("log sink unavailable")

    monkeypatch.setattr(events, "print", unavailable, raising=False)
    bus = events.EventBus("coordinator")
    bus.emit("training_started", run_id="test-run", mode="SYNCHRONOUS")
    assert bus.log_failures == 1
    bus.close()
