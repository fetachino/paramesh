import pytest

from paramesh.demo import run_demo


@pytest.mark.distributed
@pytest.mark.parametrize("component", ["worker", "shard"])
def test_terminated_process_recovers_without_changing_synchronous_sgd(component, tmp_path):
    result = run_demo(
        mode="sync",
        workers=2,
        shards=2,
        steps=20,
        failure=component,
        output=tmp_path / f"{component}.json",
    )
    assert result["shard_versions"] == [20, 20]
    assert result["max_parameter_error"] < 1e-6
    assert set(result["worker_health"].values()) == {"completed"}
    assert result["failure"]["detection_seconds"] > 0
    assert result["failure"]["recovery_seconds_until_progress"] > 0
