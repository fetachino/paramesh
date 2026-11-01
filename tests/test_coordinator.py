import pytest

from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb


def config(**changes):
    values = dict(
        run_id="test-run",
        mode=pb.ASYNCHRONOUS,
        shard_endpoints=["localhost:50051"],
        worker_ids=["worker-0", "worker-1"],
        learning_rate=0.1,
        barrier_timeout_seconds=1,
    )
    values.update(changes)
    return pb.RunConfig(**values)


def test_health_uses_multiple_thresholds_and_unavailable_sessions_are_fenced():
    now = [100.0]
    coordinator = Coordinator(config(), clock=lambda: now[0], suspect_after=3, unavailable_after=9)
    session = coordinator.register("worker-0", 1)
    assert coordinator.status().workers[0].health == "registered"
    heartbeat = pb.HeartbeatRequest(
        run_id="test-run",
        worker_id="worker-0",
        session_id=session.session_id,
        step=2,
    )
    assert coordinator.heartbeat(heartbeat).health == "healthy"
    now[0] += 3
    assert coordinator.status().workers[0].health == "suspect"
    now[0] += 6
    assert coordinator.status().workers[0].health == "unavailable"
    with pytest.raises(PermissionError):
        coordinator.heartbeat(heartbeat)
    replacement = coordinator.register("worker-0", 1)
    assert replacement.session_id != session.session_id
    with pytest.raises(PermissionError):
        coordinator.heartbeat(heartbeat)


def test_duplicate_live_worker_and_unsupported_protocol_are_rejected():
    coordinator = Coordinator(config())
    coordinator.register("worker-0", 1)
    with pytest.raises(ValueError, match="already"):
        coordinator.register("worker-0", 1)
    with pytest.raises(ValueError, match="protocol"):
        coordinator.register("worker-1", 2)
    with pytest.raises(ValueError, match="membership"):
        coordinator.register("stranger", 1)


@pytest.mark.parametrize(
    "changes",
    [
        {"learning_rate": float("nan")},
        {"learning_rate": -1},
        {"mode": 0},
        {"worker_ids": ["same", "same"]},
        {"shard_endpoints": []},
        {"barrier_timeout_seconds": 0},
        {"run_id": "../unsafe"},
    ],
)
def test_invalid_run_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        Coordinator(config(**changes))
