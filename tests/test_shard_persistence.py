import numpy as np
import pytest
from test_coordinator import config
from test_shard import update, weight

from paramesh.shard import ParameterShard
from paramesh.state import StateDB


def test_restart_preserves_weights_versions_and_replay_receipt(tmp_path):
    path = tmp_path / "shard.sqlite"
    store = StateDB(path)
    first = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)}, state=store)
    first.push(update())
    store.close()
    reopened = StateDB(path)
    second = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)}, state=reopened)
    assert second.version == 1
    assert weight(second) == pytest.approx(0.8)
    assert second.push(update()).duplicate
    assert second.version == 1
    assert second.push(update(step=1, version=1)).version == 2
    reopened.close()


def test_failed_durable_commit_does_not_change_authoritative_state(tmp_path, monkeypatch):
    store = StateDB(tmp_path / "shard.sqlite")
    shard = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)}, state=store)

    def full_disk(*args):
        raise OSError("disk full")

    monkeypatch.setattr(store, "put", full_disk)
    with pytest.raises(OSError, match="disk full"):
        shard.push(update())
    assert shard.version == 0
    assert weight(shard) == 1
    assert shard.receipts == {}
    store.close()


def test_existing_state_cannot_be_silently_reused_for_another_run_or_model(tmp_path):
    store = StateDB(tmp_path / "shard.sqlite")
    ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)}, state=store)
    with pytest.raises(ValueError, match="configuration"):
        ParameterShard(
            config(run_id="other"), {"weight": np.ones(1, dtype=np.float32)}, state=store
        )
    with pytest.raises(ValueError, match="model"):
        ParameterShard(config(), {"weight": np.ones(2, dtype=np.float32)}, state=store)
    store.close()
