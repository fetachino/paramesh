"""Bounded gRPC adapters; domain errors become intentional protocol statuses."""

import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import grpc

from paramesh.coordinator import Coordinator, WorkerAlreadyRegistered
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import CHANNEL_OPTIONS, RpcSecurity, ServerAuth, open_channel
from paramesh.shard import ParameterShard, StaleGradientError
from paramesh.state import StateDB


def _call[T](context: Any, operation: Callable[[], T]) -> T:
    try:
        return operation()
    except StaleGradientError as error:
        context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(error))
    except WorkerAlreadyRegistered as error:
        context.abort(grpc.StatusCode.ALREADY_EXISTS, str(error))
    except ValueError as error:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))
    except PermissionError as error:
        context.abort(grpc.StatusCode.PERMISSION_DENIED, str(error))
    except TimeoutError as error:
        context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, str(error))
    except grpc.RpcError:
        context.abort(grpc.StatusCode.UNAVAILABLE, "A dependent service is unavailable")
    except (OSError, sqlite3.Error):
        context.abort(grpc.StatusCode.INTERNAL, "Durable state is unavailable")
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

    def GetProgress(self, request: pb.PullRequest, context: Any) -> pb.ShardProgress:
        return _call(context, lambda: self.shard.progress(request.run_id))

    def FenceWorker(self, request: pb.FenceRequest, context: Any) -> pb.Empty:
        _call(
            context, lambda: self.shard.fence(request.run_id, request.worker_id, request.generation)
        )
        return pb.Empty()


def managed_coordinator(
    config: pb.RunConfig,
    *,
    state: StateDB | None = None,
    suspect_after: float = 5,
    unavailable_after: float = 15,
    security: RpcSecurity | None = None,
) -> Coordinator:
    def fence(worker_id: str, generation: int) -> None:
        for endpoint in config.shard_endpoints:
            with open_channel(endpoint, security, admin=True) as channel:
                rpc.ParameterShardStub(channel).FenceWorker(
                    pb.FenceRequest(
                        run_id=config.run_id,
                        worker_id=worker_id,
                        generation=generation,
                    ),
                    timeout=5,
                )

    return Coordinator(
        config,
        state=state,
        fence=fence,
        suspect_after=suspect_after,
        unavailable_after=unavailable_after,
    )


def _server(address: str, concurrency: int, security: RpcSecurity | None) -> tuple[Any, int]:
    server = grpc.server(
        ThreadPoolExecutor(max_workers=concurrency),
        options=CHANNEL_OPTIONS,
        maximum_concurrent_rpcs=concurrency,
        interceptors=[ServerAuth(security)] if security is not None else [],
    )
    if security is not None and security.certificate:
        credentials = grpc.ssl_server_credentials(
            [(security.private_key, security.certificate)],
            root_certificates=security.ca,
            require_client_auth=security.require_client_certificate,
        )
        port = server.add_secure_port(address, credentials)
    else:
        if security is not None and security.ca:
            raise ValueError("TLS service requires a certificate and private key")
        port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"Could not bind gRPC server to {address}")
    return server, port


def coordinator_server(
    coordinator: Coordinator, address: str, *, security: RpcSecurity | None = None
) -> tuple[Any, int]:
    server, port = _server(address, 8, security)
    rpc.add_CoordinatorServicer_to_server(CoordinatorService(coordinator), server)
    return server, port


def shard_server(
    shard: ParameterShard, address: str, *, security: RpcSecurity | None = None
) -> tuple[Any, int]:
    # Waiting synchronous RPCs must not occupy every thread and starve the final participant.
    server, port = _server(address, 2 * len(shard.config.worker_ids) + 4, security)
    rpc.add_ParameterShardServicer_to_server(ShardService(shard), server)
    return server, port
