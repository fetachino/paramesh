import pytest

from paramesh.demo import run_demo


@pytest.mark.distributed
def test_two_workers_two_shards_match_local_sgd_reference(tmp_path):
    result = run_demo(mode="sync", steps=8, workers=2, shards=2, output=tmp_path / "run.json")
    assert result["process_count"] == 5
    assert result["max_parameter_error"] < 1e-6
    assert result["shard_versions"] == [8, 8]
    assert set(result["ownership"].values()) == {0, 1}
    assert set(result["worker_health"].values()) == {"completed"}
    assert result["final_loss"] < result["initial_loss"]
    assert (tmp_path / "run.json").exists()


@pytest.mark.distributed
@pytest.mark.parametrize("mode", ["async", "bounded"])
def test_independent_workers_train_in_other_modes(mode, tmp_path):
    result = run_demo(mode=mode, steps=6, workers=2, shards=2, output=tmp_path / "run.json")
    assert result["shard_versions"] == [12, 12]
    assert result["final_loss"] < result["initial_loss"]
    assert result["max_parameter_error"] is None
