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
from paramesh.workload import TrainingWorkload, bundled_workload, load_parameters


def _rpc(method: Any, request: Any, timeout: float, *, retry_deadline: bool = True) -> Any:
    for attempt in range(3):
        try:
            return method(request, timeout=timeout, wait_for_ready=True)
        except grpc.RpcError as error:
            retryable = error.code() == grpc.StatusCode.UNAVAILABLE or (
                error.code() == grpc.StatusCode.DEADLINE_EXCEEDED and retry_deadline
            )
            if not retryable or attempt == 2:
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
    workload: TrainingWorkload | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    if steps < 1 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("steps and timeout must be positive")
    if not math.isfinite(step_delay) or step_delay < 0:
        raise ValueError("step_delay must be finite and nonnegative")
    try:
        training_device = torch.device(device)
    except RuntimeError as error:
        raise ValueError(f"Unsupported training device: {device}") from error
    if training_device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA training requested but this PyTorch runtime has no CUDA device")
    torch.set_num_threads(1)
    active_workload = workload or bundled_workload(hidden_width)
    network = active_workload.model_factory().to(training_device)
    progress = [0, 0]
    checkpoint_epoch = [0]
    progress_lock = threading.Lock()
    stopped = threading.Event()
    checkpoint_requested = threading.Event()
    heartbeat_errors: list[Exception] = []
    with ExitStack() as stack:
        channel = stack.enter_context(open_channel(address, security))
        grpc.channel_ready_future(channel).result(timeout=timeout)
        coordinator_ref = [rpc.CoordinatorStub(channel)]
        session = _register(coordinator_ref[0], worker_id, timeout)
        config = session.config
        session_lock = threading.Lock()
        session_ref = [session]
        session_ready = threading.Event()
        session_ready.set()
        inputs, targets = active_workload.dataset_factory(list(config.worker_ids).index(worker_id))
        inputs, targets = inputs.to(training_device), targets.to(training_device)
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
                    with session_lock:
                        current = session_ref[0]
                    state = _rpc(
                        coordinator_ref[0].Heartbeat,
                        pb.HeartbeatRequest(
                            run_id=config.run_id,
                            worker_id=worker_id,
                            session_id=current.session_id,
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
                if not isinstance(error, grpc.RpcError) or error.code() not in (
                    grpc.StatusCode.UNAVAILABLE,
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                    grpc.StatusCode.CANCELLED,
                    grpc.StatusCode.PERMISSION_DENIED,
                ):
                    heartbeat_errors.append(error)
                    return
                # Re-registering on the same endpoint lets a replacement coordinator fence
                # the old generation at every shard before training resumes.
                session_ready.clear()
                while not stopped.is_set():
                    try:
                        replacement_channel = stack.enter_context(open_channel(address, security))
                        try:
                            grpc.channel_ready_future(replacement_channel).result(timeout=timeout)
                        except grpc.FutureTimeoutError:
                            stopped.wait(0.2)
                            continue
                        replacement_stub = rpc.CoordinatorStub(replacement_channel)
                        replacement = _register(replacement_stub, worker_id, timeout)
                        coordinator_ref[0] = replacement_stub
                    except grpc.RpcError as retry_error:
                        if retry_error.code() not in (
                            grpc.StatusCode.UNAVAILABLE,
                            grpc.StatusCode.DEADLINE_EXCEEDED,
                            grpc.StatusCode.CANCELLED,
                            grpc.StatusCode.ALREADY_EXISTS,
                        ):
                            heartbeat_errors.append(retry_error)
                            return
                        stopped.wait(0.2)
                        continue
                    with session_lock:
                        session_ref[0] = replacement
                    with progress_lock:
                        step, version = progress
                    try:
                        _rpc(
                            coordinator_ref[0].Heartbeat,
                            pb.HeartbeatRequest(
                                run_id=config.run_id,
                                worker_id=worker_id,
                                session_id=replacement.session_id,
                                step=step,
                                parameter_version=version,
                            ),
                            timeout,
                        )
                    except grpc.RpcError as retry_error:
                        if retry_error.code() in (
                            grpc.StatusCode.UNAVAILABLE,
                            grpc.StatusCode.DEADLINE_EXCEEDED,
                            grpc.StatusCode.CANCELLED,
                            grpc.StatusCode.PERMISSION_DENIED,
                            grpc.StatusCode.ALREADY_EXISTS,
                        ):
                            continue
                        heartbeat_errors.append(retry_error)
                        return
                    session_ready.set()
                    return

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
                coordinator_ref[0].AcknowledgeCheckpoint,
                pb.CheckpointAck(
                    run_id=config.run_id,
                    worker_id=worker_id,
                    session_id=session_ref[0].session_id,
                    epoch=epoch,
                    step=step,
                    parameter_version=version,
                    worker_journal=journal.record.SerializeToString(deterministic=True),
                ),
                timeout,
            )
            request = pb.CheckpointRequest(run_id=config.run_id, worker_id=worker_id)
            while not stopped.is_set():
                control = _rpc(coordinator_ref[0].GetCheckpointControl, request, timeout)
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
                                        encode(name, parameter.grad.detach().cpu().numpy())
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
                            with session_lock:
                                current = session_ref[0]
                            request.generation = current.generation
                            try:
                                result: pb.UpdateResult = _rpc(
                                    client.PushGradients, request, timeout, retry_deadline=False
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
                                if error.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                                    # A synchronous barrier can abort after the peer lease is
                                    # lost.  Keep the durable journal and inspect progress before
                                    # replaying so a lost response cannot duplicate an update.
                                    progress_state = _rpc(
                                        clients[index].GetProgress,
                                        pb.PullRequest(run_id=config.run_id),
                                        timeout,
                                    )
                                    position = progress_state.next_steps[worker_id]
                                    if position > step:
                                        accepted.add(index)
                                        committed_versions[index] = progress_state.version
                                        continue
                                    if position != step:
                                        raise RuntimeError(
                                            "Shard progress crossed the worker step after a "
                                            "synchronous RPC deadline"
                                        ) from error
                                    break
                                if error.code() == grpc.StatusCode.PERMISSION_DENIED:
                                    session_ready.wait(timeout=timeout)
                                    with session_lock:
                                        reconnected = session_ref[0].generation > current.generation
                                    if reconnected:
                                        continue
                                    # The replacement may still be fencing the previous
                                    # generation; keep the durable journal and retry rather
                                    # than treating the transient denial as a fatal loss.
                                    continue
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
            # A checkpoint can begin after the final training step and after the
            # heartbeat thread's last poll. Do not mark this worker completed
            # until that requested epoch has received its durable acknowledgment.
            control = _rpc(
                coordinator_ref[0].GetCheckpointControl,
                pb.CheckpointRequest(run_id=config.run_id, worker_id=worker_id),
                timeout,
            )
            if control.phase == pb.CHECKPOINT_REQUESTED:
                with progress_lock:
                    checkpoint_epoch[0] = control.epoch
                checkpoint_requested.set()
                wait_for_checkpoint()
            if not session_ready.wait(timeout=timeout):
                raise RuntimeError("Coordinator replacement session was not restored")
            stopped.set()
            thread.join(timeout=timeout + 1)
            if heartbeat_errors:
                raise RuntimeError("Coordinator heartbeat failed") from heartbeat_errors[0]
            for _ in range(3):
                with session_lock:
                    current = session_ref[0]
                try:
                    _rpc(
                        coordinator_ref[0].Heartbeat,
                        pb.HeartbeatRequest(
                            run_id=config.run_id,
                            worker_id=worker_id,
                            session_id=current.session_id,
                            step=progress[0],
                            parameter_version=progress[1],
                            completed=True,
                        ),
                        timeout,
                    )
                    break
                except grpc.RpcError as error:
                    if error.code() != grpc.StatusCode.PERMISSION_DENIED:
                        raise
                    replacement = _register(coordinator_ref[0], worker_id, timeout)
                    with session_lock:
                        session_ref[0] = replacement
            else:
                raise RuntimeError("Coordinator completion session was not accepted")
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
