import numpy as np
import pytest
from test_coordinator import config
from test_shard import update

from paramesh.coordinator import Coordinator
from paramesh.shard import ParameterShard
from paramesh.state import StateDB


def test_fence_survives_restart_and_identical_retry_can_use_new_generation(tmp_path):
    store = StateDB(tmp_path / "shard.sqlite")
    shard = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)}, state=store)
    shard.push(update())
    shard.fence("test-run", "worker-0", 1)
    with pytest.raises(PermissionError, match="generation"):
        shard.push(update())
    retry = update()
    retry.generation = 1
    assert shard.push(retry).duplicate
    assert shard.progress("test-run").next_steps["worker-0"] == 1
    store.close()
    reopened = StateDB(tmp_path / "shard.sqlite")
    restored = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)}, state=reopened)
    assert restored.push(retry).duplicate
    with pytest.raises(ValueError, match="backwards"):
        restored.fence("test-run", "worker-0", 0)
    reopened.close()


def test_coordinator_restart_preserves_run_and_advances_fencing_generation(tmp_path):
    store = StateDB(tmp_path / "coordinator.sqlite")
    calls = []
    first = Coordinator(
        config(), state=store, fence=lambda worker, generation: calls.append(generation)
    )
    session = first.register("worker-0", 1)
    assert session.generation == 1
    store.close()
    reopened = StateDB(tmp_path / "coordinator.sqlite")
    second = Coordinator(
        config(), state=reopened, fence=lambda worker, generation: calls.append(generation)
    )
    replacement = second.register("worker-0", 1)
    assert replacement.generation == 2 and calls == [1, 2]
    assert replacement.session_id != session.session_id
    reopened.close()


def test_coordinator_never_issues_session_if_one_shard_cannot_be_fenced(tmp_path):
    def unavailable(worker, generation):
        raise OSError("shard unavailable")

    store = StateDB(tmp_path / "coordinator.sqlite")
    coordinator = Coordinator(config(), state=store, fence=unavailable)
    with pytest.raises(OSError):
        coordinator.register("worker-0", 1)
    assert coordinator.status().workers == []
    coordinator.fence = lambda worker, generation: None
    assert coordinator.register("worker-0", 1).generation == 2
    store.close()
