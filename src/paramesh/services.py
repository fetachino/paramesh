"""Bounded gRPC adapters; domain errors become intentional protocol statuses."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import grpc

from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.shard import ParameterShard
from paramesh.tensors import MAX_MESSAGE_BYTES

CHANNEL_OPTIONS = [
    ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
    ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
]


def _call[T](context: Any, operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ValueError as error:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))
    except PermissionError as error:
        context.abort(grpc.StatusCode.PERMISSION_DENIED, str(error))
    except TimeoutError as error:
        context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, str(error))
    raise AssertionError("gRPC abort must not return")


class CoordinatorService:
    def __init__(self, coordinator: Coordinator) -> None:
        self.coordinator = coordinator

    def RegisterWorker(self, request: pb.RegisterWorkerRequest, context: Any) -> pb.WorkerSession:
        return _call(
            context, lambda: self.coordinator.register(request.worker_id, request.protocol_version)
        )

    def Heartbeat(self, request: pb.HeartbeatRequest, context: Any) -> pb.WorkerState:
        return _call(context, lambda: self.coordinator.heartbeat(request))

    def GetStatus(self, request: pb.Empty, context: Any) -> pb.RunStatus:
        return self.coordinator.status()


class ShardService:
    def __init__(self, shard: ParameterShard) -> None:
        self.shard = shard

    def PullParameters(self, request: pb.PullRequest, context: Any) -> pb.Parameters:
        return _call(context, lambda: self.shard.pull(request.run_id))

    def PushGradients(self, request: pb.GradientUpdate, context: Any) -> pb.UpdateResult:
        return _call(context, lambda: self.shard.push(request, timeout=context.time_remaining()))


def _server(address: str, concurrency: int) -> tuple[Any, int]:
    server = grpc.server(
        ThreadPoolExecutor(max_workers=concurrency),
        options=CHANNEL_OPTIONS,
        maximum_concurrent_rpcs=concurrency,
    )
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"Could not bind gRPC server to {address}")
    return server, port


def coordinator_server(coordinator: Coordinator, address: str) -> tuple[Any, int]:
    server, port = _server(address, 8)
    rpc.add_CoordinatorServicer_to_server(CoordinatorService(coordinator), server)
    return server, port


def shard_server(shard: ParameterShard, address: str) -> tuple[Any, int]:
    # Waiting synchronous RPCs must not occupy every thread and starve the final participant.
    server, port = _server(address, 2 * len(shard.config.worker_ids) + 4)
    rpc.add_ParameterShardServicer_to_server(ShardService(shard), server)
    return server, port
