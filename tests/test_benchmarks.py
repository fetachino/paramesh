import csv
import json

import pytest

from paramesh.demo import run_demo


def test_warm_process_measurement_excludes_warmup_and_preserves_numerical_reference(tmp_path):
    report = run_demo(steps=6, warmup_steps=2, workers=2, shards=2, output=tmp_path / "run.json")
    assert report["max_parameter_error"] < 1e-6
    assert report["shard_versions"] == [6, 6]
    assert report["warmup"]["shard_versions"] == [2, 2]
    assert report["configuration"]["max_staleness"] == 1
    for result in report["worker_results"]:
        assert result["resumed_from"] == 2 and len(result["losses"]) == 4
        measured = result["measurement"]
        assert measured["end"] > measured["start"]
        assert measured["warmup_session_seconds"] > 0
        assert measured["sample_drops"] == 0
        pushes = [item for item in measured["rpc_samples"] if item["method"] == "PushGradients"]
        assert len(pushes) == 8 and all(item["status"] == "OK" for item in pushes)
        assert all(item["request_bytes"] > 0 for item in pushes)


def test_larger_model_payload_preserves_reference_and_is_reported(tmp_path):
    report = run_demo(
        steps=3,
        warmup_steps=1,
        workers=2,
        shards=2,
        hidden_width=256,
        output=tmp_path / "large-model.json",
    )
    assert report["workload"]["hidden_width"] == 256
    assert report["workload"]["parameter_bytes"] == (6 * 256 + 1) * 4
    assert report["max_parameter_error"] < 1e-6
    for worker in report["worker_results"]:
        pushes = [
            item
            for item in worker["measurement"]["rpc_samples"]
            if item["method"] == "PushGradients"
        ]
        assert sum(item["request_bytes"] for item in pushes) > 6 * 256 * 4


def test_framework_rotates_trials_and_exports_consistent_raw_artifacts(tmp_path, monkeypatch):
    from paramesh import benchmarks

    order = []

    def fixture_run(**options):
        mode = options["mode"]
        order.append(mode)
        raw = {
            "mode": mode,
            "environment": {"commit": "unit-fixture", "source_dirty": True},
            "workload": {"samples_per_worker": 32},
            "final_loss": 0.1,
            "max_parameter_error": 0.0 if mode == "sync" else None,
            "warmup": {"shard_versions": [1], "loss": 0.3},
            "shard_versions": [3],
            "worker_results": [
                {
                    "worker_id": "worker-0",
                    "resumed_from": 1,
                    "losses": [0.2, 0.1],
                    "measurement": {
                        "start": 10.0,
                        "end": 11.0,
                        "sample_drops": 0,
                        "rpc_samples": [
                            {
                                "method": method,
                                "status": "OK",
                                "duration_seconds": 0.001,
                                "request_bytes": 20,
                                "response_bytes": 30,
                            }
                            for method in ["PushGradients", "PullParameters"] * 2
                        ],
                    },
                }
            ],
        }
        options["output"].write_text(json.dumps(raw))
        return raw

    monkeypatch.setattr(benchmarks, "run_demo", fixture_run)
    monkeypatch.setattr(benchmarks, "hardware", lambda: {"cpu_model": "unit-fixture"})
    destination = tmp_path / "measurements"
    report = benchmarks.run_benchmarks(
        destination,
        modes=("sync", "async"),
        repetitions=2,
        warmup_steps=1,
        measured_steps=2,
        workers=1,
        shards=1,
    )
    assert order == ["sync", "async", "async", "sync"]
    assert report["status"] == "complete" and len(report["trials"]) == 4
    assert report["configuration"]["hidden_width"] == 8
    assert all(row["examples_per_second"] == 64 for row in report["trials"])
    assert len(list(csv.DictReader((destination / "rpc.csv").open()))) == 16
    assert len(list(csv.DictReader((destination / "trials.csv").open()))) == 4
    assert json.loads((destination / "manifest.json").read_text())["status"] == "complete"
    assert (destination / "overview.png").read_bytes().startswith(b"\x89PNG")
    assert len(list(destination.glob("trial-*.json"))) == 4
    with pytest.raises(FileExistsError):
        benchmarks.run_benchmarks(destination)
    with pytest.raises(ValueError):
        benchmarks.run_benchmarks(tmp_path / "bad", measured_steps=0)
    with pytest.raises(ValueError):
        benchmarks.run_benchmarks(tmp_path / "bad-width", hidden_width=32769)
    raw = json.loads((destination / "trial-000-sync.json").read_text())
    raw["worker_results"][0]["measurement"]["end"] = 10.0
    with pytest.raises(ValueError, match="measurement window"):
        benchmarks._summary(raw, 2, 1, 1)
    raw["worker_results"][0]["measurement"]["end"] = 11.0
    raw["worker_results"][0]["measurement"]["rpc_samples"] = []
    with pytest.raises(ValueError, match="push count"):
        benchmarks._summary(raw, 2, 1, 1)
    raw["worker_results"][0]["losses"] = []
    with pytest.raises(ValueError, match="iteration count"):
        benchmarks._summary(raw, 2, 1, 1)

    def failed_trial(**options):
        options["output"].write_text('{"unit_fixture":"divergent numerical result"}')
        raise RuntimeError("unit-fixture interruption")

    monkeypatch.setattr(benchmarks, "run_demo", failed_trial)
    with pytest.raises(RuntimeError):
        benchmarks.run_benchmarks(tmp_path / "interrupted")
    failed = json.loads((tmp_path / "interrupted" / "manifest.json").read_text())
    assert failed["status"] == "failed" and failed["failure_type"] == "RuntimeError"
    assert (tmp_path / "interrupted" / "trial-000-sync.json").is_file()


def test_actual_supported_host_inventory_is_recorded():
    from paramesh.benchmarks import hardware

    inventory = hardware()
    assert inventory["logical_cpu_count"] > 0
    assert inventory["memory_bytes"] > 0 and inventory["cpu_model"]
    assert inventory["clock"]["monotonic"]


def test_recovery_benchmark_keeps_raw_trials_and_rejects_false_recovery(tmp_path, monkeypatch):
    from paramesh import recovery_benchmarks as benchmarks

    order = []

    def trial(**options):
        failure = options["failure"]
        order.append(failure)
        raw = {
            "failure": {
                "terminated_component": f"{failure}-0",
                "worker_step_before_failure": 7,
                "detection_seconds": 1.0,
                "recovery_seconds_until_progress": 2.0,
            },
            "shard_versions": [20, 20],
            "worker_health": {"worker-0": "completed", "worker-1": "completed"},
            "max_parameter_error": 1e-7,
            "final_loss": 0.1,
            "environment": {"commit": "unit-fixture", "source_dirty": True},
        }
        options["output"].write_text(json.dumps(raw))
        return raw

    monkeypatch.setattr(benchmarks, "run_demo", trial)
    output = tmp_path / "recovery"
    report = benchmarks.run_recovery_benchmarks(output, repetitions=2)
    assert report["status"] == "complete"
    assert order == ["worker", "shard", "shard", "worker"]
    assert len(report["trials"]) == 4
    assert (output / "overview.png").is_file() and (output / "trials.csv").is_file()
    with pytest.raises(FileExistsError):
        benchmarks.run_recovery_benchmarks(output)

    def false_recovery(**options):
        raw = trial(**options)
        raw["max_parameter_error"] = 1e-3
        return raw

    monkeypatch.setattr(benchmarks, "run_demo", false_recovery)
    with pytest.raises(ValueError, match="did not fully recover"):
        benchmarks.run_recovery_benchmarks(tmp_path / "invalid", repetitions=1)
    failed = json.loads((tmp_path / "invalid" / "manifest.json").read_text())
    assert failed["status"] == "failed" and failed["failure_type"] == "ValueError"
    assert (tmp_path / "invalid" / "trial-000-worker.json").exists()
