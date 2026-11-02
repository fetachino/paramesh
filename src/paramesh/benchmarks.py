"""Sequential warm-process measurements with retained trial and RPC records."""

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from paramesh.demo import MODES, run_demo


def hardware() -> dict[str, Any]:
    result: dict[str, Any] = {
        "os": platform.platform(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "cpu_model": None,
        "memory_bytes": None,
        "clock": vars(time.get_clock_info("perf_counter")),
        "load_isolation": "uncontrolled workstation; background services may affect results",
    }
    try:
        if sys.platform == "win32":
            inventory = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "@{cpu_model=@((Get-CimInstance Win32_Processor).Name);"
                    "memory_bytes=(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory}"
                    " | ConvertTo-Json -Compress",
                ],
                text=True,
                timeout=15,
            )
            result.update(json.loads(inventory))
        elif sys.platform == "linux":
            result["cpu_model"] = next(
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            )
            result["memory_bytes"] = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as error:
        result["inventory_error"] = type(error).__name__
    return result


def _json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )


def _summary(raw: dict[str, Any], measured: int, workers: int, shards: int) -> dict[str, Any]:
    results = raw["worker_results"]
    if len(results) != workers or any(len(item["losses"]) != measured for item in results):
        raise ValueError("Measured worker iteration count does not match configuration")
    windows = [item["measurement"] for item in results]
    elapsed = max(item["end"] for item in windows) - min(item["start"] for item in windows)
    if not np.isfinite(elapsed) or elapsed <= 0 or any(item["sample_drops"] for item in windows):
        raise ValueError("Invalid or incomplete measurement window")
    samples = [sample for item in windows for sample in item["rpc_samples"]]
    for item in windows:
        pushes = [
            sample
            for sample in item["rpc_samples"]
            if sample["method"] == "PushGradients" and sample["status"] == "OK"
        ]
        if len(pushes) != measured * shards:
            raise ValueError("Successful push count does not match measured contributions")
    row = {
        "mode": raw["mode"],
        "commit": raw["environment"]["commit"],
        "source_dirty": raw["environment"]["source_dirty"],
        "window_seconds": elapsed,
        "worker_steps_per_second": measured * workers / elapsed,
        "examples_per_second": measured * workers * raw["workload"]["samples_per_worker"] / elapsed,
        "protobuf_bytes": sum(item["request_bytes"] + item["response_bytes"] for item in samples),
        "rpc_calls": len(samples),
        "rpc_failures": sum(item["status"] != "OK" for item in samples),
        "loss_after_warmup": raw["warmup"]["loss"],
        "final_loss": raw["final_loss"],
        "max_parameter_error": raw["max_parameter_error"],
        "shard_commit_deltas": ",".join(
            str(after - before)
            for before, after in zip(
                raw["warmup"]["shard_versions"], raw["shard_versions"], strict=True
            )
        ),
    }
    for label, method in (("push", "PushGradients"), ("pull", "PullParameters")):
        durations = [
            item["duration_seconds"]
            for item in samples
            if item["method"] == method and item["status"] == "OK"
        ]
        if not durations or not all(np.isfinite(value) and value > 0 for value in durations):
            raise ValueError("Missing or invalid successful RPC observations")
        row[f"{label}_p95_seconds"] = float(np.percentile(durations, 95))
        row[f"{label}_mean_request_bytes"] = float(
            np.mean([item["request_bytes"] for item in samples if item["method"] == method])
        )
    return row


def render(report: dict[str, Any], output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(2, 2, figsize=(11, 8))
    modes = report["configuration"]["modes"]
    for axis, key, title, scale in zip(
        axes.flat,
        ("examples_per_second", "push_p95_seconds", "pull_p95_seconds", "final_loss"),
        (
            "Measured examples / second",
            "Successful push p95 · ms",
            "Successful pull p95 · ms",
            "Final full-dataset MSE",
        ),
        (1, 1000, 1000, 1),
        strict=True,
    ):
        for index, mode in enumerate(modes):
            values = [row[key] * scale for row in report["trials"] if row["mode"] == mode]
            median = float(np.median(values))
            axis.errorbar(
                index,
                median,
                yerr=[[median - min(values)], [max(values) - median]],
                fmt="_",
                color="black",
                capsize=5,
                markersize=18,
            )
            offsets = np.linspace(-0.07, 0.07, len(values))
            offsets -= offsets.mean()
            axis.scatter(index + offsets, values, s=28)
        axis.set_xticks(range(len(modes)), modes)
        axis.set_xlim(-0.5, len(modes) - 0.5)
        axis.set_title(title)
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", alpha=0.2)
    figure.suptitle("ParamMesh · uncompressed CPU measurements", fontsize=16)
    figure.text(
        0.5,
        0.025,
        "Dots: recorded trials; bars: median and observed range.\n"
        "Equal worker iterations have different SGD-commit semantics across modes.\n"
        "Warm-process window includes registration/channel setup; background load is uncontrolled.",
        ha="center",
        fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.1, 1, 0.94))
    try:
        figure.savefig(output / "overview.png", dpi=160)
        figure.savefig(output / "overview.svg")
    finally:
        plt.close(figure)


def run_benchmarks(
    output: Path,
    *,
    modes: tuple[str, ...] = ("sync", "async", "bounded"),
    repetitions: int = 3,
    warmup_steps: int = 20,
    measured_steps: int = 200,
    workers: int = 2,
    shards: int = 2,
    hidden_width: int = 8,
) -> dict[str, Any]:
    counts = (repetitions, warmup_steps, measured_steps, workers, shards, hidden_width)
    if (
        any(type(value) is not int for value in counts)
        or not 1 <= repetitions <= 30
        or not 1 <= warmup_steps <= 1000
        or not 1 <= measured_steps <= 5000
        or not 1 <= workers <= 8
        or not 1 <= shards <= 4
        or not 1 <= hidden_width <= 32768
        or not modes
        or len(set(modes)) != len(modes)
        or any(mode not in MODES for mode in modes)
    ):
        raise ValueError("Invalid benchmark modes, repetitions, warm-up, steps or topology")
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    lock = root / "uv.lock"
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "captured_at": datetime.now(UTC).isoformat(),
        "configuration": {
            "modes": list(modes),
            "repetitions": repetitions,
            "warmup_steps": warmup_steps,
            "measured_steps": measured_steps,
            "workers": workers,
            "shards": shards,
            "hidden_width": hidden_width,
            "compression": "none",
        },
        "hardware": hardware(),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
        "trials": [],
        "window": (
            "warm processes, fresh measured session including channel setup, "
            "registration/fencing and final heartbeat"
        ),
    }
    _json(output / "manifest.json", report)
    try:
        with (
            (output / "rpc.csv").open("w", newline="", encoding="utf-8") as rpc_file,
            (output / "trials.csv").open("w", newline="", encoding="utf-8") as trial_file,
        ):
            rpc_writer = csv.DictWriter(
                rpc_file,
                fieldnames=[
                    "trial",
                    "mode",
                    "worker_id",
                    "method",
                    "status",
                    "duration_seconds",
                    "request_bytes",
                    "response_bytes",
                ],
            )
            rpc_writer.writeheader()
            trial_writer = None
            for repeat in range(repetitions):
                order = modes[repeat % len(modes) :] + modes[: repeat % len(modes)]
                for mode in order:
                    index = len(report["trials"])
                    raw = run_demo(
                        mode=mode,
                        steps=warmup_steps + measured_steps,
                        warmup_steps=warmup_steps,
                        workers=workers,
                        shards=shards,
                        hidden_width=hidden_width,
                        output=output / f"trial-{index:03d}-{mode}.json",
                    )
                    row = {
                        "trial": index,
                        "repetition": repeat + 1,
                        **_summary(raw, measured_steps, workers, shards),
                    }
                    for worker in raw["worker_results"]:
                        for sample in worker["measurement"]["rpc_samples"]:
                            rpc_writer.writerow(
                                {
                                    "trial": index,
                                    "mode": mode,
                                    "worker_id": worker["worker_id"],
                                    **sample,
                                }
                            )
                    if trial_writer is None:
                        trial_writer = csv.DictWriter(trial_file, fieldnames=list(row))
                        trial_writer.writeheader()
                    trial_writer.writerow(row)
                    rpc_file.flush()
                    trial_file.flush()
                    report["trials"].append(row)
                    _json(output / "manifest.json", report)
        render(report, output)
        report["status"] = "complete"
    except BaseException as error:
        report.update(status="failed", failure_type=type(error).__name__)
        _json(output / "manifest.json", report)
        raise
    _json(output / "manifest.json", report)
    return report
