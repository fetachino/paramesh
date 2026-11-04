import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import numpy as np
import pytest
from test_coordinator import config
from test_shard import update, weight

from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
from paramesh.shard import ParameterShard


def test_concurrent_identical_async_retries_commit_only_once():
    server = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)})
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: server.push(update()), range(32)))
    assert sum(not result.duplicate for result in results) == 1
    assert server.pull("test-run").version == 1
    assert weight(server) == pytest.approx(0.8)


def test_heartbeat_cannot_regress_or_cross_run_boundary():
    coordinator = Coordinator(config())
    session = coordinator.register("worker-0", 1)
    heartbeat = pb.HeartbeatRequest(
        run_id="test-run",
        worker_id="worker-0",
        session_id=session.session_id,
        step=3,
        parameter_version=2,
    )
    coordinator.heartbeat(heartbeat)
    heartbeat.step = 2
    with pytest.raises(ValueError, match="backwards"):
        coordinator.heartbeat(heartbeat)
    heartbeat.run_id = "other-run"
    with pytest.raises(ValueError, match="run ID"):
        coordinator.heartbeat(heartbeat)


def test_sync_overflow_wakes_other_waiters_without_a_partial_commit():
    server = ParameterShard(
        config(mode=pb.SYNCHRONOUS, learning_rate=1e30),
        {"weight": np.ones(1, dtype=np.float32)},
    )
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(server.push, update(gradient=1e30))
        second = pool.submit(server.push, update(worker="worker-1", gradient=1e30))
        errors = []
        for future in (first, second):
            with pytest.raises((ValueError, TimeoutError)) as error:
                future.result(timeout=2)
            errors.append(type(error.value))
    assert ValueError in errors and TimeoutError in errors
    assert weight(server) == 1


def test_last_worker_cannot_commit_after_barrier_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("paramesh.shard.time.monotonic", lambda: now[0])
    server = ParameterShard(config(mode=pb.SYNCHRONOUS), {"weight": np.ones(1, dtype=np.float32)})
    submitted = Event()

    def first_worker():
        with server.condition:
            submitted.set()
            return server.push(update())

    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(first_worker)
        assert submitted.wait(timeout=2)
        with server.condition:
            now[0] = 2
            with pytest.raises(TimeoutError):
                server.push(update(worker="worker-1"))
        with pytest.raises(TimeoutError):
            first.result(timeout=2)
    assert weight(server) == 1


def test_canceled_sync_gradient_aborts_pending_barrier_without_commit():
    server = ParameterShard(
        config(mode=pb.SYNCHRONOUS, barrier_timeout_seconds=5),
        {"weight": np.ones(1, dtype=np.float32)},
    )
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(server.push, update())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with server.condition:
                if set(server.pending) == {"worker-0"}:
                    break
            Event().wait(0.01)
        with server.condition:
            assert set(server.pending) == {"worker-0"}
        server.abort_barrier_if_pending("test-run", "worker-0", 0)
        with pytest.raises(TimeoutError):
            pending.result(timeout=2)
    assert server.version == 0
    assert server.pending == {}
