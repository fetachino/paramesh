"""Launch independent processes and record an honest, repeatable CPU smoke run."""

import json
import multiprocessing as mp
import platform
import subprocess
import tempfile
import time
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any, Protocol

import grpc
import numpy as np

from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel
from paramesh.services import coordinator_server, managed_coordinator, shard_server
from paramesh.shard import ParameterShard
from paramesh.state import StateDB
from paramesh.tensors import decode_many, partition

MODES = {"sync": pb.SYNCHRONOUS, "async": pb.ASYNCHRONOUS, "bounded": pb.BOUNDED_STALENESS}


class ProcessPipe(Protocol):
    """Common interface of POSIX Connection and Windows PipeConnection."""

    def send(self, value: Any) -> None: ...
    def recv(self) -> Any: ...
    def poll(self, timeout: float = 0) -> bool: ...
    def close(self) -> None: ...


def _serve(
    kind: str,
    serialized: bytes,
    index: int,
    pipe: ProcessPipe,
    *,
    state_path: Path | None = None,
    address: str = "127.0.0.1:0",
    fast_leases: bool = False,
    security: RpcSecurity | None = None,
) -> None:
    server = None
    storage = None
    try:
        storage = StateDB(state_path) if state_path is not None else None
        config = pb.RunConfig()
        config.ParseFromString(serialized)
        if kind == "coordinator":
            coordinator = managed_coordinator(
                config,
                state=storage,
                suspect_after=1.5 if fast_leases else 5,
                unavailable_after=3 if fast_leases else 15,
                security=security,
            )
            server, port = coordinator_server(coordinator, address, security=security)
        else:
            from paramesh.workload import parameters

            values = parameters()
            ownership = partition(values, len(config.shard_endpoints))
            shard = ParameterShard(
                config, {k: v for k, v in values.items() if ownership[k] == index}, state=storage
            )
            server, port = shard_server(shard, address, security=security)
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
        if storage is not None:
            storage.close()
        pipe.close()


def _train(
    address: str,
    worker_id: str,
    steps: int,
    pipe: ProcessPipe,
    *,
    state_path: Path | None = None,
    step_delay: float = 0,
    security: RpcSecurity | None = None,
) -> None:
    from paramesh.worker import train_worker

    storage = StateDB(state_path) if state_path is not None else None
    try:
        pipe.send(
            train_worker(
                address, worker_id, steps, state=storage, step_delay=step_delay, security=security
            )
        )
    except Exception as error:
        pipe.send({"error": f"{type(error).__name__}: {error}"})
        raise
    finally:
        if storage is not None:
            storage.close()
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
    failure: str | None = None,
) -> dict[str, Any]:
    if mode not in MODES or steps < 1 or not 1 <= workers <= 8 or not 1 <= shards <= 4:
        raise ValueError("Use sync/async/bounded, positive steps, 1..8 workers and 1..4 shards")
    if failure not in (None, "worker", "shard") or (failure and (mode != "sync" or steps < 15)):
        raise ValueError("Failure evidence currently requires sync mode and at least 15 steps")
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
    security = RpcSecurity.ephemeral()
    failure_report: dict[str, Any] | None = None
    with ExitStack() as stack:
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="paramesh-")))
        processes: dict[str, BaseProcess] = {}

        def start(name: str, target: Any, *arguments: Any, **options: Any) -> ProcessPipe:
            options["security"] = security if target is _serve else RpcSecurity(security.token)
            parent, child = context.Pipe()
            process = context.Process(target=target, args=(*arguments, child), kwargs=options)
            process.start()
            child.close()
            processes[name] = process
            stack.callback(_cleanup, process, parent)
            return parent

        endpoints = []
        shard_configuration = config.SerializeToString()
        # Each shard binds an OS-assigned port and reports it before workers start.
        for index in range(shards):
            pipe = start(
                f"shard-{index}",
                _serve,
                "shard",
                shard_configuration,
                index,
                state_path=directory / f"shard-{index}.sqlite",
            )
            endpoints.append(_receive(pipe)["address"])
        config.shard_endpoints[:] = endpoints
        coordinator_pipe = start(
            "coordinator",
            _serve,
            "coordinator",
            config.SerializeToString(),
            0,
            state_path=directory / "coordinator.sqlite",
            fast_leases=bool(failure),
        )
        address = _receive(coordinator_pipe)["address"]
        started = time.perf_counter()
        worker_pipes = [
            start(
                name,
                _train,
                address,
                name,
                steps,
                state_path=directory / f"{name}.sqlite",
                step_delay=0.1 if failure else 0,
            )
            for name in config.worker_ids
        ]
        if failure:
            with open_channel(address, security) as channel:
                observer = rpc.CoordinatorStub(channel)

                def worker_state() -> pb.WorkerState | None:
                    status = observer.GetStatus(pb.Empty(), timeout=2)
                    return next(
                        (item for item in status.workers if item.worker_id == "worker-0"), None
                    )

                def wait_for(predicate: Any) -> Any:
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        for name, process in processes.items():
                            if (
                                name.startswith("worker-")
                                and name not in expected_dead
                                and process.exitcode not in (None, 0)
                            ):
                                raise RuntimeError(
                                    f"Worker {name} exited during the failure scenario"
                                )
                        value = predicate()
                        if value:
                            return value
                        time.sleep(0.05)
                    raise TimeoutError("Failure scenario did not reach the required live state")

                def active_worker() -> pb.WorkerState | None:
                    item = worker_state()
                    if item and 2 <= item.step < steps - 1 and item.health == "healthy":
                        return item
                    return None

                expected_dead: set[str] = set()
                active = wait_for(active_worker)
                killed_at = time.monotonic()
                victim = "worker-0" if failure == "worker" else "shard-0"
                expected_dead.add(victim)
                processes[victim].terminate()
                processes[victim].join(timeout=5)
                if failure == "worker":
                    wait_for(lambda: (item := worker_state()) and item.health == "unavailable")
                    detected_at = time.monotonic()
                    worker_pipes[0] = start(
                        "worker-0",
                        _train,
                        address,
                        "worker-0",
                        steps,
                        state_path=directory / "worker-0.sqlite",
                        step_delay=0.1,
                    )
                    expected_dead.discard("worker-0")
                    wait_for(
                        lambda: (item := worker_state())
                        and item.generation > active.generation
                        and item.step > active.step
                    )
                    detector = "coordinator heartbeat lease"
                else:
                    with open_channel(endpoints[0], security) as shard_channel:
                        try:
                            rpc.ParameterShardStub(shard_channel).GetProgress(
                                pb.PullRequest(run_id=config.run_id), timeout=0.5
                            )
                        except grpc.RpcError:
                            pass
                        else:
                            raise RuntimeError("Terminated shard unexpectedly remained reachable")
                    detected_at = time.monotonic()
                    replacement = start(
                        "shard-0",
                        _serve,
                        "shard",
                        shard_configuration,
                        0,
                        state_path=directory / "shard-0.sqlite",
                        address=endpoints[0],
                    )
                    _receive(replacement)
                    wait_for(lambda: (item := worker_state()) and item.step > active.step)
                    detector = "observer RPC failure"
                failure_report = {
                    "terminated_component": victim,
                    "detector": detector,
                    "worker_step_before_failure": active.step,
                    "lease_suspect_seconds": 1.5,
                    "lease_unavailable_seconds": 3,
                    "step_delay_seconds": 0.1,
                    "detection_seconds": detected_at - killed_at,
                    "recovery_seconds_until_progress": time.monotonic() - killed_at,
                    "uncommitted_computation_lost": "not instrumented",
                }
        results = [_receive(pipe) for pipe in worker_pipes]
        elapsed = time.perf_counter() - started
        snapshots = []
        for endpoint in endpoints:
            with open_channel(endpoint, security) as channel:
                snapshots.append(
                    rpc.ParameterShardStub(channel).PullParameters(
                        pb.PullRequest(run_id=config.run_id), timeout=5
                    )
                )
        final = decode_many(tensor for snapshot in snapshots for tensor in snapshot.tensors)
        with open_channel(address, security) as channel:
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
        "worker_generations": {worker.worker_id: worker.generation for worker in state.workers},
        "ownership": partition(initial, shards),
        "initial_loss": loss(initial),
        "final_loss": loss(final),
        "max_parameter_error": max(
            float(np.max(np.abs(final[name] - reference[name]))) for name in final
        )
        if reference is not None
        else None,
        "worker_results": results,
        "failure": failure_report,
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
    if reference is not None and report["max_parameter_error"] >= 1e-6:
        raise RuntimeError("Distributed parameters diverged from the equivalent local reference")
    return report
