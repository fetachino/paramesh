import json

from paramesh import scaling_benchmarks


def test_scaling_matrix_preserves_raw_trials_and_reference_rows(tmp_path, monkeypatch):
    def fake_demo(**options):
        output = options["output"]
        raw = {
            "mode": "sync",
            "worker_count": options["workers"],
            "shard_versions": [2, 2],
            "final_loss": 0.2,
            "max_parameter_error": 0.0,
            "worker_wall_seconds_including_startup": 2.0,
            "workload": {"samples_per_worker": 4},
            "environment": {"commit": "fixture", "source_dirty": False},
        }
        output.write_text(json.dumps(raw))
        return raw

    monkeypatch.setattr(scaling_benchmarks, "run_demo", fake_demo)
    monkeypatch.setattr(
        scaling_benchmarks,
        "_run_reference",
        lambda **options: {
            "elapsed_seconds": 1.0,
            "examples_per_second": options["workers"] * 4 * options["steps"],
            "final_loss": 0.3,
            "workers": options["workers"],
            "steps": options["steps"],
            "samples_per_worker": 4,
            "status": "complete",
        },
    )
    monkeypatch.setattr(scaling_benchmarks, "hardware", lambda: {"cpu_model": "fixture"})

    report = scaling_benchmarks.run_scaling_matrix(
        tmp_path / "matrix",
        workers=(1, 2),
        repetitions=1,
        warmup_steps=1,
        measured_steps=2,
    )

    assert report["status"] == "complete"
    assert len(report["rows"]) == 4
    assert {row["implementation"] for row in report["rows"]} == {"paramesh", "reference"}
    assert (tmp_path / "matrix" / "paramesh-trial-000-workers-1.json").is_file()
    assert (tmp_path / "matrix" / "reference-trial-000-workers-1.json").is_file()
    assert (tmp_path / "matrix" / "trials.csv").is_file()
    assert (tmp_path / "matrix" / "manifest.json").is_file()
    assert (tmp_path / "matrix" / "overview.png").read_bytes().startswith(b"\x89PNG")


def test_scaling_matrix_preserves_failed_paramesh_trial(tmp_path, monkeypatch):
    monkeypatch.setattr(
        scaling_benchmarks,
        "_run_reference",
        lambda **_: {
            "elapsed_seconds": 1.0,
            "examples_per_second": 1.0,
            "final_loss": 0.3,
        },
    )

    def failed_demo(**_):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(scaling_benchmarks, "run_demo", failed_demo)

    try:
        scaling_benchmarks.run_scaling_matrix(
            tmp_path / "failed",
            workers=(1,),
            repetitions=1,
            warmup_steps=1,
            measured_steps=2,
        )
    except RuntimeError as error:
        assert str(error) == "fixture failure"
    else:
        raise AssertionError("expected the failed trial to be raised")

    failure = tmp_path / "failed" / "paramesh-trial-000-workers-1-failure.json"
    assert json.loads(failure.read_text())["failure_type"] == "RuntimeError"
    assert json.loads((tmp_path / "failed" / "manifest.json").read_text())["status"] == "failed"
