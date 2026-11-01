from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from test_coordinator import config

from paramesh.rpc import training_pb2 as pb
from paramesh.shard import ParameterShard
from paramesh.tensors import decode, encode


def update(worker="worker-0", step=0, version=0, gradient=2.0):
    return pb.GradientUpdate(
        run_id="test-run",
        worker_id=worker,
        step=step,
        base_version=version,
        tensors=[encode("weight", np.array([gradient], dtype=np.float32))],
    )


def shard(**changes):
    return ParameterShard(config(**changes), {"weight": np.array([1.0], dtype=np.float32)})


def weight(server):
    return decode(server.pull("test-run").tensors[0]).item()


def test_async_update_is_atomic_and_retry_does_not_apply_twice():
    server = shard()
    assert server.push(update()).version == 1
    assert weight(server) == pytest.approx(0.8)
    result = server.push(update())
    assert result.duplicate and result.version == 1
    assert weight(server) == pytest.approx(0.8)
    with pytest.raises(ValueError, match="different"):
        server.push(update(gradient=4))
    with pytest.raises(ValueError, match="sequence"):
        server.push(update(step=3, version=1))


def test_bounded_staleness_rejects_then_allows_refresh_without_consuming_step():
    server = shard(mode=pb.BOUNDED_STALENESS, max_staleness=0)
    server.push(update())
    with pytest.raises(ValueError, match="stale"):
        server.push(update(worker="worker-1"))
    assert server.push(update(worker="worker-1", version=1)).version == 2


def test_sync_averages_all_workers_once():
    server = shard(mode=pb.SYNCHRONOUS)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(server.push, update(gradient=2))
        second = pool.submit(server.push, update(worker="worker-1", gradient=4))
        assert first.result(timeout=2).version == second.result(timeout=2).version == 1
    assert weight(server) == pytest.approx(0.7)
    assert server.push(update()).duplicate


def test_missing_worker_times_out_without_mutating_or_retaining_gradients():
    server = shard(mode=pb.SYNCHRONOUS, barrier_timeout_seconds=0.02)
    with pytest.raises(TimeoutError):
        server.push(update())
    assert weight(server) == 1
    assert server.pull("test-run").version == 0
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(server.push, update(gradient=4))
        second = pool.submit(server.push, update(worker="worker-1", gradient=4))
        first.result(timeout=2)
        second.result(timeout=2)
    assert weight(server) == pytest.approx(0.6)


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "wrong"},
        {"worker_id": "stranger"},
        {"base_version": 3},
        {"tensors": []},
        {"tensors": [encode("other", np.ones(1, dtype=np.float32))]},
        {"tensors": [encode("weight", np.ones(2, dtype=np.float32))]},
    ],
)
def test_invalid_update_does_not_mutate_state(change):
    server = shard()
    message = update()
    for key, value in change.items():
        if key == "tensors":
            del message.tensors[:]
            message.tensors.extend(value)
        else:
            setattr(message, key, value)
    with pytest.raises(ValueError):
        server.push(message)
    assert weight(server) == 1
    assert server.pull("test-run").version == 0


def test_finite_gradients_that_overflow_optimizer_are_rejected_atomically():
    server = shard(learning_rate=1e30)
    with pytest.raises(ValueError, match="finite"):
        server.push(update(gradient=1e30))
    assert weight(server) == 1
