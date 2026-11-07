import pytest

from paramesh.demo import run_demo


@pytest.mark.parametrize(
    "factory",
    ["linear_workload", "cnn_workload", "transformer_workload"],
)
def test_supported_external_model_family_matches_reference(factory):
    from paramesh import workload

    result = run_demo(
        mode="sync",
        steps=2,
        workers=2,
        shards=2,
        workload=getattr(workload, factory)(),
    )

    assert result["shard_versions"] == [2, 2]
    assert result["max_parameter_error"] < 1e-6
    assert all(item["steps"] == 2 for item in result["worker_results"])
