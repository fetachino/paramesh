"""Measured ParamMesh-versus-local-reference CPU scaling trials."""

import csv
import hashlib
import json
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paramesh.benchmarks import hardware
from paramesh.demo import run_demo
from paramesh.workload import TrainingWorkload, bundled_workload


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _source_metadata() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    commit = "unknown"
    source_dirty: bool | None = None
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        source_dirty = bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        pass
    lock = root / "uv.lock"
    return {
        "python": platform.python_version(),
        "os": platform.system(),
        "machine": platform.machine(),
        "commit": commit,
        "source_dirty": source_dirty,
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
    }


def _run_reference(
    *, workload: TrainingWorkload, workers: int, steps: int, warmup_steps: int
) -> dict[str, Any]:
    import torch

    torch.set_num_threads(1)
    network = workload.model_factory()
    optimizer = torch.optim.SGD(network.parameters(), lr=0.05)
    batches = [workload.dataset_factory(index) for index in range(workers)]
    inputs = torch.cat([batch[0] for batch in batches])
    targets = torch.cat([batch[1] for batch in batches])

    def loss() -> torch.Tensor:
        return torch.nn.functional.mse_loss(network(inputs), targets)

    initial_loss = float(loss().detach())
    for _ in range(warmup_steps):
        optimizer.zero_grad()
        current = loss()
        torch.autograd.backward(current)
        optimizer.step()
    started = time.perf_counter()
    for _ in range(steps):
        optimizer.zero_grad()
        current = loss()
        torch.autograd.backward(current)
        optimizer.step()
    elapsed = time.perf_counter() - started
    final_loss = float(loss().detach())
    return {
        "status": "complete",
        "workers": workers,
        "steps": steps,
        "warmup_steps": warmup_steps,
        "elapsed_seconds": elapsed,
        "examples_per_second": workers * len(batches[0][0]) * steps / elapsed,
        "initial_loss": initial_loss,
        "final_loss": final_loss,
        "samples_per_worker": len(batches[0][0]),
        "model": type(network).__name__,
        "optimizer": "SGD",
        "device": "cpu",
    }


def _render(report: dict[str, Any], output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure, axis = plt.subplots(figsize=(9, 5))
    for implementation, marker in (("paramesh", "o"), ("reference", "s")):
        rows = [row for row in report["rows"] if row["implementation"] == implementation]
        by_workers: dict[int, list[float]] = {}
        for row in rows:
            by_workers.setdefault(row["workers"], []).append(row["examples_per_second"])
        x = sorted(by_workers)
        y = [sum(by_workers[count]) / len(by_workers[count]) for count in x]
        axis.plot(x, y, marker=marker, label=implementation)
    axis.set_xlabel("Workers")
    axis.set_ylabel("Measured examples / second")
    axis.set_title("ParamMesh scaling matrix · synchronous CPU workload")
    axis.set_xticks(sorted({row["workers"] for row in report["rows"]}))
    axis.grid(axis="y", alpha=0.2)
    axis.legend()
    figure.tight_layout()
    try:
        figure.savefig(output / "overview.png", dpi=160)
        figure.savefig(output / "overview.svg")
    finally:
        plt.close(figure)


def run_scaling_matrix(
    output: Path,
    *,
    workers: tuple[int, ...] = (1, 2, 4),
    repetitions: int = 3,
    warmup_steps: int = 20,
    measured_steps: int = 200,
    shards: int = 2,
    workload: TrainingWorkload | None = None,
) -> dict[str, Any]:
    if (
        not workers
        or any(type(count) is not int or not 1 <= count <= 8 for count in workers)
        or len(set(workers)) != len(workers)
        or type(repetitions) is not int
        or not 1 <= repetitions <= 30
        or type(warmup_steps) is not int
        or not 1 <= warmup_steps <= 1000
        or type(measured_steps) is not int
        or not 1 <= measured_steps <= 5000
        or type(shards) is not int
        or not 1 <= shards <= 4
    ):
        raise ValueError("Invalid worker counts, repetitions, steps or shard count")
    output.mkdir(parents=True, exist_ok=False)
    active = workload or bundled_workload()
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "captured_at": datetime.now(UTC).isoformat(),
        "configuration": {
            "workers": list(workers),
            "repetitions": repetitions,
            "warmup_steps": warmup_steps,
            "measured_steps": measured_steps,
            "shards": shards,
            "mode": "sync",
            "comparison": "ParamMesh process harness versus single-process PyTorch SGD",
        },
        "hardware": hardware(),
        "environment": _source_metadata(),
        "rows": [],
    }
    _write_json(output / "manifest.json", report)
    fieldnames = [
        "implementation",
        "trial",
        "repetition",
        "workers",
        "shards",
        "steps",
        "warmup_steps",
        "elapsed_seconds",
        "examples_per_second",
        "final_loss",
        "max_parameter_error",
        "failure_type",
    ]
    try:
        with (output / "trials.csv").open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            trial = 0
            for repetition in range(1, repetitions + 1):
                for count in workers:
                    reference = _run_reference(
                        workload=active,
                        workers=count,
                        steps=measured_steps,
                        warmup_steps=warmup_steps,
                    )
                    reference_path = output / f"reference-trial-{trial:03d}-workers-{count}.json"
                    _write_json(reference_path, reference)
                    reference_row = {
                        "implementation": "reference",
                        "trial": trial,
                        "repetition": repetition,
                        "workers": count,
                        "shards": "",
                        "steps": measured_steps,
                        "warmup_steps": warmup_steps,
                        "elapsed_seconds": reference["elapsed_seconds"],
                        "examples_per_second": reference["examples_per_second"],
                        "final_loss": reference["final_loss"],
                        "max_parameter_error": "",
                        "failure_type": "",
                    }
                    report["rows"].append(reference_row)
                    writer.writerow(reference_row)

                    raw_path = output / f"paramesh-trial-{trial:03d}-workers-{count}.json"
                    try:
                        raw = run_demo(
                            mode="sync",
                            steps=warmup_steps + measured_steps,
                            warmup_steps=warmup_steps,
                            workers=count,
                            shards=shards,
                            workload=active,
                            output=raw_path,
                        )
                    except BaseException as error:
                        failure = {
                            "status": "failed",
                            "failure_type": type(error).__name__,
                            "error": str(error),
                            "workers": count,
                            "shards": shards,
                            "steps": measured_steps,
                            "warmup_steps": warmup_steps,
                        }
                        _write_json(raw_path.with_name(raw_path.stem + "-failure.json"), failure)
                        failure_row = {
                            "implementation": "paramesh",
                            "trial": trial,
                            "repetition": repetition,
                            "workers": count,
                            "shards": shards,
                            "steps": measured_steps,
                            "warmup_steps": warmup_steps,
                            "elapsed_seconds": "",
                            "examples_per_second": "",
                            "final_loss": "",
                            "max_parameter_error": "",
                            "failure_type": type(error).__name__,
                        }
                        report["rows"].append(failure_row)
                        writer.writerow(failure_row)
                        csv_file.flush()
                        _write_json(output / "manifest.json", report)
                        raise
                    row = {
                        "implementation": "paramesh",
                        "trial": trial,
                        "repetition": repetition,
                        "workers": count,
                        "shards": shards,
                        "steps": measured_steps,
                        "warmup_steps": warmup_steps,
                        "elapsed_seconds": raw["worker_wall_seconds_including_startup"],
                        "examples_per_second": (
                            count
                            * raw["workload"]["samples_per_worker"]
                            * measured_steps
                            / raw["worker_wall_seconds_including_startup"]
                        ),
                        "final_loss": raw["final_loss"],
                        "max_parameter_error": raw["max_parameter_error"],
                        "failure_type": "",
                    }
                    report["rows"].append(row)
                    writer.writerow(row)
                    csv_file.flush()
                    _write_json(output / "manifest.json", report)
                    trial += 1
        _render(report, output)
        report["status"] = "complete"
    except BaseException as error:
        report.update(status="failed", failure_type=type(error).__name__, error=str(error))
        _write_json(output / "manifest.json", report)
        raise
    _write_json(output / "manifest.json", report)
    return report
