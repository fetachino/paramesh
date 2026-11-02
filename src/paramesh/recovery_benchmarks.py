"""Repeated actual process termination and measured recovery."""

import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from paramesh.benchmarks import _json, hardware
from paramesh.demo import run_demo


def run_recovery_benchmarks(output: Path, repetitions: int = 3) -> dict[str, Any]:
    """Repeat actual process termination and full numerical recovery, sequentially."""
    if type(repetitions) is not int or not 1 <= repetitions <= 30:
        raise ValueError("Use 1..30 repetitions")
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    lock = root / "uv.lock"
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "captured_at": datetime.now(UTC).isoformat(),
        "configuration": {
            "failures": ["worker", "shard"],
            "repetitions": repetitions,
            "mode": "sync",
            "steps_per_worker": 20,
            "workers": 2,
            "shards": 2,
            "step_delay_seconds": 0.1,
            "lease_suspect_seconds": 1.5,
            "lease_unavailable_seconds": 3,
        },
        "hardware": hardware(),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
        "trials": [],
    }
    _json(output / "manifest.json", report)
    try:
        with (output / "trials.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "trial",
                    "repetition",
                    "failure",
                    "commit",
                    "source_dirty",
                    "worker_step_before_failure",
                    "detection_seconds",
                    "recovery_seconds_until_progress",
                    "max_parameter_error",
                    "final_loss",
                ],
            )
            writer.writeheader()
            for repeat in range(repetitions):
                for failure in ("worker", "shard") if repeat % 2 == 0 else ("shard", "worker"):
                    index = len(report["trials"])
                    raw = run_demo(
                        mode="sync",
                        steps=20,
                        workers=2,
                        shards=2,
                        failure=failure,
                        output=output / f"trial-{index:03d}-{failure}.json",
                    )
                    fault = raw["failure"]
                    if (
                        not fault
                        or fault["terminated_component"] != f"{failure}-0"
                        or raw["shard_versions"] != [20, 20]
                        or set(raw["worker_health"].values()) != {"completed"}
                        or raw["max_parameter_error"] is None
                        or not 0 <= raw["max_parameter_error"] < 1e-6
                        or not 0
                        < fault["detection_seconds"]
                        <= fault["recovery_seconds_until_progress"]
                        or not np.isfinite(fault["recovery_seconds_until_progress"])
                    ):
                        raise ValueError("Fault trial did not fully recover and match local SGD")
                    row = {
                        "trial": index,
                        "repetition": repeat + 1,
                        "failure": failure,
                        "commit": raw["environment"]["commit"],
                        "source_dirty": raw["environment"]["source_dirty"],
                        "worker_step_before_failure": fault["worker_step_before_failure"],
                        "detection_seconds": fault["detection_seconds"],
                        "recovery_seconds_until_progress": fault["recovery_seconds_until_progress"],
                        "max_parameter_error": raw["max_parameter_error"],
                        "final_loss": raw["final_loss"],
                    }
                    writer.writerow(row)
                    stream.flush()
                    report["trials"].append(row)
                    _json(output / "manifest.json", report)
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib import pyplot as plt

        figure, axes = plt.subplots(1, 2, figsize=(10, 4))
        for axis, key, title in zip(
            axes,
            ("detection_seconds", "recovery_seconds_until_progress"),
            ("Detection · seconds", "Termination to later progress · seconds"),
            strict=True,
        ):
            for index, failure in enumerate(("worker", "shard")):
                values = [row[key] for row in report["trials"] if row["failure"] == failure]
                median = float(np.median(values))
                axis.errorbar(
                    index,
                    median,
                    yerr=[[median - min(values)], [max(values) - median]],
                    fmt="_",
                    color="black",
                    capsize=5,
                )
                offsets = np.linspace(-0.07, 0.07, len(values))
                axis.scatter(index + offsets, values, s=28)
            axis.set_xticks((0, 1), ("worker", "shard"))
            axis.set_xlim(-0.5, 1.5)
            axis.set_ylim(bottom=0)
            axis.set_title(title)
            axis.grid(axis="y", alpha=0.2)
        figure.suptitle("ParamMesh · actual process recovery")
        figure.text(
            0.5,
            0.02,
            "Dots: trials; bars: median and observed range. Local paced scenario, not an SLA.",
            ha="center",
            fontsize=9,
        )
        figure.tight_layout(rect=(0, 0.08, 1, 0.92))
        try:
            figure.savefig(output / "overview.png", dpi=160)
            figure.savefig(output / "overview.svg")
        finally:
            plt.close(figure)
        report["status"] = "complete"
    except BaseException as error:
        report.update(status="failed", failure_type=type(error).__name__)
        _json(output / "manifest.json", report)
        raise
    _json(output / "manifest.json", report)
    return report
