"""Launch independent processes and record an honest, repeatable CPU smoke run."""

import json
import multiprocessing as mp
import platform
import subprocess
import time
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any, Protocol

import grpc
import numpy as np

from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.services import CHANNEL_OPTIONS, coordinator_server, shard_server
from paramesh.shard import ParameterShard
from paramesh.tensors import decode_many, partition

MODES = {"sync": pb.SYNCHRONOUS, "async": pb.ASYNCHRONOUS, "bounded": pb.BOUNDED_STALENESS}


class ProcessPipe(Protocol):
    """Common interface of POSIX Connection and Windows PipeConnection."""

    def send(self, value: Any) -> None: ...
    def recv(self) -> Any: ...
    def poll(self, timeout: float = 0) -> bool: ...
    def close(self) -> None: ...


def _serve(kind: str, serialized: bytes, index: int, pipe: ProcessPipe) -> None:
    server = None
    try:
        config = pb.RunConfig()
        config.ParseFromString(serialized)
        if kind == "coordinator":
            server, port = coordinator_server(Coordinator(config), "127.0.0.1:0")
        else:
            from paramesh.workload import parameters

            values = parameters()
            ownership = partition(values, len(config.shard_endpoints))
            shard = ParameterShard(
                config, {k: v for k, v in values.items() if ownership[k] == index}
            )
            server, port = shard_server(shard, "127.0.0.1:0")
        server.start()
        pipe.send({"address": f"127.0.0.1:{port}"})
        pipe.recv()
    except EOFError:
        pass
    except Exception as error:
        pipe.send({"error": f"{type(error).__name__}: {error}"})
    finally:
        if server is not None:
            server.stop(0).wait()
        pipe.close()


def _train(address: str, worker_id: str, steps: int, pipe: ProcessPipe) -> None:
    from paramesh.worker import train_worker

    try:
        pipe.send(train_worker(address, worker_id, steps))
    except Exception as error:
        pipe.send({"error": f"{type(error).__name__}: {error}"})
    finally:
        pipe.close()


def _receive(pipe: ProcessPipe, timeout: float = 120) -> dict[str, Any]:
    if not pipe.poll(timeout):
        raise TimeoutError("Child process did not respond before the demo deadline")
    message: dict[str, Any] = pipe.recv()
    if "error" in message:
        raise RuntimeError(message["error"])
    return message


def _cleanup(process: BaseProcess, pipe: ProcessPipe) -> None:
    if process.is_alive():
        try:
            pipe.send("stop")
        except (BrokenPipeError, EOFError, OSError):
            pass
        process.join(timeout=3)
        if process.is_alive():
            process.terminate()
    process.join(timeout=5)
    pipe.close()
    process.close()


def run_demo(
    *,
    mode: str = "sync",
    steps: int = 20,
    workers: int = 2,
    shards: int = 2,
    output: Path | None = None,
) -> dict[str, Any]:
    if mode not in MODES or steps < 1 or not 1 <= workers <= 8 or not 1 <= shards <= 4:
        raise ValueError("Use sync/async/bounded, positive steps, 1..8 workers and 1..4 shards")
    import torch

    from paramesh.workload import dataset, load_parameters, local_reference, model, parameters

    torch.set_num_threads(1)
    config = pb.RunConfig(
        run_id=f"demo-{uuid.uuid4().hex[:12]}",
        mode=MODES[mode],
        shard_endpoints=[f"pending-{i}:0" for i in range(shards)],
        worker_ids=[f"worker-{i}" for i in range(workers)],
        learning_rate=0.05,
        max_staleness=1,
        barrier_timeout_seconds=15,
    )
    context = mp.get_context("spawn")
    with ExitStack() as stack:

        def start(target: Any, *arguments: Any) -> ProcessPipe:
            parent, child = context.Pipe()
            process = context.Process(target=target, args=(*arguments, child))
            process.start()
            child.close()
            stack.callback(_cleanup, process, parent)
            return parent

        endpoints = []
        # Each shard binds an OS-assigned port and reports it before workers start.
        for index in range(shards):
            pipe = start(_serve, "shard", config.SerializeToString(), index)
            endpoints.append(_receive(pipe)["address"])
        config.shard_endpoints[:] = endpoints
        coordinator_pipe = start(_serve, "coordinator", config.SerializeToString(), 0)
        address = _receive(coordinator_pipe)["address"]
        started = time.perf_counter()
        worker_pipes = [start(_train, address, name, steps) for name in config.worker_ids]
        results = [_receive(pipe) for pipe in worker_pipes]
        elapsed = time.perf_counter() - started
        snapshots = []
        for endpoint in endpoints:
            with grpc.insecure_channel(endpoint, options=CHANNEL_OPTIONS) as channel:
                snapshots.append(
                    rpc.ParameterShardStub(channel).PullParameters(
                        pb.PullRequest(run_id=config.run_id), timeout=5
                    )
                )
        final = decode_many(tensor for snapshot in snapshots for tensor in snapshot.tensors)
        with grpc.insecure_channel(address, options=CHANNEL_OPTIONS) as channel:
            state = rpc.CoordinatorStub(channel).GetStatus(pb.Empty(), timeout=5)
    initial = parameters()
    reference = local_reference(workers, steps, config.learning_rate) if mode == "sync" else None
    evaluation = model()
    batches = [dataset(index) for index in range(workers)]
    inputs = torch.cat([batch[0] for batch in batches])
    targets = torch.cat([batch[1] for batch in batches])

    def loss(values: dict[str, Any]) -> float:
        load_parameters(evaluation, values)
        with torch.no_grad():
            return float(torch.nn.functional.mse_loss(evaluation(inputs), targets))

    root = Path(__file__).resolve().parents[2]
    commit = "unknown"
    dirty = None
    if (root / ".git").exists():
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            dirty = bool(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=root, text=True
                ).strip()
            )
        except (OSError, subprocess.CalledProcessError):
            pass
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_id": config.run_id,
        "mode": mode,
        "steps_per_worker": steps,
        "worker_count": workers,
        "shard_count": shards,
        "process_count": 1 + workers + shards,
        "shard_versions": [snapshot.version for snapshot in snapshots],
        "worker_health": {worker.worker_id: worker.health for worker in state.workers},
        "ownership": partition(initial, shards),
        "initial_loss": loss(initial),
        "final_loss": loss(final),
        "max_parameter_error": max(
            float(np.max(np.abs(final[name] - reference[name]))) for name in final
        )
        if reference is not None
        else None,
        "worker_results": results,
        "worker_wall_seconds_including_startup": elapsed,
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "os": platform.system(),
            "machine": platform.machine(),
            "commit": commit,
            "source_dirty": dirty,
            "captured_at": datetime.now(UTC).isoformat(),
        },
        "workload": {
            "model": "MLP 4-8-1, tanh",
            "dataset": "synthetic regression",
            "samples_per_worker": 32,
            "model_seed": 7,
            "data_seed_base": 100,
            "learning_rate": config.learning_rate,
            "aggregation": "mean",
            "optimizer": "SGD",
            "device": "cpu",
            "torch_threads": 1,
        },
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
