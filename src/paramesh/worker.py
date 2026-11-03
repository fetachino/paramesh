"""PyTorch gradient producer; authoritative weights and SGD live on the shards."""

import math
import threading
import time
from contextlib import ExitStack
from typing import Any

import grpc
import torch

from paramesh import telemetry
from paramesh.journal import Journal
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel
from paramesh.state import StateDB
from paramesh.tensors import decode_many, encode, partition
from paramesh.workload import dataset, load_parameters, model


def _rpc(method: Any, request: Any, timeout: float) -> Any:
    for attempt in range(3):
        try:
            return method(request, timeout=timeout, wait_for_ready=True)
        except grpc.RpcError as error:
            if (
                error.code()
                not in (
                    grpc.StatusCode.UNAVAILABLE,
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                )
                or attempt == 2
            ):
                raise
            threading.Event().wait(0.1 * 2**attempt)
    raise AssertionError("Retry loop must return or raise")


def train_worker(
    address: str,
    worker_id: str,
    steps: int,
    *,
    timeout: float = 10,
    state: StateDB | None = None,
    step_delay: float = 0,
    security: RpcSecurity | None = None,
    hidden_width: int = 8,
) -> dict[str, Any]:
    if steps < 1 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("steps and timeout must be positive")
    if not math.isfinite(step_delay) or step_delay < 0:
        raise ValueError("step_delay must be finite and nonnegative")
    torch.set_num_threads(1)
    network = model(hidden_width)
    progress = [0, 0]
    checkpoint_epoch = [0]
    progress_lock = threading.Lock()
    stopped = threading.Event()
    checkpoint_requested = threading.Event()
    heartbeat_errors: list[Exception] = []
    with ExitStack() as stack:
        channel = stack.enter_context(open_channel(address, security))
        grpc.channel_ready_future(channel).result(timeout=timeout)
        coordinator = rpc.CoordinatorStub(channel)
        session = _register(coordinator, worker_id, timeout)
        config = session.config
        inputs, targets = dataset(list(config.worker_ids).index(worker_id))
        clients = [
            rpc.ParameterShardStub(stack.enter_context(open_channel(endpoint, security)))
            for endpoint in config.shard_endpoints
        ]
        ownership = partition(dict(network.named_parameters()), len(clients))
        journal = Journal(config, worker_id, state)
        resumed_from = journal.record.next_step
        if resumed_from > steps:
            raise ValueError("Requested training target precedes durable worker progress")
        statuses = [
            _rpc(client.GetProgress, pb.PullRequest(run_id=config.run_id), timeout)
            for client in clients
        ]
        progress[:] = [resumed_from, min(item.version for item in statuses)]

        def heartbeat() -> None:
            try:
                while not stopped.is_set():
                    with progress_lock:
                        step, version = progress
                    state = _rpc(
                        coordinator.Heartbeat,
                        pb.HeartbeatRequest(
                            run_id=config.run_id,
                            worker_id=worker_id,
                            session_id=session.session_id,
                            step=step,
                            parameter_version=version,
                        ),
                        timeout,
                    )
                    if state.checkpoint_phase == "CHECKPOINT_REQUESTED":
                        with progress_lock:
                            checkpoint_epoch[0] = state.checkpoint_epoch
                        checkpoint_requested.set()
                    stopped.wait(1)
            except Exception as error:
                heartbeat_errors.append(error)

        thread = threading.Thread(target=heartbeat, name=f"heartbeat-{worker_id}", daemon=True)
        thread.start()
        losses: list[float] = []
        refreshes = 0
        replayed = 0

        def wait_for_checkpoint() -> None:
            if not checkpoint_requested.is_set():
                return
            with progress_lock:
                step, version = progress
                epoch = checkpoint_epoch[0]
            _rpc(
                coordinator.AcknowledgeCheckpoint,
                pb.CheckpointAck(
                    run_id=config.run_id,
                    worker_id=worker_id,
                    session_id=session.session_id,
                    epoch=epoch,
                    step=step,
                    parameter_version=version,
                    worker_journal=journal.record.SerializeToString(deterministic=True),
                ),
                timeout,
            )
            request = pb.CheckpointRequest(run_id=config.run_id, worker_id=worker_id)
            while not stopped.is_set():
                control = _rpc(coordinator.GetCheckpointControl, request, timeout)
                if control.phase == pb.CHECKPOINT_RUNNING:
                    checkpoint_requested.clear()
                    return
                if heartbeat_errors:
                    raise RuntimeError("Coordinator heartbeat failed") from heartbeat_errors[0]
                stopped.wait(0.1)
            raise RuntimeError("Worker stopped while waiting for checkpoint release")

        try:
            for step in range(resumed_from, steps):
                with telemetry.span(
                    "worker.training_step", worker_id=worker_id, run_id=config.run_id, step=step
                ) as training_trace:
                    iteration_started = time.perf_counter()
                    statuses = [
                        _rpc(client.GetProgress, pb.PullRequest(run_id=config.run_id), timeout)
                        for client in clients
                    ]
                    positions = [item.next_steps[worker_id] for item in statuses]
                    if any(position not in (step, step + 1) for position in positions):
                        raise ValueError("Shard progress is inconsistent with the worker journal")
                    if not journal.record.requests and any(
                        position > step for position in positions
                    ):
                        raise ValueError(
                            "Missing durable gradient journal for a partially committed step"
                        )
                    accepted = {
                        index for index, position in enumerate(positions) if position > step
                    }
                    committed_versions = {
                        index: item.version
                        for index, item in enumerate(statuses)
                        if index in accepted
                    }
                    refresh = not bool(journal.record.requests)
                    if journal.record.requests:
                        replayed += len(clients) - len(accepted)
                    for _ in range(100):
                        if heartbeat_errors:
                            raise RuntimeError(
                                "Coordinator heartbeat failed"
                            ) from heartbeat_errors[0]
                        if refresh:
                            snapshots = [
                                _rpc(
                                    client.PullParameters,
                                    pb.PullRequest(run_id=config.run_id),
                                    timeout,
                                )
                                for client in clients
                            ]
                            values = decode_many(
                                tensor for item in snapshots for tensor in item.tensors
                            )
                            load_parameters(network, values)
                            network.zero_grad()
                            loss = torch.nn.functional.mse_loss(network(inputs), targets)
                            torch.autograd.backward(loss)
                            requests = list(journal.record.requests)
                            for index in range(len(clients)):
                                if index in accepted:
                                    continue
                                request = pb.GradientUpdate(
                                    run_id=config.run_id,
                                    worker_id=worker_id,
                                    step=step,
                                    base_version=snapshots[index].version,
                                    tensors=[
                                        encode(name, parameter.grad.detach().numpy())
                                        for name, parameter in network.named_parameters()
                                        if ownership[name] == index and parameter.grad is not None
                                    ],
                                )
                                if len(requests) == len(clients):
                                    requests[index] = request
                                else:
                                    requests.append(request)
                            journal.prepare(requests, float(loss.detach()))
                            refresh = False
                        for index, client in enumerate(clients):
                            if index in accepted:
                                continue
                            request = journal.record.requests[index]
                            request.generation = session.generation
                            try:
                                result: pb.UpdateResult = _rpc(
                                    client.PushGradients, request, timeout
                                )
                            except grpc.RpcError as error:
                                if (
                                    error.code() == grpc.StatusCode.DEADLINE_EXCEEDED
                                    and checkpoint_requested.is_set()
                                    and all(
                                        _rpc(
                                            shard.GetProgress,
                                            pb.PullRequest(run_id=config.run_id),
                                            timeout,
                                        ).next_steps[worker_id]
                                        == step
                                        for shard in clients
                                    )
                                ):
                                    journal.discard()
                                    wait_for_checkpoint()
                                    refresh = True
                                    break
                                if error.code() != grpc.StatusCode.FAILED_PRECONDITION:
                                    raise
                                refreshes += 1
                                telemetry.add("refreshes")
                                refresh = True
                                break
                            accepted.add(index)
                            committed_versions[index] = result.version
                        if len(accepted) == len(clients):
                            losses.append(journal.record.loss)
                            journal.complete()
                            with progress_lock:
                                progress[:] = [step + 1, min(committed_versions.values())]
                            telemetry.add("worker_steps")
                            telemetry.add("examples", len(inputs))
                            telemetry.set_value("loss", losses[-1])
                            telemetry.set_value("worker_step", step + 1, worker_id=worker_id)
                            telemetry.set_value("worker_version", progress[1], worker_id=worker_id)
                            telemetry.observe(
                                "step_duration_seconds", time.perf_counter() - iteration_started
                            )
                            if training_trace is not None:
                                training_trace.add_event(
                                    "step_completed",
                                    {"step": step + 1, "version": progress[1], "loss": losses[-1]},
                                )
                            break
                    else:
                        raise RuntimeError("Staleness refresh limit exceeded; run did not complete")
                stopped.wait(step_delay)
                wait_for_checkpoint()
            if heartbeat_errors:
                raise RuntimeError("Coordinator heartbeat failed") from heartbeat_errors[0]
            stopped.set()
            thread.join(timeout=timeout + 1)
            if heartbeat_errors:
                raise RuntimeError("Coordinator heartbeat failed") from heartbeat_errors[0]
            _rpc(
                coordinator.Heartbeat,
                pb.HeartbeatRequest(
                    run_id=config.run_id,
                    worker_id=worker_id,
                    session_id=session.session_id,
                    step=progress[0],
                    parameter_version=progress[1],
                    completed=True,
                ),
                timeout,
            )
            return {
                "worker_id": worker_id,
                "steps": steps,
                "losses": losses,
                "refreshes": refreshes,
                "resumed_from": resumed_from,
                "replayed_contributions": replayed,
            }
        finally:
            stopped.set()
            thread.join(timeout=timeout + 1)


def _register(coordinator: Any, worker_id: str, timeout: float) -> pb.WorkerSession:
    deadline = time.monotonic() + 120
    while True:
        try:
            session: pb.WorkerSession = coordinator.RegisterWorker(
                pb.RegisterWorkerRequest(worker_id=worker_id, protocol_version=1), timeout=timeout
            )
            return session
        except grpc.RpcError as error:
            if (
                error.code()
                not in (
                    grpc.StatusCode.ALREADY_EXISTS,
                    grpc.StatusCode.UNAVAILABLE,
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                )
                or time.monotonic() >= deadline
            ):
                raise
            threading.Event().wait(0.2)
