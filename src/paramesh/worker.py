"""PyTorch gradient producer; authoritative weights and SGD live on the shards."""

import threading
from contextlib import ExitStack
from typing import Any

import grpc
import torch

from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.services import CHANNEL_OPTIONS
from paramesh.tensors import decode_many, encode, partition
from paramesh.workload import dataset, load_parameters, model


def _push(client: Any, request: pb.GradientUpdate, timeout: float) -> pb.UpdateResult:
    for attempt in range(3):
        try:
            result: pb.UpdateResult = client.PushGradients(request, timeout=timeout)
            return result
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
    address: str, worker_id: str, steps: int, *, timeout: float = 10
) -> dict[str, Any]:
    if steps < 1 or timeout <= 0:
        raise ValueError("steps and timeout must be positive")
    torch.set_num_threads(1)
    network = model()
    progress = [0, 0]
    progress_lock = threading.Lock()
    stopped = threading.Event()
    heartbeat_errors: list[Exception] = []
    with ExitStack() as stack:
        channel = stack.enter_context(grpc.insecure_channel(address, options=CHANNEL_OPTIONS))
        grpc.channel_ready_future(channel).result(timeout=timeout)
        coordinator = rpc.CoordinatorStub(channel)
        session = coordinator.RegisterWorker(
            pb.RegisterWorkerRequest(worker_id=worker_id, protocol_version=1), timeout=timeout
        )
        config = session.config
        inputs, targets = dataset(list(config.worker_ids).index(worker_id))
        clients = [
            rpc.ParameterShardStub(
                stack.enter_context(grpc.insecure_channel(endpoint, options=CHANNEL_OPTIONS))
            )
            for endpoint in config.shard_endpoints
        ]
        ownership = partition(dict(network.named_parameters()), len(clients))

        def heartbeat() -> None:
            try:
                while not stopped.is_set():
                    with progress_lock:
                        step, version = progress
                    coordinator.Heartbeat(
                        pb.HeartbeatRequest(
                            run_id=config.run_id,
                            worker_id=worker_id,
                            session_id=session.session_id,
                            step=step,
                            parameter_version=version,
                        ),
                        timeout=timeout,
                    )
                    stopped.wait(1)
            except Exception as error:
                heartbeat_errors.append(error)

        thread = threading.Thread(target=heartbeat, name=f"heartbeat-{worker_id}", daemon=True)
        thread.start()
        losses: list[float] = []
        refreshes = 0
        try:
            for step in range(steps):
                accepted: set[int] = set()
                committed_versions: dict[int, int] = {}
                for _ in range(100):
                    if heartbeat_errors:
                        raise RuntimeError("Coordinator heartbeat failed") from heartbeat_errors[0]
                    snapshots = [
                        client.PullParameters(pb.PullRequest(run_id=config.run_id), timeout=timeout)
                        for client in clients
                    ]
                    values = decode_many(tensor for item in snapshots for tensor in item.tensors)
                    load_parameters(network, values)
                    network.zero_grad()
                    loss = torch.nn.functional.mse_loss(network(inputs), targets)
                    torch.autograd.backward(loss)
                    for index, client in enumerate(clients):
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
                        try:
                            result = _push(client, request, timeout)
                        except grpc.RpcError as error:
                            if error.code() != grpc.StatusCode.FAILED_PRECONDITION:
                                raise
                            refreshes += 1
                            break
                        accepted.add(index)
                        committed_versions[index] = result.version
                    if len(accepted) == len(clients):
                        losses.append(float(loss.detach()))
                        with progress_lock:
                            progress[:] = [step + 1, min(committed_versions.values())]
                        break
                else:
                    raise RuntimeError("Staleness refresh limit exceeded; run did not complete")
            if heartbeat_errors:
                raise RuntimeError("Coordinator heartbeat failed") from heartbeat_errors[0]
            stopped.set()
            thread.join(timeout=timeout + 1)
            if heartbeat_errors:
                raise RuntimeError("Coordinator heartbeat failed") from heartbeat_errors[0]
            coordinator.Heartbeat(
                pb.HeartbeatRequest(
                    run_id=config.run_id,
                    worker_id=worker_id,
                    session_id=session.session_id,
                    step=progress[0],
                    parameter_version=progress[1],
                    completed=True,
                ),
                timeout=timeout,
            )
            return {
                "worker_id": worker_id,
                "steps": steps,
                "losses": losses,
                "refreshes": refreshes,
            }
        finally:
            stopped.set()
            thread.join(timeout=timeout + 1)
